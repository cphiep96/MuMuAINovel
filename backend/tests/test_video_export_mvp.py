"""视频导出 MVP 的本地测试：分镜启发式、SRT、参数校验、路径安全与 FFmpeg 端到端。

运行：cd backend && python -m pytest tests/test_video_export_mvp.py -q
（无 FFmpeg 的机器上，端到端用例会自动跳过）
"""
from __future__ import annotations

import asyncio
import time
import uuid

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models.background_task import BackgroundTask
from app.models.chapter import Chapter
from app.models.project import Project
from app.models.video_export import VideoExportJob, VideoExportScene
from app.services.background_task_service import background_task_service
from app.services.video_export import ffmpeg_runner
from app.services.video_export.paths import normalize_relative_path, resolve_stored_path
from app.services.video_export.service import (
    VideoExportService,
    normalize_options,
    serialize_job,
    video_export_service,
)
from app.services.video_export.storyboard import (
    SourceChapter,
    StoryboardOptions,
    build_storyboard,
    build_visual_prompt,
    chunk_sentences,
    estimate_duration,
    normalize_text,
    split_sentences,
    validate_storyboard_limits,
)
from app.services.video_export.subtitles import build_srt, format_timestamp

FFMPEG_AVAILABLE = ffmpeg_runner.ffmpeg_binary() is not None


# --------------------------------------------------------------------------- SRT


def test_format_timestamp_matches_srt_spec():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(1.5) == "00:00:01,500"
    assert format_timestamp(3661.007) == "01:01:01,007"
    # 负值不应产生非法时间戳
    assert format_timestamp(-3) == "00:00:00,000"


def test_build_srt_is_sequential_and_monotonic():
    srt = build_srt([("Cảnh một.", 3.0), ("Cảnh hai.", 4.5), ("", 2.0)])

    blocks = [block for block in srt.split("\n\n") if block.strip()]
    assert len(blocks) == 2, "空文本不应生成字幕块"
    assert blocks[0].startswith("1\n00:00:00,000 --> 00:00:03,000\nCảnh một.")
    assert blocks[1].startswith("2\n00:00:03,000 --> 00:00:07,500\nCảnh hai.")


def test_build_srt_enforces_minimum_cue_length():
    srt = build_srt([("Ngắn.", 0.0)])
    assert "00:00:00,000 --> 00:00:00,500" in srt


def test_build_srt_keeps_internal_newlines():
    srt = build_srt([("dòng 1\ndòng 2", 2.0)])
    assert "dòng 1\ndòng 2" in srt


# --------------------------------------------------------------------------- storyboard


def test_normalize_and_split_text():
    raw = "# Tiêu đề\n\n**Đoạn một!** Đoạn hai? Đoạn ba."
    cleaned = normalize_text(raw)
    assert "#" not in cleaned and "*" not in cleaned
    # 标题行保留为独立片段，不会与正文混在一起
    assert split_sentences(cleaned) == ["Tiêu đề", "Đoạn một!", "Đoạn hai?", "Đoạn ba."]


def test_chunk_sentences_merges_short_tail():
    chunks = chunk_sentences(["aaaa.", "bbbb.", "c."], max_chars=8, min_chars=4)
    assert len(chunks) >= 1
    assert all(chunk.strip() for chunk in chunks)
    assert "c." in chunks[-1]


def test_estimate_duration_is_clamped():
    assert estimate_duration("a" * 12, 12.0) == 3.0 or estimate_duration("a" * 12, 12.0) >= 3.0
    assert estimate_duration("a" * 100000, 12.0) == 12.0  # 上限
    assert estimate_duration("a", 12.0) == 3.0  # 下限


def test_build_storyboard_produces_scenes_per_chapter():
    chapters = [
        SourceChapter(id="c1", chapter_number=1, title="Khởi hành", content="Câu một. " * 60),
        SourceChapter(id="c2", chapter_number=2, title="Gặp gỡ", content="Nội dung ngắn gọn."),
    ]
    scenes = build_storyboard(chapters, StoryboardOptions(narration_chars_per_scene=200))

    assert len(scenes) >= 2
    assert [scene.scene_index for scene in scenes] == list(range(len(scenes)))
    assert {scene.chapter_id for scene in scenes} == {"c1", "c2"}
    for scene in scenes:
        assert scene.narration
        assert 3.0 <= scene.duration_seconds <= 12.0
        assert scene.title
        assert scene.visual_prompt


def test_visual_prompt_is_deterministic_and_has_no_ai_dependency():
    prompt = build_visual_prompt("Khởi hành", 0, "Trời chưa sáng, đoàn người lặng lẽ rời làng.")
    assert prompt == build_visual_prompt("Khởi hành", 0, "Trời chưa sáng, đoàn người lặng lẽ rời làng.")
    assert "Khởi hành" in prompt


def test_validate_storyboard_limits_rejects_too_many_scenes():
    from app.services.video_export.storyboard import StoryboardScene

    scene = StoryboardScene(0, "c1", 1, "t", "n", 3.0, "p")
    from app.config import settings

    too_many = [scene] * (settings.video_max_scenes + 1)
    with pytest.raises(HTTPException) as exc:
        validate_storyboard_limits(too_many)
    assert exc.value.status_code == 400
    assert "giới hạn" in exc.value.detail


# --------------------------------------------------------------------------- options validation


def test_normalize_options_defaults():
    options = normalize_options(None)
    assert options["resolution"] == "1280x720"
    assert options["fps"] == 24
    assert options["use_project_cover"] is True
    assert options["tts_enabled"] is False


