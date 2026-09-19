"""PDF 全本导出服务

流程（全部在后台任务队列中执行，不阻塞请求）：
1. 建任务时确定章节集合（全项目，按 chapter_number/sub_index/created_at 稳定排序）与插图行
2. 逐章准备插图（可选，调用 Meta Muse Image；已 `ready` 的图片直接复用，不重复计费）
3. ReportLab 排版封面 + 目录 + 章节 → 单个 PDF 写入受管目录
4. 落库页数/体积/警告，前端可下载

安全要点：
- 只读服务端受管素材（项目封面 + 任务目录内的插图），客户端无法指定路径/URL
- API key、base64、远端 URL、绝对路径都不会进入响应/日志/PDF
- 取消 → cancelled（不计为失败、不继续调用付费 API）；重试只重做失败/取消的插图
"""
from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import settings
from app.database import get_engine
from app.logger import get_logger
from app.models.background_task import BackgroundTask
from app.models.chapter import Chapter
from app.models.pdf_export import PdfExportImage, PdfExportJob
from app.models.project import Project
from app.services.background_task_service import background_task_service
from app.services.pdf_export.builder import (
    PdfBookMeta,
    PdfBuildCancelled,
    PdfBuildError,
    PdfChapterContent,
    build_story_pdf,
    normalize_text,
)
from app.services.pdf_export.fonts import (
    PdfFontUnavailableError,
    font_available,
    register_pdf_fonts,
    resolve_pdf_fonts,
)
from app.services.pdf_export.images import (
    IMAGE_FAILURE_POLICIES,
    IMAGE_FAILURE_POLICY_DEFAULT,
    IMAGE_RETRYABLE_STATUSES,
    IMAGE_STATUS_CANCELLED,
    IMAGE_STATUS_FAILED,
    IMAGE_STATUS_GENERATING,
    IMAGE_STATUS_PENDING,
    IMAGE_STATUS_READY,
    PdfImageError,
    generate_chapter_image,
    image_relative_path,
    output_extension,
    validate_stored_image,
)
from app.services.pdf_export.paths import (
    IMAGES_DIRNAME,
    PDF_FILENAME,
    PDF_FILENAME_PART,
    job_directory,
    job_directory_path,
    normalize_relative_path,
    pdf_storage_dir,
    resolve_job_file,
    resolve_stored_path,
)
from app.services.video_export.assets import resolve_cover_image
from app.services.video_export.image_providers import (
    ImageCancelledError,
    ImageConfigError,
    ImageProviderError,
    ImageRequestError,
    ImageTimeoutError,
    build_image_provider,
    default_image_provider_name,
    image_error_detail,
    is_known_image_provider,
    list_image_provider_capabilities,
)
from app.services.video_export.providers.errors import sanitize_message

logger = get_logger(__name__)

TASK_TYPE = "pdf_export"
PAGE_SIZE_OPTIONS = ("A4", "LETTER")

# 进程内正在执行的 PDF 任务（配合数据库 lease 使用）
RUNNING_JOB_IDS: set[str] = set()
_PENDING_CLEANUPS: set[asyncio.Task] = set()


class PdfJobCancelledError(RuntimeError):
    """任务被取消/超时中断"""


class PdfJobTimeoutError(RuntimeError):
    """任务超过墙钟上限"""


def _monotonic() -> float:
    return time.monotonic()


def normalize_options(raw: Optional[dict[str, Any]]) -> dict[str, Any]:
    """校验并规范化导出参数（全部有服务端默认值/白名单）"""
    data = dict(raw or {})
    include_cover = bool(data.get("include_cover", True))
    include_images = bool(data.get("include_images", False))
    include_toc = bool(data.get("include_toc", settings.pdf_include_toc))

    policy = str(data.get("image_failure_policy") or IMAGE_FAILURE_POLICY_DEFAULT).strip().lower()
    if policy not in IMAGE_FAILURE_POLICIES:
        raise HTTPException(
            status_code=400,
            detail=f"Chính sách khi ảnh lỗi không hợp lệ, chỉ chấp nhận: {', '.join(IMAGE_FAILURE_POLICIES)}",
        )

    page_size = str(data.get("page_size") or settings.pdf_default_page_size).strip().upper()
    if page_size not in PAGE_SIZE_OPTIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Khổ giấy không hợp lệ, chỉ chấp nhận: {', '.join(PAGE_SIZE_OPTIONS)}",
        )

    author = normalize_text(data.get("author"), max_chars=120)
    title_override = normalize_text(data.get("title"), max_chars=200)

    image_plan: dict[str, Any] = {
        "image_provider": None,
        "image_model": None,
        "image_aspect_ratio": None,
        "image_size": None,
        "image_reasoning_strength": None,
    }
    if include_images:
        if not settings.video_image_enabled:
            raise HTTPException(
                status_code=503,
                detail="Chức năng tạo ảnh đang bị tắt trên máy chủ (VIDEO_IMAGE_ENABLED=false) nên không thể tạo ảnh minh họa",
            )
        requested = str(data.get("image_provider") or "").strip()
        if requested and not is_known_image_provider(requested):
            raise HTTPException(status_code=400, detail=f"Provider ảnh không được hỗ trợ: {requested}")
        name = requested or (settings.video_image_provider or "").strip() or default_image_provider_name() or ""
        if not name:
            raise HTTPException(
                status_code=503,
                detail=(
                    "Chưa có provider tạo ảnh nào được cấu hình trên máy chủ (cần META_MUSE_API_KEY). "
                    "Hãy tắt tùy chọn ảnh minh họa để xuất PDF chỉ có chữ."
                ),
            )
        provider = _resolve_image_provider(name)
        try:
            model = provider.normalize_model(data.get("image_model") or settings.video_image_model)
            aspect_ratio = provider.normalize_aspect_ratio(
                data.get("image_aspect_ratio") or settings.video_image_aspect_ratio
            )
            size = provider.normalize_size(data.get("image_size"), aspect_ratio)
            reasoning = provider.normalize_reasoning_strength(
                data.get("image_reasoning_strength") or settings.video_image_reasoning_strength
            )
        except ImageRequestError as exc:
            raise HTTPException(status_code=400, detail=image_error_detail(exc)) from exc
        image_plan = {
            "image_provider": provider.name,
            "image_model": model,
            "image_aspect_ratio": aspect_ratio,
            "image_size": size,
            "image_reasoning_strength": reasoning,
        }

    return {
        "include_cover": include_cover,
        "include_images": include_images,
        "include_toc": include_toc,
        "image_failure_policy": policy,
        "page_size": page_size,
        "author": author or None,
        "title": title_override or None,
        **image_plan,
    }


