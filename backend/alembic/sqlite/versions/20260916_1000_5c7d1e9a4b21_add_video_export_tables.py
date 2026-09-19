"""add video export tables

Revision ID: 5c7d1e9a4b21
Revises: f0e1d2c3b4a5
Create Date: 2026-09-16 10:00:00
"""
from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa


revision: str = "5c7d1e9a4b21"
down_revision: Union[str, None] = "f0e1d2c3b4a5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    """表是否已存在

    应用启动时会兜底创建视频导出表（兼容未执行迁移的旧部署），
    所以这里必须幂等，否则后续 `alembic upgrade head` 会因表已存在而失败。
    离线模式（--sql）没有连接，按“不存在”处理以生成完整 DDL。
    """
    if context.is_offline_mode():
        return False
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if not _has_table("video_export_jobs"):
        op.create_table(
            "video_export_jobs",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(100), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=True),
            sa.Column("status_message", sa.String(500), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("chapter_ids", sa.JSON(), nullable=True),
            sa.Column("options", sa.JSON(), nullable=True),
            sa.Column("scene_count", sa.Integer(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("video_path", sa.String(500), nullable=True),
            sa.Column("subtitle_path", sa.String(500), nullable=True),
            sa.Column("video_size_bytes", sa.Integer(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_video_export_jobs_user_id", "video_export_jobs", ["user_id"])
        op.create_index("ix_video_export_jobs_project_id", "video_export_jobs", ["project_id"])

    if not _has_table("video_export_scenes"):
        op.create_table(
            "video_export_scenes",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("job_id", sa.String(36), nullable=False),
            sa.Column("scene_index", sa.Integer(), nullable=False),
            sa.Column("chapter_id", sa.String(36), nullable=True),
            sa.Column("chapter_number", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(200), nullable=True),
            sa.Column("narration", sa.Text(), nullable=True),
            sa.Column("duration_seconds", sa.Float(), nullable=True),
            sa.Column("visual_prompt", sa.Text(), nullable=True),
            sa.Column("asset_kind", sa.String(20), nullable=True),
            sa.Column("asset_path", sa.String(500), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["job_id"], ["video_export_jobs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_video_export_scenes_job_id", "video_export_scenes", ["job_id"])


def downgrade() -> None:
    if _has_table("video_export_scenes"):
        op.drop_table("video_export_scenes")
    if _has_table("video_export_jobs"):
        op.drop_table("video_export_jobs")
