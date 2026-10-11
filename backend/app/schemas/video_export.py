"""视频导出相关的 Pydantic 数据模型"""
from typing import Any, Optional

from pydantic import BaseModel, Field


class VideoExportChapterRef(BaseModel):
    """请求中引用的章节"""

    chapter_id: str = Field(min_length=1, max_length=36)


class VideoShotPlanEntry(BaseModel):
    scene_index: int = Field(ge=0)
    direction: dict[str, Any] = Field(default_factory=dict)


class VideoExportOptions(BaseModel):
    """导出参数，所有字段都有服务端默认值"""

    resolution: Optional[str] = Field(default=None, description="分辨率，需在白名单内，如 1280x720")
    fps: Optional[int] = Field(default=None, ge=1, le=60, description="帧率，需在白名单内")
    use_project_cover: Optional[bool] = Field(default=True, description="是否使用项目封面作为画面")
    tts_enabled: Optional[bool] = Field(default=False, description="是否合成旁白音频（默认静音）")
    tts_provider: Optional[str] = Field(
        default=None, max_length=50, description="TTS provider: deepgram / openai_compatible"
    )
    tts_model: Optional[str] = Field(
        default=None, max_length=100, description="TTS model, ví dụ flux-hannah-en"
    )
    narration_chars_per_scene: Optional[int] = Field(
        default=None, ge=80, le=600, description="每个分镜的旁白字数"
    )
    chars_per_second: Optional[float] = Field(
        default=None, ge=4, le=40, description="朗读速度（字/秒），用于估算分镜时长"
    )

    storyboard_mode: Optional[str] = None
    muse_audio_mode: Optional[str] = None
    storyboard_fingerprint: Optional[str] = None
    shot_plan: Optional[list[VideoShotPlanEntry]] = Field(default=None, max_length=80)

    # ---- 视频转场（motion video）----
    motion_mode: Optional[str] = Field(
        default=None,
        description="转场模式: local（本地 FFmpeg）/remote（远端 provider）/hybrid（远端优先，可按策略回落本地）",
    )
    motion_provider: Optional[str] = Field(
        default=None, max_length=50, description="provider 名称，需在 capabilities.motion_providers 内"
    )
    motion_model: Optional[str] = Field(
        default=None, max_length=100, description="模型名，必须是该 provider 支持的模型"
    )
    motion_resolution: Optional[str] = Field(
        default=None, max_length=20, description="provider 分辨率 token，如 720p/1080p"
    )
    motion_aspect_ratio: Optional[str] = Field(
        default=None, max_length=10, description="provider 画面比例，如 16:9 / 9:16"
    )
    hybrid_fallback_on_error: Optional[bool] = Field(
        default=None, description="hybrid 模式下远端失败时是否回落到本地 FFmpeg（默认取服务端配置）"
    )

    # ---- 场景图生成（image provider）----
    generate_scene_images: Optional[bool] = Field(
        default=False, description="是否用 image provider 为每个分镜生成场景图（ảnh nay làm reference cho video AI）"
    )
    image_provider: Optional[str] = Field(
        default=None, max_length=50, description="image provider id，需在 capabilities.image_providers 内"
    )
    image_model: Optional[str] = Field(default=None, max_length=100, description="图片模型名")
    image_aspect_ratio: Optional[str] = Field(
        default=None, max_length=10, description="比例 ảnh：16:9 / 9:16 / 1:1"
    )
    image_size: Optional[str] = Field(
        default=None, max_length=20, description="图片尺寸白名单值，如 1792x1024"
    )
    image_reasoning_strength: Optional[str] = Field(
        default=None, max_length=20, description="reasoning strength（仅 provider 支持时发送）"
    )


class VideoExportCreateRequest(BaseModel):
    """创建导出任务的请求体"""

    project_id: str = Field(min_length=1, max_length=36)
    chapter_ids: list[str] = Field(min_length=1, description="参与导出的章节ID列表")
    options: Optional[VideoExportOptions] = None


class VideoExportSceneResponse(BaseModel):
    """分镜信息"""

    id: str
    job_id: str
    scene_index: int
    chapter_id: Optional[str] = None
    chapter_number: Optional[int] = None
    title: Optional[str] = None
    narration: Optional[str] = None
    duration_seconds: float = 0.0
    visual_prompt: Optional[str] = None
    asset_kind: Optional[str] = None
    status: str
    error_message: Optional[str] = None
    clip_ready: bool = False
    # 转场元数据（不含远端 URL、凭证与 operation id）
    motion_provider: Optional[str] = None
    motion_model: Optional[str] = None
    motion_status: Optional[str] = None
    motion_fallback_used: bool = False
    provider_error: Optional[str] = None
    clip_duration_seconds: Optional[float] = None
    # 场景图元数据（不含 base64、prompt、密钥、路径或远端 URL）
    image_provider: Optional[str] = None
    image_model: Optional[str] = None
    image_status: Optional[str] = None
    image_error: Optional[str] = None
    image_size: Optional[str] = None
    has_image: bool = False


class VideoExportJobResponse(BaseModel):
    """导出任务信息（含 storyboard）"""

    id: str
    project_id: str
    status: str
    progress: int = 0
    status_message: Optional[str] = None
    error_message: Optional[str] = None
    chapter_ids: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    motion_mode: str = "local"
    motion_provider: Optional[str] = None
    motion_model: Optional[str] = None
    image_provider: Optional[str] = None
    image_model: Optional[str] = None
    scene_count: int = 0
    duration_seconds: float = 0.0
    video_size_bytes: Optional[int] = None
    has_video: bool = False
    has_subtitles: bool = False
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None
    scenes: list[VideoExportSceneResponse] = Field(default_factory=list)


