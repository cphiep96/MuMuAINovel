"""Provider 注册表

- `build_provider(name)`：按名字构建 provider（支持注入 httpx transport 以便测试）
- `list_providers()`：列出所有 provider 及其能力（不含密钥/路径）
- `resolve_motion_provider(name, *, require_remote)`：解析并校验配置，缺配置时抛出 `MotionConfigError`
"""
from __future__ import annotations

from typing import Callable, Iterable, Optional

from app.services.video_export.providers.base import (
    KIND_LOCAL,
    KIND_REMOTE,
    MotionProvider,
    ProviderConfigState,
)
from app.services.video_export.providers.errors import MotionConfigError
from app.services.video_export.providers.google_veo import GoogleVeoProvider
from app.services.video_export.providers.local_ffmpeg import LocalFFmpegProvider
from app.services.video_export.providers.openai_compatible import OpenAICompatibleVideoProvider
from app.services.video_export.providers.xai_grok_imagine import XaiGrokImagineProvider

LOCAL_PROVIDER_NAME = LocalFFmpegProvider.name

PROVIDER_ORDER: tuple[str, ...] = (
    LOCAL_PROVIDER_NAME,
    XaiGrokImagineProvider.name,
    GoogleVeoProvider.name,
    OpenAICompatibleVideoProvider.name,
)

_FACTORIES: dict[str, Callable[..., MotionProvider]] = {
    LOCAL_PROVIDER_NAME: LocalFFmpegProvider,
    XaiGrokImagineProvider.name: XaiGrokImagineProvider,
    GoogleVeoProvider.name: GoogleVeoProvider,
    OpenAICompatibleVideoProvider.name: OpenAICompatibleVideoProvider,
}


def known_provider_names() -> tuple[str, ...]:
    return PROVIDER_ORDER


def is_known_provider(name: str) -> bool:
    return str(name or "").strip() in _FACTORIES


def build_provider(name: str, *, transport=None) -> MotionProvider:
    """构建 provider 实例；未注册的名字抛 MotionConfigError"""
    key = str(name or "").strip()
    factory = _FACTORIES.get(key)
    if factory is None:
        raise MotionConfigError(
            f"Provider video không được hỗ trợ: {key or '(trống)'}. "
            f"Các provider hợp lệ: {', '.join(PROVIDER_ORDER)}"
        )
    if factory is LocalFFmpegProvider:
        return LocalFFmpegProvider()
    return factory(transport=transport)


def list_providers() -> list[MotionProvider]:
    return [build_provider(name) for name in PROVIDER_ORDER]


def list_provider_capabilities() -> list[dict]:
    """全部 provider 的能力描述（含配置状态；不暴露任何密钥值）"""
    return [provider.capabilities() for provider in list_providers()]


def configured_remote_providers(providers: Optional[Iterable[MotionProvider]] = None) -> list[MotionProvider]:
    items = list(providers) if providers is not None else list_providers()
    return [item for item in items if item.kind == KIND_REMOTE and item.configuration().configured]


def default_remote_provider_name() -> Optional[str]:
    configured = configured_remote_providers()
    return configured[0].name if configured else None


def provider_config_state(name: str) -> ProviderConfigState:
    return build_provider(name).configuration()


__all__ = [
    "KIND_LOCAL",
    "KIND_REMOTE",
    "LOCAL_PROVIDER_NAME",
    "MotionProvider",
    "PROVIDER_ORDER",
    "build_provider",
    "configured_remote_providers",
    "default_remote_provider_name",
    "is_known_provider",
    "known_provider_names",
    "list_provider_capabilities",
    "list_providers",
    "provider_config_state",
]
