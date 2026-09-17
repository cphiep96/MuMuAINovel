"""PDF 导出的启动期数据收敛

服务重启后，上一进程遗留的 `pending`/`running` PDF 任务无法再被推进，必须收敛为失败，
否则会永久占用用户的并发配额（`PDF_MAX_ACTIVE_JOBS`）。

只重置**任务级**状态并释放执行权（lease）；插图记录**保持原样**：
状态为 `ready` 的插图在重试时会被复用，不会重新调用付费 API。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import update

from app.logger import get_logger

logger = get_logger(__name__)

INTERRUPTED_ERROR = "Dịch vụ khởi động lại, tác vụ xuất PDF đã bị gián đoạn"
INTERRUPTED_MESSAGE = "Dịch vụ khởi động lại, vui lòng xuất PDF lại"


async def fail_interrupted_jobs(conn, *, interrupted_at: Optional[datetime] = None) -> int:
    """把中断的 PDF 导出任务标记为失败并释放执行权，返回受影响的任务数"""
    # 先导入 app.database（定义 Base）再导入模型，避免 app.models ↔ app.database 的循环导入
    import app.database  # noqa: F401
    from app.models.pdf_export import PdfExportJob

    now = interrupted_at or datetime.now()
    result = await conn.execute(
        update(PdfExportJob)
        .where(PdfExportJob.status.in_(("pending", "running")))
        .values(
            status="failed",
            error_message=INTERRUPTED_ERROR,
            status_message=INTERRUPTED_MESSAGE,
            completed_at=now,
            updated_at=now,
            worker_token=None,
            claimed_at=None,
        )
    )
    count = int(result.rowcount or 0)
    if count:
        logger.info("已收敛 %s 个中断的 PDF 导出任务（保留已生成插图以便复用）", count)
    return count
