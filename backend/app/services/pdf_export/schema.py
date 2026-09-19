"""PDF 导出表结构的启动兜底同步

与视频导出一致：Alembic 仍是结构唯一来源，但打包发布（EXE/Docker）常出现"代码已升级、
迁移未执行"的情况，因此启动时补建缺失的表并补齐新增的可空列，保证旧库仍可读写。

只处理 pdf_export_* 两张表，不修改其他表。
"""
from __future__ import annotations

from typing import Iterable, Sequence

import sqlalchemy as sa

from app.logger import get_logger

logger = get_logger(__name__)

# 允许在启动时自动补齐的可空列（其余缺失列只提示，需人工执行 alembic upgrade head）
ADDITIVE_COLUMNS: frozenset[str] = frozenset(
    {
        "warnings",
        "chapter_count",
        "image_count",
        "text_chars",
        "page_count",
        "output_path",
        "file_size_bytes",
        "output_generation",
        "output_created_at",
        "run_attempt",
        "worker_token",
        "claimed_at",
        "provider",
        "model",
        "size",
        "path",
        "error",
        "sub_index",
        "chapter_number",
        "chapter_id",
        "title",
    }
)


def _models() -> Sequence[type]:
    """延迟导入模型，并先导入 app.database（定义 Base）以避免循环导入"""
    import app.database  # noqa: F401
    from app.models.pdf_export import PdfExportImage, PdfExportJob

    return (PdfExportJob, PdfExportImage)


def _columns(connection, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table_name)}


def _create_missing_tables(connection) -> None:
    for model in _models():
        model.__table__.create(connection, checkfirst=True)


def _add_missing_columns(connection, models: Iterable[type] | None = None) -> list[str]:
    added: list[str] = []
    for model in models if models is not None else _models():
        table = model.__table__
        missing = {column.name for column in table.columns} - _columns(connection, table.name)
        if not missing:
            continue
        columns = {column.name: column for column in table.columns}
        for name in sorted(missing & ADDITIVE_COLUMNS):
            column_type = columns[name].type.compile(dialect=connection.dialect)
            connection.exec_driver_sql(f"ALTER TABLE {table.name} ADD COLUMN {name} {column_type}")
            added.append(f"{table.name}.{name}")
        remaining = missing - ADDITIVE_COLUMNS
        if remaining:
            logger.warning(
                "⚠️ Bảng %s thiếu cột %s, vui lòng chạy 'alembic upgrade head' để đồng bộ cấu trúc",
                table.name,
                ", ".join(sorted(remaining)),
            )
    return added


def sync_pdf_export_schema(connection) -> list[str]:
    """补建缺失表并补齐新增列；返回本次补齐的列（幂等）"""
    _create_missing_tables(connection)
    added = _add_missing_columns(connection)
    if added:
        logger.info("已自动补齐 PDF 导出新增列: %s", ", ".join(added))
    return added
