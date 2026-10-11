"""场景图片 Provider 注册表（与 motion video 注册表相互独立）"""
from __future__ import annotations

from typing import Any, Callable, Optional

from app.services.video_export.image_providers.base import SceneImageProvider
from app.services.video_export.image_providers.errors import ImageConfigError
from app.services.video_export.image_providers.meta_muse_image import MetaMuseImageProvider
from app.services.video_export.image_providers.gptimage_proxy import GptImageProxyProvider
from app.services.video_export.image_providers.user_credentials import (
    image_provider_kwargs_from_settings,
    missing_muse_config_hint,
)

META_PROVIDER_NAME = MetaMuseImageProvider.name
GPTIMAGE_PROVIDER_NAME = GptImageProxyProvider.name

IMAGE_PROVIDER_ORDER: tuple[str, ...] = (GPTIMAGE_PROVIDER_NAME, META_PROVIDER_NAME)

_FACTORIES: dict[str, Callable[..., SceneImageProvider]] = {
    META_PROVIDER_NAME: MetaMuseImageProvider,
    GPTIMAGE_PROVIDER_NAME: GptImageProxyProvider,
}


def known_image_provider_names() -> tuple[str, ...]:
    return IMAGE_PROVIDER_ORDER


def is_known_image_provider(name: str) -> bool:
    return str(name or "").strip() in _FACTORIES


def build_image_provider(
    name: str,
    *,
    transport=None,
    user_settings: Any = None,
) -> SceneImageProvider:
    """构建图片 provider；未注册的名字抛 ImageConfigError

    `user_settings`: bản ghi Cài đặt của user. Nếu đã chọn Meta Muse + API key
    thì dùng key đó; không thì fallback sang biến môi trường máy chủ.
    """
    key = str(name or "").strip()
    factory = _FACTORIES.get(key)
    if factory is None:
        raise ImageConfigError(
            f"Provider ảnh không được hỗ trợ: {key or '(trống)'}. "
            f"Các provider hợp lệ: {', '.join(IMAGE_PROVIDER_ORDER)}"
        )
    kwargs: dict[str, Any] = dict(image_provider_kwargs_from_settings(user_settings))
    if transport is not None:
        kwargs["transport"] = transport
    return factory(**kwargs)


def list_image_providers(*, user_settings: Any = None) -> list[SceneImageProvider]:
    return [build_image_provider(name, user_settings=user_settings) for name in IMAGE_PROVIDER_ORDER]


def list_image_provider_capabilities(*, user_settings: Any = None) -> list[dict]:
    """全部图片 provider 的能力（含配置状态；不含密钥/路径）"""
    items = []
    for provider in list_image_providers(user_settings=user_settings):
        payload = provider.capabilities()
        if not payload.get("configured") and not payload.get("config_error"):
            payload["config_error"] = missing_muse_config_hint()
        items.append(payload)
    return items


def configured_image_providers(
    providers: Optional[list[SceneImageProvider]] = None,
    *,
    user_settings: Any = None,
) -> list[SceneImageProvider]:
    items = providers if providers is not None else list_image_providers(user_settings=user_settings)
    return [item for item in items if item.configuration().configured]


def default_image_provider_name(*, user_settings: Any = None) -> Optional[str]:
    configured = configured_image_providers(user_settings=user_settings)
    return configured[0].name if configured else None


__all__ = [
    "IMAGE_PROVIDER_ORDER",
    "META_PROVIDER_NAME",
    "GPTIMAGE_PROVIDER_NAME",
    "build_image_provider",
    "configured_image_providers",
    "default_image_provider_name",
    "is_known_image_provider",
    "known_image_provider_names",
    "list_image_provider_capabilities",
    "list_image_providers",
]
