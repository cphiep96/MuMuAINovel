"""Bổ sung cột Settings khi khởi động (tương thích chưa chạy Alembic)."""
from __future__ import annotations

from typing import Iterable

import sqlalchemy as sa

from app.logger import get_logger

logger = get_logger(__name__)

ADDITIVE_COLUMNS: frozenset[str] = frozenset(
    {
        "tts_enabled",
        "tts_api_provider",
        "tts_api_key",
        "tts_api_base_url",
        "tts_model",
    }
)


def _columns(connection, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table_name)}


def _add_missing_columns(connection, models: Iterable[type]) -> list[str]:
    added: list[str] = []
    for model in models:
        table = model.__table__
        if not sa.inspect(connection).has_table(table.name):
            continue
        missing = {column.name for column in table.columns} - _columns(connection, table.name)
        if not missing:
            continue
        columns = {column.name: column for column in table.columns}
        for name in sorted(missing & ADDITIVE_COLUMNS):
            column_type = columns[name].type.compile(dialect=connection.dialect)
            extra = ""
            if name == "tts_enabled":
                extra = " DEFAULT FALSE" if connection.dialect.name == "postgresql" else " DEFAULT 0"
            connection.exec_driver_sql(
                f"ALTER TABLE {table.name} ADD COLUMN {name} {column_type}{extra}"
            )
            added.append(f"{table.name}.{name}")
    return added


def sync_settings_schema(connection) -> list[str]:
    import app.database  # noqa: F401
    from app.models.settings import Settings

    added = _add_missing_columns(connection, (Settings,))
    if added:
        logger.info("Đã tự động bổ sung cột cài đặt TTS: %s", ", ".join(added))
    return added
