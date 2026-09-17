"""add scene image generation columns

Revision ID: c4f7d9b2e568
Revises: b3e6c8a1d457
Create Date: 2026-09-17 15:00:00

为“场景图片生成”（image provider，例如 Meta Muse Image）补充字段：
- `video_export_jobs`：image_provider / image_model
- `video_export_scenes`：image_provider / image_model / image_status / image_error / image_path / image_size

注意：`image_path` 只保存任务目录内的相对路径，供服务端定位素材；
**不保存**远端 URL、base64 或任何密钥，也不对外返回。

幂等：应用启动时会兜底补建缺失的可空列（兼容未执行迁移的旧部署），
离线模式（--sql）按“不存在”处理以生成完整 DDL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c4f7d9b2e568"
down_revision: Union[str, None] = "b3e6c8a1d457"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOB_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("image_provider", sa.String(50), nullable=True),
    sa.Column("image_model", sa.String(100), nullable=True),
)

SCENE_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("image_provider", sa.String(50), nullable=True),
    sa.Column("image_model", sa.String(100), nullable=True),
    sa.Column("image_status", sa.String(20), nullable=True),
    sa.Column("image_error", sa.Text(), nullable=True),
    sa.Column("image_path", sa.String(500), nullable=True),
    sa.Column("image_size", sa.String(20), nullable=True),
)

TABLES = (("video_export_jobs", JOB_COLUMNS), ("video_export_scenes", SCENE_COLUMNS))


def _existing_columns(table: str) -> set[str]:
    """已存在的列名；离线模式（--sql）或表不存在时返回空集合"""
    bind = op.get_bind()
    if bind is None or type(bind).__name__ == "MockConnection":
        return set()
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    for table, columns in TABLES:
        existing = _existing_columns(table)
        if not existing:
            # 表由更早的迁移创建；此处无需补列
            continue
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade() -> None:
    for table, columns in TABLES:
        existing = _existing_columns(table)
        for column in columns:
            if column.name in existing:
                op.drop_column(table, column.name)
