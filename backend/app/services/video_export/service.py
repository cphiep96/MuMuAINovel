"""视频导出服务 - 从章节到分镜、MP4 成片与 SRT 字幕的完整流水线

设计要点：
- 任务立即落库（含分镜），前端可随时查看 storyboard、重试单镜头、下载成片
- 流水线在既有后台任务队列中执行（同一用户串行），可复用 /api/tasks 的进度与取消能力
- 产物只写入受管存储目录，数据库仅保存相对路径，下载时再次做越界校验
- 默认静音成片；TTS 不可用或失败时自动回落，不阻断导出
"""
from __future__ import annotations

import asyncio
import contextlib
import shutil
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import get_engine
from app.logger import get_logger
from app.models.background_task import BackgroundTask
from app.models.chapter import Chapter
from app.models.project import Project
from app.models.settings import Settings
from app.models.video_export import VideoExportJob, VideoExportScene
from app.services.background_task_service import background_task_service
from app.services.video_export import ffmpeg_runner
from app.services.video_export.assets import (
    ALLOWED_IMAGE_SUFFIXES,
    ASSET_KIND_PLACEHOLDER,
    SceneAsset,
    resolve_cover_image,
    resolve_scene_asset,
)
from app.services.video_export.ffmpeg_runner import (
    FFmpegCancelledError,
    FFmpegExecutionError,
    FFmpegUnavailableError,
)
from app.services.video_export.image_providers import (
    IMAGE_STATUS_CANCELLED,
    IMAGE_STATUS_FAILED,
    IMAGE_STATUS_GENERATING,
    IMAGE_STATUS_PENDING,
    IMAGE_STATUS_READY,
    META_PROVIDER_NAME,
    ImageCancelledError,
    ImageConfigError,
    ImageProviderError,
    ImageRequest,
    ImageRequestError,
    ImageTimeoutError,
    SceneImageProvider,
    build_image_provider,
    default_image_provider_name,
    image_error_detail,
    is_known_image_provider,
    list_image_provider_capabilities,
    missing_muse_config_hint,
    output_extension,
)
from app.services.video_export.paths import (
    VIDEO_STORAGE_DIR,
    job_directory,
    job_directory_path,
    normalize_relative_path,
    resolve_stored_path,
)
from app.services.video_export.providers import (
    KIND_REMOTE,
    LOCAL_PROVIDER_NAME,
    LocalRenderOptions,
    MotionCancelledError,
    MotionConfigError,
    MotionOperation,
    MotionProvider,
    MotionProviderError,
    MotionReference,
    MotionRequest,
    MotionRequestError,
    MotionTimeoutError,
    build_provider,
    default_remote_provider_name,
    is_known_provider,
    list_provider_capabilities,
    provider_error_detail,
)
from app.services.video_export.continuity import build_continuity_storyboard
from app.services.video_export.scene_audio import replace_scene_audio
from app.services.video_export.storyboard import (
    DEFAULT_CHARS_PER_SECOND,
    DEFAULT_NARRATION_CHARS,
    MIN_NARRATION_CHARS,
    MAX_NARRATION_CHARS,
    SourceChapter,
    StoryboardOptions,
    build_storyboard,
    validate_storyboard_limits,
)
from app.services.video_export.subtitles import build_srt_from_scenes
from app.services.video_export.tts import (
    TTS_PROVIDERS,
    NullTTSEngine,
    build_tts_engine,
    default_tts_model,
    default_tts_provider_name,
    list_tts_provider_capabilities,
    missing_tts_config_hint,
    prefer_native_language_engine,
    tts_configured,
)

logger = get_logger(__name__)

TASK_TYPE = "video_export"
CLIPS_DIRNAME = "clips"
ASSETS_DIRNAME = "assets"
FINAL_VIDEO_NAME = "output.mp4"
SUBTITLED_VIDEO_NAME = "output_subtitled.mp4"
SUBTITLE_NAME = "subtitles.srt"

DOWNLOAD_KIND_VIDEO = "video"
DOWNLOAD_KIND_SUBTITLES = "subtitles"

# 转场模式：local 完全本地；remote 必须使用远端 provider；hybrid 远端优先、可按策略回落本地
MOTION_MODE_LOCAL = "local"
MOTION_MODE_REMOTE = "remote"
MOTION_MODE_HYBRID = "hybrid"
MOTION_MODES = (MOTION_MODE_LOCAL, MOTION_MODE_REMOTE, MOTION_MODE_HYBRID)

# 远端操作状态
MOTION_STATUS_PENDING = "pending"
MOTION_STATUS_RUNNING = "running"
MOTION_STATUS_COMPLETED = "completed"
MOTION_STATUS_FAILED = "failed"
MOTION_STATUS_CANCELLED = "cancelled"
MOTION_STATUS_SKIPPED = "skipped"
# 远端操作可能仍然存活（或状态未知）的状态：重试时必须续跑同一个 operation，避免重复计费
RESUME_MOTION_STATUSES = frozenset(
    {MOTION_STATUS_PENDING, MOTION_STATUS_RUNNING, MOTION_STATUS_CANCELLED}
)

# 正在本进程内执行流水线的任务ID：删除/清理时必须先确认这些任务已停止
RUNNING_JOB_IDS: set[str] = set()
# 延迟清理任务（等待正在运行的 FFmpeg 释放文件后再删除目录）
_PENDING_CLEANUPS: set[asyncio.Task] = set()


def _monotonic() -> float:
    """单调时钟（单独封装，便于测试注入时间流逝）"""
    return time.monotonic()


class JobCancelledError(RuntimeError):
    """任务在执行过程中被取消"""


class JobTimeoutError(RuntimeError):
    """任务整体耗时超过配置的墙钟上限"""


class SceneRenderError(RuntimeError):
    """部分分镜渲染失败（可单独重试）"""


def _allowed_resolutions() -> list[str]:
    return [item.strip() for item in settings.video_allowed_resolutions.split(",") if item.strip()]


def _allowed_fps() -> list[int]:
    values: list[int] = []
    for item in settings.video_allowed_fps.split(","):
        item = item.strip()
        if item.isdigit():
            values.append(int(item))
    return values or [settings.video_default_fps]


def parse_resolution(resolution: str) -> tuple[int, int]:
    """把 `宽x高` 解析为像素尺寸，非法值直接报错"""
    try:
        width_text, height_text = resolution.lower().split("x", 1)
        width, height = int(width_text), int(height_text)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(status_code=400, detail="Độ phân giải không hợp lệ") from exc
    if not (160 <= width <= 3840 and 160 <= height <= 2160):
        raise HTTPException(status_code=400, detail="Độ phân giải nằm ngoài phạm vi cho phép")
    return width, height


def normalize_options(
    raw: Optional[dict[str, Any]],
    *,
    user_settings: Any = None,
) -> dict[str, Any]:
    """校验并补全导出参数"""
    data = dict(raw or {})

    resolution = str(data.get("resolution") or settings.video_default_resolution).lower().strip()
    allowed_resolutions = _allowed_resolutions()
    if resolution not in allowed_resolutions:
        raise HTTPException(
            status_code=400,
            detail=f"Độ phân giải không được hỗ trợ, chỉ chấp nhận: {', '.join(allowed_resolutions)}",
        )
    parse_resolution(resolution)

    try:
        fps = int(data.get("fps") or settings.video_default_fps)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="FPS không hợp lệ") from exc
    if fps not in _allowed_fps():
        raise HTTPException(
            status_code=400,
            detail=f"FPS không được hỗ trợ, chỉ chấp nhận: {', '.join(str(v) for v in _allowed_fps())}",
        )

    try:
        chars_per_scene = int(data.get("narration_chars_per_scene") or DEFAULT_NARRATION_CHARS)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Số ký tự mỗi phân cảnh không hợp lệ") from exc
    if not (MIN_NARRATION_CHARS <= chars_per_scene <= MAX_NARRATION_CHARS):
        raise HTTPException(
            status_code=400,
            detail=f"Số ký tự mỗi phân cảnh phải nằm trong khoảng {MIN_NARRATION_CHARS}-{MAX_NARRATION_CHARS}",
        )

    try:
        chars_per_second = float(data.get("chars_per_second") or DEFAULT_CHARS_PER_SECOND)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="Tốc độ đọc không hợp lệ") from exc

    tts_enabled = bool(data.get("tts_enabled", False))
    if tts_enabled and not tts_configured(user_settings=user_settings):
        raise HTTPException(
            status_code=400,
            detail=missing_tts_config_hint(),
        )

    tts_provider = str(data.get("tts_provider") or "").strip().lower() or None
    if tts_provider in {"edge", "microsoft", "edge_tts"}:
        tts_provider = "omnivoice"
    if tts_provider and tts_provider not in TTS_PROVIDERS:
        raise HTTPException(
            status_code=400,
            detail=f"Provider TTS không hỗ trợ, chỉ chấp nhận: {', '.join(TTS_PROVIDERS)}",
        )
    tts_model = str(data.get("tts_model") or "").strip() or None

    muse = data.get("motion_provider") == "muse_tool" or (not data.get("motion_provider") and settings.video_motion_provider == "muse_tool")
    storyboard_mode = data.get("storyboard_mode") or ("continuity" if muse else "legacy")
    if storyboard_mode not in ("legacy", "continuity"):
        raise HTTPException(400, "Chế độ storyboard không hợp lệ")
    audio_mode = data.get("muse_audio_mode") or ("silent" if muse else None)
    if audio_mode is not None and audio_mode not in ("native", "ambience", "silent"):
        raise HTTPException(400, "Chế độ âm thanh Muse không hợp lệ")
    if tts_enabled and muse:
        audio_mode = "silent"
    return {
        "storyboard_mode": storyboard_mode,
        "muse_audio_mode": audio_mode,
        "resolution": resolution,
        "fps": fps,
        "use_project_cover": bool(data.get("use_project_cover", True)),
        "tts_enabled": tts_enabled,
        "tts_provider": tts_provider,
        "tts_model": tts_model,
        "narration_chars_per_scene": chars_per_scene,
        "chars_per_second": char_speed_clamp(chars_per_second),
    }


def char_speed_clamp(value: float) -> float:
    """限制朗读速度，避免出现极短或极长的分镜"""
    return max(4.0, min(float(value or DEFAULT_CHARS_PER_SECOND), 40.0))


def build_scene_idempotency_key(job_id: str, scene_index: int) -> str:
    """每个分镜一个稳定幂等键：同一分镜的重复 HTTP 提交不会产生第二个远端任务"""
    return f"{job_id}:{scene_index}"


def renew_scene_idempotency_key(job_id: str, scene_index: int) -> str:
    """用户主动重试时更换幂等键，允许生成新的远端任务（避免复用旧操作的结果）"""
    return f"{job_id}:{scene_index}:{uuid.uuid4().hex[:12]}"


