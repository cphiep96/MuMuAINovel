"""
设置管理 API
"""
from fastapi import APIRouter, HTTPException, Request, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import Dict, Any, List, Optional
from pathlib import Path
from pydantic import BaseModel
from datetime import datetime
import httpx
import json
import time

from app.database import get_db
from app.models.settings import Settings
from app.services.cover_generation_service import cover_generation_service
from app.schemas.settings import (
    SettingsCreate, SettingsUpdate, SettingsResponse,
    APIKeyPreset, APIKeyPresetConfig, PresetCreateRequest,
    PresetUpdateRequest, PresetResponse, PresetListResponse,
    ChapterAnalysisPresetSelectionRequest,
    SystemSMTPSettingsResponse, SystemSMTPSettingsUpdate, SMTPTestRequest
)
from app.user_manager import User
from app.logger import get_logger, safe_preview
from app.config import settings as app_settings, PROJECT_ROOT
from app.services.ai_service import AIService, create_user_ai_service, create_user_ai_service_with_mcp, normalize_provider
from app.services.email_service import email_service
from app.security import validate_ai_http_url

logger = get_logger(__name__)
MASKED_SECRET = "********"
SETTINGS_SECRET_FIELDS = ("api_key", "cover_api_key", "tts_api_key")


def _settings_response_payload(settings: Settings) -> dict[str, Any]:
    payload = SettingsResponse.model_validate(settings).model_dump()
    for field in SETTINGS_SECRET_FIELDS:
        if payload.get(field):
            payload[field] = MASKED_SECRET
    return payload


def _preserve_masked_secrets(values: dict[str, Any]) -> None:
    for field in SETTINGS_SECRET_FIELDS:
        if values.get(field) == MASKED_SECRET:
            values.pop(field)


def _validate_tts_base_url(raw_url: Optional[str]) -> Optional[str]:
    if raw_url is None:
        return None
    clean = raw_url.strip()
    return validate_ai_http_url(clean) if clean else ""

router = APIRouter(prefix="/settings", tags=["Quản lý cài đặt"])


class CoverSettingsTestRequest(BaseModel):
    cover_api_provider: str
    cover_api_key: str
    cover_api_base_url: Optional[str] = None
    cover_image_model: str


class TTSSettingsTestRequest(BaseModel):
    tts_api_provider: str
    tts_api_key: str
    tts_api_base_url: Optional[str] = None
    tts_model: Optional[str] = None


def read_env_defaults() -> Dict[str, Any]:
    """从.env文件读取默认配置（仅读取，不修改）"""
    default_provider = (app_settings.default_ai_provider or "openai").lower().strip()
    provider_defaults = _resolve_provider_defaults(default_provider)
    return {
        "api_provider": default_provider,
        "api_key": "" if default_provider == "xiaomi_mimo" else provider_defaults["api_key"],
        "api_base_url": provider_defaults["api_base_url"],
        "llm_model": app_settings.default_model,
        "temperature": app_settings.default_temperature,
        "max_tokens": app_settings.default_max_tokens,
    }


def _normalize_raw_provider(provider: Optional[str]) -> str:
    """保留内置适配器名称，仅做大小写/空白标准化。"""
    return (provider or "openai").lower().strip()


def _resolve_provider_defaults(provider: Optional[str]) -> Dict[str, str]:
    """按 provider 解析环境变量默认配置，避免在代码中硬编码真实密钥。"""
    raw_provider = _normalize_raw_provider(provider)
    if raw_provider == "xiaomi_mimo":
        return {
            "api_key": app_settings.xiaomi_mimo_api_key or "",
            "api_base_url": app_settings.xiaomi_mimo_base_url or "https://token-plan-cn.xiaomimimo.com/v1",
        }
    if raw_provider == "anthropic":
        return {
            "api_key": app_settings.anthropic_api_key or "",
            "api_base_url": app_settings.anthropic_base_url or "",
        }
    if raw_provider == "gemini":
        return {
            "api_key": app_settings.gemini_api_key or "",
            "api_base_url": app_settings.gemini_base_url or "",
        }
    return {
        "api_key": app_settings.openai_api_key or "",
        "api_base_url": app_settings.openai_base_url or "",
    }


def _apply_provider_defaults(provider: Optional[str], api_key: Optional[str], api_base_url: Optional[str]) -> Dict[str, str]:
    """补齐内置适配器或环境变量中的 key/base_url。"""
    defaults = _resolve_provider_defaults(provider)
    return {
        "api_key": api_key or defaults["api_key"],
        "api_base_url": api_base_url or defaults["api_base_url"],
    }


def resolve_runtime_ai_config(provider: Optional[str], api_key: Optional[str], api_base_url: Optional[str]) -> Dict[str, str]:
    """在 API 层解析运行时 AI 配置。

    内置适配器（如 Xiaomi MiMo）只在数据库/前端保留 provider 标识与地址，真实 Key
    仅从后端环境变量读取；传给 AIService 时转换为底层兼容 provider（OpenAI 格式）。
    """
    raw_provider = _normalize_raw_provider(provider)
    resolved = _apply_provider_defaults(raw_provider, api_key, api_base_url)
    runtime_provider = "openai" if raw_provider == "xiaomi_mimo" else (normalize_provider(raw_provider) or "openai")
    return {
        "raw_provider": raw_provider,
        "api_provider": runtime_provider,
        "api_key": resolved["api_key"],
        "api_base_url": resolved["api_base_url"],
    }


def _safe_load_preferences(raw_preferences: Optional[str]) -> Dict[str, Any]:
    """安全解析用户偏好设置。"""
    try:
        return json.loads(raw_preferences or '{}')
    except (json.JSONDecodeError, TypeError):
        return {}


def _get_api_presets_payload(prefs: Dict[str, Any]) -> Dict[str, Any]:
    """获取API预设偏好结构。"""
    api_presets = prefs.get('api_presets')
    if not isinstance(api_presets, dict):
        api_presets = {'presets': [], 'version': '1.0'}
    if not isinstance(api_presets.get('presets'), list):
        api_presets['presets'] = []
    api_presets.setdefault('version', '1.0')
    return api_presets


def _get_chapter_analysis_preset_id(prefs: Dict[str, Any]) -> Optional[str]:
    """读取章节内容分析专用API预设ID。"""
    preset_id = prefs.get('chapter_analysis_preset_id')
    return preset_id if isinstance(preset_id, str) and preset_id.strip() else None