class VideoExportJobSummary(BaseModel):
    """任务列表项（不含分镜，减小响应体积）"""

    id: str
    project_id: str
    status: str
    progress: int = 0
    status_message: Optional[str] = None
    error_message: Optional[str] = None
    chapter_ids: list[str] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    motion_mode: str = "local"
    motion_provider: Optional[str] = None
    motion_model: Optional[str] = None
    image_provider: Optional[str] = None
    image_model: Optional[str] = None
    scene_count: int = 0
    duration_seconds: float = 0.0
    video_size_bytes: Optional[int] = None
    has_video: bool = False
    has_subtitles: bool = False
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    updated_at: Optional[str] = None


class VideoExportJobListResponse(BaseModel):
    """任务列表响应"""

    items: list[VideoExportJobSummary] = Field(default_factory=list)
    total: int = 0


class VideoMotionFeatures(BaseModel):
    """provider 支持的特性"""

    image_to_video: bool = True
    narration_postprocess: bool = False
    placeholder: bool = False
    cancel: bool = False
    idempotency: bool = False


class VideoMotionLimits(BaseModel):
    """provider 支持的时长/比例/分辨率"""

    min_duration_seconds: float = 1.0
    max_duration_seconds: float = 8.0
    duration_options: list[float] = Field(default_factory=list)
    aspect_ratios: list[str] = Field(default_factory=list)
    resolutions: list[str] = Field(default_factory=list)
    default_resolution: str = ""


class VideoMotionProviderInfo(BaseModel):
    """provider 能力与配置状态（不包含密钥值、绝对路径）"""

    id: str
    label: str
    kind: str
    description: str = ""
    configured: bool = False
    missing_config: list[str] = Field(default_factory=list)
    config_error: Optional[str] = None
    models: list[str] = Field(default_factory=list)
    default_model: str = ""
    features: VideoMotionFeatures = Field(default_factory=VideoMotionFeatures)
    limits: VideoMotionLimits = Field(default_factory=VideoMotionLimits)
    model_limits: dict[str, VideoMotionLimits] = Field(
        default_factory=dict, description="限制按模型区分（例如 Veo 3.1 只接受 8 秒）"
    )
    cost_note: str = ""


class VideoImageProviderInfo(BaseModel):
    """图片 provider 能力与配置状态（不含密钥值、路径、base64）"""

    id: str
    label: str
    kind: str = "image"
    description: str = ""
    configured: bool = False
    missing_config: list[str] = Field(default_factory=list)
    config_error: Optional[str] = None
    models: list[str] = Field(default_factory=list)
    default_model: str = ""
    aspect_ratios: list[str] = Field(default_factory=list)
    sizes: list[str] = Field(default_factory=list)
    default_size: str = ""
    output_format: str = "webp"
    supports_reasoning_strength: bool = False
    reasoning_strengths: list[str] = Field(default_factory=list)
    cost_note: str = ""


class VideoTTSProviderInfo(BaseModel):
    """TTS provider visible to the client — no secrets."""

    id: str
    label: str
    kind: str = "tts"
    description: str = ""
    configured: bool = False
    missing_config: list[str] = Field(default_factory=list)
    models: list[str] = Field(default_factory=list)
    model_labels: dict[str, str] = Field(default_factory=dict)
    default_model: str = ""
    languages: list[str] = Field(default_factory=list)


class VideoExportCapabilitiesResponse(BaseModel):
    """实例能力与限制说明（不包含 FFmpeg 绝对路径，避免泄露服务端目录）"""

    enabled: bool
    ffmpeg_available: bool
    tts_available: bool = False
    default_tts_provider: Optional[str] = None
    default_tts_model: Optional[str] = None
    tts_hint: Optional[str] = None
    tts_providers: list[VideoTTSProviderInfo] = Field(default_factory=list)
    allowed_resolutions: list[str] = Field(default_factory=list)
    default_resolution: str
    allowed_fps: list[int] = Field(default_factory=list)
    default_fps: int
    max_chapters: int
    max_scenes: int
    max_duration_seconds: int
    max_output_mb: int
    max_active_jobs: int
    job_timeout_seconds: int
    scene_duration_range: list[float] = Field(default_factory=list)
    narration_chars_range: list[int] = Field(default_factory=list)
    default_narration_chars_per_scene: int
    # 视频转场
    motion_modes: list[str] = Field(default_factory=lambda: ["local", "remote", "hybrid"])
    default_motion_mode: str = "local"
    default_motion_provider: Optional[str] = None
    default_motion_model: Optional[str] = None
    default_motion_resolution: Optional[str] = None
    hybrid_fallback_on_error: bool = True
    remote_tts_supported: bool = False
    motion_providers: list[VideoMotionProviderInfo] = Field(default_factory=list)
    # 场景图生成
    image_enabled: bool = True
    default_image_provider: Optional[str] = None
    default_image_model: Optional[str] = None
    default_image_aspect_ratio: Optional[str] = None
    default_image_size: Optional[str] = None
    image_max_mb: int = 16
    image_providers: list[VideoImageProviderInfo] = Field(default_factory=list)


class VideoExportActionResponse(BaseModel):
    """通用动作响应"""

    message: str
    job: VideoExportJobSummary
