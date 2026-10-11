"""GPT Image Proxy adapter — local ChatGPT desktop pipeline.

POST {base}/api/generate with `{prompt}`; response body is image bytes.
Configured only when GPTIMAGE_BASE_URL is set. Localhost HTTP is allowed
because this provider is a machine-local proxy, not a public API.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.logger import get_logger
from app.services.video_export.image_providers.base import (
    ASPECT_RATIOS,
    ImageProviderConfigState,
    ImageRequest,
    SceneImageProvider,
    SceneImageResult,
)
from app.services.video_export.image_providers.errors import (
    ImageCancelledError,
    ImageConfigError,
    ImageProviderError,
    ImageRequestError,
)
from app.services.video_export.image_providers.meta_muse_image import (
    _atomic_write,
    detect_image_magic,
    validate_provider_base_url,
)
from app.services.video_export.providers.errors import (
    MotionCancelledError,
    MotionProviderError,
    sanitize_message,
)
from app.services.video_export.providers.http_utils import (
    request_with_retries,
    raise_for_status,
)

logger = get_logger(__name__)

BASE_URL_ENV = "GPTIMAGE_BASE_URL"
SIZE_BY_ASPECT = {
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "1:1": "1024x1024",
}
MIME_BY_FORMAT = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}


class GptImageProxyProvider(SceneImageProvider):
    """Local GPT Image Studio proxy (`feat/studio-shell-jobs`)."""

    name = "gptimage"
    label = "GPT Image Studio"
    description = (
        "Tạo ảnh phân cảnh qua proxy GPT Image local (ChatGPT desktop). "
        "Mỗi phân cảnh là một lần gọi POST /api/generate."
    )
    models = ("chatgpt-image",)
    default_model = "chatgpt-image"
    aspect_ratios = ASPECT_RATIOS
    size_options = tuple(SIZE_BY_ASPECT.values())
    default_size = SIZE_BY_ASPECT["16:9"]
    output_format = "png"
    supports_reasoning_strength = False
    cost_note = (
        "Dùng tài khoản ChatGPT trên máy local, không gọi Meta Muse. "
        "Mỗi phân cảnh chờ proxy vẽ xong (thường 40–240 giây)."
    )

    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        transport=None,
        **_ignored,
    ) -> None:
        self._transport = transport
        self.base_url = str(
            base_url if base_url is not None else (settings.gptimage_base_url or "")
        ).strip().rstrip("/")
        self.max_image_bytes = int(settings.video_image_max_mb) * 1024 * 1024

    def configuration(self) -> ImageProviderConfigState:
        if not self.base_url:
            return ImageProviderConfigState(
                configured=False,
                missing_config=(BASE_URL_ENV,),
                detail=(
                    "Chưa cấu hình GPT Image Studio. Đặt GPTIMAGE_BASE_URL "
                    "(ví dụ http://127.0.0.1:3000) khi proxy local đang chạy."
                ),
            )
        try:
            validate_provider_base_url(
                self.base_url,
                allow_insecure_localhost=True,
            )
        except ImageConfigError as exc:
            return ImageProviderConfigState(
                configured=False,
                missing_config=(BASE_URL_ENV,),
                detail=str(exc),
            )
        host = (urlsplit(self.base_url).hostname or "").lower()
        if host not in ("localhost", "127.0.0.1", "::1"):
            return ImageProviderConfigState(
                configured=False,
                missing_config=(BASE_URL_ENV,),
                detail="GPTIMAGE_BASE_URL chỉ được trỏ tới localhost của máy chạy proxy.",
            )
        return ImageProviderConfigState(configured=True)

    def size_for_aspect(self, aspect_ratio: str) -> str:
        return SIZE_BY_ASPECT.get(aspect_ratio, self.default_size)

    @property
    def _timeout(self) -> float:
        return float(max(int(settings.video_image_timeout_seconds), 240))

    def _prompt_for(self, request: ImageRequest) -> str:
        prompt = str(request.prompt or "").strip()
        if not prompt:
            raise ImageRequestError("Thiếu prompt cho ảnh phân cảnh")
        aspect = self.normalize_aspect_ratio(request.aspect_ratio)
        suffix = f" — cinematic still, aspect ratio {aspect}, film production frame, no text overlay"
        if suffix.strip(" —") in prompt:
            return prompt
        return f"{prompt}{suffix}"

    def _safe(self, message: str) -> str:
        return sanitize_message(message)

    async def generate_image(
        self,
        request: ImageRequest,
        out_path: Path,
        *,
        cancel_check=None,
        timeout: Optional[float] = None,
    ) -> SceneImageResult:
        self.require_configured()
        payload = {"prompt": self._prompt_for(request)}
        url = f"{self.base_url}/api/generate"

        if cancel_check is not None and await cancel_check():
            raise ImageCancelledError("Đã hủy theo yêu cầu của người dùng")

        try:
            async with httpx.AsyncClient(
                transport=self._transport, timeout=timeout or self._timeout
            ) as client:
                response = await request_with_retries(
                    client,
                    "POST",
                    url,
                    json=payload,
                    headers={"Content-Type": "application/json"},
                    max_retries=int(settings.video_image_max_retries),
                    base_delay=float(settings.video_image_retry_delay_seconds),
                    cancel_check=cancel_check,
                    allow_non_idempotent_retry=False,
                )
            raise_for_status(response, provider=self.name)
        except (MotionCancelledError, ImageCancelledError) as exc:
            raise ImageCancelledError(self._safe("Đã hủy theo yêu cầu của người dùng")) from exc
        except MotionProviderError as exc:
            raise ImageProviderError(
                self._safe(str(exc)), retryable=exc.retryable, status_code=exc.status_code
            ) from exc
        except Exception as exc:  # noqa: BLE001
            raise ImageProviderError(
                self._safe(f"Không gọi được GPT Image Studio: {type(exc).__name__}"),
                retryable=True,
            ) from exc

        content_type = (response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if "application/json" in content_type:
            try:
                data = response.json()
                detail = data.get("error") if isinstance(data, dict) else None
            except Exception:  # noqa: BLE001
                detail = None
            raise ImageProviderError(self._safe(str(detail) or "GPT Image Studio không trả về ảnh"))

        content = response.content or b""
        if len(content) > self.max_image_bytes:
            raise ImageProviderError("Ảnh từ GPT Image Studio vượt giới hạn dung lượng")
        kind = detect_image_magic(content[:16])
        if kind is None:
            raise ImageProviderError("GPT Image Studio không trả về ảnh hợp lệ")

        bytes_written = _atomic_write(out_path, content)
        return SceneImageResult(
            path=out_path,
            provider=self.name,
            model=self.normalize_model(request.model),
            size=self.normalize_size(request.size, request.aspect_ratio),
            mime_type=MIME_BY_FORMAT.get(kind, "image/png"),
            bytes_written=bytes_written,
        )
