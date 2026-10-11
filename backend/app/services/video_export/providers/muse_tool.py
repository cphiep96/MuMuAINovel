"""Muse Tool's authenticated localhost video API (text-to-video)."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.services.video_export.providers.base import (
    CancelCheck, MotionOperation, MotionRequest, ProviderConfigState,
    RemoteMotionProvider, STATUS_PENDING, STATUS_RUNNING, STATUS_COMPLETED, STATUS_FAILED,
)
from app.services.video_export.providers.errors import (
    MotionProviderError, MotionRequestError, MotionTimeoutError, sanitize_message,
)
from app.services.video_export.providers.http_utils import (
    download_to_path, request_with_retries, raise_for_status,
)

_STATUSES = {
    "waiting": STATUS_PENDING, "connecting": STATUS_RUNNING,
    "running": STATUS_RUNNING, "done": STATUS_COMPLETED, "error": STATUS_FAILED,
}


class MuseToolVideoProvider(RemoteMotionProvider):
    name = "muse_tool"
    label = "Muse Tool (local)"
    description = "Tạo video từ prompt qua Muse Tool trên cùng máy; mỗi phân cảnh dùng một chat riêng."
    models = ("muse-video",)
    default_model = "muse-video"
    supports_placeholder = True
    supports_cancel = False
    supports_idempotency = True
    min_duration_seconds = 5.0
    max_duration_seconds = 15.0
    duration_options = (5.0, 10.0, 15.0)
    aspect_ratios = ("16:9", "9:16", "1:1", "4:3", "3:4")
    resolutions = ("auto",)
    default_resolution = "auto"
    cost_note = (
        "Dùng hạn mức tài khoản Muse đang đăng nhập trong Muse Tool. "
        "Tạo từ prompt, chưa gửi ảnh tham chiếu. Có thể ghép một giọng kể TTS riêng; Muse quyết định độ phân giải thực tế; "
        "tỉ lệ và thời lượng là yêu cầu. Hủy ở đây chỉ dừng theo dõi, tác vụ Muse vẫn có thể chạy."
    )

    def __init__(self, *, api_key: Optional[str] = None, base_url: Optional[str] = None,
                 config_file: Optional[str] = None, transport=None) -> None:
        super().__init__(transport=transport)
        self._config_error = None
        configured_file = config_file if config_file is not None else settings.video_motion_muse_config_file
        local_config = {}
        if configured_file and api_key is None and not settings.video_motion_muse_api_key:
            try:
                local_config = json.loads(Path(configured_file).read_text(encoding="utf-8-sig"))
                if not isinstance(local_config, dict):
                    raise ValueError("Expected object")
            except (OSError, ValueError):
                self._config_error = "Không đọc được cấu hình Muse Tool; kiểm tra VIDEO_MOTION_MUSE_CONFIG_FILE."
        raw_key = api_key if api_key is not None else settings.video_motion_muse_api_key or local_config.get("apiKey", "")
        self.api_key = raw_key.strip() if isinstance(raw_key, str) else ""
        port = local_config.get("port", 8910)
        if not isinstance(port, int) or isinstance(port, bool) or not 1024 <= port <= 65535:
            self._config_error = "Port trong cấu hình Muse Tool không hợp lệ."
            port = 8910
        self.base_url = str(base_url if base_url is not None else
                            settings.video_motion_muse_base_url or f"http://127.0.0.1:{port}").strip().rstrip("/")

    def configuration(self) -> ProviderConfigState:
        if self._config_error:
            return ProviderConfigState(False, ("VIDEO_MOTION_MUSE_CONFIG_FILE",), self._config_error)
        if len(self.api_key) < 32 or any(ord(c) < 32 or ord(c) > 126 for c in self.api_key):
            return ProviderConfigState(False, ("VIDEO_MOTION_MUSE_API_KEY", "VIDEO_MOTION_MUSE_CONFIG_FILE"),
                                       "Đặt API key Muse hoặc đường dẫn file cấu hình Muse Tool trên máy chủ.")
        try:
            url = urlsplit(self.base_url)
            valid = (url.scheme == "http" and url.hostname in ("127.0.0.1", "localhost")
                     and not url.username and not url.password and not url.query
                     and not url.fragment and url.path in ("", "/")
                     and (url.port is None or 1024 <= url.port <= 65535))
        except ValueError:
            valid = False
        if not valid:
            return ProviderConfigState(False, ("VIDEO_MOTION_MUSE_BASE_URL",),
                                       "Muse Tool yêu cầu HTTP localhost cùng máy (base URL không có /v1).")
        return ProviderConfigState(True)

    def capabilities(self) -> dict:
        result = super().capabilities()
        result["features"]["image_to_video"] = False
        result["features"]["narration_postprocess"] = True
        return result

    def _headers(self, key: Optional[str] = None) -> dict[str, str]:
        result = {"Authorization": f"Bearer {self.api_key}"}
        if key:
            result["Idempotency-Key"] = key
        return result

    @staticmethod
    def _task_id(value: object) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,100}", value):
            raise MotionProviderError("Muse Tool trả về ID tác vụ không hợp lệ")
        return value

    async def _request(self, method: str, path: str, *, cancel_check=None, **kwargs) -> dict:
        async with httpx.AsyncClient(transport=self._transport, timeout=self._http_timeout(),
                                    trust_env=False, follow_redirects=False) as client:
            response = await request_with_retries(client, method, f"{self.base_url}{path}",
                                                  cancel_check=cancel_check, **kwargs)
        raise_for_status(response, provider=self.name)
        try:
            data = response.json()
        except ValueError as exc:
            raise MotionProviderError("Muse Tool không trả về JSON hợp lệ") from exc
        if not isinstance(data, dict):
            raise MotionProviderError("Muse Tool trả về dữ liệu không đúng định dạng")
        return data

    def _operation(self, payload: dict, model: str, expected_id: Optional[str] = None) -> MotionOperation:
        task_id = self._task_id(payload.get("id"))
        if expected_id and task_id != expected_id:
            raise MotionProviderError("Muse Tool trả về một tác vụ khác với yêu cầu")
        status = _STATUSES.get(payload.get("status"))
        if status is None or payload.get("kind", "video") != "video":
            raise MotionProviderError("Trạng thái tác vụ video Muse Tool không hợp lệ")
        return MotionOperation(provider=self.name, model=model, operation_id=task_id, status=status,
                               progress=100 if status == STATUS_COMPLETED else None,
                               failure_reason=sanitize_message(payload.get("message"), secrets=(self.api_key,))
                               if status == STATUS_FAILED else None)

    async def _submit(self, request: MotionRequest, cancel_check: Optional[CancelCheck] = None) -> MotionOperation:
        self.require_configured()
        prompt = str(request.prompt or "").strip()
        if not prompt or len(prompt) > 10000:
            raise MotionRequestError("Prompt Muse phải có từ 1 đến 10000 ký tự")
        if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", request.idempotency_key or ""):
            raise MotionRequestError("Thiếu hoặc sai khóa chống tạo video trùng")
        model = self.normalize_model(request.model)
        self.normalize_resolution(request.resolution, model)
        body = {"prompt": prompt, "ratio": self.normalize_aspect_ratio(request.aspect_ratio, model),
                "duration": f"{int(self.clamp_duration(request.duration_seconds, model))}s"}
        if request.audio_mode is not None:
            if request.audio_mode not in ("native", "ambience", "silent"):
                raise MotionRequestError("Chế độ âm thanh Muse không hợp lệ")
            body["audioMode"] = request.audio_mode
        if request.scene_direction:
            body["sceneDirection"] = request.scene_direction
        payload = await self._request("POST", "/v1/videos", cancel_check=cancel_check,
                                      headers=self._headers(request.idempotency_key),
                                      json=body)
        return self._operation(payload, model)

    async def _poll(self, operation: MotionOperation, cancel_check: Optional[CancelCheck] = None) -> MotionOperation:
        task_id = self._task_id(operation.operation_id)
        try:
            payload = await self._request("GET", f"/v1/videos/{task_id}",
                                          headers=self._headers(), cancel_check=cancel_check)
        except MotionProviderError as exc:
            if exc.retryable:
                # Preserve the stored operation on disconnect; resume instead of creating another video.
                raise MotionTimeoutError("Mất kết nối Muse Tool; thử lại để tiếp tục tác vụ đã gửi.") from exc
            raise
        return self._operation(payload, operation.model, task_id)

    async def _download(self, operation: MotionOperation, out_path: Path, *,
                        cancel_check: Optional[CancelCheck] = None, timeout: Optional[float] = None) -> int:
        task_id = self._task_id(operation.operation_id)
        # Construct from our configured endpoint; never trust response downloadUrl or redirect targets.
        async with httpx.AsyncClient(transport=self._transport, timeout=timeout or self._http_timeout(),
                                    trust_env=False, follow_redirects=False) as client:
            try:
                return await download_to_path(
                    client, f"{self.base_url}/v1/videos/{task_id}/content", out_path,
                    max_bytes=int(settings.video_motion_max_clip_mb) * 1024 * 1024,
                    headers=self._headers(), allowed_hosts=(urlsplit(self.base_url).hostname,),
                    provider_host=urlsplit(self.base_url).hostname, allow_insecure_localhost=True,
                    max_redirects=0, cancel_check=cancel_check, timeout=timeout,
                )
            except httpx.TransportError as exc:
                raise MotionTimeoutError("Tải video Muse bị gián đoạn; thử lại để tải tác vụ đã có.") from exc