def _resolve_image_provider(name: str):
    """构建并校验图片 provider；未配置时 503（绝不静默换 provider）"""
    try:
        provider = build_image_provider(name)
    except ImageConfigError as exc:
        raise HTTPException(status_code=503, detail=image_error_detail(exc)) from exc
    state = provider.configuration()
    if not state.configured:
        missing = ", ".join(state.missing_config) if state.missing_config else ""
        detail = state.detail or f"Provider ảnh {name} chưa được cấu hình"
        if missing:
            detail = f"{detail} Biến môi trường còn thiếu: {missing}."
        raise HTTPException(status_code=503, detail=sanitize_message(detail))
    return provider


def serialize_image(row: PdfExportImage) -> dict[str, Any]:
    """插图信息（不含路径/URL/base64）"""
    return {
        "id": row.id,
        "chapter_id": row.chapter_id,
        "chapter_number": row.chapter_number,
        "sub_index": row.sub_index,
        "title": row.title,
        "status": row.status,
        "provider": row.provider,
        "model": row.model,
        "size": row.size,
        "error": row.error,
    }


def _artifact_file_exists(job: PdfExportJob) -> bool:
    """产物文件是否真实存在（`has_pdf` 不能只看数据库字段）"""
    if not job.output_path:
        return False
    try:
        if normalize_relative_path(job.output_path).split("/", 1)[0] != job.user_id:
            return False
        return resolve_stored_path(pdf_storage_dir(), job.output_path).is_file()
    except (HTTPException, ValueError, OSError):
        return False


def _job_timestamp(job: PdfExportJob, name: str) -> Optional[str]:
    """安全读取时间戳字段

    `updated_at` 使用 SQL 表达式 `onupdate=func.now()`，刚提交的 UPDATE 可能让该属性失效；
    在同步上下文里访问会触发惰性加载失败（MissingGreenlet），因此这里降级为 None 而不是抛错。
    """
    try:
        value = getattr(job, name, None)
    except Exception:  # noqa: BLE001 - 属性已过期且当前上下文无法惰性加载
        return None
    try:
        return value.isoformat() if value is not None else None
    except Exception:  # noqa: BLE001
        return None


def serialize_job(
    job: PdfExportJob, images: Optional[Sequence[PdfExportImage]] = None
) -> dict[str, Any]:
    """任务对外表示

    - `has_pdf` 检查文件是否真的存在（记录里有路径但文件被删 → False）
    - `artifact_stale` 为 True 表示：本次运行失败/取消，但**仍保留着上一次成功生成的 PDF**
      （`artifact_generation` < `run_attempt`）；前端据此提示用户下载的是旧版本
    """
    has_pdf = _artifact_file_exists(job)
    generation = int(job.output_generation or 0)
    attempt = int(job.run_attempt or 0)
    artifact_stale = bool(has_pdf and generation and attempt > generation)
    return {
        "id": job.id,
        "project_id": job.project_id,
        "status": job.status,
        "progress": int(job.progress or 0),
        "status_message": job.status_message,
        "error_message": job.error_message,
        "warnings": list(job.warnings or []),
        "options": dict(job.options or {}),
        "chapter_count": int(job.chapter_count or 0),
        "image_count": int(job.image_count or 0),
        "text_chars": int(job.text_chars or 0),
        "page_count": job.page_count,
        "file_size_bytes": job.file_size_bytes,
        "has_pdf": has_pdf,
        "artifact_stale": artifact_stale,
        "artifact_generation": generation,
        "artifact_created_at": _job_timestamp(job, "output_created_at"),
        "run_attempt": attempt,
        "created_at": _job_timestamp(job, "created_at"),
        "started_at": _job_timestamp(job, "started_at"),
        "completed_at": _job_timestamp(job, "completed_at"),
        "updated_at": _job_timestamp(job, "updated_at"),
        "images": [serialize_image(row) for row in images] if images is not None else [],
    }


