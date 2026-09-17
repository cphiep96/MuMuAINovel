"""add pdf export tables

Revision ID: e6b1f4a9c287
Revises: c4f7d9b2e568
Create Date: 2026-09-17 18:00:00

为「PDF 全本导出」新增两张表：
- `pdf_export_jobs`：任务状态/进度/参数/结果（页数、体积、警告）与跨进程执行权
- `pdf_export_images`：每章插图记录（缓存 + 只重做失败图片），只保存受管目录内的相对路径

幂等：应用启动时会兜底建表（兼容未执行迁移的旧部署），因此这里用 `has_table` 判断，
离线模式（--sql）按“不存在”处理以生成完整 DDL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6b1f4a9c287"
down_revision: Union[str, None] = "c4f7d9b2e568"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(name: str) -> bool:
    """表是否已存在；离线模式（--sql）没有连接，按"不存在"处理以生成完整 DDL"""
    bind = op.get_bind()
    if bind is None or type(bind).__name__ == "MockConnection":
        return False
    return sa.inspect(bind).has_table(name)


def upgrade() -> None:
    if not _has_table("pdf_export_jobs"):
        op.create_table(
            "pdf_export_jobs",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("user_id", sa.String(100), nullable=False),
            sa.Column("project_id", sa.String(36), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("progress", sa.Integer(), nullable=True),
            sa.Column("status_message", sa.String(500), nullable=True),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("warnings", sa.JSON(), nullable=True),
            sa.Column("options", sa.JSON(), nullable=True),
            sa.Column("chapter_count", sa.Integer(), nullable=True),
            sa.Column("image_count", sa.Integer(), nullable=True),
            sa.Column("text_chars", sa.Integer(), nullable=True),
            sa.Column("page_count", sa.Integer(), nullable=True),
            sa.Column("output_path", sa.String(500), nullable=True),
            sa.Column("file_size_bytes", sa.Integer(), nullable=True),
            sa.Column("worker_token", sa.String(64), nullable=True),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("started_at", sa.DateTime(), nullable=True),
            sa.Column("completed_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_pdf_export_jobs_user_id", "pdf_export_jobs", ["user_id"])
        op.create_index("ix_pdf_export_jobs_project_id", "pdf_export_jobs", ["project_id"])

    if not _has_table("pdf_export_images"):
        op.create_table(
            "pdf_export_images",
            sa.Column("id", sa.String(36), nullable=False),
            sa.Column("job_id", sa.String(36), nullable=False),
            sa.Column("chapter_id", sa.String(36), nullable=True),
            sa.Column("chapter_number", sa.Integer(), nullable=True),
            sa.Column("sub_index", sa.Integer(), nullable=True),
            sa.Column("title", sa.String(200), nullable=True),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("provider", sa.String(50), nullable=True),
            sa.Column("model", sa.String(100), nullable=True),
            sa.Column("size", sa.String(20), nullable=True),
            sa.Column("path", sa.String(500), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.ForeignKeyConstraint(["job_id"], ["pdf_export_jobs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_pdf_export_images_job_id", "pdf_export_images", ["job_id"])


def downgrade() -> None:
    if _has_table("pdf_export_images"):
        op.drop_table("pdf_export_images")
    if _has_table("pdf_export_jobs"):
        op.drop_table("pdf_export_jobs")