@pytest.mark.parametrize(
    "payload, expected",
    [
        ({"resolution": "4096x2160"}, "Độ phân giải"),
        ({"fps": 7}, "FPS"),
        ({"narration_chars_per_scene": 10}, "Số ký tự"),
    ],
)
def test_normalize_options_rejects_invalid_values(payload, expected):
    with pytest.raises(HTTPException) as exc:
        normalize_options(payload)
    assert exc.value.status_code == 400
    assert expected in exc.value.detail


# --------------------------------------------------------------------------- path safety


@pytest.mark.parametrize("relative", ["../secret.mp4", "a/../../b.mp4", "/etc/passwd", "C:/windows/x.mp4"])
def test_normalize_relative_path_rejects_traversal(relative):
    with pytest.raises(HTTPException) as exc:
        normalize_relative_path(relative)
    assert exc.value.status_code == 404


def test_resolve_stored_path_stays_inside_root(tmp_path):
    root = tmp_path / "videos"
    root.mkdir()
    inside = root / "u1" / "j1" / "output.mp4"
    inside.parent.mkdir(parents=True)
    inside.write_bytes(b"x")

    assert resolve_stored_path(root, "u1/j1/output.mp4") == inside.resolve()
    with pytest.raises(HTTPException):
        resolve_stored_path(root, "../outside.mp4")


# --------------------------------------------------------------------------- service (sqlite)


@pytest_asyncio.fixture
async def engine(tmp_path):
    # 使用文件型 SQLite，便于后台流水线用另一个会话读取同一份数据
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'test.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as db:
        yield db


@pytest.fixture(autouse=True)
def isolated_video_storage(tmp_path, monkeypatch):
    """所有用例的成片/片段都写到临时目录，避免污染仓库内的 storage"""
    from app.services.video_export import paths as video_paths
    from app.services.video_export import service as service_module

    root = tmp_path / "video-storage"
    monkeypatch.setattr(video_paths, "VIDEO_STORAGE_DIR", root)
    monkeypatch.setattr(service_module, "VIDEO_STORAGE_DIR", root)
    return root


@pytest_asyncio.fixture
async def sample_project(session: AsyncSession):
    project = Project(id=str(uuid.uuid4()), user_id="user-1", title="Dự án thử nghiệm")
    session.add(project)
    session.add(
        Chapter(
            id=str(uuid.uuid4()),
            project_id=project.id,
            chapter_number=1,
            title="Chương một",
            content="Trời chưa sáng. Đoàn người rời làng. " * 40,
        )
    )
    await session.commit()
    return project


def _stub_spawn(monkeypatch, stub_ffmpeg: bool = True):
    spawned: list[tuple[str, str]] = []

    async def fake_spawn(task_id, user_id, task_func, *args, **kwargs):
        spawned.append((task_id, user_id))

    monkeypatch.setattr(background_task_service, "spawn_background_task", fake_spawn)
    if stub_ffmpeg:
        # 仅用于校验逻辑，避免测试依赖真实 FFmpeg；真实流水线测试不 stub
        monkeypatch.setattr(ffmpeg_runner, "ffmpeg_binary", lambda: "/usr/bin/ffmpeg")
    return spawned


@pytest.mark.asyncio
async def test_create_job_persists_storyboard_and_background_task(session, sample_project, monkeypatch):
    spawned = _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
        options={"resolution": "854x480", "fps": 12},
    )

    assert job.status == "pending"
    assert job.scene_count >= 1
    assert job.duration_seconds > 0
    assert spawned == [(job.id, "user-1")]

    scenes = (
        await session.execute(
            VideoExportScene.__table__.select().where(VideoExportScene.job_id == job.id)
        )
    ).all()
    assert len(scenes) == job.scene_count

    task = await session.get(BackgroundTask, job.id)
    assert task is not None and task.task_type == "video_export" and task.status == "pending"

    payload = serialize_job(job, [])
    assert payload["has_video"] is False and payload["scenes"] == []


