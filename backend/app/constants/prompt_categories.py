"""提示词工坊分类常量"""

PROMPT_CATEGORIES = {
    "general": "Chung",
    "fantasy": "Huyền huyễn / Tiên hiệp",
    "martial": "Võ hiệp",
    "romance": "Ngôn tình",
    "scifi": "Khoa học viễn tưởng",
    "horror": "Huyền nghi / Kinh dị",
    "history": "Lịch sử",
    "urban": "Đô thị",
    "game": "Game / Thể thao điện tử",
    "other": "Khác",
}

CATEGORY_LIST = [
    {"id": k, "name": v} for k, v in PROMPT_CATEGORIES.items()
]

# 热门标签（建议）
POPULAR_TAGS = [
    "Huyền huyễn", "Tiên hiệp", "Tu chân", "Dòng thăng cấp", "Nhiệt huyết",
    "Võ hiệp", "Cổ phong", "Ngôn tình", "Ngọt sủng", "Ngược luyến",
    "Khoa học viễn tưởng", "Liên sao", "Tận thế", "Huyền nghi", "Suy luận",
    "Kinh dị", "Lịch sử", "Giả tưởng", "Đô thị", "Công sở",
    "Game", "Thể thao điện tử", "Nhị thứ nguyên", "Light novel", "Dòng hệ thống",
    "Dòng vô địch", "Chậm nóng", "Thường nhật", "Chữa lành"
]