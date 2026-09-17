"""OpenAI 兼容视频适配器（generic）

适用于实现 OpenAI Videos API 的服务（OpenAI Sora、以及兼容网关/自建服务）：
1. `POST {base}/videos`（`multipart/form-data`）
   Header: `Authorization: Bearer $OPENAI_API_KEY`（可选 `Idempotency-Key`）
   Fields: `model`, `prompt`, `size`（如 `1280x720`）、`seconds`（`4`/`8`/`12`）、
           `input_reference`（首帧图片文件，需与 `size` 匹配）
   Response: `{"id": "video_...", "status": "queued|in_progress|completed|failed", "progress": 0}`
2. `GET {base}/videos/{id}` → 同上，失败时带 `error`
3. `GET {base}/videos/{id}/content` → MP4 字节流

说明：
- `input_reference` 必须存在（本适配器按 image-to-video 使用），placeholder 会被拒绝
- 分辨率按模型区分：`sora-2` 仅 720p，`sora-2-pro` 额外支持 1024p（`1024p` 需要 Pro，否则提前报错）
- `size` 只能取 Videos API 白名单值（1280x720 / 720x1280 / 1792x1024 / 1024x1792），不做算术推导
- provider 返回的 video id 在存储与轮询前都会做严格校验，避免被篡改后改变请求目标
- 该 API 未提供取消端点，`supports_cancel = False`
- `seconds` 只接受 4/8/12，超出范围时分镜时长会被夹到最近的合法值
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

import httpx

from app.config import settings
from app.services.video_export import ffmpeg_runner
from app.services.video_export.assets import guess_image_mime
from app.services.video_export.providers.base import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_FAILED,
    STATUS_PENDING,
    STATUS_RUNNING,
    CancelCheck,
    MotionOperation,
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
    sanitize_path_token,
)

_STATUS_MAP = {
    "queued": STATUS_PENDING,
    "pending": STATUS_PENDING,
    "in_progress": STATUS_RUNNING,
    "processing": STATUS_RUNNING,
    "running": STATUS_RUNNING,
    "completed": STATUS_COMPLETED,
    "succeeded": STATUS_COMPLETED,
    "failed": STATUS_FAILED,
    "error": STATUS_FAILED,
    "cancelled": STATUS_CANCELLED,
    "canceled": STATUS_CANCELLED,
}


class OpenAICompatibleVideoProvider(RemoteMotionProvider):
    name = "openai_compatible"
    label = "OpenAI compatible (Videos API)"
    description = "Gọi API video tương thích OpenAI (/videos): phù hợp Sora hoặc gateway tự dựng cùng hợp đồng."
    models = ("sora-2", "sora-2-pro")
    default_model = "sora-2"
    supports_placeholder = False
    supports_cancel = False
    supports_idempotency = True
    aspect_ratios = ("16:9", "9:16")

    # 按模型区分限制（OpenAI Videos API）：Sora 2 仅 720p，Sora 2 Pro 额外支持 1024p
    MODEL_LIMITS: dict[str, dict] = {
        "sora-2": {
            "min_duration_seconds": 4.0,
            "max_duration_seconds": 12.0,
            "duration_options": [4.0, 8.0, 12.0],
            "aspect_ratios": ["16:9", "9:16"],
            "resolutions": ["720p"],
            "default_resolution": "720p",
        },
        "sora-2-pro": {
            "min_duration_seconds": 4.0,
            "max_duration_seconds": 12.0,
            "duration_options": [4.0, 8.0, 12.0],
            "aspect_ratios": ["16:9", "9:16"],
            "resolutions": ["720p", "1024p"],
            "default_resolution": "720p",
        },
    }
    # 类属性仅作为兜底（真实限制由 model_limits 决定）
    min_duration_seconds = 4.0
    max_duration_seconds = 12.0
    duration_options = (4.0, 8.0, 12.0)
    resolutions = ("720p",)
    default_resolution = "720p"
    cost_note = (
        "Tính phí theo giây video (OpenAI Sora tính theo giây × độ phân giải). "
        "Mỗi phân cảnh là một lần gọi API có tính phí."
    )
    request_timeout_seconds = None

    # OpenAI Videos API 只接受固定像素尺寸（不能用算术推导），按 (分辨率 token, 比例) 白名单映射
    SIZE_MAP: dict[tuple[str, str], str] = {
        ("720p", "16:9"): "1280x720",
        ("720p", "9:16"): "720x1280",
        ("1024p", "16:9"): "1792x1024",
        ("1024p", "9:16"): "1024x1792",
    }

    def model_limits(self, model: Optional[str] = None) -> dict:
        """按模型返回限制；未知模型回落到默认模型（保守：仅 720p）"""
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

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        transport=None,
    ) -> None:
        super().__init__(transport=transport)
        self.api_key = (api_key if api_key is not None else settings.video_motion_openai_api_key or "").strip()
        self.base_url = (base_url or settings.video_motion_openai_base_url or "").rstrip("/")
        self.model = (model or settings.video_motion_openai_model or self.default_model).strip()

    # ---------------------------------------------------------------- 配置

    def configuration(self) -> ProviderConfigState:
        missing = []
        if not self.api_key:
            missing.append("VIDEO_MOTION_OPENAI_API_KEY")
        if not self.base_url:
            missing.append("VIDEO_MOTION_OPENAI_BASE_URL")
        if missing:
            return ProviderConfigState(
                configured=False,
                missing_config=tuple(missing),
                detail="Thiếu cấu hình provider OpenAI compatible: cần base URL và API key.",
            )
        return ProviderConfigState(configured=True)

    # ---------------------------------------------------------------- HTTP

    def _headers(self, *, idempotency_key: Optional[str] = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    @property
    def _provider_host(self) -> str:
        return httpx.URL(self.base_url).host or ""

    def _target_pixels(self, request: MotionRequest) -> tuple[int, int]:
        model = self.normalize_model(request.model)
        limits = self.model_limits(model)
        resolution = self.normalize_resolution(request.resolution or limits["default_resolution"], model)
        size = self.SIZE_MAP.get((resolution, request.aspect_ratio))
        if size is None:
            raise MotionRequestError(
                f"Tổ hợp {resolution}/{request.aspect_ratio} không có kích thước hợp lệ cho model {model} "
                f"(hỗ trợ: {', '.join(sorted(self.SIZE_MAP.values()))})"
            )
        width, height = size.split("x", 1)
        return int(width), int(height)

    def _pixel_size(self, request: MotionRequest) -> tuple[str, str]:
        """把统一的分辨率 token 映射为 OpenAI Videos API 接受的 `size` 与 `seconds`"""
        width, height = self._target_pixels(request)
        model = self.normalize_model(request.model)
        seconds = str(int(round(self.clamp_duration(request.duration_seconds, model))))
        return f"{width}x{height}", seconds

    def _reference_path_for_size(self, request: MotionRequest, width: int, height: int) -> Path:
        """input_reference 必须与 `size` 完全一致：必要时用 FFmpeg 生成等比缩放的副本

        副本写在受管素材目录内（与源图同目录），失败时抛出明确错误，绝不提交尺寸不符的请求。
        """
        source = request.reference.path if request.reference else None
        if source is None or not source.is_file():
            raise MotionRequestError("Ảnh tham chiếu cho provider không còn tồn tại trên máy chủ")
        actual = ffmpeg_runner.probe_image_size(source)
        if actual == (width, height):
            return source
        target = source.with_name(f"{source.stem}_ai_{width}x{height}{source.suffix or '.png'}")
        if target.is_file() and ffmpeg_runner.probe_image_size(target) == (width, height):
            return target
        try:
            ffmpeg_runner.resize_image_cover(source, target, width=width, height=height)
        except ffmpeg_runner.FFmpegUnavailableError as exc:
            raise MotionRequestError(
                "Provider yêu cầu ảnh tham chiếu khớp chính xác kích thước video "
                f"({width}x{height}) nhưng máy chủ không có FFmpeg để resize ảnh"
            ) from exc
        except ffmpeg_runner.FFmpegExecutionError as exc:
            raise MotionRequestError(
                f"Không thể resize ảnh tham chiếu về {width}x{height} để gửi provider: {exc}"
            ) from exc
        return target

    async def _submit(
        self, request: MotionRequest, cancel_check: Optional[CancelCheck] = None
    ) -> MotionOperation:
        model = self.normalize_model(request.model)
        if request.reference is None or request.reference.is_placeholder:
            raise MotionRequestError(
                "Provider openai_compatible yêu cầu ảnh tham chiếu (input_reference), không nhận placeholder"
            )
        if not request.reference.path.is_file():
            raise MotionRequestError("Ảnh tham chiếu cho provider không còn tồn tại trên máy chủ")

        size, seconds = self._pixel_size(request)
        width, height = self._target_pixels(request)
        reference_path = self._reference_path_for_size(request, width, height)
        data = {"model": model, "prompt": request.prompt, "size": size, "seconds": seconds}
        files = {
            "input_reference": (
                reference_path.name,
                reference_path.read_bytes(),
                guess_image_mime(reference_path),
            )
        }
        url = f"{self.base_url}/videos"
        idempotency_key = request.idempotency_key if self.supports_idempotency else None
        async with httpx.AsyncClient(transport=self._transport, timeout=self._http_timeout()) as client:
            response = await request_with_retries(
                client,
                "POST",
                url,
                data=data,
                files=files,
                headers=self._headers(idempotency_key=idempotency_key),
                cancel_check=cancel_check,
            )
        raise_for_status(response, provider=self.name)
        payload = _json_object(response, provider=self.name)
        raw_id = str(payload.get("id") or "").strip()
        if not raw_id:
            raise MotionProviderError("Provider không trả về id video")
        # id 会拼进后续 URL 路径：严格校验后再存储
        video_id = sanitize_path_token(raw_id, provider=self.name, label="video id")
        return MotionOperation(
            provider=self.name,
            model=model,
            operation_id=video_id,
            status=_STATUS_MAP.get(str(payload.get("status") or "").lower(), STATUS_PENDING),
            progress=_as_progress(payload.get("progress")),
        )

    async def _poll(
        self, operation: MotionOperation, cancel_check: Optional[CancelCheck] = None
    ) -> MotionOperation:
        # 轮询（包含重启后的 resume）前再次校验，防止 DB 中被篡改的值改变请求目标
        video_id = sanitize_path_token(operation.operation_id, provider=self.name, label="video id")
        url = f"{self.base_url}/videos/{video_id}"
        async with httpx.AsyncClient(transport=self._transport, timeout=self._http_timeout()) as client:
            response = await request_with_retries(
                client, "GET", url, headers=self._headers(), cancel_check=cancel_check
            )
        raise_for_status(response, provider=self.name)
        payload = _json_object(response, provider=self.name)
        operation.status = _STATUS_MAP.get(str(payload.get("status") or "").lower(), STATUS_RUNNING)
        operation.progress = _as_progress(payload.get("progress"))
        if operation.status == STATUS_COMPLETED:
            operation.download_url = f"{self.base_url}/videos/{video_id}/content"
        elif operation.status == STATUS_FAILED:
            operation.failure_reason = (
                extract_error_message(payload) or "Provider báo tạo video thất bại"
            )
        return operation

    async def _download(
        self,
        operation: MotionOperation,
        out_path: Path,
        *,
        cancel_check: Optional[CancelCheck] = None,
        timeout: Optional[float] = None,
    ) -> int:
        if operation.download_url:
            url = operation.download_url
        else:
            video_id = sanitize_path_token(operation.operation_id, provider=self.name, label="video id")
            url = f"{self.base_url}/videos/{video_id}/content"
        max_bytes = int(settings.video_motion_max_clip_mb) * 1024 * 1024
        async with httpx.AsyncClient(transport=self._transport, timeout=timeout or 300.0) as client:
            return await download_to_path(
                client,
                url,
                out_path,
                max_bytes=max_bytes,
                headers=dict(self._headers()),
                provider_host=self._provider_host,
                cancel_check=cancel_check,
            )


def _as_progress(value: object) -> Optional[int]:
    if isinstance(value, (int, float)):
        return int(max(0, min(int(value), 100)))
    return None


def _json_object(response: httpx.Response, *, provider: str) -> dict:
    try:
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - provider 返回非 JSON
        raise MotionProviderError(f"{provider} trả về dữ liệu không phải JSON") from exc
    if not isinstance(data, dict):
        raise MotionProviderError(f"{provider} trả về dữ liệu không đúng định dạng")
    return data
