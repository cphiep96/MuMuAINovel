"""场景图片生成 Provider 的错误分类（与 motion video provider 相互独立）

约定：异常消息会返回给用户并可能写入数据库，因此**不得**包含密钥、绝对路径、base64 或远端 URL。
"""
from __future__ import annotations

from app.services.video_export.providers.errors import sanitize_message

__all__ = [
    "ImageConfigError",
    "ImageProviderError",
    "ImageRequestError",
    "ImageTimeoutError",
    "ImageCancelledError",
    "sanitize_message",
]


class ImageProviderError(RuntimeError):
    """图片 provider 调用失败"""

    def __init__(self, message: str, *, retryable: bool = False, status_code: int | None = None) -> None:
        super().__init__(sanitize_message(message))
        self.retryable = retryable
        self.status_code = status_code


class ImageConfigError(RuntimeError):
    """图片 provider 未正确配置（缺少环境变量等）"""

    def __init__(self, message: str, *, missing_config: tuple[str, ...] = ()) -> None:
        super().__init__(sanitize_message(message))
        self.missing_config = tuple(missing_config)


class ImageRequestError(RuntimeError):
    """请求参数不被图片 provider 接受（消息同样经过 sanitize，不泄露 payload 敏感内容）"""

    def __init__(self, message: str) -> None:
        super().__init__(sanitize_message(message))


class ImageTimeoutError(RuntimeError):
    """单张图片生成超出墙钟上限"""

    def __init__(self, message: str) -> None:
        super().__init__(sanitize_message(message))


class ImageCancelledError(RuntimeError):
    """任务在生成图片期间被取消"""
