"""场景图片 Provider 注册表（与 motion video 注册表相互独立）"""
from __future__ import annotations

from typing import Callable, Optional

from app.services.video_export.image_providers.base import SceneImageProvider
from app.services.video_export.image_providers.errors import ImageConfigError
from app.services.video_export.image_providers.meta_muse_image import MetaMuseImageProvider

META_PROVIDER_NAME = MetaMuseImageProvider.name

IMAGE_PROVIDER_ORDER: tuple[str, ...] = (META_PROVIDER_NAME,)

_FACTORIES: dict[str, Callable[..., SceneImageProvider]] = {
    META_PROVIDER_NAME: MetaMuseImageProvider,
}


def known_image_provider_names() -> tuple[str, ...]:
    return IMAGE_PROVIDER_ORDER


def is_known_image_provider(name: str) -> bool:
    return str(name or "").strip() in _FACTORIES


def build_image_provider(name: str, *, transport=None) -> SceneImageProvider:
    """构建图片 provider；未注册的名字抛 ImageConfigError"""
    key = str(name or "").strip()
    factory = _FACTORIES.get(key)
    if factory is None:
        raise ImageConfigError(
            f"Provider ảnh không được hỗ trợ: {key or '(trống)'}. "
            f"Các provider hợp lệ: {', '.join(IMAGE_PROVIDER_ORDER)}"
        )
    return factory(transport=transport)


def list_image_providers() -> list[SceneImageProvider]:
    return [build_image_provider(name) for name in IMAGE_PROVIDER_ORDER]


def list_image_provider_capabilities() -> list[dict]:
    """全部图片 provider 的能力（含配置状态；不含密钥/路径）"""
    return [provider.capabilities() for provider in list_image_providers()]


def configured_image_providers(
    providers: Optional[list[SceneImageProvider]] = None,
) -> list[SceneImageProvider]:
    items = providers if providers is not None else list_image_providers()
    return [item for item in items if item.configuration().configured]


def default_image_provider_name() -> Optional[str]:
    configured = configured_image_providers()
    return configured[0].name if configured else None


__all__ = [
    "IMAGE_PROVIDER_ORDER",
    "META_PROVIDER_NAME",
    "build_image_provider",
    "configured_image_providers",
    "default_image_provider_name",
    "is_known_image_provider",
    "known_image_provider_names",
    "list_image_provider_capabilities",
    "list_image_providers",
]
