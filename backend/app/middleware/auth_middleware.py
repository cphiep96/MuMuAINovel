"""
Middleware xác thực - lấy thông tin người dùng từ Cookie và gắn vào request.state
Hỗ trợ yêu cầu proxy từ instance khác (tính năng xưởng prompt)
"""
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.user_manager import user_manager
from app.logger import get_logger
from app.security import verify_session_token
import hmac
import os

logger = get_logger(__name__)


class AuthMiddleware(BaseHTTPMiddleware):
    """认证中间件"""
    
    async def dispatch(self, request: Request, call_next):
        """
        Xử lý yêu cầu, lấy user ID từ Cookie hoặc Header và gắn vào request.state
        
        Với yêu cầu proxy liên quan xưởng prompt (có Header X-Instance-ID),
        đọc định danh người dùng từ Header thay vì Cookie.
        """
        # 检查是否为来自其他实例的代理请求（提示词工坊）
        instance_id = request.headers.get("X-Instance-ID")
        is_workshop_path = request.url.path.startswith("/api/prompt-workshop")
        
        if instance_id and is_workshop_path:
            # 来自其他实例的代理请求
            header_user_id = request.headers.get("X-User-ID")
            
            request.state.is_proxy_request = True
            request.state.proxy_instance_id = instance_id
            
            if header_user_id:
                # 有用户标识，使用代理的用户信息
                request.state.user_id = header_user_id  # 这是 "instance:user_id" 格式
                request.state.user = None  # 代理请求没有实际的 User 对象
                request.state.is_admin = False
            else:
                # 没有用户标识，匿名访问
                request.state.user_id = None
                request.state.user = None
                request.state.is_admin = False
        else:
            # 本地请求或非工坊路径，使用 Cookie 认证
            request.state.is_proxy_request = False
            request.state.proxy_instance_id = None
            
            # 优先验证签名会话 Cookie；不再信任客户端可伪造的明文 user_id。
            user_id = verify_session_token(request.cookies.get("session_token"))
            mcp_authenticated = False

            # First-party MCP server may call the existing REST/SSE APIs with
            # a shared bearer token instead of a browser cookie.  The token is
            # never accepted from a plain user-id header: it must match the
            # server-side MUMU_MCP_TOKEN environment variable.  A deployment
            # can provide the user through MUMU_MCP_USER_ID or the explicit
            # X-Mumu-User-ID header sent by the MCP server.
            if not user_id:
                authorization = request.headers.get("authorization", "")
                bearer = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
                configured_token = os.getenv("MUMU_MCP_TOKEN", "")
                if bearer and configured_token and hmac.compare_digest(bearer, configured_token):
                    user_id = request.headers.get("X-Mumu-User-ID") or os.getenv("MUMU_MCP_USER_ID") or os.getenv("MUMU_USER_ID")
                    mcp_authenticated = bool(user_id)
            
            if user_id:
                # A valid MCP bearer token is already authenticated by the
                # server secret; it may intentionally represent a service user
                # that has no browser profile row yet.
                user = None if mcp_authenticated else await user_manager.get_user(user_id)
                if mcp_authenticated:
                    request.state.user_id = user_id
                    request.state.user = None
                    request.state.is_admin = False
                elif user:
                    # 检查用户是否被禁用 (trust_level = -1)
                    if user.trust_level == -1:
                        logger.warning(f"禁用用户尝试访问: {user_id} ({user.username})")
                        # 清除用户状态，视为未登录
                        request.state.user_id = None
                        request.state.user = None
                        request.state.is_admin = False
                    else:
                        # 用户正常，注入状态
                        request.state.user_id = user_id
                        request.state.user = user
                        request.state.is_admin = user.is_admin
                else:
                    # 用户不存在，清除状态
                    request.state.user_id = None
                    request.state.user = None
                    request.state.is_admin = False
            else:
                # 未登录
                request.state.user_id = None
                request.state.user = None
                request.state.is_admin = False
        
        # 继续处理请求
        response = await call_next(request)
        return response