def _scene_image_file(workdir: Path, scene: VideoExportScene) -> Path:
    """定位分镜图片文件（优先使用 DB 中的相对路径，否则按约定文件名查找）"""
    if scene.image_path:
        try:
            return resolve_stored_path(workdir, scene.image_path)
        except HTTPException:
            logger.warning("分镜图片路径异常，忽略并按约定名查找: scene=%s", scene.scene_index)
    assets_dir = workdir / ASSETS_DIRNAME
    for suffix in ALLOWED_IMAGE_SUFFIXES:
        candidate = assets_dir / f"scene_{scene.scene_index:03d}{suffix}"
        if candidate.is_file():
            return candidate
    return assets_dir / f"scene_{scene.scene_index:03d}.webp"


def _http_error_from_motion(exc: Exception) -> HTTPException:
    """把 provider 层异常映射为 API 错误码：配置问题 503，参数问题 400"""
    if isinstance(exc, MotionConfigError):
        missing = ", ".join(exc.missing_config) if exc.missing_config else ""
        detail = str(exc)
        if missing:
            detail = f"{detail} Biến môi trường còn thiếu: {missing}."
        return HTTPException(status_code=503, detail=detail)
    if isinstance(exc, MotionRequestError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=503, detail=provider_error_detail(exc))


def resolve_motion_provider(name: str) -> MotionProvider:
    """构建 provider 并校验配置（缺配置时抛 HTTPException 503，绝不静默降级）"""
    try:
        provider = build_provider(name)
    except MotionConfigError as exc:
        raise _http_error_from_motion(exc) from exc
    if not provider.configuration().configured:
        raise _http_error_from_motion(
            MotionConfigError(
                provider.configuration().detail or f"Provider {name} chưa được cấu hình",
                missing_config=provider.configuration().missing_config,
            )
        )
    return provider


def normalize_motion_options(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    """校验转场模式/provider/model/分辨率等参数

    - `local`：强制使用本地 FFmpeg（忽略远端字段，避免误以为会调用 API）
    - `remote`：必须指定（或能推导出）已配置的远端 provider，否则直接 503 报出缺失的环境变量
    - `hybrid`：远端优先，`hybrid_fallback_on_error` 明确控制是否允许回落本地
    """
    data = dict(raw or {})
    mode = str(data.get("motion_mode") or settings.video_motion_mode or MOTION_MODE_LOCAL).strip().lower()
    if mode not in MOTION_MODES:
        raise HTTPException(
            status_code=400,
            detail=f"Chế độ chuyển động không hợp lệ, chỉ chấp nhận: {', '.join(MOTION_MODES)}",
        )

    fallback_raw = data.get("hybrid_fallback_on_error")
    fallback = (
        bool(settings.video_motion_hybrid_fallback_on_error)
        if fallback_raw is None
        else bool(fallback_raw)
    )

    if mode == MOTION_MODE_LOCAL:
        return {
            "motion_mode": MOTION_MODE_LOCAL,
            "motion_provider": None,
            "motion_model": None,
            "motion_resolution": None,
            "motion_aspect_ratio": None,
            "hybrid_fallback_on_error": False,
        }

    requested = str(data.get("motion_provider") or "").strip()
    if requested and not is_known_provider(requested):
        raise HTTPException(status_code=400, detail=f"Provider video không được hỗ trợ: {requested}")

    name = requested or (settings.video_motion_provider or "").strip() or default_remote_provider_name() or ""
    if not name:
        raise HTTPException(
            status_code=503,
            detail=(
                "Chưa có provider video nào được cấu hình trên máy chủ. "
                "Hãy đặt API key của xAI/Gemini/OpenAI compatible rồi thử lại, hoặc chọn chế độ cục bộ."
            ),
        )
    provider = resolve_motion_provider(name)
    if provider.kind != KIND_REMOTE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Chế độ {mode} cần provider tạo video từ xa, nhưng '{name}' là provider cục bộ. "
                "Hãy chọn chế độ local hoặc một provider remote."
            ),
        )

    default_model = settings.video_motion_model or None
    aspect_hint = data.get("motion_aspect_ratio") or _aspect_from_resolution(data.get("resolution"))
    try:
        model = provider.normalize_model(data.get("motion_model") or default_model)
        # 限制按模型区分（例如 Veo 3.1 只接受 8 秒、Lite 不支持 4k），
        # 这里提前校验，避免 UI 提交必然被 provider 拒绝的组合
        resolution = provider.normalize_resolution(
            data.get("motion_resolution") or settings.video_motion_resolution, model
        )
        aspect_ratio = provider.normalize_aspect_ratio(aspect_hint, model)
    except MotionRequestError as exc:
        raise _http_error_from_motion(exc) from exc

    return {
        "motion_mode": mode,
        "motion_provider": provider.name,
        "motion_model": model,
        "motion_resolution": resolution,
        "motion_aspect_ratio": aspect_ratio,
        "hybrid_fallback_on_error": bool(fallback) if mode == MOTION_MODE_HYBRID else False,
    }


def _aspect_from_resolution(resolution: Optional[str]) -> str:
    """由输出分辨率推导画面比例（宽 ≥ 高 => 16:9，否则 9:16）"""
    value = str(resolution or settings.video_default_resolution).lower()
    try:
        width_text, height_text = value.split("x", 1)
        return "16:9" if int(width_text) >= int(height_text) else "9:16"
    except (ValueError, AttributeError):
        return "16:9"


def motion_provider_status(name: Optional[str]) -> Optional[dict[str, Any]]:
    """单个 provider 的对外能力快照（供任务详情展示配置健康度）"""
    if not name:
        return None
    for item in list_provider_capabilities():
        if item["id"] == name:
            return item
    return None


def _http_error_from_image(exc: Exception) -> HTTPException:
    """把图片 provider 的异常映射为 API 错误码：配置问题 503，参数问题 400

    所有分支都经过 sanitize：错误消息可能直接回给客户端，不得包含 key/URL/path。
    """
    if isinstance(exc, ImageConfigError):
        detail = image_error_detail(exc) or missing_muse_config_hint()
        return HTTPException(status_code=503, detail=detail)
    if isinstance(exc, ImageRequestError):
        return HTTPException(status_code=400, detail=image_error_detail(exc))
    return HTTPException(status_code=503, detail=image_error_detail(exc))


async def load_user_image_settings(db: AsyncSession, user_id: str) -> Optional[Settings]:
    if not user_id:
        return None
    result = await db.execute(select(Settings).where(Settings.user_id == user_id))
    return result.scalar_one_or_none()


def resolve_image_provider(name: str, *, user_settings: Any = None) -> SceneImageProvider:
    """构建图片 provider 并校验配置（缺配置时 503，绝不静默换 provider）"""
    try:
        provider = build_image_provider(name, user_settings=user_settings)
    except ImageConfigError as exc:
        raise _http_error_from_image(exc) from exc
    state = provider.configuration()
    if not state.configured:
        raise _http_error_from_image(
            ImageConfigError(
                missing_muse_config_hint(),
                missing_config=state.missing_config,
            )
        )
    return provider


def normalize_image_options(
    raw: Optional[dict[str, Any]],
    *,
    user_settings: Any = None,
) -> dict[str, Any]:
    """校验“生成场景图”相关参数

    - 未开启：全部字段为 None，pipeline 保持旧行为（ảnh cảnh thủ công → cover → placeholder）
    - 已开启：provider 必须已配置（否则 503 并列出缺失的环境变量），尺寸/比例/reasoning 全部走白名单
    - 绝不自动 fallback sang provider ảnh khác
    """
    data = dict(raw or {})
    enabled = bool(data.get("generate_scene_images", False))
    if not enabled:
        return {
            "generate_scene_images": False,
            "image_provider": None,
            "image_model": None,
            "image_aspect_ratio": None,
            "image_size": None,
            "image_reasoning_strength": None,
        }

    if not settings.video_image_enabled:
        raise HTTPException(
            status_code=503,
            detail="Chức năng tạo ảnh phân cảnh đang bị tắt trên máy chủ này (VIDEO_IMAGE_ENABLED=false)",
        )

    requested = str(data.get("image_provider") or "").strip()
    if requested and not is_known_image_provider(requested):
        raise HTTPException(status_code=400, detail=f"Provider ảnh không được hỗ trợ: {requested}")

    name = (
        requested
        or (settings.video_image_provider or "").strip()
        or default_image_provider_name(user_settings=user_settings)
        or META_PROVIDER_NAME
    )
    if not name:
        raise HTTPException(status_code=503, detail=missing_muse_config_hint())
    provider = resolve_image_provider(name, user_settings=user_settings)

    aspect_hint = (
        data.get("image_aspect_ratio")
        or settings.video_image_aspect_ratio
        or _aspect_from_resolution(data.get("resolution"))
    )
    try:
        requested_model = data.get("image_model") or settings.video_image_model
        if requested_model and requested_model not in provider.models:
            requested_model = None
        model = provider.normalize_model(requested_model)
        aspect_ratio = provider.normalize_aspect_ratio(aspect_hint)
        size = provider.normalize_size(data.get("image_size"), aspect_ratio)
        reasoning_raw = data.get("image_reasoning_strength")
        if reasoning_raw is None and provider.supports_reasoning_strength:
            reasoning_raw = settings.video_image_reasoning_strength
        reasoning = provider.normalize_reasoning_strength(reasoning_raw)
    except ImageRequestError as exc:
        raise _http_error_from_image(exc) from exc

    return {
        "generate_scene_images": True,
        "image_provider": provider.name,
        "image_model": model,
        "image_aspect_ratio": aspect_ratio,
        "image_size": size,
        "image_reasoning_strength": reasoning,
    }


def serialize_scene(scene: VideoExportScene) -> dict[str, Any]:
    return {
        "id": scene.id,
        "job_id": scene.job_id,
        "scene_index": scene.scene_index,
        "chapter_id": scene.chapter_id,
        "chapter_number": scene.chapter_number,
        "title": scene.title,
        "narration": scene.narration,
        "duration_seconds": round(float(scene.duration_seconds or 0.0), 1),
        "visual_prompt": scene.visual_prompt,
        "asset_kind": scene.asset_kind,
        "status": scene.status,
        "error_message": scene.error_message,
        "clip_ready": bool(scene.status == "ready"),
        # 转场元数据：只暴露 provider/模型/状态，绝不返回远端 URL、凭证或 operation id
        # （operation id 仍保存在数据库用于断点续跑，但不属于公开响应的一部分）
        "motion_provider": scene.motion_provider,
        "motion_model": scene.motion_model,
        "motion_status": scene.motion_status,
        "motion_fallback_used": bool(scene.motion_fallback_used),
        "provider_error": scene.provider_error,
        "clip_duration_seconds": (
            round(float(scene.clip_duration_seconds), 1)
            if scene.clip_duration_seconds is not None
            else None
        ),
        # 场景图元数据：不含 base64、prompt、密钥、远端 URL 或文件系统路径
        "image_provider": scene.image_provider,
        "image_model": scene.image_model,
        "image_status": scene.image_status,
        "image_error": scene.image_error,
        "image_size": scene.image_size,
        "has_image": scene.image_status == IMAGE_STATUS_READY,
    }


