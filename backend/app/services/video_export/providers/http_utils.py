"""Provider 的 HTTP 安全工具

安全边界（服务端才持有凭证与目标地址，客户端永远无法指定 URL）：
1. 出站地址只来自服务端配置；下载地址来自 provider 响应，因此必须做 SSRF 校验：
   - 仅允许 https（开发环境可用 `VIDEO_MOTION_ALLOW_INSECURE_LOCALHOST=true` 放开 localhost 的 http）
   - 拒绝携带用户信息的 URL、拒绝回环/私网/链路本地/保留地址，避免访问内网与云元数据
   - 可用 `VIDEO_MOTION_DOWNLOAD_ALLOWED_HOSTS` 进一步限定 CDN 主机白名单
2. API 凭证只发送给 provider 自身主机；下载走 CDN 时不带凭证，避免密钥随重定向泄漏
3. 下载有体积上限、MIME 与文件头校验，先写 `.part` 临时文件，校验通过后才原子替换
"""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import re
import socket
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional
from urllib.parse import urlsplit

import httpx

from app.config import settings
from app.logger import get_logger
from app.services.video_export.providers.errors import (
    MotionCancelledError,
    MotionProviderError,
)

logger = get_logger(__name__)

CancelCheck = Callable[[], Awaitable[bool]]

# 允许的视频容器文件头：ISO BMFF（mp4/mov，box 对齐）与 Matroska/WebM
_MP4_BOX_BRANDS = (b"ftyp", b"styp")
_WEBM_HEADER = b"\x1aE\xdf\xa3"
_REJECTED_CONTENT_TYPES = ("text/", "application/json", "application/xml", "text/html")
RETRYABLE_STATUS_CODES = frozenset({408, 425, 429, 500, 502, 503, 504})


def _settings_hosts(raw: str) -> tuple[str, ...]:
    return tuple(part.strip().lower() for part in str(raw or "").split(",") if part.strip())


def _is_url_allowed_scheme(host: str, scheme: str, *, allow_insecure_localhost: bool) -> bool:
    if scheme == "https":
        return True
    return bool(allow_insecure_localhost and scheme == "http" and _is_localhost_name(host))


def _is_localhost_name(host: str) -> bool:
    lowered = host.lower().strip("[]")
    return lowered in ("localhost", "127.0.0.1", "::1", "0.0.0.0")


