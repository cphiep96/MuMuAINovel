"""视频转场 Provider 包

对外只暴露契约与注册表；具体适配器（xAI / Google Veo / OpenAI 兼容 / 本地 FFmpeg）在各自模块中实现。
"""
from app.services.video_export.providers.base import (
    KIND_LOCAL,
    KIND_REMOTE,
    TERMINAL_STATUSES,
    LocalRenderOptions,
    MotionOperation,
    MotionProvider,
    MotionReference,
    MotionRenderResult,
    MotionRequest,
    ProviderConfigState,
    RemoteMotionProvider,
    provider_error_detail,
)
from app.services.video_export.providers.errors import (
    MotionCancelledError,
    MotionConfigError,
    MotionProviderError,
    MotionRequestError,
    MotionTimeoutError,
    sanitize_message,
)
from app.services.video_export.providers.local_ffmpeg import LocalFFmpegProvider
from app.services.video_export.providers.registry import (
    LOCAL_PROVIDER_NAME,
    PROVIDER_ORDER,
    build_provider,
    configured_remote_providers,
    default_remote_provider_name,
    is_known_provider,
    known_provider_names,
    list_provider_capabilities,
    list_providers,
    provider_config_state,
)

__all__ = [
    "KIND_LOCAL",
    "KIND_REMOTE",
    "LOCAL_PROVIDER_NAME",
    "PROVIDER_ORDER",
    "TERMINAL_STATUSES",
    "LocalFFmpegProvider",
    "LocalRenderOptions",
    "MotionCancelledError",
    "MotionConfigError",
    "MotionOperation",
    "MotionProvider",
    "MotionProviderError",
    "MotionReference",
    "MotionRenderResult",
    "MotionRequest",
    "MotionRequestError",
    "MotionTimeoutError",
    "ProviderConfigState",
    "RemoteMotionProvider",
    "build_provider",
    "configured_remote_providers",
    "default_remote_provider_name",
    "is_known_provider",
    "known_provider_names",
    "list_provider_capabilities",
    "list_providers",
    "provider_config_state",
    "provider_error_detail",
    "sanitize_message",
]