@pytest.mark.asyncio
async def test_create_job_requires_project_ownership(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    with pytest.raises(HTTPException) as exc:
        await video_export_service.create_job(
            db=session,
            user_id="user-2",
            project_id=sample_project.id,
            chapter_ids=[chapter.id],
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_job_rejects_chapter_from_other_project(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    other_project = Project(id=str(uuid.uuid4()), user_id="user-1", title="Khác")
    other_chapter = Chapter(
        id=str(uuid.uuid4()),
        project_id=other_project.id,
        chapter_number=1,
        title="Chương lạ",
        content="Nội dung.",
    )
    session.add_all([other_project, other_chapter])
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await video_export_service.create_job(
            db=session,
            user_id="user-1",
            project_id=sample_project.id,
            chapter_ids=[other_chapter.id],
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_job_rejects_empty_chapter_content(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    empty_chapter = Chapter(
        id=str(uuid.uuid4()),
        project_id=sample_project.id,
        chapter_number=2,
        title="Chương trống",
        content="   ",
    )
    session.add(empty_chapter)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await video_export_service.create_job(
            db=session,
            user_id="user-1",
            project_id=sample_project.id,
            chapter_ids=[empty_chapter.id],
        )
    assert exc.value.status_code == 400
    assert "chưa có nội dung" in exc.value.detail


@pytest.mark.asyncio
async def test_create_job_enforces_chapter_limit(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    from app.config import settings

    with pytest.raises(HTTPException) as exc:
        await video_export_service.create_job(
            db=session,
            user_id="user-1",
            project_id=sample_project.id,
            chapter_ids=[chapter.id] * (settings.video_max_chapters + 1),
        )
    assert exc.value.status_code == 400
    assert "tối đa" in exc.value.detail


@pytest.mark.asyncio
async def test_get_output_path_rejects_tampered_relative_path(session, sample_project):
    job = VideoExportJob(
        id=str(uuid.uuid4()),
        user_id="user-1",
        project_id=sample_project.id,
        status="completed",
        video_path="../../etc/passwd",
        subtitle_path="user-1/job/subtitles.srt",
    )
    session.add(job)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await video_export_service.get_output_path(
            db=session, user_id="user-1", job_id=job.id, kind="video"
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_output_path_hides_other_users_jobs(session, sample_project):
    job = VideoExportJob(
        id=str(uuid.uuid4()),
        user_id="user-1",
        project_id=sample_project.id,
        status="completed",
        video_path=f"user-1/{uuid.uuid4()}/output.mp4",
    )
    session.add(job)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await video_export_service.get_output_path(
            db=session, user_id="user-2", job_id=job.id, kind="video"
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_retry_scene_resets_only_target_and_requeues(session, sample_project, monkeypatch):
    spawned = _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
        options={"narration_chars_per_scene": 100},
    )
    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert len(scenes) >= 2
    scenes[0].status = "ready"
    scenes[1].status = "failed"
    scenes[1].error_message = "boom"
    job.status = "failed"
    # 任务记录被用户在后台任务面板中清理
    task = await session.get(BackgroundTask, job.id)
    await session.delete(task)
    await session.commit()

    await video_export_service.retry_scene(
        db=session, user_id="user-1", job_id=job.id, scene_id=scenes[1].id
    )

    refreshed = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert refreshed[0].status == "ready", "已完成的分镜不应被重置"
    assert refreshed[1].status == "pending" and refreshed[1].error_message is None
    await session.refresh(job)
    assert job.status == "pending" and job.progress == 0

    recreated = await session.get(BackgroundTask, job.id)
    assert recreated is not None and recreated.status == "pending"
    assert spawned[-1] == (job.id, "user-1")


@pytest.mark.asyncio
async def test_retry_scene_rejects_other_users(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    monkeypatch.setattr(ffmpeg_runner, "ffmpeg_binary", lambda: "/usr/bin/ffmpeg")
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )
    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)

    with pytest.raises(HTTPException) as exc:
        await video_export_service.retry_scene(
            db=session, user_id="user-2", job_id=job.id, scene_id=scenes[0].id
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_project_artifacts_commit_false_defers_db_and_files(
    session, sample_project, monkeypatch, isolated_video_storage
):
    """commit=False：DB 删除留在调用方事务中，文件必须等提交后才删（回滚不留缺口）"""
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    job.status = "completed"
    job.video_path = f"user-1/{job.id}/output.mp4"
    await session.commit()
    job_id, project_id = job.id, sample_project.id
    _write_job_files(isolated_video_storage, "user-1", job_id)
    job_dir = isolated_video_storage / "user-1" / job_id

    result = await video_export_service.delete_project_artifacts(
        db=session, user_id="user-1", project_id=project_id, commit=False
    )
    assert result["targets"] == [("user-1", job_id)]
    assert result["files_removed"] == 0
    assert job_dir.exists(), "尚未提交时不得删除产物文件"

    # 调用方提交失败 → 回滚后记录仍在，且文件未被删除（不会出现记录在、文件没了）
    await session.rollback()
    assert await session.get(VideoExportJob, job_id) is not None
    assert job_dir.exists()
    assert await session.get(BackgroundTask, job_id) is not None

    # 正常提交路径：先提交，再删文件
    result = await video_export_service.delete_project_artifacts(
        db=session, user_id="user-1", project_id=project_id, commit=False
    )
    await session.commit()
    removed = video_export_service.remove_artifact_dirs(result["targets"])
    assert removed == 1
    assert await session.get(VideoExportJob, job_id) is None
    assert not job_dir.exists()


@pytest.mark.asyncio
async def test_clear_project_tasks_aborts_when_video_cleanup_fails(
    session, sample_project, monkeypatch
):
    """清理任务记录时，视频导出清理失败必须中止（否则批量删除会留下孤儿导出任务）"""
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    job.status = "completed"
    await session.commit()
    project_id, job_id = sample_project.id, job.id

    async def boom(**kwargs):
        raise RuntimeError("db offline")

    monkeypatch.setattr(video_export_service, "delete_project_artifacts", boom)

    with TestClient(_build_api_app(session)) as client:
        response = client.delete(
            f"/api/tasks/project/{project_id}/clear", headers={"x-test-user": "user-1"}
        )
    assert response.status_code == 500
    # 任务映射与导出任务都还在，没有产生孤儿记录
    assert await session.get(VideoExportJob, job_id) is not None
    assert await session.get(BackgroundTask, job_id) is not None


@pytest.mark.asyncio
async def test_project_delete_aborts_when_video_cleanup_fails(session, sample_project, monkeypatch):
    """视频导出清理失败时不得删除项目，避免留下项目已消失的孤儿任务/文件"""
    pytest.importorskip("chromadb", reason="后端依赖缺失时跳过该集成用例")
    from fastapi.testclient import TestClient

    from app.api import projects as projects_api

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    job.status = "completed"
    await session.commit()
    project_id, job_id = sample_project.id, job.id

    async def boom(**kwargs):
        raise RuntimeError("db offline")

    monkeypatch.setattr(video_export_service, "delete_project_artifacts", boom)

    app = _build_api_app(session, include=(projects_api.router,))
    # 端点会把清理异常继续抛出（由全局异常处理器转成 500），这里关闭测试客户端的重新抛出
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete(f"/api/projects/{project_id}", headers={"x-test-user": "user-1"})
    assert response.status_code >= 400
    assert await session.get(Project, project_id) is not None, "项目不应被删除"
    assert await session.get(VideoExportJob, job_id) is not None


@pytest.mark.asyncio
async def test_project_delete_removes_video_rows_and_files(
    session, sample_project, monkeypatch, isolated_video_storage
):
    pytest.importorskip("chromadb", reason="后端依赖缺失时跳过该集成用例")
    from fastapi.testclient import TestClient

    from app.api import projects as projects_api

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    job.status = "completed"
    job.video_path = f"user-1/{job.id}/output.mp4"
    await session.commit()
    _write_job_files(isolated_video_storage, "user-1", job.id)
    job_dir = isolated_video_storage / "user-1" / job.id
    project_id, job_id = sample_project.id, job.id

    app = _build_api_app(session, include=(projects_api.router,))
    with TestClient(app) as client:
        response = client.delete(f"/api/projects/{project_id}", headers={"x-test-user": "user-1"})
    assert response.status_code == 200, response.text

    assert await session.get(Project, project_id) is None
    assert await session.get(VideoExportJob, job_id) is None
    assert await session.get(BackgroundTask, job_id) is None
    assert not job_dir.exists()


@pytest.mark.asyncio
async def test_retry_job_respects_active_job_quota(session, sample_project, monkeypatch):
    from app.config import settings

    _stub_spawn(monkeypatch)
    monkeypatch.setattr(settings, "video_max_active_jobs", 1)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    terminal = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    terminal.status = "failed"
    terminal.error_message = "boom"
    other_active = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await video_export_service.retry_job(db=session, user_id="user-1", job_id=terminal.id)
    assert exc.value.status_code == 409
    assert "giới hạn" in exc.value.detail
    await session.refresh(terminal)
    assert terminal.status == "failed", "配额不足时不应把任务改回 pending"
    await session.refresh(other_active)
    assert other_active.status == "pending"


@pytest.mark.asyncio
async def test_retry_job_excludes_itself_from_quota(session, sample_project, monkeypatch):
    """任务本身仍是 pending 时，重试不应因为它自己触发配额上限"""
    from app.config import settings

    spawned = _stub_spawn(monkeypatch)
    monkeypatch.setattr(settings, "video_max_active_jobs", 1)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    job = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    assert job.status == "pending"

    await video_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)
    await session.refresh(job)
    assert job.status == "pending"
    assert len(spawned) == 2, "重试应重新排队执行"


@pytest.mark.asyncio
async def test_retry_blocked_while_pipeline_still_running(session, sample_project, monkeypatch):
    """取消后流水线仍在收尾（FFmpeg 未退出）时不允许立刻重试，避免重复执行"""
    from app.services.video_export.service import RUNNING_JOB_IDS

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    job.status = "cancelled"
    await session.commit()

    RUNNING_JOB_IDS.add(job.id)
    try:
        with pytest.raises(HTTPException) as exc:
            await video_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)
        assert exc.value.status_code == 409
    finally:
        RUNNING_JOB_IDS.discard(job.id)

    await video_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)
    await session.refresh(job)
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_pipeline_passes_timeout_and_cancel_check_to_mux(
    session, engine, sample_project, monkeypatch, isolated_video_storage
):
    """mux 步骤必须同样受任务剩余时间与取消信号约束（不依赖真实 FFmpeg）"""
    from app.config import settings
    from app.services.video_export import service as service_module

    monkeypatch.setattr(service_module, "get_engine", lambda user_id: _awaitable(engine))
    _stub_spawn(monkeypatch)

    async def fake_render(*, out_path, duration, **kwargs):  # noqa: ARG001
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"clip")

    async def fake_concat(clip_paths, out_path, **kwargs):  # noqa: ARG001
        out_path.write_bytes(b"video")

    recorded: dict = {}

    async def fake_mux(video_path, srt_path, out_path, **kwargs):
        recorded.update(kwargs)
        out_path.write_bytes(b"subtitled")
        return True

    monkeypatch.setattr(service_module.ffmpeg_runner, "render_scene_clip", fake_render)
    monkeypatch.setattr(service_module.ffmpeg_runner, "concat_clips", fake_concat)
    monkeypatch.setattr(service_module.ffmpeg_runner, "mux_subtitles", fake_mux)

    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    await service_module._run_video_export_job(job.id, "user-1", job.id)

    await session.refresh(job)
    assert job.status == "completed", job.error_message
    assert callable(recorded.get("cancel_check"))
    timeout = recorded.get("timeout")
    assert timeout is not None and 0 < timeout <= settings.video_render_timeout_seconds


def test_capabilities_exposes_limits():
    capabilities = VideoExportService().capabilities()
    assert capabilities["max_scenes"] > 0
    assert "1280x720" in capabilities["allowed_resolutions"]
    assert isinstance(capabilities["ffmpeg_available"], bool)


# --------------------------------------------------------------------------- API (FastAPI TestClient)


def _build_api_app(session: AsyncSession, include: tuple = ()):
    """只挂载视频导出与后台任务路由（可追加其他 router），用于验证鉴权/权限/响应模型"""
    from fastapi import FastAPI, Request
    from app.api import tasks as tasks_api
    from app.api import video_export as video_export_api
    from app.database import get_db

    app = FastAPI()

    @app.middleware("http")
    async def fake_auth(request: Request, call_next):
        # 用请求头模拟 AuthMiddleware 注入的登录态
        user_id = request.headers.get("x-test-user")
        if user_id:
            request.state.user_id = user_id
        return await call_next(request)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(video_export_api.router, prefix="/api")
    app.include_router(tasks_api.router, prefix="/api")
    for router in include:
        app.include_router(router, prefix="/api")
    return app


def test_api_requires_authentication(session, sample_project):
    from fastapi.testclient import TestClient

    with TestClient(_build_api_app(session)) as client:
        response = client.get("/api/video-export/capabilities")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_api_create_list_and_fetch_storyboard(session, sample_project, monkeypatch):
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    # 事件循环外读取章节ID，避免与 TestClient 的线程共用 session
    chapter_id = chapter.id
    project_id = sample_project.id

    with TestClient(_build_api_app(session)) as client:
        headers = {"x-test-user": "user-1"}

        created = client.post(
            "/api/video-export/jobs",
            headers=headers,
            json={
                "project_id": project_id,
                "chapter_ids": [chapter_id],
                "options": {"resolution": "854x480", "fps": 12},
            },
        )
        assert created.status_code == 200, created.text
        payload = created.json()
        assert payload["status"] == "pending"
        assert payload["scenes"], "创建后应可以直接看到 storyboard"
        assert payload["scenes"][0]["narration"]

        listed = client.get("/api/video-export/jobs", headers=headers, params={"project_id": project_id})
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        detail = client.get(f"/api/video-export/jobs/{payload['id']}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["scene_count"] == len(payload["scenes"])

        # 其他用户访问同一任务应拿到 404
        forbidden = client.get(f"/api/video-export/jobs/{payload['id']}", headers={"x-test-user": "user-2"})
        assert forbidden.status_code == 404

    # 校验输入：越权项目、缺失字段
    with TestClient(_build_api_app(session)) as client:
        headers = {"x-test-user": "user-2"}
        denied = client.post(
            "/api/video-export/jobs",
            headers=headers,
            json={"project_id": project_id, "chapter_ids": [chapter_id]},
        )
        assert denied.status_code == 404

        invalid = client.post(
            "/api/video-export/jobs",
            headers={"x-test-user": "user-1"},
            json={"project_id": project_id, "chapter_ids": []},
        )
        assert invalid.status_code == 422


@pytest.mark.asyncio
async def test_api_download_missing_output_returns_404(session, sample_project):
    from fastapi.testclient import TestClient

    job = VideoExportJob(
        id=str(uuid.uuid4()),
        user_id="user-1",
        project_id=sample_project.id,
        status="completed",
        video_path=f"user-1/{uuid.uuid4()}/output.mp4",
        subtitle_path=f"user-1/{uuid.uuid4()}/subtitles.srt",
    )
    session.add(job)
    await session.commit()

    with TestClient(_build_api_app(session)) as client:
        response = client.get(
            f"/api/video-export/jobs/{job.id}/download/video", headers={"x-test-user": "user-1"}
        )
        assert response.status_code == 404



@pytest.mark.asyncio
async def test_api_download_video_is_inline_for_player(
    session, sample_project, isolated_video_storage
):
    """Thẻ <video> cần Content-Disposition: inline; attachment sẽ không phát trong Chrome."""
    from fastapi.testclient import TestClient

    job_id = str(uuid.uuid4())
    job = VideoExportJob(
        id=job_id,
        user_id="user-1",
        project_id=sample_project.id,
        status="completed",
        video_path=f"user-1/{job_id}/output.mp4",
    )
    session.add(job)
    await session.commit()
    job_dir = isolated_video_storage / "user-1" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "output.mp4").write_bytes(b"fake-mp4-bytes")

    with TestClient(_build_api_app(session)) as client:
        response = client.get(
            f"/api/video-export/jobs/{job_id}/download/video", headers={"x-test-user": "user-1"}
        )
    assert response.status_code == 200
    disposition = response.headers.get("content-disposition", "")
    assert "inline" in disposition
    assert "attachment" not in disposition
    assert response.headers.get("content-type", "").startswith("video/mp4")
    assert response.content == b"fake-mp4-bytes"

# --------------------------------------------------------------------------- FFmpeg 端到端


@pytest.mark.asyncio
@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg chưa được cài đặt")
async def test_full_pipeline_produces_mp4_and_srt(
    session, engine, sample_project, monkeypatch, isolated_video_storage
):
    """跑完整流水线：storyboard → 片段 → ghép → SRT → 状态落库"""
    from app.services.video_export import service as service_module

    storage_root = isolated_video_storage
    storage_root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(service_module, "get_engine", lambda user_id: _awaitable(engine))

    spawned = _stub_spawn(monkeypatch, stub_ffmpeg=False)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
        options={
            "resolution": "854x480",
            "fps": 12,
            "narration_chars_per_scene": 120,
            "use_project_cover": False,
        },
    )
    assert spawned, "创建后应立即排入后台队列"

    # 直接执行后台函数（跳过队列）
    await service_module._run_video_export_job(job.id, "user-1", job.id)

    await session.refresh(job)
    assert job.status == "completed", job.error_message
    assert job.progress == 100
    assert job.video_path and job.subtitle_path
    assert job.video_size_bytes and job.video_size_bytes > 0

    scenes = (
        await session.execute(
            VideoExportScene.__table__.select().where(VideoExportScene.job_id == job.id)
        )
    ).all()
    assert scenes and all(scene.status == "ready" for scene in scenes)

    storage_root_path = storage_root / job.video_path
    subtitle_root_path = storage_root / job.subtitle_path
    assert storage_root_path.is_file() and storage_root_path.stat().st_size > 0
    srt_text = subtitle_root_path.read_text(encoding="utf-8")
    assert srt_text.startswith("1\n00:00:00,000 --> ")
    assert "Cảnh" not in srt_text  # 字幕内容应为旁白正文

    task = await session.get(BackgroundTask, job.id)
    assert task is not None and task.status == "completed" and task.progress == 100

    # 下载路径解析必须落在受管目录内
    resolved_job, resolved_path = await video_export_service.get_output_path(
        db=session, user_id="user-1", job_id=job.id, kind="video"
    )
    assert resolved_job.id == job.id
    assert resolved_path == storage_root_path.resolve()


async def _awaitable(value):
    return value


@pytest.mark.asyncio
@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg chưa được cài đặt")
async def test_ffmpeg_renders_mp4_and_srt_end_to_end(tmp_path):
    from app.services.video_export.subtitles import build_srt_from_scenes

    workdir = tmp_path / "job"
    clips_dir = workdir / "clips"
    clips_dir.mkdir(parents=True)

    # 一张真实的图片，用于覆盖 zoompan（pan/zoom）分支
    cover = workdir / "cover.png"
    await ffmpeg_runner.run_ffmpeg(
        ["-f", "lavfi", "-i", "color=c=0x2b3a67:s=640x360", "-frames:v", "1", "-y", cover.as_posix()]
    )

    class _Scene:
        def __init__(self, narration: str, duration: float) -> None:
            self.narration = narration
            self.duration_seconds = duration

    scenes = [_Scene("Phân cảnh đầu tiên.", 3.0), _Scene("Phân cảnh thứ hai.", 3.0)]
    clips = []
    for index, scene in enumerate(scenes):
        clip = clips_dir / f"scene_{index:03d}.mp4"
        await ffmpeg_runner.render_scene_clip(
            out_path=clip,
            duration=scene.duration_seconds,
            width=854,
            height=480,
            fps=12,
            image_path=cover if index == 0 else None,  # 第二段走占位背景分支
        )
        assert clip.is_file() and clip.stat().st_size > 0
        clips.append(clip)

    output = workdir / "output.mp4"
    await ffmpeg_runner.concat_clips(clips, output, workdir=workdir, fps=12)
    assert output.is_file() and output.stat().st_size > 0

    subtitle = workdir / "subtitles.srt"
    subtitle.write_text(build_srt_from_scenes(scenes), encoding="utf-8")
    assert "00:00:00,000 --> 00:00:03,000" in subtitle.read_text(encoding="utf-8")

    subtitled = workdir / "output_subtitled.mp4"
    assert await ffmpeg_runner.mux_subtitles(output, subtitle, subtitled) is True
    assert subtitled.stat().st_size > 0

    streams = await ffmpeg_runner.probe_stream_types(subtitled)
    assert "video" in streams
    assert "subtitle" in streams, "SRT 应作为字幕轨写入 MP4"

    duration = await ffmpeg_runner.probe_duration(subtitled)
    assert duration is not None and 5.0 <= duration <= 7.5


# --------------------------------------------------------------------------- 删除 / 清理 / 配额 / 取消回归


def _long_encode_args(out_path) -> list[str]:
    """一条足够长的 FFmpeg 命令，用于验证取消/超时会真正终止进程"""
    return [
        "-f",
        "lavfi",
        "-r",
        "30",
        "-i",
        "color=c=black:s=1280x720",
        "-t",
        "600",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-y",
        out_path.as_posix(),
    ]


def _write_job_files(root, user_id: str, job_id: str) -> None:
    job_dir = root / user_id / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / "output.mp4").write_bytes(b"fake-video")


@pytest.mark.asyncio
async def test_delete_job_blocks_pending_running_and_active_worker(session, sample_project, monkeypatch):
    from app.services.video_export.service import RUNNING_JOB_IDS

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
    )

    # pending：仍在队列中，必须先取消
    with pytest.raises(HTTPException) as exc:
        await video_export_service.delete_job(db=session, user_id="user-1", job_id=job.id)
    assert exc.value.status_code == 409

    job.status = "running"
    await session.commit()
    with pytest.raises(HTTPException) as exc:
        await video_export_service.delete_job(db=session, user_id="user-1", job_id=job.id)
    assert exc.value.status_code == 409

    # 已标记取消，但流水线仍在执行（FFmpeg 未退出）时同样拒绝
    job.status = "cancelled"
    await session.commit()
    RUNNING_JOB_IDS.add(job.id)
    try:
        with pytest.raises(HTTPException) as exc:
            await video_export_service.delete_job(db=session, user_id="user-1", job_id=job.id)
        assert exc.value.status_code == 409
    finally:
        RUNNING_JOB_IDS.discard(job.id)

    # 真正停止后才允许删除，并清理分镜/后台任务记录
    await video_export_service.delete_job(db=session, user_id="user-1", job_id=job.id)
    assert await session.get(VideoExportJob, job.id) is None
    assert await session.get(BackgroundTask, job.id) is None
    remaining_scenes = (
        await session.execute(
            VideoExportScene.__table__.select().where(VideoExportScene.job_id == job.id)
        )
    ).all()
    assert remaining_scenes == []


