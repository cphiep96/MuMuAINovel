"""PDF 全本导出的本地测试（不调用 Meta 真实 API）

覆盖：
- Unicode 字体解析（缺字体 → 报错清晰、不生成乱码 PDF）
- 排版：多章节顺序、用户内容 escaping、目录、页数/元数据、插图等比适配、坏图跳过
- 参数校验（策略/纸张/图片 provider 未配置 → 4xx/503）
- 任务流水线：章节排序、插图缓存（重试不重复计费）、skip/fail 策略、取消 → cancelled
- 多 worker 执行权：stale running 被接管后必须真正跑完、续租、接管后不覆盖新 worker 状态
- API/ownership/路径穿越/下载/删除/项目清理
- 迁移图谱（含 PDF 表）与启动兜底建表

运行：cd backend && python -m pytest tests/test_pdf_export.py -q
"""
from __future__ import annotations

import asyncio
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.background_task import BackgroundTask
from app.models.chapter import Chapter
from app.models.pdf_export import PdfExportImage, PdfExportJob
from app.models.project import Project
from app.services.pdf_export import builder as pdf_builder
from app.services.pdf_export import fonts as pdf_fonts
from app.services.pdf_export import service as pdf_service_module
from app.services.pdf_export.builder import (
    PdfBookMeta,
    PdfChapterContent,
    build_story_pdf,
    escape_markup,
    normalize_text,
    split_paragraphs,
)
from app.services.pdf_export.fonts import (
    PdfFontUnavailableError,
    register_pdf_fonts,
    resolve_pdf_fonts,
)
from app.services.pdf_export.images import (
    IMAGE_STATUS_FAILED,
    IMAGE_STATUS_PENDING,
    IMAGE_STATUS_READY,
    build_image_prompt,
    image_relative_path,
    validate_stored_image,
)
from app.services.pdf_export.service import (
    normalize_options,
    pdf_export_service,
    serialize_job,
)
from app.services.video_export.image_providers import ImageCancelledError, ImageProviderError

pytest.importorskip("reportlab", reason="未安装 reportlab 时跳过 PDF 用例")

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 128
WEBP_BYTES = b"RIFF" + (64).to_bytes(4, "little") + b"WEBP" + b"\x00" * 48


def _make_png(path: Path, *, size: tuple[int, int] = (400, 600)) -> Path:
    """用 Pillow（reportlab 依赖）生成一张真实 PNG，供排版测试使用"""
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 40, 40)).save(path)
    return path


# --------------------------------------------------------------------------- fixtures


@pytest.fixture(autouse=True)
def pdf_settings(monkeypatch):
    monkeypatch.setattr(settings, "pdf_export_enabled", True)
    monkeypatch.setattr(settings, "pdf_font_path", None)
    monkeypatch.setattr(settings, "pdf_max_chapters", 300)
    monkeypatch.setattr(settings, "pdf_max_text_chars", 2_000_000)
    monkeypatch.setattr(settings, "pdf_max_images", 60)
    monkeypatch.setattr(settings, "pdf_max_output_mb", 64)
    monkeypatch.setattr(settings, "pdf_max_active_jobs", 2)
    monkeypatch.setattr(settings, "pdf_job_timeout_seconds", 600)
    monkeypatch.setattr(settings, "pdf_claim_ttl_buffer_seconds", 300)
    monkeypatch.setattr(settings, "pdf_claim_renew_seconds", 60.0)
    monkeypatch.setattr(settings, "pdf_cancel_poll_seconds", 0.05)
    monkeypatch.setattr(settings, "video_image_enabled", True)
    monkeypatch.setattr(settings, "video_image_provider", None)
    monkeypatch.setattr(settings, "video_image_model", None)
    monkeypatch.setattr(settings, "video_image_aspect_ratio", None)
    monkeypatch.setattr(settings, "video_image_reasoning_strength", None)
    monkeypatch.setattr(settings, "video_image_timeout_seconds", 30)
    monkeypatch.setattr(settings, "video_image_max_mb", 16)
    monkeypatch.setattr(settings, "meta_muse_api_key", None)
    monkeypatch.setattr(settings, "model_api_key", None)
    pdf_fonts.reset_font_cache()
    return settings


@pytest_asyncio.fixture
async def engine(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'pdf.db').as_posix()}")
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
def isolated_pdf_storage(tmp_path, monkeypatch):
    """把 PDF 产物写到临时目录（通过配置项隔离，避免污染真实 storage/）"""
    root = tmp_path / "pdf-storage"
    monkeypatch.setattr(settings, "pdf_export_storage_dir", str(root))
    return root


def _job_dir(root: Path, user_id: str, job_id: str) -> Path:
    path = root / user_id / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest_asyncio.fixture
async def sample_project(session: AsyncSession):
    project = Project(
        id=str(uuid.uuid4()),
        user_id="user-1",
        title="Truyện thử nghiệm PDF",
        description="Mô tả ngắn cho bìa PDF",
        genre="Huyền huyễn",
        cover_image_url=None,
        cover_status="none",
    )
    session.add(project)
    # 故意打乱插入顺序，验证排序只由 chapter_number/sub_index 决定
    for number, sub, content in (
        (2, 1, "Nội dung chương hai."),
        (1, 2, "Nội dung chương một (phần hai)."),
        (1, 1, "Nội dung chương một."),
        (3, 1, "Nội dung chương ba."),
    ):
        session.add(
            Chapter(
                id=str(uuid.uuid4()),
                project_id=project.id,
                chapter_number=number,
                sub_index=sub,
                title=f"Chương {number}.{sub}",
                content=content,
                summary=f"Tóm tắt {number}.{sub}",
            )
        )
    await session.commit()
    return project


class _FakeImageProvider:
    """假 Meta Muse Image：可成功/失败/取消，记录调用次数"""

    name = "meta_muse_image"
    label = "Meta Muse Image 1.0"
    kind = "image"
    models = ("muse-image-1.0",)
    default_model = "muse-image-1.0"
    aspect_ratios = ("16:9", "9:16", "1:1")
    size_options = ("1792x1024", "1024x1792", "1024x1024")
    default_size = "1024x1792"
    output_format = "webp"
    supports_reasoning_strength = True
    reasoning_strengths = ("low", "high")

    def __init__(self, *, mode: str = "ok") -> None:
        self.mode = mode
        self.calls: list[str] = []

    def configuration(self):
        from app.services.video_export.image_providers.base import ImageProviderConfigState

        return ImageProviderConfigState(configured=True)

    def size_for_aspect(self, aspect_ratio: str) -> str:
        return {"16:9": "1792x1024", "9:16": "1024x1792", "1:1": "1024x1024"}.get(
            aspect_ratio, self.default_size
        )

    def normalize_model(self, value):
        return value or self.default_model

    def normalize_aspect_ratio(self, value):
        return value or self.aspect_ratios[0]

    def normalize_size(self, value, aspect_ratio):
        return value or self.size_for_aspect(aspect_ratio)

    def normalize_reasoning_strength(self, value):
        return value or None

    async def generate_image(self, request, out_path, *, cancel_check=None, timeout=None):
        from app.services.video_export.image_providers.base import SceneImageResult

        self.calls.append(request.prompt[:60])
        if self.mode == "cancel":
            raise ImageCancelledError("Đã hủy theo yêu cầu của người dùng")
        if self.mode == "fail":
            raise ImageProviderError("fake image provider down")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        _write_png(out_path)
        return SceneImageResult(
            path=out_path,
            provider=self.name,
            model=self.default_model,
            size=request.size,
            mime_type="image/png",
            bytes_written=out_path.stat().st_size,
        )


def _write_png(path: Path) -> None:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (320, 480), (40, 120, 200)).save(path)


