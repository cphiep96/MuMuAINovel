"""PDF Unicode 字体解析（ReportLab + TTF）

越南语需要完整的 Latin Extended 覆盖：
- 优先使用配置 `PDF_FONT_PATH`（必须是 .ttf/.otf 文件）
- 否则按平台探测常见系统字体：Windows Arial / Linux DejaVu Sans、Noto Sans / macOS Arial
- 找不到任何可用字体时抛 `PdfFontUnavailableError`，**不生成**会显示成方块的 PDF，并给出安装指引

字体注册在 ReportLab 的全局 registry 中（进程内只做一次），返回注册后的 family 名称，
builder 用它设置 ParagraphStyle.fontName。
"""
from __future__ import annotations

import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.config import PROJECT_ROOT, settings
from app.logger import get_logger

logger = get_logger(__name__)

FONT_FAMILY_NAME = "MuMuUnicode"

# (regular, bold) 候选；按平台顺序探测
_WINDOWS_FONTS = (
    (r"C:\Windows\Fonts\arial.ttf", r"C:\Windows\Fonts\arialbd.ttf"),
    (r"C:\Windows\Fonts\segoeui.ttf", r"C:\Windows\Fonts\segoeuib.ttf"),
    (r"C:\Windows\Fonts\times.ttf", r"C:\Windows\Fonts\timesbd.ttf"),
)
_LINUX_FONTS = (
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/dejavu/DejaVuSans.ttf", "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/truetype/noto/NotoSans-Bold.ttf"),
    ("/usr/share/fonts/opentype/noto/NotoSans-Regular.ttf", "/usr/share/fonts/opentype/noto/NotoSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf", "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
)
_MACOS_FONTS = (
    ("/System/Library/Fonts/Supplemental/Arial.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/System/Library/Fonts/Supplemental/Times New Roman.ttf", "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"),
)

# 项目内自带字体的兜底位置（部署时把字体放到这里也可用）
_BUNDLED_FONT_DIRS = (
    PROJECT_ROOT / "backend" / "assets" / "fonts",
    PROJECT_ROOT / "assets" / "fonts",
)

_BOLD_SUFFIX_CANDIDATES = ("bd", "-Bold", "_Bold", "b", "Bold")
_registry_lock = threading.Lock()
_registered_family: Optional[str] = None


class PdfFontUnavailableError(RuntimeError):
    """没有可用的 Unicode 字体（或 ReportLab 未安装）"""


@dataclass(frozen=True)
class PdfFonts:
    """解析结果（只保留路径信息，供 builder/日志使用）"""

    regular: Path
    bold: Path
    family: str = FONT_FAMILY_NAME


def _font_candidates() -> tuple[tuple[str, str], ...]:
    if sys.platform.startswith("win"):
        return _WINDOWS_FONTS + _LINUX_FONTS
    if sys.platform == "darwin":
        return _MACOS_FONTS + _LINUX_FONTS
    return _LINUX_FONTS + _MACOS_FONTS


def _guess_bold(regular: Path) -> Optional[Path]:
    """按常见命名规则猜同目录的粗体文件；找不到就返回 None（用常规字重代替）"""
    stem = regular.stem
    for suffix in _BOLD_SUFFIX_CANDIDATES:
        candidate = regular.with_name(f"{stem}{suffix}{regular.suffix}")
        if candidate.is_file():
            return candidate
    return None


def _bundled_fonts() -> Optional[tuple[Path, Path]]:
    for directory in _BUNDLED_FONT_DIRS:
        if not directory.is_dir():
            continue
        for name in ("DejaVuSans.ttf", "NotoSans-Regular.ttf", "Arial.ttf", "arial.ttf"):
            regular = directory / name
            if regular.is_file():
                return regular, (_guess_bold(regular) or regular)
    return None


def resolve_pdf_fonts(*, configured_path: Optional[str] = None) -> PdfFonts:
    """解析（不注册）可用的 Unicode 字体，失败时抛 `PdfFontUnavailableError`"""
    raw = configured_path if configured_path is not None else settings.pdf_font_path
    configured = (raw or "").strip()
    if configured:
        regular = Path(configured).expanduser()
        if not regular.is_absolute():
            regular = PROJECT_ROOT / regular
        if not regular.is_file():
            raise PdfFontUnavailableError(
                "Không tìm thấy tệp font PDF_FONT_PATH đã cấu hình. "
                "Hãy trỏ tới một tệp .ttf Unicode (ví dụ DejaVuSans.ttf hoặc arial.ttf)."
            )
        if regular.suffix.lower() not in (".ttf", ".otf"):
            raise PdfFontUnavailableError("PDF_FONT_PATH phải là tệp .ttf hoặc .otf có hỗ trợ Unicode")
        return PdfFonts(regular=regular, bold=_guess_bold(regular) or regular)

    bundled = _bundled_fonts()
    if bundled is not None:
        return PdfFonts(regular=bundled[0], bold=bundled[1])

    for regular_text, bold_text in _font_candidates():
        regular = Path(regular_text)
        if regular.is_file():
            bold = Path(bold_text)
            return PdfFonts(regular=regular, bold=bold if bold.is_file() else regular)

    raise PdfFontUnavailableError(
        "Máy chủ chưa có font Unicode để tạo PDF tiếng Việt. "
        "Hãy cài font (Debian/Ubuntu: `apt-get install -y fonts-dejavu-core fonts-noto-core`) "
        "hoặc đặt biến môi trường PDF_FONT_PATH trỏ tới tệp .ttf Unicode."
    )


def register_pdf_fonts(*, configured_path: Optional[str] = None) -> PdfFonts:
    """把字体注册进 ReportLab（进程内只注册一次），返回 family 名称"""
    global _registered_family

    fonts = resolve_pdf_fonts(configured_path=configured_path)
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError as exc:  # pragma: no cover - 依赖缺失时给出明确错误
        raise PdfFontUnavailableError(
            "Chưa cài ReportLab nên không thể tạo PDF. Hãy chạy `pip install reportlab`."
        ) from exc

    with _registry_lock:
        if _registered_family == fonts.family:
            return fonts
        pdfmetrics.registerFont(TTFont(fonts.family, str(fonts.regular)))
        bold_name = f"{fonts.family}-Bold"
        if fonts.bold != fonts.regular:
            pdfmetrics.registerFont(TTFont(bold_name, str(fonts.bold)))
        else:
            logger.warning("Không tìm thấy font đậm tương ứng, PDF sẽ dùng một kiểu chữ cho toàn bộ văn bản")
            bold_name = fonts.family
        pdfmetrics.registerFontFamily(
            fonts.family, normal=fonts.family, bold=bold_name, italic=fonts.family, boldItalic=bold_name
        )
        _registered_family = fonts.family
    logger.info("Đã đăng ký font PDF Unicode: %s", fonts.regular.name)
    return fonts


def font_available() -> bool:
    """探测字体是否就绪（用于 capabilities，不抛错、不泄露路径）"""
    try:
        resolve_pdf_fonts()
    except PdfFontUnavailableError:
        return False
    return True


def reset_font_cache() -> None:
    """测试辅助：允许在配置变更后重新注册"""
    global _registered_family
    with _registry_lock:
        _registered_family = None