@pytest.mark.asyncio
async def test_delete_project_artifacts_removes_rows_tasks_and_files(
    session, sample_project, monkeypatch, isolated_video_storage
):
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    finished = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    active = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    finished.status = "completed"
    finished.video_path = f"user-1/{finished.id}/output.mp4"
    active.status = "running"
    await session.commit()
    for job in (finished, active):
        _write_job_files(isolated_video_storage, "user-1", job.id)

    result = await video_export_service.delete_project_artifacts(
        db=session, user_id="user-1", project_id=sample_project.id
    )

    assert result["jobs"] == 2
    assert await session.get(VideoExportJob, finished.id) is None
    assert await session.get(VideoExportJob, active.id) is None
    # 孤儿分镜与后台任务映射必须一并删除（SQLite 无外键级联）
    for job_id in (finished.id, active.id):
        scenes = (
            await session.execute(
                VideoExportScene.__table__.select().where(VideoExportScene.job_id == job_id)
            )
        ).all()
        assert scenes == []
        assert await session.get(BackgroundTask, job_id) is None
        assert not (isolated_video_storage / "user-1" / job_id).exists(), "产物目录必须被删除"


@pytest.mark.asyncio
async def test_delete_project_artifacts_defers_cleanup_while_worker_runs(
    session, sample_project, monkeypatch, isolated_video_storage
):
    """正在执行的任务：先取消并删记录，目录等 FFmpeg 退出后再删"""
    from app.services.video_export.service import RUNNING_JOB_IDS

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    job = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    job.status = "running"
    await session.commit()
    _write_job_files(isolated_video_storage, "user-1", job.id)
    job_dir = isolated_video_storage / "user-1" / job.id

    RUNNING_JOB_IDS.add(job.id)
    try:
        await video_export_service.delete_project_artifacts(
            db=session, user_id="user-1", project_id=sample_project.id
        )
        assert job_dir.exists(), "流水线未退出时不应立刻删除目录"
    finally:
        RUNNING_JOB_IDS.discard(job.id)

    await asyncio.sleep(1.2)  # 延迟清理每 0.5s 轮询一次
    assert not job_dir.exists(), "流水线停止后目录应被清理"


