"""拆书导入 API"""
from __future__ import annotations

import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.logger import get_logger
from app.schemas.book_import import (
    BookImportApplyRequest,
    BookImportApplyResponse,
    BookImportPreviewResponse,
    BookImportRetryRequest,
    BookImportTaskCreateResponse,
    BookImportTaskCreateRequest,
    BookImportTaskStatusResponse,
)
from app.services.book_import_service import book_import_service
from app.api.settings import get_user_ai_service_from_db
from app.utils.sse_response import SSEResponse, create_sse_response

router = APIRouter(prefix="/book-import", tags=["Nhập đọc tách sách"])
logger = get_logger(__name__)

MAX_TXT_SIZE = 50 * 1024 * 1024  # 50MB


@router.post("/tasks", response_model=BookImportTaskCreateResponse, summary="Tạo tác vụ đọc tách sách (tải lên TXT)")
async def create_book_import_task(
    request: Request,
    file: UploadFile = File(..., description="TXT 文件"),
    project_id: str | None = Form(default=None, description="兼容参数：当前版本固定新建项目，不支持传入"),
    create_new_project: bool = Form(default=True, description="兼容参数：当前版本仅支持 true"),
    import_mode: str = Form(default="append", description="导入模式：append/overwrite"),
    extract_mode: str = Form(default="tail", description="解析范围：tail=截取末章，full=整本"),
    tail_chapter_count: int = Form(default=10, description="当 extract_mode=tail 时，截取末尾章节数，需为5的倍数；超过50按整本拆处理"),
):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")

    if not file.filename or not file.filename.lower().endswith(".txt"):
        raise HTTPException(status_code=400, detail="Chỉ hỗ trợ tệp .txt")

    if import_mode not in {"append", "overwrite"}:
        raise HTTPException(status_code=400, detail="import_mode chỉ hỗ trợ append hoặc overwrite")

    if extract_mode not in {"tail", "full"}:
        raise HTTPException(status_code=400, detail="extract_mode chỉ hỗ trợ tail hoặc full")
    if tail_chapter_count < 5:
        raise HTTPException(status_code=400, detail="tail_chapter_count không được nhỏ hơn 5")
    if tail_chapter_count % 5 != 0:
        raise HTTPException(status_code=400, detail="tail_chapter_count phải là bội số của 5")

    if tail_chapter_count > 50:
        extract_mode = "full"

    if project_id:
        raise HTTPException(status_code=400, detail="Hiện chỉ hỗ trợ nhập vào dự án mới, không hỗ trợ chỉ định project_id")
    if not create_new_project:
        raise HTTPException(status_code=400, detail="Hiện chỉ hỗ trợ nhập vào dự án mới")

    create_payload = BookImportTaskCreateRequest(
        extract_mode=extract_mode,
        tail_chapter_count=tail_chapter_count,
    )

    content = await file.read()
    if len(content) > MAX_TXT_SIZE:
        raise HTTPException(status_code=413, detail="Kích thước tệp vượt quá giới hạn 50MB")

    task = await book_import_service.create_task(
        user_id=user_id,
        filename=file.filename,
        file_content=content,
        project_id=None,
        create_new_project=True,
        import_mode=import_mode,
        extract_mode=create_payload.extract_mode,
        tail_chapter_count=create_payload.tail_chapter_count,
    )
    return task


@router.get("/tasks/{task_id}", response_model=BookImportTaskStatusResponse, summary="Tra cứu trạng thái tác vụ đọc tách sách")
async def get_book_import_task_status(task_id: str, request: Request):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")

    return await book_import_service.get_task_status(task_id=task_id, user_id=user_id)


@router.get("/tasks/{task_id}/preview", response_model=BookImportPreviewResponse, summary="Lấy bản xem trước đọc tách sách")
async def get_book_import_preview(task_id: str, request: Request):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")

    return await book_import_service.get_preview(task_id=task_id, user_id=user_id)


