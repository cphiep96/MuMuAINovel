"""应用配置管理"""
from pydantic_settings import BaseSettings
from typing import Optional
from pathlib import Path
import logging
import os
import uuid

# 获取项目根目录(从backend/app/config.py向上两级)
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# 配置模块使用标准logging（在logger.py初始化之前）
config_logger = logging.getLogger(__name__)

# 数据库配置：PostgreSQL
# 从环境变量获取数据库URL
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://mumuai:password@localhost:5432/mumuai_novel")

config_logger.debug(f"Loại cơ sở dữ liệu: PostgreSQL")
config_logger.debug(f"URL cơ sở dữ liệu: {DATABASE_URL}")

class Settings(BaseSettings):
    """应用配置"""
    
    # 应用配置
    app_name: str = "MuMuAINovel"
    app_version: str = "1.5.4"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False
    
    # 日志配置
    log_level: str = "INFO"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    log_to_file: bool = True  # 是否输出到文件
    log_file_path: str = str(PROJECT_ROOT / "logs" / "app.log")
    log_max_bytes: int = 10 * 1024 * 1024  # 10MB
    log_backup_count: int = 30  # 保留30个备份文件
    log_message_max_chars: int = 2000  # 单条日志消息最大字符数
    
    # CORS配置
    cors_origins: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]
    
    # 数据库配置 - PostgreSQL
    database_url: str = DATABASE_URL
    
    # PostgreSQL连接池配置（优化后支持150-200并发用户）
    database_pool_size: int = 50  # 核心连接池大小（优化：从30提升到50）
    database_max_overflow: int = 30  # 最大溢出连接数（优化：从20提升到30）
    database_pool_timeout: int = 90  # 连接池超时秒数（优化：从60提升到90）
    database_pool_recycle: int = 1800  # 连接回收时间秒数（30分钟，防止长时间连接失效）
    database_pool_pre_ping: bool = True  # 连接前ping检测，确保连接有效
    database_pool_use_lifo: bool = True  # 使用LIFO策略提高连接复用率
    
    # 连接池高级配置
    database_echo_pool: bool = False  # 是否记录连接池日志（调试用）
    database_pool_reset_on_return: str = "rollback"  # Chiến lược reset khi trả kết nối: rollback/commit/none
    database_max_identifier_length: int = 128  # PostgreSQL标识符最大长度
    
    # 会话监控配置
    database_session_max_active: int = 50  # 活跃会话警告阈值（从100降低到50）
    database_session_leak_threshold: int = 100  # 会话泄漏严重告警阈值
    
    # 数据库监控配置
    database_enable_slow_query_log: bool = True  # 启用慢查询日志
    database_slow_query_threshold: float = 1.0  # 慢查询阈值（秒）
    database_enable_metrics: bool = True  # 启用性能指标收集
    
    # AI服务配置
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    xiaomi_mimo_api_key: Optional[str] = None
    xiaomi_mimo_base_url: str = "https://token-plan-cn.xiaomimimo.com/v1"
    gemini_api_key: Optional[str] = None
    gemini_base_url: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    default_ai_provider: str = "openai"
    default_model: str = "gpt-4"
    default_temperature: float = 0.7
    default_max_tokens: int = 32000
    # Allow Ollama / local Llama / Docker host.docker.internal as AI base URLs.
    # Default false keeps SSRF protection for public deployments.
    allow_private_ai_endpoints: bool = False
    # Comma-separated host allowlist, e.g. "host.docker.internal,127.0.0.1"
    allowed_ai_hosts: str = ""
    
    # MCP配置
    mcp_max_rounds: int = 3  # MCP工具调用最大轮数（全局统一控制）
    
    # LinuxDO OAuth2 配置
    LINUXDO_CLIENT_ID: Optional[str] = None
    LINUXDO_CLIENT_SECRET: Optional[str] = None
    # 回调地址：Docker部署时必须使用实际域名或服务器IP，不能使用localhost
    # 本地开发: http://localhost:8000/api/auth/callback
    # 生产环境: https://your-domain.com/api/auth/callback 或 http://your-ip:8000/api/auth/callback
    LINUXDO_REDIRECT_URI: Optional[str] = None
    # LinuxDO 专用代理配置（仅用于 OAuth token 与用户信息请求，不影响 AI/SMTP/其他请求）
    # 示例: http://127.0.0.1:7890
    LINUXDO_PROXY_URL: Optional[str] = None
    
    # 前端URL配置（用于OAuth回调后重定向）
    # 本地开发: http://localhost:8000
    # 生产环境: https://your-domain.com 或 http://your-ip:8000
    FRONTEND_URL: str = "http://localhost:8000"
    
    # 初始管理员配置（LinuxDO user_id）
    INITIAL_ADMIN_LINUXDO_ID: Optional[str] = None
    
    # 本地账户登录配置
    LOCAL_AUTH_ENABLED: bool = True  # 是否启用本地账户登录
    LOCAL_AUTH_USERNAME: Optional[str] = None  # 本地登录用户名
    LOCAL_AUTH_PASSWORD: Optional[str] = None  # 本地登录密码
    LOCAL_AUTH_DISPLAY_NAME: str = "Người dùng cục bộ"  # Tên hiển thị người dùng local
    
    # 会话配置
    SESSION_EXPIRE_MINUTES: int = 120  # 会话过期时间（分钟），默认2小时
    SESSION_REFRESH_THRESHOLD_MINUTES: int = 30  # 会话刷新阈值（分钟），剩余时间少于此值时可刷新
    SESSION_SECRET_KEY: Optional[str] = None  # 会话签名密钥，生产环境必须配置为高强度随机值
    SESSION_COOKIE_SECURE: Optional[bool] = None  # 是否强制 Cookie Secure；None 时按 DEBUG 自动判断

    # 系统 SMTP 默认配置（可被管理员系统设置覆盖）
    SMTP_PROVIDER: str = "qq"
    SMTP_HOST: Optional[str] = "smtp.qq.com"
    SMTP_PORT: int = 465
    SMTP_USERNAME: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_USE_TLS: bool = False
    SMTP_USE_SSL: bool = True
    SMTP_FROM_EMAIL: Optional[str] = None
    SMTP_FROM_NAME: str = "MuMuAINovel"
    EMAIL_AUTH_ENABLED: bool = True
    EMAIL_REGISTER_ENABLED: bool = True
    EMAIL_VERIFICATION_CODE_TTL_MINUTES: int = 10
    EMAIL_VERIFICATION_RESEND_INTERVAL_SECONDS: int = 60
    
    # 提示词工坊配置
    WORKSHOP_MODE: str = "client"  # client: instance triển khai local, server: máy chủ trung tâm đám mây
    WORKSHOP_CLOUD_URL: str = "https://mumuverse.space:1566"  # Địa chỉ dịch vụ đám mây
    WORKSHOP_API_TIMEOUT: int = 30  # 云端API请求超时时间（秒）

    # 视频导出配置（章节 → 分镜 → MP4/SRT），MVP 默认本地静音成片
    video_export_enabled: bool = True  # 总开关，可临时禁用整个导出能力
    video_ffmpeg_binary: Optional[str] = None  # FFmpeg 可执行文件路径；为空时使用 PATH 中的 ffmpeg
    video_export_storage_dir: Optional[str] = None  # 成片存储目录；为空时使用 backend/storage/generated_videos
    video_render_timeout_seconds: int = 900  # 单个 FFmpeg 调用的超时时间
    video_job_timeout_seconds: int = 1800  # 单个导出任务的墙钟总超时（秒）
    video_claim_ttl_buffer_seconds: int = 300  # 执行权 lease 的额外缓冲：任务超时上限 + 该值后才允许其它 worker 接管
    video_cancel_poll_seconds: float = 1.0  # FFmpeg 运行期间检查取消信号的间隔（秒）
    video_max_active_jobs: int = 2  # 每个用户同时可存在的未完成导出任务数
    video_max_chapters: int = 10  # 单次导出最多章节数
    video_max_scenes: int = 40  # 单次导出最多分镜数
    video_max_duration_seconds: int = 900  # 成片总时长上限（秒）
    video_max_output_mb: int = 512  # 成片体积上限（MB）
    video_scene_min_seconds: float = 3.0  # 单个分镜最短时长
    video_scene_max_seconds: float = 12.0  # 单个分镜最长时长
    video_allowed_resolutions: str = "1280x720,1920x1080,854x480"  # 允许的分辨率白名单
    video_default_resolution: str = "1280x720"
    video_default_fps: int = 24
    video_allowed_fps: str = "12,15,24,25,30"
    # TTS 为可选项：默认生成静音成片，配置完整后才会合成旁白音频
    video_tts_enabled: bool = False
    video_tts_provider: str = "openai_compatible"  # 目前支持 openai_compatible（/audio/speech）
    video_tts_base_url: Optional[str] = None
    video_tts_api_key: Optional[str] = None
    video_tts_model: Optional[str] = None
    video_tts_voice: str = "alloy"
    video_tts_timeout_seconds: int = 120

    # 视频转场 Provider（motion video）：local = FFmpeg 兜底，remote = 远端 image-to-video，hybrid = 优先远端并可按策略回落 local
    video_motion_mode: str = "local"  # local/remote/hybrid（客户端可覆盖，受 capabilities 约束）
    video_motion_provider: Optional[str] = None  # 服务端默认 provider（为空时自动选择已配置的远端 provider）
    video_motion_model: Optional[str] = None  # 服务端默认模型
    video_motion_resolution: Optional[str] = None  # 服务端默认分辨率 token（480p/720p/1080p/1024p）
    video_motion_hybrid_fallback_on_error: bool = True  # hybrid 模式下远端失败时是否回落到本地 FFmpeg
    video_motion_poll_interval_seconds: float = 5.0  # 轮询远端操作的初始间隔
    video_motion_poll_max_interval_seconds: float = 20.0  # 轮询退避上限
    video_motion_operation_timeout_seconds: int = 900  # 单个分镜等待远端完成的墙钟上限
    video_motion_max_retries: int = 2  # 单次 HTTP 请求的重试次数（仅网络错误/408/429/5xx）
    video_motion_request_timeout_seconds: int = 120  # 提交/轮询请求的超时
    video_motion_download_timeout_seconds: int = 300  # 下载单个片段的超时
    video_motion_max_clip_mb: int = 128  # 单个远端片段的大小上限
    # 安全：默认只允许 HTTPS 下载；白名单为空时按“公网 HTTPS”校验（拒绝内网/回环/元数据地址）
    video_motion_allow_insecure_localhost: bool = False
    video_motion_download_allowed_hosts: str = ""  # 逗号分隔的下载主机白名单（如 CDN 域名）

    # xAI Grok Imagine（POST /videos/generations → GET /videos/{request_id}）
    video_motion_xai_api_key: Optional[str] = None
    video_motion_xai_base_url: str = "https://api.x.ai/v1"
    video_motion_xai_model: str = "grok-imagine-video-1.5"
    video_motion_xai_generate_audio: bool = False  # Grok Imagine 支持原生音频，默认关闭以便与旁白时长一致

    # Google Veo（Gemini API：models/{model}:predictLongRunning）
    video_motion_gemini_api_key: Optional[str] = None
    video_motion_gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    video_motion_gemini_model: str = "veo-3.1-generate-preview"
    video_motion_veo_person_generation: str = "allow_adult"

    # OpenAI 兼容视频 API（POST /videos → GET /videos/{id} → /videos/{id}/content）
    video_motion_openai_api_key: Optional[str] = None
    video_motion_openai_base_url: Optional[str] = None
    video_motion_openai_model: str = "sora-2"

    # 场景图片生成（image provider）：为每个分镜生成画面，再交给 motion provider 作为参考图
    video_image_enabled: bool = True  # 总开关：false 时 UI/API 都不允许开启 tạo ảnh
    video_image_provider: Optional[str] = None  # 默认图片 provider（为空时取第一个已配置的）
    video_image_model: Optional[str] = None
    video_image_aspect_ratio: Optional[str] = None  # 16:9 / 9:16 / 1:1
    video_image_reasoning_strength: Optional[str] = None  # 仅 provider 支持时发送
    video_image_timeout_seconds: int = 120  # 单张图片生成超时
    video_image_max_retries: int = 2  # 单次请求重试次数（仅网络/408/429/5xx）
    video_image_retry_delay_seconds: float = 2.0  # 重试退避基数
    video_image_max_mb: int = 16  # 单张图片大小上限（base64 解码后同样受限）
    image_allow_insecure_localhost: bool = False  # 仅开发：允许 http://localhost 的图片 provider
    image_download_allowed_hosts: str = ""  # 图片下载主机白名单（CSV）；留空 = 任意公网 HTTPS

    # Meta Model API（Muse Image 1.0）：POST {base}/images/generations
    meta_muse_api_key: Optional[str] = None  # 主变量；不写日志/DB/响应
    model_api_key: Optional[str] = None  # 兼容别名（Meta 文档里的 MODEL_API_KEY）
    meta_muse_base_url: str = "https://api.meta.ai/v1"
    meta_muse_model: str = "muse-image-1.0"
    meta_muse_output_format: str = "webp"  # webp/png/jpeg
    meta_muse_reasoning_strengths: str = "low,high"  # theo docs Meta hiện hành chỉ low/high

    # PDF 全本导出（ReportLab Platypus）
    pdf_export_enabled: bool = True  # 总开关
    pdf_export_storage_dir: Optional[str] = None  # 为空时使用 backend/storage/generated_pdfs
    pdf_font_path: Optional[str] = None  # Unicode TTF 路径；为空时自动探测系统字体
    pdf_max_chapters: int = 300  # 单次导出最多章节数（全本通常很多章）
    pdf_max_text_chars: int = 2_000_000  # 正文总字符上限，避免内存/耗时失控
    pdf_max_images: int = 60  # 单次导出最多插图数（每张都可能调用付费 API）
    pdf_max_output_mb: int = 128  # PDF 体积上限
    pdf_job_timeout_seconds: int = 1800  # 单个任务墙钟上限
    pdf_max_active_jobs: int = 2  # 每个用户同时未完成的任务数
    pdf_claim_ttl_buffer_seconds: int = 300  # 执行权 lease 缓冲（配合 pdf_job_timeout_seconds）
    pdf_claim_renew_seconds: float = 60.0  # 运行期间续租执行权的最小间隔（避免长任务被误判为 stale）
    pdf_cancel_poll_seconds: float = 1.0  # 检查取消信号的最小间隔（避免频繁查库）
    pdf_default_page_size: str = "A4"  # A4/LETTER
    pdf_include_toc: bool = True  # 是否生成目录
    pdf_image_width_ratio: float = 0.85  # 插图占正文宽度比例（保持等比，不放大）
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Bỏ qua biến môi trường chưa định nghĩa để tránh lỗi validate


