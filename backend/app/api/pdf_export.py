"""PDF 全本导出 API - 能力查询/创建/查询/重试/取消/删除/下载

所有端点都要求登录，并通过项目 owner 校验（`user_id` + `project_id`）隔离数据；
下载只从受管存储目录读取并做越界/软链接校验，客户端无法指定路径。
"""
from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.pdf_export import PdfExportJob
from app.schemas.pdf_export import (
    PdfExportCapabilitiesResponse,
    PdfExportCreateRequest,
    PdfExportJobListResponse,
    PdfExportJobResponse,
)
from app.services.pdf_export.service import pdf_export_service, serialize_job

router = APIRouter(prefix="/pdf-export", tags=["Xuất PDF"])

_UNSAFE_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]+')


def _require_user_id(request: Request) -> str:
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(status_code=401, detail="Chưa đăng nhập")
    return user_id


def _safe_filename(text: str, fallback: str = "truyen") -> str:
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", (text or "").strip())
    cleaned = cleaned.strip("._ ")
    return cleaned[:80] or fallback


@router.get(
    "/projects/{project_id}/capabilities",
    response_model=PdfExportCapabilitiesResponse,
    summary="Lấy khả năng xuất PDF",
)
async def get_pdf_capabilities(project_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    """返回 ReportLab/字体是否就绪、各项上限、图片 provider 配置状态（不含密钥/路径）"""
    user_id = _require_user_id(request)
    await pdf_export_service._load_project(db=db, user_id=user_id, project_id=project_id)
    return pdf_export_service.capabilities()


@router.post(
    "/projects/{project_id}/jobs",
    response_model=PdfExportJobResponse,
    summary="Tạo tác vụ xuất PDF full truyện",
)
async def create_pdf_export_job(
    project_id: str,
    payload: PdfExportCreateRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """创建任务（立即返回）；章节范围固定为「全项目所有章节」，按序号稳定排序"""
    user_id = _require_user_id(request)
    options = payload.options.model_dump(exclude_none=True) if payload.options else {}
    job = await pdf_export_service.create_job(
        db=db, user_id=user_id, project_id=project_id, options=options
    )
    images = await pdf_export_service._get_images(db=db, job_id=job.id)
    return serialize_job(job, images)


@router.get(
    "/projects/{project_id}/jobs",
    response_model=PdfExportJobListResponse,
    summary="Danh sách tác vụ xuất PDF của dự án",
)
async def list_pdf_export_jobs(
    project_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    user_id = _require_user_id(request)
    await pdf_export_service._load_project(db=db, user_id=user_id, project_id=project_id)
    conditions = (PdfExportJob.project_id == project_id, PdfExportJob.user_id == user_id)
    # total = 应用 limit 之前的真实总数
    total = int(
        (
            await db.execute(select(func.count(PdfExportJob.id)).where(*conditions))
        ).scalar()
        or 0
    )
    result = await db.execute(
        select(PdfExportJob)
        .where(*conditions)
        .order_by(PdfExportJob.created_at.desc())
        .limit(limit)
    )
    jobs = list(result.scalars().all())
    return {"items": [serialize_job(job) for job in jobs], "total": total}


@router.get("/jobs/{job_id}", response_model=PdfExportJobResponse, summary="Chi tiết tác vụ xuất PDF")
async def get_pdf_export_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _require_user_id(request)
    job = await pdf_export_service._get_job(db=db, user_id=user_id, job_id=job_id)
    images = await pdf_export_service._get_images(db=db, job_id=job.id)
    return serialize_job(job, images)


@router.post("/jobs/{job_id}/retry", response_model=PdfExportJobResponse, summary="Xuất lại (giữ ảnh đã có)")
async def retry_pdf_export_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _require_user_id(request)
    job = await pdf_export_service.retry_job(db=db, user_id=user_id, job_id=job_id)
    return serialize_job(job)


@router.post("/jobs/{job_id}/cancel", response_model=PdfExportJobResponse, summary="Hủy tác vụ xuất PDF")
async def cancel_pdf_export_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _require_user_id(request)
    job = await pdf_export_service.cancel_job(db=db, user_id=user_id, job_id=job_id)
    return serialize_job(job)


@router.delete("/jobs/{job_id}", summary="Xóa tác vụ xuất PDF")
async def delete_pdf_export_job(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _require_user_id(request)
    await pdf_export_service.delete_job(db=db, user_id=user_id, job_id=job_id)
    return {"message": "Đã xóa tác vụ và tệp PDF kèm ảnh minh họa"}


@router.get("/jobs/{job_id}/download", summary="Tải PDF full truyện")
async def download_pdf_export(job_id: str, request: Request, db: AsyncSession = Depends(get_db)):
    user_id = _require_user_id(request)
    job, path = await pdf_export_service.get_output_path(db=db, user_id=user_id, job_id=job_id)
    project = await pdf_export_service._load_project(
        db=db, user_id=user_id, project_id=job.project_id
    )
    filename = _safe_filename(getattr(project, "title", "") or job.project_id[:8]) + ".pdf"
    # FileResponse 会自动写入 `Content-Disposition`（含 UTF-8 filename*），前端可据此取名
    return FileResponse(path=path, filename=filename, media_type="application/pdf")
