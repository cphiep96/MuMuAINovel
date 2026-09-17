"""视频导出数据模型 - 章节转分镜并渲染为 MP4 的任务与分镜记录"""
from sqlalchemy import (
    Boolean,
    Column,
    String,
    Integer,
    Float,
    DateTime,
    Text,
    JSON,
    ForeignKey,
)
from sqlalchemy.sql import func
from app.database import Base
import uuid


class VideoExportJob(Base):
    """视频导出任务表 - 记录一次"章节 → 分镜 → MP4/SRT"的导出过程"""

    __tablename__ = "video_export_jobs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String(100), nullable=False, index=True, comment="用户ID")
    project_id = Column(
        String(36),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="项目ID",
    )

    # 任务状态
    status = Column(
        String(20),
        default="pending",
        nullable=False,
        comment="任务状态: pending/running/completed/failed/cancelled",
    )
    progress = Column(Integer, default=0, comment="进度百分比(0-100)")
    status_message = Column(String(500), comment="当前状态消息")
    error_message = Column(Text, comment="失败原因")

    # 输入与参数
    chapter_ids = Column(JSON, comment="参与导出的章节ID列表")
    options = Column(JSON, comment="导出参数: resolution/fps/use_project_cover/tts_enabled 等")

    # 视频转场模式（旧任务为 NULL，读取时按 local 处理）
    motion_mode = Column(String(20), comment="转场模式: local/remote/hybrid")
    motion_provider = Column(String(50), comment="使用的转场 provider 名称")
    motion_model = Column(String(100), comment="provider 模型名")

    # 跨进程执行权（lease）：多 worker 部署时用一次原子 UPDATE 抢占，避免重复提交远端任务
    worker_token = Column(String(64), comment="当前执行该任务的 worker 令牌")
    claimed_at = Column(DateTime, comment="执行权领取时间（用于判定过期 lease）")

    # 场景图片生成（image provider，例如 Meta Muse Image）
    image_provider = Column(String(50), comment="生成场景图的 provider 名称")
    image_model = Column(String(100), comment="图片 provider 的模型名")

    # 结果概览
    scene_count = Column(Integer, default=0, comment="分镜数量")
    duration_seconds = Column(Float, default=0.0, comment="总时长(秒)")
    video_path = Column(String(500), comment="成片相对路径(相对视频存储根目录)")
    subtitle_path = Column(String(500), comment="SRT 字幕相对路径")
    video_size_bytes = Column(Integer, comment="成片大小(字节)")

    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    started_at = Column(DateTime, comment="开始时间")
    completed_at = Column(DateTime, comment="完成时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<VideoExportJob(id={self.id[:8]}, status={self.status}, progress={self.progress}%)>"


class VideoExportScene(Base):
    """视频分镜表 - 每个分镜保存旁白、时长、画面提示词与渲染状态"""

    __tablename__ = "video_export_scenes"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    job_id = Column(
        String(36),
        ForeignKey("video_export_jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属导出任务ID",
    )
    scene_index = Column(Integer, nullable=False, comment="分镜序号(从0开始)")
    chapter_id = Column(String(36), comment="来源章节ID")
    chapter_number = Column(Integer, comment="来源章节序号")
    title = Column(String(200), comment="分镜标题")
    narration = Column(Text, comment="旁白文本(用于字幕与 TTS)")
    duration_seconds = Column(Float, default=0.0, comment="分镜时长(秒)")
    visual_prompt = Column(Text, comment="画面提示词(可用于后续图片生成)")
    asset_kind = Column(String(20), default="placeholder", comment="画面来源: cover/placeholder/image")
    asset_path = Column(String(500), comment="渲染片段相对路径(相对任务目录)")

    # 远端转场元数据（只保存 operation id/状态，绝不上库远端 URL 或凭证）
    motion_provider = Column(String(50), comment="本分镜使用的 provider")
    motion_model = Column(String(100), comment="本分镜使用的模型")
    motion_operation_id = Column(String(200), comment="远端操作ID（诊断用）")
    motion_status = Column(String(20), comment="远端状态: pending/running/completed/failed/cancelled/skipped")
    motion_idempotency_key = Column(String(120), comment="幂等键（仅 provider 支持时发送）")
    motion_fallback_used = Column(Boolean, default=False, comment="是否已回落到本地 FFmpeg")
    provider_error = Column(Text, comment="provider 返回的错误摘要")
    clip_duration_seconds = Column(Float, comment="片段实际时长(秒)，用于字幕对齐")

    # 场景图片生成元数据（只保存 provider/状态/相对路径，绝不保存密钥或远端 URL）
    image_provider = Column(String(50), comment="生成该分镜画面的 provider")
    image_model = Column(String(100), comment="图片模型名")
    image_status = Column(String(20), comment="图片状态: pending/generating/ready/failed/cancelled")
    image_error = Column(Text, comment="图片生成失败原因摘要")
    image_path = Column(String(500), comment="场景图相对路径(相对任务目录)，仅服务端使用")
    image_size = Column(String(20), comment="请求的图片尺寸，如 1792x1024")

    status = Column(
        String(20),
        default="pending",
        nullable=False,
        comment="分镜状态: pending/rendering/ready/failed",
    )
    error_message = Column(Text, comment="分镜渲染失败原因")

    created_at = Column(DateTime, server_default=func.now(), comment="创建时间")
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), comment="更新时间")

    def __repr__(self):
        return f"<VideoExportScene(id={self.id[:8]}, index={self.scene_index}, status={self.status})>"