async def _resolve_host_ips(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise MotionProviderError(f"Không phân giải được tên miền tải video: {exc}", retryable=True) from exc
    ips: list[str] = []
    for info in infos:
        address = info[4][0]
        if address and address not in ips:
            ips.append(address)
    return ips


def _ip_is_private(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return True
    return not ip.is_global


async def validate_download_url(
    url: str,
    *,
    allowed_hosts: Optional[Iterable[str]] = None,
    allow_insecure_localhost: Optional[bool] = None,
    provider_host: Optional[str] = None,
) -> str:
    """校验 provider 响应里的下载地址；不合法时抛出 MotionProviderError（消息不含完整 URL）"""
    raw = str(url or "").strip()
    if not raw:
        raise MotionProviderError("Provider không trả về địa chỉ tải video")

    allow_local = (
        bool(settings.video_motion_allow_insecure_localhost)
        if allow_insecure_localhost is None
        else bool(allow_insecure_localhost)
    )
    parts = urlsplit(raw)
    if parts.scheme not in ("http", "https"):
        raise MotionProviderError("Địa chỉ tải video không dùng giao thức được hỗ trợ")
    if parts.username or parts.password:
        raise MotionProviderError("Địa chỉ tải video chứa thông tin đăng nhập, đã bị từ chối")
    host = (parts.hostname or "").strip().lower()
    if not host:
        raise MotionProviderError("Địa chỉ tải video thiếu tên miền")
    if not _is_url_allowed_scheme(host, parts.scheme, allow_insecure_localhost=allow_local):
        raise MotionProviderError("Địa chỉ tải video phải dùng HTTPS")

    hosts = tuple(allowed_hosts) if allowed_hosts is not None else _settings_hosts(
        settings.video_motion_download_allowed_hosts
    )
    if hosts:
        permitted = set(hosts)
        if provider_host:
            permitted.add(str(provider_host).strip().lower())
        if host not in permitted:
            logger.warning("拒绝白名单外的下载主机: host=%s", host)
            raise MotionProviderError("Máy chủ tải video không nằm trong danh sách cho phép")

    if not (allow_local and _is_localhost_name(host)):
        for address in await _resolve_host_ips(host):
            if _ip_is_private(address):
                logger.warning("拒绝指向内网地址的下载请求: host=%s ip=%s", host, address)
                raise MotionProviderError("Địa chỉ tải video trỏ tới mạng nội bộ, đã bị từ chối")
    return raw


def _host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").strip().lower()


async def _sleep_with_cancel(delay: float, cancel_check: Optional[CancelCheck]) -> None:
    if cancel_check is None:
        await asyncio.sleep(delay)
        return
    deadline = asyncio.get_running_loop().time() + delay
    while True:
        if await cancel_check():
            raise MotionCancelledError("Đã hủy theo yêu cầu của người dùng")
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            return
        await asyncio.sleep(min(0.5, remaining))


def sanitize_path_token(value: object, *, provider: str, label: str = "operation id") -> str:
    """校验会拼进 URL 路径的 token（operation id / request id）

    provider 返回的（或数据库里被篡改的）值绝不允许改变请求目标：拒绝绝对 URL、`..`、
    额外路径段、查询/片段、编码字符与控制字符，只保留 `[A-Za-z0-9._:-]`。

    失败信息只描述问题，不包含 API key，也不回显可疑内容。
    """
    raw = str(value or "").strip()
    if not raw or len(raw) > 200:
        raise MotionProviderError(f"{provider} trả về {label} không hợp lệ")
    if (
        "://" in raw
        or "/" in raw
        or "\\" in raw
        or "?" in raw
        or "#" in raw
        or "%" in raw
        or ".." in raw
        or any(char.isspace() or ord(char) < 0x20 for char in raw)
    ):
        raise MotionProviderError(
            f"{provider} trả về {label} chứa ký tự không được phép, đã từ chối gọi endpoint"
        )
    if not re.fullmatch(r"[A-Za-z0-9._:-]+", raw) or not re.search(r"[A-Za-z0-9]", raw):
        raise MotionProviderError(f"{provider} trả về {label} không đúng định dạng")
    return raw


def extract_error_message(payload: object, *, limit: int = 200) -> str:
    """从 provider 的错误响应里取出可读信息（清洗密钥并截断）"""
    from app.services.video_export.providers.errors import sanitize_message

    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            return sanitize_message(error.get("message") or error.get("status") or error, limit=limit)
        if isinstance(error, str):
            return sanitize_message(error, limit=limit)
        for key in ("message", "detail", "error_message"):
            if payload.get(key):
                return sanitize_message(payload[key], limit=limit)
    if isinstance(payload, str):
        return sanitize_message(payload, limit=limit)
    return ""


def raise_for_status(response: httpx.Response, *, provider: str) -> None:
    """把非 2xx 响应转换为 MotionProviderError（消息不含密钥/完整 URL）"""
    if 200 <= response.status_code < 300:
        return
    detail = ""
    try:
        detail = extract_error_message(response.json())
    except Exception:  # noqa: BLE001 - 非 JSON 响应
        detail = (response.text or "")[:200]
    message = f"{provider} trả mã {response.status_code}"
    if detail:
        message = f"{message}: {detail}"
    raise MotionProviderError(
        message,
        retryable=response.status_code in RETRYABLE_STATUS_CODES,
        status_code=response.status_code,
    )


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: Optional[int] = None,
    base_delay: Optional[float] = None,
    cancel_check: Optional[CancelCheck] = None,
    allow_non_idempotent_retry: bool = False,
    **kwargs,
) -> httpx.Response:
    """带指数退避的请求。

    Non-idempotent requests are retried only when the caller supplies an
    ``Idempotency-Key`` header or explicitly opts in with
    ``allow_non_idempotent_retry``.  This prevents a timeout/5xx during a paid
    provider submission from creating a second remote job that nobody polls.
    """
    attempts = max(int(settings.video_motion_max_retries if max_retries is None else max_retries), 0) + 1
    if method.upper() in {"POST", "PUT", "PATCH"} and not allow_non_idempotent_retry:
        headers = kwargs.get("headers") or {}
        has_idempotency_key = any(
            str(key).lower() == "idempotency-key" and str(value).strip()
            for key, value in headers.items()
        )
        if not has_idempotency_key:
            attempts = 1
    delay = float(settings.video_motion_poll_interval_seconds if base_delay is None else base_delay)
    last_error: Optional[Exception] = None

    for attempt in range(attempts):
        if cancel_check is not None and await cancel_check():
            raise MotionCancelledError("Đã hủy theo yêu cầu của người dùng")
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.TransportError, httpx.TimeoutException) as exc:
            last_error = exc
        else:
            if response.status_code not in RETRYABLE_STATUS_CODES:
                return response
            last_error = MotionProviderError(
                f"Provider trả mã {response.status_code}",
                retryable=True,
                status_code=response.status_code,
            )
            # httpx async stream 必须用 aclose()：同步 close() 会抛 RuntimeError
            await response.aclose()

        if attempt == attempts - 1:
            break
        wait = min(delay * (2**attempt), max(delay, float(settings.video_motion_poll_max_interval_seconds)))
        logger.warning("Provider 请求失败，%.1fs 后重试 (lần %s/%s)", wait, attempt + 1, attempts - 1)
        await _sleep_with_cancel(wait, cancel_check)

    if isinstance(last_error, MotionProviderError):
        raise last_error
    raise MotionProviderError(
        f"Không kết nối được provider: {type(last_error).__name__ if last_error else 'unknown'}",
        retryable=True,
    )


