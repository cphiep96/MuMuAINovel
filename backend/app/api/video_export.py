"""视频导出 API - 创建/查询/重试/取消/删除导出任务并下载成片与字幕"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.schemas.video_export import (
    VideoExportActionResponse,
    VideoExportCapabilitiesResponse,
    VideoExportCreateRequest,
    VideoExportJobListResponse,
    VideoExportJobResponse,
    VideoExportJobSummary,
)
from app.services.video_export.service import (
    DOWNLOAD_KIND_SUBTITLES,
    DOWNLOAD_KIND_VIDEO,
    load_user_image_settings,
    serialize_job,
    video_export_service,
)

router = APIRouter(prefix="/video-export", tags=["Xuất video"])

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _require_user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return user_id


def _safe_filename(text: str, fallback: str = "phim") -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", (text or "").strip())
    cleaned = cleaned.strip("._ ")
    return cleaned[:60] or fallback


@router.get("/capabilities", response_model=VideoExportCapabilitiesResponse, summary="Lấy khả năng xuất phim")
async def get_capabilities(request: Request, db: AsyncSession = Depends(get_db)):
    """返回当前实例是否可用（FFmpeg/TTS）、分辨率白名单与各项上限"""
    user_id = _require_user_id(request)
    user_settings = await load_user_image_settings(db, user_id)
    return video_export_service.capabilities(user_settings=user_settings)


@router.post("/jobs", response_model=VideoExportJobResponse, summary="Tạo tác vụ xuất phim")
async def create_video_export_job(
    payload: VideoExportCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """从章节创建导出任务：立即生成分镜并排队渲染，可轮询任务状态查看进度"""
    user_id = _require_user_id(request)
    options = payload.options.model_dump() if payload.options else None
    job = await video_export_service.create_job(
        db=db,
        user_id=user_id,
        project_id=payload.project_id,
        chapter_ids=payload.chapter_ids,
        options=options,
    )
    job, scenes = await video_export_service.get_job_detail(db=db, user_id=user_id, job_id=job.id)
    return serialize_job(job, scenes)


@router.get("/jobs", response_model=VideoExportJobListResponse, summary="Lấy danh sách tác vụ xuất phim")
async def list_video_export_jobs(
    request: Request,
    project_id: str = Query(..., min_length=1, max_length=36),
    limit: int = Query(20, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """按项目列出导出任务（需要项目归属权限）"""
    user_id = _require_user_id(request)
    jobs = await video_export_service.list_jobs(
        db=db, user_id=user_id, project_id=project_id, limit=limit
    )
    items = [VideoExportJobSummary(**serialize_job(job)) for job in jobs]
    return {"items": items, "total": len(items)}


@router.get("/jobs/{job_id}", response_model=VideoExportJobResponse, summary="Lấy chi tiết tác vụ và storyboard")
async def get_video_export_job(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    job, scenes = await video_export_service.get_job_detail(db=db, user_id=user_id, job_id=job_id)
    return serialize_job(job, scenes)


@router.post("/jobs/{job_id}/retry", response_model=VideoExportActionResponse, summary="Thử lại toàn bộ tác vụ")
async def retry_video_export_job(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    job = await video_export_service.retry_job(db=db, user_id=user_id, job_id=job_id)
    return {"message": "Đã đưa tác vụ vào hàng đợi dựng lại", "job": serialize_job(job)}


@router.post(
    "/jobs/{job_id}/scenes/{scene_id}/retry",
    response_model=VideoExportActionResponse,
    summary="Thử lại một phân cảnh",
)
async def retry_video_export_scene(
    job_id: str,
    scene_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    job = await video_export_service.retry_scene(
        db=db, user_id=user_id, job_id=job_id, scene_id=scene_id
    )
    return {"message": "Đã đưa phân cảnh vào hàng đợi dựng lại", "job": serialize_job(job)}


@router.post("/jobs/{job_id}/cancel", response_model=VideoExportActionResponse, summary="Hủy tác vụ xuất phim")
async def cancel_video_export_job(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    job = await video_export_service.cancel_job(db=db, user_id=user_id, job_id=job_id)
    return {"message": "Tác vụ đã bị hủy", "job": serialize_job(job)}


@router.delete("/jobs/{job_id}", summary="Xóa tác vụ xuất phim")
async def delete_video_export_job(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    await video_export_service.delete_job(db=db, user_id=user_id, job_id=job_id)
    return {"message": "Đã xóa tác vụ và tệp đính kèm"}


@router.get("/jobs/{job_id}/download/video", summary="Tải video MP4")
async def download_video_export(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    job, path = await video_export_service.get_output_path(
        db=db, user_id=user_id, job_id=job_id, kind=DOWNLOAD_KIND_VIDEO
    )
    # inline: thẻ <video> / Range request phải phát được trong trang.
    # Nút Tải MP4 vẫn buộc download bằng blob + <a download>.
    return FileResponse(
        path=path,
        filename=f"{_safe_filename(job.id[:8])}.mp4",
        media_type="video/mp4",
        content_disposition_type="inline",
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/jobs/{job_id}/download/subtitles", summary="Tải phụ đề SRT")
async def download_video_export_subtitles(
    job_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    job, path = await video_export_service.get_output_path(
        db=db, user_id=user_id, job_id=job_id, kind=DOWNLOAD_KIND_SUBTITLES
    )
    return FileResponse(
        path=path,
        filename=f"{_safe_filename(job.id[:8])}.srt",
        media_type="application/x-subrip",
    )


@router.get("/jobs/{job_id}/scenes/{scene_id}/image", summary="Xem ảnh phân cảnh")
async def download_video_export_scene_image(
    job_id: str,
    scene_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    _job, scene, path = await video_export_service.get_scene_image_path(
        db=db, user_id=user_id, job_id=job_id, scene_id=scene_id
    )
    suffix = path.suffix.lower()
    media_type = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
    }.get(suffix, "application/octet-stream")
    return FileResponse(
        path=path,
        filename=f"scene_{int(scene.scene_index) + 1:02d}{suffix}",
        media_type=media_type,
    )
