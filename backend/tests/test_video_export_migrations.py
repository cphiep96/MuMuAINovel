"""迁移与旧版本兼容性测试

- 校验 sqlite / postgres 两套迁移图谱：新迁移的 down_revision 指向视频导出表迁移，且两棵树无重复 revision
- 在“旧库”（已存在 video_export_jobs/video_export_scenes 但没有转场列）上执行新迁移的 upgrade()，
  确认新增列被补齐、旧数据保留，并可被 downgrade() 回滚（兼容未执行迁移的旧部署与回滚路径）

说明：postgres 迁移脚本与 sqlite 版本共享同一份 add_column/drop_column 逻辑，
这里在 SQLite 方言上做结构级冒烟（真实 PostgreSQL 由部署时的 `alembic upgrade head` 验证）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import sqlalchemy as sa

alembic = pytest.importorskip("alembic", reason="未安装 alembic 时跳过迁移用例")
from alembic.migration import MigrationContext  # noqa: E402
from alembic.operations import Operations  # noqa: E402

BACKEND_ROOT = Path(__file__).resolve().parents[1]
VERSION_TREES = {
    "sqlite": BACKEND_ROOT / "alembic" / "sqlite" / "versions",
    "postgres": BACKEND_ROOT / "alembic" / "postgres" / "versions",
}
MOTION_MIGRATION_PREFIX = "20260917_1000_7d2f9b4c1e58_add_motion_video_provider_columns"
LEASE_MIGRATION_PREFIX = "20260917_1200_b3e6c8a1d457_add_video_export_worker_lease"
IMAGE_MIGRATION_PREFIX = "20260917_1500_c4f7d9b2e568_add_scene_image_columns"
PDF_MIGRATION_PREFIX = "20260917_1800_e6b1f4a9c287_add_pdf_export_tables"
PDF_ARTIFACT_MIGRATION_PREFIX = "20260917_2000_f7c2a5d8b913_add_pdf_export_artifact_generation"
TTS_MIGRATION_PREFIX = "20260919_2300_a8c3e1f4b702_add_video_tts_settings"
PARENT_REVISION = "5c7d1e9a4b21"
MOTION_REVISION = "7d2f9b4c1e58"
LEASE_REVISION = "b3e6c8a1d457"
IMAGE_REVISION = "c4f7d9b2e568"
PDF_REVISION = "e6b1f4a9c287"
PDF_ARTIFACT_REVISION = "f7c2a5d8b913"
TTS_REVISION = "a8c3e1f4b702"
HEAD_REVISION = TTS_REVISION

JOB_COLUMNS = {"motion_mode", "motion_provider", "motion_model"}
LEASE_COLUMNS = {"worker_token", "claimed_at"}
IMAGE_JOB_COLUMNS = {"image_provider", "image_model"}
IMAGE_SCENE_COLUMNS = {
    "image_provider",
    "image_model",
    "image_status",
    "image_error",
    "image_path",
    "image_size",
}
SCENE_COLUMNS = {
    "motion_provider",
    "motion_model",
    "motion_operation_id",
    "motion_status",
    "motion_idempotency_key",
    "motion_fallback_used",
    "provider_error",
    "clip_duration_seconds",
}


def _load_migration(tree: str, prefix: str):
    path = VERSION_TREES[tree] / f"{prefix}.py"
    assert path.is_file(), f"缺少迁移脚本: {path}"
    spec = importlib.util.spec_from_file_location(f"{prefix}_{tree}", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _load_motion_migration(tree: str):
    return _load_migration(tree, MOTION_MIGRATION_PREFIX)


def _load_lease_migration(tree: str):
    return _load_migration(tree, LEASE_MIGRATION_PREFIX)


def _load_image_migration(tree: str):
    return _load_migration(tree, IMAGE_MIGRATION_PREFIX)


def _load_pdf_migration(tree: str):
    return _load_migration(tree, PDF_MIGRATION_PREFIX)


def _load_pdf_artifact_migration(tree: str):
    return _load_migration(tree, PDF_ARTIFACT_MIGRATION_PREFIX)
def _load_tts_migration(tree: str):
    return _load_migration(tree, TTS_MIGRATION_PREFIX)


def _upgrade_all(tree: str):
    """按图谱顺序执行本功能新增的全部迁移"""
    return (
        _load_motion_migration(tree),
        _load_lease_migration(tree),
        _load_image_migration(tree),
        _load_pdf_migration(tree),
        _load_pdf_artifact_migration(tree),
    )


@pytest.mark.parametrize("tree", sorted(VERSION_TREES))
def test_migration_scripts_link_to_video_export_revision(tree: str):
    motion = _load_motion_migration(tree)
    assert motion.revision == MOTION_REVISION
    assert motion.down_revision == PARENT_REVISION

    lease = _load_lease_migration(tree)
    assert lease.revision == LEASE_REVISION
    assert lease.down_revision == MOTION_REVISION

    image = _load_image_migration(tree)
    assert image.revision == IMAGE_REVISION
    assert image.down_revision == LEASE_REVISION

    pdf = _load_pdf_migration(tree)
    assert pdf.revision == PDF_REVISION
    assert pdf.down_revision == IMAGE_REVISION

    artifact = _load_pdf_artifact_migration(tree)
    assert artifact.revision == PDF_ARTIFACT_REVISION
    assert artifact.down_revision == PDF_REVISION
    tts = _load_tts_migration(tree)
    assert tts.revision == TTS_REVISION
    assert tts.down_revision == PDF_ARTIFACT_REVISION


@pytest.mark.parametrize("tree", sorted(VERSION_TREES))
def test_migration_graph_has_single_head_and_no_duplicate_revisions(tree: str):
    revisions: dict[str, str | None] = {}
    for path in VERSION_TREES[tree].glob("*.py"):
        source = path.read_text(encoding="utf-8")
        revision = None
        parent = None
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith("revision:") or stripped.startswith("revision ="):
                revision = stripped.split("=", 1)[1].strip().strip("'\"")
            elif stripped.startswith("down_revision:") or stripped.startswith("down_revision ="):
                parent = stripped.split("=", 1)[1].strip().strip("'\"")
            if revision and parent is not None:
                break
        assert revision, f"{path.name} 缺少 revision 声明"
        assert revision not in revisions, f"重复 revision: {revision}"
        revisions[revision] = parent

    parents = {parent for parent in revisions.values() if parent}
    heads = sorted(set(revisions) - parents)
    assert heads == [HEAD_REVISION], f"{tree} 迁移图谱应只有一个 head，实际: {heads}"
    assert PARENT_REVISION in revisions
    assert MOTION_REVISION in revisions and LEASE_REVISION in revisions and IMAGE_REVISION in revisions
    assert PDF_REVISION in revisions
    assert PDF_ARTIFACT_REVISION in revisions
    assert TTS_REVISION in revisions


def _legacy_database(path: Path) -> sa.Engine:
    """构造执行视频导出迁移之前的旧库结构（没有转场列）"""
    engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE video_export_jobs (
                id VARCHAR(36) PRIMARY KEY,
                user_id VARCHAR(100) NOT NULL,
                project_id VARCHAR(36) NOT NULL,
                status VARCHAR(20) NOT NULL,
                options JSON,
                scene_count INTEGER
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE video_export_scenes (
                id VARCHAR(36) PRIMARY KEY,
                job_id VARCHAR(36) NOT NULL,
                scene_index INTEGER NOT NULL,
                narration TEXT,
                status VARCHAR(20) NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO video_export_jobs (id, user_id, project_id, status, options) "
            "VALUES ('job-1', 'user-1', 'project-1', 'completed', '{\"resolution\": \"1280x720\"}')"
        )
        connection.exec_driver_sql(
            "INSERT INTO video_export_scenes (id, job_id, scene_index, narration, status) "
            "VALUES ('scene-1', 'job-1', 0, 'noi dung', 'ready')"
        )
    return engine


def _columns(connection, table: str) -> set[str]:
    return {column["name"] for column in sa.inspect(connection).get_columns(table)}


def _settings_database(path: Path) -> sa.Engine:
    engine = sa.create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE settings (id VARCHAR(36) PRIMARY KEY, user_id VARCHAR(50) NOT NULL)"
        )
    return engine


@pytest.mark.parametrize("tree", sorted(VERSION_TREES))
def test_tts_migration_is_idempotent(tree: str, tmp_path: Path):
    module = _load_tts_migration(tree)
    engine = _settings_database(tmp_path / f"tts-{tree}.db")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                module.upgrade()
                module.upgrade()
            expected = {"tts_enabled", "tts_api_provider", "tts_api_key", "tts_api_base_url", "tts_model"}
            assert expected <= _columns(connection, "settings")
            with Operations.context(context):
                module.downgrade()
                module.downgrade()
            assert not (expected & _columns(connection, "settings"))
    finally:
        engine.dispose()


@pytest.mark.parametrize("tree", sorted(VERSION_TREES))
def test_upgrade_backfills_motion_columns_and_keeps_legacy_rows(tree: str, tmp_path: Path):
    migrations = _upgrade_all(tree)
    engine = _legacy_database(tmp_path / f"legacy-{tree}.db")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                for module in migrations:
                    module.upgrade()
                    # 幂等：重复执行 upgrade 不应报错
                    module.upgrade()

            assert JOB_COLUMNS <= _columns(connection, "video_export_jobs")
            assert LEASE_COLUMNS <= _columns(connection, "video_export_jobs")
            assert IMAGE_JOB_COLUMNS <= _columns(connection, "video_export_jobs")
            assert SCENE_COLUMNS <= _columns(connection, "video_export_scenes")
            assert IMAGE_SCENE_COLUMNS <= _columns(connection, "video_export_scenes")
            # PDF 导出表（独立功能）也应被创建
            assert sa.inspect(connection).has_table("pdf_export_jobs")
            assert sa.inspect(connection).has_table("pdf_export_images")

            # 旧任务数据保留，新增列默认为 NULL（读取时按 local 处理、执行权为空即可被领取）
            row = connection.exec_driver_sql(
                "SELECT status, motion_mode, motion_provider, worker_token, claimed_at, image_provider "
                "FROM video_export_jobs WHERE id = 'job-1'"
            ).one()
            assert tuple(row) == ("completed", None, None, None, None, None)
            scene_row = connection.exec_driver_sql(
                "SELECT status, motion_status, image_status, image_path "
                "FROM video_export_scenes WHERE id = 'scene-1'"
            ).one()
            assert tuple(scene_row) == ("ready", None, None, None)
    finally:
        engine.dispose()


@pytest.mark.parametrize("tree", sorted(VERSION_TREES))
def test_downgrade_removes_motion_columns(tree: str, tmp_path: Path):
    migrations = _upgrade_all(tree)
    engine = _legacy_database(tmp_path / f"downgrade-{tree}.db")
    try:
        with engine.begin() as connection:
            context = MigrationContext.configure(connection)
            with Operations.context(context):
                for module in migrations:
                    module.upgrade()
                for module in reversed(migrations):
                    module.downgrade()
            assert not (JOB_COLUMNS & _columns(connection, "video_export_jobs"))
            assert not (LEASE_COLUMNS & _columns(connection, "video_export_jobs"))
            assert not (IMAGE_JOB_COLUMNS & _columns(connection, "video_export_jobs"))
            assert not (SCENE_COLUMNS & _columns(connection, "video_export_scenes"))
            assert not (IMAGE_SCENE_COLUMNS & _columns(connection, "video_export_scenes"))
            assert not sa.inspect(connection).has_table("pdf_export_jobs")
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM video_export_jobs").scalar() == 1
    finally:
        engine.dispose()


def test_startup_schema_sync_backfills_legacy_database(tmp_path: Path):
    """未执行迁移的旧部署：启动时应补建缺失表并补齐转场列，旧任务保持可读"""
    from app.services.video_export.schema import sync_video_export_schema

    engine = _legacy_database(tmp_path / "startup.db")
    try:
        with engine.begin() as connection:
            added = sync_video_export_schema(connection)
            assert any(name.endswith(".motion_mode") for name in added)
            assert any(name.endswith(".worker_token") for name in added)
            assert any(name.endswith(".image_status") for name in added)
            assert JOB_COLUMNS <= _columns(connection, "video_export_jobs")
            assert LEASE_COLUMNS <= _columns(connection, "video_export_jobs")
            assert IMAGE_JOB_COLUMNS <= _columns(connection, "video_export_jobs")
            assert SCENE_COLUMNS <= _columns(connection, "video_export_scenes")
            assert IMAGE_SCENE_COLUMNS <= _columns(connection, "video_export_scenes")
            assert connection.exec_driver_sql("SELECT status FROM video_export_jobs").scalar() == "completed"

            # 幂等：再次调用不再补列
            assert sync_video_export_schema(connection) == []
    finally:
        engine.dispose()


def test_startup_schema_sync_creates_missing_tables(tmp_path: Path):
    from app.services.pdf_export.schema import sync_pdf_export_schema
    from app.services.video_export.schema import sync_video_export_schema

    engine = sa.create_engine(f"sqlite:///{(tmp_path / 'empty.db').as_posix()}")
    try:
        with engine.begin() as connection:
            sync_video_export_schema(connection)
            inspector = sa.inspect(connection)
            assert inspector.has_table("video_export_jobs")
            assert inspector.has_table("video_export_scenes")
            assert JOB_COLUMNS <= _columns(connection, "video_export_jobs")
            assert LEASE_COLUMNS <= _columns(connection, "video_export_jobs")
            assert IMAGE_JOB_COLUMNS <= _columns(connection, "video_export_jobs")
            assert SCENE_COLUMNS <= _columns(connection, "video_export_scenes")
            assert IMAGE_SCENE_COLUMNS <= _columns(connection, "video_export_scenes")

            # PDF 导出表由独立的 sync 负责（同样幂等）
            assert sync_pdf_export_schema(connection) == []
            assert sa.inspect(connection).has_table("pdf_export_jobs")
            assert sa.inspect(connection).has_table("pdf_export_images")
            expected = {
                "status",
                "progress",
                "options",
                "warnings",
                "page_count",
                "output_path",
                "file_size_bytes",
                "worker_token",
                "claimed_at",
                "chapter_count",
                "image_count",
                "text_chars",
                "output_generation",
                "output_created_at",
                "run_attempt",
            }
            assert expected <= _columns(connection, "pdf_export_jobs")
            assert {"status", "provider", "model", "size", "path", "error"} <= _columns(
                connection, "pdf_export_images"
            )
    finally:
        engine.dispose()