def _stub_spawn(monkeypatch):
    spawned: list[str] = []

    async def fake_spawn(task_id, user_id, task_func, *args, **kwargs):
        spawned.append(task_id)

    monkeypatch.setattr(
        "app.services.pdf_export.service.background_task_service.spawn_background_task", fake_spawn
    )
    return spawned


def _patch_image_provider(monkeypatch, provider):
    """把 PDF 服务里的图片 provider 相关入口全部指向假 provider"""
    monkeypatch.setattr(pdf_service_module, "build_image_provider", lambda name, **kwargs: provider)
    monkeypatch.setattr(pdf_service_module, "_resolve_image_provider", lambda name: provider)
    monkeypatch.setattr(pdf_service_module, "is_known_image_provider", lambda name: True)
    monkeypatch.setattr(pdf_service_module, "default_image_provider_name", lambda: provider.name)


async def _run_pipeline(engine, session, job, monkeypatch, provider=None):
    async def _awaitable(value):
        return value

    monkeypatch.setattr(pdf_service_module, "get_engine", lambda user_id: _awaitable(engine))
    if provider is not None:
        _patch_image_provider(monkeypatch, provider)
    await pdf_service_module._run_pdf_export_job(job.id, job.user_id, job.id)
    await session.refresh(job)
    return job


# --------------------------------------------------------------------------- 文本处理/字体


def test_normalize_and_split_text_keeps_vietnamese():
    raw = "Câu chuyện bắt đầu.\r\n\r\n\t Anh ấy nói: “Xin chào” — rồi đi.\x00"
    normalized = normalize_text(raw)
    assert normalized.startswith("Câu chuyện bắt đầu.")
    assert "Anh ấy nói: “Xin chào” — rồi đi." in normalized
    assert "\x00" not in normalized
    paragraphs = split_paragraphs("Đoạn một.\n\nĐoạn hai dòng 1\nĐoạn hai dòng 2")
    assert paragraphs == ["Đoạn một.", "Đoạn hai dòng 1\nĐoạn hai dòng 2"]


def test_split_paragraphs_breaks_very_long_block():
    long_line = "x" * 5000
    paragraphs = split_paragraphs(long_line, max_paragraph_chars=4000)
    assert len(paragraphs) == 2
    assert all(len(item) <= 4000 for item in paragraphs)


def test_escape_markup_neutralizes_user_content():
    assert escape_markup("<b>bold</b> & 'quote'") == "&lt;b&gt;bold&lt;/b&gt; &amp; &apos;quote&apos;"


def test_font_resolver_prefers_configured_path(tmp_path):
    font_file = tmp_path / "Custom.ttf"
    font_file.write_bytes(b"\x00\x01\x00\x00" + b"\x00" * 32)
    fonts = resolve_pdf_fonts(configured_path=str(font_file))
    assert fonts.regular == font_file
    assert fonts.bold == font_file  # 找不到粗体时回落到常规字重


def test_font_resolver_reports_missing_config_clearly(tmp_path):
    with pytest.raises(PdfFontUnavailableError) as exc:
        resolve_pdf_fonts(configured_path=str(tmp_path / "nope.ttf"))
    assert "PDF_FONT_PATH" in str(exc.value)


def test_font_resolver_rejects_non_font_extension(tmp_path):
    bad = tmp_path / "font.txt"
    bad.write_text("not a font")
    with pytest.raises(PdfFontUnavailableError):
        resolve_pdf_fonts(configured_path=str(bad))


def test_system_font_is_available_for_tests():
    """测试环境必须有可用字体，否则后面的排版断言没有意义"""
    fonts = resolve_pdf_fonts()
    assert fonts.regular.is_file()
    register_pdf_fonts()


# --------------------------------------------------------------------------- 排版（builder）


def _chapters(count: int = 3) -> list[PdfChapterContent]:
    return [
        PdfChapterContent(
            number=index,
            title=f"Chapter {index} Alpha",
            content=f"Body line for chapter {index}.",
        )
        for index in range(1, count + 1)
    ]


def _pdf_text(pdf_bytes: bytes) -> str:
    """从已生成的 PDF 中提取可见文本（仅测试用）

    ReportLab 会压缩内容流，因此先按常见滤波器解压，再收集 `(...) Tj` 的字符串。
    注意：嵌入的自定义 TTF 会用 glyph 编码，此时文本不可读——本函数用于内置字体场景。
    """
    import base64
    import re
    import zlib

    def decode(raw: bytes) -> bytes:
        attempts = (
            lambda r: zlib.decompress(base64.a85decode(r, adobe=True)),
            lambda r: zlib.decompress(base64.a85decode(r.rstrip(b"~>"), adobe=False)),
            zlib.decompress,
            lambda r: r,
        )
        for attempt in attempts:
            try:
                return attempt(raw)
            except Exception:  # noqa: BLE001 - 逐个尝试滤波器
                continue
        return b""

    def unescape(value: str) -> str:
        out = []
        index = 0
        while index < len(value):
            char = value[index]
            if char == "\\" and index + 1 < len(value):
                nxt = value[index + 1]
                if nxt in "()\\":
                    out.append(nxt)
                    index += 2
                    continue
                if nxt.isdigit():
                    digits = value[index + 1 : index + 4]
                    out.append(chr(int(digits, 8)))
                    index += 1 + len(digits)
                    continue
                out.append(nxt)
                index += 2
                continue
            out.append(char)
            index += 1
        return "".join(out)

    chunks: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", pdf_bytes, re.S):
        stream = decode(match.group(1).rstrip(b"\r\n")).decode("latin-1")
        for literal in re.findall(r"\(((?:[^()\\]|\\.)*)\)\s*Tj", stream):
            chunks.append(unescape(literal))
    return " ".join(chunks)


def test_build_pdf_multi_chapter_order_and_metadata(tmp_path):
    """用内置 Helvetica 验证章节顺序、TOC 与元数据（文本可提取，便于断言）"""
    out_path = tmp_path / "story.pdf"
    result = build_story_pdf(
        meta=PdfBookMeta(title="My Test Story", author="Author Name", include_toc=True),
        chapters=_chapters(3),
        out_path=out_path,
        font_family="Helvetica",
    )
    data = out_path.read_bytes()
    assert data.startswith(b"%PDF-")
    assert result.page_count >= 3
    assert result.chapter_count == 3
    assert result.file_size_bytes == out_path.stat().st_size > 0
    assert b"/Title (My Test Story)" in data
    assert b"/Author (Author Name)" in data

    text = _pdf_text(data)
    assert "My Test Story" in text, "标题必须出现在 PDF 中"

    # 章节顺序与标题必须严格递增出现（封面 → 目录 → 章节）
    positions = [text.find(f"Chapter {index} Alpha") for index in (1, 2, 3)]
    assert all(position >= 0 for position in positions), f"章节标题必须出现在 PDF 文本中: {text[:200]}"
    assert positions == sorted(positions), "章节必须按 thứ tự 排列"


def test_build_pdf_footer_shows_total_page_count(tmp_path):
    """页脚为两遍式「Trang N / TOTAL」：总页数在整本排版完成（含 TOC 多遍构建）后才回填"""
    out_path = tmp_path / "footer.pdf"
    result = build_story_pdf(
        meta=PdfBookMeta(title="Footer Test", include_toc=True),
        chapters=_chapters(3),
        out_path=out_path,
        font_family="Helvetica",
    )
    text = _pdf_text(out_path.read_bytes())
    total = result.page_count
    assert total >= 4, "封面 + 目录 + 3 章"
    for page in range(1, total + 1):
        assert f"Trang {page} / {total}" in text, f"第 {page} 页缺少正确页码: {text}"
    assert f"Trang 1 / 1" not in text, "总页数不能沿用单页占位值"


