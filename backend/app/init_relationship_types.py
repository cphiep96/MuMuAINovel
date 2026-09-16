"""初始化关系类型数据"""
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import AsyncSessionLocal
from app.models.relationship import RelationshipType
from app.logger import get_logger

logger = get_logger(__name__)


async def init_relationship_types():
    """初始化预置的关系类型数据"""
    
    # 预置关系类型数据
    relationship_types = [
        # 家族关系
        {"name": "Cha", "category": "family", "reverse_name": "Con cái", "intimacy_range": "high", "icon": "👨"},
        {"name": "Mẹ", "category": "family", "reverse_name": "Con cái", "intimacy_range": "high", "icon": "👩"},
        {"name": "Anh em", "category": "family", "reverse_name": "Anh em", "intimacy_range": "high", "icon": "👬"},
        {"name": "Chị em", "category": "family", "reverse_name": "Chị em", "intimacy_range": "high", "icon": "👭"},
        {"name": "Con cái", "category": "family", "reverse_name": "Cha mẹ", "intimacy_range": "high", "icon": "👶"},
        {"name": "Vợ/chồng", "category": "family", "reverse_name": "Vợ/chồng", "intimacy_range": "high", "icon": "💑"},
        {"name": "Người yêu", "category": "family", "reverse_name": "Người yêu", "intimacy_range": "high", "icon": "💕"},
        
        # 社交关系
        {"name": "Sư phụ", "category": "social", "reverse_name": "Đồ đệ", "intimacy_range": "high", "icon": "🎓"},
        {"name": "Đồ đệ", "category": "social", "reverse_name": "Sư phụ", "intimacy_range": "high", "icon": "📚"},
        {"name": "Bạn bè", "category": "social", "reverse_name": "Bạn bè", "intimacy_range": "medium", "icon": "🤝"},
        {"name": "Bạn học", "category": "social", "reverse_name": "Bạn học", "intimacy_range": "medium", "icon": "🎒"},
        {"name": "Hàng xóm", "category": "social", "reverse_name": "Hàng xóm", "intimacy_range": "low", "icon": "🏘️"},
        {"name": "Tri kỷ", "category": "social", "reverse_name": "Tri kỷ", "intimacy_range": "high", "icon": "💙"},
        
        # 职业关系
        {"name": "Cấp trên", "category": "professional", "reverse_name": "Cấp dưới", "intimacy_range": "low", "icon": "👔"},
        {"name": "Cấp dưới", "category": "professional", "reverse_name": "Cấp trên", "intimacy_range": "low", "icon": "💼"},
        {"name": "Đồng nghiệp", "category": "professional", "reverse_name": "Đồng nghiệp", "intimacy_range": "medium", "icon": "🤵"},
        {"name": "Đối tác", "category": "professional", "reverse_name": "Đối tác", "intimacy_range": "medium", "icon": "🤜🤛"},
        
        # 敌对关系
        {"name": "Kẻ thù", "category": "hostile", "reverse_name": "Kẻ thù", "intimacy_range": "low", "icon": "⚔️"},
        {"name": "Kẻ thù riêng", "category": "hostile", "reverse_name": "Kẻ thù riêng", "intimacy_range": "low", "icon": "💢"},
        {"name": "Đối thủ cạnh tranh", "category": "hostile", "reverse_name": "Đối thủ cạnh tranh", "intimacy_range": "low", "icon": "🎯"},
        {"name": "Kẻ thù truyền kiếp", "category": "hostile", "reverse_name": "Kẻ thù truyền kiếp", "intimacy_range": "low", "icon": "⚡"},
    ]
    
    async with AsyncSessionLocal() as session:
        try:
            # 检查是否已经有数据
            result = await session.execute(select(RelationshipType))
            existing = result.scalars().first()
            
            if existing:
                logger.info("关系类型数据已存在，跳过初始化")
                return
            
            # 插入预置数据
            logger.info("开始插入关系类型数据...")
            for rt_data in relationship_types:
                relationship_type = RelationshipType(**rt_data)
                session.add(relationship_type)
            
            await session.commit()
            logger.info(f"成功插入 {len(relationship_types)} 条关系类型数据")
            
        except Exception as e:
            logger.error(f"初始化关系类型数据失败: {str(e)}", exc_info=True)
            await session.rollback()
            raise


if __name__ == "__main__":
    asyncio.run(init_relationship_types())