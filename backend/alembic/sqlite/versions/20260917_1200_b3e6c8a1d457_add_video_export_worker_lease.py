"""add video export worker lease columns

Revision ID: b3e6c8a1d457
Revises: 7d2f9b4c1e58
Create Date: 2026-09-17 12:00:00

为多 worker 部署补上执行权（lease）字段：
- `worker_token`：当前 worker 的令牌，领取/释放都靠一次条件 UPDATE
- `claimed_at`：领取时间，用于判定过期 lease 并允许其它 worker 接管

幂等：应用启动时会兜底补建缺失的可空列（兼容未执行迁移的旧部署），
离线模式（--sql）按“不存在”处理以生成完整 DDL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3e6c8a1d457"
down_revision: Union[str, None] = "7d2f9b4c1e58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

LEASE_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("worker_token", sa.String(64), nullable=True),
    sa.Column("claimed_at", sa.DateTime(), nullable=True),
)


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
    existing = _existing_columns("video_export_jobs")
    if not existing:
        # 表由更早的迁移创建；此处无需补列
        return
    for column in LEASE_COLUMNS:
        if column.name not in existing:
            op.add_column("video_export_jobs", column)


def downgrade() -> None:
    existing = _existing_columns("video_export_jobs")
    for column in LEASE_COLUMNS:
        if column.name in existing:
            op.drop_column("video_export_jobs", column.name)
