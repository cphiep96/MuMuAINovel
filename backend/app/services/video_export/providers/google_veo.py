"""Google Veo (Gemini API) 适配器

API（参考 https://ai.google.dev/gemini-api/docs/veo）：
1. `POST {base}/models/{model}:predictLongRunning`
   Header: `x-goog-api-key: $GEMINI_API_KEY`
   Body: `{"instances": [{"prompt": "...", "image": {"bytesBase64Encoded": "...", "mimeType": "image/png"}}],
           "parameters": {"aspectRatio": "16:9", "durationSeconds": 8, "resolution": "720p",
                          "negativePrompt": "...", "sampleCount": 1, "personGeneration": "allow_adult"}}`
   Response: `{"name": "models/veo-.../operations/xxx"}`
2. `GET {base}/{operation_name}`（例如 `models/veo-3.1-generate-preview/operations/abc`）
   Response: `{"done": true, "response": {"generateVideoResponse": {"generatedSamples": [{"video": {"uri": "..."}}]}}}`
   失败时携带 `{"error": {"code": ..., "message": "..."}}`
3. 下载 `video.uri`：同一 `googleapis.com` 主机，需要 `x-goog-api-key` 头。

说明：
- 时长/分辨率按模型区分：Veo 3.1 (generate/fast/lite) 只生成 8 秒视频（720p/1080p，4k 仅 generate/fast），
  Veo 2.0 支持 5–8 秒与 720p；`durationSeconds` 会按模型夹取，非法组合（如 Lite + 4k）在提交前报错
- operation 资源名在提交与轮询前都会做严格校验（`validate_operation_name`），防止把 provider 返回值
  直接拼进 URL 造成 SSRF/凭证泄漏
- 该 API 未提供取消端点，`supports_cancel = False`，取消只停止轮询与下载
"""
from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings
from app.services.video_export.providers.base import (
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    CancelCheck,
    MotionOperation,
    MotionReference,
    MotionRequest,
    ProviderConfigState,
    RemoteMotionProvider,
)
from app.services.video_export.providers.errors import MotionProviderError, MotionRequestError
from app.services.video_export.providers.http_utils import (
    download_to_path,
    extract_error_message,
    raise_for_status,
    request_with_retries,
)

MISSING_KEY_HINT = "VIDEO_MOTION_GEMINI_API_KEY"
NEGATIVE_PROMPT = "blurry, watermark, text overlay, low quality, distorted, extra limbs"

# docs 规定的 operation 资源名：`models/<model>/operations/<id>`
OPERATION_NAME_PATTERN = re.compile(r"^models/(?P<model>[A-Za-z0-9._-]+)/operations/(?P<operation>[A-Za-z0-9._-]+)$")


def validate_operation_name(name: object, *, expected_model: str) -> str:
    """严格校验 Veo 的 operation 资源名，避免把 provider/DB 提供的值直接拼进 URL

    - 只接受 `models/<model>/operations/<id>` 两段固定结构（无 `://`、无 `/` 多余层级、
      无 `..`、无查询/片段、无编码字符、无空白）
    - `<model>` 必须与本次请求的 model 一致，或在其后追加合法后缀（例如版本号
      `veo-3.1-generate-preview-001`），避免用其它模型/服务的 operation 冒充
    - 失败时抛 `MotionProviderError`，消息不含 API key，也不回显可疑内容
    """
    raw = str(name or "").strip()
    if not raw or len(raw) > 300:
        raise MotionProviderError("Google Veo trả về tên operation không hợp lệ")
    if "://" in raw or "\\" in raw or ".." in raw or raw.startswith("/"):
        raise MotionProviderError(
            "Google Veo trả về tên operation không hợp lệ (không được là URL tuyệt đối hoặc chứa '..')"
        )
    if any(char.isspace() or ord(char) < 0x20 for char in raw):
        raise MotionProviderError("Google Veo trả về tên operation chứa ký tự điều khiển")

    match = OPERATION_NAME_PATTERN.match(raw)
    if match is None:
        raise MotionProviderError(
            "Google Veo trả về tên operation không đúng định dạng 'models/<model>/operations/<id>'"
        )

    model, operation = match.group("model"), match.group("operation")
    if not re.search(r"[A-Za-z0-9]", operation):
        raise MotionProviderError("Google Veo trả về mã operation rỗng hoặc không hợp lệ")

    expected = str(expected_model or "").strip()
    if expected and not (model == expected or model.startswith(expected)):
        raise MotionProviderError(
            "Operation của Google Veo thuộc model khác với model đã yêu cầu, đã từ chối gọi endpoint"
        )
    return raw


