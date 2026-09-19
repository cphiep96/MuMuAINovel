"""场景图片生成 Provider 包

与 `video_export/providers/`（motion video）严格分开：这里只负责生成“分镜画面”，
生成结果写入任务目录 `assets/`，随后由 motion video provider 作为参考图消费。
"""
from app.services.video_export.image_providers.base import (
    ASPECT_RATIOS,
    IMAGE_STATUS_CANCELLED,
    IMAGE_STATUS_FAILED,
    IMAGE_STATUS_GENERATING,
    IMAGE_STATUS_PENDING,
    IMAGE_STATUS_READY,
    KIND_IMAGE,
    ImageProviderConfigState,
    ImageRequest,
    SceneImageProvider,
    SceneImageResult,
    image_error_detail,
)
from app.services.video_export.image_providers.errors import (
    ImageCancelledError,
    ImageConfigError,
    ImageProviderError,
    ImageRequestError,
    ImageTimeoutError,
)
from app.services.video_export.image_providers.meta_muse_image import (
    MetaMuseImageProvider,
    detect_image_magic,
    output_extension,
    validate_provider_base_url,
)
from app.services.video_export.image_providers.registry import (
    IMAGE_PROVIDER_ORDER,
    META_PROVIDER_NAME,
    build_image_provider,
    configured_image_providers,
    default_image_provider_name,
    is_known_image_provider,
    known_image_provider_names,
    list_image_provider_capabilities,
    list_image_providers,
)
from app.services.video_export.image_providers.user_credentials import (
    image_provider_kwargs_from_settings,
    missing_muse_config_hint,
)

__all__ = [
    "ASPECT_RATIOS",
    "IMAGE_PROVIDER_ORDER",
    "IMAGE_STATUS_CANCELLED",
    "IMAGE_STATUS_FAILED",
    "IMAGE_STATUS_GENERATING",
    "IMAGE_STATUS_PENDING",
    "IMAGE_STATUS_READY",
    "KIND_IMAGE",
    "META_PROVIDER_NAME",
    "ImageCancelledError",
    "ImageConfigError",
    "ImageProviderConfigState",
    "ImageProviderError",
    "ImageRequest",
    "ImageRequestError",
    "ImageTimeoutError",
    "MetaMuseImageProvider",
    "SceneImageProvider",
    "SceneImageResult",
    "build_image_provider",
    "configured_image_providers",
    "default_image_provider_name",
    "detect_image_magic",
    "image_error_detail",
    "is_known_image_provider",
    "known_image_provider_names",
    "list_image_provider_capabilities",
    "list_image_providers",
    "image_provider_kwargs_from_settings",
    "missing_muse_config_hint",
    "output_extension",
    "validate_provider_base_url",
]