def test_build_pdf_escapes_user_markup(tmp_path):
    out_path = tmp_path / "escape.pdf"
    build_story_pdf(
        meta=PdfBookMeta(title="Escape Test", include_toc=False),
        chapters=[
            PdfChapterContent(
                number=1,
                title="Chapter with <b>markup</b>",
                content='Line one <script>alert(1)</script> & "quotes".',
            )
        ],
        out_path=out_path,
        font_family="Helvetica",
    )
    text = _pdf_text(out_path.read_bytes())
    # 用户内容被当作纯文本渲染（若未 escape，ReportLab 会把 <b> 当标记吃掉）
    # ReportLab 会把文本拆成多个 glyph run，这里去掉空白后再比较
    compact = "".join(text.split())
    assert "<b>markup</b>" in compact
    assert "<script>alert(1)</script>" in compact
    assert '"quotes"' in compact


def test_build_pdf_vietnamese_text_with_unicode_font(tmp_path):
    out_path = tmp_path / "vietnamese.pdf"
    build_story_pdf(
        meta=PdfBookMeta(title="Truyện tiếng Việt", author="Tác giả", include_toc=True),
        chapters=[
            PdfChapterContent(
                number=1,
                title="Khởi đầu",
                content="Trời chưa sáng, đoàn người rời làng. “Đi thôi!” — ai đó nói.",
            )
        ],
        out_path=out_path,
        fonts=register_pdf_fonts(),
    )
    data = out_path.read_bytes()
    assert data.startswith(b"%PDF-")
    assert b"/FontFile2" in data or b"FontFile" in data, "font Unicode phải được nhúng (tránh chữ vỡ)"


def test_build_pdf_includes_fitted_image_and_skips_broken_one(tmp_path):
    image_path = _make_png(tmp_path / "images" / "chapter_0001_01.png")
    broken_path = tmp_path / "images" / "broken.png"
    broken_path.write_bytes(b"not-an-image")

    out_path = tmp_path / "with-images.pdf"
    result = build_story_pdf(
        meta=PdfBookMeta(title="Images", include_toc=False),
        chapters=[
            PdfChapterContent(number=1, title="Chapter 1", content="body", image_path=image_path),
            PdfChapterContent(number=2, title="Chapter 2", content="body", image_path=broken_path),
            PdfChapterContent(number=3, title="Chapter 3", content="body", image_path=tmp_path / "missing.png"),
        ],
        out_path=out_path,
        fonts=register_pdf_fonts(),
    )
    assert result.image_count == 1, "chỉ ảnh hợp lệ được chèn"
    assert len(result.warnings) == 2
    assert all("bỏ qua" in warning for warning in result.warnings)
    assert out_path.stat().st_size > 0


def test_build_pdf_empty_project_still_produces_file(tmp_path):
    out_path = tmp_path / "empty.pdf"
    result = build_story_pdf(
        meta=PdfBookMeta(title="Rỗng"),
        chapters=[],
        out_path=out_path,
        fonts=register_pdf_fonts(),
    )
    assert result.page_count >= 1
    assert out_path.stat().st_size > 0


