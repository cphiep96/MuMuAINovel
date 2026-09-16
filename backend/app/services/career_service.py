"""职业生成服务"""
from typing import Dict, Any, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.models.project import Project
from app.models.career import Career
from app.services.ai_service import AIService
from app.logger import get_logger

logger = get_logger(__name__)


class CareerService:
    """职业相关业务逻辑服务"""
    
    @staticmethod
    async def get_career_generation_prompt(
        project: Project,
        main_career_count: int = 2,
        sub_career_count: int = 6
    ) -> str:
        """
        构建职业体系生成的提示词
        
        Args:
            project: 项目对象
            main_career_count: 主职业数量
            sub_career_count: 副职业数量
            
        Returns:
            完整的提示词
        """
        project_context = f"""
Thông tin dự án:
- Tên sách: {project.title}
- Thể loại: {project.genre or 'Chưa thiết lập'}
- Chủ đề: {project.theme or 'Chưa thiết lập'}
- Bối cảnh thời gian: {project.world_time_period or 'Chưa thiết lập'}
- Vị trí địa lý: {project.world_location or 'Chưa thiết lập'}
- Gam bầu không khí: {project.world_atmosphere or 'Chưa thiết lập'}
- Quy tắc thế giới: {project.world_rules or 'Chưa thiết lập'}
"""
        
        user_requirements = f"""
Yêu cầu tạo:
- Số nghề chính: {main_career_count}
- Số nghề phụ: {sub_career_count}
- Nghề chính phải khớp nghiêm quy tắc bối cảnh thế giới, thể hiện hệ năng lực cốt lõi
- Nghề phụ có thể tự do linh hoạt hơn, gồm sản xuất, hỗ trợ, loại đặc biệt
"""
        
        prompt = f"""【Yêu cầu ngôn ngữ】Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.
{project_context}

{user_requirements}

Hãy tạo hệ nghề hoàn chỉnh cho dự án tiểu thuyết này. Trả về JSON với cấu trúc sau:

{{
  "main_careers": [
    {{
      "name": "Tên nghề",
      "description": "Mô tả nghề (100-200 chữ)",
      "category": "Phân loại nghề (vd: hệ chiến đấu, hệ pháp thuật, hệ thể tu...)",
      "stages": [
        {{"level": 1, "name": "Tên giai đoạn", "description": "Mô tả giai đoạn"}},
        {{"level": 2, "name": "Tên giai đoạn", "description": "Mô tả giai đoạn"}},
        ... (tổng 10 giai đoạn)
      ],
      "max_stage": 10,
      "requirements": "Yêu cầu nghề (vd: cần thiên phú/tư chất cụ thể)",
      "special_abilities": "Mô tả năng lực đặc biệt",
      "worldview_rules": "Liên kết quy tắc bối cảnh (giải thích nghề hòa vào thế giới thế nào)",
      "attribute_bonuses": {{"strength": "+10%", "intelligence": "+5%"}}
    }}
  ],
  "sub_careers": [
    {{
      "name": "Tên nghề phụ",
      "description": "Mô tả nghề",
      "category": "Hệ sản xuất/hệ hỗ trợ/hệ đặc biệt",
      "stages": [
        {{"level": 1, "name": "Tên giai đoạn", "description": "Mô tả giai đoạn"}},
        ... (5-8 giai đoạn)
      ],
      "max_stage": 5,
      "requirements": "Yêu cầu nghề",
      "special_abilities": "Năng lực đặc biệt"
    }}
  ]
}}

Lưu ý quan trọng:
1. Thiết lập giai đoạn nghề chính phải chi tiết, thể hiện lộ trình trưởng thành rõ ràng; tên giai đoạn cần có bản sắc
2. Chọn nghề phù hợp thể loại tiểu thuyết:
   - Tu tiên: kiếm tu, thể tu, pháp tu, phù tu...; giai đoạn như: luyện khí, trúc cơ, kim đan, nguyên anh...
   - Huyền huyễn: chiến sĩ, pháp sư, thích khách...; giai đoạn như: kiến tập, sơ cấp, trung cấp, cao cấp...
   - Đô thị dị năng: phân loại dị năng giả; giai đoạn như: thức tỉnh, sơ giai, trung giai, cao giai...
   - Khoa huyễn tương lai: chiến sĩ gene, sư cơ giáp...; giai đoạn như: cấp E, D, C, B...
3. Nghề phụ cần thực dụng và thú vị, ví dụ: luyện đan sư, luyện khí sư, trận pháp sư, thuần thú sư, y sư...
4. Mọi nghề phải khớp thiết lập bối cảnh thế giới tổng thể của dự án
5. Mô tả giai đoạn phải ngắn gọn rõ ràng, thể hiện đặc trưng cốt lõi của giai đoạn đó
6. **Chỉ trả về object JSON thuần, không thêm chữ giải thích hay đánh dấu markdown**
"""
        
        return prompt
    
    @staticmethod
    async def parse_and_save_careers(
        career_data: Dict[str, Any],
        project_id: str,
        db: AsyncSession
    ) -> Dict[str, List[str]]:
        """
        解析AI返回的职业数据并保存到数据库
        
        Args:
            career_data: AI返回的职业数据（已解析为dict）
            project_id: 项目ID
            db: 数据库会话
            
        Returns:
            {"main_careers": [...], "sub_careers": [...]} 创建的职业名称列表
        """
        result = {
            "main_careers": [],
            "sub_careers": []
        }
        
        # 保存主职业
        for idx, career_info in enumerate(career_data.get("main_careers", [])):
            try:
                stages_json = json.dumps(career_info.get("stages", []), ensure_ascii=False)
                attribute_bonuses = career_info.get("attribute_bonuses")
                attribute_bonuses_json = json.dumps(attribute_bonuses, ensure_ascii=False) if attribute_bonuses else None
                
                career = Career(
                    project_id=project_id,
                    name=career_info.get("name", f"Nghề chính chưa đặt tên {idx+1}"),
                    type="main",
                    description=career_info.get("description"),
                    category=career_info.get("category"),
                    stages=stages_json,
                    max_stage=career_info.get("max_stage", 10),
                    requirements=career_info.get("requirements"),
                    special_abilities=career_info.get("special_abilities"),
                    worldview_rules=career_info.get("worldview_rules"),
                    attribute_bonuses=attribute_bonuses_json,
                    source="ai"
                )
                db.add(career)
                await db.flush()
                result["main_careers"].append(career.name)
                logger.info(f"  ✅ 创建主职业：{career.name}")
            except Exception as e:
                logger.error(f"  ❌ 创建主职业失败：{str(e)}")
                continue
        
        # 保存副职业
        for idx, career_info in enumerate(career_data.get("sub_careers", [])):
            try:
                stages_json = json.dumps(career_info.get("stages", []), ensure_ascii=False)
                attribute_bonuses = career_info.get("attribute_bonuses")
                attribute_bonuses_json = json.dumps(attribute_bonuses, ensure_ascii=False) if attribute_bonuses else None
                
                career = Career(
                    project_id=project_id,
                    name=career_info.get("name", f"Nghề phụ chưa đặt tên {idx+1}"),
                    type="sub",
                    description=career_info.get("description"),
                    category=career_info.get("category"),
                    stages=stages_json,
                    max_stage=career_info.get("max_stage", 5),
                    requirements=career_info.get("requirements"),
                    special_abilities=career_info.get("special_abilities"),
                    worldview_rules=career_info.get("worldview_rules"),
                    attribute_bonuses=attribute_bonuses_json,
                    source="ai"
                )
                db.add(career)
                await db.flush()
                result["sub_careers"].append(career.name)
                logger.info(f"  ✅ 创建副职业：{career.name}")
            except Exception as e:
                logger.error(f"  ❌ 创建副职业失败：{str(e)}")
                continue
        
        await db.commit()
        
        return result
    
    @staticmethod
    async def get_project_careers_summary(project_id: str, db: AsyncSession) -> Dict[str, Any]:
        """
        获取项目职业体系摘要
        
        Args:
            project_id: 项目ID
            db: 数据库会话
            
        Returns:
            职业体系摘要信息
        """
        result = await db.execute(
            select(Career).where(Career.project_id == project_id)
        )
        careers = result.scalars().all()
        
        main_careers = []
        sub_careers = []
        
        for career in careers:
            career_info = {
                "id": career.id,
                "name": career.name,
                "category": career.category,
                "max_stage": career.max_stage
            }
            
            if career.type == "main":
                main_careers.append(career_info)
            else:
                sub_careers.append(career_info)
        
        return {
            "main_careers": main_careers,
            "sub_careers": sub_careers,
            "total_count": len(careers)
        }


# 创建全局服务实例
career_service = CareerService()