def _job_motion_mode(job: VideoExportJob) -> str:
    """兼容旧任务：没有 motion_mode 列时按 options 推断，最终回落到 local"""
    mode = (job.motion_mode or "").strip().lower()
    if mode in MOTION_MODES:
        return mode
    option_mode = str((job.options or {}).get("motion_mode") or "").strip().lower()
    return option_mode if option_mode in MOTION_MODES else MOTION_MODE_LOCAL


def serialize_job(job: VideoExportJob, scenes: Optional[Sequence[VideoExportScene]] = None) -> dict[str, Any]:
    return {
        "id": job.id,
        "project_id": job.project_id,
        "status": job.status,
        "progress": int(job.progress or 0),
        "status_message": job.status_message,
        "error_message": job.error_message,
        "chapter_ids": list(job.chapter_ids or []),
        "options": dict(job.options or {}),
        "motion_mode": _job_motion_mode(job),
        "motion_provider": job.motion_provider,
        "motion_model": job.motion_model,
        "image_provider": job.image_provider,
        "image_model": job.image_model,
        "scene_count": int(job.scene_count or 0),
        "duration_seconds": round(float(job.duration_seconds or 0.0), 1),
        "video_size_bytes": job.video_size_bytes,
        "has_video": bool(job.video_path),
        "has_subtitles": bool(job.subtitle_path),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
        "scenes": [serialize_scene(scene) for scene in scenes] if scenes is not None else [],
    }