@pytest.mark.asyncio
async def test_delete_project_artifacts_only_finished_keeps_active_job(
    session, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    finished = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    pending = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    finished.status = "completed"
    await session.commit()

    result = await video_export_service.delete_project_artifacts(
        db=session, user_id="user-1", project_id=sample_project.id, only_finished=True
    )

    assert result["jobs"] == 1
    assert await session.get(VideoExportJob, finished.id) is None
    assert await session.get(VideoExportJob, pending.id) is not None, "未完成任务不应被清理"


@pytest.mark.asyncio
async def test_clear_project_tasks_removes_video_export_job_and_files(
    session, sample_project, monkeypatch, isolated_video_storage
):
    """清理项目任务记录时不能只删任务映射而留下孤儿导出任务"""
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()
    finished = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    pending = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    finished.status = "completed"
    finished.video_path = f"user-1/{finished.id}/output.mp4"
    await session.commit()
    _write_job_files(isolated_video_storage, "user-1", finished.id)
    project_id, finished_id, pending_id = sample_project.id, finished.id, pending.id

    with TestClient(_build_api_app(session)) as client:
        response = client.delete(
            f"/api/tasks/project/{project_id}/clear", headers={"x-test-user": "user-1"}
        )
    assert response.status_code == 200, response.text

    assert await session.get(VideoExportJob, finished_id) is None
    assert await session.get(BackgroundTask, finished_id) is None
    assert not (isolated_video_storage / "user-1" / finished_id).exists()
    # 未完成的任务保留（含其任务映射），避免误删正在跑的记录
    assert await session.get(VideoExportJob, pending_id) is not None
    assert await session.get(BackgroundTask, pending_id) is not None


@pytest.mark.asyncio
async def test_download_path_prefix_must_match_current_user(
    session, sample_project, isolated_video_storage
):
    """即使文件真实存在，路径前缀为其他用户也必须拒绝（纵深防御）"""
    other_user = "user-2"
    other_job_id = str(uuid.uuid4())
    _write_job_files(isolated_video_storage, other_user, other_job_id)

    job = VideoExportJob(
        id=str(uuid.uuid4()),
        user_id="user-1",
        project_id=sample_project.id,
        status="completed",
        video_path=f"{other_user}/{other_job_id}/output.mp4",
        subtitle_path=f"user-1/{other_job_id}/subtitles.srt",
    )
    session.add(job)
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await video_export_service.get_output_path(
            db=session, user_id="user-1", job_id=job.id, kind="video"
        )
    assert exc.value.status_code == 404


def test_capabilities_hides_ffmpeg_path_and_exposes_quota():
    capabilities = VideoExportService().capabilities()
    assert "ffmpeg_path" not in capabilities, "不应向前端暴露 FFmpeg 绝对路径"
    assert capabilities["max_active_jobs"] >= 1
    assert capabilities["job_timeout_seconds"] > 0


@pytest.mark.asyncio
async def test_create_job_enforces_active_job_quota(session, sample_project, monkeypatch):
    from app.config import settings

    _stub_spawn(monkeypatch)
    monkeypatch.setattr(settings, "video_max_active_jobs", 1)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    with pytest.raises(HTTPException) as exc:
        await video_export_service.create_job(
            db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
        )
    assert exc.value.status_code == 409
    assert "giới hạn" in exc.value.detail

    # 其他用户不受影响
    other_project = Project(id=str(uuid.uuid4()), user_id="user-2", title="Dự án khác")
    other_chapter = Chapter(
        id=str(uuid.uuid4()),
        project_id=other_project.id,
        chapter_number=1,
        title="Chương",
        content="Nội dung đủ dài để tạo phân cảnh. " * 20,
    )
    session.add_all([other_project, other_chapter])
    await session.commit()
    await video_export_service.create_job(
        db=session, user_id="user-2", project_id=other_project.id, chapter_ids=[other_chapter.id]
    )


@pytest.mark.asyncio
@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg chưa được cài đặt")
async def test_run_ffmpeg_cancel_check_kills_process(tmp_path):
    out_path = tmp_path / "long.mp4"
    calls = {"count": 0}

    async def cancel_check() -> bool:
        calls["count"] += 1
        return calls["count"] >= 2

    started = time.monotonic()
    with pytest.raises(ffmpeg_runner.FFmpegCancelledError):
        await ffmpeg_runner.run_ffmpeg(
            _long_encode_args(out_path), cancel_check=cancel_check, poll_seconds=0.2, timeout=300
        )
    elapsed = time.monotonic() - started
    assert elapsed < 20, f"取消后应立即返回，实际耗时 {elapsed:.1f}s"
    assert calls["count"] >= 2
    # 进程已被回收：Windows 下文件仍被占用时删除会失败
    out_path.unlink(missing_ok=True)
    assert not out_path.exists()


@pytest.mark.asyncio
@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg chưa được cài đặt")
async def test_run_ffmpeg_timeout_kills_process(tmp_path):
    out_path = tmp_path / "long.mp4"

    started = time.monotonic()
    with pytest.raises(ffmpeg_runner.FFmpegExecutionError) as exc:
        await ffmpeg_runner.run_ffmpeg(_long_encode_args(out_path), timeout=2, poll_seconds=0.2)
    assert "vượt quá thời gian" in str(exc.value)
    assert time.monotonic() - started < 20
    out_path.unlink(missing_ok=True)
    assert not out_path.exists()


@pytest.mark.asyncio
async def test_job_wall_clock_timeout_marks_failed(
    session, engine, sample_project, monkeypatch, isolated_video_storage
):
    """整个任务的墙钟上限：超过后任务失败且不会继续渲染"""
    from app.services.video_export import service as service_module

    real_monotonic = service_module._monotonic
    calls = {"count": 0}

    def fast_forward() -> float:
        calls["count"] += 1
        return real_monotonic() + (10_000 if calls["count"] > 1 else 0)

    monkeypatch.setattr(service_module, "_monotonic", fast_forward)
    monkeypatch.setattr(service_module, "get_engine", lambda user_id: _awaitable(engine))
    _stub_spawn(monkeypatch)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    job = await video_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, chapter_ids=[chapter.id]
    )
    await service_module._run_video_export_job(job.id, "user-1", job.id)

    await session.refresh(job)
    assert job.status == "failed"
    assert "thời gian" in (job.error_message or "")
    scenes = await video_export_service._get_scenes(db=session, job_id=job.id)
    assert all(scene.status == "pending" for scene in scenes), "超时后不应继续渲染分镜"


