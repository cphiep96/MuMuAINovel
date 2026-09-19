"""场景图片生成 Provider 契约

与 motion video provider（`video_export/providers/`）**刻意分开**：
- 职责不同：这里只负责“把一个分镜的 prompt 变成受管目录里的一张图片”
- 契约更小：`generate_image(request, out_path)` → 返回 `SceneImageResult`
- 能力输出（`capabilities()`）只包含 provider/model/size/cost，**绝不**包含密钥、绝对路径、base64

图片生成结果始终写入任务目录内的 `assets/`，由 `assets.resolve_scene_asset()` 统一读取，
因此客户端永远无法指定路径或 URL。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from app.services.video_export.image_providers.errors import (
    ImageConfigError,
    ImageRequestError,
    sanitize_message,
)

CancelCheck = Callable[[], Awaitable[bool]]

KIND_IMAGE = "image"

# 分镜图片状态（与 motion 状态分开，便于前端区分“图片”和“视频”两段进度）
IMAGE_STATUS_PENDING = "pending"
IMAGE_STATUS_GENERATING = "generating"
IMAGE_STATUS_READY = "ready"
IMAGE_STATUS_FAILED = "failed"
IMAGE_STATUS_CANCELLED = "cancelled"

# 允许的分镜画面比例（与视频输出比例保持一致）
ASPECT_RATIOS = ("16:9", "9:16", "1:1")


@dataclass(frozen=True)
class ImageProviderConfigState:
    """provider 配置状态（只暴露环境变量名，不暴露值）"""

    configured: bool
    missing_config: tuple[str, ...] = ()
    detail: Optional[str] = None


@dataclass(frozen=True)
class ImageRequest:
    """单个分镜的图片生成请求"""

    prompt: str
    aspect_ratio: str
    size: str
    model: Optional[str] = None
    reasoning_strength: Optional[str] = None


@dataclass
class SceneImageResult:
    """生成的场景图片（只记录受管目录内的相对信息）"""

    path: Path
    provider: str
    model: str
    size: str
    mime_type: str
    bytes_written: int


class SceneImageProvider(ABC):
    """场景图片生成 provider 基类"""

    name: str = ""
    label: str = ""
    kind: str = KIND_IMAGE
    description: str = ""
    models: tuple[str, ...] = ()
    default_model: str = ""
    aspect_ratios: tuple[str, ...] = ASPECT_RATIOS
    size_options: tuple[str, ...] = ()
    default_size: str = ""
    output_format: str = "webp"
    cost_note: str = ""
    supports_reasoning_strength: bool = False
    reasoning_strengths: tuple[str, ...] = ()
    max_image_bytes: int = 0

    def configuration(self) -> ImageProviderConfigState:  # pragma: no cover - 由子类实现
        return ImageProviderConfigState(configured=True)

    def require_configured(self) -> None:
        state = self.configuration()
        if not state.configured:
            raise ImageConfigError(
                state.detail or f"Provider ảnh {self.name} chưa được cấu hình trên máy chủ",
                missing_config=state.missing_config,
            )

    def normalize_model(self, value: Optional[str]) -> str:
        candidate = str(value or "").strip()
        if candidate and candidate in self.models:
            return candidate
        if candidate:
            raise ImageRequestError(f"Model ảnh {candidate} không thuộc provider {self.name}")
        return self.default_model or (self.models[0] if self.models else "")

    def normalize_aspect_ratio(self, value: Optional[str]) -> str:
        candidate = str(value or "").strip()
        if candidate and candidate in self.aspect_ratios:
            return candidate
        if candidate:
            raise ImageRequestError(
                f"Tỉ lệ ảnh {candidate} không được provider {self.name} hỗ trợ "
                f"(hỗ trợ: {', '.join(self.aspect_ratios)})"
            )
        return self.aspect_ratios[0]

    def normalize_size(self, value: Optional[str], aspect_ratio: str) -> str:
        """把（可选的）客户端尺寸收敛到 provider 白名单；非法值直接报错"""
        candidate = str(value or "").strip()
        if candidate:
            if candidate not in self.size_options:
                raise ImageRequestError(
                    f"Kích thước ảnh {candidate} không được provider {self.name} hỗ trợ "
                    f"(hỗ trợ: {', '.join(self.size_options)})"
                )
            return candidate
        return self.size_for_aspect(aspect_ratio)

    def size_for_aspect(self, aspect_ratio: str) -> str:
        """按比例给出默认尺寸（子类可覆盖）"""
        return self.default_size or (self.size_options[0] if self.size_options else "")

    def normalize_reasoning_strength(self, value: Optional[str]) -> Optional[str]:
        candidate = str(value or "").strip().lower()
        if not candidate:
            return None
        if not self.supports_reasoning_strength:
            raise ImageRequestError(f"Provider {self.name} không hỗ trợ reasoning strength")
        if self.reasoning_strengths and candidate not in self.reasoning_strengths:
            raise ImageRequestError(
                f"Reasoning strength {candidate} không hợp lệ "
                f"(chấp nhận: {', '.join(self.reasoning_strengths)})"
            )
        return candidate

    def capabilities(self) -> dict[str, Any]:
        """对外能力描述：不含密钥、路径、base64"""
        state = self.configuration()
        return {
            "id": self.name,
            "label": self.label or self.name,
            "kind": self.kind,
            "description": self.description,
            "configured": state.configured,
            "missing_config": list(state.missing_config),
            "config_error": state.detail,
            "models": list(self.models),
            "default_model": self.default_model,
            "aspect_ratios": list(self.aspect_ratios),
            "sizes": list(self.size_options),
            "default_size": self.default_size,
            "output_format": self.output_format,
            "supports_reasoning_strength": self.supports_reasoning_strength,
            "reasoning_strengths": list(self.reasoning_strengths),
            "cost_note": self.cost_note,
        }

    @abstractmethod
    async def generate_image(
        self,
        request: ImageRequest,
        out_path: Path,
        *,
        cancel_check: Optional[CancelCheck] = None,
        timeout: Optional[float] = None,
    ) -> SceneImageResult:
        """生成一张分镜图片并写入 `out_path`（必须做大小/格式校验与原子写入）"""
        raise NotImplementedError


def image_error_detail(exc: Exception) -> str:
    """把异常转换为可直接展示的错误文本（无密钥、无绝对路径）"""
    return sanitize_message(str(exc)) or type(exc).__name__