def detect_video_magic(head: bytes) -> bool:
    """仅凭文件头判断是否为视频容器

    - ISO BMFF（mp4/mov）要求 `ftyp`/`styp` box 出现在标准位置（offset 4）
    - Matroska/WebM 要求 EBML 头

    Content-Type 永远不作为“是视频”的证据，只用于提前排除明显错误的内容类型。
    """
    if len(head) < 12:
        return False
    if head[4:8] in _MP4_BOX_BRANDS:
        return True
    return head.startswith(_WEBM_HEADER)


def looks_like_video(content_type: str, head: bytes) -> bool:
    """校验下载内容确实是视频容器：必须通过 magic bytes，Content-Type 仅用于快速排除"""
    lowered = (content_type or "").split(";", 1)[0].strip().lower()
    if lowered.startswith(_REJECTED_CONTENT_TYPES):
        return False
    return detect_video_magic(head)


def looks_like_image(content_type: str, head: bytes) -> bool:
    """图片版本：同样只认 magic bytes（PNG/JPEG/WebP），Content-Type 仅用于快速排除"""
    lowered = (content_type or "").split(";", 1)[0].strip().lower()
    if lowered.startswith(_REJECTED_CONTENT_TYPES):
        return False
    if head.startswith(b"\x89PNG\r\n\x1a\n") or head.startswith(b"\xff\xd8\xff"):
        return True
    return len(head) >= 12 and head[:4] == b"RIFF" and head[8:12] == b"WEBP"


async def download_to_path(
    client: httpx.AsyncClient,
    url: str,
    out_path: Path,
    *,
    max_bytes: int,
    headers: Optional[dict[str, str]] = None,
    allowed_hosts: Optional[Iterable[str]] = None,
    provider_host: Optional[str] = None,
    cancel_check: Optional[CancelCheck] = None,
    timeout: Optional[float] = None,
    max_redirects: int = 3,
    content_validator: Optional[Callable[[str, bytes], bool]] = None,
    allow_insecure_localhost: Optional[bool] = None,
    invalid_content_message: str = (
        "Nội dung tải về không phải video hợp lệ (kiểm tra bằng magic bytes, không dựa vào Content-Type)"
    ),
) -> int:
    """流式下载并校验内容，返回写入的字节数

    - 每一跳重定向都重新做 SSRF 校验
    - `content_validator` 默认按视频容器校验（`looks_like_video`），图片等其它类型可传入自己的校验器；
      内容类型永远不是“合法”的证据，必须通过 magic bytes 校验
    - `allow_insecure_localhost` 可显式覆盖（图片 provider 用 `IMAGE_ALLOW_INSECURE_LOCALHOST`，
      视频 provider 缺省沿用 `VIDEO_MOTION_ALLOW_INSECURE_LOCALHOST`）
    - 超出 `max_bytes`、内容不合法、写入失败都会清理临时文件
    """
    validator = content_validator or looks_like_video
    current = await validate_download_url(
        url,
        allowed_hosts=allowed_hosts,
        allow_insecure_localhost=allow_insecure_localhost,
        provider_host=provider_host,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = out_path.with_name(out_path.name + ".part")
    written = 0

    try:
        for _hop in range(max_redirects + 1):
            request_headers = dict(headers or {})
            if provider_host and _host_of(current) != str(provider_host).strip().lower():
                # 下载走 CDN 时绝不携带 provider 凭证
                request_headers.pop("Authorization", None)
                request_headers.pop("x-goog-api-key", None)
            async with client.stream(
                "GET", current, headers=request_headers, timeout=timeout, follow_redirects=False
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location")
                    if not location:
                        raise MotionProviderError("Provider chuyển hướng tải video thiếu đích")
                    current = await validate_download_url(
                        httpx.URL(current).join(location).__str__(),
                        allowed_hosts=allowed_hosts,
                        allow_insecure_localhost=allow_insecure_localhost,
                        provider_host=provider_host,
                    )
                    continue
                if response.status_code != 200:
                    raise MotionProviderError(
                        f"Tải video thất bại (mã {response.status_code})", retryable=True
                    )

                content_type = response.headers.get("content-type", "")
                declared = response.headers.get("content-length")
                if declared and declared.isdigit() and int(declared) > max_bytes:
                    raise MotionProviderError("Video trả về vượt giới hạn dung lượng cho phép")

                with open(temp_path, "wb") as handle:
                    head = b""
                    async for chunk in response.aiter_bytes():
                        if not chunk:
                            continue
                        if not head:
                            head = chunk[:64]
                        written += len(chunk)
                        if written > max_bytes:
                            raise MotionProviderError("Video trả về vượt giới hạn dung lượng cho phép")
                        handle.write(chunk)
                        if cancel_check is not None and await cancel_check():
                            raise MotionCancelledError("Đã hủy theo yêu cầu của người dùng")
                if written == 0:
                    raise MotionProviderError("Provider trả về tệp rỗng")
                if not validator(content_type, head):
                    raise MotionProviderError(invalid_content_message)
                os.replace(temp_path, out_path)
                return written
        raise MotionProviderError("Provider chuyển hướng quá nhiều lần khi tải video")
    except BaseException:
        # 取消、超时、体积超限或校验失败都必须清理临时文件
        with contextlib.suppress(OSError):
            temp_path.unlink()
        raise