@pytest.mark.asyncio
@pytest.mark.skipif(not FFMPEG_AVAILABLE, reason="FFmpeg chưa được cài đặt")
async def test_cancel_stops_running_ffmpeg_pipeline(
    session, engine, sample_project, monkeypatch, isolated_video_storage
):
    """取消后必须尽快终止正在运行的 FFmpeg，并把任务落库为 cancelled"""
    from app.services.video_export import service as service_module

    monkeypatch.setattr(service_module, "get_engine", lambda user_id: _awaitable(engine))
    _stub_spawn(monkeypatch, stub_ffmpeg=False)

    async def long_render(*, out_path, duration, **kwargs):  # noqa: ARG001
        await ffmpeg_runner.run_ffmpeg(
            _long_encode_args(out_path),
            cancel_check=kwargs.get("cancel_check"),
            poll_seconds=0.2,
            timeout=300,
        )
        out_path.write_bytes(b"unreachable")

    monkeypatch.setattr(service_module.ffmpeg_runner, "render_scene_clip", long_render)
    chapter = (await session.execute(Chapter.__table__.select())).first()

    job = await video_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        chapter_ids=[chapter.id],
        options={"resolution": "854x480", "fps": 12},
    )

    # 预置一个“正在写入”的半成品成片，取消后必须被清理
    job_dir = isolated_video_storage / "user-1" / job.id
    job_dir.mkdir(parents=True, exist_ok=True)
    partial_output = job_dir / "output.mp4"
    partial_output.write_bytes(b"partial")

    pipeline = asyncio.create_task(service_module._run_video_export_job(job.id, "user-1", job.id))
    try:
        await asyncio.sleep(2.0)
        assert job.id in service_module.RUNNING_JOB_IDS, "流水线应正在执行"

        await video_export_service.cancel_job(db=session, user_id="user-1", job_id=job.id)
        started = time.monotonic()
        await asyncio.wait_for(pipeline, timeout=30)
        elapsed = time.monotonic() - started
    finally:
        if not pipeline.done():
            pipeline.cancel()

    assert elapsed < 20, f"取消后流水线应尽快停止，实际 {elapsed:.1f}s"
    assert job.id not in service_module.RUNNING_JOB_IDS
    await session.refresh(job)
    assert job.status == "cancelled"
    # 半成品成片必须被清理，避免出现可下载的残缺 MP4
    assert not partial_output.exists()
