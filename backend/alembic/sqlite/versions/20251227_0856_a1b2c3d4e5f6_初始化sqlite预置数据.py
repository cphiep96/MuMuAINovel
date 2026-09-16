"""初始化SQLite预置数据

Revision ID: a1b2c3d4e5f6
Revises: fbeb1038c728
Create Date: 2025-12-27 08:56:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column, String, Integer, Text


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'fbeb1038c728'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """插入预置数据"""
    
    # ==================== 1. 插入关系类型数据 ====================
    relationship_types_table = table(
        'relationship_types',
        column('name', String),
        column('category', String),
        column('reverse_name', String),
        column('intimacy_range', String),
        column('icon', String),
        column('description', Text),
    )
    
    relationship_types_data = [
        # 家庭关系
        {"name": "Cha", "category": "family", "reverse_name": "Con cái", "intimacy_range": "high", "icon": "👨", "description": "Quan hệ cha - con"},
        {"name": "Mẹ", "category": "family", "reverse_name": "Con cái", "intimacy_range": "high", "icon": "👩", "description": "Quan hệ mẹ - con"},
        {"name": "Anh em", "category": "family", "reverse_name": "Anh em", "intimacy_range": "high", "icon": "👬", "description": "Quan hệ anh em"},
        {"name": "Chị em", "category": "family", "reverse_name": "Chị em", "intimacy_range": "high", "icon": "👭", "description": "Quan hệ chị em"},
        {"name": "Con cái", "category": "family", "reverse_name": "Cha mẹ", "intimacy_range": "high", "icon": "👶", "description": "Quan hệ con cái với cha mẹ"},
        {"name": "Vợ/chồng", "category": "family", "reverse_name": "Vợ/chồng", "intimacy_range": "high", "icon": "💑", "description": "Quan hệ vợ chồng"},
        {"name": "Người yêu", "category": "family", "reverse_name": "Người yêu", "intimacy_range": "high", "icon": "💕", "description": "Quan hệ yêu đương"},
        
        # 社交关系
        {"name": "Sư phụ", "category": "social", "reverse_name": "Đồ đệ", "intimacy_range": "high", "icon": "🎓", "description": "Quan hệ sư đồ (góc nhìn sư phụ)"},
        {"name": "Đồ đệ", "category": "social", "reverse_name": "Sư phụ", "intimacy_range": "high", "icon": "📚", "description": "Quan hệ sư đồ (góc nhìn đồ đệ)"},
        {"name": "Bạn bè", "category": "social", "reverse_name": "Bạn bè", "intimacy_range": "medium", "icon": "🤝", "description": "Quan hệ bạn bè"},
        {"name": "Bạn học", "category": "social", "reverse_name": "Bạn học", "intimacy_range": "medium", "icon": "🎒", "description": "Quan hệ bạn học"},
        {"name": "Hàng xóm", "category": "social", "reverse_name": "Hàng xóm", "intimacy_range": "low", "icon": "🏘️", "description": "Quan hệ hàng xóm"},
        {"name": "Tri kỷ", "category": "social", "reverse_name": "Tri kỷ", "intimacy_range": "high", "icon": "💙", "description": "Bạn tri kỷ"},
        
        # 职业关系
        {"name": "Cấp trên", "category": "professional", "reverse_name": "Cấp dưới", "intimacy_range": "low", "icon": "👔", "description": "Quan hệ cấp trên - cấp dưới (góc nhìn cấp trên)"},
        {"name": "Cấp dưới", "category": "professional", "reverse_name": "Cấp trên", "intimacy_range": "low", "icon": "💼", "description": "Quan hệ cấp trên - cấp dưới (góc nhìn cấp dưới)"},
        {"name": "Đồng nghiệp", "category": "professional", "reverse_name": "Đồng nghiệp", "intimacy_range": "medium", "icon": "🤵", "description": "Quan hệ đồng nghiệp"},
        {"name": "Đối tác", "category": "professional", "reverse_name": "Đối tác", "intimacy_range": "medium", "icon": "🤜🤛", "description": "Quan hệ hợp tác"},
        
        # 敌对关系
        {"name": "Kẻ thù", "category": "hostile", "reverse_name": "Kẻ thù", "intimacy_range": "low", "icon": "⚔️", "description": "Quan hệ đối địch"},
        {"name": "Kẻ thù riêng", "category": "hostile", "reverse_name": "Kẻ thù riêng", "intimacy_range": "low", "icon": "💢", "description": "Quan hệ thù hận"},
        {"name": "Đối thủ cạnh tranh", "category": "hostile", "reverse_name": "Đối thủ cạnh tranh", "intimacy_range": "low", "icon": "🎯", "description": "Quan hệ cạnh tranh"},
        {"name": "Kẻ thù truyền kiếp", "category": "hostile", "reverse_name": "Kẻ thù truyền kiếp", "intimacy_range": "low", "icon": "⚡", "description": "Kẻ thù truyền kiếp"},
    ]
    
    op.bulk_insert(relationship_types_table, relationship_types_data)
    print(f"✅ SQLite: 已插入 {len(relationship_types_data)} 条关系类型数据")
    
    
    # ==================== 2. 插入全局写作风格预设 ====================
    writing_styles_table = table(
        'writing_styles',
        column('user_id', String),
        column('name', String),
        column('style_type', String),
        column('preset_id', String),
        column('description', Text),
        column('prompt_content', Text),
        column('order_index', Integer),
    )
    
    writing_styles_data = [
        {
            "user_id": None,  # NULL 表示全局预设
            "name": "自然流畅",
            "style_type": "preset",
            "preset_id": "natural",
            "description": "自然流畅的叙事风格，适合现代都市、现实题材",
            "prompt_content": """写作风格要求：