def _build_ai_service_from_config(
    *,
    config: Dict[str, Any],
    user_id: str,
    db: AsyncSession,
    enable_mcp: bool,
) -> AIService:
    """基于指定配置创建AI服务。"""
    resolved_config = resolve_runtime_ai_config(
        config.get('api_provider'),
        config.get('api_key'),
        config.get('api_base_url'),
    )
    return create_user_ai_service_with_mcp(
        api_provider=resolved_config["api_provider"],
        api_key=resolved_config["api_key"],
        api_base_url=resolved_config["api_base_url"],
        model_name=config.get('llm_model') or app_settings.default_model,
        temperature=config.get('temperature') if config.get('temperature') is not None else app_settings.default_temperature,
        max_tokens=config.get('max_tokens') if config.get('max_tokens') is not None else app_settings.default_max_tokens,
        user_id=user_id,
        db_session=db,
        system_prompt=config.get('system_prompt'),
        enable_mcp=enable_mcp,
    )


def require_login(request: Request):
    """依赖：要求用户已登录"""
    if not hasattr(request.state, "user") or not request.state.user:
        raise HTTPException(status_code=401, detail="Cần đăng nhập")
    return request.state.user


async def _resolve_secret_value(
    value: Optional[str],
    field: str,
    user: User,
    db: AsyncSession,
) -> str:
    if value != MASKED_SECRET:
        return value or ""
    result = await db.execute(select(Settings).where(Settings.user_id == user.user_id))
    settings = result.scalar_one_or_none()
    return str(getattr(settings, field, "") or "") if settings else ""


def require_admin(user: User = Depends(require_login)):
    """依赖：要求管理员权限"""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Chỉ quản trị viên mới truy cập được cài đặt hệ thống")
    return user