def test_build_pdf_fails_clearly_when_reportlab_missing(tmp_path, monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("reportlab"):
            raise ImportError("no reportlab")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(pdf_builder.PdfBuildError) as exc:
        build_story_pdf(
            meta=PdfBookMeta(title="x"), chapters=[], out_path=tmp_path / "a.pdf", fonts=None
        )
    assert "ReportLab" in str(exc.value)


def test_pdf_chapter_display_title_handles_sub_index():
    assert PdfChapterContent(number=3, sub_index=1, title="A", content="").display_title == "Chương 3: A"
    assert PdfChapterContent(number=3, sub_index=2, title="B", content="").display_title == "Chương 3.2: B"


# --------------------------------------------------------------------------- 参数校验


def test_normalize_options_defaults_and_policy():
    plan = normalize_options(None)
    assert plan["include_cover"] is True
    assert plan["include_images"] is False
    assert plan["include_toc"] is True
    assert plan["image_failure_policy"] == "skip"
    assert plan["page_size"] == "A4"
    assert plan["image_provider"] is None


def test_normalize_options_rejects_bad_policy_and_page_size():
    with pytest.raises(HTTPException) as policy_exc:
        normalize_options({"image_failure_policy": "explode"})
    assert policy_exc.value.status_code == 400
    with pytest.raises(HTTPException) as size_exc:
        normalize_options({"page_size": "A0"})
    assert size_exc.value.status_code == 400


def test_normalize_options_requires_image_provider_when_images_enabled():
    with pytest.raises(HTTPException) as exc:
        normalize_options({"include_images": True})
    assert exc.value.status_code == 503
    assert "META_MUSE_API_KEY" in exc.value.detail


def test_normalize_options_rejects_unknown_image_provider():
    with pytest.raises(HTTPException) as exc:
        normalize_options({"include_images": True, "image_provider": "ghost"})
    assert exc.value.status_code == 400


def test_normalize_options_respects_server_switch(monkeypatch):
    monkeypatch.setattr(settings, "video_image_enabled", False)
    with pytest.raises(HTTPException) as exc:
        normalize_options({"include_images": True})
    assert exc.value.status_code == 503
    assert "VIDEO_IMAGE_ENABLED" in exc.value.detail


def test_normalize_options_with_image_plan(monkeypatch):
    provider = _FakeImageProvider()
    _patch_image_provider(monkeypatch, provider)
    plan = normalize_options(
        {"include_images": True, "image_aspect_ratio": "16:9", "image_failure_policy": "fail"}
    )
    assert plan["image_provider"] == "meta_muse_image"
    assert plan["image_model"] == "muse-image-1.0"
    assert plan["image_size"] == "1792x1024"
    assert plan["image_failure_policy"] == "fail"


# --------------------------------------------------------------------------- 插图工具


def test_build_image_prompt_is_bounded_and_uses_summary():
    prompt = build_image_prompt(title="Khởi đầu", summary="Tóm tắt", content="y" * 5000)
    assert prompt.startswith("Minh họa bìa chương truyện: Khởi đầu")
    assert "Tóm tắt" in prompt
    assert len(prompt) <= 900


def test_image_relative_path_is_deterministic():
    assert image_relative_path("images", chapter_number=12, sub_index=3, extension=".webp") == (
        "images/chapter_0012_03.webp"
    )


def test_validate_stored_image_checks_magic_bytes(tmp_path):
    good = tmp_path / "good.png"
    _write_png(good)
    ok, reason = validate_stored_image(good, max_bytes=1024 * 1024)
    assert ok and reason is None

    bad = tmp_path / "bad.png"
    bad.write_bytes(b"<html>not an image</html>")
    ok, reason = validate_stored_image(bad, max_bytes=1024 * 1024)
    assert not ok and "PNG/WebP/JPEG" in reason

    ok, reason = validate_stored_image(tmp_path / "missing.png", max_bytes=1024)
    assert not ok

    ok, reason = validate_stored_image(good, max_bytes=10)
    assert not ok and "dung lượng" in reason


# --------------------------------------------------------------------------- 任务流水线


@pytest.mark.asyncio
async def test_create_job_orders_chapters_and_creates_image_rows(
    session, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    _patch_image_provider(monkeypatch, _FakeImageProvider())

    job = await pdf_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        options={"include_images": True, "image_aspect_ratio": "9:16"},
    )
    assert job.chapter_count == 4
    assert job.status == "pending"
    assert job.image_count == 0

    images = await pdf_export_service._get_images(db=session, job_id=job.id)
    assert [(row.chapter_number, row.sub_index) for row in images] == [(1, 1), (1, 2), (2, 1), (3, 1)]
    assert all(row.status == IMAGE_STATUS_PENDING for row in images)
    assert all(row.size == "1024x1792" for row in images)

    chapters = await pdf_export_service._load_chapters(
        db=session, project_id=sample_project.id, user_id="user-1"
    )
    assert [(chapter.chapter_number, chapter.sub_index) for chapter in chapters] == [
        (1, 1),
        (1, 2),
        (2, 1),
        (3, 1),
    ]


@pytest.mark.asyncio
async def test_create_job_rejects_foreign_project(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    with pytest.raises(HTTPException) as exc:
        await pdf_export_service.create_job(
            db=session, user_id="someone-else", project_id=sample_project.id
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_create_job_enforces_quota(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    session.add(
        PdfExportJob(
            id=str(uuid.uuid4()),
            user_id="user-1",
            project_id=sample_project.id,
            status="running",
            progress=10,
        )
    )
    await session.commit()
    monkeypatch.setattr(settings, "pdf_max_active_jobs", 1)
    with pytest.raises(HTTPException) as exc:
        await pdf_export_service.create_job(
            db=session, user_id="user-1", project_id=sample_project.id
        )
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_create_job_rejects_too_many_chapters(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    monkeypatch.setattr(settings, "pdf_max_chapters", 2)
    with pytest.raises(HTTPException) as exc:
        await pdf_export_service.create_job(
            db=session, user_id="user-1", project_id=sample_project.id
        )
    assert exc.value.status_code == 400
    assert "giới hạn" in exc.value.detail


@pytest.mark.asyncio
async def test_pipeline_produces_pdf_text_only(
    session, engine, sample_project, monkeypatch, isolated_pdf_storage
):
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id, options={}
    )
    job = await _run_pipeline(engine, session, job, monkeypatch)

    assert job.status == "completed", job.error_message
    assert job.page_count and job.page_count >= 4
    assert job.file_size_bytes > 0
    assert job.image_count == 0
    assert job.progress == 100
    assert job.output_path == f"user-1/{job.id}/story.pdf"

    path = isolated_pdf_storage / "user-1" / job.id / "story.pdf"
    assert path.is_file() and path.read_bytes().startswith(b"%PDF-")

    payload = serialize_job(job)
    assert payload["has_pdf"] is True
    assert "output_path" not in payload
    assert not any("pdf-storage" in str(value) for value in payload.values() if isinstance(value, str))


@pytest.mark.asyncio
async def test_pipeline_generates_one_image_per_chapter(
    session, engine, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    provider = _FakeImageProvider()
    _patch_image_provider(monkeypatch, provider)

    job = await pdf_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        options={"include_images": True, "image_aspect_ratio": "9:16"},
    )
    job = await _run_pipeline(engine, session, job, monkeypatch, provider)

    assert job.status == "completed", job.error_message
    assert len(provider.calls) == 4, "mỗi chương đúng một ảnh"
    assert job.image_count == 4
    rows = await pdf_export_service._get_images(db=session, job_id=job.id)
    assert all(row.status == IMAGE_STATUS_READY for row in rows)
    assert all(row.path and row.path.startswith("images/chapter_") for row in rows)
    for row in rows:
        stored = pdf_service_module.resolve_job_file(job.user_id, job.id, row.path)
        assert stored.is_file()


@pytest.mark.asyncio
async def test_image_failure_skip_policy_still_exports_full_pdf(
    session, engine, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    provider = _FakeImageProvider(mode="fail")
    _patch_image_provider(monkeypatch, provider)

    job = await pdf_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        options={"include_images": True, "image_failure_policy": "skip"},
    )
    job = await _run_pipeline(engine, session, job, monkeypatch, provider)

    assert job.status == "completed", job.error_message
    assert job.image_count == 0
    assert job.warnings and any("bỏ qua ảnh minh họa" in warning for warning in job.warnings)
    rows = await pdf_export_service._get_images(db=session, job_id=job.id)
    assert all(row.status == IMAGE_STATUS_FAILED for row in rows)
    assert all("fake image provider down" in (row.error or "") for row in rows)


@pytest.mark.asyncio
async def test_image_failure_fail_policy_marks_job_failed(
    session, engine, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    provider = _FakeImageProvider(mode="fail")
    _patch_image_provider(monkeypatch, provider)

    job = await pdf_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        options={"include_images": True, "image_failure_policy": "fail"},
    )
    job = await _run_pipeline(engine, session, job, monkeypatch, provider)

    assert job.status == "failed"
    assert "ảnh minh họa" in (job.error_message or "")
    assert not job.output_path


@pytest.mark.asyncio
async def test_cancel_during_image_generation_marks_cancelled(
    session, engine, sample_project, monkeypatch
):
    """取消 → cancelled（不是 failed），且不写入 PDF"""
    _stub_spawn(monkeypatch)
    provider = _FakeImageProvider(mode="cancel")
    _patch_image_provider(monkeypatch, provider)

    job = await pdf_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        options={"include_images": True},
    )
    job = await _run_pipeline(engine, session, job, monkeypatch, provider)

    assert job.status == "cancelled", job.error_message
    assert not job.output_path
    rows = await pdf_export_service._get_images(db=session, job_id=job.id)
    assert rows[0].status == "cancelled"


@pytest.mark.asyncio
async def test_retry_keeps_ready_images_and_regenerates_failed(
    session, sample_project, monkeypatch
):
    """重试只重做失败/取消的插图，ready 图片不会被重新生成（不重复计费）"""
    spawned = _stub_spawn(monkeypatch)
    provider = _FakeImageProvider()
    _patch_image_provider(monkeypatch, provider)

    job = await pdf_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        options={"include_images": True},
    )
    rows = await pdf_export_service._get_images(db=session, job_id=job.id)
    rows[0].status = IMAGE_STATUS_READY
    rows[0].path = "images/chapter_0001_01.webp"
    rows[1].status = IMAGE_STATUS_FAILED
    rows[1].error = "boom"
    job.status = "failed"
    await session.commit()

    await pdf_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)

    refreshed = await pdf_export_service._get_images(db=session, job_id=job.id)
    assert refreshed[0].status == IMAGE_STATUS_READY and refreshed[0].path.endswith(".webp")
    assert refreshed[1].status == IMAGE_STATUS_PENDING and refreshed[1].error is None
    assert all(row.status == IMAGE_STATUS_PENDING for row in refreshed[2:])
    await session.refresh(job)
    assert job.status == "pending"
    assert "3 ảnh minh họa sẽ được tạo lại" in (job.status_message or "")
    assert spawned, "重试必须重新排队后台任务"


@pytest.mark.asyncio
async def test_run_job_skips_when_other_worker_holds_lease(
    session, engine, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.worker_token = "other-worker"
    job.claimed_at = datetime.now()
    await session.commit()

    async def _awaitable(value):
        return value

    monkeypatch.setattr(pdf_service_module, "get_engine", lambda user_id: _awaitable(engine))
    calls: list[str] = []

    async def fake_render(**kwargs):
        calls.append("rendered")

    monkeypatch.setattr(pdf_export_service, "_render_pdf", fake_render)
    await pdf_export_service.run_job(job_id=job.id, user_id="user-1")

    assert calls == []
    await session.refresh(job)
    assert job.status == "pending"


@pytest.mark.asyncio
async def test_cancel_job_marks_cancelled_and_blocks_when_finished(
    session, sample_project, monkeypatch
):
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "running"
    await session.commit()

    cancelled = await pdf_export_service.cancel_job(db=session, user_id="user-1", job_id=job.id)
    assert cancelled.status == "cancelled"
    task = await session.get(BackgroundTask, job.id)
    assert task is not None and task.cancel_requested is True

    with pytest.raises(HTTPException) as exc:
        await pdf_export_service.cancel_job(db=session, user_id="user-1", job_id=job.id)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_delete_job_removes_records_and_files(
    session, sample_project, monkeypatch, isolated_pdf_storage
):
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "completed"
    job.output_path = f"user-1/{job.id}/story.pdf"
    await session.commit()

    job_dir = pdf_service_module.job_directory("user-1", job.id)
    (job_dir / "story.pdf").write_bytes(b"%PDF-1.4 test")
    (job_dir / "images").mkdir(parents=True, exist_ok=True)
    (job_dir / "images" / "chapter_0001_01.webp").write_bytes(WEBP_BYTES)

    await pdf_export_service.delete_job(db=session, user_id="user-1", job_id=job.id)

    assert (await session.execute(PdfExportJob.__table__.select())).first() is None
    assert (await session.execute(PdfExportImage.__table__.select())).first() is None
    assert not job_dir.exists(), "PDF 与插图文件都要被清理"


@pytest.mark.asyncio
async def test_delete_job_blocked_while_running(session, sample_project, monkeypatch):
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    with pytest.raises(HTTPException) as exc:
        await pdf_export_service.delete_job(db=session, user_id="user-1", job_id=job.id)
    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_download_path_rejects_traversal(
    session, sample_project, monkeypatch, isolated_pdf_storage
):
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    for hostile in ("../evil.pdf", "/etc/passwd", "user-2/other/secret.pdf"):
        job.status = "completed"
        job.output_path = hostile
        await session.commit()
        with pytest.raises(HTTPException) as exc:
            await pdf_export_service.get_output_path(
                db=session, user_id="user-1", job_id=job.id
            )
        assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_download_returns_managed_file(session, sample_project, monkeypatch, isolated_pdf_storage):
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "completed"
    job.output_path = f"user-1/{job.id}/story.pdf"
    await session.commit()
    job_dir = pdf_service_module.job_directory("user-1", job.id)
    (job_dir / "story.pdf").write_bytes(b"%PDF-1.4 real")

    _, path = await pdf_export_service.get_output_path(db=session, user_id="user-1", job_id=job.id)
    assert path.read_bytes() == b"%PDF-1.4 real"

    with pytest.raises(HTTPException) as exc:
        await pdf_export_service.get_output_path(db=session, user_id="user-2", job_id=job.id)
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_delete_project_artifacts_cleans_pdf_jobs(
    session, sample_project, monkeypatch, isolated_pdf_storage
):
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "completed"
    await session.commit()
    job_dir = pdf_service_module.job_directory("user-1", job.id)
    (job_dir / "story.pdf").write_bytes(b"%PDF-1.4 x")

    result = await pdf_export_service.delete_project_artifacts(
        db=session, user_id="user-1", project_id=sample_project.id, commit=True
    )
    assert result["jobs"] == 1
    assert not job_dir.exists()
    assert (await session.execute(PdfExportJob.__table__.select())).first() is None


@pytest.mark.asyncio
async def test_meta_provider_mocked_image_flows_into_pdf(
    session, engine, sample_project, monkeypatch
):
    """用 mock HTTP 的 Meta provider 跑完整流程：图片进入 PDF，且不泄露 key/URL"""
    import base64
    import io
    import json

    import httpx

    from app.services.video_export.image_providers import MetaMuseImageProvider

    _stub_spawn(monkeypatch)
    monkeypatch.setattr(settings, "meta_muse_api_key", "pdf-test-key-not-real")
    monkeypatch.setattr(settings, "meta_muse_base_url", "https://api.meta.ai/v1")

    calls: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        buffer = io.BytesIO()
        from PIL import Image

        Image.new("RGB", (360, 540), (12, 34, 56)).save(buffer, format="PNG")
        payload = base64.b64encode(buffer.getvalue()).decode("ascii")
        return httpx.Response(200, json={"data": [{"b64_json": payload}]})

    provider = MetaMuseImageProvider(
        api_key="pdf-test-key-not-real",
        transport=httpx.MockTransport(handler),
    )
    monkeypatch.setattr(pdf_service_module, "build_image_provider", lambda name, **kwargs: provider)
    monkeypatch.setattr(pdf_service_module, "_resolve_image_provider", lambda name: provider)

    job = await pdf_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        options={"include_images": True, "image_aspect_ratio": "9:16", "image_reasoning_strength": "high"},
    )
    job = await _run_pipeline(engine, session, job, monkeypatch, provider)

    assert job.status == "completed", job.error_message
    assert len(calls) == job.chapter_count
    assert all(call["model"] == "muse-image-1.0" for call in calls)
    assert all(call["response_format"] == "b64_json" for call in calls)
    assert all(call["reasoning_strength"] == "high" for call in calls)
    assert job.image_count == job.chapter_count

    payload = serialize_job(job, await pdf_export_service._get_images(db=session, job_id=job.id))
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "pdf-test-key-not-real" not in serialized
    assert "api.meta.ai" not in serialized
    assert "b64_json" not in serialized
    assert "images/chapter" not in serialized, "内部相对路径不入响应"


@pytest.mark.asyncio
async def test_startup_fails_interrupted_jobs_and_keeps_images(
    session, sample_project, monkeypatch
):
    """重启收敛：pending/running → failed + 释放 lease，但插图记录（含 ready 路径）保持不变"""
    from app.services.pdf_export.startup import fail_interrupted_jobs

    _stub_spawn(monkeypatch)
    interrupted = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    interrupted.status = "running"
    interrupted.worker_token = "dead-worker"
    interrupted.claimed_at = datetime.now()
    done = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    done.status = "completed"
    await session.commit()

    affected = await fail_interrupted_jobs(session)
    assert affected == 1

    await session.refresh(interrupted)
    assert interrupted.status == "failed"
    assert "khởi động lại" in (interrupted.error_message or "")
    assert interrupted.worker_token is None and interrupted.claimed_at is None
    await session.refresh(done)
    assert done.status == "completed", "tác vụ đã kết thúc không được đụng tới"


@pytest.mark.asyncio
async def test_startup_keeps_ready_images_for_retry(session, sample_project, monkeypatch):
    """收敛后重试仍复用 ready 插图（不重新调用付费 API）"""
    from app.services.pdf_export.startup import fail_interrupted_jobs

    _stub_spawn(monkeypatch)
    provider = _FakeImageProvider()
    _patch_image_provider(monkeypatch, provider)
    job = await pdf_export_service.create_job(
        db=session,
        user_id="user-1",
        project_id=sample_project.id,
        options={"include_images": True},
    )
    rows = await pdf_export_service._get_images(db=session, job_id=job.id)
    rows[0].status = IMAGE_STATUS_READY
    rows[0].path = "images/chapter_0001_01.webp"
    job.status = "running"
    job.worker_token = "dead-worker"
    await session.commit()

    await fail_interrupted_jobs(session)
    await pdf_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)

    refreshed = await pdf_export_service._get_images(db=session, job_id=job.id)
    assert refreshed[0].status == IMAGE_STATUS_READY
    assert refreshed[0].path == "images/chapter_0001_01.webp"
    assert all(row.status == IMAGE_STATUS_PENDING for row in refreshed[1:])


