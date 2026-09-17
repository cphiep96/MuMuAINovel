"""Meta Model API — Muse Image 1.0 适配器

API（theo tài liệu Meta hiện hành）：
1. `POST {base}/images/generations`
   Header: `Authorization: Bearer <MODEL_API_KEY>`, `Content-Type: application/json`
   Body: `{"model": "muse-image-1.0", "prompt": "...", "n": 1, "size": "1792x1024",
           "response_format": "b64_json", "output_format": "webp"}`
   （`reasoning_strength` là tuỳ chọn, chỉ gửi khi được cấu hình/chọn）
2. Response: `{"data": [{"b64_json": "..."}]}`；một số biến thể trả `data[0].url` thay vì base64.

安全策略：
- 密钥只从环境变量读取，永不写日志/数据库/响应；能力输出只列缺失的变量名
- 只请求服务端配置的 base URL（HTTPS，localhost 仅限开发），base URL 会做一次格式校验
- 优先使用 `b64_json` 以避免 SSRF；若 provider 只返回 URL，则复用统一的 SSRF/重定向/体积校验，
  且**不向 CDN 发送 API key**
- base64 严格解码 + 解码上限 + 图片 magic bytes 校验 + `.part` 原子替换
"""
from __future__ import annotations

import base64
import binascii
import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.logger import get_logger
from app.services.video_export.image_providers.base import (
    ASPECT_RATIOS,
    CancelCheck,
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
from app.services.video_export.providers.errors import (
    MotionCancelledError,
    MotionProviderError,
    sanitize_message,
)
from app.services.video_export.providers.http_utils import (
    download_to_path,
    extract_error_message,
    looks_like_image,
    raise_for_status,
    request_with_retries,
)

logger = get_logger(__name__)

PRIMARY_KEY_ENV = "META_MUSE_API_KEY"
ALIAS_KEY_ENV = "MODEL_API_KEY"

# Muse Image 1.0 的尺寸白名单（比例 → 像素）
SIZE_BY_ASPECT = {
    "16:9": "1792x1024",
    "9:16": "1024x1792",
    "1:1": "1024x1024",
}
ALLOWED_OUTPUT_FORMATS = ("webp", "png", "jpeg")
MIME_BY_FORMAT = {"webp": "image/webp", "png": "image/png", "jpeg": "image/jpeg"}
EXTENSION_BY_FORMAT = {"webp": ".webp", "png": ".png", "jpeg": ".jpg"}

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
JPEG_MAGIC = b"\xff\xd8\xff"
WEBP_RIFF = b"RIFF"
WEBP_TAG = b"WEBP"

_BASE64_PREFIX = re.compile(r"^data:[a-zA-Z0-9/+.-]+;base64,")


def detect_image_magic(head: bytes) -> Optional[str]:
    """按文件头识别图片格式，返回 `png`/`jpeg`/`webp`，未知格式返回 None"""
    if head.startswith(PNG_MAGIC):
        return "png"
    if head.startswith(JPEG_MAGIC):
        return "jpeg"
    if len(head) >= 12 and head[:4] == WEBP_RIFF and head[8:12] == WEBP_TAG:
        return "webp"
    return None


def decode_base64_image(raw: object, *, max_bytes: int) -> bytes:
    """严格解码 provider 返回的 base64（拒绝非法字符、前缀异常与超限内容）"""
    text = str(raw or "").strip()
    if not text:
        raise ImageProviderError("Provider ảnh trả về dữ liệu rỗng")
    text = _BASE64_PREFIX.sub("", text)
    # base64 体积上界：先按字符长度拒绝，避免解码超大 payload 占满内存
    if len(text) > (max_bytes // 3 + 1) * 4 + 1024:
        raise ImageProviderError("Ảnh trả về vượt giới hạn dung lượng cho phép")
    try:
        decoded = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ImageProviderError("Provider ảnh trả về base64 không hợp lệ") from exc
    if not decoded:
        raise ImageProviderError("Provider ảnh trả về dữ liệu rỗng")
    if len(decoded) > max_bytes:
        raise ImageProviderError("Ảnh trả về vượt giới hạn dung lượng cho phép")
    return decoded


class MetaMuseImageProvider(SceneImageProvider):
    """Meta Model API `muse-image-1.0`（image generation）"""

    name = "meta_muse_image"
    label = "Meta Muse Image 1.0"
    description = "Tạo ảnh cho từng phân cảnh bằng Meta Model API; ảnh này được dùng làm ảnh tham chiếu cho video AI."
    models = ("muse-image-1.0",)
    default_model = "muse-image-1.0"
    aspect_ratios = ASPECT_RATIOS
    size_options = tuple(SIZE_BY_ASPECT.values())
    default_size = SIZE_BY_ASPECT["16:9"]
    output_format = "webp"
    supports_reasoning_strength = True
    # Theo tài liệu Meta hiện hành chỉ có low/high (medium không được hỗ trợ)
    reasoning_strengths = ("low", "high")
    cost_note = (
        "Tính phí theo từng ảnh (Meta Model API). Mỗi phân cảnh được bật tạo ảnh là một lần gọi API có tính phí."
    )

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        output_format: Optional[str] = None,
        reasoning_strengths: Optional[str] = None,
        transport=None,
    ) -> None:
        self._transport = transport
        resolved_key = api_key
        if resolved_key is None:
            resolved_key = settings.meta_muse_api_key or settings.model_api_key or ""
        self.api_key = str(resolved_key or "").strip()
        self.base_url = str(
            base_url if base_url is not None else (settings.meta_muse_base_url or "")
        ).strip().rstrip("/")
        self.model = str(
            model if model is not None else (settings.meta_muse_model or self.default_model)
        ).strip()
        configured_format = str(
            output_format
            if output_format is not None
            else (settings.meta_muse_output_format or self.output_format)
        ).strip().lower()
        self.output_format = (
            configured_format if configured_format in ALLOWED_OUTPUT_FORMATS else self.output_format
        )
        strengths = reasoning_strengths
        if strengths is None:
            strengths = settings.meta_muse_reasoning_strengths
        self.reasoning_strengths = tuple(
            item.strip().lower() for item in str(strengths or "").split(",") if item.strip()
        ) or ("low", "high")
        self.max_image_bytes = int(settings.video_image_max_mb) * 1024 * 1024

    # ---------------------------------------------------------------- 配置

    def configuration(self) -> ImageProviderConfigState:
        missing: list[str] = []
        if not self.api_key:
            missing.append(PRIMARY_KEY_ENV)
        if not self.base_url:
            missing.append("META_MUSE_BASE_URL")
        if missing:
            detail = f"Thiếu cấu hình Meta Muse Image: cần API key ({PRIMARY_KEY_ENV}, hoặc alias {ALIAS_KEY_ENV})."
            return ImageProviderConfigState(
                configured=False, missing_config=tuple(missing), detail=detail
            )
        try:
            validate_provider_base_url(
                self.base_url, allow_insecure_localhost=settings.image_allow_insecure_localhost
            )
        except ImageConfigError as exc:
            return ImageProviderConfigState(
                configured=False,
                missing_config=("META_MUSE_BASE_URL",),
                detail=str(exc),
            )
        return ImageProviderConfigState(configured=True)

    def size_for_aspect(self, aspect_ratio: str) -> str:
        return SIZE_BY_ASPECT.get(aspect_ratio, self.default_size)

    def normalize_model(self, value: Optional[str]) -> str:
        return super().normalize_model(value or self.model)

    @property
    def _provider_host(self) -> str:
        return urlsplit(self.base_url).hostname or ""

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    @property
    def _timeout(self) -> float:
        return float(settings.video_image_timeout_seconds)

    # ---------------------------------------------------------------- 生成

    def _build_payload(self, request: ImageRequest) -> dict:
        model = self.normalize_model(request.model)
        size = self.normalize_size(request.size, request.aspect_ratio)
        payload: dict = {
            "model": model,
            "prompt": request.prompt,
            "n": 1,
            "size": size,
            "response_format": "b64_json",
            "output_format": self.output_format,
        }
        strength = self.normalize_reasoning_strength(request.reasoning_strength)
        if strength:
            payload["reasoning_strength"] = strength
        return payload

    async def generate_image(
        self,
        request: ImageRequest,
        out_path: Path,
        *,
        cancel_check: Optional[CancelCheck] = None,
        timeout: Optional[float] = None,
    ) -> SceneImageResult:
        self.require_configured()
        if not str(request.prompt or "").strip():
            raise ImageRequestError("Thiếu prompt cho ảnh phân cảnh")
        payload = self._build_payload(request)
        url = f"{self.base_url}/images/generations"

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
                    headers=self._headers(),
                    max_retries=int(settings.video_image_max_retries),
                    base_delay=float(settings.video_image_retry_delay_seconds),
                    cancel_check=cancel_check,
                )
            # 非 2xx 统一转换为图片 provider 错误（消息已 sanitize，不含 key）
            raise_for_status(response, provider=self.name)
        except (MotionCancelledError, ImageCancelledError) as exc:
            # HTTP helper báo cancel bằng MotionCancelledError → 必须映射为 ImageCancelledError
            # 让 pipeline 以 JobCancelled/cancelled 收尾，而不是把分镜标记为 failed
            raise ImageCancelledError(self._safe("Đã hủy theo yêu cầu của người dùng")) from exc
        except MotionProviderError as exc:
            raise ImageProviderError(
                self._safe(str(exc)), retryable=exc.retryable, status_code=exc.status_code
            ) from exc
        except Exception as exc:  # noqa: BLE001 - 网络异常统一为 provider 错误（消息已 sanitize）
            raise ImageProviderError(
                self._safe(f"Không gọi được Meta Model API: {type(exc).__name__}"), retryable=True
            ) from exc

        data = self._json_object(response)

        items = data.get("data")
        if not isinstance(items, list) or not items or not isinstance(items[0], dict):
            raise ImageProviderError("Meta Model API không trả về ảnh nào")
        first = items[0]

        # b64_json được ưu tiên để tránh SSRF；空字符串等异常值也要走严格解码并报错
        has_b64 = "b64_json" in first and first.get("b64_json") is not None
        remote_url = str(first.get("url") or "").strip()
        if has_b64:
            content = decode_base64_image(first.get("b64_json"), max_bytes=self.max_image_bytes)
            detected = detect_image_magic(content[:16])
            if detected is None:
                raise ImageProviderError(
                    "Dữ liệu ảnh trả về không phải PNG/WebP/JPEG hợp lệ (kiểm tra bằng magic bytes)"
                )
            written = _atomic_write(out_path, content)
            mime = MIME_BY_FORMAT[detected]
        elif remote_url:
            await self._download_via_url(remote_url, out_path, cancel_check=cancel_check)
            detected = detect_image_magic(out_path.read_bytes()[:16])
            if detected is None:
                out_path.unlink(missing_ok=True)
                raise ImageProviderError(
                    "Ảnh tải từ URL không phải PNG/WebP/JPEG hợp lệ (kiểm tra bằng magic bytes)"
                )
            written = out_path.stat().st_size
            mime = MIME_BY_FORMAT[detected]
        else:
            raise ImageProviderError("Meta Model API không trả về b64_json hoặc URL ảnh")

        return SceneImageResult(
            path=out_path,
            provider=self.name,
            model=self.normalize_model(request.model),
            size=str(payload["size"]),
            mime_type=mime,
            bytes_written=written,
        )

    async def _download_via_url(
        self, remote_url: str, out_path: Path, *, cancel_check: Optional[CancelCheck]
    ) -> None:
        """URL fallback：统一 SSRF/重定向/体积/magic bytes 校验

        安全：这里 **绝不** 发送 Authorization/API key —— kể cả khi host trùng `api.meta.ai`
        (provider 返回的 URL 可能被篡改，凭证不应随下载请求外发)。
        取消（HTTP helper 抛 MotionCancelledError）会映射为 ImageCancelledError，并清理 `.part`。
        """
        try:
            async with httpx.AsyncClient(transport=self._transport, timeout=self._timeout) as client:
                await download_to_path(
                    client,
                    remote_url,
                    out_path,
                    max_bytes=self.max_image_bytes,
                    headers=None,
                    provider_host=self._provider_host,
                    cancel_check=cancel_check,
                    timeout=self._timeout,
                    content_validator=looks_like_image,
                    invalid_content_message=(
                        "Nội dung tải về không phải ảnh hợp lệ (kiểm tra bằng magic bytes, "
                        "không dựa vào Content-Type)"
                    ),
                )
        except (MotionCancelledError, ImageCancelledError) as exc:
            # `.part` đã được download_to_path dọn trước khi raise
            raise ImageCancelledError(self._safe("Đã hủy theo yêu cầu của người dùng")) from exc
        except Exception as exc:  # noqa: BLE001 - SSRF/体积/格式校验失败统一收敛
            raise ImageProviderError(
                self._safe(f"Không tải được ảnh từ provider: {exc}")
            ) from exc

    def _safe(self, text: object) -> str:
        """清洗可能进入 DB/UI/log 的文本：屏蔽本 provider 的 key、URL、路径与 token-like 串"""
        return sanitize_message(text, secrets=(self.api_key,))

    def _json_object(self, response: httpx.Response) -> dict:
        try:
            data = response.json()
        except Exception as exc:  # noqa: BLE001 - provider 返回非 JSON
            raise ImageProviderError("Meta Model API trả về dữ liệu không phải JSON") from exc
        if not isinstance(data, dict):
            raise ImageProviderError("Meta Model API trả về dữ liệu không đúng định dạng")
        if isinstance(data.get("error"), dict):
            detail = extract_error_message(data) or "Meta Model API báo lỗi"
            raise ImageProviderError(self._safe(detail))
        return data