async def get_or_create_admin_settings(db: AsyncSession, user: User) -> Settings:
    """获取或创建管理员设置，系统级 SMTP 配置挂在管理员设置记录上"""
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        env_defaults = read_env_defaults()
        settings = Settings(
            user_id=user.user_id,
            smtp_provider=app_settings.SMTP_PROVIDER,
            smtp_host=app_settings.SMTP_HOST,
            smtp_port=app_settings.SMTP_PORT,
            smtp_username=app_settings.SMTP_USERNAME,
            smtp_password=app_settings.SMTP_PASSWORD,
            smtp_use_tls=app_settings.SMTP_USE_TLS,
            smtp_use_ssl=app_settings.SMTP_USE_SSL,
            smtp_from_email=app_settings.SMTP_FROM_EMAIL,
            smtp_from_name=app_settings.SMTP_FROM_NAME,
            email_auth_enabled=app_settings.EMAIL_AUTH_ENABLED,
            email_register_enabled=app_settings.EMAIL_REGISTER_ENABLED,
            verification_code_ttl_minutes=app_settings.EMAIL_VERIFICATION_CODE_TTL_MINUTES,
            verification_resend_interval_seconds=app_settings.EMAIL_VERIFICATION_RESEND_INTERVAL_SECONDS,
            **env_defaults
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    return settings


async def get_user_ai_service(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
) -> AIService:
    """
    依赖：获取当前用户的AI服务实例（支持MCP工具自动加载）
    
    从数据库读取用户设置并创建对应的AI服务。
    自动传递 user_id 和 db_session，使得 AIService 能够加载用户配置的MCP工具。
    根据用户的所有MCP插件状态决定是否启用MCP：如果有启用的插件则启用，否则禁用。
    """
    from app.models.mcp_plugin import MCPPlugin
    
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    
    if not settings:
        # 如果用户没有设置，从.env读取并保存
        env_defaults = read_env_defaults()
        settings = Settings(
            user_id=user.user_id,
            **env_defaults
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
        logger.info(f"用户 {user.user_id} 首次使用AI服务，已从.env同步设置到数据库")
    
    # 查询用户的所有MCP插件状态
    mcp_result = await db.execute(
        select(MCPPlugin).where(MCPPlugin.user_id == user.user_id)
    )
    mcp_plugins = mcp_result.scalars().all()
    
    # 检查是否有启用的MCP插件
    enable_mcp = any(plugin.enabled for plugin in mcp_plugins) if mcp_plugins else False
    
    if mcp_plugins:
        enabled_count = sum(1 for p in mcp_plugins if p.enabled)
        logger.info(f"用户 {user.user_id} 有 {len(mcp_plugins)} 个MCP插件，{enabled_count} 个启用，{enable_mcp} 决定使用MCP")
    else:
        logger.debug(f"用户 {user.user_id} 没有配置MCP插件，禁用MCP")
    
    # ✅ 使用支持MCP的工厂函数创建AI服务实例
    # 传递 user_id 和 db_session，使得 AIService 能够自动加载用户配置的MCP工具
    resolved_settings = resolve_runtime_ai_config(settings.api_provider, settings.api_key, settings.api_base_url)
    return create_user_ai_service_with_mcp(
        api_provider=resolved_settings["api_provider"],
        api_key=resolved_settings["api_key"],
        api_base_url=resolved_settings["api_base_url"],
        model_name=settings.llm_model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        user_id=user.user_id,          # ✅ 传递 user_id
        db_session=db,                 # ✅ 传递 db_session
        system_prompt=settings.system_prompt,
        enable_mcp=enable_mcp,         # 根据MCP插件状态动态决定
        disable_thinking=bool(getattr(settings, 'disable_thinking', False)),
    )


async def get_user_ai_service_from_db(user_id: str, db: AsyncSession) -> AIService:
    """
    从数据库直接创建用户AI服务实例（用于后台任务，不依赖FastAPI的Depends）
    """
    return await get_user_ai_service_from_db_by_usage(user_id, db, usage="default")


async def get_user_ai_service_from_db_by_usage(
    user_id: str,
    db: AsyncSession,
    usage: str = "default"
) -> AIService:
    """按用途创建用户AI服务实例。"""
    from app.models.mcp_plugin import MCPPlugin

    result = await db.execute(
        select(Settings).where(Settings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()

    if not settings:
        env_defaults = read_env_defaults()
        settings = Settings(user_id=user_id, **env_defaults)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)

    mcp_result = await db.execute(
        select(MCPPlugin).where(MCPPlugin.user_id == user_id)
    )
    mcp_plugins = mcp_result.scalars().all()
    enable_mcp = any(plugin.enabled for plugin in mcp_plugins) if mcp_plugins else False

    if usage == "chapter_analysis":
        prefs = _safe_load_preferences(settings.preferences)
        api_presets = _get_api_presets_payload(prefs)
        presets = api_presets.get('presets', [])
        preset_id = _get_chapter_analysis_preset_id(prefs)
        if preset_id:
            target_preset = next((p for p in presets if p.get('id') == preset_id), None)
            if target_preset and isinstance(target_preset.get('config'), dict):
                logger.info(f"用户 {user_id} 使用章节内容分析专用API预设: {target_preset.get('name')}")
                return _build_ai_service_from_config(
                    config=target_preset['config'],
                    user_id=user_id,
                    db=db,
                    enable_mcp=enable_mcp,
                )
            logger.warning(f"用户 {user_id} 配置的章节内容分析预设不存在，回退默认API配置: {preset_id}")

    resolved_settings = resolve_runtime_ai_config(settings.api_provider, settings.api_key, settings.api_base_url)
    return create_user_ai_service_with_mcp(
        api_provider=resolved_settings["api_provider"],
        api_key=resolved_settings["api_key"],
        api_base_url=resolved_settings["api_base_url"],
        model_name=settings.llm_model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        user_id=user_id,
        db_session=db,
        system_prompt=settings.system_prompt,
        enable_mcp=enable_mcp,
        disable_thinking=bool(getattr(settings, 'disable_thinking', False)),
    )


@router.get("", response_model=SettingsResponse)
async def get_settings(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    获取当前用户的设置
    如果用户没有保存过设置，自动从.env创建并保存到数据库
    """
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    
    if not settings:
        env_defaults = read_env_defaults()
        logger.info(f"用户 {user.user_id} 首次获取设置，自动从.env同步到数据库")
        settings = Settings(
            user_id=user.user_id,
            **env_defaults
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
        logger.info(f"用户 {user.user_id} 的设置已从.env同步到数据库")
    
    logger.info(f"用户 {user.user_id} 获取已保存的设置")
    return _settings_response_payload(settings)


@router.post("/cover/test")
async def test_cover_settings(
    data: CoverSettingsTestRequest,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    api_key = await _resolve_secret_value(data.cover_api_key, "cover_api_key", user, db)
    result = await cover_generation_service.test_cover_settings(
        provider=data.cover_api_provider,
        api_key=api_key,
        api_base_url=data.cover_api_base_url,
        model=data.cover_image_model,
    )
    return {
        "success": result.success,
        "message": result.message,
        "provider": result.provider,
        "model": result.model,
    }


@router.post("/tts/test")
async def test_tts_settings_endpoint(
    data: TTSSettingsTestRequest,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    from app.services.video_export.tts import test_tts_settings

    api_key = await _resolve_secret_value(data.tts_api_key, "tts_api_key", user, db)
    api_base_url = _validate_tts_base_url(data.tts_api_base_url)
    result = await test_tts_settings(
        provider=data.tts_api_provider,
        api_key=api_key,
        api_base_url=api_base_url,
        model=data.tts_model,
    )
    logger.info(
        "Người dùng %s kiểm tra TTS provider=%s success=%s",
        user.user_id,
        data.tts_api_provider,
        bool(result.get("success")),
    )
    return result




@router.get("/system/smtp", response_model=SystemSMTPSettingsResponse)
async def get_system_smtp_settings(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """获取系统 SMTP 设置（仅管理员）"""
    settings = await get_or_create_admin_settings(db, user)
    return settings


@router.put("/system/smtp", response_model=SystemSMTPSettingsResponse)
async def update_system_smtp_settings(
    data: SystemSMTPSettingsUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """更新系统 SMTP 设置（仅管理员）"""
    settings = await get_or_create_admin_settings(db, user)
    update_data = data.model_dump(exclude_unset=True)

    if update_data.get("smtp_provider") == "qq":
        update_data.setdefault("smtp_host", "smtp.qq.com")
        update_data.setdefault("smtp_port", 465)
        update_data.setdefault("smtp_use_ssl", True)
        update_data.setdefault("smtp_use_tls", False)

    if update_data.get("smtp_use_ssl") and update_data.get("smtp_use_tls"):
        raise HTTPException(status_code=400, detail="Không thể bật đồng thời SSL và TLS")

    for key, value in update_data.items():
        setattr(settings, key, value)

    await db.commit()
    await db.refresh(settings)
    logger.info(f"管理员 {user.user_id} 更新系统 SMTP 设置")
    return settings


@router.post("/system/smtp/test")
async def test_system_smtp_settings(
    data: SMTPTestRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """测试系统 SMTP 设置（真实发送测试邮件）"""
    settings = await get_or_create_admin_settings(db, user)

    if not settings.smtp_host or not settings.smtp_username or not settings.smtp_password:
        raise HTTPException(status_code=400, detail="Vui lòng hoàn thiện host SMTP, tên người dùng và mã ủy quyền trước")

    if settings.smtp_provider == "qq" and settings.smtp_host != "smtp.qq.com":
        raise HTTPException(status_code=400, detail="Host SMTP của QQ Mail phải là smtp.qq.com")

    if "@" not in data.to_email or "." not in data.to_email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Định dạng email nhận kiểm tra không đúng")

    from_email = settings.smtp_from_email or settings.smtp_username
    if not from_email:
        raise HTTPException(status_code=400, detail="Vui lòng cấu hình email người gửi hoặc tên người dùng SMTP trước")

    subject = "Email kiểm tra SMTP MuMuAINovel"
    text_body = (
        "Đây là email kiểm tra SMTP từ trang cài đặt hệ thống MuMuAINovel.\n\n"
        f"Thời gian gửi: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Nhà cung cấp SMTP: {settings.smtp_provider}\n"
        f"Máy chủ SMTP: {settings.smtp_host}:{settings.smtp_port}\n"
        "Nếu bạn nhận được email này, cấu hình SMTP hiện tại có thể gửi thư bình thường."
    )
    html_body = f"""
    <div style=\"font-family: Arial, sans-serif; line-height: 1.7; color: #1f1f1f;\">
      <h2 style=\"margin-bottom: 12px;\">Email kiểm tra SMTP MuMuAINovel</h2>
      <p>Đây là email kiểm tra SMTP từ trang cài đặt hệ thống.</p>
      <ul>
        <li><strong>Thời gian gửi:</strong>{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</li>
        <li><strong>Nhà cung cấp SMTP:</strong>{settings.smtp_provider}</li>
        <li><strong>Máy chủ SMTP:</strong>{settings.smtp_host}:{settings.smtp_port}</li>
      </ul>
      <p>Nếu bạn nhận được email này, cấu hình SMTP hiện tại có thể gửi thư bình thường.</p>
    </div>
    """

    try:
        await email_service.send_mail(
            host=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            use_tls=settings.smtp_use_tls,
            use_ssl=settings.smtp_use_ssl,
            from_email=from_email,
            from_name=settings.smtp_from_name,
            to_email=data.to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
    except Exception as exc:
        logger.exception(f"SMTP 测试邮件发送失败: {exc}")
        raise HTTPException(status_code=400, detail=f"Gửi email kiểm tra SMTP thất bại: {str(exc)}") from exc

    return {
        "success": True,
        "message": f"Đã gửi email kiểm tra tới {data.to_email}, vui lòng kiểm tra hộp thư đến và thư rác",
        "provider": settings.smtp_provider,
        "host": settings.smtp_host,
        "port": settings.smtp_port,
    }


@router.post("", response_model=SettingsResponse)
async def save_settings(
    data: SettingsCreate,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """创建或更新当前用户的设置。"""
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    settings_dict = data.model_dump(exclude_unset=True)
    _preserve_masked_secrets(settings_dict)
    if "tts_api_base_url" in settings_dict:
        settings_dict["tts_api_base_url"] = _validate_tts_base_url(settings_dict["tts_api_base_url"])

    if settings:
        for key, value in settings_dict.items():
            setattr(settings, key, value)
        try:
            prefs = json.loads(settings.preferences or '{}')
            api_presets = prefs.get('api_presets', {'presets': [], 'version': '1.0'})
            presets = api_presets.get('presets', [])
            active_preset = next((p for p in presets if p.get('is_active')), None)
            if active_preset:
                preset_config = active_preset.get('config', {})
                config_changed = (
                    preset_config.get('api_provider') != settings_dict.get('api_provider', settings.api_provider)
                    or preset_config.get('api_key') != settings_dict.get('api_key', settings.api_key)
                    or preset_config.get('api_base_url') != settings_dict.get('api_base_url', settings.api_base_url)
                    or preset_config.get('llm_model') != settings_dict.get('llm_model', settings.llm_model)
                    or preset_config.get('temperature') != settings_dict.get('temperature', settings.temperature)
                    or preset_config.get('max_tokens') != settings_dict.get('max_tokens', settings.max_tokens)
                )
                if config_changed:
                    active_preset['is_active'] = False
                    prefs['api_presets'] = api_presets
                    settings.preferences = json.dumps(prefs, ensure_ascii=False)
                    logger.info(f"用户 {user.user_id} 手动修改配置，已取消预设 {active_preset.get('name')} 的激活状态")
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"解析用户 {user.user_id} 的preferences失败: {e}")
        await db.commit()
        await db.refresh(settings)
        logger.info(f"用户 {user.user_id} 更新设置")
    else:
        settings = Settings(user_id=user.user_id, **settings_dict)
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
        logger.info(f"用户 {user.user_id} 创建设置")

    return _settings_response_payload(settings)


@router.put("", response_model=SettingsResponse)
async def update_settings(
    data: SettingsUpdate,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """更新当前用户的设置。"""
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        raise HTTPException(status_code=404, detail="Chưa có cài đặt, vui lòng tạo cài đặt trước")

    update_data = data.model_dump(exclude_unset=True)
    _preserve_masked_secrets(update_data)
    if "tts_api_base_url" in update_data:
        update_data["tts_api_base_url"] = _validate_tts_base_url(update_data["tts_api_base_url"])
    for key, value in update_data.items():
        setattr(settings, key, value)

    await db.commit()
    await db.refresh(settings)
    logger.info(f"用户 {user.user_id} 更新设置")
    return _settings_response_payload(settings)


@router.delete("")
async def delete_settings(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """删除当前用户的设置。"""
    result = await db.execute(
        select(Settings).where(Settings.user_id == user.user_id)
    )
    settings = result.scalar_one_or_none()
    if not settings:
        raise HTTPException(status_code=404, detail="Cài đặt không tồn tại")
    await db.delete(settings)
    await db.commit()
    logger.info(f"用户 {user.user_id} 删除设置")
    return {"message": "Cài đặt đã bị xóa", "user_id": user.user_id}


@router.get("/models")
async def get_available_models(
    api_key: Optional[str] = "",
    api_base_url: Optional[str] = "",
    provider: str = "openai",
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    """
    从配置的 API 获取可用的模型列表
    
    Args:
        api_key: API 密钥
        api_base_url: API 基础 URL
        provider: API 提供商 (openai, anthropic, azure, custom)
    
    Returns:
        模型列表
    """
    try:
        raw_provider = _normalize_raw_provider(provider)
        api_key = await _resolve_secret_value(api_key, "api_key", user, db)
        resolved_config = resolve_runtime_ai_config(raw_provider, api_key, api_base_url)
        provider = resolved_config["api_provider"]
        api_key = resolved_config["api_key"]
        api_base_url = validate_ai_http_url(resolved_config["api_base_url"])

        async with httpx.AsyncClient(timeout=10.0) as client:
            if provider == "openai" or provider == "azure" or provider == "custom":
                # OpenAI 兼容接口获取模型列表
                url = f"{api_base_url.rstrip('/')}/models"
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json"
                }
                
                logger.info(f"正在从 {url} 获取模型列表")
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                
                data = response.json()
                models = []
                
                if "data" in data and isinstance(data["data"], list):
                    for model in data["data"]:
                        model_id = model.get("id", "")
                        # 返回所有模型，不进行过滤
                        if model_id:
                            models.append({
                                "value": model_id,
                                "label": model_id,
                                "description": model.get("description", "") or f"Created: {model.get('created', 'N/A')}"
                            })
                
                if not models:
                    raise HTTPException(
                        status_code=404,
                        detail="Không lấy được danh sách mô hình khả dụng từ API"
                    )
                
                logger.info(f"成功获取 {len(models)} 个模型")
                return {
                    "provider": provider,
                    "models": models,
                    "count": len(models)
                }
                
            elif provider == "anthropic":
                # Anthropic models API
                url = f"{api_base_url.rstrip('/')}/v1/models"
                headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                data = response.json()
                models = [{"value": m["id"], "label": m["id"], "description": m.get("display_name", "")} for m in data.get("data", [])]
                return {"provider": provider, "models": models, "count": len(models)}
            
            elif provider == "gemini":
                # Gemini models API
                url = f"{api_base_url.rstrip('/')}/models?key={api_key}"
                response = await client.get(url)
                response.raise_for_status()
                data = response.json()
                models = []
                for m in data.get("models", []):
                    if "generateContent" in m.get("supportedGenerationMethods", []):
                        mid = m.get("name", "").replace("models/", "")
                        models.append({"value": mid, "label": m.get("displayName", mid), "description": ""})
                return {"provider": provider, "models": models, "count": len(models)}
            
            else:
                raise HTTPException(status_code=400, detail=f"Nhà cung cấp không được hỗ trợ: {provider}")
            
    except httpx.HTTPStatusError as e:
        logger.error(f"获取模型列表失败 (HTTP {e.response.status_code}): {safe_preview(e.response.text, 500)}")
        if e.response.status_code == 404:
            raise HTTPException(
                status_code=400,
                detail=f"Nhà cung cấp API này không hỗ trợ truy vấn danh sách mô hình (/models trả về 404), vui lòng nhập tên mô hình thủ công. Địa chỉ yêu cầu hiện tại: {api_base_url.rstrip('/')}/models"
            )
        raise HTTPException(
            status_code=400,
            detail=f"Không lấy được danh sách mô hình từ API (HTTP {e.response.status_code})"
        )
    except httpx.RequestError as e:
        logger.error(f"请求模型列表失败: {str(e)}")
        raise HTTPException(
            status_code=400,
            detail=f"Không thể kết nối tới API: {str(e)}"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"获取模型列表时发生错误: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Lấy danh sách mô hình thất bại: {str(e)}"
        )


class ApiTestRequest(BaseModel):
    """API 测试请求模型"""
    api_key: Optional[str] = ""
    api_base_url: Optional[str] = ""
    provider: str
    llm_model: str
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


@router.post("/check-function-calling")
async def check_function_calling_support(
    data: ApiTestRequest,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):

    """
    检查模型是否支持 Function Calling（工具调用）
    
    基于业界最佳实践的测试方法：
    1. 发送包含工具定义的请求
    2. 检查响应的 finish_reason 是否为 "tool_calls"
    3. 验证响应中是否包含有效的 tool_calls 数据
    
    Args:
        data: 包含 API 配置的请求数据
    
    Returns:
        检测结果包含支持状态、详细信息和建议
    """
    raw_provider = _normalize_raw_provider(data.provider)
    request_api_key = await _resolve_secret_value(data.api_key, "api_key", user, db)
    resolved_config = resolve_runtime_ai_config(raw_provider, request_api_key, data.api_base_url)
    api_key = resolved_config["api_key"]
    api_base_url = validate_ai_http_url(resolved_config["api_base_url"])
    provider = resolved_config["api_provider"]
    llm_model = data.llm_model

    
    try:
        start_time = time.time()
        
        from app.services.ai_clients.openai_client import is_meta_model_api

        meta_model = is_meta_model_api(api_base_url, llm_model)
        # Muse Spark luôn reasoning; token suy nghĩ tính vào max_tokens.
        # Probe 200 token → finish_reason=length, chưa kịp tool_calls.
        probe_max_tokens = 4096 if meta_model else 800
        probe_temperature = 1.0 if meta_model else 0.3
        system_prompt = (
            "You are a function-calling probe. You MUST call get_weather. "
            "Do not answer the weather from memory or in prose."
            if meta_model
            else None
        )

        test_tools = [{
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "Return current weather for the given location.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "location": {
                            "type": "string",
                            "description": "City name, e.g. Seattle"
                        }
                    },
                    "required": ["location"]
                }
            }
        }]

        test_prompt = (
            "What is the weather in Seattle right now? Use the get_weather tool."
        )

        logger.info("🧪 开始检测 Function Calling 支持")
        logger.info("  - 提供商: %s", provider)
        logger.info("  - 模型: %s", llm_model)
        logger.info("  - meta_model: %s", meta_model)
        logger.info("  - 测试工具: get_weather")
        logger.info("  - max_tokens: %s", probe_max_tokens)

        test_service = AIService(
            api_provider=provider,
            api_key=api_key,
            api_base_url=api_base_url,
            default_model=llm_model,
            default_temperature=probe_temperature,
            default_max_tokens=probe_max_tokens,
            enable_mcp=False,
            disable_thinking=False,
        )

        async def _probe() -> Any:
            return await test_service.generate_text(
                prompt=test_prompt,
                provider=provider,
                model=llm_model,
                temperature=probe_temperature,
                max_tokens=probe_max_tokens,
                system_prompt=system_prompt,
                tools=test_tools,
                tool_choice="auto",
                auto_mcp=False,
                handle_tool_calls=False,
            )

        response = await _probe()
        if meta_model and isinstance(response, dict) and not response.get("tool_calls"):
            if response.get("finish_reason") in {"length", "max_tokens", None}:
                logger.info("🔁 Muse Spark chưa gọi tool (finish_reason=%s), thử lại một lần", response.get("finish_reason"))
                response = await _probe()
        
        end_time = time.time()
        response_time = round((end_time - start_time) * 1000, 2)
        
        # 分析响应以确定是否支持 Function Calling
        supported = False
        finish_reason = None
        tool_calls = None
        response_content = None
        
        if isinstance(response, dict):
            # 检查 finish_reason（OpenAI 标准）
            finish_reason = response.get("finish_reason")
            
            # 检查是否有 tool_calls
            if "tool_calls" in response and response["tool_calls"]:
                supported = True
                tool_calls = response["tool_calls"]
                logger.info(f"✅ 检测到工具调用: {len(tool_calls)} 个")
            elif finish_reason == "tool_calls":
                supported = True
                logger.info("✅ finish_reason=tool_calls")
            elif meta_model:
                # Meta chỉ cho tool_choice=auto. Muse Spark hay hết token lúc reasoning
                # (finish_reason=length) dù API đã nhận tools — vẫn dùng được MCP.
                supported = True
                logger.info("✅ Muse Spark nhận tools thành công, coi như hỗ trợ Function Calling")
            
            # 记录返回的内容（如果有）
            if "content" in response:
                response_content = response.get("content")
        elif isinstance(response, str):
            response_content = response

        logger.info(f"  - 响应时间: {response_time}ms")
        logger.info(f"  - finish_reason: {finish_reason}")
        logger.info(f"  - 支持状态: {'✅ 支持' if supported else '❌ 不支持'}")

        result = {
            "success": True,
            "supported": supported,
            "message": "✅ Mô hình hỗ trợ Function Calling" if supported else "❌ Mô hình không hỗ trợ Function Calling",
            "response_time_ms": response_time,
            "provider": provider,
            "model": llm_model,
            "details": {
                "finish_reason": finish_reason,
                "has_tool_calls": bool(tool_calls),
                "tool_call_count": len(tool_calls) if tool_calls else 0,
                "test_tool": "get_weather",
                "test_prompt": test_prompt,
                "response_type": "tool_calls" if supported else "text"
            }
        }

        if supported:
            if tool_calls:
                result["tool_calls"] = tool_calls
            elif response_content:
                result["response_preview"] = response_content[:200]
            result["suggestions"] = [
                "✅ Mô hình này hỗ trợ Function Calling và có thể sử dụng plugin MCP bình thường",
                "Gợi ý: bật các plugin MCP cần thiết để mở rộng khả năng AI",
            ]
            if meta_model:
                result["suggestions"].append(
                    "Muse Spark dùng token để suy nghĩ trước khi gọi tool; backend đã nâng hạn mức tối thiểu khi có công cụ."
                )
        else:
            result["response_preview"] = response_content[:200] if response_content else None
            result["suggestions"] = [
                "❌ Mô hình này không hỗ trợ Function Calling nên không thể sử dụng plugin MCP",
                "Gợi ý: đổi sang mô hình hỗ trợ gọi công cụ",
                "Mô hình đề xuất: dòng GPT-4, GPT-4-turbo, Claude 3 Opus/Sonnet, Gemini 1.5 Pro, v.v.",
                "Giải thích: mô hình trả về phản hồi văn bản thay vì gọi công cụ, cho thấy mô hình không hỗ trợ tính năng này"
            ]

        return result
        
    except ValueError as e:
        error_msg = str(e)
        logger.error(f"❌ Function Calling 检测配置错误: {error_msg}")
        return {
            "success": False,
            "supported": False,
            "message": "Lỗi cấu hình",
            "error": error_msg,
            "error_type": "ConfigurationError",
            "suggestions": [
                "Vui lòng kiểm tra API Key có chính xác không",
                "Vui lòng xác nhận định dạng API Base URL có chính xác không",
                "Vui lòng xác minh nhà cung cấp đã chọn có khớp với cấu hình không"
            ]
        }
        
    except TimeoutError as e:
        error_msg = str(e)
        logger.error(f"❌ Function Calling 检测超时: {error_msg}")
        return {
            "success": False,
            "supported": None,
            "message": "Hết thời gian kiểm tra",
            "error": error_msg,
            "error_type": "TimeoutError",
            "suggestions": [
                "Vui lòng kiểm tra kết nối mạng có bình thường không",
                "Vui lòng xác nhận dịch vụ API có thể truy cập không",
                "Gợi ý: thử lại sau hoặc sử dụng môi trường mạng khác"
            ]
        }
        
    except Exception as e:
        error_msg = str(e)
        error_type = type(e).__name__
        
        logger.error(f"❌ Function Calling 检测失败: {error_msg}")
        logger.error(f"  - 错误类型: {error_type}")
        
        # 智能分析错误原因
        suggestions = []
        if "tool" in error_msg.lower() or "function" in error_msg.lower():
            suggestions = [
                "Mô hình này có thể không hỗ trợ tính năng Function Calling",
                "API trả về lỗi liên quan đến việc gọi công cụ",
                "Gợi ý: đổi sang mô hình hỗ trợ gọi công cụ hoặc liên hệ nhà cung cấp API"
            ]
        elif "unauthorized" in error_msg.lower() or "401" in error_msg:
            suggestions = [
                "Xác thực API Key thất bại",
                "Vui lòng kiểm tra API Key có chính xác và hợp lệ không",
                "Vui lòng xác nhận API Key có đủ quyền không"
            ]
        elif "not found" in error_msg.lower() or "404" in error_msg:
            suggestions = [
                "Mô hình không tồn tại hoặc không khả dụng",
                "Vui lòng kiểm tra tên mô hình có chính xác không",
                "Vui lòng xác nhận mô hình này có khả dụng trong API hiện tại không"
            ]
        else:
            suggestions = [
                "Đã gặp lỗi không xác định trong quá trình kiểm tra",
                "Gợi ý: kiểm tra tất cả tham số cấu hình có chính xác không",
                "Lưu ý: xem thông tin lỗi chi tiết để biết thêm manh mối"
            ]
        
        return {
            "success": False,
            "supported": False,
            "message": "Kiểm tra Function Calling thất bại",
            "error": error_msg,
            "error_type": error_type,
            "suggestions": suggestions
        }


@router.post("/test")
async def test_api_connection(
    data: ApiTestRequest,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):

    """
    测试 API 连接和配置是否正确
    
    Args:
        data: 包含 API 配置的请求数据（包括 temperature 和 max_tokens）
    
    Returns:
        测试结果包含状态、响应时间和详细信息
    """
    raw_provider = _normalize_raw_provider(data.provider)
    request_api_key = await _resolve_secret_value(data.api_key, "api_key", user, db)
    resolved_config = resolve_runtime_ai_config(raw_provider, request_api_key, data.api_base_url)
    api_key = resolved_config["api_key"]
    api_base_url = validate_ai_http_url(resolved_config["api_base_url"])
    provider = resolved_config["api_provider"]
    llm_model = data.llm_model
    # 使用前端传递的参数，如果未传递则使用默认值
    temperature = data.temperature if data.temperature is not None else 0.7
    max_tokens = data.max_tokens if data.max_tokens is not None else 2000
    import time
    
    try:
        start_time = time.time()
        
        # 创建临时 AI 服务实例，使用前端传递的参数
        test_service = AIService(
            api_provider=provider,
            api_key=api_key,
            api_base_url=api_base_url,
            default_model=llm_model,
            default_temperature=temperature,
            default_max_tokens=max_tokens
        )
        
        # 发送简单的测试请求
        test_prompt = "Hãy trả lời bằng một câu: kiểm tra thành công"
        
        logger.info(f"🧪 开始测试 API 连接")
        logger.info(f"  - 提供商: {provider}")
        logger.info(f"  - 模型: {llm_model}")
        logger.info(f"  - Base URL: {api_base_url}")
        logger.info(f"  - Temperature: {temperature}")
        logger.info(f"  - Max Tokens: {max_tokens}")
        
        response = await test_service.generate_text(
            prompt=test_prompt,
            provider=provider,
            model=llm_model,
            temperature=temperature,
            max_tokens=max_tokens,
            auto_mcp=False  # 测试时不加载MCP工具
        )
        
        end_time = time.time()
        response_time = round((end_time - start_time) * 1000, 2)  # 转换为毫秒
        
        logger.info(f"✅ API 测试成功")
        logger.info(f"  - 响应时间: {response_time}ms")
        
        # 安全地处理响应内容（确保是字符串）
        response_str = str(response) if response else 'N/A'
        logger.info(f"  - 响应内容长度: {len(response_str)}")
        
        return {
            "success": True,
            "message": "Kiểm tra kết nối API thành công",
            "response_time_ms": response_time,
            "provider": provider,
            "model": llm_model,
            "response_preview": response_str[:100] if len(response_str) > 100 else response_str,
            "details": {
                "api_available": True,
                "model_accessible": True,
                "response_valid": bool(response),
                "temperature": temperature,
                "max_tokens": max_tokens
            }
        }
        
    except json.JSONDecodeError as e:
        # 上游接口返回了 HTTP 成功状态，但响应体不是合法 JSON。
        error_msg = str(e)
        logger.error(f"❌ API 响应解析失败: {error_msg}")
        logger.error(f"  - 错误类型: {type(e).__name__}")
        return {
            "success": False,
            "message": "Phân tích phản hồi API thất bại",
            "error": error_msg,
            "error_type": "JSONDecodeError",
            "suggestions": [
                "Dịch vụ upstream có thể đã trả về phản hồi trống, trang lỗi HTML hoặc JSON không tương thích với OpenAI",
                "Vui lòng xem lỗi phân tích JSON phản hồi HTTP của AI trong nhật ký backend và xác nhận status, content-type cùng body_preview",
                "Vui lòng xác nhận API Base URL có trỏ đến đúng endpoint /v1 tương thích OpenAI không"
            ]
        }

    except ValueError as e:
        # 配置错误
        error_msg = str(e)
        logger.error(f"❌ API 配置错误: {error_msg}")
        return {
            "success": False,
            "message": "Lỗi cấu hình API",
            "error": error_msg,
            "error_type": "ConfigurationError",
            "suggestions": [
                "Vui lòng kiểm tra API Key có chính xác không",
                "Vui lòng xác nhận định dạng API Base URL chính xác",
                "Vui lòng xác minh nhà cung cấp đã chọn có khớp không"
            ]
        }
        
    except TimeoutError as e:
        # 超时错误
        error_msg = str(e)
        logger.error(f"❌ API 请求超时: {error_msg}")
        return {
            "success": False,
            "message": "Yêu cầu API hết thời gian",
            "error": error_msg,
            "error_type": "TimeoutError",
            "suggestions": [
                "Vui lòng kiểm tra kết nối mạng",
                "Vui lòng xác nhận API Base URL có thể truy cập không",
                "Nếu sử dụng proxy, vui lòng kiểm tra cài đặt proxy"
            ]
        }
        
    except Exception as e:
        # 其他错误
        error_msg = str(e)
        error_type = type(e).__name__
        
        logger.error(f"❌ API 测试失败: {error_msg}")
        logger.error(f"  - 错误类型: {error_type}")
        
        # 分析错误原因并提供建议
        suggestions = []
        if "blocked" in error_msg.lower():
            suggestions = [
                "Yêu cầu bị nhà cung cấp API chặn",
                "Nguyên nhân có thể: API Key bị hạn chế hoặc bị giới hạn theo khu vực",
                "Gợi ý: kiểm tra trạng thái API Key và số dư tài khoản",
                "Gợi ý: thử đổi API Base URL hoặc sử dụng proxy"
            ]
        elif "unauthorized" in error_msg.lower() or "401" in error_msg:
            suggestions = [
                "Xác thực API Key thất bại",
                "Gợi ý: kiểm tra API Key có chính xác không",
                "Gợi ý: xác nhận API Key có hết hạn không"
            ]
        elif "not found" in error_msg.lower() or "404" in error_msg:
            suggestions = [
                "Endpoint API không tồn tại hoặc mô hình không khả dụng",
                "Gợi ý: kiểm tra API Base URL có chính xác không",
                "Gợi ý: xác nhận tên mô hình có chính xác không"
            ]
        elif "rate limit" in error_msg.lower() or "429" in error_msg:
            suggestions = [
                "Vượt quá tần suất yêu cầu API",
                "Gợi ý: thử lại sau",
                "Gợi ý: nâng cấp gói API"
            ]
        elif "insufficient" in error_msg.lower() or "quota" in error_msg.lower():
            suggestions = [
                "Hạn ngạch API không đủ",
                "Gợi ý: kiểm tra số dư tài khoản",
                "Gợi ý: nạp tiền hoặc nâng cấp gói"
            ]
        else:
            suggestions = [
                "Vui lòng kiểm tra tất cả tham số cấu hình có chính xác không",
                "Vui lòng xác nhận kết nối mạng bình thường",
                "Vui lòng xem thông tin lỗi chi tiết"
            ]
        
        return {
            "success": False,
            "message": "Kiểm tra API thất bại",
            "error": error_msg,
            "error_type": error_type,
            "suggestions": suggestions
        }


# ========== API配置预设管理（零数据库改动方案）==========

async def get_user_settings(user_id: str, db: AsyncSession) -> Settings:
    """获取用户settings，如果不存在则创建"""
    result = await db.execute(
        select(Settings).where(Settings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    
    if not settings:
        # 创建默认设置
        env_defaults = read_env_defaults()
        settings = Settings(
            user_id=user_id,
            **env_defaults,
            preferences='{}'  # 初始化为空JSON
        )
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
        logger.info(f"用户 {user_id} 首次访问，已创建默认设置")
    
    return settings


@router.get("/presets", response_model=PresetListResponse)
async def get_presets(
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    获取所有API配置预设
    
    从preferences字段读取预设列表
    """
    settings = await get_user_settings(user.user_id, db)
    
    # 解析preferences
    try:
        prefs = json.loads(settings.preferences or '{}')
    except json.JSONDecodeError:
        logger.warning(f"用户 {user.user_id} 的preferences字段JSON格式错误，重置为空")
        prefs = {}
    
    api_presets = _get_api_presets_payload(prefs)
    presets = api_presets.get('presets', [])
    chapter_analysis_preset_id = _get_chapter_analysis_preset_id(prefs)
    if chapter_analysis_preset_id and not any(p.get('id') == chapter_analysis_preset_id for p in presets):
        chapter_analysis_preset_id = None
    
    # 找到激活的预设
    active_preset_id = next(
        (p['id'] for p in presets if p.get('is_active')),
        None
    )
    
    logger.info(f"用户 {user.user_id} 获取预设列表，共 {len(presets)} 个")
    
    return {
        "presets": presets,
        "total": len(presets),
        "active_preset_id": active_preset_id,
        "chapter_analysis_preset_id": chapter_analysis_preset_id
    }


@router.post("/presets", response_model=PresetResponse)
async def create_preset(
    data: PresetCreateRequest,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    创建新预设
    
    将预设添加到preferences字段的JSON中
    """
    settings = await get_user_settings(user.user_id, db)
    
    # 解析preferences
    try:
        prefs = json.loads(settings.preferences or '{}')
    except json.JSONDecodeError:
        prefs = {}
    
    api_presets = prefs.get('api_presets', {'presets': [], 'version': '1.0'})
    presets = api_presets.get('presets', [])
    
    # 创建新预设
    new_preset = {
        "id": f"preset_{int(datetime.now().timestamp() * 1000)}",
        "name": data.name,
        "description": data.description,
        "is_active": False,
        "created_at": datetime.now().isoformat(),
        "config": {
            **data.config.model_dump(),
            "api_provider": _normalize_raw_provider(data.config.api_provider)
        }
    }
    
    presets.append(new_preset)
    
    # 保存回preferences
    api_presets['presets'] = presets
    prefs['api_presets'] = api_presets
    settings.preferences = json.dumps(prefs, ensure_ascii=False)
    
    await db.commit()
    
    logger.info(f"用户 {user.user_id} 创建预设: {data.name}")
    return new_preset


@router.put("/presets/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: str,
    data: PresetUpdateRequest,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    更新预设
    
    在preferences字段的JSON中更新指定预设
    """
    settings = await get_user_settings(user.user_id, db)
    
    # 解析preferences
    try:
        prefs = json.loads(settings.preferences or '{}')
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Lỗi định dạng dữ liệu cấu hình")
    
    api_presets = prefs.get('api_presets', {'presets': [], 'version': '1.0'})
    presets = api_presets.get('presets', [])
    
    # 找到并更新预设
    target_preset = next((p for p in presets if p['id'] == preset_id), None)
    if not target_preset:
        raise HTTPException(status_code=404, detail="Cấu hình sẵn không tồn tại")
    
    # 更新字段
    if data.name is not None:
        target_preset['name'] = data.name
    if data.description is not None:
        target_preset['description'] = data.description
    if data.config is not None:
        target_preset['config'] = {
            **data.config.model_dump(),
            'api_provider': _normalize_raw_provider(data.config.api_provider)
        }
    
    # 保存回preferences
    prefs['api_presets'] = api_presets
    settings.preferences = json.dumps(prefs, ensure_ascii=False)
    
    await db.commit()
    
    logger.info(f"用户 {user.user_id} 更新预设: {preset_id}")
    return target_preset


@router.delete("/presets/{preset_id}")
async def delete_preset(
    preset_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    删除预设
    
    从preferences字段的JSON中删除指定预设
    """
    settings = await get_user_settings(user.user_id, db)
    
    # 解析preferences
    try:
        prefs = json.loads(settings.preferences or '{}')
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Lỗi định dạng dữ liệu cấu hình")
    
    api_presets = _get_api_presets_payload(prefs)
    presets = api_presets.get('presets', [])
    
    # 找到预设
    target_preset = next((p for p in presets if p['id'] == preset_id), None)
    if not target_preset:
        raise HTTPException(status_code=404, detail="Cấu hình sẵn không tồn tại")
    
    # 检查是否是激活的预设
    if target_preset.get('is_active'):
        raise HTTPException(status_code=400, detail="Không thể xóa cấu hình sẵn đang kích hoạt, vui lòng kích hoạt cấu hình khác trước")
    
    # 删除预设
    presets = [p for p in presets if p['id'] != preset_id]
    if prefs.get('chapter_analysis_preset_id') == preset_id:
        prefs.pop('chapter_analysis_preset_id', None)
    
    # 保存回preferences
    api_presets['presets'] = presets
    prefs['api_presets'] = api_presets
    settings.preferences = json.dumps(prefs, ensure_ascii=False)
    
    await db.commit()
    
    logger.info(f"用户 {user.user_id} 删除预设: {preset_id}")
    return {"message": "Cấu hình sẵn đã bị xóa", "preset_id": preset_id}


@router.post("/presets/{preset_id}/activate")
async def activate_preset(
    preset_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    激活预设
    
    将预设的配置应用到Settings主字段
    """
    settings = await get_user_settings(user.user_id, db)
    
    # 解析preferences
    try:
        prefs = json.loads(settings.preferences or '{}')
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Lỗi định dạng dữ liệu cấu hình")
    
    api_presets = prefs.get('api_presets', {'presets': [], 'version': '1.0'})
    presets = api_presets.get('presets', [])
    
    # 找到目标预设
    target_preset = next((p for p in presets if p['id'] == preset_id), None)
    if not target_preset:
        raise HTTPException(status_code=404, detail="Cấu hình sẵn không tồn tại")
    
    # 应用配置到Settings主字段
    config = target_preset['config']
    resolved_config = _apply_provider_defaults(config.get('api_provider'), config.get('api_key'), config.get('api_base_url'))
    settings.api_provider = _normalize_raw_provider(config['api_provider'])
    settings.api_key = config.get('api_key') or ""
    settings.api_base_url = resolved_config["api_base_url"]
    settings.llm_model = config['llm_model']
    settings.temperature = config['temperature']
    settings.max_tokens = config['max_tokens']
    settings.system_prompt = config.get('system_prompt')
    
    # 更新所有预设的is_active状态
    for preset in presets:
        preset['is_active'] = (preset['id'] == preset_id)
    
    # 保存回preferences
    prefs['api_presets'] = api_presets
    settings.preferences = json.dumps(prefs, ensure_ascii=False)
    
    await db.commit()
    
    logger.info(f"用户 {user.user_id} 激活预设: {target_preset['name']}")
    return {
        "message": "Cấu hình sẵn đã được kích hoạt",
        "preset_id": preset_id,
        "preset_name": target_preset['name']
    }


@router.put("/presets/usage/chapter-analysis")
async def set_chapter_analysis_preset_selection(
    data: ChapterAnalysisPresetSelectionRequest,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """设置章节内容分析专用API预设；为空则使用默认API配置。"""
    settings = await get_user_settings(user.user_id, db)
    prefs = _safe_load_preferences(settings.preferences)
    api_presets = _get_api_presets_payload(prefs)
    presets = api_presets.get('presets', [])

    preset_id = data.preset_id.strip() if data.preset_id else None
    preset_name = None
    if preset_id:
        target_preset = next((p for p in presets if p.get('id') == preset_id), None)
        if not target_preset:
            raise HTTPException(status_code=404, detail="Cấu hình sẵn không tồn tại")
        prefs['chapter_analysis_preset_id'] = preset_id
        preset_name = target_preset.get('name')
    else:
        prefs.pop('chapter_analysis_preset_id', None)

    prefs['api_presets'] = api_presets
    settings.preferences = json.dumps(prefs, ensure_ascii=False)
    await db.commit()

    logger.info(f"用户 {user.user_id} 设置章节内容分析API预设: {preset_id or '默认配置'}")
    return {
        "message": "Đã cập nhật cấu hình API phân tích nội dung chương",
        "chapter_analysis_preset_id": preset_id,
        "preset_name": preset_name
    }


@router.post("/presets/{preset_id}/test")
async def test_preset(
    preset_id: str,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    测试预设的API连接
    """
    settings = await get_user_settings(user.user_id, db)
    
    # 解析preferences
    try:
        prefs = json.loads(settings.preferences or '{}')
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Lỗi định dạng dữ liệu cấu hình")
    
    api_presets = prefs.get('api_presets', {'presets': [], 'version': '1.0'})
    presets = api_presets.get('presets', [])
    
    # 找到预设
    target_preset = next((p for p in presets if p['id'] == preset_id), None)
    if not target_preset:
        raise HTTPException(status_code=404, detail="Cấu hình sẵn không tồn tại")
    
    # 使用现有的test_api_connection逻辑
    # 确保传递完整参数，与当前配置测试保持一致
    config = target_preset['config']
    test_request = ApiTestRequest(
        api_key=config['api_key'],
        api_base_url=config.get('api_base_url', ''),
        provider=config['api_provider'],
        llm_model=config['llm_model'],
        temperature=config.get('temperature'),   # 使用预设中的温度参数
        max_tokens=config.get('max_tokens')      # 使用预设中的最大tokens参数
    )
    
    logger.info(f"用户 {user.user_id} 测试预设: {target_preset['name']}")
    return await test_api_connection(test_request)


@router.post("/presets/from-current", response_model=PresetResponse)
async def create_preset_from_current(
    name: str,
    description: Optional[str] = None,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db)
):
    """
    从当前配置创建新预设
    
    快捷方式：将当前激活的配置保存为新预设
    """
    settings = await get_user_settings(user.user_id, db)
    
    # 从当前Settings主字段读取配置
    current_config = APIKeyPresetConfig(
        api_provider=_normalize_raw_provider(settings.api_provider),
        api_key=settings.api_key,
        api_base_url=settings.api_base_url,
        llm_model=settings.llm_model,
        temperature=settings.temperature,
        max_tokens=settings.max_tokens,
        system_prompt=settings.system_prompt
    )
    
    # 创建预设
    create_request = PresetCreateRequest(
        name=name,
        description=description,
        config=current_config
    )
    
    logger.info(f"用户 {user.user_id} 从当前配置创建预设: {name}")
    return await create_preset(create_request, user, db)
