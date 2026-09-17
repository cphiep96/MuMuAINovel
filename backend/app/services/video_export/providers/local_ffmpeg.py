"""本地 FFmpeg provider（兜底）

不调用任何付费 API：有图片时做 Ken Burns（pan/zoom），没有图片时生成渐变/纯色占位背景，
保证成片始终是合法视频。远端 provider 失败时是否回落到这里由上层策略（hybrid）决定。
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from app.config import settings
from app.services.video_export import ffmpeg_runner
from app.services.video_export.providers.base import (
    KIND_LOCAL,
    CancelCheck,
    MotionProvider,
    MotionRenderResult,
    MotionRequest,
    OperationHook,
    ProviderConfigState,
)
from app.services.video_export.providers.errors import MotionRequestError

ALLOWED_FPS = (12, 15, 24, 25, 30)


class LocalFFmpegProvider(MotionProvider):
    """本地 Ken Burns / 占位背景渲染"""

    name = "local_ffmpeg"
    label = "Cục bộ (FFmpeg Ken Burns)"
    kind = KIND_LOCAL
    description = "Dựng chuyển động nhẹ từ ảnh bằng FFmpeg, không gọi API trả phí và không tạo cảnh AI mới."
    models = ("ken_burns",)
    default_model = "ken_burns"
    supports_placeholder = True
    supports_cancel = True
    supports_idempotency = True
    min_duration_seconds = 1.0
    max_duration_seconds = 600.0
    aspect_ratios = ("16:9", "9:16", "1:1")
    resolutions = ("480p", "720p", "1080p")
    default_resolution = "720p"
    cost_note = "Miễn phí: chỉ dùng CPU/GPU của máy chủ, không phát sinh chi phí API."

    def configuration(self) -> ProviderConfigState:
        if not ffmpeg_runner.ffmpeg_binary():
            return ProviderConfigState(
                configured=False,
                missing_config=("VIDEO_FFMPEG_BINARY",),
                detail="FFmpeg chưa được cài đặt trên máy chủ nên không thể dựng video cục bộ.",
            )
        return ProviderConfigState(configured=True)

    async def render_scene(
        self,
        *,
        request: MotionRequest,
        out_path: Path,
        cancel_check: Optional[CancelCheck] = None,
        timeout: Optional[float] = None,
        on_operation: Optional[OperationHook] = None,
    ) -> MotionRenderResult:
        self.require_configured()
        options = request.local
        if options is None:
            raise MotionRequestError("Thiếu tham số dựng cục bộ (kích thước/FPS) cho provider local_ffmpeg")

        await ffmpeg_runner.render_scene_clip(
            out_path=out_path,
            duration=float(request.duration_seconds or settings.video_scene_min_seconds),
            width=int(options.width),
            height=int(options.height),
            fps=int(options.fps),
            image_path=request.reference.path if request.reference and not request.reference.is_placeholder else None,
            audio_path=options.audio_path,
            enable_motion=bool(options.enable_motion),
            cancel_check=cancel_check,
            timeout=timeout,
        )
        return MotionRenderResult(
            clip_path=out_path,
            provider=self.name,
            model=self.default_model,
            duration_seconds=float(request.duration_seconds or 0.0) or None,
        )
