"""
Module quản lý mật khẩu người dùng - lưu trữ bằng database
"""
import asyncio
import hashlib
import hmac
import secrets
from typing import Optional
from datetime import datetime
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from app.config import settings


class UserPasswordManager:
    """用户密码管理器 - 使用数据库存储（PostgreSQL共享库）"""
    
    def __init__(self):
        """初始化密码管理器"""
        pass
    
    async def _get_session(self) -> AsyncSession:
        """获取数据库会话 - 使用共享的PostgreSQL引擎"""
        from app.database import get_engine
        
        # 使用共享的PostgreSQL引擎（user_id使用特殊标识）
        engine = await get_engine("_global_users_")
        
        session_maker = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False
        )
        
        return session_maker()
    
    def _hash_password(self, password: str) -> str:
        """密码哈希"""
        salt = secrets.token_hex(16)
        iterations = 260000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
        return f"pbkdf2_sha256${iterations}${salt}${digest}"

    def _verify_hash(self, password: str, stored_hash: str) -> bool:
        if stored_hash.startswith("pbkdf2_sha256$"):
            try:
                _, iterations, salt, digest = stored_hash.split("$", 3)
                candidate = hashlib.pbkdf2_hmac(
                    "sha256",
                    password.encode(),
                    salt.encode(),
                    int(iterations),
                ).hex()
                return hmac.compare_digest(candidate, digest)
            except Exception:
                return False

        # Legacy unsalted SHA-256 hash support for existing deployments.
        legacy_hash = hashlib.sha256(password.encode()).hexdigest()
        return hmac.compare_digest(legacy_hash, stored_hash)
    
    async def set_password(self, user_id: str, username: str, password: Optional[str] = None) -> str:
        """
        Thiết lập mật khẩu người dùng
        
        Args:
            user_id: ID người dùng
            username: Tên người dùng
            password: Mật khẩu; nếu None thì dùng mật khẩu mặc định (username+@666)
            
        Returns:
            Mật khẩu thực tế dùng (plain text, chỉ trả về khi thiết lập lần đầu)
        """
        from app.models.user import UserPassword as UserPasswordModel
        
        # 如果没有提供密码，使用默认密码
        actual_password = password if password else f"{username}@666"
        
        async with await self._get_session() as session:
            # 查询密码记录是否存在
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            if pwd_record:
                # 更新现有密码
                pwd_record.username = username
                pwd_record.password_hash = self._hash_password(actual_password)
                pwd_record.has_custom_password = password is not None
                pwd_record.updated_at = datetime.now()
            else:
                # 创建新密码记录
                pwd_record = UserPasswordModel(
                    user_id=user_id,
                    username=username,
                    password_hash=self._hash_password(actual_password),
                    has_custom_password=password is not None,
                    created_at=datetime.now(),
                    updated_at=datetime.now()
                )
                session.add(pwd_record)
            
            await session.commit()
            
            return actual_password
    
    async def verify_password(self, user_id: str, password: str) -> bool:
        """
        Xác minh mật khẩu người dùng
        
        Args:
            user_id: ID người dùng
            password: Mật khẩu cần xác minh
            
        Returns:
            Có xác minh thành công hay không
        """
        from app.models.user import UserPassword as UserPasswordModel
        
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            if not pwd_record:
                return False
            
            verified = self._verify_hash(password, pwd_record.password_hash)
            if verified and not pwd_record.password_hash.startswith("pbkdf2_sha256$"):
                pwd_record.password_hash = self._hash_password(password)
                pwd_record.updated_at = datetime.now()
                await session.commit()
            return verified
    
    async def has_password(self, user_id: str) -> bool:
        """
        Kiểm tra người dùng đã đặt mật khẩu chưa
        
        Args:
            user_id: ID người dùng
            
        Returns:
            Đã đặt mật khẩu hay chưa
        """
        from app.models.user import UserPassword as UserPasswordModel
        
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            return pwd_record is not None
    
    async def has_custom_password(self, user_id: str) -> bool:
        """
        Kiểm tra người dùng đã đặt mật khẩu tùy chỉnh (không phải mặc định)
        
        Args:
            user_id: ID người dùng
            
        Returns:
            Có dùng mật khẩu tùy chỉnh hay không
        """
        from app.models.user import UserPassword as UserPasswordModel
        
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            if not pwd_record:
                return False
            
            return pwd_record.has_custom_password
    
    async def get_username(self, user_id: str) -> Optional[str]:
        """
        Lấy tên người dùng
        
        Args:
            user_id: ID người dùng
            
        Returns:
            Tên người dùng; nếu không tồn tại trả về None
        """
        from app.models.user import UserPassword as UserPasswordModel
        
        async with await self._get_session() as session:
            result = await session.execute(
                select(UserPasswordModel).where(UserPasswordModel.user_id == user_id)
            )
            pwd_record = result.scalar_one_or_none()
            
            if not pwd_record:
                return None
            
            return pwd_record.username


# 全局密码管理器实例
password_manager = UserPasswordManager()
