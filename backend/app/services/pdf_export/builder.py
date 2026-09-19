"""PDF 全本排版（ReportLab Platypus）

结构：封面 → 目录（可选） → 各章节（标题 + 插图 + 正文段落），带页眉页脚与「Trang X / Y」。
安全/健壮性：
- 章节正文是用户内容：先做 XML escape 与不可见控制符清理，再交给 Paragraph
- 超长单词/URL 允许断行（`splitLongWords`），避免文字溢出页面
- 插图按比例缩放到正文宽度，读图失败只记 warning 并跳过（不阻断整本导出）
- 只读取服务端受管目录内的图片路径（由调用方传入，客户端永远无法指定）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, Sequence
from xml.sax.saxutils import escape

from app.config import settings
from app.logger import get_logger
from app.services.pdf_export.fonts import FONT_FAMILY_NAME, PdfFonts

logger = get_logger(__name__)

PAGE_SIZES = ("A4", "LETTER")
MAX_TITLE_CHARS = 200
MAX_CHAPTER_TITLE_CHARS = 200


class PdfBuildError(RuntimeError):
    """排版失败（例如 ReportLab 未安装或输出不可写）"""


class PdfBuildCancelled(RuntimeError):
    """排版过程中被取消（worker 设置了取消标记）"""


@dataclass
class PdfBookMeta:
    """书籍元信息（标题/作者等，均来自服务端数据）"""

    title: str
    author: str = ""
    genre: str = ""
    description: str = ""
    cover_path: Optional[Path] = None
    generated_at: Optional[datetime] = None
    include_toc: bool = True
    page_size: str = "A4"


@dataclass
class PdfChapterContent:
    """一章的渲染输入"""

    number: int
    title: str
    content: str
    sub_index: int = 1
    image_path: Optional[Path] = None

    @property
    def display_title(self) -> str:
        """章节显示名：细化模式下用 `Chương 12.3` 区分同序号子章节"""
        number = int(self.number or 0)
        sub = int(self.sub_index or 1)
        label = f"Chương {number}" if sub <= 1 else f"Chương {number}.{sub}"
        title = normalize_text(self.title) or "Không có tiêu đề"
        return f"{label}: {title}"


@dataclass
class PdfBuildResult:
    """排版结果"""

    page_count: int
    file_size_bytes: int
    chapter_count: int
    image_count: int
    warnings: list[str] = field(default_factory=list)


def normalize_text(text: object, *, max_chars: Optional[int] = None) -> str:
    """清理用户文本：去掉控制符、统一换行、压缩空白并截断"""
    raw = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    cleaned = "".join(ch for ch in raw if ch == "\n" or ch >= " " or ch == "\t")
    cleaned = cleaned.replace("\t", "    ").strip()
    if max_chars is not None:
        cleaned = cleaned[:max_chars]
    return cleaned


def escape_markup(text: str) -> str:
    """转义 XML 特殊字符，避免用户内容被当成 ReportLab 标记（注入/排版错乱）"""
    return escape(text, {'"': "&quot;", "'": "&apos;"})


def split_paragraphs(content: str, *, max_paragraph_chars: int = 4000) -> list[str]:
    """把章节正文拆成段落：按空行分段；段落/单行过长时按字符数硬切，避免排版溢出"""
    text = normalize_text(content)
    if not text:
        return []
    paragraphs: list[str] = []

    def _chunk_long_line(line: str) -> str:
        """把超长单行切成固定长度的块，返回最后一块（可能不足 max）留给后续拼接"""
        buffer = ""
        for start in range(0, len(line), max_paragraph_chars):
            chunk = line[start : start + max_paragraph_chars]
            if len(chunk) == max_paragraph_chars:
                paragraphs.append(chunk)
            else:
                buffer = chunk
        return buffer

    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        if len(block) <= max_paragraph_chars:
            paragraphs.append(block)
            continue

        buffer = ""
        for line in block.split("\n"):
            if len(line) > max_paragraph_chars:
                if buffer:
                    paragraphs.append(buffer)
                buffer = _chunk_long_line(line)
                continue
            candidate = f"{buffer}\n{line}" if buffer else line
            if len(candidate) > max_paragraph_chars:
                if buffer:
                    paragraphs.append(buffer)
                buffer = line
            else:
                buffer = candidate
        if buffer:
            paragraphs.append(buffer)
    return paragraphs


def build_story_pdf(
    *,
    meta: PdfBookMeta,
    chapters: Sequence[PdfChapterContent],
    out_path: Path,
    fonts: Optional[PdfFonts] = None,
    max_image_width_ratio: Optional[float] = None,
    font_family: Optional[str] = None,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> PdfBuildResult:
    """渲染整本 PDF 并写入 `out_path`，返回页数/大小/警告

    - `font_family` 可覆盖字体族（例如内置 Helvetica，用于纯 ASCII 场景/测试）
    - `cancel_check`：线程安全的同步回调（例如 `threading.Event.is_set`）。在**每个章节**开始前、
      以及每若干段落/插图前检查一次；一旦返回 True 就抛出 `PdfBuildCancelled`，
      让 worker 能及时回收（`asyncio.to_thread` 本身无法中断线程）。
    """
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
        from reportlab.lib.pagesizes import A4, LETTER
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import cm
        from reportlab.pdfgen import canvas as pdfgen_canvas
        from reportlab.platypus import (
            BaseDocTemplate,
            Frame,
            KeepTogether,
            PageBreak,
            PageTemplate,
            Paragraph,
            Spacer,
            Table,
            TableStyle,
        )
        from reportlab.platypus.tableofcontents import TableOfContents
    except ImportError as exc:  # pragma: no cover - 依赖缺失
        raise PdfBuildError(
            "Chưa cài ReportLab nên không thể tạo PDF. Hãy chạy `pip install reportlab`."
        ) from exc

    family = font_family or (fonts.family if fonts else FONT_FAMILY_NAME)
    page_size = (meta.page_size or "A4").upper()
    size = LETTER if page_size == "LETTER" else A4
    ratio = float(max_image_width_ratio if max_image_width_ratio is not None else settings.pdf_image_width_ratio)
    warnings: list[str] = []

    styles = getSampleStyleSheet()
    body_style = ParagraphStyle(
        "BodyText-VN",
        parent=styles["BodyText"],
        fontName=family,
        fontSize=11,
        leading=17,
        alignment=TA_JUSTIFY,
        spaceAfter=8,
        splitLongWords=1,
        wordWrap="LTR",
    )
    chapter_style = ParagraphStyle(
        "ChapterHeading-VN",
        parent=styles["Heading1"],
        fontName=family,
        fontSize=18,
        leading=24,
        spaceBefore=6,
        spaceAfter=14,
        textColor=colors.HexColor("#1f2937"),
    )
    cover_title_style = ParagraphStyle(
        "CoverTitle-VN",
        parent=styles["Title"],
        fontName=family,
        fontSize=30,
        leading=38,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#111827"),
    )
    cover_sub_style = ParagraphStyle(
        "CoverSub-VN",
        parent=styles["Normal"],
        fontName=family,
        fontSize=13,
        leading=20,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#4b5563"),
    )
    caption_style = ParagraphStyle(
        "Caption-VN",
        parent=styles["Normal"],
        fontName=family,
        fontSize=9,
        leading=13,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#6b7280"),
    )

    class _StoryDocTemplate(BaseDocTemplate):
        """支持目录条目通知 + 页眉页脚/页码"""

        def afterFlowable(self, flowable):  # noqa: N802 - ReportLab 约定
            if isinstance(flowable, Paragraph) and flowable.style.name == "ChapterHeading-VN":
                self.notify("TOCEntry", (0, flowable.getPlainText(), self.page))

    class _NumberedCanvas(pdfgen_canvas.Canvas):
        """两遍式页码：总页数只有整本排版完成后才确定，故在 save() 阶段回填「Trang N / TOTAL」

        与目录（`multiBuild` 的多遍构建）兼容：每一遍都创建独立 canvas，只有最终一遍被保存，
        因此在 save() 时收集的页数就是最终页数；页眉仍由 `onPage` 绘制。
        """

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved_page_states: list[dict] = []

        def showPage(self):  # noqa: N802 - ReportLab 约定
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total_pages = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self.saveState()
                self.setFont(family, 8)
                self.setFillColor(colors.HexColor("#9ca3af"))
                self.drawCentredString(size[0] / 2, 1.2 * cm, f"Trang {self._pageNumber} / {total_pages}")
                self.restoreState()
                super().showPage()
            super().save()

    created = meta.generated_at or datetime.now()
    title = normalize_text(meta.title, max_chars=MAX_TITLE_CHARS) or "Truyện"
    author = normalize_text(meta.author, max_chars=120)
    genre = normalize_text(meta.genre, max_chars=80)
    description = normalize_text(meta.description, max_chars=1200)

    doc_kwargs = {
        "pagesize": size,
        "leftMargin": 2.2 * cm,
        "rightMargin": 2.2 * cm,
        "topMargin": 2.4 * cm,
        "bottomMargin": 2.0 * cm,
        "title": title,
        "author": author or "MuMuAINovel",
        "subject": description[:200] if description else f"Bản đầy đủ: {title}",
        "creator": "MuMuAINovel PDF Export",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)

    def _decorate(canvas, doc) -> None:
        canvas.saveState()
        canvas.setFont(family, 8)
        canvas.setFillColor(colors.HexColor("#9ca3af"))
        header = title
        canvas.drawString(doc.leftMargin, size[1] - 1.5 * cm, header[:90])
        canvas.drawRightString(size[0] - doc.rightMargin, size[1] - 1.5 * cm, created.strftime("%d/%m/%Y"))
        canvas.setStrokeColor(colors.HexColor("#e5e7eb"))
        canvas.line(doc.leftMargin, size[1] - 1.7 * cm, size[0] - doc.rightMargin, size[1] - 1.7 * cm)
        canvas.restoreState()

    try:
        doc = _StoryDocTemplate(str(out_path), **doc_kwargs)
    except Exception as exc:  # noqa: BLE001 - 目录不可写等
        raise PdfBuildError(f"Không tạo được tệp PDF: {type(exc).__name__}") from exc

    frame = Frame(
        doc.leftMargin,
        doc.bottomMargin,
        doc.width,
        doc.height,
        id="body",
        leftPadding=0,
        rightPadding=0,
        topPadding=0,
        bottomPadding=0,
    )
    doc.addPageTemplates([PageTemplate(id="story", frames=[frame], onPage=_decorate)])

    story: list = []

    # ---------------- 封面 ----------------
    story.append(Spacer(1, 3.2 * cm))
    story.append(Paragraph(escape_markup(title), cover_title_style))
    if author:
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph(escape_markup(author), cover_sub_style))
    if genre:
        story.append(Spacer(1, 0.2 * cm))
        story.append(Paragraph(escape_markup(genre), cover_sub_style))
    story.append(Spacer(1, 0.8 * cm))

    cover_rendered = False
    if meta.cover_path is not None:
        cover = _build_image_flowable(meta.cover_path, doc.width * 0.72, 10 * cm, warnings, label="bìa")
        if cover is not None:
            story.append(cover)
            cover_rendered = True
    if not cover_rendered:
        story.append(Spacer(1, 0.4 * cm))

    story.append(Spacer(1, 0.6 * cm))
    info_rows = [
        ["Số chương", str(len(chapters))],
        ["Thời điểm xuất", created.strftime("%d/%m/%Y %H:%M")],
    ]
    info_table = Table(info_rows, colWidths=[doc.width * 0.3, doc.width * 0.5], hAlign="CENTER")
    info_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, -1), family),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("TEXTCOLOR", (0, 0), (0, -1), colors.HexColor("#6b7280")),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(info_table)
    if description:
        story.append(Spacer(1, 0.8 * cm))
        story.append(Paragraph(escape_markup(description), cover_sub_style))

    # ---------------- 目录 ----------------
    if meta.include_toc:
        story.append(PageBreak())
        toc = TableOfContents()
        toc.levelStyles = [
            ParagraphStyle(
                "TOCEntry-VN",
                fontName=family,
                fontSize=11,
                leading=16,
                leftIndent=0,
                firstLineIndent=0,
            )
        ]
        story.append(Paragraph(escape_markup("Mục lục"), cover_title_style))
        story.append(Spacer(1, 0.5 * cm))
        story.append(toc)

    # ---------------- 章节 ----------------
    image_count = 0
    for chapter in chapters:
        if cancel_check is not None and cancel_check():
            raise PdfBuildCancelled("Đã hủy trong lúc dựng PDF")
        story.append(PageBreak())
        heading = Paragraph(escape_markup(chapter.display_title), chapter_style)
        story.append(heading)

        if chapter.image_path is not None:
            illustration = _build_image_flowable(
                chapter.image_path,
                doc.width * ratio,
                (size[1] - doc.topMargin - doc.bottomMargin) * 0.5,
                warnings,
                label=chapter.display_title,
            )
            if illustration is not None:
                story.append(KeepTogether([illustration, Spacer(1, 0.2 * cm)]))
                story.append(Paragraph("Ảnh minh họa cho chương", caption_style))
                story.append(Spacer(1, 0.4 * cm))
                image_count += 1

        paragraphs = split_paragraphs(chapter.content) or ["(Chương này chưa có nội dung)"]
        for index, paragraph in enumerate(paragraphs):
            if cancel_check is not None and index % 20 == 0 and cancel_check():
                raise PdfBuildCancelled("Đã hủy trong lúc dựng PDF")
            story.append(Paragraph(escape_markup(paragraph).replace("\n", "<br/>"), body_style))

    if not chapters:
        story.append(Paragraph(escape_markup("Dự án chưa có chương nào."), body_style))

    try:
        doc.multiBuild(story, canvasmaker=_NumberedCanvas)
    except PdfBuildCancelled:
        raise
    except PdfBuildError:
        raise
    except Exception as exc:  # noqa: BLE001 - 排版异常统一收敛为可读错误
        raise PdfBuildError(f"Lỗi khi dựng PDF: {type(exc).__name__}") from exc

    if not out_path.is_file() or out_path.stat().st_size <= 0:
        raise PdfBuildError("Tệp PDF không được tạo hoặc rỗng")
    return PdfBuildResult(
        page_count=int(doc.page or 0),
        file_size_bytes=out_path.stat().st_size,
        chapter_count=len(chapters),
        image_count=image_count,
        warnings=warnings,
    )


def _build_image_flowable(path: Path, max_width: float, max_height: float, warnings: list[str], *, label: str):
    """按比例缩放插图；读图失败/尺寸异常时记 warning 并返回 None（不阻断导出）"""
    try:
        from reportlab.lib.utils import ImageReader
        from reportlab.platypus import Image
    except ImportError as exc:  # pragma: no cover
        raise PdfBuildError("ReportLab thiếu module Image") from exc

    if not path.is_file():
        warnings.append(f"Không tìm thấy ảnh minh họa cho {label}, đã bỏ qua")
        return None
    try:
        reader = ImageReader(str(path))
        width, height = reader.getSize()
    except Exception as exc:  # noqa: BLE001 - 文件损坏/格式不支持
        warnings.append(f"Ảnh minh họa của {label} không đọc được ({type(exc).__name__}), đã bỏ qua")
        return None
    if width <= 0 or height <= 0:
        warnings.append(f"Ảnh minh họa của {label} có kích thước không hợp lệ, đã bỏ qua")
        return None

    scale = min(max_width / float(width), max_height / float(height), 1.0)
    draw_width = max(1.0, float(width) * scale)
    draw_height = max(1.0, float(height) * scale)
    try:
        image = Image(str(path), width=draw_width, height=draw_height)
        image.hAlign = "CENTER"
        return image
    except Exception as exc:  # noqa: BLE001
        warnings.append(f"Không chèn được ảnh minh họa của {label} ({type(exc).__name__}), đã bỏ qua")
        return None