# --------------------------------------------------------------------------- 原子产物 / 重试安全


@pytest.mark.asyncio
async def test_retry_failure_keeps_previous_pdf_downloadable(
    session, engine, sample_project, monkeypatch, isolated_pdf_storage
):
    """成功 → 重试失败：旧 PDF 必须保留且仍可下载，响应区分「产物旧 / 运行新」"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job = await _run_pipeline(engine, session, job, monkeypatch)
    assert job.status == "completed"
    assert job.output_generation == 1 and job.run_attempt == 1

    pdf_path = isolated_pdf_storage / "user-1" / job.id / "story.pdf"
    original_bytes = pdf_path.read_bytes()
    assert original_bytes.startswith(b"%PDF-")

    # 第二次运行：构建失败
    def boom(**_kwargs):
        raise pdf_service_module.PdfBuildError("dựng PDF thất bại (giả lập)")

    monkeypatch.setattr(pdf_service_module, "build_story_pdf", boom)
    await pdf_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)
    job = await _run_pipeline(engine, session, job, monkeypatch)

    assert job.status == "failed"
    assert job.run_attempt == 2, "运行代次必须递增，用于区分新旧"
    assert job.output_generation == 1, "失败不得提升产物代次"
    assert pdf_path.is_file(), "旧 PDF 不能被删除"
    assert pdf_path.read_bytes() == original_bytes

    payload = serialize_job(job)
    assert payload["has_pdf"] is True
    assert payload["artifact_stale"] is True, "必须标记出下载的是上一次成功的产物"
    assert payload["run_attempt"] == 2 and payload["artifact_generation"] == 1
    # 临时文件已清理
    assert not list((isolated_pdf_storage / "user-1" / job.id).glob("*building*"))


@pytest.mark.asyncio
async def test_retry_cancel_keeps_previous_pdf_downloadable(
    session, engine, sample_project, monkeypatch, isolated_pdf_storage
):
    """成功 → 重试被取消：旧 PDF 仍可下载，状态为 cancelled（不是 failed）"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job = await _run_pipeline(engine, session, job, monkeypatch)
    pdf_path = isolated_pdf_storage / "user-1" / job.id / "story.pdf"
    original_bytes = pdf_path.read_bytes()

    # 第二次运行时取消：builder 立刻感知取消标记
    def cancelled_build(**kwargs):
        cancel_check = kwargs.get("cancel_check")
        for _ in range(100):
            if cancel_check is not None and cancel_check():
                raise pdf_service_module.PdfBuildCancelled("hủy")
        raise pdf_service_module.PdfBuildError("không nhận được tín hiệu hủy")

    monkeypatch.setattr(pdf_service_module, "build_story_pdf", cancelled_build)
    await pdf_export_service.retry_job(db=session, user_id="user-1", job_id=job.id)

    state = {"first": True}

    async def fake_cancel_check():
        # 第一次检查（渲染开始前）返回 False，之后返回 True，模拟用户中途点 Hủy
        if state["first"]:
            state["first"] = False
            return False
        return True

    monkeypatch.setattr(pdf_export_service, "_make_cancel_checker", lambda db, job: fake_cancel_check)
    job = await _run_pipeline(engine, session, job, monkeypatch)

    assert job.status == "cancelled", job.error_message
    assert pdf_path.is_file() and pdf_path.read_bytes() == original_bytes
    payload = serialize_job(job)
    assert payload["has_pdf"] is True and payload["artifact_stale"] is True