1. 语言简洁明快，贴近现代口语
2. 多用短句，节奏流畅
3. 注重情感细节的自然流露
4. 避免过度修饰和复杂句式""",
            "order_index": 1
        },
        {
            "user_id": None,
            "name": "古典优雅",
            "style_type": "preset",
            "preset_id": "classical",
            "description": "古典文雅的写作风格，适合古装、仙侠题材",
            "prompt_content": """写作风格要求：
1. 使用文言、半文言或典雅的白话
2. 适当运用古典诗词意象
3. 注重意境营造和韵味
4. 对话和描写保持古典美感""",
            "order_index": 2
        },
        {
            "user_id": None,
            "name": "现代简约",
            "style_type": "preset",
            "preset_id": "modern",
            "description": "现代简约风格，适合轻小说、网文快节奏叙事",
            "prompt_content": """写作风格要求：
1. 语言直白简练，信息密度高
2. 多用对话推进情节
3. 避免冗长描写，突出关键动作
4. 节奏明快，适合快速阅读""",
            "order_index": 3
        },
        {
            "user_id": None,
            "name": "文艺细腻",
            "style_type": "preset",
            "preset_id": "literary",
            "description": "文艺细腻风格，注重心理描写和氛围营造",
            "prompt_content": """写作风格要求：
1. 注重心理活动和情感细节
2. 善用环境描写烘托氛围
3. 语言优美，富有文学性
4. 适当使用比喻、象征等修辞手法""",
            "order_index": 4
        },
        {
            "user_id": None,
            "name": "紧张悬疑",
            "style_type": "preset",
            "preset_id": "suspense",
            "description": "紧张悬疑风格，适合推理、惊悚题材",
            "prompt_content": """写作风格要求：
1. 营造紧张压迫的氛围
2. 多用短句加快节奏
3. 善于设置悬念和伏笔
4. 注重细节描写，为推理埋下线索""",
            "order_index": 5
        },
        {
            "user_id": None,
            "name": "幽默诙谐",
            "style_type": "preset",
            "preset_id": "humorous",
            "description": "幽默诙谐风格，适合轻松搞笑题材",
            "prompt_content": """写作风格要求：
1. 语言活泼风趣，善用俏皮话
2. 注重对话的喜剧效果
3. 适当夸张和反转制造笑点
4. 保持轻松愉快的基调""",
            "order_index": 6
        },
    ]
    
    op.bulk_insert(writing_styles_table, writing_styles_data)
    print(f"✅ SQLite: 已插入 {len(writing_styles_data)} 条全局写作风格预设")


def downgrade() -> None:
    """删除预置数据"""
    
    # 删除写作风格预设（只删除全局预设）
    op.execute("DELETE FROM writing_styles WHERE user_id IS NULL")
    print("✅ SQLite: 已删除全局写作风格预设")
    
    # 删除关系类型
    op.execute("DELETE FROM relationship_types")
    print("✅ SQLite: 已删除关系类型数据")