def _as_instance_image(reference: MotionReference) -> dict:
    if not reference.path.is_file():
        raise MotionRequestError("Ảnh tham chiếu cho provider không còn tồn tại trên máy chủ")
    payload = base64.b64encode(reference.path.read_bytes()).decode("ascii")
    return {"bytesBase64Encoded": payload, "mimeType": reference.mime_type}


def _extract_video_uri(payload: dict) -> Optional[str]:
    """从 operation 响应里找出视频下载地址（不同版本字段位置略有差异）"""
    response = payload.get("response")
    if not isinstance(response, dict):
        return None
    containers = [
        response.get("generateVideoResponse"),
        response.get("generate_video_response"),
        response,
    ]
    for container in containers:
        if not isinstance(container, dict):
            continue
        samples = container.get("generatedSamples") or container.get("generated_samples")
        if isinstance(samples, list) and samples:
            first = samples[0]
            if isinstance(first, dict):
                video = first.get("video") if isinstance(first.get("video"), dict) else first
                uri = str(video.get("uri") or video.get("gcsUri") or "").strip()
                if uri:
                    return uri
        videos = container.get("videos")
        if isinstance(videos, list) and videos and isinstance(videos[0], dict):
            uri = str(videos[0].get("uri") or videos[0].get("gcsUri") or "").strip()
            if uri:
                return uri
    return None


