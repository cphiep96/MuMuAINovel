"""启动期数据收敛

服务重启后，上一进程遗留的 `pending`/`running` 导出任务不可能再被任何人推进，必须收敛为失败，
否则会永久占用用户的并发配额。

关键点：只重置**任务级**状态并释放执行权（lease），**刻意不动**分镜的
`motion_operation_id`/`motion_status` —— 远端 provider 的操作可能仍在执行，
重试时应当继续轮询同一个 operation，而不是重新下单（避免重复计费）。
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import update

from app.logger import get_logger

logger = get_logger(__name__)

INTERRUPTED_ERROR = "Dịch vụ khởi động lại, tác vụ xuất phim đã bị gián đoạn"
INTERRUPTED_MESSAGE = "Dịch vụ khởi động lại, vui lòng dựng lại phim"


async def fail_interrupted_jobs(conn, *, interrupted_at: Optional[datetime] = None) -> int:
    """把中断的导出任务标记为失败并释放执行权，返回受影响的任务数"""
    # 先导入 app.database（定义 Base）再导入模型，避免 app.models ↔ app.database 的循环导入
    import app.database  # noqa: F401
    from app.models.video_export import VideoExportJob

    now = interrupted_at or datetime.now()
    result = await conn.execute(
        update(VideoExportJob)
        .where(VideoExportJob.status.in_(("pending", "running")))
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
        logger.info("已收敛 %s 个中断的视频导出任务（保留远端 operation 以供续跑）", count)
    return count
