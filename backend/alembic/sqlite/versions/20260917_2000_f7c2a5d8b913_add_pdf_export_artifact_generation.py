"""add pdf export artifact generation columns

Revision ID: f7c2a5d8b913
Revises: e6b1f4a9c287
Create Date: 2026-09-17 20:00:00

为 PDF 导出补充「产物代次」字段，使重试失败/取消时**不会丢掉上一次成功的 PDF**：
- `output_generation`：成功产物代次（每次构建成功 +1，用于区分旧产物与新一次运行）
- `output_created_at`：当前产物生成时间
- `run_attempt`：运行代次（每次开始执行 +1），也用于生成本次构建的临时文件名

幂等：应用启动时会兜底补建缺失的可空列（兼容未执行迁移的旧部署），
离线模式（--sql）按“不存在”处理以生成完整 DDL。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f7c2a5d8b913"
down_revision: Union[str, None] = "e6b1f4a9c287"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ARTIFACT_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("output_generation", sa.Integer(), nullable=True),
    sa.Column("output_created_at", sa.DateTime(), nullable=True),
    sa.Column("run_attempt", sa.Integer(), nullable=True),
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
    existing = _existing_columns("pdf_export_jobs")
    if not existing:
        # 表由更早的迁移创建；此处无需补列
        return
    for column in ARTIFACT_COLUMNS:
        if column.name not in existing:
            op.add_column("pdf_export_jobs", column)


def downgrade() -> None:
    existing = _existing_columns("pdf_export_jobs")
    for column in ARTIFACT_COLUMNS:
        if column.name in existing:
            op.drop_column("pdf_export_jobs", column.name)