class GoogleVeoProvider(RemoteMotionProvider):
    name = "google_veo"
    label = "Google Veo (Gemini API)"
    description = "Image-to-video qua Gemini API: ảnh phân cảnh làm khung đầu, video có âm thanh gốc của Veo."
    models = (
        "veo-3.1-generate-preview",
        "veo-3.1-fast-generate-preview",
        "veo-3.1-lite-generate-preview",
        "veo-2.0-generate-001",
    )
    default_model = "veo-3.1-generate-preview"
    supports_placeholder = False
    supports_cancel = False
    supports_idempotency = False
    aspect_ratios = ("16:9", "9:16")

    # 按模型区分限制（Gemini API 文档）：
    # - Veo 3.1 (generate/fast/lite): video 8 giây; 720p/1080p; 4k có trên generate/fast (không có trên Lite)
    #   và chỉ với clip 8 giây → 3.1 luôn gửi durationSeconds = 8
    # - Veo 2.0: 5–8 giây, 720p
    MODEL_LIMITS: dict[str, dict] = {
        "veo-3.1-generate-preview": {
            "min_duration_seconds": 8.0,
            "max_duration_seconds": 8.0,
            "duration_options": [8.0],
            "aspect_ratios": ["16:9", "9:16"],
            "resolutions": ["720p", "1080p", "4k"],
            "default_resolution": "720p",
        },
        "veo-3.1-fast-generate-preview": {
            "min_duration_seconds": 8.0,
            "max_duration_seconds": 8.0,
            "duration_options": [8.0],
            "aspect_ratios": ["16:9", "9:16"],
            "resolutions": ["720p", "1080p", "4k"],
            "default_resolution": "720p",
        },
        "veo-3.1-lite-generate-preview": {
            "min_duration_seconds": 8.0,
            "max_duration_seconds": 8.0,
            "duration_options": [8.0],
            "aspect_ratios": ["16:9", "9:16"],
            "resolutions": ["720p", "1080p"],
            "default_resolution": "720p",
        },
        "veo-2.0-generate-001": {
            "min_duration_seconds": 5.0,
            "max_duration_seconds": 8.0,
            "duration_options": [5.0, 6.0, 7.0, 8.0],
            "aspect_ratios": ["16:9", "9:16"],
            "resolutions": ["720p"],
            "default_resolution": "720p",
        },
    }
    # 类属性仅作为兜底（真正的限制由 model_limits 决定）
    min_duration_seconds = 8.0
    max_duration_seconds = 8.0
    duration_options = (8.0,)
    resolutions = ("720p", "1080p", "4k")
    default_resolution = "720p"
    cost_note = (
        "Tính phí theo giây video và độ phân giải (Gemini API). Veo 3.1 luôn tạo clip 8 giây; "
        "1080p/4k đắt hơn 720p, 4k không có trên Veo 3.1 Lite."
    )

    def __init__(self, *, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None, transport=None) -> None:
        super().__init__(transport=transport)
        self.api_key = (api_key if api_key is not None else settings.video_motion_gemini_api_key or "").strip()
        self.base_url = (base_url or settings.video_motion_gemini_base_url or "").rstrip("/")
        self.model = (model or settings.video_motion_gemini_model or self.default_model).strip()

    def model_limits(self, model: Optional[str] = None) -> dict:
        """按模型返回限制；未知模型回落到 Veo 3.1 的保守限制（8 秒/720p）"""
        key = str(model or self.model or self.default_model).strip()
        limits = self.MODEL_LIMITS.get(key) or self.MODEL_LIMITS[self.default_model]
        return {
            "min_duration_seconds": limits["min_duration_seconds"],
            "max_duration_seconds": limits["max_duration_seconds"],
            "duration_options": list(limits["duration_options"]),
            "aspect_ratios": list(limits["aspect_ratios"]),
            "resolutions": list(limits["resolutions"]),
            "default_resolution": limits["default_resolution"],
        }

    # ---------------------------------------------------------------- 配置

    def configuration(self) -> ProviderConfigState:
        missing = []
        if not self.api_key:
            missing.append(MISSING_KEY_HINT)
        if not self.base_url:
            missing.append("VIDEO_MOTION_GEMINI_BASE_URL")
        if missing:
            return ProviderConfigState(
                configured=False,
                missing_config=tuple(missing),
                detail="Thiếu cấu hình Google Veo: cần API key của Gemini API (hoặc Vertex AI).",
            )
        return ProviderConfigState(configured=True)

    # ---------------------------------------------------------------- HTTP

    def _headers(self) -> dict[str, str]:
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    @property
    def _provider_host(self) -> str:
        return httpx.URL(self.base_url).host or ""

    def _build_body(self, request: MotionRequest) -> dict:
        if request.reference is None or request.reference.is_placeholder:
            raise MotionRequestError(
                "Provider google_veo yêu cầu ảnh tham chiếu, không nhận ảnh placeholder"
            )
        model = self.normalize_model(request.model)
        limits = self.model_limits(model)
        duration = int(round(self.clamp_duration(request.duration_seconds, model)))
        options = limits.get("duration_options") or []
        if options and duration not in options:
            raise MotionRequestError(
                f"Model {model} chỉ nhận video {', '.join(str(int(item)) for item in options)} giây "
                f"(đang yêu cầu {duration} giây)"
            )
        resolution = self.normalize_resolution(request.resolution or limits["default_resolution"], model)
        if resolution in ("1080p", "4k") and duration != 8:
            raise MotionRequestError(
                f"Veo chỉ hỗ trợ độ phân giải {resolution} với video 8 giây (đang yêu cầu {duration} giây)"
            )
        parameters: dict = {
            "aspectRatio": request.aspect_ratio,
            "durationSeconds": duration,
            "resolution": resolution,
            "negativePrompt": request.negative_prompt or NEGATIVE_PROMPT,
            "sampleCount": 1,
            "personGeneration": settings.video_motion_veo_person_generation,
        }
        instance: dict = {"image": _as_instance_image(request.reference)}
        if request.prompt:
            instance["prompt"] = request.prompt
        return {"instances": [instance], "parameters": parameters}

    async def _submit(
        self, request: MotionRequest, cancel_check: Optional[CancelCheck] = None
    ) -> MotionOperation:
        model = self.normalize_model(request.model)
        body = self._build_body(request)
        url = f"{self.base_url}/models/{model}:predictLongRunning"
        async with httpx.AsyncClient(transport=self._transport, timeout=self._http_timeout()) as client:
            response = await request_with_retries(
                client, "POST", url, json=body, headers=self._headers(), cancel_check=cancel_check
            )
        raise_for_status(response, provider=self.name)
        data = _json_object(response, provider=self.name)
        # 提交时立即校验：绝不把未校验的 provider 返回值存库/拼进后续 URL
        operation_name = validate_operation_name(
            data.get("name"), expected_model=model
        ) if str(data.get("name") or "").strip() else ""
        if not operation_name:
            raise MotionProviderError("Google Veo không trả về tên operation")
        return MotionOperation(
            provider=self.name, model=model, operation_id=operation_name, status=STATUS_PENDING
        )

    async def _poll(
        self, operation: MotionOperation, cancel_check: Optional[CancelCheck] = None
    ) -> MotionOperation:
        # 轮询（包含重启后的 resume）前再次校验，防止 DB 中被篡改的值改变请求目标
        expected_model = operation.model or self.model or self.default_model
        operation_name = validate_operation_name(operation.operation_id, expected_model=expected_model)
        url = f"{self.base_url}/{operation_name}"
        async with httpx.AsyncClient(transport=self._transport, timeout=self._http_timeout()) as client:
            response = await request_with_retries(
                client, "GET", url, headers=self._headers(), cancel_check=cancel_check
            )
        raise_for_status(response, provider=self.name)
        data = _json_object(response, provider=self.name)

        if isinstance(data.get("error"), dict):
            operation.status = STATUS_FAILED
            operation.failure_reason = (
                extract_error_message(data) or "Google Veo báo lỗi khi tạo video"
            )
            return operation

        if data.get("done") is True:
            uri = _extract_video_uri(data)
            if uri:
                operation.status = STATUS_COMPLETED
                operation.download_url = uri
                operation.progress = 100
            else:
                operation.status = STATUS_FAILED
                operation.failure_reason = "Google Veo hoàn tất nhưng không trả về URI video"
            return operation

        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        progress = metadata.get("progressPercent")
        if isinstance(progress, (int, float)):
            operation.progress = int(max(0, min(int(progress), 100)))
        operation.status = STATUS_RUNNING
        return operation

    async def _download(
        self,
        operation: MotionOperation,
        out_path: Path,
        *,
        cancel_check: Optional[CancelCheck] = None,
        timeout: Optional[float] = None,
    ) -> int:
        if not operation.download_url:
            raise MotionProviderError("Không có URI tải video từ Google Veo")
        max_bytes = int(settings.video_motion_max_clip_mb) * 1024 * 1024
        async with httpx.AsyncClient(transport=self._transport, timeout=timeout or 300.0) as client:
            return await download_to_path(
                client,
                operation.download_url,
                out_path,
                max_bytes=max_bytes,
                headers=dict(self._headers()),
                provider_host=self._provider_host,
                cancel_check=cancel_check,
            )


def _json_object(response: httpx.Response, *, provider: str) -> dict:
    try:
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - provider 返回非 JSON
        raise MotionProviderError(f"{provider} trả về dữ liệu không phải JSON") from exc
    if not isinstance(data, dict):
        raise MotionProviderError(f"{provider} trả về dữ liệu không đúng định dạng")
    return data