def validate_provider_base_url(url: str, *, allow_insecure_localhost: bool) -> str:
    """校验 base URL：必须是 http(s)、无 userinfo、HTTPS 之外只允许开发用 localhost"""
    raw = str(url or "").strip()
    if not raw:
        raise ImageConfigError("Base URL của provider ảnh chưa được cấu hình")
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise ImageConfigError("Base URL của provider ảnh phải dùng http(s)")
    if parts.username or parts.password:
        raise ImageConfigError("Base URL của provider ảnh không được chứa thông tin đăng nhập")
    host = (parts.hostname or "").lower()
    if not host:
        raise ImageConfigError("Base URL của provider ảnh thiếu tên miền")
    is_local = host in ("localhost", "127.0.0.1", "::1")
    if parts.scheme != "https" and not (allow_insecure_localhost and is_local):
        raise ImageConfigError("Base URL của provider ảnh phải dùng HTTPS (chỉ localhost mới cho phép http)")
    return raw.rstrip("/")


def _atomic_write(out_path: Path, content: bytes) -> int:
    """先写 `.part` 再原子替换，避免留下半张图片"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(out_path.name + ".part")
    try:
        with open(temp_path, "wb") as handle:
            handle.write(content)
        os.replace(temp_path, out_path)
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:  # pragma: no cover
            pass
        raise ImageProviderError("Không ghi được ảnh vào thư mục tác vụ") from exc
    return len(content)


def output_extension(provider: SceneImageProvider) -> str:
    """provider 输出格式对应的文件扩展名（用于生成 `assets/scene_XXX.webp`）"""
    return EXTENSION_BY_FORMAT.get(str(provider.output_format).lower(), ".webp")
