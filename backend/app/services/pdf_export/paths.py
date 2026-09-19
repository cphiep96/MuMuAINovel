"""PDF 导出存储路径管理

与视频导出同样的安全策略：
- 产物只写入受管目录（`storage/generated_pdfs`），数据库只保存相对路径
- 对外只暴露相对路径；下载时重新拼接并再次校验越界/绝对路径/`..`
- 复用视频导出的通用校验函数（`normalize_relative_path` / `resolve_stored_path`），
  其中 `resolve()` 会解析软链接，因此指向受管目录之外的符号链接同样会被拒绝
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from app.config import PROJECT_ROOT, settings
from app.services.video_export.paths import (  # 通用路径安全校验（与业务无关）
    normalize_relative_path,
    resolve_stored_path,
)

if getattr(sys, "frozen", False):
    DEFAULT_PDF_STORAGE_DIR = Path(sys.executable).parent / "storage" / "generated_pdfs"
else:
    DEFAULT_PDF_STORAGE_DIR = PROJECT_ROOT / "storage" / "generated_pdfs"

# 用户ID/任务ID均来自数据库，这里再做一次白名单校验以防御异常数据
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def _ensure_safe_id(value: str, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID_PATTERN.match(text):
        raise ValueError(f"{label} không hợp lệ")
    return text


def pdf_storage_dir() -> Path:
    """返回 PDF 存储根目录（可在配置中覆盖），并确保目录存在"""
    configured = (settings.pdf_export_storage_dir or "").strip()
    root = Path(configured).expanduser() if configured else DEFAULT_PDF_STORAGE_DIR
    root = root if root.is_absolute() else (PROJECT_ROOT / root)
    root.mkdir(parents=True, exist_ok=True)
    return root


# 兼容直接导入常量的场景（进程启动时确定，运行期不随配置热更新）
PDF_STORAGE_DIR = pdf_storage_dir()

# 子目录/文件名约定
IMAGES_DIRNAME = "images"
PDF_FILENAME = "story.pdf"
# 构建过程中的临时文件名前缀（`.{run_attempt}.building` 由服务层拼接）
PDF_FILENAME_PART = f"{PDF_FILENAME}.building"


def job_directory_path(user_id: str, job_id: str) -> Path:
    """返回某个 PDF 任务的工作目录（不创建，供清理流程使用）

    每次都通过 `pdf_storage_dir()` 解析根目录，因此运行期改配置（或测试里替换目录）都能生效。
    """
    safe_user = _ensure_safe_id(user_id, "ID người dùng")
    safe_job = _ensure_safe_id(job_id, "ID tác vụ")
    return pdf_storage_dir() / safe_user / safe_job


def job_directory(user_id: str, job_id: str) -> Path:
    """返回某个 PDF 任务的工作目录（自动创建）"""
    path = job_directory_path(user_id, job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def resolve_job_file(user_id: str, job_id: str, relative: str) -> Path:
    """把任务内的相对路径解析为绝对路径，越界/符号链接外逃即拒绝"""
    return resolve_stored_path(job_directory_path(user_id, job_id), relative)


__all__ = [
    "DEFAULT_PDF_STORAGE_DIR",
    "IMAGES_DIRNAME",
    "PDF_FILENAME",
    "PDF_FILENAME_PART",
    "PDF_STORAGE_DIR",
    "job_directory",
    "job_directory_path",
    "normalize_relative_path",
    "pdf_storage_dir",
    "resolve_job_file",
    "resolve_stored_path",
]
