"""PDF 全本导出服务包 - ReportLab 排版、Unicode 字体、章节插图与任务编排

子模块：
- `builder.py`：Platypus 排版（封面/目录/章节/插图/页眉页脚）
- `fonts.py`：Unicode 字体解析与注册（`PDF_FONT_PATH` + 系统字体探测）
- `images.py`：章节插图（Meta Muse Image）缓存与校验
- `service.py`：任务编排（后台执行、进度、取消、重试、删除、下载）
- `paths.py`：受管存储路径与越界/软链接校验
"""
from app.services.pdf_export.paths import (
    PDF_FILENAME,
    PDF_STORAGE_DIR,
    job_directory,
    resolve_job_file,
)

__all__ = ["PDF_FILENAME", "PDF_STORAGE_DIR", "job_directory", "resolve_job_file"]
