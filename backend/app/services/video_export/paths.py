"""视频导出存储路径管理

所有成片、字幕与中间片段都必须位于受管存储目录内：
- 对外只暴露相对路径（保存到数据库），下载时再拼回受管目录
- 拒绝绝对路径、`..`、反斜杠等可疑片段，避免路径穿越
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from fastapi import HTTPException

from app.config import PROJECT_ROOT, settings

# 打包为 EXE 时存储目录与可执行文件同级，与封面等既有资源保持一致
if getattr(sys, "frozen", False):
    DEFAULT_VIDEO_STORAGE_DIR = Path(sys.executable).parent / "storage" / "generated_videos"
else:
    DEFAULT_VIDEO_STORAGE_DIR = PROJECT_ROOT / "storage" / "generated_videos"

# 用户ID/任务ID均来自数据库，这里再做一次白名单校验以防御异常数据
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.-]{1,100}$")


def video_storage_dir() -> Path:
    """返回成片存储根目录（可在配置中覆盖），并确保目录存在"""
    configured = (settings.video_export_storage_dir or "").strip()
    root = Path(configured).expanduser() if configured else DEFAULT_VIDEO_STORAGE_DIR
    root = root if root.is_absolute() else (PROJECT_ROOT / root)
    root.mkdir(parents=True, exist_ok=True)
    return root


# 兼容直接导入常量的场景（进程启动时确定，运行期不随配置热更新）
VIDEO_STORAGE_DIR = video_storage_dir()


def _ensure_safe_id(value: str, label: str) -> str:
    text = str(value or "")
    if not _SAFE_ID_PATTERN.match(text):
        raise HTTPException(status_code=400, detail=f"{label} không hợp lệ")
    return text


def job_directory_path(user_id: str, job_id: str) -> Path:
    """返回某个导出任务的工作目录（不创建目录，供清理流程使用）"""
    safe_user = _ensure_safe_id(user_id, "ID người dùng")
    safe_job = _ensure_safe_id(job_id, "ID tác vụ")
    return VIDEO_STORAGE_DIR / safe_user / safe_job


def job_directory(user_id: str, job_id: str) -> Path:
    """返回某个导出任务的工作目录（自动创建）"""
    path = job_directory_path(user_id, job_id)
    path.mkdir(parents=True, exist_ok=True)
    return path


def normalize_relative_path(relative: str) -> str:
    """把存储相对路径规范化为 POSIX 形式，并拒绝绝对路径与穿越片段"""
    raw = str(relative or "").strip()
    if raw.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", raw):
        raise HTTPException(status_code=404, detail="Đường dẫn tệp không hợp lệ")

    text = raw.replace("\\", "/")
    parts = [part for part in text.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise HTTPException(status_code=404, detail="Đường dẫn tệp không hợp lệ")
    return "/".join(parts)


def resolve_stored_path(root: Path, relative: str) -> Path:
    """把相对路径解析为受管目录内的绝对路径，越界即拒绝"""
    normalized = normalize_relative_path(relative)
    root_resolved = root.resolve()
    candidate = (root_resolved / normalized).resolve()
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Đường dẫn tệp không hợp lệ") from exc
    return candidate
