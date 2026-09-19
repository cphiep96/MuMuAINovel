"""请求追踪ID中间件"""
import uuid
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from typing import Callable


class RequestIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware ID theo dõi yêu cầu
    
    Tạo ID duy nhất cho mỗi yêu cầu và thêm vào ngữ cảnh log
    """
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Xử lý yêu cầu, thêm ID theo dõi
        
        Args:
            request: Đối tượng yêu cầu
            call_next: Bộ xử lý tiếp theo
            
        Returns:
            Đối tượng phản hồi
        """
        # 从请求头获取追踪ID，或生成新的
        request_id = request.headers.get('X-Request-ID') or str(uuid.uuid4())
        
        # 将请求ID存储到request.state中，方便后续访问
        request.state.request_id = request_id
        
        # 创建日志过滤器，自动添加request_id到日志记录
        log_filter = RequestIDFilter(request_id)
        
        # 获取根日志器并添加过滤器
        root_logger = logging.getLogger()
        root_logger.addFilter(log_filter)
        
        try:
            # 处理请求
            response = await call_next(request)
            
            # 将请求ID添加到响应头
            response.headers['X-Request-ID'] = request_id
            
            return response
        finally:
            # 移除过滤器，避免影响其他请求
            root_logger.removeFilter(log_filter)


class RequestIDFilter(logging.Filter):
    """日志过滤器，为日志记录添加request_id属性"""
    
    def __init__(self, request_id: str):
        """
        Khởi tạo bộ lọc
        
        Args:
            request_id: ID theo dõi yêu cầu
        """
        super().__init__()
        self.request_id = request_id
    
    def filter(self, record: logging.LogRecord) -> bool:
        """
        Thêm thuộc tính request_id vào bản ghi log
        
        Args:
            record: Bản ghi log
            
        Returns:
            True (không lọc bất kỳ log nào)
        """
        record.request_id = self.request_id
        return True