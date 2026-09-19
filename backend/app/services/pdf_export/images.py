"""章节插图（Meta Muse Image）解析、缓存与校验

策略：
- 插图只来自**服务端受管目录**：PDF 任务目录内的 `images/`；客户端永远无法指定路径或 URL
- 已有 `ready` 图片直接复用（重试不重复调用付费 API）
- `include_images=false` 或未配置 image provider 时完全不调用 Meta
- 图片失败时按 `image_failure_policy` 处理：`skip`（默认）记录 warning 继续导出，`fail` 直接失败
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.logger import get_logger
from app.services.video_export.image_providers import (  # 复用图片 provider 契约
    ImageProviderError,
    ImageRequest,
    SceneImageProvider,
    SceneImageResult,
    detect_image_magic,
    image_error_detail,
    output_extension,
)

logger = get_logger(__name__)

IMAGE_STATUS_PENDING = "pending"
IMAGE_STATUS_GENERATING = "generating"
IMAGE_STATUS_READY = "ready"
IMAGE_STATUS_FAILED = "failed"
IMAGE_STATUS_CANCELLED = "cancelled"
IMAGE_STATUS_SKIPPED = "skipped"

IMAGE_FAILURE_POLICIES = ("skip", "fail")
IMAGE_FAILURE_POLICY_DEFAULT = "skip"

# 重试时需要重新生成的图片状态（ready 一律复用）
IMAGE_RETRYABLE_STATUSES = frozenset(
    {IMAGE_STATUS_PENDING, IMAGE_STATUS_GENERATING, IMAGE_STATUS_FAILED, IMAGE_STATUS_CANCELLED}
)

PROMPT_MAX_CHARS = 900
PROMPT_EXCERPT_CHARS = 320

PROMPT_STYLE_SUFFIX = (
    "Phong cách minh họa điện ảnh cho sách, ánh sáng tự nhiên, bố cục dọc, "
    "không chữ, không watermark, không khung viền."
)


class PdfImageError(RuntimeError):
    """插图准备失败（消息已 sanitize）"""


@dataclass
class ChapterImagePlan:
    """一章的插图准备结果"""

    chapter_id: str
    chapter_number: int
    sub_index: int
    title: str
    status: str
    path: Optional[Path] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    size: Optional[str] = None
    error: Optional[str] = None


def build_image_prompt(
    *,
    title: str,
    summary: Optional[str] = None,
    content: Optional[str] = None,
    max_chars: int = PROMPT_MAX_CHARS,
) -> str:
    """由章节标题 + 摘要 + 正文开头构造插图 prompt（有长度上限，避免请求过大/费用不可控）"""
    parts: list[str] = []
    clean_title = " ".join(str(title or "").split())
    if clean_title:
        parts.append(f"Minh họa bìa chương truyện: {clean_title}.")
    clean_summary = " ".join(str(summary or "").split())
    if clean_summary:
        parts.append(f"Tóm tắt: {clean_summary[:PROMPT_EXCERPT_CHARS]}.")
    clean_content = " ".join(str(content or "").split())
    if clean_content:
        parts.append(f"Trích đoạn: {clean_content[:PROMPT_EXCERPT_CHARS]}.")
    parts.append(PROMPT_STYLE_SUFFIX)
    prompt = " ".join(parts)
    return prompt[:max_chars]


def image_relative_path(job_relative_dir: str, *, chapter_number: int, sub_index: int, extension: str) -> str:
    """任务内的图片相对路径（序号来自数据库，客户端无法控制）"""
    number = int(chapter_number or 0)
    sub = int(sub_index or 1)
    name = f"chapter_{number:04d}_{sub:02d}{extension}"
    prefix = f"{job_relative_dir.strip('/')}/" if job_relative_dir else ""
    return f"{prefix}{name}"


def validate_stored_image(path: Path, *, max_bytes: int) -> tuple[bool, Optional[str]]:
    """校验受管目录内的图片：存在、非空、未超限、magic bytes 正确"""
    if not path.is_file():
        return False, "không tìm thấy tệp ảnh"
    size = path.stat().st_size
    if size <= 0:
        return False, "tệp ảnh rỗng"
    if size > max_bytes:
        return False, "ảnh vượt giới hạn dung lượng"
    try:
        head = path.read_bytes()[:16]
    except OSError:
        return False, "không đọc được tệp ảnh"
    if detect_image_magic(head) is None:
        return False, "tệp không phải PNG/WebP/JPEG hợp lệ"
    return True, None


async def generate_chapter_image(
    *,
    provider: SceneImageProvider,
    title: str,
    summary: Optional[str],
    content: Optional[str],
    out_path: Path,
    model: Optional[str],
    aspect_ratio: str,
    size: str,
    reasoning_strength: Optional[str],
    cancel_check=None,
    timeout: Optional[float] = None,
) -> SceneImageResult:
    """调用 image provider 生成一章的插图（异常统一 sanitize）"""
    prompt = build_image_prompt(title=title, summary=summary, content=content)
    request = ImageRequest(
        prompt=prompt,
        aspect_ratio=aspect_ratio,
        size=size,
        model=model,
        reasoning_strength=reasoning_strength,
    )
    try:
        return await provider.generate_image(
            request, out_path, cancel_check=cancel_check, timeout=timeout
        )
    except ImageProviderError as exc:
        raise PdfImageError(image_error_detail(exc)) from exc


__all__ = [
    "IMAGE_FAILURE_POLICIES",
    "IMAGE_FAILURE_POLICY_DEFAULT",
    "IMAGE_RETRYABLE_STATUSES",
    "IMAGE_STATUS_CANCELLED",
    "IMAGE_STATUS_FAILED",
    "IMAGE_STATUS_GENERATING",
    "IMAGE_STATUS_PENDING",
    "IMAGE_STATUS_READY",
    "IMAGE_STATUS_SKIPPED",
    "ChapterImagePlan",
    "PdfImageError",
    "build_image_prompt",
    "generate_chapter_image",
    "image_relative_path",
    "output_extension",
    "validate_stored_image",
]
