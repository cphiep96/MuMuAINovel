"""视频转场 / 图片 Provider 的错误分类

约定：异常消息会直接返回给用户/写入数据库/写日志，因此 **不得** 包含密钥、绝对路径或原始远端 URL。
所有构造入口都会经过 `sanitize_message()`（见下），把密钥样式片段、Bearer token、URL、绝对路径、
内联 base64 与超长 token-like 字符串替换为占位符。

- `MotionConfigError`：服务端配置缺失或非法（不可重试，需要管理员处理）
- `MotionRequestError`：参数不被 provider 接受（不可重试，客户端可修正后重试）
- `MotionProviderError`：provider 返回错误；`retryable` 标记是否值得重试
- `MotionCancelledError`：任务被用户取消，停止轮询/下载
- `MotionTimeoutError`：单个分镜超过墙钟上限
"""
from __future__ import annotations

import re
from typing import Iterable, Optional

_DATA_URI_PATTERN = re.compile(r"data:[a-zA-Z0-9/+.-]+;base64,[A-Za-z0-9+/=]+")
_BASE64_BLOB_PATTERN = re.compile(r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}={0,2}(?![A-Za-z0-9+/])")
_URL_PATTERN = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s\"'<>\)\]]+")
_ABS_PATH_PATTERN = re.compile(
    r"(?:(?<=^)|(?<=[\s\"'(=]))(?:[A-Za-z]:[\\/]|/(?:home|root|usr|var|tmp|etc|mnt|opt|Users|storage|app|private)/)[^\s\"'<>\)\]]*"
)
# key/token/secret dạng `key=xxx`, `"api_key": "xxx"` hoặc `Authorization: Bearer xxx`
_KEYED_SECRET_PATTERN = re.compile(
    r"(?i)\b(api[_-]?key|authorization|bearer|token|secret|password|passwd)\b\s*[:=]?\s*"
    r"(?:bearer|basic|token)?\s*[\"']?([A-Za-z0-9._\-/+]{6,})"
)
# token-like: chuỗi rất dài (≥32 ký tự) — thường là raw API key; tên biến môi trường được giữ lại
_TOKEN_LIKE_PATTERN = re.compile(r"[A-Za-z0-9_\-]{32,}")
_ENV_NAME_PATTERN = re.compile(r"[A-Z0-9_]+")


def _mask_long_tokens(message: str) -> str:
    """Che các chuỗi dài giống raw key, nhưng giữ nguyên tên biến môi trường (không phải bí mật)"""

    def replace(match: re.Match) -> str:
        token = match.group(0)
        if _ENV_NAME_PATTERN.fullmatch(token):
            return token
        return "<token>"

    return _TOKEN_LIKE_PATTERN.sub(replace, message)


def sanitize_message(
    text: object,
    *,
    limit: int = 300,
    secrets: Optional[Iterable[str]] = None,
) -> str:
    """清洗待展示文本：去掉密钥样式片段、URL、绝对路径、内联 base64 与 token-like 字符串

    `secrets` 用于显式屏蔽已知的密钥值（例如 provider 自己的 API key），
    即使它的形态不匹配任何正则也能被替换掉。
    """
    message = str(text or "").strip()
    if not message:
        return ""
    for secret in secrets or ():
        value = str(secret or "").strip()
        if len(value) >= 6:
            message = message.replace(value, "<hidden>")
    message = _DATA_URI_PATTERN.sub("<inline-data>", message)
    message = _BASE64_BLOB_PATTERN.sub("<inline-data>", message)
    message = _KEYED_SECRET_PATTERN.sub(r"\1=<hidden>", message)
    message = _URL_PATTERN.sub("<url>", message)
    message = _ABS_PATH_PATTERN.sub("<path>", message)
    message = _mask_long_tokens(message)
    return message[:limit]


class MotionProviderError(RuntimeError):
    """Provider 调用失败"""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None) -> None:
        super().__init__(sanitize_message(message))
        self.retryable = retryable
        self.status_code = status_code


class MotionConfigError(RuntimeError):
    """Provider 未被正确配置（缺少环境变量等）"""

    def __init__(self, message: str, *, missing_config: tuple[str, ...] = ()) -> None:
        super().__init__(sanitize_message(message))
        self.missing_config = tuple(missing_config)


class MotionRequestError(RuntimeError):
    """请求参数不被 provider 接受"""


class MotionCancelledError(RuntimeError):
    """任务在等待远端操作期间被取消"""


class MotionTimeoutError(RuntimeError):
    """单个分镜的远端生成超出墙钟上限"""
