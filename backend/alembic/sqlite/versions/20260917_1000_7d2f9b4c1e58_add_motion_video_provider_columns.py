"""add motion video provider columns

Revision ID: 7d2f9b4c1e58
Revises: 5c7d1e9a4b21
Create Date: 2026-09-17 10:00:00

为视频转场 provider（远端 image-to-video）补充字段：
- `video_export_jobs`：motion_mode / motion_provider / motion_model
- `video_export_scenes`：provider、远端 operation 状态、幂等键、错误摘要与片段实际时长

幂等：应用启动时会兜底补建缺失列（兼容未执行迁移的旧部署），因此这里只补缺失列，
离线模式（--sql）按“不存在”处理以生成完整 DDL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "7d2f9b4c1e58"
down_revision: Union[str, None] = "5c7d1e9a4b21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOB_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("motion_mode", sa.String(20), nullable=True),
    sa.Column("motion_provider", sa.String(50), nullable=True),
    sa.Column("motion_model", sa.String(100), nullable=True),
)

SCENE_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("motion_provider", sa.String(50), nullable=True),
    sa.Column("motion_model", sa.String(100), nullable=True),
    sa.Column("motion_operation_id", sa.String(200), nullable=True),
    sa.Column("motion_status", sa.String(20), nullable=True),
    sa.Column("motion_idempotency_key", sa.String(120), nullable=True),
    sa.Column("motion_fallback_used", sa.Boolean(), nullable=True),
    sa.Column("provider_error", sa.Text(), nullable=True),
    sa.Column("clip_duration_seconds", sa.Float(), nullable=True),
)

TABLES = (("video_export_jobs", JOB_COLUMNS), ("video_export_scenes", SCENE_COLUMNS))


def _existing_columns(table: str) -> set[str] | None:
    """Return columns, or ``None`` when offline introspection is unavailable."""
    bind = op.get_bind()
    if bind is None or type(bind).__name__ == "MockConnection":
        return None
    inspector = sa.inspect(bind)
    if not inspector.has_table(table):
        return set()
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    for table, columns in TABLES:
        existing = _existing_columns(table)
        if existing is None:
            # Offline --sql cannot inspect the table, so emit the complete DDL.
            for column in columns:
                op.add_column(table, column)
            continue
        if not existing:
            # The table is genuinely absent; a later table-creation migration owns it.
            continue
        for column in columns:
            if column.name not in existing:
                op.add_column(table, column)


def downgrade() -> None:
    for table, columns in TABLES:
        existing = _existing_columns(table)
        if existing is None:
            for column in columns:
                op.drop_column(table, column.name)
            continue
        for column in columns:
            if column.name in existing:
                op.drop_column(table, column.name)