@pytest.mark.asyncio
async def test_build_thread_cancelled_race_maps_to_cancelled(
    session, engine, sample_project, monkeypatch, isolated_pdf_storage
):
    """构建线程先于 worker 取消竞态结束（抛 PdfBuildCancelled）→ cancelled，绝不记为 failed"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )

    async def build_cancelled(**_kwargs):
        raise pdf_service_module.PdfBuildCancelled("Đã hủy trong lúc dựng PDF")

    monkeypatch.setattr(pdf_export_service, "_build_pdf_in_thread", build_cancelled)
    job = await _run_pipeline(engine, session, job, monkeypatch)

    assert job.status == "cancelled", job.error_message
    assert job.error_message is None, "取消不是失败，不得写入 error_message"
    assert not job.output_path
    job_dir = isolated_pdf_storage / "user-1" / job.id
    assert not list(job_dir.glob("*building*")), "构建中的临时文件必须被清理"


@pytest.mark.asyncio
async def test_has_pdf_reflects_real_file(session, sample_project, monkeypatch, isolated_pdf_storage):
    """记录里有路径但文件被删 → has_pdf 必须为 False"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "completed"
    job.output_path = f"user-1/{job.id}/story.pdf"
    job.output_generation = 1
    job.run_attempt = 1
    await session.commit()
    await session.refresh(job)
    assert serialize_job(job)["has_pdf"] is False

    job_dir = pdf_service_module.job_directory("user-1", job.id)
    (job_dir / "story.pdf").write_bytes(b"%PDF-1.4 x")
    assert serialize_job(job)["has_pdf"] is True

    (job_dir / "story.pdf").unlink()
    assert serialize_job(job)["has_pdf"] is False


@pytest.mark.asyncio
async def test_build_thread_is_cancellable(session, sample_project, monkeypatch):
    """构建线程在取消/超时时必须能被 worker 收回（不会被 to_thread 长期占住）"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.run_attempt = 1

    def slow_build(**kwargs):
        cancel_check = kwargs.get("cancel_check")
        for _ in range(200):
            if cancel_check is not None and cancel_check():
                raise pdf_service_module.PdfBuildCancelled("hủy")
            time.sleep(0.02)
        raise pdf_service_module.PdfBuildError("không nhận được tín hiệu hủy")

    monkeypatch.setattr(pdf_service_module, "build_story_pdf", slow_build)

    async def fake_cancel_check():
        return True

    with pytest.raises(pdf_service_module.PdfJobCancelledError):
        await pdf_export_service._build_pdf_in_thread(
            meta=pdf_service_module.PdfBookMeta(title="x"),
            chapters=[],
            out_path=sample_project.id and (pdf_service_module.job_directory_path("user-1", job.id) / "t.building"),
            fonts=None,
            cancel_check=fake_cancel_check,
            deadline=time.monotonic() + 30,
        )


@pytest.mark.asyncio
async def test_build_thread_timeout(session, sample_project, monkeypatch):
    """超过墙钟 → PdfJobTimeoutError，且线程收到取消标记后退出"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )

    def slow_build(**kwargs):
        cancel_check = kwargs.get("cancel_check")
        for _ in range(200):
            if cancel_check is not None and cancel_check():
                raise pdf_service_module.PdfBuildCancelled("hủy")
            time.sleep(0.02)
        raise pdf_service_module.PdfBuildError("không nhận được tín hiệu hủy")

    monkeypatch.setattr(pdf_service_module, "build_story_pdf", slow_build)

    async def no_cancel():
        return False

    with pytest.raises(pdf_service_module.PdfJobTimeoutError):
        await pdf_export_service._build_pdf_in_thread(
            meta=pdf_service_module.PdfBookMeta(title="x"),
            chapters=[],
            out_path=pdf_service_module.job_directory_path("user-1", job.id) / "t.building",
            fonts=None,
            cancel_check=no_cancel,
            deadline=time.monotonic() + 0.3,
        )


# --------------------------------------------------------------------------- 取消/事务竞态


@pytest.mark.asyncio
async def test_cancel_queued_job_is_not_overwritten_by_worker(
    session, engine, sample_project, monkeypatch
):
    """用户取消队列中的任务后，worker 不得把它改回 running"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    await pdf_export_service.cancel_job(db=session, user_id="user-1", job_id=job.id)
    await session.refresh(job)
    assert job.status == "cancelled"
    assert job.run_attempt in (0, None), "取消发生在 worker 启动前"

    async def _awaitable(value):
        return value

    monkeypatch.setattr(pdf_service_module, "get_engine", lambda user_id: _awaitable(engine))
    renders: list[str] = []

    async def fake_render(**kwargs):
        renders.append("rendered")

    monkeypatch.setattr(pdf_export_service, "_render_pdf", fake_render)
    await pdf_export_service.run_job(job_id=job.id, user_id="user-1")

    assert renders == [], "已取消的任务不得进入渲染"
    await session.refresh(job)
    assert job.status == "cancelled"
    assert job.run_attempt == 0, "被取消的任务不应消耗运行代次"


@pytest.mark.asyncio
async def test_start_run_is_conditional(session, sample_project, monkeypatch):
    """_start_run 只在 pending/failed 且持有执行权时成功；running 仅在持有本次领取的令牌时可重启"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.worker_token = "worker-a"
    await session.commit()

    assert await pdf_export_service._start_run(db=session, job=job) is True
    assert job.run_attempt == 1 and job.status == "running"

    # running 但内存里的令牌不是数据库里的持有者（说明已被接管）→ 拒绝
    session.expunge(job)
    job.worker_token = "worker-stale"
    assert await pdf_export_service._start_run(db=session, job=job) is False
    assert job.run_attempt == 1

    # 已取消的任务不能被 worker 改回 running
    cancelled = (
        await session.execute(select(PdfExportJob).where(PdfExportJob.id == job.id))
    ).scalar_one()
    cancelled.status = "cancelled"
    await session.commit()
    assert await pdf_export_service._start_run(db=session, job=cancelled) is False
    assert cancelled.run_attempt == 1


