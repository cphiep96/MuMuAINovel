"""FastAPI应用主入口"""
from fastapi import FastAPI, Request, status, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, FileResponse
from fastapi.exceptions import RequestValidationError
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
import mimetypes
import sys

from app.config import settings as config_settings
from app.database import close_db, _session_stats
from app.logger import setup_logging, get_logger
from app.middleware import RequestIDMiddleware
from app.middleware.auth_middleware import AuthMiddleware
from app.mcp import mcp_client, register_status_sync

setup_logging(
    level=config_settings.log_level,
    log_to_file=config_settings.log_to_file,
    log_file_path=config_settings.log_file_path,
    max_bytes=config_settings.log_max_bytes,
    backup_count=config_settings.log_backup_count,
    message_max_chars=config_settings.log_message_max_chars,
)
logger = get_logger(__name__)


# 不依赖 Windows 注册表，确保前端模块脚本始终返回正确的 MIME 类型。
STATIC_MIME_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".wasm": "application/wasm",
}

for _suffix, _media_type in STATIC_MIME_TYPES.items():
    mimetypes.add_type(_media_type, _suffix, strict=True)


def get_static_media_type(path: Path) -> str:
    """返回稳定的静态文件 MIME 类型，避免未知类型退回 text/plain。"""
    return (
        STATIC_MIME_TYPES.get(path.suffix.lower())
        or mimetypes.guess_type(path.name)[0]
        or "application/octet-stream"
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 注册MCP状态同步服务
    register_status_sync()

    # 安全保障：确保后台任务表存在（兼容未执行Alembic迁移的旧部署）
    try:
        from app.database import get_engine
        from app.models.background_task import BackgroundTask
        from app.models.batch_generation_task import BatchGenerationTask
        from app.models.analysis_task import AnalysisTask
        from sqlalchemy import update as sql_update
        _startup_engine = await get_engine("system")
        async with _startup_engine.begin() as conn:
            # 仅创建 background_tasks 表（如果不存在），不影响其他表
            await conn.run_sync(
                lambda sync_conn: BackgroundTask.__table__.create(sync_conn, checkfirst=True)
            )
            # 视频导出表兜底创建：补建缺失的表与转场新增列，不修改既有列
            # （Alembic 仍是结构唯一来源；新增的迁移脚本已做幂等处理，可与此兜底共存）
            from app.services.video_export.schema import sync_video_export_schema

            await conn.run_sync(sync_video_export_schema)

            # PDF 导出表兜底创建（同样只补缺失的表/可空列）
            from app.services.pdf_export.schema import sync_pdf_export_schema

            await conn.run_sync(sync_pdf_export_schema)

            from app.services.settings_schema import sync_settings_schema

            await conn.run_sync(sync_settings_schema)
            interrupted_at = datetime.now()
            await conn.execute(
                sql_update(BackgroundTask)
                .where(BackgroundTask.status.in_(["pending", "running"]))
                .values(
                    status="failed",
                    error_message="Dịch vụ khởi động lại, tác vụ nền đã bị gián đoạn",
                    status_message="Dịch vụ khởi động lại, tác vụ đã bị gián đoạn, vui lòng khởi tạo lại",
                    completed_at=interrupted_at,
                    updated_at=interrupted_at,
                )
            )
            await conn.execute(
                sql_update(BatchGenerationTask)
                .where(BatchGenerationTask.status.in_(["pending", "running"]))
                .values(
                    status="failed",
                    error_message="Dịch vụ khởi động lại, tác vụ tạo hàng loạt đã bị gián đoạn",
                    completed_at=interrupted_at,
                )
            )
            await conn.execute(
                sql_update(AnalysisTask)
                .where(AnalysisTask.status.in_(["pending", "running"]))
                .values(
                    status="failed",
                    error_message="Dịch vụ khởi động lại, tác vụ phân tích chương đã bị gián đoạn",
                    progress=0,
                    completed_at=interrupted_at,
                )
            )
            # 视频导出任务：标记失败并释放执行权（worker_token/claimed_at=None），
            # 但刻意保留分镜的 motion_operation_id/motion_status，重试时可继续轮询已提交的远端操作。
            # 实现放在 services/video_export/startup.py 便于单测覆盖。
            from app.services.video_export.startup import fail_interrupted_jobs

            await fail_interrupted_jobs(conn, interrupted_at=interrupted_at)

            # PDF 导出任务：同样收敛为失败并释放执行权（已生成的插图会被保留，重试时复用）
            from app.services.pdf_export.startup import (
                fail_interrupted_jobs as fail_interrupted_pdf_jobs,
            )

            await fail_interrupted_pdf_jobs(conn, interrupted_at=interrupted_at)
        logger.info("后台任务表检查完成")
    except Exception as e:
        logger.warning(f"后台任务表检查失败（不影响启动）: {e}")

    logger.info("应用启动完成")
    
    yield
    
    # 清理MCP插件
    await mcp_client.cleanup()
    
    # 清理HTTP客户端池
    from app.services.ai_service import cleanup_http_clients
    await cleanup_http_clients()
    
    # 关闭数据库连接
    await close_db()
    
    logger.info("应用已关闭")


app = FastAPI(
    title=config_settings.app_name,
    version=config_settings.app_version,
    description="Công cụ AI viết tiểu thuyết - Trợ lý sáng tác thông minh",
    lifespan=lifespan
)

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求验证错误"""
    logger.error(f"请求验证失败: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": "Xác thực tham số yêu cầu thất bại",
            "errors": exc.errors()
        }
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """处理所有未捕获的异常"""
    logger.error(f"未处理的异常: {type(exc).__name__}: {str(exc)}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Lỗi nội bộ máy chủ",
            "message": str(exc) if config_settings.debug else "Vui lòng thử lại sau"
        }
    )

app.add_middleware(RequestIDMiddleware)
app.add_middleware(AuthMiddleware)

if config_settings.debug:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=config_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "ok"}


@app.get("/health/db-sessions")
async def db_session_stats(request: Request):
    """
    Thống kê phiên database (theo dõi rò rỉ kết nối)
    
    Trả về:
    - created: Tổng số phiên đã tạo
    - closed: Tổng số phiên đã đóng
    - active: Số phiên đang hoạt động (nên gần 0)
    - errors: Số lần lỗi
    - generator_exits: Số lần SSE ngắt kết nối
    - last_check: Thời điểm kiểm tra gần nhất
    """
    if not getattr(request.state, "is_admin", False):
        raise HTTPException(status_code=403, detail="Cần quyền quản trị viên")
    return {
        "status": "ok",
        "session_stats": _session_stats,
        "warning": "Số phiên hoạt động quá nhiều" if _session_stats["active"] > 10 else None
    }


from app.api import (
    projects, outlines, outline_transfer, characters, chapters,
    wizard_stream, relationships, organizations,
    auth, users, settings, writing_styles, memories,
    mcp_plugins, admin, inspiration, prompt_templates,
    changelog, careers, foreshadows, prompt_workshop, book_import,
    project_covers, project_agent, tasks, skills, announcements,
    video_export, pdf_export
)

app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(admin.router, prefix="/api")

app.include_router(projects.router, prefix="/api")
app.include_router(project_covers.router, prefix="/api")
app.include_router(project_agent.router, prefix="/api")
app.include_router(wizard_stream.router, prefix="/api")
app.include_router(inspiration.router, prefix="/api")
app.include_router(outlines.router, prefix="/api")
app.include_router(outline_transfer.router, prefix="/api")
app.include_router(characters.router, prefix="/api")
app.include_router(careers.router, prefix="/api")  # API quản lý nghề nghiệp
app.include_router(chapters.router, prefix="/api")
app.include_router(relationships.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(writing_styles.router, prefix="/api")
app.include_router(memories.router)  # 记忆管理API (已包含/api前缀)
app.include_router(foreshadows.router)  # 伏笔管理API (已包含/api前缀)
app.include_router(mcp_plugins.router, prefix="/api")  # API quản lý plugin MCP
app.include_router(prompt_templates.router, prefix="/api")  # API quản lý template prompt
app.include_router(changelog.router, prefix="/api")  # API nhật ký cập nhật
app.include_router(skills.router)  # Skill API（已包含/api前缀）
app.include_router(prompt_workshop.router, prefix="/api")  # API xưởng prompt
app.include_router(book_import.router, prefix="/api")  # API nhập/đọc tách sách
app.include_router(tasks.router, prefix="/api")  # API tác vụ nền
app.include_router(video_export.router, prefix="/api")  # API xuất phim từ chương
app.include_router(pdf_export.router, prefix="/api")  # API xuất PDF full truyện
app.include_router(announcements.router, prefix="/api")  # API thông báo

if getattr(sys, "frozen", False):
    static_dir = Path(sys._MEIPASS) / "backend" / "static"
    generated_assets_root_dir = Path(sys.executable).parent / "storage"
else:
    static_dir = Path(__file__).parent.parent / "static"
    generated_assets_root_dir = Path(__file__).parent.parent / "storage"
generated_covers_dir = generated_assets_root_dir / "generated_covers"
generated_covers_dir.mkdir(parents=True, exist_ok=True)
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(static_dir / "assets")), name="assets")
    app.mount("/generated-assets/covers", StaticFiles(directory=str(generated_covers_dir)), name="generated-covers")
    
    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        """服务单页应用，所有非API路径返回index.html"""
        if full_path.startswith("api/"):
            return JSONResponse(
                status_code=404,
                content={"detail": "Đường dẫn API không tồn tại"}
            )
        
        file_path = static_dir / full_path
        try:
            resolved_file = file_path.resolve()
            resolved_static = static_dir.resolve()
            resolved_file.relative_to(resolved_static)
        except ValueError:
            return JSONResponse(
                status_code=404,
                content={"detail": "Trang không tồn tại"}
            )

        if resolved_file.is_file():
            return FileResponse(
                resolved_file,
                media_type=get_static_media_type(resolved_file),
                headers={"Cache-Control": "no-cache"} if resolved_file.suffix == ".html" else None,
            )
        
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file, headers={"Cache-Control": "no-cache"})
        
        return JSONResponse(
            status_code=404,
            content={"detail": "Trang không tồn tại"}
        )
else:
    logger.warning("静态文件目录不存在，请先构建前端: cd frontend && npm run build")
    
    @app.get("/")
    async def root():
        return {
            "message": "Chào mừng sử dụng MuMuAINovel",
            "version": config_settings.app_version,
            "docs": "/docs",
            "notice": "Vui lòng build frontend trước: cd frontend && npm run build"
        }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=config_settings.app_host,
        port=config_settings.app_port,
        reload=config_settings.debug
    )
