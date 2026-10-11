"""add video tts settings columns

Revision ID: a8c3e1f4b702
Revises: f7c2a5d8b913
Create Date: 2026-09-19 23:00:00

Lưu cấu hình Deepgram / OpenAI-compatible TTS trên trang Cài đặt của user.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8c3e1f4b702"
down_revision: Union[str, None] = "f7c2a5d8b913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TTS_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("tts_enabled", sa.Boolean(), nullable=True, server_default=sa.text("false"), comment="是否启用视频旁白 TTS"),
    sa.Column("tts_api_provider", sa.String(length=50), nullable=True, comment="视频 TTS 提供商"),
    sa.Column("tts_api_key", sa.String(length=500), nullable=True, comment="视频 TTS API 密钥"),
    sa.Column("tts_api_base_url", sa.String(length=500), nullable=True, comment="视频 TTS API 地址"),
    sa.Column("tts_model", sa.String(length=100), nullable=True, comment="视频 TTS 模型/音色"),
)


def _existing_columns() -> set[str] | None:
    bind = op.get_bind()
    if bind is None or type(bind).__name__ == "MockConnection":
        return None
    inspector = sa.inspect(bind)
    if not inspector.has_table("settings"):
        return set()
    return {column["name"] for column in inspector.get_columns("settings")}


def upgrade() -> None:
    existing = _existing_columns()
    for column in TTS_COLUMNS:
        if existing is None or column.name not in existing:
            op.add_column("settings", column)


def downgrade() -> None:
    existing = _existing_columns()
    for column in reversed(TTS_COLUMNS):
        if existing is None or column.name in existing:
            op.drop_column("settings", column.name)