class VideoExportService:
    """章节 → 分镜 → MP4/SRT 的导出服务"""

    # ------------------------------------------------------------------ 能力与校验

    @staticmethod
    def ensure_enabled() -> None:
        if not settings.video_export_enabled:
            raise HTTPException(status_code=503, detail="Chức năng xuất phim đang bị tắt trên máy chủ này")

    @staticmethod
    def ensure_ffmpeg() -> str:
        binary = ffmpeg_runner.ffmpeg_binary()
        if not binary:
            raise HTTPException(
                status_code=503,
                detail=(
                    "FFmpeg chưa được cài đặt trên máy chủ, không thể dựng video. "
                    "Hãy cài FFmpeg (hoặc đặt biến môi trường VIDEO_FFMPEG_BINARY) rồi thử lại."
                ),
            )
        return binary

    def capabilities(self, *, user_settings: Any = None) -> dict[str, Any]:
        """返回当前实例的导出能力，便于前端做降级提示

        注意：不返回 FFmpeg 的绝对路径，避免泄露服务端目录结构。
        """
        image_provider_name = settings.video_image_provider or default_image_provider_name(
            user_settings=user_settings
        )
        default_image_aspect = settings.video_image_aspect_ratio
        default_image_size: Optional[str] = None
        if image_provider_name:
            try:
                image_provider = build_image_provider(
                    image_provider_name, user_settings=user_settings
                )
                default_image_aspect = default_image_aspect or image_provider.aspect_ratios[0]
                default_image_size = image_provider.size_for_aspect(default_image_aspect)
            except ImageConfigError:
                default_image_size = None
        return {
            "enabled": bool(settings.video_export_enabled),
            "ffmpeg_available": bool(ffmpeg_runner.ffmpeg_binary()),
            "tts_available": tts_configured(user_settings=user_settings),
            "default_tts_provider": default_tts_provider_name(user_settings),
            "default_tts_model": default_tts_model(user_settings),
            "tts_hint": missing_tts_config_hint(),
            "tts_providers": list_tts_provider_capabilities(user_settings),
            "allowed_resolutions": _allowed_resolutions(),
            "default_resolution": settings.video_default_resolution,
            "allowed_fps": _allowed_fps(),
            "default_fps": settings.video_default_fps,
            "max_chapters": settings.video_max_chapters,
            "max_scenes": settings.video_max_scenes,
            "max_duration_seconds": settings.video_max_duration_seconds,
            "max_output_mb": settings.video_max_output_mb,
            "max_active_jobs": settings.video_max_active_jobs,
            "job_timeout_seconds": settings.video_job_timeout_seconds,
            "scene_duration_range": [
                settings.video_scene_min_seconds,
                settings.video_scene_max_seconds,
            ],
            "narration_chars_range": [MIN_NARRATION_CHARS, MAX_NARRATION_CHARS],
            "default_narration_chars_per_scene": DEFAULT_NARRATION_CHARS,
            # 转场能力：只暴露 provider 名称、模型、限制与配置状态，密钥与路径永不出现在响应里
            "motion_modes": list(MOTION_MODES),
            "default_motion_mode": settings.video_motion_mode,
            "default_motion_provider": settings.video_motion_provider or default_remote_provider_name(),
            "default_motion_model": settings.video_motion_model,
            "default_motion_resolution": settings.video_motion_resolution,
            "hybrid_fallback_on_error": bool(settings.video_motion_hybrid_fallback_on_error),
            "remote_tts_supported": True,
            "motion_providers": list_provider_capabilities(),
            # 场景图能力：只暴露 provider 名称、模型、尺寸与缺失的 env 名，绝不含密钥/路径
            "image_enabled": bool(settings.video_image_enabled),
            "default_image_provider": image_provider_name,
            "default_image_model": settings.video_image_model,
            "default_image_aspect_ratio": default_image_aspect,
            "default_image_size": default_image_size,
            "image_max_mb": settings.video_image_max_mb,
            "image_providers": list_image_provider_capabilities(user_settings=user_settings),
        }

    # ------------------------------------------------------------------ 查询

    async def _load_project(self, *, db: AsyncSession, user_id: str, project_id: str) -> Project:
        if not user_id:
            raise HTTPException(status_code=401, detail="Chưa đăng nhập")
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        project = result.scalar_one_or_none()
        if not project:
            raise HTTPException(status_code=404, detail="Dự án không tồn tại hoặc không có quyền truy cập")
        return project

    async def _get_job(self, *, db: AsyncSession, user_id: str, job_id: str) -> VideoExportJob:
        result = await db.execute(
            select(VideoExportJob).where(
                VideoExportJob.id == job_id,
                VideoExportJob.user_id == user_id,
            )
        )
        job = result.scalar_one_or_none()
        if not job:
            raise HTTPException(status_code=404, detail="Tác vụ xuất phim không tồn tại")
        return job

    async def _get_scenes(self, *, db: AsyncSession, job_id: str) -> list[VideoExportScene]:
        result = await db.execute(
            select(VideoExportScene)
            .where(VideoExportScene.job_id == job_id)
            .order_by(VideoExportScene.scene_index)
        )
        return list(result.scalars().all())

    async def list_jobs(
        self, *, db: AsyncSession, user_id: str, project_id: str, limit: int = 20
    ) -> list[VideoExportJob]:
        await self._load_project(db=db, user_id=user_id, project_id=project_id)
        result = await db.execute(
            select(VideoExportJob)
            .where(
                VideoExportJob.project_id == project_id,
                VideoExportJob.user_id == user_id,
            )
            .order_by(VideoExportJob.created_at.desc())
            .limit(max(1, min(int(limit or 20), 50)))
        )
        return list(result.scalars().all())

    async def get_job_detail(
        self, *, db: AsyncSession, user_id: str, job_id: str
    ) -> tuple[VideoExportJob, list[VideoExportScene]]:
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        scenes = await self._get_scenes(db=db, job_id=job.id)
        return job, scenes

    # ------------------------------------------------------------------ 创建

    async def _ensure_active_quota(
        self, *, db: AsyncSession, user_id: str, exclude_job_id: Optional[str] = None
    ) -> None:
        """限制单个用户同时存在的未完成导出任务数，避免占满磁盘与 FFmpeg 资源

        `exclude_job_id`：重试场景下排除当前任务本身（它即将回到 pending，不应把自己算进配额）。
        """
        limit = max(int(settings.video_max_active_jobs), 1)
        conditions = [
            VideoExportJob.user_id == user_id,
            VideoExportJob.status.in_(("pending", "running")),
        ]
        if exclude_job_id:
            conditions.append(VideoExportJob.id != exclude_job_id)
        result = await db.execute(select(func.count(VideoExportJob.id)).where(*conditions))
        active = int(result.scalar_one() or 0)
        if active >= limit:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Bạn đang có {active} tác vụ xuất phim chưa hoàn tất (giới hạn {limit}). "
                    "Vui lòng chờ hoàn thành hoặc hủy bớt trước khi tạo tác vụ mới."
                ),
            )

    async def _load_source_chapters(
        self, *, db: AsyncSession, project_id: str, chapter_ids: Sequence[str]
    ) -> list[SourceChapter]:
        ordered_ids = list(dict.fromkeys(chapter_ids))
        result = await db.execute(
            select(Chapter)
            .where(Chapter.project_id == project_id, Chapter.id.in_(ordered_ids))
            .order_by(Chapter.chapter_number)
        )
        chapters = list(result.scalars().all())
        if len(chapters) != len(ordered_ids):
            raise HTTPException(status_code=404, detail="Một số chương không tồn tại trong dự án này")

        empty = [chapter for chapter in chapters if not (chapter.content or "").strip()]
        if empty:
            numbers = ", ".join(str(chapter.chapter_number) for chapter in empty[:5])
            raise HTTPException(
                status_code=400,
                detail=f"Chương {numbers} chưa có nội dung, vui lòng viết nội dung trước khi xuất phim",
            )
        return [
            SourceChapter(
                id=chapter.id,
                chapter_number=chapter.chapter_number,
                title=chapter.title,
                content=chapter.content or "",
            )
            for chapter in chapters
        ]

    @staticmethod
    def _ensure_remote_reference_available(
        *,
        project: Project,
        normalized: dict[str, Any],
        motion: dict[str, Any],
        image: Optional[dict[str, Any]] = None,
    ) -> None:
        """远端 provider 只接受真实图片：建任务前就检查参考画面是否存在

        - 本地模式可以生成占位背景，但远端 image-to-video 不接受占位图
        - 若已开启“生成场景图”（image provider），每个分镜都会有真实参考图 → 不再要求项目封面
        - hybrid 允许回落本地占位背景，仅提示而非阻断
        """
        if normalized.get("tts_enabled") and motion.get("motion_provider") != "muse_tool":
            raise HTTPException(
                status_code=400,
                detail=(
                    "Chế độ remote/hybrid không ghép giọng đọc TTS vào clip do provider trả về. "
                    "Hãy tắt giọng đọc hoặc dùng chế độ cục bộ."
                ),
            )
        if build_provider(motion["motion_provider"]).supports_placeholder:
            # Text-to-video providers do not require a project cover.
            return
        if image and image.get("generate_scene_images"):
            # 每个分镜都会先生成 ảnh 场景 → 一定有参考图
            return
        if motion["motion_mode"] == MOTION_MODE_HYBRID:
            # hybrid 允许回落本地占位背景，仅提示而非阻断
            return
        if not normalized.get("use_project_cover", True):
            raise HTTPException(
                status_code=400,
                detail=(
                    "Chế độ remote cần ảnh tham chiếu cho từng phân cảnh. "
                    "Hãy bật 'Dùng ảnh bìa làm hình nền' hoặc bật tạo ảnh phân cảnh bằng provider ảnh."
                ),
            )
        if resolve_cover_image(project.cover_image_url, project.cover_status) is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Dự án chưa có ảnh bìa khả dụng nên không thể tạo video bằng provider remote "
                    "(provider không nhận ảnh placeholder). Hãy tạo ảnh bìa cho dự án, bật tạo ảnh phân cảnh, "
                    "hoặc chọn chế độ cục bộ / kết hợp."
                ),
            )

    async def preview_storyboard(self, *, db, user_id, project_id, chapter_ids, options=None):
        self.ensure_enabled()
        await self._load_project(db=db, user_id=user_id, project_id=project_id)
        if not chapter_ids or len(chapter_ids) > settings.video_max_chapters:
            raise HTTPException(400, "Số chương không hợp lệ")
        user_settings = await load_user_image_settings(db, user_id)
        normalized = normalize_options(options, user_settings=user_settings)
        chapters = await self._load_source_chapters(db=db, project_id=project_id, chapter_ids=chapter_ids)
        storyboard_options = StoryboardOptions(narration_chars_per_scene=normalized["narration_chars_per_scene"],
            chars_per_second=normalized["chars_per_second"], resolution=normalized["resolution"], fps=normalized["fps"])
        scenes, directions, stamp = build_continuity_storyboard(chapters, storyboard_options)
        duration = validate_storyboard_limits(scenes)
        return {"fingerprint": stamp, "scene_count": len(scenes), "duration_seconds": duration,
            "scenes": [{"scene_index": s.scene_index, "narration": s.narration, "direction": directions[i]}
                       for i, s in enumerate(scenes)]}

    async def create_job(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        project_id: str,
        chapter_ids: Sequence[str],
        options: Optional[dict[str, Any]] = None,
    ) -> VideoExportJob:
        self.ensure_enabled()
        self.ensure_ffmpeg()
        project = await self._load_project(db=db, user_id=user_id, project_id=project_id)

        if not chapter_ids:
            raise HTTPException(status_code=400, detail="Vui lòng chọn ít nhất một chương để xuất phim")
        if len(chapter_ids) > settings.video_max_chapters:
            raise HTTPException(
                status_code=400,
                detail=f"Mỗi tác vụ chỉ nhận tối đa {settings.video_max_chapters} chương",
            )

        await self._ensure_active_quota(db=db, user_id=user_id)

        user_settings = await load_user_image_settings(db, user_id)
        normalized = normalize_options(options, user_settings=user_settings)
        # 转场参数在这里校验：远端模式缺凭证会立刻 503，不会先建任务再失败
        motion = normalize_motion_options(options)
        # 场景图参数：ưu tiên key Muse trên trang Cài đặt, env chỉ là fallback
        image = normalize_image_options(options, user_settings=user_settings)
        if motion["motion_mode"] != MOTION_MODE_LOCAL:
            self._ensure_remote_reference_available(
                project=project, normalized=normalized, motion=motion, image=image
            )
        normalized.update(motion)
        normalized.update(image)

        chapters = await self._load_source_chapters(db=db, project_id=project.id, chapter_ids=chapter_ids)
        storyboard_options = StoryboardOptions(
            narration_chars_per_scene=normalized["narration_chars_per_scene"],
            chars_per_second=normalized["chars_per_second"],
            resolution=normalized["resolution"],
            fps=normalized["fps"],
        )
        if normalized.get("storyboard_mode") == "continuity":
            scenes, directions, stamp = build_continuity_storyboard(chapters, storyboard_options,
                reviewed_plan=(options or {}).get("shot_plan"),
                reviewed_fingerprint=(options or {}).get("storyboard_fingerprint"))
            normalized["shot_plan"] = [{"scene_index": s.scene_index, "direction": directions[i]}
                                     for i, s in enumerate(scenes)]
            normalized["storyboard_fingerprint"] = stamp
        else:
            if (options or {}).get("shot_plan") is not None:
                raise HTTPException(400, "Storyboard đã duyệt cần chế độ continuity")
            scenes = build_storyboard(chapters, storyboard_options)
        total_duration = validate_storyboard_limits(scenes)

        job = VideoExportJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            project_id=project.id,
            status="pending",
            progress=0,
            status_message="Đã tạo phân cảnh, đang chờ dựng phim...",
            chapter_ids=[chapter.id for chapter in chapters],
            options=normalized,
            motion_mode=motion["motion_mode"],
            motion_provider=motion["motion_provider"],
            motion_model=motion["motion_model"],
            image_provider=image["image_provider"],
            image_model=image["image_model"],
            scene_count=len(scenes),
            duration_seconds=total_duration,
        )
        db.add(job)
        await db.flush()

        for scene in scenes:
            db.add(
                VideoExportScene(
                    job_id=job.id,
                    scene_index=scene.scene_index,
                    chapter_id=scene.chapter_id,
                    chapter_number=scene.chapter_number,
                    title=scene.title,
                    narration=scene.narration,
                    duration_seconds=scene.duration_seconds,
                    visual_prompt=scene.visual_prompt,
                    asset_kind=ASSET_KIND_PLACEHOLDER,
                    status="pending",
                    motion_provider=motion["motion_provider"],
                    motion_model=motion["motion_model"],
                    motion_status=None if motion["motion_mode"] == MOTION_MODE_LOCAL else "pending",
                    motion_idempotency_key=build_scene_idempotency_key(job.id, scene.scene_index),
                    image_provider=image["image_provider"],
                    image_model=image["image_model"],
                    image_status=(
                        IMAGE_STATUS_PENDING if image["generate_scene_images"] else None
                    ),
                    image_size=image["image_size"],
                )
            )

        # 复用后台任务面板：任务ID与导出任务ID一致，进度/取消能力开箱即用
        db.add(
            BackgroundTask(
                id=job.id,
                user_id=user_id,
                project_id=project.id,
                task_type=TASK_TYPE,
                status="pending",
                progress=0,
                status_message="Đã tạo tác vụ xuất phim, đang chờ thực thi...",
                task_input={
                    "chapter_ids": job.chapter_ids,
                    "options": normalized,
                    "scene_count": len(scenes),
                },
                max_retries=1,
            )
        )
        await db.commit()
        await db.refresh(job)
        logger.info(
            "创建视频导出任务: job=%s project=%s chapters=%s scenes=%s",
            job.id[:8],
            project.id[:8],
            len(chapters),
            len(scenes),
        )

        await background_task_service.spawn_background_task(
            job.id, user_id, _run_video_export_job, job.id
        )
        return job

    # ------------------------------------------------------------------ 状态同步

    async def _apply_state(
        self,
        db: AsyncSession,
        job: VideoExportJob,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        started: bool = False,
        completed: bool = False,
    ) -> None:
        """同时更新导出任务与对应后台任务，保证 /api/tasks 面板进度一致"""
        now = datetime.now()
        if status is not None:
            job.status = status
        if progress is not None:
            job.progress = max(0, min(int(progress), 100))
        if message is not None:
            job.status_message = message[:500]
        if error is not None:
            job.error_message = error
        if started:
            job.started_at = job.started_at or now
        if completed:
            job.completed_at = now
        job.updated_at = now

        task = await db.get(BackgroundTask, job.id)
        if task is not None:
            if status is not None:
                task.status = status
            if progress is not None:
                task.progress = job.progress
            if message is not None:
                task.status_message = job.status_message
            if error is not None:
                task.error_message = error
            if started:
                task.started_at = task.started_at or now
            if completed:
                task.completed_at = now
            task.progress_details = {
                "stage": status or "running",
                "message": job.status_message,
                "progress": job.progress,
                "job_id": job.id,
            }
            task.updated_at = now
        await db.commit()

    async def _is_cancelled(self, db: AsyncSession, job: VideoExportJob) -> bool:
        """检查任务是否被取消（或被其它 worker 接管执行权）

        用列级查询而不是 ORM refresh，避免任务行被并发删除（如项目被删除）时抛错：
        行已不存在时按“已取消”处理，让流水线尽快停下。

        同时校验执行权：如果 lease 已被另一个 worker 抢走（stale takeover），
        本进程立即停止，避免两个 worker 同时写同一个任务。
        """
        try:
            result = await db.execute(
                select(VideoExportJob.status, VideoExportJob.worker_token).where(
                    VideoExportJob.id == job.id
                )
            )
            row = result.first()
        except Exception as exc:  # noqa: BLE001 - 会话异常时保守地停止流水线
            logger.warning("检查导出任务状态失败，按已取消处理: job=%s error=%s", job.id[:8], exc)
            return True

        if row is None:
            return True
        if row[0] == "cancelled":
            return True
        owner = row[1]
        if owner and job.worker_token and owner != job.worker_token:
            logger.warning(
                "执行权已被其它 worker 接管，停止本进程流水线: job=%s", job.id[:8]
            )
            return True

        task_row = (
            await db.execute(
                select(BackgroundTask.cancel_requested, BackgroundTask.status).where(
                    BackgroundTask.id == job.id
                )
            )
        ).first()
        if task_row is None:
            return False
        return bool(task_row[0] or task_row[1] == "cancelled")

    def _make_cancel_checker(self, db: AsyncSession, job: VideoExportJob):
        """构造传给 FFmpeg 的取消回调（带节流，避免每秒多次查库）"""
        interval = max(float(settings.video_cancel_poll_seconds), 0.1)
        state = {"checked_at": 0.0, "cancelled": False}

        async def check() -> bool:
            if state["cancelled"]:
                return True
            now = _monotonic()
            if now - state["checked_at"] < interval:
                return False
            state["checked_at"] = now
            state["cancelled"] = await self._is_cancelled(db, job)
            if state["cancelled"]:
                logger.info("检测到取消信号，正在停止 FFmpeg: job=%s", job.id[:8])
            return state["cancelled"]

        return check

    async def _safe_apply_state(self, db: AsyncSession, job: VideoExportJob, **kwargs: Any) -> None:
        """终态更新：任务行可能已被并发删除（项目删除/记录清理），这里只记日志不抛出"""
        try:
            await self._apply_state(db, job, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("更新导出任务终态失败（记录可能已被删除）: job=%s error=%s", job.id[:8], exc)

    # ------------------------------------------------------------------ 流水线

    async def run_job(self, *, job_id: str, user_id: str) -> None:
        """后台执行入口：可安全重复调用（已完成的镜头会被跳过；同一任务不会并发执行两遍）"""
        if job_id in RUNNING_JOB_IDS:
            logger.info("导出任务已在本进程执行中，跳过重复排队: job=%s", job_id[:8])
            return

        engine = await get_engine(user_id)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        RUNNING_JOB_IDS.add(job_id)
        try:
            await self._run_job_with_session(
                session_factory=session_factory, job_id=job_id, user_id=user_id
            )
        finally:
            RUNNING_JOB_IDS.discard(job_id)

    async def _run_job_with_session(
        self, *, session_factory: Any, job_id: str, user_id: str
    ) -> None:
        async with session_factory() as db:
            try:
                job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
            except HTTPException:
                # 任务可能在排队期间被删除（例如项目被删除），此时直接跳过
                logger.info("导出任务已不存在，跳过执行: job=%s", job_id[:8])
                return
            if job.status not in ("pending", "failed", "running"):
                logger.info("跳过非等待状态的导出任务: job=%s status=%s", job.id[:8], job.status)
                return

            # 跨进程抢占执行权：多 worker 部署时只有一个实例能进入流水线，
            # 避免同一个远端操作被重复提交（重复计费）。running + lease 过期的情况也允许接管。
            token = uuid.uuid4().hex
            if not await self._claim_job(db=db, job=job, token=token):
                logger.info("导出任务已被其它 worker 领取，跳过: job=%s", job.id[:8])
                return

            try:
                await self._run_claimed_job(db=db, job=job, user_id=user_id, token=token)
            finally:
                await self._release_claim(db=db, job=job, token=token)

    async def _run_claimed_job(
        self, *, db: AsyncSession, job: VideoExportJob, user_id: str, token: str
    ) -> None:
        scenes = await self._get_scenes(db=db, job_id=job.id)
        if not scenes:
            await self._safe_apply_state(
                db, job, status="failed", error="Tác vụ không có phân cảnh nào để dựng", completed=True
            )
            return

        options = dict(job.options or {})
        await self._apply_state(
            db,
            job,
            status="running",
            progress=3,
            message="Đang chuẩn bị dựng phim...",
            started=True,
        )

        try:
            await self._render_pipeline(db=db, job=job, scenes=scenes, options=options, user_id=user_id)
        except (JobCancelledError, FFmpegCancelledError):
            await self._cleanup_partial_output(job=job, user_id=user_id)
            await self._safe_apply_state(
                db, job, status="cancelled", message="Tác vụ đã bị hủy", completed=True
            )
        except JobTimeoutError as exc:
            logger.warning("导出任务超时: job=%s error=%s", job.id[:8], exc)
            await self._cleanup_partial_output(job=job, user_id=user_id)
            await self._safe_apply_state(
                db,
                job,
                status="failed",
                error=str(exc),
                message="Dựng phim vượt quá thời gian cho phép",
                completed=True,
            )
        except SceneRenderError as exc:
            logger.warning("导出任务存在失败镜头: job=%s error=%s", job.id[:8], exc)
            await self._safe_apply_state(
                db,
                job,
                status="failed",
                error=str(exc),
                message="Một số phân cảnh dựng thất bại, hãy thử lại phân cảnh bị lỗi",
                completed=True,
            )
        except FFmpegUnavailableError as exc:
            await self._safe_apply_state(db, job, status="failed", error=str(exc), completed=True)
        except HTTPException as exc:
            await self._safe_apply_state(db, job, status="failed", error=str(exc.detail), completed=True)
        except Exception as exc:  # noqa: BLE001 - 后台任务必须落库失败原因
            logger.error("导出视频失败: job=%s error=%s", job.id[:8], exc, exc_info=True)
            await self._safe_apply_state(
                db,
                job,
                status="failed",
                error=f"{type(exc).__name__}: {exc}"[:1000],
                message="Dựng phim thất bại",
                completed=True,
            )

    async def _cleanup_partial_output(self, *, job: VideoExportJob, user_id: str) -> None:
        """取消/超时后删除半成品成片与未完成的图片素材

        已生成成功的分镜图片会被保留：它们是已付费产物，重试时应复用而不是重新生成。
        未写完的 `.part` 文件则一律清理，避免留下孤儿素材。
        """
        workdir = job_directory_path(user_id, job.id)
        for name in (FINAL_VIDEO_NAME, SUBTITLED_VIDEO_NAME, SUBTITLE_NAME, "clips.txt"):
            try:
                (workdir / name).unlink(missing_ok=True)
            except OSError as exc:  # 文件可能正被其它进程占用（Windows）
                logger.warning("删除半成品文件失败: %s (%s)", name, exc)
        # The files above are the paths exposed by the job record.  Clear the
        # metadata together with the files so a cancelled/expired retry cannot
        # advertise a download that now returns 404.
        job.video_path = None
        job.subtitle_path = None
        job.video_size_bytes = None
        job.duration_seconds = 0.0
        assets_dir = workdir / ASSETS_DIRNAME
        if assets_dir.is_dir():
            for leftover in list(assets_dir.glob("*.part")) + list(assets_dir.glob("*/*.part")):
                try:
                    leftover.unlink(missing_ok=True)
                except OSError as exc:  # pragma: no cover - Windows 占用
                    logger.warning("删除图片临时文件失败: %s (%s)", leftover.name, exc)

    # ------------------------------------------------------------------ 执行权（lease）

    @staticmethod
    def _lease_expiry(now: datetime) -> datetime:
        """过期阈值：超过该时间未续期的执行权可被其它 worker 接管

        TTL 取任务墙钟上限加缓冲，避免正常执行中的任务被误判为过期。
        """
        ttl = max(int(settings.video_job_timeout_seconds), 60) + int(settings.video_claim_ttl_buffer_seconds)
        return now - timedelta(seconds=ttl)

    async def _claim_job(self, *, db: AsyncSession, job: VideoExportJob, token: str) -> bool:
        """原子领取执行权：只有一次条件 UPDATE 生效的调用方才能进入流水线

        可领取的情况：
        1. 状态仍为 `pending`/`failed`，且（无持有者 或 持有者 lease 已过期 或 就是自己）
        2. 状态为 `running` 但 lease 已过期 —— worker trước đã chết giữa chừng；
           此时**不触碰分镜**，远端 `motion_operation_id` 仍被保留，接管后会继续轮询（resume），
           不会重复下单。

        `rowcount == 1` 表示领取成功；否则说明其它进程正在正常执行。
        """
        now = datetime.now()
        stale_before = self._lease_expiry(now)
        result = await db.execute(
            update(VideoExportJob)
            .where(
                VideoExportJob.id == job.id,
                or_(
                    and_(
                        VideoExportJob.status.in_(("pending", "failed")),
                        or_(
                            VideoExportJob.worker_token.is_(None),
                            VideoExportJob.claimed_at.is_(None),
                            VideoExportJob.claimed_at < stale_before,
                            VideoExportJob.worker_token == token,
                        ),
                    ),
                    and_(
                        VideoExportJob.status == "running",
                        or_(
                            VideoExportJob.claimed_at.is_(None),
                            VideoExportJob.claimed_at < stale_before,
                        ),
                    ),
                ),
            )
            .values(worker_token=token, claimed_at=now, updated_at=now)
        )
        await db.commit()
        claimed = int(result.rowcount or 0) == 1
        if claimed:
            job.worker_token = token
            job.claimed_at = now
            if job.status == "running":
                logger.warning(
                    "Tiếp quản tác vụ đang running nhưng lease đã hết hạn: job=%s", job.id[:8]
                )
        return claimed

    async def _release_claim(
        self, *, db: AsyncSession, job: VideoExportJob, token: str
    ) -> None:
        """任务收敛（或本进程异常退出）后释放执行权，允许其它 worker 接管"""
        try:
            await db.execute(
                update(VideoExportJob)
                .where(VideoExportJob.id == job.id, VideoExportJob.worker_token == token)
                .values(worker_token=None, claimed_at=None)
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - 释放失败不应影响任务结果
            logger.warning("释放导出任务执行权失败: job=%s error=%s", job.id[:8], exc)

    # ------------------------------------------------------------------ 转场 provider 辅助

    @staticmethod
    def _build_provider_for_job(name: str) -> MotionProvider:
        """构建远端 provider；未配置时抛 503（由任务失败处理落库原因）"""
        provider = resolve_motion_provider(name)
        if provider.kind != KIND_REMOTE:
            raise HTTPException(
                status_code=400, detail=f"Provider {name} không phải provider tạo video từ xa"
            )
        return provider

    @staticmethod
    def _build_image_provider_for_job(
        name: str, *, user_settings: Any = None
    ) -> SceneImageProvider:
        """构建场景图 provider；未配置时抛 503（任务会以明确原因失败，绝不静默降级）"""
        return resolve_image_provider(name or META_PROVIDER_NAME, user_settings=user_settings)

    @staticmethod
    def _build_reference(asset: SceneAsset) -> Optional[MotionReference]:
        """把受管素材转成 provider 需要的参考图（placeholder 时为 None）"""
        if asset.path is None:
            return None
        return MotionReference(path=asset.path, mime_type=asset.mime_type, kind=asset.kind)

    async def _safe_commit(self, db: AsyncSession, job: VideoExportJob) -> None:
        """提交分镜进度；记录已被并发删除时立刻停止流水线，避免继续写孤儿数据"""
        try:
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - 记录被删除/会话失效
            logger.warning(
                "导出任务记录已失效（可能被删除），停止流水线: job=%s error=%s", job.id[:8], exc
            )
            with contextlib.suppress(Exception):
                await db.rollback()
            raise JobCancelledError() from exc

    def _operation_hook(self, *, db: AsyncSession, job: VideoExportJob, scene: VideoExportScene, provider: MotionProvider):
        """远端操作状态落库回调：只保存 operation id/状态，不保存远端 URL"""

        async def hook(operation: MotionOperation) -> None:
            if await self._is_cancelled(db, job):
                raise MotionCancelledError("Đã hủy theo yêu cầu của người dùng")
            scene.motion_provider = provider.name
            if operation.model:
                scene.motion_model = operation.model
            if operation.operation_id:
                scene.motion_operation_id = operation.operation_id[:200]
            scene.motion_status = operation.status
            await self._safe_commit(db, job)

        return hook

    async def _finish_scene(
        self,
        *,
        scene: VideoExportScene,
        asset: SceneAsset,
        clip_path: Path,
        result: Any,
        fallback_used: bool = False,
    ) -> None:
        """分镜成功后统一落库：片段路径、画面来源、远端状态与实际时长"""
        scene.status = "ready"
        scene.asset_kind = asset.kind
        scene.asset_path = f"{CLIPS_DIRNAME}/{clip_path.name}"
        scene.error_message = None
        scene.motion_provider = result.provider
        scene.motion_model = result.model or scene.motion_model
        if result.operation_id:
            scene.motion_operation_id = result.operation_id[:200]
        if result.provider == LOCAL_PROVIDER_NAME:
            # local 模式没有远端操作；hybrid 回落时保留 provider 的失败状态，便于排查
            if not fallback_used:
                scene.motion_status = MOTION_STATUS_SKIPPED
        else:
            scene.motion_status = MOTION_STATUS_COMPLETED
        scene.motion_fallback_used = bool(fallback_used)
        probed = await ffmpeg_runner.probe_duration(clip_path)
        actual = probed or result.duration_seconds
        scene.clip_duration_seconds = round(float(actual), 1) if actual else None

    # ------------------------------------------------------------------ 场景图生成

    async def _generate_scene_image(
        self,
        *,
        db: AsyncSession,
        job: VideoExportJob,
        scene: VideoExportScene,
        provider: SceneImageProvider,
        assets_dir: Path,
        options: dict[str, Any],
        cancel_check: Any,
        timeout: float,
    ) -> Optional[Path]:
        """为一个分镜生成场景图，成功返回受管目录内的图片路径

        - 已有成功图片（`image_status == ready` 且文件仍在）→ 直接复用，**不重复付费生成**
        - 失败/取消都会如实落库，绝不静默换 provider 或退回占位图
        """
        suffix = output_extension(provider)
        out_path = assets_dir / f"scene_{scene.scene_index:03d}{suffix}"
        if scene.image_status == IMAGE_STATUS_READY and out_path.is_file():
            return out_path

        if await self._is_cancelled(db, job):
            raise JobCancelledError()

        scene.image_status = IMAGE_STATUS_GENERATING
        scene.image_error = None
        await self._safe_commit(db, job)

        request = ImageRequest(
            prompt=scene.visual_prompt or scene.narration or "",
            aspect_ratio=str(options.get("image_aspect_ratio") or provider.aspect_ratios[0]),
            size=str(options.get("image_size") or provider.size_for_aspect(
                str(options.get("image_aspect_ratio") or provider.aspect_ratios[0])
            )),
            model=job.image_model or options.get("image_model"),
            reasoning_strength=options.get("image_reasoning_strength"),
        )
        try:
            result = await provider.generate_image(
                request,
                out_path,
                cancel_check=cancel_check,
                timeout=timeout,
            )
        except (ImageCancelledError, MotionCancelledError, FFmpegCancelledError):
            # cancel 必须让 job 以 cancelled 收尾（không ghi scene failed），并立即停止流水线
            scene.image_status = IMAGE_STATUS_CANCELLED
            await self._safe_commit(db, job)
            raise JobCancelledError()
        except (ImageProviderError, ImageRequestError, ImageConfigError, ImageTimeoutError) as exc:
            detail = image_error_detail(exc)
            scene.image_status = IMAGE_STATUS_FAILED
            scene.image_error = detail[:1000]
            scene.status = "failed"
            scene.error_message = f"{provider.name}: {detail}"[:1000]
            logger.warning(
                "生成场景图失败: job=%s scene=%s provider=%s error=%s",
                job.id[:8],
                scene.scene_index,
                provider.name,
                detail,
            )
            await self._safe_commit(db, job)
            return None

        scene.image_status = IMAGE_STATUS_READY
        scene.image_provider = result.provider
        scene.image_model = result.model
        scene.image_size = result.size
        scene.image_path = f"{ASSETS_DIRNAME}/{result.path.name}"
        scene.image_error = None
        await self._safe_commit(db, job)
        return result.path

    async def _handle_remote_failure(
        self,
        *,
        db: AsyncSession,
        job: VideoExportJob,
        scene: VideoExportScene,
        asset: SceneAsset,
        request: MotionRequest,
        clip_path: Path,
        local_provider: MotionProvider,
        remote_exc: Exception,
        allow_fallback: bool,
        cancel_check: Any,
        timeout: float,
        ready_clips: list[Path],
    ) -> None:
        """远端失败：remote 模式直接标记失败；hybrid 且策略允许时回落到本地 FFmpeg

        超时（`MotionTimeoutError`）时远端操作很可能仍在执行，因此状态保持 `running`：
        重试会继续轮询同一个操作而不是重新下单，避免重复计费。
        """
        detail = provider_error_detail(remote_exc)
        scene.provider_error = detail[:1000]
        scene.motion_status = (
            MOTION_STATUS_RUNNING if isinstance(remote_exc, MotionTimeoutError) else MOTION_STATUS_FAILED
        )
        logger.warning(
            "远端转场失败: job=%s scene=%s provider=%s error=%s",
            job.id[:8],
            scene.scene_index,
            scene.motion_provider,
            detail,
        )

        if not allow_fallback:
            scene.status = "failed"
            scene.error_message = f"{scene.motion_provider or 'provider'}: {detail}"[:1000]
            return

        if await self._is_cancelled(db, job):
            raise JobCancelledError()
        logger.info(
            "Theo chính sách hybrid, dựng lại phân cảnh bằng FFmpeg cục bộ: job=%s scene=%s",
            job.id[:8],
            scene.scene_index,
        )
        try:
            result = await local_provider.render_scene(
                request=request,
                out_path=clip_path,
                cancel_check=cancel_check,
                timeout=timeout,
            )
        except FFmpegCancelledError as exc:
            raise JobCancelledError() from exc
        except Exception as fallback_exc:  # noqa: BLE001 - 兜底同样失败则如实上报
            scene.status = "failed"
            scene.error_message = (
                f"Provider remote lỗi ({detail}); dựng cục bộ cũng thất bại: "
                f"{provider_error_detail(fallback_exc)}"
            )[:1000]
            return

        await self._finish_scene(
            scene=scene,
            asset=asset,
            clip_path=clip_path,
            result=result,
            fallback_used=True,
        )
        ready_clips.append(clip_path)

    async def _render_pipeline(
        self,
        *,
        db: AsyncSession,
        job: VideoExportJob,
        scenes: list[VideoExportScene],
        options: dict[str, Any],
        user_id: str,
    ) -> None:
        workdir = job_directory(user_id, job.id)
        clips_dir = workdir / CLIPS_DIRNAME
        assets_dir = workdir / ASSETS_DIRNAME
        clips_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

        width, height = parse_resolution(options.get("resolution", settings.video_default_resolution))
        fps = int(options.get("fps", settings.video_default_fps))
        use_cover = bool(options.get("use_project_cover", True))

        # 整个任务的墙钟上限，避免异常任务长期占用 FFmpeg
        job_deadline = _monotonic() + max(int(settings.video_job_timeout_seconds), 30)
        cancel_check = self._make_cancel_checker(db, job)

        def remaining_budget() -> float:
            remaining = job_deadline - _monotonic()
            if remaining <= 0:
                raise JobTimeoutError(
                    f"Tác vụ vượt quá thời gian cho phép {settings.video_job_timeout_seconds} giây"
                )
            return remaining

        def step_timeout() -> float:
            """单次 FFmpeg 调用既受单项超时约束，也不得超过任务剩余时间"""
            return min(float(settings.video_render_timeout_seconds), remaining_budget())

        project = await db.get(Project, job.project_id)
        cover_path = (
            resolve_cover_image(project.cover_image_url, project.cover_status) if project else None
        )

        # 转场 provider：local 模式只用本地；remote/hybrid 需要远端实例
        motion_mode = _job_motion_mode(job)
        remote_provider: Optional[MotionProvider] = None
        if motion_mode != MOTION_MODE_LOCAL:
            provider_name = (job.motion_provider or options.get("motion_provider") or "").strip()
            remote_provider = self._build_provider_for_job(provider_name)
        local_provider: MotionProvider = build_provider(LOCAL_PROVIDER_NAME)
        hybrid_fallback = bool(options.get("hybrid_fallback_on_error")) and (
            motion_mode == MOTION_MODE_HYBRID
        )

        # 场景图 provider（可选）：缺配置直接让任务失败并说明原因，不静默改用封面/占位图
        user_settings = await load_user_image_settings(db, user_id)
        image_provider: Optional[SceneImageProvider] = None
        if options.get("generate_scene_images"):
            image_name = (job.image_provider or options.get("image_provider") or "").strip()
            image_provider = self._build_image_provider_for_job(
                image_name, user_settings=user_settings
            )
            job.image_provider = image_provider.name
            job.image_model = job.image_model or options.get("image_model")
            await self._safe_commit(db, job)

        tts_engine = (
            build_tts_engine(
                user_settings=user_settings,
                provider=options.get("tts_provider"),
                model=options.get("tts_model"),
            )
            if options.get("tts_enabled")
            else NullTTSEngine()
        )
        tts_switched = False
        if options.get("tts_enabled"):
            sample = " ".join((scene.narration or "") for scene in scenes[:3])
            tts_engine, tts_switched = prefer_native_language_engine(tts_engine, sample)
        tts_failed = False

        total = len(scenes)
        ready_clips: list[Path] = []
        for position, scene in enumerate(scenes, start=1):
            if await self._is_cancelled(db, job):
                raise JobCancelledError()
            remaining_budget()

            clip_path = clips_dir / f"scene_{scene.scene_index:03d}.mp4"
            if scene.status == "ready" and clip_path.is_file():
                ready_clips.append(clip_path)
                continue

            scene.status = "rendering"
            scene.error_message = None
            await self._safe_commit(db, job)

            progress = 5 + int(75 * (position - 1) / max(total, 1))
            switch_note = " (giọng tiếng Việt)" if tts_switched else ""
            await self._apply_state(
                db,
                job,
                progress=progress,
                message=f"Đang dựng phân cảnh {position}/{total}{switch_note}...",
            )

            # 生成场景图（nếu bật）：图片先落到 assets/，再作为参考图交给 motion provider
            if image_provider is not None:
                generated = await self._generate_scene_image(
                    db=db,
                    job=job,
                    scene=scene,
                    provider=image_provider,
                    assets_dir=assets_dir,
                    options=options,
                    cancel_check=cancel_check,
                    timeout=min(
                        float(settings.video_image_timeout_seconds), remaining_budget()
                    ),
                )
                if generated is None:
                    # 图片失败：该分镜明确失败，不换 provider、不退回占位图
                    await self._safe_commit(db, job)
                    continue

            asset = resolve_scene_asset(
                assets_dir=assets_dir,
                scene_index=scene.scene_index,
                cover_path=cover_path,
                use_project_cover=use_cover,
            )

            audio_path: Optional[Path] = None
            if options.get("tts_enabled"):
                try:
                    audio_path = await tts_engine.synthesize(
                        text=scene.narration or "",
                        out_path=clips_dir / f"tts_{scene.scene_index:03d}.mp3",
                    )
                    if audio_path is not None:
                        audio_duration = await ffmpeg_runner.probe_duration(audio_path)
                        if audio_duration and audio_duration > 0:
                            scene.duration_seconds = round(
                                max(
                                    settings.video_scene_min_seconds,
                                    min(float(audio_duration) + 0.25, 90.0),
                                ),
                                1,
                            )
                except Exception as exc:  # noqa: BLE001 - TTS 失败必须回落到静音
                    tts_failed = True
                    audio_path = None
                    if remote_provider and remote_provider.name == "muse_tool":
                        scene.status = "failed"
                        scene.error_message = "Tạo lời kể thất bại; chưa gửi yêu cầu Muse cho cảnh này."
                        await self._safe_commit(db, job)
                        continue
                    logger.warning("TTS 合成失败，改用静音: scene=%s error=%s", scene.scene_index, exc)

            if options.get("tts_enabled") and remote_provider and remote_provider.name == "muse_tool" and audio_path is None:
                scene.status = "failed"
                scene.error_message = "Không có audio lời kể; chưa gửi yêu cầu Muse."
                await self._safe_commit(db, job)
                continue
            shot = next((item.get("direction") for item in options.get("shot_plan", [])
                         if item.get("scene_index") == scene.scene_index), None)
            request = MotionRequest(
                audio_mode=options.get("muse_audio_mode") if job.motion_provider == "muse_tool" else None,
                scene_direction=shot if job.motion_provider == "muse_tool" else None,
                prompt=scene.visual_prompt or scene.narration or "",
                duration_seconds=float(scene.duration_seconds or settings.video_scene_min_seconds),
                aspect_ratio=str(
                    options.get("motion_aspect_ratio") or _aspect_from_resolution(options.get("resolution"))
                ),
                resolution=str(
                    options.get("motion_resolution")
                    or (remote_provider.default_resolution if remote_provider else "")
                ),
                reference=self._build_reference(asset),
                idempotency_key=scene.motion_idempotency_key
                or build_scene_idempotency_key(job.id, scene.scene_index),
                model=job.motion_model or options.get("motion_model"),
                # 远端操作仍可能存活时复用同一个 operation（续跑），避免重复计费
                resume_operation_id=(
                    scene.motion_operation_id
                    if scene.motion_operation_id and (scene.motion_status in self.RESUME_MOTION_STATUSES or (scene.motion_provider == "muse_tool" and scene.motion_status == MOTION_STATUS_COMPLETED and scene.status != "ready"))
                    else None
                ),
                local=LocalRenderOptions(
                    width=width,
                    height=height,
                    fps=fps,
                    audio_path=audio_path,
                    enable_motion=True,
                ),
            )

            provider = (
                local_provider
                if motion_mode == MOTION_MODE_LOCAL or remote_provider is None
                else remote_provider
            )
            provider_timeout = (
                min(float(settings.video_motion_operation_timeout_seconds), remaining_budget())
                if provider.kind == KIND_REMOTE
                else step_timeout()
            )

            try:
                result = await provider.render_scene(
                    request=request,
                    out_path=clip_path,
                    cancel_check=cancel_check,
                    timeout=provider_timeout,
                    on_operation=self._operation_hook(db=db, job=job, scene=scene, provider=provider),
                )
                if provider.name == "muse_tool" and (audio_path or options.get("muse_audio_mode") == "silent"):
                    await replace_scene_audio(clip_path, audio_path=audio_path, cancel_check=cancel_check, timeout=step_timeout())
                await self._finish_scene(scene=scene, asset=asset, clip_path=clip_path, result=result)
                ready_clips.append(clip_path)
            except (MotionCancelledError, FFmpegCancelledError):
                scene.status = "pending"
                if scene.motion_status:
                    scene.motion_status = MOTION_STATUS_CANCELLED
                await self._safe_commit(db, job)
                raise JobCancelledError()
            except (MotionProviderError, MotionTimeoutError, MotionConfigError, MotionRequestError) as exc:
                await self._handle_remote_failure(
                    db=db,
                    job=job,
                    scene=scene,
                    asset=asset,
                    request=request,
                    clip_path=clip_path,
                    local_provider=local_provider,
                    remote_exc=exc,
                    allow_fallback=hybrid_fallback,
                    cancel_check=cancel_check,
                    timeout=step_timeout(),
                    ready_clips=ready_clips,
                )
            except FFmpegExecutionError as exc:
                scene.status = "failed"
                scene.error_message = str(exc)[:1000]
                logger.warning("分镜渲染失败: job=%s scene=%s error=%s", job.id[:8], scene.scene_index, exc)
            await self._safe_commit(db, job)

        if await self._is_cancelled(db, job):
            raise JobCancelledError()

        failed_scenes = [scene for scene in scenes if scene.status != "ready"]
        if failed_scenes:
            indexes = ", ".join(str(scene.scene_index + 1) for scene in failed_scenes[:8])
            raise SceneRenderError(
                f"{len(failed_scenes)}/{total} phân cảnh dựng thất bại (phân cảnh: {indexes})"
            )

        await self._apply_state(db, job, progress=85, message="Đang ghép các phân cảnh thành phim...")
        video_path = workdir / FINAL_VIDEO_NAME
        await ffmpeg_runner.concat_clips(
            ready_clips,
            video_path,
            workdir=workdir,
            fps=fps,
            cancel_check=cancel_check,
            timeout=step_timeout(),
        )

        subtitle_path = workdir / SUBTITLE_NAME
        subtitle_path.write_text(build_srt_from_scenes(scenes), encoding="utf-8")

        await self._apply_state(db, job, progress=92, message="Đang gắn phụ đề vào video...")
        subtitled_path = workdir / SUBTITLED_VIDEO_NAME
        if await ffmpeg_runner.mux_subtitles(
            video_path,
            subtitle_path,
            subtitled_path,
            cancel_check=cancel_check,
            timeout=step_timeout(),
        ):
            video_path.unlink(missing_ok=True)
            subtitled_path.replace(video_path)

        size_bytes = video_path.stat().st_size
        max_bytes = int(settings.video_max_output_mb) * 1024 * 1024
        if size_bytes > max_bytes:
            video_path.unlink(missing_ok=True)
            raise SceneRenderError(
                f"Video thành phẩm vượt giới hạn {settings.video_max_output_mb}MB, "
                "hãy giảm số chương hoặc độ phân giải rồi thử lại"
            )

        actual_duration = await ffmpeg_runner.probe_duration(video_path)
        job.video_path = f"{user_id}/{job.id}/{FINAL_VIDEO_NAME}"
        job.subtitle_path = f"{user_id}/{job.id}/{SUBTITLE_NAME}"
        job.video_size_bytes = size_bytes
        if actual_duration:
            job.duration_seconds = round(float(actual_duration), 1)

        message = "Xuất phim hoàn tất"
        if tts_switched and not tts_failed:
            message = "Xuất phim hoàn tất (đã dùng giọng tiếng Việt vì Deepgram chỉ đọc được tiếng Anh)"
        if tts_failed:
            message = "Xuất phim hoàn tất (một số phân cảnh không có giọng đọc, đã dùng video im lặng)"
        await self._apply_state(
            db, job, status="completed", progress=100, message=message, error=None, completed=True
        )
        logger.info(
            "视频导出完成: job=%s size=%s bytes duration=%ss",
            job.id[:8],
            size_bytes,
            job.duration_seconds,
        )

    # ------------------------------------------------------------------ 重试 / 取消 / 删除

    # 远端操作可能仍在执行（或状态未知）的集合：重试时必须续跑而不是重新下单
    RESUME_MOTION_STATUSES = RESUME_MOTION_STATUSES

    async def _reset_scene_clips(
        self, *, user_id: str, job_id: str, scenes: Sequence[VideoExportScene]
    ) -> str:
        """重置分镜状态；返回给用户的说明（远端操作被续跑时会带警告文案）

        计费安全策略：如果分镜存在远端 operation 且状态不确定（pending/running/cancelled，
        例如超时中断或取消后 provider 仍在生成），**保留** operation id 并要求续跑轮询，
        绝不静默提交第二个请求；只有远端操作已明确终结（completed/failed/expired）或从未提交时，
        才生成新的幂等键并重新下单。
        """
        workdir = job_directory(user_id, job_id)
        # A retry rebuilds the final artefacts.  Remove the previous generation
        # up front and clear its metadata; otherwise a failed retry leaves a
        # completed job pointing at files that no longer exist.
        for name in (FINAL_VIDEO_NAME, SUBTITLED_VIDEO_NAME, SUBTITLE_NAME, "clips.txt"):
            try:
                (workdir / name).unlink(missing_ok=True)
            except OSError as exc:
                logger.warning("删除重试旧成品失败: %s (%s)", name, exc)
        resumed = 0
        for scene in scenes:
            resume_remote = bool(
                scene.motion_operation_id and (scene.motion_status in self.RESUME_MOTION_STATUSES or (scene.motion_provider == "muse_tool" and scene.motion_status == MOTION_STATUS_COMPLETED and scene.status != "ready"))
            )
            scene.status = "pending"
            scene.error_message = None
            scene.asset_path = None
            scene.motion_fallback_used = False
            scene.clip_duration_seconds = None
            # 场景图：已生成成功的图片**保留**（重新生成会产生额外费用），
            # 只有失败/被取消的图片才会被清掉并在重试时重新生成。
            if scene.image_status == IMAGE_STATUS_READY:
                if not _scene_image_file(workdir, scene).is_file():
                    scene.image_status = IMAGE_STATUS_PENDING
            elif scene.image_provider:
                _scene_image_file(workdir, scene).unlink(missing_ok=True)
                scene.image_status = IMAGE_STATUS_PENDING
                scene.image_error = None
            if resume_remote:
                # 保留 operation id 与幂等键：流水线会继续轮询这个操作
                scene.motion_status = MOTION_STATUS_RUNNING
                resumed += 1
            else:
                scene.motion_operation_id = None
                scene.motion_status = MOTION_STATUS_PENDING if scene.motion_provider else None
                scene.provider_error = None
                scene.motion_idempotency_key = renew_scene_idempotency_key(job_id, scene.scene_index)
            (workdir / CLIPS_DIRNAME / f"scene_{scene.scene_index:03d}.mp4").unlink(missing_ok=True)

        if not resumed:
            return ""
        return (
            f"{resumed} phân cảnh sẽ tiếp tục theo dõi thao tác AI đã gửi trước đó "
            "(không tạo yêu cầu mới, tránh tính phí hai lần)"
        )

    async def _validate_rerun_preconditions(
        self, *, db: AsyncSession, user_id: str, job: VideoExportJob
    ) -> None:
        """Validate retry guards before mutating scene rows or deleting clips."""
        self.ensure_enabled()
        self.ensure_ffmpeg()
        if job.status == "running" or job.id in RUNNING_JOB_IDS:
            raise HTTPException(
                status_code=409,
                detail="Tác vụ đang dựng hoặc đang dừng, vui lòng chờ hoàn tất trước khi thử lại",
            )
        await self._ensure_active_quota(db=db, user_id=user_id, exclude_job_id=job.id)

    async def _schedule_rerun(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        job: VideoExportJob,
        resume_message: str = "",
    ) -> None:
        self.ensure_enabled()
        self.ensure_ffmpeg()
        if job.status == "running" or job.id in RUNNING_JOB_IDS:
            # 纵深防御：状态可能已被并发修改，或流水线仍在收尾（FFmpeg 未退出）
            raise HTTPException(
                status_code=409,
                detail="Tác vụ đang dựng hoặc đang dừng, vui lòng chờ hoàn tất trước khi thử lại",
            )
        # 重试同样受配额约束（排除自身），避免通过反复重试绕过并发上限
        await self._ensure_active_quota(db=db, user_id=user_id, exclude_job_id=job.id)

        task = await db.get(BackgroundTask, job.id)
        if task is None:
            # 任务记录可能已在后台任务面板中被清理，重新建立映射以便继续展示进度
            task = BackgroundTask(
                id=job.id,
                user_id=user_id,
                project_id=job.project_id,
                task_type=TASK_TYPE,
                status="pending",
                progress=0,
                task_input={"chapter_ids": list(job.chapter_ids or []), "options": dict(job.options or {})},
                max_retries=1,
            )
            db.add(task)
        task.cancel_requested = False
        task.error_message = None
        task.completed_at = None
        # 释放旧的执行权（如果存在），让重新排队的任务能被任意 worker 领取
        job.worker_token = None
        job.claimed_at = None
        await self._apply_state(
            db,
            job,
            status="pending",
            progress=0,
            message=resume_message or "Đang chuẩn bị thử lại...",
            error=None,
        )
        await background_task_service.spawn_background_task(
            job.id, user_id, _run_video_export_job, job.id
        )

    # 需要重跑的分镜状态：任何未完成的状态（含进程被中断后残留的 rendering）
    UNFINISHED_SCENE_STATUSES = frozenset({"pending", "rendering", "failed", "cancelled"})

    async def retry_job(self, *, db: AsyncSession, user_id: str, job_id: str) -> VideoExportJob:
        """重试整个任务：保留已成功的分镜，重跑所有未完成/失败/残留的分镜

        - Chỉ giữ lại scene có `status == "ready"` (clip đã dựng xong)
        - Mọi scene dở (`pending`/`rendering`/`failed`/`cancelled`, kể cả ảnh đang `generating`)
          đều được reset để chạy lại; ảnh `ready` vẫn được giữ để không tạo lại ảnh Meta (tránh tính phí hai lần)
        - Remote operation đang có thể còn sống (`pending`/`running`/`cancelled`) được giữ để resume
        """
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        scenes = await self._get_scenes(db=db, job_id=job.id)
        # Do all expected 409/503 checks before resetting scenes or unlinking
        # FFmpeg output.  An unsuccessful retry request must be side-effect free.
        await self._validate_rerun_preconditions(db=db, user_id=user_id, job=job)
        unfinished = [scene for scene in scenes if scene.status != "ready"]
        resume_message = ""
        if unfinished:
            resume_message = await self._reset_scene_clips(
                user_id=user_id, job_id=job.id, scenes=unfinished
            )
            job.video_path = None
            job.subtitle_path = None
            job.video_size_bytes = None
            job.duration_seconds = 0.0
            await db.commit()
        await self._schedule_rerun(db=db, user_id=user_id, job=job, resume_message=resume_message)
        return job

    async def retry_scene(
        self, *, db: AsyncSession, user_id: str, job_id: str, scene_id: str
    ) -> VideoExportJob:
        """重试单个分镜，随后自动重新拼接成片"""
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        scenes = await self._get_scenes(db=db, job_id=job.id)
        target = next((scene for scene in scenes if scene.id == scene_id), None)
        if target is None:
            raise HTTPException(status_code=404, detail="Phân cảnh không tồn tại trong tác vụ này")
        await self._validate_rerun_preconditions(db=db, user_id=user_id, job=job)
        resume_message = await self._reset_scene_clips(
            user_id=user_id, job_id=job.id, scenes=[target]
        )
        job.video_path = None
        job.subtitle_path = None
        job.video_size_bytes = None
        job.duration_seconds = 0.0
        await db.commit()
        await self._schedule_rerun(db=db, user_id=user_id, job=job, resume_message=resume_message)
        return job

    async def cancel_job(self, *, db: AsyncSession, user_id: str, job_id: str) -> VideoExportJob:
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        if job.status not in ("pending", "running"):
            raise HTTPException(status_code=400, detail="Tác vụ đã kết thúc, không thể hủy")
        task = await db.get(BackgroundTask, job.id)
        if task is not None:
            task.cancel_requested = True
        await self._apply_state(
            db, job, status="cancelled", message="Tác vụ đã bị hủy", completed=True
        )
        return job

    async def delete_job(self, *, db: AsyncSession, user_id: str, job_id: str) -> None:
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        self.ensure_deletable(job)

        await self._delete_job_rows(db=db, job=job)
        await db.commit()

        self._remove_job_files(user_id=job.user_id, job_id=job.id)

    def ensure_deletable(self, job: VideoExportJob) -> None:
        """未结束或仍在本进程内执行的任务不允许删除，避免一边写一边删"""
        if job.status in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail="Tác vụ đang chờ hoặc đang dựng, vui lòng hủy và chờ dừng hẳn trước khi xóa",
            )
        if job.id in RUNNING_JOB_IDS:
            raise HTTPException(
                status_code=409,
                detail="Tác vụ đang dừng FFmpeg, vui lòng thử lại sau vài giây",
            )

    async def _delete_job_rows(self, *, db: AsyncSession, job: VideoExportJob) -> None:
        """显式删除分镜与后台任务映射（SQLite 默认不启用外键级联）"""
        for scene in await self._get_scenes(db=db, job_id=job.id):
            await db.delete(scene)
        task = await db.get(BackgroundTask, job.id)
        if task is not None:
            await db.delete(task)
        await db.delete(job)

    def _remove_job_files(self, *, user_id: str, job_id: str) -> None:
        """删除任务产物目录；任务仍在运行时推迟到 FFmpeg 退出后再删"""
        workdir = job_directory_path(user_id, job_id)
        if job_id in RUNNING_JOB_IDS:
            self._schedule_deferred_cleanup(workdir, job_id)
            return
        shutil.rmtree(workdir, ignore_errors=True)

    def _schedule_deferred_cleanup(self, workdir: Path, job_id: str, *, timeout: float = 120.0) -> None:
        """等待流水线停止后再删除目录（Windows 下删除被占用的文件会失败）"""

        async def _cleanup() -> None:
            deadline = _monotonic() + timeout
            while job_id in RUNNING_JOB_IDS and _monotonic() < deadline:
                await asyncio.sleep(0.5)
            shutil.rmtree(workdir, ignore_errors=True)

        task = asyncio.ensure_future(_cleanup())
        _PENDING_CLEANUPS.add(task)
        task.add_done_callback(_PENDING_CLEANUPS.discard)

    async def delete_project_artifacts(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        project_id: str,
        only_finished: bool = False,
        commit: bool = True,
    ) -> dict[str, Any]:
        """删除项目下所有视频导出任务（数据库记录 + 产物文件）

        - `only_finished=True`：只清理已结束且没有正在运行的任务（供“清理项目任务记录”使用）
        - `only_finished=False`：项目被删除时调用，先取消未完成任务再清理
        - `commit=False`：数据库删除并入调用方事务（例如与“删除项目”同一次提交），
          调用方提交成功后必须调用 `remove_artifact_dirs(result["targets"])` 才会删除文件。
          这样即使调用方提交失败回滚，也不会出现“记录还在但文件已被删除”的不一致。
        - `commit=True`：自行提交并立即删除产物文件（独立调用场景）

        SQLite 默认不启用外键约束，因此必须显式删除分镜与后台任务映射，
        否则会留下孤儿记录和无法清理的成片文件。
        """
        jobs = list(
            (
                await db.execute(
                    select(VideoExportJob).where(
                        VideoExportJob.project_id == project_id,
                        VideoExportJob.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        removable = [
            job
            for job in jobs
            if not only_finished
            or (job.status in ("completed", "failed", "cancelled") and job.id not in RUNNING_JOB_IDS)
        ]
        if not removable:
            return {"jobs": 0, "scenes": 0, "tasks": 0, "files_removed": 0, "targets": []}

        now = datetime.now()
        # 1) 先发出取消信号并提交，让仍在执行的流水线尽快停止
        for job in removable:
            if job.status in ("pending", "running"):
                job.status = "cancelled"
                job.status_message = "Dự án đã bị xóa" if not only_finished else "Tác vụ đã bị hủy"
                job.completed_at = now
            job.updated_at = now
            task = await db.get(BackgroundTask, job.id)
            if task is not None:
                task.cancel_requested = True
        if commit:
            # Publish the cancellation signal before removing rows so a worker
            # in another session can stop promptly.  For commit=False callers
            # (project deletion/transactional cleanup), keep everything in the
            # caller's transaction so a later failure can roll it all back.
            await db.commit()

        # 2) 显式删除关联记录（commit=False 时不提交，交由调用方与自身写入一起提交）
        targets = [(job.user_id, job.id) for job in removable]
        scene_count = 0
        task_count = 0
        for job in removable:
            scenes = await self._get_scenes(db=db, job_id=job.id)
            for scene in scenes:
                await db.delete(scene)
            scene_count += len(scenes)
            task = await db.get(BackgroundTask, job.id)
            if task is not None:
                await db.delete(task)
                task_count += 1
            await db.delete(job)

        if commit:
            await db.commit()
            self.remove_artifact_dirs(targets)

        logger.info(
            "已清理视频导出任务: project=%s jobs=%s scenes=%s tasks=%s commit=%s",
            project_id[:8],
            len(removable),
            scene_count,
            task_count,
            commit,
        )
        return {
            "jobs": len(removable),
            "scenes": scene_count,
            "tasks": task_count,
            "files_removed": len(targets) if commit else 0,
            "targets": targets,
        }

    def remove_artifact_dirs(self, targets: Sequence[tuple[str, str]]) -> int:
        """删除产物目录（必须在数据库提交之后调用）

        正在执行的任务会延迟到 FFmpeg 退出后再删，避免删除正在写入的文件。
        """
        removed = 0
        for owner_id, job_id in targets:
            try:
                self._remove_job_files(user_id=owner_id, job_id=job_id)
                removed += 1
            except Exception as exc:  # noqa: BLE001 - 文件清理失败不应影响已完成的数据库事务
                logger.warning("删除导出产物目录失败: job=%s error=%s", str(job_id)[:8], exc)
        return removed

    # ------------------------------------------------------------------ 下载

    async def get_output_path(
        self, *, db: AsyncSession, user_id: str, job_id: str, kind: str
    ) -> tuple[VideoExportJob, Path]:
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        if kind not in (DOWNLOAD_KIND_VIDEO, DOWNLOAD_KIND_SUBTITLES):
            raise HTTPException(status_code=400, detail="Loại tệp không hợp lệ")
        relative = job.video_path if kind == DOWNLOAD_KIND_VIDEO else job.subtitle_path
        if not relative:
            raise HTTPException(status_code=404, detail="Tác vụ chưa có tệp để tải xuống")

        # 双重校验：路径必须以当前用户目录开头，且解析后仍位于受管存储目录内
        if normalize_relative_path(relative).split("/", 1)[0] != user_id:
            logger.warning(
                "拒绝越权的导出文件路径: job=%s user=%s path=%s", job.id[:8], user_id, relative
            )
            raise HTTPException(status_code=404, detail="Đường dẫn tệp không hợp lệ")

        path = resolve_stored_path(VIDEO_STORAGE_DIR, relative)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Tệp đã bị xóa khỏi máy chủ, vui lòng dựng lại")
        return job, path

    async def get_scene_image_path(
        self, *, db: AsyncSession, user_id: str, job_id: str, scene_id: str
    ) -> tuple[VideoExportJob, VideoExportScene, Path]:
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        scenes = await self._get_scenes(db=db, job_id=job.id)
        scene = next((item for item in scenes if item.id == scene_id), None)
        if scene is None:
            raise HTTPException(status_code=404, detail="Phân cảnh không tồn tại")
        if scene.image_status != IMAGE_STATUS_READY:
            raise HTTPException(status_code=404, detail="Phân cảnh chưa có ảnh")
        path = _scene_image_file(job_directory_path(user_id, job.id), scene)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Ảnh phân cảnh đã bị xóa khỏi máy chủ")
        return job, scene, path


async def _run_video_export_job(task_id: str, user_id: str, job_id: str) -> None:
    """后台队列执行入口（函数签名与 background_task_service 约定一致）"""
    await video_export_service.run_job(job_id=job_id, user_id=user_id)


video_export_service = VideoExportService()