# 创建全局配置实例
settings = Settings()
config_logger.info(f"Đã tải cấu hình: {settings.app_name} v{settings.app_version}")
config_logger.debug(f"Chế độ debug: {settings.debug}")
config_logger.debug(f"Nhà cung cấp AI: {settings.default_ai_provider}")


# ==================== 提示词工坊实例标识 ====================

def get_or_create_instance_id() -> str:
    """Lấy hoặc tạo định danh duy nhất của instance
    
    - Chế độ Server: cố định dùng "server" làm định danh, tách biệt mọi instance Client
    - Chế độ Client: đọc từ file .instance_id hoặc tự sinh định danh duy nhất
    """
    # Server 模式使用固定标识
    if settings.WORKSHOP_MODE.lower() == "server":
        config_logger.info("Chế độ Server: dùng định danh instance cố định 'server'")
        return "server"
    
    # Client 模式：从文件读取或生成
    instance_file = PROJECT_ROOT / ".instance_id"
    if instance_file.exists():
        with open(instance_file, 'r') as f:
            instance_id = f.read().strip()
            if instance_id and instance_id != "server":  # Đảm bảo không trùng với server
                return instance_id
    
    # 生成新的实例ID
    instance_id = str(uuid.uuid4())[:12]
    try:
        with open(instance_file, 'w') as f:
            f.write(instance_id)
        config_logger.info(f"Đã tạo định danh instance mới: {instance_id}")
    except Exception as e:
        config_logger.warning(f"Không thể lưu định danh instance vào file: {e}")
    
    return instance_id

INSTANCE_ID = get_or_create_instance_id()

def is_workshop_server() -> bool:
    """判断当前实例是否为工坊服务端"""
    return settings.WORKSHOP_MODE.lower() == "server"

config_logger.info(f"Chế độ xưởng prompt: {settings.WORKSHOP_MODE}, instance ID: {INSTANCE_ID}")
