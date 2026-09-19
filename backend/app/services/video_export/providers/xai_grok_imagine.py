"""xAI Grok Imagine 视频适配器（image-to-video）

API（参考 https://docs.x.ai/developers/rest-api-reference/inference/videos）：
1. `POST {base}/videos/generations`
   Header: `Authorization: Bearer $XAI_API_KEY`, `Content-Type: application/json`
   Body: `{"model": "...", "prompt": "...", "image": {"url": "data:image/png;base64,..."},
           "duration": 8, "aspect_ratio": "16:9", "resolution": "720p", "generate_audio": false}`
   Response: `{"request_id": "..."}`
2. `GET {base}/videos/{request_id}` → `{"status": "pending|done|failed|expired", "progress": 0-99,
   "video": {"url": "https://.../video.mp4", "duration": 8}, "error": {...}}`
3. 下载 `video.url`（远端 CDN，只做 SSRF 校验，且**不携带 API key**）

说明：该 API 未提供取消端点，因此 `supports_cancel = False`；取消只停止轮询/下载，
远端任务可能仍会继续执行并计费。
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Optional

import httpx

from app.config import settings
from app.services.video_export.providers.base import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
    STATUS_EXPIRED,
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
    sanitize_path_token,
)

MISSING_KEY_HINT = "VIDEO_MOTION_XAI_API_KEY"

_STATUS_MAP = {
    "pending": STATUS_PENDING,
    "queued": STATUS_PENDING,
    "in_progress": STATUS_RUNNING,
    "running": STATUS_RUNNING,
    "processing": STATUS_RUNNING,
    "done": STATUS_COMPLETED,
    "completed": STATUS_COMPLETED,
    "succeeded": STATUS_COMPLETED,
    "success": STATUS_COMPLETED,
    "failed": STATUS_FAILED,
    "error": STATUS_FAILED,
    "expired": STATUS_EXPIRED,
    "canceled": STATUS_CANCELLED,
    "cancelled": STATUS_CANCELLED,
}


def _as_data_uri(reference: MotionReference) -> str:
    if not reference.path.is_file():
        raise MotionRequestError("Ảnh tham chiếu cho provider không còn tồn tại trên máy chủ")
    payload = base64.b64encode(reference.path.read_bytes()).decode("ascii")
    return f"data:{reference.mime_type};base64,{payload}"


class XaiGrokImagineProvider(RemoteMotionProvider):
    name = "xai_grok_imagine"
    label = "xAI Grok Imagine (video)"
    description = "Image-to-video qua xAI Grok Imagine: gửi ảnh phân cảnh làm khung đầu và mô tả chuyển động."
    models = ("grok-imagine-video-1.5", "grok-imagine-video")
    default_model = "grok-imagine-video-1.5"
    supports_placeholder = False
    supports_cancel = False
    supports_idempotency = False
    min_duration_seconds = 1.0
    max_duration_seconds = 15.0
    # API 接受 1–15 秒的整数，因此不做固定档位裁剪，只做区间夹取
    duration_options: tuple[float, ...] = ()
    aspect_ratios = ("16:9", "9:16", "1:1")
    resolutions = ("480p", "720p", "1080p")
    default_resolution = "720p"
    cost_note = (
        "Tính phí theo giây video và độ phân giải (xem bảng giá xAI). "
        "Mỗi phân cảnh là một lần gọi API có tính phí."
    )

    def __init__(self, *, api_key: Optional[str] = None, base_url: Optional[str] = None, model: Optional[str] = None, transport=None) -> None:
        super().__init__(transport=transport)
        self.api_key = (api_key if api_key is not None else settings.video_motion_xai_api_key or "").strip()
        self.base_url = (base_url or settings.video_motion_xai_base_url or "").rstrip("/")
        self.model = (model or settings.video_motion_xai_model or self.default_model).strip()

    # ---------------------------------------------------------------- 配置

    def configuration(self) -> ProviderConfigState:
        missing = []
        if not self.api_key:
            missing.append(MISSING_KEY_HINT)
        if not self.base_url:
            missing.append("VIDEO_MOTION_XAI_BASE_URL")
        if missing:
            return ProviderConfigState(
                configured=False,
                missing_config=tuple(missing),
                detail="Thiếu cấu hình xAI Grok Imagine: cần API key và base URL của xAI.",
            )
        return ProviderConfigState(configured=True)

    def normalize_model(self, value: Optional[str]) -> str:
        return super().normalize_model(value or self.model)

    # ---------------------------------------------------------------- HTTP

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @property
    def _provider_host(self) -> str:
        return httpx.URL(self.base_url).host or ""

    def _build_payload(self, request: MotionRequest) -> dict:
        model = self.normalize_model(request.model)
        payload: dict = {
            "model": model,
            "duration": int(round(self.clamp_duration(request.duration_seconds, model))),
            "aspect_ratio": request.aspect_ratio,
            "resolution": self.normalize_resolution(request.resolution, model),
            "generate_audio": bool(settings.video_motion_xai_generate_audio),
        }
        if request.prompt:
            payload["prompt"] = request.prompt
        if request.reference is not None:
            if request.reference.is_placeholder:
                raise MotionRequestError(
                    "Provider xai_grok_imagine yêu cầu ảnh tham chiếu, không nhận ảnh placeholder"
                )
            payload["image"] = {"url": _as_data_uri(request.reference)}
        else:
            raise MotionRequestError(
                "Provider xai_grok_imagine yêu cầu ảnh tham chiếu cho phân cảnh (image-to-video)"
            )
        return payload

    async def _submit(
        self, request: MotionRequest, cancel_check: Optional[CancelCheck] = None
    ) -> MotionOperation:
        payload = self._build_payload(request)
        async with httpx.AsyncClient(transport=self._transport, timeout=self._http_timeout()) as client:
            response = await request_with_retries(
                client,
                "POST",
                f"{self.base_url}/videos/generations",
                json=payload,
                headers=self._headers(),
                cancel_check=cancel_check,
            )
        raise_for_status(response, provider=self.name)
        data = _json_object(response)
        raw_id = str(data.get("request_id") or data.get("id") or "").strip()
        if not raw_id:
            raise MotionProviderError("xAI không trả về request_id cho tác vụ video")
        operation_id = sanitize_path_token(raw_id, provider=self.name, label="request_id")
        return MotionOperation(
            provider=self.name,
            model=str(payload.get("model") or self.default_model),
            operation_id=operation_id,
            status=STATUS_PENDING,
        )

    async def _poll(
        self, operation: MotionOperation, cancel_check: Optional[CancelCheck] = None
    ) -> MotionOperation:
        # request_id 会拼进 URL 路径：先严格校验，防止被篡改的值改变请求目标
        request_id = sanitize_path_token(
            operation.operation_id, provider=self.name, label="request_id"
        )
        async with httpx.AsyncClient(transport=self._transport, timeout=self._http_timeout()) as client:
            response = await request_with_retries(
                client,
                "GET",
                f"{self.base_url}/videos/{request_id}",
                headers=self._headers(),
                cancel_check=cancel_check,
            )
        raise_for_status(response, provider=self.name)
        data = _json_object(response)
        raw_status = str(data.get("status") or "").lower()
        operation.status = _STATUS_MAP.get(raw_status, STATUS_RUNNING)
        progress = data.get("progress")
        if isinstance(progress, (int, float)):
            operation.progress = int(max(0, min(int(progress), 100)))
        video = data.get("video") if isinstance(data.get("video"), dict) else {}
        operation.download_url = str(video.get("url") or "").strip() or None
        if operation.status == STATUS_COMPLETED and not operation.download_url:
            operation.status = STATUS_FAILED
            operation.failure_reason = "xAI báo hoàn tất nhưng không trả về địa chỉ video"
        if operation.status in (STATUS_FAILED, STATUS_EXPIRED):
            operation.failure_reason = (
                extract_error_message(data) or f"xAI kết thúc với trạng thái {raw_status or 'unknown'}"
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
        if not operation.download_url:
            raise MotionProviderError("Không có địa chỉ tải video từ xAI")
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


def _json_object(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except Exception as exc:  # noqa: BLE001 - provider 返回非 JSON
        raise MotionProviderError("xAI trả về dữ liệu không phải JSON") from exc
    if not isinstance(data, dict):
        raise MotionProviderError("xAI trả về dữ liệu không đúng định dạng")
    return data