@pytest.mark.asyncio
async def test_start_run_resumes_stale_running_job(
    session, sample_project, monkeypatch
):
    """stale running 被重新领取后，_start_run 必须放行（否则领取成功却什么都不做）"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "running"
    job.worker_token = "dead-worker"
    job.claimed_at = datetime.now() - timedelta(
        seconds=int(settings.pdf_job_timeout_seconds)
        + int(settings.pdf_claim_ttl_buffer_seconds)
        + 60
    )
    job.run_attempt = 1
    await session.commit()

    assert await pdf_export_service._claim_job(db=session, job=job, token="worker-b") is True
    assert job.worker_token == "worker-b"
    assert await pdf_export_service._start_run(db=session, job=job) is True
    assert job.status == "running" and job.run_attempt == 2


@pytest.mark.asyncio
async def test_reclaimed_stale_running_job_really_exports_pdf(
    session, engine, sample_project, monkeypatch, isolated_pdf_storage
):
    """worker 死掉后遗留的 running 任务被接管，必须真正跑完并产出 PDF"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "running"
    job.worker_token = "dead-worker"
    job.claimed_at = datetime.now() - timedelta(
        seconds=int(settings.pdf_job_timeout_seconds)
        + int(settings.pdf_claim_ttl_buffer_seconds)
        + 60
    )
    job.run_attempt = 1
    await session.commit()

    job = await _run_pipeline(engine, session, job, monkeypatch)

    assert job.status == "completed", job.error_message
    assert job.run_attempt == 2, "接管必须推进运行代次"
    assert job.output_path == f"user-1/{job.id}/story.pdf"
    assert (isolated_pdf_storage / "user-1" / job.id / "story.pdf").is_file()