class PdfExportService:
    """项目 → 单个 PDF（全本）的导出服务"""

    # ------------------------------------------------------------------ 能力与校验

    @staticmethod
    def ensure_enabled() -> None:
        if not settings.pdf_export_enabled:
            raise HTTPException(status_code=503, detail="Chức năng xuất PDF đang bị tắt trên máy chủ này")

    @staticmethod
    def ensure_ready() -> None:
        """校验依赖：ReportLab + Unicode 字体（缺一则报错，不生成乱码 PDF）"""
        PdfExportService.ensure_enabled()
        try:
            import reportlab  # noqa: F401
        except ImportError as exc:
            raise HTTPException(
                status_code=503,
                detail="Máy chủ chưa cài ReportLab nên không thể tạo PDF. Hãy chạy `pip install reportlab`.",
            ) from exc
        try:
            resolve_pdf_fonts()
        except PdfFontUnavailableError as exc:
            raise HTTPException(status_code=503, detail=sanitize_message(str(exc))) from exc

    def capabilities(self) -> dict[str, Any]:
        """实例能力（不含字体路径、密钥或任何本地目录）"""
        try:
            import reportlab  # noqa: F401

            reportlab_available = True
        except ImportError:
            reportlab_available = False
        return {
            "enabled": bool(settings.pdf_export_enabled),
            "reportlab_available": reportlab_available,
            "font_available": font_available(),
            "allowed_page_sizes": list(PAGE_SIZE_OPTIONS),
            "default_page_size": settings.pdf_default_page_size,
            "max_chapters": settings.pdf_max_chapters,
            "max_text_chars": settings.pdf_max_text_chars,
            "max_images": settings.pdf_max_images,
            "max_output_mb": settings.pdf_max_output_mb,
            "max_active_jobs": settings.pdf_max_active_jobs,
            "job_timeout_seconds": settings.pdf_job_timeout_seconds,
            "image_failure_policies": list(IMAGE_FAILURE_POLICIES),
            "default_image_failure_policy": IMAGE_FAILURE_POLICY_DEFAULT,
            "image_enabled": bool(settings.video_image_enabled),
            "default_image_provider": settings.video_image_provider or default_image_provider_name(),
            "default_image_model": settings.video_image_model,
            "image_providers": list_image_provider_capabilities(),
        }

    # ------------------------------------------------------------------ 查询辅助

    async def _load_project(self, *, db: AsyncSession, user_id: str, project_id: str) -> Project:
        if not user_id:
            raise HTTPException(status_code=401, detail="Chưa đăng nhập")
        result = await db.execute(
            select(Project).where(Project.id == project_id, Project.user_id == user_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            raise HTTPException(status_code=404, detail="Dự án không tồn tại hoặc không thuộc về bạn")
        return project

    async def _get_job(self, *, db: AsyncSession, user_id: str, job_id: str) -> PdfExportJob:
        result = await db.execute(
            select(PdfExportJob).where(
                PdfExportJob.id == job_id,
                PdfExportJob.user_id == user_id,
            )
        )
        job = result.scalar_one_or_none()
        if job is None:
            raise HTTPException(status_code=404, detail="Tác vụ xuất PDF không tồn tại")
        return job

    async def _get_images(self, *, db: AsyncSession, job_id: str) -> list[PdfExportImage]:
        result = await db.execute(
            select(PdfExportImage)
            .where(PdfExportImage.job_id == job_id)
            .order_by(PdfExportImage.chapter_number, PdfExportImage.sub_index)
        )
        return list(result.scalars().all())

    async def _load_chapters(
        self, *, db: AsyncSession, project_id: str, user_id: str
    ) -> list[Chapter]:
        """全本模式：取该项目**全部**章节（带 ownership 过滤），稳定排序

        排序：chapter_number ASC → sub_index ASC → outline_order/created_at → id（最终 tie-breaker），
        保证同一序号下的多个子章节顺序稳定、可重复。
        """
        result = await db.execute(
            select(Chapter)
            .join(Project, Project.id == Chapter.project_id)
            .where(Chapter.project_id == project_id, Project.user_id == user_id)
            .order_by(
                Chapter.chapter_number.asc(),
                Chapter.sub_index.asc(),
                Chapter.created_at.asc(),
                Chapter.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def _ensure_active_quota(
        self, *, db: AsyncSession, user_id: str, exclude_job_id: Optional[str] = None
    ) -> None:
        query = select(func.count(PdfExportJob.id)).where(
            PdfExportJob.user_id == user_id,
            PdfExportJob.status.in_(("pending", "running")),
        )
        if exclude_job_id:
            query = query.where(PdfExportJob.id != exclude_job_id)
        active = int((await db.execute(query)).scalar() or 0)
        limit = max(int(settings.pdf_max_active_jobs), 1)
        if active >= limit:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Bạn đang có {active} tác vụ xuất PDF chưa hoàn tất (giới hạn {limit}). "
                    "Vui lòng chờ hoặc hủy bớt trước khi tạo tác vụ mới."
                ),
            )

    # ------------------------------------------------------------------ 创建任务

    async def create_job(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        project_id: str,
        options: Optional[dict[str, Any]] = None,
    ) -> PdfExportJob:
        self.ensure_ready()
        project = await self._load_project(db=db, user_id=user_id, project_id=project_id)
        normalized = normalize_options(options)

        chapters = await self._load_chapters(db=db, project_id=project.id, user_id=user_id)
        if not chapters:
            raise HTTPException(status_code=400, detail="Dự án chưa có chương nào để xuất PDF")
        if len(chapters) > settings.pdf_max_chapters:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Dự án có {len(chapters)} chương, vượt giới hạn {settings.pdf_max_chapters} chương mỗi lần xuất PDF. "
                    "Hãy tách bớt nội dung hoặc tăng PDF_MAX_CHAPTERS."
                ),
            )
        total_chars = sum(len(chapter.content or "") for chapter in chapters)
        if total_chars > settings.pdf_max_text_chars:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Tổng nội dung {total_chars} ký tự vượt giới hạn {settings.pdf_max_text_chars} ký tự mỗi lần xuất PDF."
                ),
            )
        if normalized["include_images"] and len(chapters) > settings.pdf_max_images:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Cần tạo {len(chapters)} ảnh minh họa nhưng giới hạn là {settings.pdf_max_images} ảnh mỗi tác vụ. "
                    "Hãy tắt ảnh minh họa hoặc tăng PDF_MAX_IMAGES."
                ),
            )

        await self._ensure_active_quota(db=db, user_id=user_id)

        job = PdfExportJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            project_id=project.id,
            status="pending",
            progress=0,
            status_message="Đã tạo tác vụ xuất PDF, đang chờ thực thi...",
            options=normalized,
            warnings=[],
            chapter_count=len(chapters),
            text_chars=total_chars,
        )
        db.add(job)
        await db.flush()

        if normalized["include_images"]:
            for chapter in chapters:
                db.add(
                    PdfExportImage(
                        job_id=job.id,
                        chapter_id=chapter.id,
                        chapter_number=chapter.chapter_number,
                        sub_index=chapter.sub_index or 1,
                        title=chapter.title,
                        status=IMAGE_STATUS_PENDING,
                        provider=normalized["image_provider"],
                        model=normalized["image_model"],
                        size=normalized["image_size"],
                    )
                )

        # 复用后台任务面板：任务ID与导出任务ID一致，进度/取消能力开箱即用
        db.add(
            BackgroundTask(
                id=job.id,
                user_id=user_id,
                project_id=project.id,
                task_type=TASK_TYPE,
                status="pending",
                progress=0,
                status_message="Đã tạo tác vụ xuất PDF, đang chờ thực thi...",
                task_input={
                    "chapter_count": len(chapters),
                    "options": normalized,
                },
                max_retries=1,
            )
        )
        await db.commit()
        await db.refresh(job)
        await background_task_service.spawn_background_task(
            job.id, user_id, _run_pdf_export_job, job.id
        )
        logger.info("已创建 PDF 导出任务: job=%s chapters=%s", job.id[:8], len(chapters))
        return job

    # ------------------------------------------------------------------ 取消/租约/状态

    async def _apply_state(
        self,
        db: AsyncSession,
        job: PdfExportJob,
        *,
        status: Optional[str] = None,
        progress: Optional[int] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
        started: bool = False,
        completed: bool = False,
        commit: bool = True,
    ) -> None:
        """更新任务/后台任务状态；`commit=False` 时把提交交给调用方事务

        （项目删除/清理流程必须与调用方共用同一事务，避免中途提交造成半删状态。）
        """
        now = datetime.now()
        if status:
            job.status = status
        if progress is not None:
            job.progress = max(0, min(int(progress), 100))
        if message is not None:
            job.status_message = message[:500]
        if error is not None:
            job.error_message = error[:2000]
        if started:
            job.started_at = now
        if completed:
            job.completed_at = now
        job.updated_at = now

        task = await db.get(BackgroundTask, job.id)
        if task is not None:
            if status:
                task.status = status
            if progress is not None:
                task.progress = job.progress
            if message is not None:
                task.status_message = job.status_message
            if error is not None:
                task.error_message = job.error_message
            if completed:
                task.completed_at = now
            task.updated_at = now
        if commit:
            await db.commit()

    async def _start_run(self, *, db: AsyncSession, job: PdfExportJob) -> bool:
        """把任务条件性推进到 running 并分配新的运行代次

        条件 UPDATE 保证「用户刚取消的队列任务」不会被 worker 覆盖：
        只有状态仍为 pending/failed 且执行权属于自己时才成功。

        `running` 也允许启动，但**必须**是本次刚领取的令牌（stale running 被接管后要真正跑下去）；
        令牌已被别的 worker 换成新值时条件不成立，因此不会出现两个 worker 同时推进同一任务。
        """
        now = datetime.now()
        attempt = int(job.run_attempt or 0) + 1
        result = await db.execute(
            update(PdfExportJob)
            .where(
                PdfExportJob.id == job.id,
                or_(
                    and_(
                        PdfExportJob.status.in_(("pending", "failed")),
                        or_(
                            PdfExportJob.worker_token == job.worker_token,
                            PdfExportJob.worker_token.is_(None),
                        ),
                    ),
                    # 接管 stale running：只有持有本次新 token 的 worker 能重新启动
                    # （job.worker_token 为 None 时该比较恒为 NULL，不会匹配任何行）
                    and_(
                        PdfExportJob.status == "running",
                        PdfExportJob.worker_token == job.worker_token,
                    ),
                ),
            )
            .values(
                status="running",
                progress=2,
                status_message="Đang chuẩn bị dữ liệu để xuất PDF...",
                error_message=None,
                run_attempt=attempt,
                started_at=now,
                updated_at=now,
            )
        )
        await db.commit()
        if int(result.rowcount or 0) != 1:
            logger.info(
                "任务状态已被取消/接管，放弃本次执行: job=%s status=%s", job.id[:8], job.status
            )
            return False
        job.status = "running"
        job.progress = 2
        job.error_message = None
        job.run_attempt = attempt
        job.started_at = now

        task = await db.get(BackgroundTask, job.id)
        if task is not None:
            task.status = "running"
            task.progress = 2
            task.status_message = "Đang chuẩn bị dữ liệu để xuất PDF..."
            task.error_message = None
            task.updated_at = now
            await db.commit()
        return True

    async def _safe_apply_state(self, db: AsyncSession, job: PdfExportJob, **kwargs: Any) -> None:
        """终态更新容错：任务记录可能已被并发删除（项目删除/记录清理）"""
        try:
            await self._apply_state(db, job, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("更新 PDF 任务状态失败（记录可能已删除）: job=%s error=%s", job.id[:8], exc)
            with contextlib.suppress(Exception):
                await db.rollback()

    async def _safe_commit(self, db: AsyncSession, job: PdfExportJob) -> None:
        try:
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - 记录被删除/会话失效
            logger.warning("PDF 任务记录已失效，停止流水线: job=%s error=%s", job.id[:8], exc)
            with contextlib.suppress(Exception):
                await db.rollback()
            raise PdfJobCancelledError() from exc

    async def _is_cancelled(self, db: AsyncSession, job: PdfExportJob) -> bool:
        """任务是否被取消 / 被删除 / 执行权被其它 worker 接管"""
        try:
            result = await db.execute(
                select(PdfExportJob.status, PdfExportJob.worker_token).where(
                    PdfExportJob.id == job.id
                )
            )
            row = result.first()
        except Exception as exc:  # noqa: BLE001
            logger.warning("检查 PDF 任务状态失败，按已取消处理: job=%s error=%s", job.id[:8], exc)
            return True
        if row is None:
            return True
        if row[0] == "cancelled":
            return True
        owner = row[1]
        if owner and job.worker_token and owner != job.worker_token:
            logger.warning("执行权已被其它 worker 接管，停止本进程流水线: job=%s", job.id[:8])
            return True
        task_row = (
            await db.execute(
                select(BackgroundTask.cancel_requested, BackgroundTask.status).where(
                    BackgroundTask.id == job.id
                )
            )
        ).first()
        if task_row is None:
            return False
        return bool(task_row[0] or task_row[1] == "cancelled")

    def _make_cancel_checker(self, db: AsyncSession, job: PdfExportJob):
        """构造传给绘图/图片生成的取消回调（带节流）

        同一个节流出口顺带**续租**执行权：长任务（尤其构建线程）期间定期刷新 `claimed_at`，
        避免 lease 过期后被其它 worker 接管；续租失败说明执行权已易主，按取消处理。
        """
        interval = max(float(settings.pdf_cancel_poll_seconds), 0.1)
        renew_interval = max(float(settings.pdf_claim_renew_seconds), 1.0)
        state = {"checked_at": 0.0, "renewed_at": 0.0, "cancelled": False}

        async def check() -> bool:
            if state["cancelled"]:
                return True
            now = _monotonic()
            if now - state["checked_at"] < interval:
                return False
            state["checked_at"] = now
            state["cancelled"] = await self._is_cancelled(db, job)
            if state["cancelled"]:
                return True
            if now - state["renewed_at"] >= renew_interval:
                state["renewed_at"] = now
                if not await self._renew_lease(db=db, job=job):
                    logger.warning("PDF 任务执行权已易主，停止本进程流水线: job=%s", job.id[:8])
                    state["cancelled"] = True
            return state["cancelled"]

        return check

    @staticmethod
    def _lease_expiry(now: datetime) -> datetime:
        ttl = max(int(settings.pdf_job_timeout_seconds), 60) + int(settings.pdf_claim_ttl_buffer_seconds)
        return now - timedelta(seconds=ttl)

    async def _renew_lease(self, *, db: AsyncSession, job: PdfExportJob) -> bool:
        """续租执行权：只有仍是持有者（token 未被换掉）时才生效

        返回 False 表示执行权已被其它 worker 接管（或记录已删除），本进程必须停止。
        """
        token = job.worker_token
        if not token:
            return False
        now = datetime.now()
        try:
            result = await db.execute(
                update(PdfExportJob)
                .where(PdfExportJob.id == job.id, PdfExportJob.worker_token == token)
                .values(claimed_at=now, updated_at=now)
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - 记录被删除/会话失效
            logger.warning("续租 PDF 任务执行权失败: job=%s error=%s", job.id[:8], exc)
            with contextlib.suppress(Exception):
                await db.rollback()
            return False
        if int(result.rowcount or 0) != 1:
            return False
        job.claimed_at = now
        return True

    async def _still_owns_lease(self, *, db: AsyncSession, job: PdfExportJob) -> bool:
        """本进程是否仍持有执行权（被接管后不得再覆盖任务状态，否则会打断新 worker）"""
        token = job.worker_token
        if not token:
            return True
        try:
            row = (
                await db.execute(
                    select(PdfExportJob.worker_token).where(PdfExportJob.id == job.id)
                )
            ).first()
        except Exception as exc:  # noqa: BLE001 - 查询失败按不拥有处理
            logger.warning("检查 PDF 执行权归属失败: job=%s error=%s", job.id[:8], exc)
            return False
        return row is not None and row[0] == token

    async def _claim_job(self, *, db: AsyncSession, job: PdfExportJob, token: str) -> bool:
        """原子领取执行权（多 worker 安全；stale running 也允许接管）"""
        now = datetime.now()
        stale_before = self._lease_expiry(now)
        result = await db.execute(
            update(PdfExportJob)
            .where(
                PdfExportJob.id == job.id,
                or_(
                    and_(
                        PdfExportJob.status.in_(("pending", "failed")),
                        or_(
                            PdfExportJob.worker_token.is_(None),
                            PdfExportJob.claimed_at.is_(None),
                            PdfExportJob.claimed_at < stale_before,
                            PdfExportJob.worker_token == token,
                        ),
                    ),
                    and_(
                        PdfExportJob.status == "running",
                        or_(
                            PdfExportJob.claimed_at.is_(None),
                            PdfExportJob.claimed_at < stale_before,
                        ),
                    ),
                ),
            )
            .values(worker_token=token, claimed_at=now, updated_at=now)
        )
        await db.commit()
        claimed = int(result.rowcount or 0) == 1
        if claimed:
            job.worker_token = token
            job.claimed_at = now
        return claimed

    async def _release_claim(self, *, db: AsyncSession, job: PdfExportJob, token: str) -> None:
        try:
            await db.execute(
                update(PdfExportJob)
                .where(PdfExportJob.id == job.id, PdfExportJob.worker_token == token)
                .values(worker_token=None, claimed_at=None)
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("释放 PDF 任务执行权失败: job=%s error=%s", job.id[:8], exc)

    # ------------------------------------------------------------------ 后台执行

    async def run_job(self, *, job_id: str, user_id: str) -> None:
        """后台执行入口（签名与 background_task_service 约定一致）"""
        if job_id in RUNNING_JOB_IDS:
            logger.info("PDF 任务已在本进程执行中，跳过重复排队: job=%s", job_id[:8])
            return

        engine = await get_engine(user_id)
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        RUNNING_JOB_IDS.add(job_id)
        try:
            await self._run_job_with_session(
                session_factory=session_factory, job_id=job_id, user_id=user_id
            )
        finally:
            RUNNING_JOB_IDS.discard(job_id)

    async def _run_job_with_session(
        self, *, session_factory: Any, job_id: str, user_id: str
    ) -> None:
        async with session_factory() as db:
            try:
                job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
            except HTTPException:
                logger.info("PDF 任务已不存在，跳过执行: job=%s", job_id[:8])
                return
            if job.status not in ("pending", "failed", "running"):
                logger.info("跳过非等待状态的 PDF 任务: job=%s status=%s", job.id[:8], job.status)
                return

            token = uuid.uuid4().hex
            if not await self._claim_job(db=db, job=job, token=token):
                logger.info("PDF 任务已被其它 worker 领取，跳过: job=%s", job.id[:8])
                return

            try:
                await self._run_claimed_job(db=db, job=job, user_id=user_id)
            finally:
                await self._release_claim(db=db, job=job, token=token)

    async def _run_claimed_job(self, *, db: AsyncSession, job: PdfExportJob, user_id: str) -> None:
        options = dict(job.options or {})
        if not await self._start_run(db=db, job=job):
            # 队列中被取消（或被其它 worker 接管）→ 不覆盖状态、不产生任何副作用
            return
        run_attempt = int(job.run_attempt or 1)
        try:
            await self._render_pdf(db=db, job=job, user_id=user_id, options=options)
        except (PdfJobCancelledError, PdfBuildCancelled, PdfJobTimeoutError) as exc:
            # 取消/超时：**保留**上一次成功的 PDF，只清理本次构建的临时文件
            self._discard_run_temp(user_id=user_id, job_id=job.id, run_attempt=run_attempt)
            # 构建线程可能先于 worker 的取消检查结束（竞态）：`PdfBuildCancelled` 同样记为 cancelled
            cancelled = isinstance(exc, (PdfJobCancelledError, PdfBuildCancelled))
            if cancelled and not await self._still_owns_lease(db=db, job=job):
                # 执行权已被其它 worker 接管：此时写 cancelled 会把新 worker 的运行打断
                logger.warning("PDF 任务执行权已易主，不再覆盖任务状态: job=%s", job.id[:8])
                return
            await self._safe_apply_state(
                db,
                job,
                status="cancelled" if cancelled else "failed",
                message=(
                    "Tác vụ đã bị hủy"
                    if cancelled
                    else "Xuất PDF vượt quá thời gian cho phép"
                ),
                error=None if cancelled else sanitize_message(str(exc)),
                completed=True,
            )
        except HTTPException as exc:
            self._discard_run_temp(user_id=user_id, job_id=job.id, run_attempt=run_attempt)
            await self._safe_apply_state(
                db, job, status="failed", error=sanitize_message(exc.detail), completed=True
            )
        except (PdfBuildError, PdfFontUnavailableError) as exc:
            self._discard_run_temp(user_id=user_id, job_id=job.id, run_attempt=run_attempt)
            await self._safe_apply_state(
                db,
                job,
                status="failed",
                error=sanitize_message(str(exc)),
                message="Không dựng được PDF",
                completed=True,
            )
        except Exception as exc:  # noqa: BLE001 - 后台任务必须落库失败原因
            logger.error("Xuất PDF thất bại: job=%s error=%s", job.id[:8], exc, exc_info=True)
            self._discard_run_temp(user_id=user_id, job_id=job.id, run_attempt=run_attempt)
            await self._safe_apply_state(
                db,
                job,
                status="failed",
                error=sanitize_message(f"{type(exc).__name__}: {exc}"),
                message="Xuất PDF thất bại",
                completed=True,
            )

    # ------------------------------------------------------------------ 渲染流水线

    async def _render_pdf(
        self, *, db: AsyncSession, job: PdfExportJob, user_id: str, options: dict[str, Any]
    ) -> None:
        deadline = _monotonic() + max(int(settings.pdf_job_timeout_seconds), 30)
        cancel_check = self._make_cancel_checker(db, job)

        def remaining_budget() -> float:
            remaining = deadline - _monotonic()
            if remaining <= 0:
                raise PdfJobTimeoutError(
                    f"Tác vụ vượt quá thời gian cho phép {settings.pdf_job_timeout_seconds} giây"
                )
            return remaining

        workdir = job_directory(user_id, job.id)
        images_dir = workdir / IMAGES_DIRNAME

        chapters = await self._load_chapters(db=db, project_id=job.project_id, user_id=user_id)
        if not chapters:
            raise HTTPException(status_code=400, detail="Dự án chưa có chương nào để xuất PDF")

        project = await db.get(Project, job.project_id)
        warnings: list[str] = list(job.warnings or [])

        # ---------------- 1. 插图（可选） ----------------
        image_rows = await self._get_images(db=db, job_id=job.id) if options.get("include_images") else []
        image_paths: dict[str, Path] = {}
        if image_rows:
            provider = _resolve_image_provider(options.get("image_provider") or "")
            rows_by_chapter = {(row.chapter_id or ""): row for row in image_rows}
            total = len(chapters)
            for index, chapter in enumerate(chapters, start=1):
                if await cancel_check():
                    raise PdfJobCancelledError()
                remaining_budget()
                row = rows_by_chapter.get(chapter.id)
                if row is None:
                    continue
                await self._apply_state(
                    db,
                    job,
                    progress=2 + int(60 * (index - 1) / max(total, 1)),
                    message=f"Đang chuẩn bị ảnh minh họa {index}/{total}...",
                )
                prepared = await self._prepare_chapter_image(
                    db=db,
                    job=job,
                    chapter=chapter,
                    row=row,
                    provider=provider,
                    images_dir=images_dir,
                    options=options,
                    warnings=warnings,
                    cancel_check=cancel_check,
                    timeout=min(float(settings.video_image_timeout_seconds), remaining_budget()),
                )
                if prepared is not None:
                    image_paths[chapter.id] = prepared

        if await cancel_check():
            raise PdfJobCancelledError()

        # ---------------- 2. 组装章节内容 ----------------
        contents: list[PdfChapterContent] = [
            PdfChapterContent(
                number=int(chapter.chapter_number or 0),
                sub_index=int(chapter.sub_index or 1),
                title=chapter.title or "",
                content=chapter.content or "",
                image_path=image_paths.get(chapter.id),
            )
            for chapter in chapters
        ]
        text_chars = sum(len(item.content) for item in contents)

        cover_path = None
        if options.get("include_cover", True) and project is not None:
            cover_path = resolve_cover_image(project.cover_image_url, project.cover_status)
            if cover_path is not None:
                ok, reason = validate_stored_image(
                    cover_path, max_bytes=int(settings.pdf_max_output_mb) * 1024 * 1024
                )
                if not ok:
                    warnings.append(f"Ảnh bìa bị bỏ qua: {reason}")
                    cover_path = None

        meta = PdfBookMeta(
            title=options.get("title")
            or normalize_text(project.title if project else "", max_chars=200)
            or "Truyện",
            author=options.get("author") or "",
            genre=normalize_text(project.genre if project else "", max_chars=80),
            description=normalize_text(project.description if project else "", max_chars=1200),
            cover_path=cover_path,
            generated_at=datetime.now(),
            include_toc=bool(options.get("include_toc", True)),
            page_size=str(options.get("page_size") or settings.pdf_default_page_size),
        )

        await self._apply_state(
            db, job, progress=70, message="Đang dựng PDF (bìa, mục lục, chương)..."
        )
        if await cancel_check():
            raise PdfJobCancelledError()

        fonts = register_pdf_fonts()
        # 原子产物策略：先写到本次运行的临时文件，构建成功后才 replace 覆盖旧 PDF。
        # 这样重试失败/取消时，上一次成功生成的 PDF 依然可下载。
        out_path = workdir / PDF_FILENAME
        run_attempt = int(job.run_attempt or 1)
        temp_path = workdir / f"{PDF_FILENAME}.{run_attempt}.building"
        result = await self._build_pdf_in_thread(
            meta=meta,
            chapters=contents,
            out_path=temp_path,
            fonts=fonts,
            cancel_check=cancel_check,
            deadline=deadline,
        )
        warnings.extend(result.warnings)

        if result.file_size_bytes > int(settings.pdf_max_output_mb) * 1024 * 1024:
            temp_path.unlink(missing_ok=True)
            raise PdfBuildError(
                f"PDF vượt giới hạn {settings.pdf_max_output_mb}MB, hãy tắt ảnh minh họa hoặc giảm số chương"
            )

        if await cancel_check():
            temp_path.unlink(missing_ok=True)
            raise PdfJobCancelledError()

        try:
            os.replace(temp_path, out_path)
        except OSError as exc:
            temp_path.unlink(missing_ok=True)
            raise PdfBuildError("Không thể ghi tệp PDF vào thư mục tác vụ") from exc

        job.output_path = f"{user_id}/{job.id}/{PDF_FILENAME}"
        job.file_size_bytes = result.file_size_bytes
        job.page_count = result.page_count
        job.image_count = result.image_count
        job.chapter_count = result.chapter_count
        job.text_chars = text_chars
        job.warnings = warnings[:50]
        # 代次提升：产物与本次运行对齐，`artifact_stale` 随之变回 False
        job.output_generation = run_attempt
        job.output_created_at = datetime.now()
        message = "Xuất PDF hoàn tất"
        if warnings:
            message = f"Xuất PDF hoàn tất với {len(warnings)} cảnh báo"
        await self._apply_state(
            db, job, status="completed", progress=100, message=message, error=None, completed=True
        )
        logger.info(
            "PDF 导出完成: job=%s gen=%s pages=%s size=%s images=%s",
            job.id[:8],
            run_attempt,
            result.page_count,
            result.file_size_bytes,
            result.image_count,
        )

    async def _build_pdf_in_thread(
        self,
        *,
        meta: PdfBookMeta,
        chapters: Sequence[PdfChapterContent],
        out_path: Path,
        fonts,
        cancel_check,
        deadline: float,
    ):
        """在线程中构建 PDF，并允许 worker 在取消/超时时收回控制权

        `asyncio.to_thread` 无法强制中断线程，因此：
        1. 传入线程安全的取消标记（`threading.Event`），builder 会在章节/段落边界检查并抛出 `PdfBuildCancelled`
        2. 外层每 0.25 秒检查一次取消信号与墙钟；一旦触发就设置标记并给出短暂收尾时间
        3. 若线程在收尾时间内仍未结束，worker 直接抛错退出（临时文件由后续清理兜底）
        """
        stop_flag = threading.Event()

        async def _cancel_bridge() -> bool:
            if stop_flag.is_set():
                return True
            if await cancel_check():
                stop_flag.set()
                return True
            return False

        build_task = asyncio.ensure_future(
            asyncio.to_thread(
                build_story_pdf,
                meta=meta,
                chapters=chapters,
                out_path=out_path,
                fonts=fonts,
                cancel_check=stop_flag.is_set,
            )
        )
        try:
            while True:
                done, _ = await asyncio.wait({build_task}, timeout=0.25)
                if done:
                    return build_task.result()
                if await _cancel_bridge():
                    await self._await_build_thread(build_task)
                    raise PdfJobCancelledError()
                if _monotonic() >= deadline:
                    stop_flag.set()
                    await self._await_build_thread(build_task)
                    raise PdfJobTimeoutError(
                        f"Tác vụ vượt quá thời gian cho phép {settings.pdf_job_timeout_seconds} giây"
                    )
        except (PdfJobCancelledError, PdfJobTimeoutError):
            raise
        except asyncio.CancelledError:
            stop_flag.set()
            build_task.cancel()
            raise
        finally:
            stop_flag.set()

    @staticmethod
    async def _await_build_thread(build_task: asyncio.Future, *, grace: float = 5.0) -> None:
        """给构建线程一点收尾时间（builder 会在下一个检查点退出）"""
        with contextlib.suppress(Exception, asyncio.CancelledError):
            await asyncio.wait_for(asyncio.shield(build_task), timeout=grace)

    async def _prepare_chapter_image(
        self,
        *,
        db: AsyncSession,
        job: PdfExportJob,
        chapter: Chapter,
        row: PdfExportImage,
        provider,
        images_dir: Path,
        options: dict[str, Any],
        warnings: list[str],
        cancel_check,
        timeout: float,
    ) -> Optional[Path]:
        """准备一章的插图：复用 ready 图片，否则调用 image provider

        - `ready` 且文件仍有效 → 直接复用（重试不重复计费）
        - 生成失败 → 按 `image_failure_policy`：`skip` 记 warning 继续，`fail` 抛错终止
        - 取消 → 抛出 PdfJobCancelledError（任务标记 cancelled，不写 failed）
        """
        policy = str(options.get("image_failure_policy") or IMAGE_FAILURE_POLICY_DEFAULT)
        extension = output_extension(provider)
        relative = image_relative_path(
            IMAGES_DIRNAME,
            chapter_number=int(chapter.chapter_number or 0),
            sub_index=int(chapter.sub_index or 1),
            extension=extension,
        )
        out_path = images_dir / Path(relative).name

        if row.status == IMAGE_STATUS_READY and row.path:
            try:
                existing = resolve_job_file(job.user_id, job.id, row.path)
            except HTTPException:
                existing = None
            if existing is not None and existing.is_file():
                ok, reason = validate_stored_image(
                    existing, max_bytes=int(settings.video_image_max_mb) * 1024 * 1024
                )
                if ok:
                    return existing
                warnings.append(f"Ảnh minh họa chương {chapter.chapter_number} không dùng được: {reason}")
                row.status = IMAGE_STATUS_FAILED
                row.error = reason
                await self._safe_commit(db, job)
            else:
                # 记录里有路径但文件不见了 → 需要重新生成
                row.status = IMAGE_STATUS_PENDING

        if row.status not in IMAGE_RETRYABLE_STATUSES:
            # 任何非 ready 状态（含 skipped）都会重新尝试生成
            row.status = IMAGE_STATUS_PENDING

        if await cancel_check():
            raise PdfJobCancelledError()

        row.status = IMAGE_STATUS_GENERATING
        row.error = None
        await self._safe_commit(db, job)

        try:
            result = await generate_chapter_image(
                provider=provider,
                title=chapter.title or "",
                summary=chapter.summary,
                content=chapter.content,
                out_path=out_path,
                model=options.get("image_model"),
                aspect_ratio=str(options.get("image_aspect_ratio") or provider.aspect_ratios[0]),
                size=str(options.get("image_size") or provider.size_for_aspect(
                    str(options.get("image_aspect_ratio") or provider.aspect_ratios[0])
                )),
                reasoning_strength=options.get("image_reasoning_strength"),
                cancel_check=cancel_check,
                timeout=timeout,
            )
        except (ImageCancelledError, PdfJobCancelledError) as exc:
            row.status = IMAGE_STATUS_CANCELLED
            row.error = sanitize_message("Đã hủy theo yêu cầu của người dùng")
            await self._safe_commit(db, job)
            raise PdfJobCancelledError() from exc
        except PdfJobTimeoutError:
            raise
        except (
            PdfImageError,
            ImageProviderError,
            ImageRequestError,
            ImageConfigError,
            ImageTimeoutError,
        ) as exc:
            detail = image_error_detail(exc)
            row.status = IMAGE_STATUS_FAILED
            row.error = detail[:1000]
            await self._safe_commit(db, job)
            logger.warning(
                "Tạo ảnh minh họa thất bại: job=%s chapter=%s error=%s",
                job.id[:8],
                chapter.chapter_number,
                detail,
            )
            if policy == "fail":
                raise HTTPException(
                    status_code=400,
                    detail=f"Không tạo được ảnh minh họa cho chương {chapter.chapter_number}: {detail}",
                ) from exc
            warnings.append(f"Chương {chapter.chapter_number}: bỏ qua ảnh minh họa ({detail})")
            return None

        row.status = IMAGE_STATUS_READY
        row.provider = result.provider
        row.model = result.model
        row.size = result.size
        row.path = f"{IMAGES_DIRNAME}/{result.path.name}"
        row.error = None
        await self._safe_commit(db, job)
        return result.path

    # ------------------------------------------------------------------ 重试/取消/删除

    async def retry_job(self, *, db: AsyncSession, user_id: str, job_id: str) -> PdfExportJob:
        """重试：保留 `ready` 插图，只把失败/取消/未完成的插图重新排队"""
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        if job.status == "running" or job.id in RUNNING_JOB_IDS:
            raise HTTPException(
                status_code=409,
                detail="Tác vụ đang chạy, vui lòng chờ hoặc hủy trước khi thử lại",
            )
        await self._ensure_active_quota(db=db, user_id=user_id, exclude_job_id=job.id)

        images = await self._get_images(db=db, job_id=job.id)
        requeued = 0
        for row in images:
            if row.status == IMAGE_STATUS_READY and row.path:
                continue
            row.status = IMAGE_STATUS_PENDING
            row.error = None
            requeued += 1

        task = await db.get(BackgroundTask, job.id)
        if task is None:
            task = BackgroundTask(
                id=job.id,
                user_id=user_id,
                project_id=job.project_id,
                task_type=TASK_TYPE,
                status="pending",
                progress=0,
                max_retries=1,
            )
            db.add(task)
        task.cancel_requested = False
        task.error_message = None
        task.completed_at = None
        job.worker_token = None
        job.claimed_at = None
        message = "Đang chuẩn bị thử lại..."
        if requeued:
            message = f"Đang chuẩn bị thử lại ({requeued} ảnh minh họa sẽ được tạo lại)..."
        await self._apply_state(db, job, status="pending", progress=0, message=message, error=None)
        await background_task_service.spawn_background_task(
            job.id, user_id, _run_pdf_export_job, job.id
        )
        return job

    async def cancel_job(self, *, db: AsyncSession, user_id: str, job_id: str) -> PdfExportJob:
        """取消任务：条件 UPDATE，保证队列中的任务不会被 worker 覆盖回 running

        - 只有 `pending`/`running` 才能取消（终态返回 400）
        - 同时设置 `BackgroundTask.cancel_requested`，worker 的 `_is_cancelled` 会看到该标记
        - worker 侧用 `_start_run` 的条件 UPDATE 抢占启动，双保险避免竞态
        """
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        if job.status not in ("pending", "running"):
            raise HTTPException(status_code=400, detail="Tác vụ đã kết thúc, không thể hủy")

        now = datetime.now()
        result = await db.execute(
            update(PdfExportJob)
            .where(
                PdfExportJob.id == job.id,
                PdfExportJob.status.in_(("pending", "running")),
            )
            .values(
                status="cancelled",
                status_message="Tác vụ đã bị hủy",
                completed_at=now,
                updated_at=now,
            )
        )
        task = await db.get(BackgroundTask, job.id)
        if task is not None:
            task.cancel_requested = True
            task.status = "cancelled"
            task.status_message = "Tác vụ đã bị hủy"
            task.completed_at = now
            task.updated_at = now
        await db.commit()

        if int(result.rowcount or 0) != 1:
            raise HTTPException(status_code=400, detail="Tác vụ đã kết thúc, không thể hủy")
        await db.refresh(job)
        return job

    def ensure_deletable(self, job: PdfExportJob) -> None:
        if job.status in ("pending", "running"):
            raise HTTPException(
                status_code=409,
                detail="Tác vụ đang chờ hoặc đang chạy, vui lòng hủy và chờ dừng hẳn trước khi xóa",
            )
        if job.id in RUNNING_JOB_IDS:
            raise HTTPException(
                status_code=409,
                detail="Tác vụ đang dừng, vui lòng thử lại sau vài giây",
            )

    async def delete_job(self, *, db: AsyncSession, user_id: str, job_id: str) -> None:
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        self.ensure_deletable(job)
        await self._delete_job_rows(db=db, job=job)
        await db.commit()
        self._remove_job_files(user_id=job.user_id, job_id=job.id)

    async def _delete_job_rows(self, *, db: AsyncSession, job: PdfExportJob) -> None:
        """显式删除插图与后台任务映射（SQLite 默认不启用外键级联）"""
        for row in await self._get_images(db=db, job_id=job.id):
            await db.delete(row)
        task = await db.get(BackgroundTask, job.id)
        if task is not None:
            await db.delete(task)
        await db.delete(job)

    def _remove_job_files(self, *, user_id: str, job_id: str) -> None:
        """删除任务产物目录（PDF + 图片）；任务仍在运行时推迟删除"""
        workdir = job_directory_path(user_id, job_id)
        if job_id in RUNNING_JOB_IDS:
            self._schedule_deferred_cleanup(workdir, job_id)
            return
        shutil.rmtree(workdir, ignore_errors=True)

    def _schedule_deferred_cleanup(self, workdir: Path, job_id: str, *, timeout: float = 120.0) -> None:
        async def _cleanup() -> None:
            deadline = _monotonic() + timeout
            while job_id in RUNNING_JOB_IDS and _monotonic() < deadline:
                await asyncio.sleep(0.5)
            shutil.rmtree(workdir, ignore_errors=True)

        task = asyncio.ensure_future(_cleanup())
        _PENDING_CLEANUPS.add(task)
        task.add_done_callback(_PENDING_CLEANUPS.discard)

    async def _cleanup_partial_output(self, *, job: PdfExportJob, user_id: str) -> None:
        """删除本次运行的临时文件与 `.part` 残留（**不删除**已发布的 PDF 与已生成插图）"""
        self._discard_run_temp(
            user_id=user_id, job_id=job.id, run_attempt=int(job.run_attempt or 1)
        )

    def _discard_run_temp(self, *, user_id: str, job_id: str, run_attempt: int) -> None:
        """清理本次运行产生的临时 PDF（构建中的文件）与未完成的图片临时文件"""
        workdir = job_directory_path(user_id, job_id)
        for candidate in (
            workdir / f"{PDF_FILENAME}.{run_attempt}.building",
            workdir / PDF_FILENAME_PART,
        ):
            try:
                candidate.unlink(missing_ok=True)
            except OSError as exc:  # pragma: no cover - Windows 占用
                logger.warning("删除 PDF 临时文件失败: %s (%s)", candidate.name, exc)
        images_dir = workdir / IMAGES_DIRNAME
        if images_dir.is_dir():
            for leftover in images_dir.glob("*.part"):
                with contextlib.suppress(OSError):
                    leftover.unlink(missing_ok=True)

    async def delete_project_artifacts(
        self,
        *,
        db: AsyncSession,
        user_id: str,
        project_id: str,
        only_finished: bool = False,
        commit: bool = True,
    ) -> dict[str, Any]:
        """删除项目下所有 PDF 导出任务（记录 + 文件）

        与视频导出保持一致的语义，并保证 **绝不在调用方事务中提交**：
        - `commit=False`（项目删除/清理任务记录）时，所有 cancel/delete 只写入当前事务，
          由调用方在自己的事务里一起提交；提交成功后再调用 `remove_artifact_dirs` 删文件。
          这样即使后续步骤失败回滚，也不会出现「导出任务已删、项目还在」的半删状态。
        - 正在进行中的任务只做取消标记 + 状态更新，文件删除推迟到 worker 结束后执行。
        """
        jobs = list(
            (
                await db.execute(
                    select(PdfExportJob).where(
                        PdfExportJob.project_id == project_id,
                        PdfExportJob.user_id == user_id,
                    )
                )
            )
            .scalars()
            .all()
        )
        removable: list[PdfExportJob] = []
        for job in jobs:
            if only_finished and (job.status in ("pending", "running") or job.id in RUNNING_JOB_IDS):
                continue
            if job.status in ("pending", "running"):
                # 先标记取消，让仍在运行的 worker 尽快停下（记录本身会在本事务内删除）
                task = await db.get(BackgroundTask, job.id)
                if task is not None:
                    task.cancel_requested = True
                await self._apply_state(
                    db,
                    job,
                    status="cancelled",
                    message="Dự án đã bị xóa",
                    completed=True,
                    commit=False,
                )
            removable.append(job)

        targets: list[dict[str, str]] = []
        for job in removable:
            await self._delete_job_rows(db=db, job=job)
            targets.append({"user_id": user_id, "job_id": job.id})

        if commit:
            await db.commit()
            self.remove_artifact_dirs(targets)
        return {"jobs": len(removable), "targets": targets}

    def remove_artifact_dirs(self, targets: Sequence[dict[str, str]]) -> int:
        """删除产物目录（数据库提交成功后调用）"""
        removed = 0
        for target in targets:
            user_id = str(target.get("user_id") or "")
            job_id = str(target.get("job_id") or "")
            if not user_id or not job_id:
                continue
            try:
                workdir = job_directory_path(user_id, job_id)
            except ValueError:
                continue
            if job_id in RUNNING_JOB_IDS:
                self._schedule_deferred_cleanup(workdir, job_id)
                continue
            shutil.rmtree(workdir, ignore_errors=True)
            removed += 1
        return removed

    # ------------------------------------------------------------------ 下载

    async def get_output_path(
        self, *, db: AsyncSession, user_id: str, job_id: str
    ) -> tuple[PdfExportJob, Path]:
        job = await self._get_job(db=db, user_id=user_id, job_id=job_id)
        if not job.output_path:
            raise HTTPException(status_code=404, detail="Tác vụ chưa có tệp PDF để tải xuống")
        # 双重校验：路径必须以当前用户目录开头，且解析后仍在受管存储目录内（含软链接）
        if normalize_relative_path(job.output_path).split("/", 1)[0] != user_id:
            logger.warning(
                "拒绝越权的 PDF 路径: job=%s user=%s", job.id[:8], user_id
            )
            raise HTTPException(status_code=404, detail="Đường dẫn tệp không hợp lệ")
        # 相对路径包含 `{user}/{job}` 前缀，因此以存储根目录为基准解析（与视频导出一致）
        path = resolve_stored_path(pdf_storage_dir(), job.output_path)
        if not path.is_file():
            raise HTTPException(
                status_code=404, detail="Tệp PDF đã bị xóa khỏi máy chủ, vui lòng xuất lại"
            )
        return job, path


async def _run_pdf_export_job(task_id: str, user_id: str, job_id: str) -> None:
    """后台队列执行入口（函数签名与 background_task_service 约定一致）"""
    await pdf_export_service.run_job(job_id=job_id, user_id=user_id)


pdf_export_service = PdfExportService()
