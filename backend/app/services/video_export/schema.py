"""视频导出表结构的启动兜底同步

Alembic 仍是结构的唯一来源，但打包发布（EXE/Docker）常出现“代码已升级、迁移未执行”的情况，
因此启动时补建缺失的表，并为本功能新增的 **可空** 列补齐列，保证旧任务仍可读写。

只处理 video_export_* 两张表与视频导出的新增列，不修改其他表，也不改变既有列类型。
"""
from __future__ import annotations

from typing import Iterable, Sequence

import sqlalchemy as sa

from app.logger import get_logger

logger = get_logger(__name__)

# 允许在启动时自动补齐的可空列（其余缺失列只提示，需人工执行 alembic upgrade head）
ADDITIVE_COLUMNS: frozenset[str] = frozenset(
    {
        "motion_mode",
        "motion_provider",
        "motion_model",
        "motion_operation_id",
        "motion_status",
        "motion_idempotency_key",
        "motion_fallback_used",
        "provider_error",
        "clip_duration_seconds",
        "worker_token",
        "claimed_at",
        "image_provider",
        "image_model",
        "image_status",
        "image_error",
        "image_path",
        "image_size",
    }
)

# 这些列非空且无默认值，不能通过 ALTER TABLE 直接追加
NON_ADDITIVE_COLUMNS: frozenset[str] = frozenset({"status", "user_id", "project_id", "scene_index"})


def _models() -> Sequence[type]:
    """延迟导入模型，并先把 `app.database` 导入好

    本仓库的 `app.models` 与 `app.database` 互相引用（database 定义 Base 后再导入全部模型），
    因此必须先导入 `app.database`，否则当本模块成为进程里的第一个导入者时会触发循环导入。
    """
    import app.database  # noqa: F401 - 先建立 Base，再导入模型
    from app.models.video_export import VideoExportJob, VideoExportScene

    return (VideoExportJob, VideoExportScene)


def _columns(connection, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table_name)}


def _create_missing_tables(connection) -> None:
    for model in _models():
        model.__table__.create(connection, checkfirst=True)


def _add_missing_columns(connection, models: Iterable[type] | None = None) -> list[str]:
    """为缺失的可空列执行 ADD COLUMN，返回已补齐的列名（用于日志/测试断言）"""
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


def sync_video_export_schema(connection) -> list[str]:
    """补建缺失表并补齐转场新增列；返回本次补齐的列（幂等，可重复调用）"""
    _create_missing_tables(connection)
    added = _add_missing_columns(connection)
    if added:
        logger.info("已自动补齐视频导出新增列: %s", ", ".join(added))
    return added