@pytest.mark.asyncio
async def test_renew_lease_keeps_live_job_and_blocks_takeover(
    session, sample_project, monkeypatch
):
    """续租：claimed_at 被刷新后，其它 worker 不能接管正在运行的任务"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    assert await pdf_export_service._claim_job(db=session, job=job, token="worker-a") is True
    job.claimed_at = datetime.now() - timedelta(seconds=3600)
    await session.commit()

    assert await pdf_export_service._renew_lease(db=session, job=job) is True
    claimed_at = (
        await session.execute(
            select(PdfExportJob.claimed_at).where(PdfExportJob.id == job.id)
        )
    ).scalar_one()
    assert (datetime.now() - claimed_at) < timedelta(minutes=1), "续租必须刷新 claimed_at"

    assert await pdf_export_service._claim_job(db=session, job=job, token="worker-b") is False
    await session.refresh(job)
    assert job.worker_token == "worker-a"


@pytest.mark.asyncio
async def test_lease_renewal_detects_takeover_and_is_token_guarded(
    session, engine, sample_project, monkeypatch
):
    """执行权被别的进程接管后：续租失败、取消检查器返回 True、本进程不再拥有 lease"""
    _stub_spawn(monkeypatch)
    monkeypatch.setattr(settings, "pdf_claim_renew_seconds", 1.0)
    monkeypatch.setattr(settings, "pdf_cancel_poll_seconds", 0.01)

    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    assert await pdf_export_service._claim_job(db=session, job=job, token="worker-a") is True
    job.claimed_at = datetime.now() - timedelta(seconds=900)
    await session.commit()

    check = pdf_export_service._make_cancel_checker(session, job)
    assert await check() is False
    claimed_at = (
        await session.execute(
            select(PdfExportJob.claimed_at).where(PdfExportJob.id == job.id)
        )
    ).scalar_one()
    assert (datetime.now() - claimed_at) < timedelta(minutes=1), "检查器必须顺带续租"

    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as other_worker:
        await other_worker.execute(
            update(PdfExportJob)
            .where(PdfExportJob.id == job.id)
            .values(worker_token="worker-b", claimed_at=datetime.now())
        )
        await other_worker.commit()

    assert job.worker_token == "worker-a", "旧进程内存里仍是旧令牌"
    assert await pdf_export_service._renew_lease(db=session, job=job) is False
    assert await pdf_export_service._still_owns_lease(db=session, job=job) is False
    await asyncio.sleep(0.15)  # 取消检查器有最小节流间隔（≥0.1s）
    assert await check() is True, "旧 worker 必须停止流水线"


@pytest.mark.asyncio
async def test_lost_lease_does_not_clobber_new_worker_state(
    session, engine, sample_project, monkeypatch
):
    """被接管后旧 worker 不得写入终态（否则会把新 worker 的 running 改成 cancelled）"""
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def render_then_lose_lease(**_kwargs):
        async with factory() as other_worker:
            await other_worker.execute(
                update(PdfExportJob)
                .where(PdfExportJob.id == job.id)
                .values(
                    status="running",
                    progress=42,
                    worker_token="worker-b",
                    claimed_at=datetime.now(),
                )
            )
            await other_worker.commit()
        raise pdf_service_module.PdfJobCancelledError()

    monkeypatch.setattr(pdf_export_service, "_render_pdf", render_then_lose_lease)
    await _run_pipeline(engine, session, job, monkeypatch)

    await session.refresh(job)
    assert job.worker_token == "worker-b"
    assert job.status == "running", "旧 worker 不得覆盖新 worker 的状态"
    assert job.progress == 42


@pytest.mark.asyncio
async def test_delete_project_artifacts_does_not_commit_inner_transaction(
    session, sample_project, monkeypatch
):
    """`commit=False` 时所有改动留在调用方事务里：回滚后任务仍然存在且未被标记取消"""
    _stub_spawn(monkeypatch)
    pending = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    finished = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    finished.status = "completed"
    await session.commit()
    pending_id = pending.id

    result = await pdf_export_service.delete_project_artifacts(
        db=session, user_id="user-1", project_id=sample_project.id, commit=False
    )
    assert result["jobs"] == 2
    # 尚未提交：调用方回滚后一切照旧（没有半删状态）
    await session.rollback()

    rows = (await session.execute(PdfExportJob.__table__.select())).all()
    assert len(rows) == 2, "回滚后任务必须完好无损"
    refreshed = await pdf_export_service._get_job(
        db=session, user_id="user-1", job_id=pending_id
    )
    assert refreshed.status == "pending", "回滚后不能残留 cancelled 状态"
    task = await session.get(BackgroundTask, pending_id)
    assert task is not None and not task.cancel_requested


@pytest.mark.asyncio
async def test_delete_project_artifacts_commit_true_removes_everything(
    session, sample_project, monkeypatch, isolated_pdf_storage
):
    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "completed"
    job.output_path = f"user-1/{job.id}/story.pdf"
    await session.commit()
    job_dir = pdf_service_module.job_directory("user-1", job.id)
    (job_dir / "story.pdf").write_bytes(b"%PDF-1.4 x")

    result = await pdf_export_service.delete_project_artifacts(
        db=session, user_id="user-1", project_id=sample_project.id, commit=True
    )
    assert result["jobs"] == 1
    assert (await session.execute(PdfExportJob.__table__.select())).first() is None
    assert not job_dir.exists()


# --------------------------------------------------------------------------- API 细节


@pytest.mark.asyncio
async def test_api_total_counts_before_limit(session, sample_project, monkeypatch):
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    monkeypatch.setattr(settings, "pdf_max_active_jobs", 10)
    for _ in range(3):
        await pdf_export_service.create_job(
            db=session, user_id="user-1", project_id=sample_project.id
        )

    with TestClient(_build_api_app(session)) as client:
        response = client.get(
            f"/api/pdf-export/projects/{sample_project.id}/jobs",
            headers={"x-test-user": "user-1"},
            params={"limit": 2},
        )
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 2
    assert payload["total"] == 3, "total 必须是 limit 之前的真实总数"


@pytest.mark.asyncio
async def test_api_download_sets_content_disposition(
    session, sample_project, monkeypatch, isolated_pdf_storage
):
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "completed"
    job.output_path = f"user-1/{job.id}/story.pdf"
    await session.commit()
    job_dir = pdf_service_module.job_directory("user-1", job.id)
    (job_dir / "story.pdf").write_bytes(b"%PDF-1.4 download-name")

    with TestClient(_build_api_app(session)) as client:
        response = client.get(
            f"/api/pdf-export/jobs/{job.id}/download", headers={"x-test-user": "user-1"}
        )
    assert response.status_code == 200
    disposition = response.headers.get("content-disposition", "")
    assert "attachment" in disposition
    assert ".pdf" in disposition


@pytest.mark.asyncio
async def test_task_delete_removes_pdf_job_and_files(
    session, sample_project, monkeypatch, isolated_pdf_storage
):
    """DELETE /api/tasks/{id} 对 pdf_export 任务必须连带删除领域记录与文件"""
    from fastapi.testclient import TestClient

    from app.api import tasks as tasks_api
    from app.database import get_db

    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "completed"
    job.output_path = f"user-1/{job.id}/story.pdf"
    await session.commit()
    # 后台任务必须与领域任务同状态（worker 完成时会同步），否则删除接口会以为还在运行
    background = await session.get(BackgroundTask, job.id)
    background.status = "completed"
    await session.commit()
    job_dir = pdf_service_module.job_directory("user-1", job.id)
    (job_dir / "story.pdf").write_bytes(b"%PDF-1.4 delete-me")

    app = FastAPI()

    @app.middleware("http")
    async def fake_auth(request, call_next):
        request.state.user_id = request.headers.get("x-test-user")
        return await call_next(request)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(tasks_api.router, prefix="/api")

    with TestClient(app) as client:
        response = client.delete(f"/api/tasks/{job.id}", headers={"x-test-user": "user-1"})

    assert response.status_code == 200, response.text
    assert (await session.execute(PdfExportJob.__table__.select())).first() is None
    assert (await session.execute(PdfExportImage.__table__.select())).first() is None
    assert not job_dir.exists(), "PDF 与插图文件都要被删除"


# --------------------------------------------------------------------------- API


def _build_api_app(session: AsyncSession):
    from fastapi import FastAPI, Request

    from app.api import pdf_export as pdf_export_api
    from app.database import get_db

    app = FastAPI()

    @app.middleware("http")
    async def fake_auth(request: Request, call_next):
        user_id = request.headers.get("x-test-user")
        if user_id:
            request.state.user_id = user_id
        return await call_next(request)

    async def override_get_db():
        yield session

    app.dependency_overrides[get_db] = override_get_db
    app.include_router(pdf_export_api.router, prefix="/api")
    return app


def test_api_capabilities_exposes_limits_without_secrets(session, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "meta_muse_api_key", "pdf-test-key-not-real")
    with TestClient(_build_api_app(session)) as client:
        response = client.get(
            f"/api/pdf-export/projects/{uuid.uuid4()}/capabilities",
            headers={"x-test-user": "user-1"},
        )
    # 项目不属于该用户 → 404（能力端点同样做 ownership 校验）
    assert response.status_code == 404


def test_api_capabilities_ok_for_owner(session, sample_project, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(settings, "meta_muse_api_key", "pdf-test-key-not-real")
    with TestClient(_build_api_app(session)) as client:
        response = client.get(
            f"/api/pdf-export/projects/{sample_project.id}/capabilities",
            headers={"x-test-user": "user-1"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["enabled"] is True
    assert payload["reportlab_available"] is True
    assert payload["font_available"] is True
    assert payload["image_failure_policies"] == ["skip", "fail"]
    assert payload["default_image_failure_policy"] == "skip"
    assert "pdf-test-key-not-real" not in response.text
    providers = {item["id"]: item for item in payload["image_providers"]}
    assert providers["meta_muse_image"]["configured"] is True


@pytest.mark.asyncio
async def test_api_create_list_detail_cancel_delete_flow(session, sample_project, monkeypatch):
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    headers = {"x-test-user": "user-1"}
    app = _build_api_app(session)

    with TestClient(app) as client:
        created = client.post(
            f"/api/pdf-export/projects/{sample_project.id}/jobs",
            headers=headers,
            json={"options": {"include_images": False, "author": "Tác giả A"}},
        )
        assert created.status_code == 200, created.text
        job = created.json()
        job_id = job["id"]
        assert job["status"] == "pending"
        assert job["chapter_count"] == 4
        assert job["options"]["author"] == "Tác giả A"

        listed = client.get(f"/api/pdf-export/projects/{sample_project.id}/jobs", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1

        detail = client.get(f"/api/pdf-export/jobs/{job_id}", headers=headers)
        assert detail.status_code == 200
        assert detail.json()["chapter_count"] == 4

        foreign = client.get(
            f"/api/pdf-export/jobs/{job_id}", headers={"x-test-user": "user-2"}
        )
        assert foreign.status_code == 404

        cancelled = client.post(f"/api/pdf-export/jobs/{job_id}/cancel", headers=headers)
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"

        downloaded = client.get(f"/api/pdf-export/jobs/{job_id}/download", headers=headers)
        assert downloaded.status_code == 404  # chưa có file

        deleted = client.delete(f"/api/pdf-export/jobs/{job_id}", headers=headers)
        assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_api_create_rejects_images_without_meta(session, sample_project, monkeypatch):
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    with TestClient(_build_api_app(session)) as client:
        response = client.post(
            f"/api/pdf-export/projects/{sample_project.id}/jobs",
            headers={"x-test-user": "user-1"},
            json={"options": {"include_images": True}},
        )
    assert response.status_code == 503
    assert "META_MUSE_API_KEY" in response.json()["detail"]


@pytest.mark.asyncio
async def test_api_download_serves_pdf(
    session, sample_project, monkeypatch, isolated_pdf_storage
):
    from fastapi.testclient import TestClient

    _stub_spawn(monkeypatch)
    job = await pdf_export_service.create_job(
        db=session, user_id="user-1", project_id=sample_project.id
    )
    job.status = "completed"
    job.output_path = f"user-1/{job.id}/story.pdf"
    await session.commit()
    job_dir = pdf_service_module.job_directory("user-1", job.id)
    (job_dir / "story.pdf").write_bytes(b"%PDF-1.4 download-test")

    with TestClient(_build_api_app(session)) as client:
        response = client.get(
            f"/api/pdf-export/jobs/{job.id}/download", headers={"x-test-user": "user-1"}
        )
    assert response.status_code == 200
    assert response.content.startswith(b"%PDF-1.4")
    assert "application/pdf" in response.headers["content-type"]


def test_api_requires_login(session):
    from fastapi.testclient import TestClient

    with TestClient(_build_api_app(session)) as client:
        response = client.get(f"/api/pdf-export/jobs/{uuid.uuid4()}")
    assert response.status_code == 401