@router.post("/tasks/{task_id}/apply", response_model=BookImportApplyResponse, summary="Xác nhận và nhập")
async def apply_book_import(
    task_id: str,
    payload: BookImportApplyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")

    return await book_import_service.apply_import(
        task_id=task_id,
        user_id=user_id,
        payload=payload,
        db=db,
    )


@router.delete("/tasks/{task_id}", summary="Hủy tác vụ đọc tách sách")
async def cancel_book_import_task(task_id: str, request: Request):
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")

    return await book_import_service.cancel_task(task_id=task_id, user_id=user_id)


@router.post("/tasks/{task_id}/apply-stream", summary="Xác nhận và nhập (tiến độ SSE streaming)")
async def apply_book_import_stream(
    task_id: str,
    payload: BookImportApplyRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    SSE 流式接口：执行基础导入后，分步生成世界观/职业/角色并实时推送进度。
    使用 asyncio.Queue 在服务与 SSE 生成器之间传递进度消息。
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")

    # 使用 asyncio.Queue 实现实时进度推送
    progress_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _progress_callback(message: str, progress: int, status: str = "processing") -> None:
        """进度回调：放入队列供 SSE 生成器消费"""
        sse_msg = SSEResponse.format_sse({
            "type": "progress",
            "message": message,
            "progress": progress,
            "status": status,
        })
        await progress_queue.put(sse_msg)

    async def _run_import() -> None:
        """在后台任务中执行导入并通过队列推送进度"""
        try:
            ai_service = await get_user_ai_service_from_db(user_id, db)
            result = await book_import_service.apply_import_stream(
                task_id=task_id,
                user_id=user_id,
                payload=payload,
                db=db,
                progress_callback=_progress_callback,
                ai_service=ai_service,
            )

            # 发送结果
            await progress_queue.put(await SSEResponse.send_result({
                "success": result.success,
                "project_id": result.project_id,
                "statistics": result.statistics,
            }))
            await progress_queue.put(await SSEResponse.send_progress("Nhập hoàn tất!", 100, "success"))
            await progress_queue.put(await SSEResponse.send_done())
        except HTTPException as exc:
            await progress_queue.put(await SSEResponse.send_error(exc.detail, exc.status_code))
        except Exception as exc:
            logger.error(f"拆书SSE导入失败: {exc}", exc_info=True)
            await progress_queue.put(await SSEResponse.send_error(str(exc), 500))
        finally:
            # 发送终止信号
            await progress_queue.put(None)

    async def _streaming_generator() -> AsyncGenerator[str, None]:
        yield await SSEResponse.send_progress("Bắt đầu nhập dữ liệu phân tích sách...", 0, "processing")

        # 启动后台导入任务
        import_task = asyncio.create_task(_run_import())

        try:
            while True:
                msg = await progress_queue.get()
                if msg is None:
                    break
                yield msg
        except GeneratorExit:
            import_task.cancel()
        except Exception as exc:
            logger.error(f"SSE生成器异常: {exc}", exc_info=True)
            yield await SSEResponse.send_error(str(exc), 500)

    return create_sse_response(_streaming_generator())


@router.post("/tasks/{task_id}/retry-stream", summary="Thử lại các bước tạo thất bại (tiến độ SSE streaming)")
async def retry_failed_steps_stream(
    task_id: str,
    payload: BookImportRetryRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    SSE 流式接口：仅重试之前导入过程中失败的AI生成步骤（世界观/职业/角色）。
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")

    progress_queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def _progress_callback(message: str, progress: int, status: str = "processing") -> None:
        sse_msg = SSEResponse.format_sse({
            "type": "progress",
            "message": message,
            "progress": progress,
            "status": status,
        })
        await progress_queue.put(sse_msg)

    async def _run_retry() -> None:
        try:
            ai_service = await get_user_ai_service_from_db(user_id, db)
            result = await book_import_service.retry_failed_steps_stream(
                task_id=task_id,
                user_id=user_id,
                steps_to_retry=payload.steps,
                db=db,
                progress_callback=_progress_callback,
                ai_service=ai_service,
            )

            await progress_queue.put(await SSEResponse.send_result(result))

            if result.get("still_failed"):
                await progress_queue.put(await SSEResponse.send_progress(
                    f"Thử lại xong, vẫn còn {len(result['still_failed'])} bước thất bại",
                    100,
                    "warning",
                ))
            else:
                await progress_queue.put(await SSEResponse.send_progress("Thử lại tất cả các bước thành công!", 100, "success"))

            await progress_queue.put(await SSEResponse.send_done())
        except HTTPException as exc:
            await progress_queue.put(await SSEResponse.send_error(exc.detail, exc.status_code))
        except Exception as exc:
            logger.error(f"拆书SSE重试失败: {exc}", exc_info=True)
            await progress_queue.put(await SSEResponse.send_error(str(exc), 500))
        finally:
            await progress_queue.put(None)

    async def _streaming_generator() -> AsyncGenerator[str, None]:
        yield await SSEResponse.send_progress("Bắt đầu thử lại các bước tạo bị thất bại...", 0, "processing")

        retry_task = asyncio.create_task(_run_retry())

        try:
            while True:
                msg = await progress_queue.get()
                if msg is None:
                    break
                yield msg
        except GeneratorExit:
            retry_task.cancel()
        except Exception as exc:
            logger.error(f"SSE重试生成器异常: {exc}", exc_info=True)
            yield await SSEResponse.send_error(str(exc), 500)

    return create_sse_response(_streaming_generator())