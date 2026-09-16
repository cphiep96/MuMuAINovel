"""初始化预置数据

Revision ID: e411428f00c0
Revises: ee0a189f1532
Create Date: 2025-12-26 11:02:24.080526

"""
from typing import Sequence, Union
from datetime import datetime

from alembic import op
import sqlalchemy as sa
from sqlalchemy import table, column, String, Integer, Float, Text, Boolean, DateTime


# revision identifiers, used by Alembic.
revision: str = 'e411428f00c0'
down_revision: Union[str, None] = 'ee0a189f1532'
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
    print(f"✅ 已插入 {len(relationship_types_data)} 条关系类型数据")
    
    
    # ==================== 2. 插入全局写作风格预设 ====================
    # 注意：这里需要从 WritingStyleManager 获取预设配置
    # 为了避免导入应用代码，我们直接硬编码预设风格
    
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
            "name": "Tự nhiên, trôi chảy",
            "style_type": "preset",
            "preset_id": "natural",
            "description": "Phong cách kể chuyện tự nhiên, trôi chảy, phù hợp đề tài đô thị hiện đại và hiện thực",
            "prompt_content": """Yêu cầu phong cách viết:
1. Ngôn ngữ gọn gàng, sáng rõ, gần với khẩu ngữ hiện đại
2. Dùng nhiều câu ngắn, nhịp điệu trôi chảy
3. Chú trọng để cảm xúc chi tiết bộc lộ tự nhiên
4. Tránh tô vẽ quá mức và câu cú phức tạp""",
            "order_index": 1
        },
        {
            "user_id": None,
            "name": "Cổ điển, thanh nhã",
            "style_type": "preset",
            "preset_id": "classical",
            "description": "Phong cách viết cổ điển, thanh nhã, phù hợp đề tài cổ trang và tiên hiệp",
            "prompt_content": """Yêu cầu phong cách viết:
1. Dùng văn ngôn, bán văn ngôn hoặc bạch thoại trang nhã
2. Vận dụng hợp lý hình ảnh thơ cổ điển
3. Chú trọng tạo dựng ý cảnh và dư vị
4. Giữ vẻ đẹp cổ điển trong đối thoại và miêu tả""",
            "order_index": 2
        },
        {
            "user_id": None,
            "name": "Hiện đại, tối giản",
            "style_type": "preset",
            "preset_id": "modern",
            "description": "Phong cách hiện đại tối giản, phù hợp light novel và nhịp kể nhanh của tiểu thuyết mạng",
            "prompt_content": """Yêu cầu phong cách viết:
1. Ngôn ngữ trực tiếp, súc tích, mật độ thông tin cao
2. Dùng nhiều đối thoại để đẩy tình tiết
3. Tránh miêu tả dài dòng, làm nổi bật hành động then chốt
4. Nhịp điệu nhanh, phù hợp đọc nhanh""",
            "order_index": 3
        },
        {
            "user_id": None,
            "name": "Văn chương, tinh tế",
            "style_type": "preset",
            "preset_id": "literary",
            "description": "Phong cách văn chương tinh tế, chú trọng miêu tả tâm lý và tạo dựng bầu không khí",
            "prompt_content": """Yêu cầu phong cách viết:
1. Chú trọng hoạt động tâm lý và chi tiết cảm xúc
2. Khéo dùng miêu tả môi trường để tôn bầu không khí
3. Ngôn ngữ đẹp, giàu tính văn học
4. Sử dụng hợp lý biện pháp tu từ như so sánh, ẩn dụ""",
            "order_index": 4
        },
        {
            "user_id": None,
            "name": "Căng thẳng, huyền nghi",
            "style_type": "preset",
            "preset_id": "suspense",
            "description": "Phong cách căng thẳng, huyền nghi, phù hợp đề tài trinh thám và kinh dị",
            "prompt_content": """Yêu cầu phong cách viết:
1. Tạo bầu không khí căng thẳng, dồn nén
2. Dùng nhiều câu ngắn để tăng nhịp độ
3. Khéo cài điểm treo và phục bút
4. Chú trọng miêu tả chi tiết, gài manh mối cho suy luận""",
            "order_index": 5
        },
        {
            "user_id": None,
            "name": "Hài hước, dí dỏm",
            "style_type": "preset",
            "preset_id": "humorous",
            "description": "Phong cách hài hước dí dỏm, phù hợp đề tài nhẹ nhàng, gây cười",
            "prompt_content": """Yêu cầu phong cách viết:
1. Ngôn ngữ hoạt bát, dí dỏm, khéo dùng lối nói bông đùa
2. Chú trọng hiệu quả hài trong đối thoại
3. Cường điệu và đảo ngược hợp lý để tạo tiếng cười
4. Giữ giọng điệu nhẹ nhàng, vui vẻ""",
            "order_index": 6
        },
    ]
    
    op.bulk_insert(writing_styles_table, writing_styles_data)
    print(f"✅ Đã chèn {len(writing_styles_data)} phong cách viết mặc định")


def downgrade() -> None:
    """删除预置数据"""
    
    # 删除写作风格预设（只删除全局预设）
    op.execute("DELETE FROM writing_styles WHERE user_id IS NULL")
    print("✅ 已删除全局写作风格预设")
    
    # 删除关系类型
    op.execute("DELETE FROM relationship_types")
    print("✅ 已删除关系类型数据")
