"""提示词管理服务"""
from typing import Dict, Any, Optional
import json
from app.services.skill_loader import get_all_skills_cached


class WritingStyleManager:
    """写作风格管理器"""
    
    @staticmethod
    def apply_style_to_prompt(base_prompt: str, style_content: str) -> str:
        """
        将写作风格应用到基础提示词中
        
        注意：写作风格已通过 system_prompt 注入（system_prompt_with_style），
        此方法仅追加输出指令，不再重复注入 style_content，避免风格信息被注入两次。
        
        Args:
            base_prompt: 基础提示词
            style_content: 风格要求内容（已通过 system_prompt 注入，此处不使用）
            
        Returns:
            追加输出指令后的提示词
        """
        # 写作风格已在 system_prompt 中注入，此处只追加输出格式指令
        return f"{base_prompt}\n\nHãy xuất trực tiếp nội dung chính văn chương, không kèm tiêu đề chương hay chữ giải thích khác."


class PromptService:
    """提示词模板管理"""

    NOVEL_COVER_PROMPT_TEMPLATE = """Tạo một minh họa bìa tiểu thuyết chất lượng cao, phù hợp bìa sách khổ dọc.

Tiêu đề tiểu thuyết là: “{title}”.
Thể loại: {genre}. Chủ đề cốt lõi: {theme}. Tóm tắt câu chuyện: {description}

Hình ảnh cần có cảm giác điện ảnh, tinh tế, giàu bầu không khí và biểu cảm cảm xúc, với điểm nhấn thị giác rõ ràng cùng hình tượng tượng trưng mạnh. Hãy ưu tiên kể chuyện thị giác và cảm xúc phù hợp thể loại tiểu thuyết, thay vì miêu tả máy móc một cảnh cụ thể.

Kết quả phải trông như bìa chuyên nghiệp kiểu tiểu thuyết mạng hoặc ấn bản giấy.

Yêu cầu cứng:
- Phải có chữ tiêu đề tiểu thuyết “{title}” ở vị trí nổi bật, sắp chữ đầy tính nghệ thuật và hòa quyện với phong cách thể loại {genre}.
- Bố cục dọc chuẩn bìa tiểu thuyết (tỉ lệ 2:3).
- Trong khung hình chỉ được có chữ tiêu đề; tuyệt đối không có tên tác giả, phụ đề hay chữ cái ngẫu nhiên không liên quan.
- Không logo.
- Không watermark.
- Không khung viền.
- Không phần tử UI.
- Không hiệu ứng mockup.

Ảnh cuối phải là một tác phẩm bìa sách hoàn chỉnh, chuyên nghiệp; minh họa nền và chữ tiêu đề phải bổ trợ lẫn nhau."""

    @classmethod
    async def build_novel_cover_prompt(
        cls,
        project: Any,
        user_id: str = None,
        db = None,
    ) -> str:
        """基于项目基础信息构建小说封面提示词，支持用户自定义模板"""
        title = (getattr(project, "title", "") or "Tiểu thuyết chưa đặt tên").strip()
        genre = (getattr(project, "genre", "") or "Chưa chỉ định thể loại").strip()
        theme = (getattr(project, "theme", "") or "Chưa chỉ định chủ đề").strip()
        description = (getattr(project, "description", "") or "Không có mô tả thêm").strip()

        compact_description = description[:300]
        template = await cls.get_template_with_fallback(
            "NOVEL_COVER_PROMPT_TEMPLATE",
            user_id=user_id,
            db=db,
        )
        return template.format(
            title=title,
            genre=genre,
            theme=theme,
            description=compact_description,
        )
    
    # ========== V2版本提示词模板（RTCO框架）==========
    
    # 世界构建提示词 V2（RTCO框架）
    WORLD_BUILDING = """<system>
Bạn là nhà thiết kế bối cảnh thế giới dày dạn, giỏi dựng bối cảnh chân thực, tự nhất quán cho tiểu thuyết thể loại {genre}.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ thiết kế]
Dựng thiết lập bối cảnh thế giới hoàn chỉnh cho tiểu thuyết «{title}».

[Yêu cầu cốt lõi]
- Khớp chủ đề: bối cảnh thế giới phải chống đỡ chủ đề "{theme}"
- Khớp mô tả: cung cấp nền hợp lý cho tình tiết trong phần giới thiệu
- Khớp thể loại: phù hợp đặc trưng thể loại {genre}
- Quy mô phù hợp: chọn mức thiết lập thích hợp theo đề tài
</task>

<input priority="P0">
[Thông tin dự án]
Tên sách: {title}
Thể loại: {genre}
Chủ đề: {theme}
Mô tả: {description}
</input>

<guidelines priority="P1">
[Nguyên tắc hướng dẫn theo thể loại]

**Đô thị hiện đại / ngôn tình / thanh xuân**:
- Thời gian: xã hội đương đại (thập niên 2020) hoặc cận tương lai (2030-2050)
- Tránh: khái niệm đồ sộ kiểu đại sụp đổ, kỷ nguyên, tận thế
- Trọng tâm: môi trường đô thị cụ thể, văn hóa công sở, hiện trạng xã hội

**Lịch sử / cổ đại**:
- Thời gian: triều đại lịch sử rõ ràng hoặc cổ đại hư cấu
- Trọng tâm: đặc trưng thời đại, lễ giáo, phân hóa giai cấp

**Huyền huyễn / tiên hiệp / tu chân**:
- Thời gian: giai đoạn cụ thể của nền văn minh tu luyện
- Trọng tâm: quy tắc tu luyện, môi trường linh khí, thế lực môn phái

**Khoa huyễn**:
- Thời gian: giai đoạn tương lai rõ ràng (vd: năm 2150, sơ kỳ kỷ nguyên liên sao)
- Trọng tâm: trình độ khoa học kỹ thuật, hình thái xã hội, bước ngoặt văn minh

**Kỳ ảo / phép thuật**:
- Thời gian: giai đoạn cụ thể của nền văn minh phép thuật
- Trọng tâm: hệ thống phép thuật, quan hệ chủng tộc, cục diện lục địa

**Kiểm soát quy mô thiết lập**:
- Đô thị hiện đại: tập trung một thành phố, ngành nghề, tầng lớp
- Thanh xuân học đường: môi trường trường học, đời sống học sinh, khó khăn trưởng thành
- Ngôn tình công sở: văn hóa công ty, đặc thù ngành, áp lực nghề nghiệp
- Đề tài sử thi: mới cần kiến trúc bối cảnh thế giới đồ sộ
</guidelines>

<output priority="P0">
[Định dạng đầu ra]
Tạo một object JSON gồm bốn trường sau, mỗi trường 300-500 chữ:

1. **time_period**(Bối cảnh thời gian và trạng thái xã hội)
   - Thiết lập bối cảnh thời gian quy mô phù hợp theo thể loại
   - Đề tài hiện đại: đặc trưng xã hội cụ thể (vd: Bắc Kinh 2024, ngành internet phát triển nhanh)
   - Đề tài lịch sử: triều đại và giai đoạn rõ ràng (vd: niên hiệu Gia Tĩnh nhà Minh, duyên hải dưới chính sách hải cấm)
   - Đề tài kỳ ảo: giai đoạn phát triển văn minh, cụ thể chứ không rỗng
   - Làm rõ mâu thuẫn cốt lõi thời đại và lo âu xã hội

2. **location**(Môi trường không gian và đặc trưng địa lý)
   - Môi trường không gian nơi câu chuyện chủ yếu diễn ra
   - Đề tài hiện đại: tên thành phố cụ thể hoặc loại thành phố
   - Môi trường ảnh hưởng cách sinh tồn của cư dân thế nào
   - Mô tả cảnh biểu tượng

3. **atmosphere**(Trải nghiệm giác quan và gam cảm xúc)
   - Chi tiết giác quan khiến người đọc như đang ở đó (thị giác, thính giác, khứu giác)
   - Phong cách thẩm mỹ và gam màu
   - Trạng thái tâm lý cư dân và bầu không khí cảm xúc
   - Họa âm với cảm xúc chủ đề

4. **rules**(Quy tắc thế giới và cấu trúc xã hội)
   - Quy tắc cốt lõi vận hành thế giới
   - Đề tài hiện đại: quy tắc xã hội, luật ngầm ngành, quy tắc quan hệ người
   - Đề tài kỳ ảo: hệ lực lượng, đẳng cấp xã hội, phân bổ tài nguyên
   - Cấu trúc quyền lực và cục diện lợi ích
   - Điều cấm xã hội và hậu quả

[Quy chuẩn định dạng]
- Xuất JSON thuần, bắt đầu bằng {{ và kết thúc bằng }}
- Không có đánh dấu markdown hay ký hiệu khối mã
- Giá trị trường là đoạn văn đầy đủ
- Không bọc nội dung bằng ký hiệu đặc biệt
- Cung cấp nội dung gốc phong phú

[Ví dụ JSON]
{{
  "time_period": "Mô tả chi tiết bối cảnh thời gian và trạng thái xã hội (300-500 chữ)",
  "location": "Mô tả chi tiết môi trường không gian và đặc trưng địa lý (300-500 chữ)",
  "atmosphere": "Mô tả chi tiết trải nghiệm giác quan và gam cảm xúc (300-500 chữ)",
  "rules": "Mô tả chi tiết quy tắc thế giới và cấu trúc xã hội (300-500 chữ)"
}}
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Khớp mô tả: cung cấp nền hợp lý cho tình tiết phần giới thiệu
✅ Khớp thể loại: phù hợp đặc trưng của {genre}
✅ Bám chủ đề: chống đỡ chủ đề "{theme}"
✅ Cụ thể hóa: dùng chi tiết cụ thể thay vì khái niệm rỗng
✅ Tự nhất quán logic: mọi thiết lập nâng đỡ lẫn nhau

[Điều cấm]
❌ Tạo thiết lập không khớp thể loại
❌ Dùng bối cảnh thế giới đồ sộ cho đề tài quy mô nhỏ
❌ Dùng diễn đạt khuôn mẫu, rỗng
❌ Xuất markdown hoặc đánh dấu khối mã
</constraints>"""

    # 批量角色生成提示词 V2（RTCO框架）
    CHARACTERS_BATCH_GENERATION = """<system>
Bạn là chuyên gia thiết lập nhân vật, giỏi tạo nhân vật đầy đặn, đa chiều cho tiểu thuyết thể loại {genre}.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ tạo]
Tạo {count} thực thể nhân vật và tổ chức.

[Yêu cầu số lượng - tuân thủ nghiêm]
Mảng phải chứa đúng {count} object, không hơn không kém.

[Phân bổ loại thực thể]
- Ít nhất 1 nhân vật chính (protagonist)
- Nhiều nhân vật phụ (supporting)
- Có thể gồm phản diện (antagonist)
- Có thể gồm 1-2 tổ chức ảnh hưởng cao (power_level: 70-95)
</task>

<worldview priority="P0">
[Thông tin bối cảnh thế giới]
Bối cảnh thời gian: {time_period}
Vị trí địa lý: {location}
Gam bầu không khí: {atmosphere}
Quy tắc thế giới: {rules}

Chủ đề: {theme}
Thể loại: {genre}
</worldview>

<requirements priority="P1">
[Yêu cầu đặc biệt]
{requirements}
</requirements>

<output priority="P0">
[Định dạng đầu ra]
Trả về mảng JSON thuần, mỗi object gồm:

**Object nhân vật**:
{{
  "name": "Họ tên nhân vật",
  "age": 25,
  "gender": "nam/nữ/khác",
  "is_organization": false,
  "role_type": "protagonist/supporting/antagonist",
  "personality": "Đặc điểm tính cách (100-200 chữ): tính cách cốt lõi, ưu/nhược, thói quen đặc biệt",
  "background": "Câu chuyện nền (100-200 chữ): gia cảnh, trải nghiệm trưởng thành, bước ngoặt quan trọng",
  "appearance": "Mô tả ngoại hình (50-100 chữ): chiều cao, vóc dáng, khuôn mặt, phong cách ăn mặc",
  "traits": ["Đặc điểm 1", "Đặc điểm 2", "Đặc điểm 3"],
  "relationships_array": [
    {{
      "target_character_name": "Tên nhân vật đã tạo",
      "relationship_type": "Loại quan hệ",
      "intimacy_level": 75,
      "description": "Mô tả quan hệ"
    }}
  ],
  "organization_memberships": [
    {{
      "organization_name": "Tên tổ chức đã tạo",
      "position": "Chức vụ",
      "rank": 5,
      "loyalty": 80
    }}
  ]
}}

**Object tổ chức**:
{{
  "name": "Tên tổ chức",
  "is_organization": true,
  "role_type": "supporting",
  "personality": "Đặc tính tổ chức (100-200 chữ): cách vận hành, ý niệm cốt lõi, phong cách hành sự",
  "background": "Bối cảnh tổ chức (100-200 chữ): lịch sử thành lập, quá trình phát triển, sự kiện quan trọng",
  "appearance": "Biểu hiện bên ngoài (50-100 chữ): vị trí trụ sở, công trình biểu tượng",
  "organization_type": "Loại tổ chức",
  "organization_purpose": "Mục đích tổ chức",
  "organization_members": ["Thành viên 1", "Thành viên 2"],
  "power_level": 85,
  "location": "Địa điểm hoặc khu vực hoạt động chính",
  "motto": "Châm ngôn, khẩu hiệu hoặc tôn chỉ tổ chức",
  "color": "Màu đại diện",
  "traits": []
}}

[Tham chiếu loại quan hệ]
- Gia tộc: cha, mẹ, anh/em trai, chị/em gái, con cái, vợ/chồng, người yêu
- Xã giao: sư phụ, đệ tử, bạn, bạn học, đồng nghiệp, hàng xóm, tri kỷ
- Nghề nghiệp: cấp trên, cấp dưới, đối tác
- Đối địch: kẻ thù, thù nhà, đối thủ cạnh tranh, tử thù

[Phạm vi số]
- intimacy_level: -100 đến 100 (âm nghĩa là đối địch)
- loyalty: 0 đến 100
- rank: 0 đến 10 (cấp chức vụ)
- power_level: 70 đến 95 (ảnh hưởng tổ chức)
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Số lượng chính xác: mảng phải chứa {count} object
✅ Khớp bối cảnh: thiết lập nhân vật nhất quán với thế giới
✅ Có chiều sâu: tính cách và nền phải đầy đặn
✅ Mạng quan hệ: giữa các nhân vật hình thành quan hệ hợp lý
✅ Tổ chức hợp lý: tổ chức là lực lượng then chốt đẩy cốt truyện

[Ràng buộc quan hệ]
✅ relationships_array chỉ được tham chiếu nhân vật đã xuất hiện trong lô này
✅ organization_memberships chỉ được tham chiếu tổ chức trong lô này
✅ relationships_array của nhân vật đầu tiên phải là [] rỗng
✅ Cấm ảo giác: không tham chiếu nhân vật/tổ chức không tồn tại

[Ràng buộc định dạng]
✅ Xuất mảng JSON thuần, không đánh dấu markdown
✅ Nghiêm cấm dùng ký hiệu đặc biệt trong mô tả nội dung (dấu ngoặc kép, ngoặc vuông, ngoặc sách...)
✅ Danh từ riêng viết trực tiếp, không dùng ký hiệu bao quanh

[Điều cấm]
❌ Số lượng tạo không khớp (nhiều hơn hoặc ít hơn {count})
❌ Trích dẫn nhân vật hoặc tổ chức không tồn tại
❌ Tạo tổ chức tầm thường, ảnh hưởng thấp
❌ Dùng markdown hoặc đánh dấu khối mã
❌ Dùng ký hiệu đặc biệt trong mô tả
</constraints>"""

    # 大纲生成提示词 V2（RTCO框架）
    OUTLINE_CREATE = """<system>
Bạn là nhà văn và biên kịch tiểu thuyết dày kinh nghiệm, giỏi thiết kế mở đầu hấp dẫn cho tiểu thuyết thể loại {genre}.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ sáng tác]
Tạo dàn ý {chapter_count} chương mở đầu cho tiểu thuyết «{title}».

[Lưu ý quan trọng]
Đây là phần mở đầu của quá trình khởi tạo dự án, không phải dàn ý hoàn chỉnh:
- Hoàn thành thiết lập mở đầu và giới thiệu bối cảnh thế giới
- Giới thiệu nhân vật chính, thiết lập quan hệ ban đầu
- Gài cắm xung đột cốt lõi và móc câu nghi vấn
- Đặt nền tảng cho diễn biến tình tiết về sau
- Không cần khép kín hoàn chỉnh, chừa không gian cho việc viết tiếp
</task>

<project priority="P0">
[Thông tin dự án]
Tên sách: {title}
Chủ đề: {theme}
Thể loại: {genre}
Số chương mở đầu: {chapter_count}
Góc kể chuyện: {narrative_perspective}
</project>

<worldview priority="P1">
[Bối cảnh thế giới]
Bối cảnh thời gian: {time_period}
Vị trí địa lý: {location}
Gam bầu không khí: {atmosphere}
Quy tắc thế giới: {rules}
</worldview>

<characters priority="P1">
[Thông tin nhân vật]
{characters_info}
</characters>

<mcp_context priority="P2">
{mcp_references}
</mcp_context>

<requirements priority="P1">
[Yêu cầu khác]
{requirements}
</requirements>

<output priority="P0">
[Định dạng đầu ra]
Trả về mảng JSON chứa {chapter_count} object chương:

[
  {{
   "chapter_number": 1,
   "title": "Tiêu đề chương",
   "summary": "Tóm tắt chương (500-1000 chữ): tình tiết chính, tương tác nhân vật, sự kiện then chốt, xung đột và bước ngoặt",
   "scenes": ["Mô tả cảnh 1", "Mô tả cảnh 2", "Mô tả cảnh 3"],
   "characters": [
     {{"name": "Tên nhân vật 1", "type": "character"}},
     {{"name": "Tên tổ chức/thế lực 1", "type": "organization"}}
   ],
   "key_points": ["Điểm tình tiết 1", "Điểm tình tiết 2"],
   "emotion": "Gam cảm xúc chương này",
   "goal": "Mục tiêu kể chuyện chương này"
 }},
 {{
   "chapter_number": 2,
   "title": "Tiêu đề chương",
   "summary": "Tóm tắt chương...",
   "scenes": ["Cảnh 1", "Cảnh 2"],
   "characters": [
     {{"name": "Tên nhân vật 2", "type": "character"}},
     {{"name": "Tên tổ chức 2", "type": "organization"}}
   ],
   "key_points": ["Điểm chính 1", "Điểm chính 2"],
   "emotion": "Gam cảm xúc",
   "goal": "Mục tiêu kể chuyện"
 }}
]

[Giải thích trường characters]
- type là "character" nghĩa là nhân vật cá nhân; type là "organization" nghĩa là tổ chức/thế lực/môn phái/bang hội...
- Phải phân biệt nhân vật và tổ chức, không coi tổ chức như nhân vật

[Quy chuẩn định dạng]
- Xuất mảng JSON thuần, không đánh dấu markdown
- Nghiêm cấm dùng ký hiệu đặc biệt trong mô tả nội dung
- Danh từ riêng viết trực tiếp
- Cấu trúc trường khớp hoàn toàn với chương hiện có
</output>

<constraints>
[Yêu cầu dàn ý mở đầu]
✅ Thiết lập mở đầu: vài chương đầu hoàn thành giới thiệu bối cảnh thế giới, nhân vật chính xuất hiện, trạng thái ban đầu
✅ Đưa vào xung đột: gợi ra xung đột cốt lõi, nhưng không vội triển khai
✅ Nhân vật xuất hiện: các nhân vật chính lần lượt xuất hiện, thể hiện tính cách và quan hệ
✅ Kiểm soát nhịp độ: phần mở đầu không nên quá nhanh, cho người đọc thời gian thích nghi
✅ Tạo nghi vấn: gài cắm phục bút và móc câu, chừa không gian cho việc viết tiếp
✅ Thống nhất góc nhìn: dùng góc nhìn {narrative_perspective}
✅ Nghệ thuật để trống: kết thúc không khép lại quá chặt, chừa không gian phát triển

[Bắt buộc tuân thủ]
✅ Số lượng chính xác: mảng chứa {chapter_count} object chương
✅ Khớp thể loại: tình tiết phù hợp đặc trưng thể loại {genre}
✅ Bám chủ đề: thể hiện chủ đề "{theme}"
✅ Định vị mở đầu: là khởi đầu chứ không phải câu chuyện hoàn chỉnh
✅ Mô tả chi tiết: mỗi summary 500-1000 chữ

[Điều cấm]
❌ Xuất markdown hoặc đánh dấu khối mã
❌ Dùng ký hiệu đặc biệt trong mô tả
❌ Cố kết thúc câu chuyện ngay ở phần mở đầu
❌ Nhịp độ quá nhanh, quá tải thông tin
</constraints>"""
    
    # 大纲续写提示词 V2（RTCO框架 - 简化版）
    OUTLINE_CONTINUE = """<system>
Bạn là nhà văn và biên kịch tiểu thuyết dày kinh nghiệm, giỏi viết tiếp dàn ý tiểu thuyết thể loại {genre}.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ viết tiếp]
Dựa trên nội dung {current_chapter_count} chương đã có, viết tiếp dàn ý từ chương {start_chapter} đến chương {end_chapter} (tổng {chapter_count} chương).

[Giai đoạn tình tiết hiện tại]
{plot_stage_instruction}

[Hướng phát triển câu chuyện]
{story_direction}
</task>

<project priority="P0">
[Thông tin dự án]
Tên sách: {title}
Chủ đề: {theme}
Thể loại: {genre}
Góc kể chuyện: {narrative_perspective}
</project>

<worldview priority="P1">
[Bối cảnh thế giới]
Bối cảnh thời gian: {time_period}
Vị trí địa lý: {location}
Gam bầu không khí: {atmosphere}
Quy tắc thế giới: {rules}
</worldview>

<previous_context priority="P0">
{recent_outlines}
</previous_context>

<characters priority="P0">
[Toàn bộ thông tin nhân vật]
{characters_info}
</characters>

<user_input priority="P0">
[Thông tin người dùng]
Số chương viết tiếp: {chapter_count} chương
Giai đoạn tình tiết: {plot_stage_instruction}
Hướng phát triển câu chuyện: {story_direction}
Yêu cầu khác: {requirements}
</user_input>

<mcp_context priority="P2">
{mcp_references}
</mcp_context>

<output priority="P0">
[Định dạng đầu ra]
Trả về mảng JSON từ chương {start_chapter} đến chương {end_chapter} (tổng {chapter_count} object):

[
  {{
   "chapter_number": {start_chapter},
   "title": "Tiêu đề chương",
   "summary": "Tóm tắt chương (500-1000 chữ): tình tiết chính, tương tác nhân vật, sự kiện then chốt, xung đột và bước ngoặt",
   "scenes": ["Mô tả cảnh 1", "Mô tả cảnh 2", "Mô tả cảnh 3"],
   "characters": [
     {{"name": "Tên nhân vật 1", "type": "character"}},
     {{"name": "Tên tổ chức/thế lực 1", "type": "organization"}}
   ],
   "key_points": ["Điểm tình tiết 1", "Điểm tình tiết 2"],
   "emotion": "Gam cảm xúc chương này",
   "goal": "Mục tiêu kể chuyện chương này"
 }},
 {{
   "chapter_number": {start_chapter} + 1,
   "title": "Tiêu đề chương",
   "summary": "Tóm tắt chương...",
   "scenes": ["Cảnh 1", "Cảnh 2"],
   "characters": [
     {{"name": "Tên nhân vật 2", "type": "character"}},
     {{"name": "Tên tổ chức 2", "type": "organization"}}
   ],
   "key_points": ["Điểm chính 1", "Điểm chính 2"],
   "emotion": "Gam cảm xúc",
   "goal": "Mục tiêu kể chuyện"
 }}
]

[Giải thích trường characters]
- type là "character" nghĩa là nhân vật cá nhân; type là "organization" nghĩa là tổ chức/thế lực/môn phái/bang hội...
- Phải phân biệt nhân vật và tổ chức, không coi tổ chức như nhân vật

[Quy chuẩn định dạng]
- Xuất mảng JSON thuần, không đánh dấu markdown
- Nghiêm cấm dùng ký hiệu đặc biệt trong mô tả nội dung
- Danh từ riêng viết trực tiếp
- Cấu trúc trường khớp hoàn toàn với chương hiện có
</output>

<constraints>
[Yêu cầu viết tiếp]
✅ Tình tiết liền mạch: nối tự nhiên với phần trước, giữ tính liên tục
✅ Phát triển nhân vật: tuân theo quỹ đạo trưởng thành của nhân vật, tận dụng đầy đủ thông tin nhân vật
✅ Giai đoạn tình tiết: tuân theo yêu cầu {plot_stage_instruction}
✅ Phong cách nhất quán: giữ cùng phong cách và mức độ chi tiết với các chương đã có
✅ Dàn ý chi tiết: phân tích đầy đủ thông tin trường structure của dàn ý 10 chương gần nhất

[Bắt buộc tuân thủ]
✅ Số lượng chính xác: mảng chứa {chapter_count} chương
✅ Đánh số đúng: bắt đầu từ chương {start_chapter}
✅ Mô tả chi tiết: mỗi summary 500-1000 chữ
✅ Kế trước mở sau: nối tự nhiên với phần trước

[Điều cấm]
❌ Xuất markdown hoặc đánh dấu khối mã
❌ Dùng ký hiệu đặc biệt trong mô tả
❌ Mâu thuẫn hoặc đứt gãy với phần trước
❌ Bỏ qua phát triển nhân vật đã có
❌ Bỏ qua manh mối tình tiết trong dàn ý gần nhất
</constraints>"""
    
    # 章节生成 - 1-N模式（第1章）
    CHAPTER_GENERATION_ONE_TO_MANY = """<system>
Bạn là tác giả của «{project_title}», một nhà văn tiểu thuyết mạng chuyên về thể loại {genre}.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ sáng tác]
Viết toàn bộ chính văn chương {chapter_number} «{chapter_title}».

[Yêu cầu cơ bản]
- Số chữ mục tiêu: {target_word_count} chữ (cho phép lệch ±200 chữ)
- Góc kể chuyện: {narrative_perspective}
</task>

<outline priority="P0">
[Dàn ý chương này - bắt buộc tuân thủ]
{chapter_outline}
</outline>

<characters priority="P1">
[Nhân vật chương này - tuân thủ nghiêm thiết lập nhân vật]
{characters_info}

⚠️ Lưu ý tương tác nhân vật:
- Hội thoại và hành vi giữa nhân vật phải khớp thiết lập quan hệ (vd: sư đồ, đối địch)
- Tình tiết liên quan tổ chức phải thể hiện thân phận và chức vụ của nhân vật trong tổ chức
- Biểu hiện năng lực nhân vật phải khớp nghề và giai đoạn đã thiết lập
</characters>

<careers priority="P2">
[Nghề nghiệp chương này]
{chapter_careers}
</careers>

<foreshadow_reminders priority="P2">
[🎯 Nhắc phục bút]
{foreshadow_reminders}
</foreshadow_reminders>

<memory priority="P2">
[Ghi nhớ liên quan]
{relevant_memories}
</memory>

<constraints>
[Bắt buộc tuân thủ]
✅ Đẩy tình tiết đúng theo dàn ý
✅ Giữ tính cách và cách nói của nhân vật nhất quán
✅ Tương tác nhân vật phải khớp thiết lập quan hệ (sư đồ, bạn bè, đối địch...)
✅ Tình tiết tổ chức phải thể hiện thân phận thành viên và cấp bậc chức vụ
✅ Kiểm soát số chữ trong phạm vi mục tiêu
✅ Nếu có nhắc phục bút, hãy gài hoặc thu hồi phục bút tương ứng trong chương này một cách hợp lý

[Điều cấm]
❌ Xuất tiêu đề chương, số thứ tự và siêu thông tin khác
❌ Dùng câu tổng kết kiểu AI như "Tóm lại", "Tóm tắt lại"
❌ Dùng câu hỏi tu từ mở ở phần kết
❌ Thêm chú thích tác giả hoặc ghi chú sáng tác
❌ Hành vi nhân vật vượt năng lực giai đoạn nghề của họ
</constraints>

<output>
[Quy chuẩn đầu ra]
Xuất trực tiếp chính văn tiểu thuyết, bắt đầu từ cảnh hoặc hành động.
Không cần lời mở đầu, kết hay chữ giải thích.

Bắt đầu sáng tác ngay:
</output>"""

    # 章节生成 - 1-1模式（第1章）
    CHAPTER_GENERATION_ONE_TO_ONE = """<system>
Bạn là tác giả của «{project_title}», một nhà văn tiểu thuyết mạng chuyên về thể loại {genre}.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task priority="P0">
[Nhiệm vụ sáng tác]
Viết toàn bộ chính văn chương {chapter_number} «{chapter_title}».

[Yêu cầu cơ bản]
- Số chữ mục tiêu: {target_word_count} chữ (cho phép lệch ±200 chữ)
- Góc kể chuyện: {narrative_perspective}
</task>

<outline priority="P0">
[Dàn ý chương này]
{chapter_outline}
</outline>

<characters priority="P1">
[Nhân vật chương này]
{characters_info}
</characters>

<careers priority="P2">
[Nghề nghiệp chương này]
{chapter_careers}
</careers>

<foreshadow_reminders priority="P2">
[🎯 Nhắc phục bút]
{foreshadow_reminders}
</foreshadow_reminders>

<memory priority="P2">
[Ghi nhớ liên quan]
{relevant_memories}
</memory>

<constraints>
[Bắt buộc tuân thủ]
✅ Đẩy tình tiết đúng theo dàn ý
✅ Giữ tính cách và cách nói của nhân vật nhất quán
✅ Số chữ phải được kiểm soát nghiêm trong số chữ mục tiêu
✅ Nếu có nhắc phục bút, hãy gài hoặc thu hồi phục bút tương ứng trong chương này một cách hợp lý

[Điều cấm]
❌ Xuất tiêu đề chương, số thứ tự và siêu thông tin khác
❌ Dùng câu tổng kết kiểu AI như "Tóm lại", "Tóm tắt lại"
❌ Thêm chú thích tác giả hoặc ghi chú sáng tác
❌ Số chữ tạo ra không được vượt số chữ mục tiêu
</constraints>

<output>
[Quy chuẩn đầu ra]
Xuất trực tiếp chính văn tiểu thuyết, bắt đầu từ cảnh hoặc hành động.
Không cần lời mở đầu, kết hay chữ giải thích.

Bắt đầu sáng tác ngay:
</output>"""

    # 章节生成 - 1-1模式（第2章及以后）
    CHAPTER_GENERATION_ONE_TO_ONE_NEXT = """<system>
Bạn là tác giả của «{project_title}», một nhà văn tiểu thuyết mạng chuyên về thể loại {genre}.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task priority="P0">
[Nhiệm vụ sáng tác]
Viết toàn bộ chính văn chương {chapter_number} «{chapter_title}».

[Yêu cầu cơ bản]
- Số chữ mục tiêu: {target_word_count} chữ (cho phép lệch ±200 chữ)
- Góc kể chuyện: {narrative_perspective}
</task>

<outline priority="P0">
[Dàn ý chương này]
{chapter_outline}
</outline>

<previous_chapter_summary priority="P1">
[Tóm tắt tình tiết chương trước]
{previous_chapter_summary}
</previous_chapter_summary>

<recent_context priority="P1">
[Tóm tắt các chương gần đây - tham chiếu mạch truyện]
{recent_chapters_context}
</recent_context>

<previous_chapter priority="P1">
[Toàn văn chương trước]
{previous_chapter_content}
</previous_chapter>

<characters priority="P1">
[Nhân vật chương này]
{characters_info}
</characters>

<careers priority="P2">
[Nghề nghiệp chương này]
{chapter_careers}
</careers>

<foreshadow_reminders priority="P2">
[🎯 Nhắc phục bút]
{foreshadow_reminders}
</foreshadow_reminders>

<memory priority="P2">
[Ghi nhớ liên quan]
{relevant_memories}
</memory>

<constraints>
[Bắt buộc tuân thủ]
✅ Đẩy tình tiết đúng theo dàn ý
✅ Nối tự nhiên với nội dung cuối chương trước, giữ tính liên tục
✅ Giữ tính cách và cách nói của nhân vật nhất quán
✅ Số chữ phải được kiểm soát nghiêm trong số chữ mục tiêu
✅ Nếu có nhắc phục bút, hãy gài hoặc thu hồi phục bút tương ứng trong chương này một cách hợp lý

[Điều cấm]
❌ Xuất tiêu đề chương, số thứ tự và siêu thông tin khác
❌ Dùng câu tổng kết kiểu AI như "Tóm lại", "Tóm tắt lại"
❌ Dùng câu hỏi tu từ mở ở phần kết
❌ Thêm chú thích tác giả hoặc ghi chú sáng tác
❌ Lặp lại sự kiện đã xảy ra ở chương trước
❌ Số chữ tạo ra không được vượt số chữ mục tiêu
</constraints>

<output>
[Quy chuẩn đầu ra]
Xuất trực tiếp chính văn tiểu thuyết, bắt đầu từ cảnh hoặc hành động.
Không cần lời mở đầu, kết hay chữ giải thích.

Bắt đầu sáng tác ngay:
</output>"""

    # 章节生成 - 1-N模式（第2章及以后）
    CHAPTER_GENERATION_ONE_TO_MANY_NEXT = """<system>
Bạn là tác giả của «{project_title}», một nhà văn tiểu thuyết mạng chuyên về thể loại {genre}.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ sáng tác]
Viết toàn bộ chính văn chương {chapter_number} «{chapter_title}».

[Yêu cầu cơ bản]
- Số chữ mục tiêu: {target_word_count} chữ (cho phép lệch ±200 chữ)
- Góc kể chuyện: {narrative_perspective}
</task>

<outline priority="P0">
[Dàn ý chương này - bắt buộc tuân thủ]
{chapter_outline}
</outline>

<recent_context priority="P1">
[Kế hoạch các chương gần đây - tham chiếu mạch truyện]
{recent_chapters_context}
</recent_context>

<continuation priority="P0">
[Mốc nối - bắt buộc tiếp nối]
Toàn văn chương trước:
"{continuation_point}"

[🔴 Tình tiết đã hoàn thành ở chương trước (cấm lặp lại!)]
{previous_chapter_summary}

⚠️ Cảnh báo nghiêm trọng:
1. "Tình tiết đã hoàn thành" và "mốc nối" ở trên là nội dung **đã được viết**
2. Chương này phải tiến tới **điểm tình tiết mới**, tuyệt đối không kể lại sự kiện đã xảy ra
3. Chương này phải tiếp nối tình huống cuối chương trước để phát triển tiếp, không nhắc lại toàn văn chương trước
4. Nếu chương trước kết thúc bằng hội thoại hoặc bối cảnh, hãy bắt đầu từ hành động, phản ứng hoặc chuyển cảnh sau đó
</continuation>

<characters priority="P1">
[Nhân vật chương này - tuân thủ nghiêm thiết lập nhân vật]
{characters_info}

⚠️ Lưu ý tương tác nhân vật:
- Hội thoại và hành vi giữa nhân vật phải khớp thiết lập quan hệ (vd: sư đồ, đối địch)
- Tình tiết liên quan tổ chức phải thể hiện thân phận và chức vụ của nhân vật trong tổ chức
- Biểu hiện năng lực nhân vật phải khớp nghề và giai đoạn đã thiết lập
</characters>

<careers priority="P2">
[Nghề nghiệp chương này]
{chapter_careers}
</careers>

<foreshadow_reminders priority="P1">
[🎯 Nhắc phục bút - cần chú ý]
{foreshadow_reminders}
</foreshadow_reminders>

<memory priority="P2">
[Ký ức liên quan - tham khảo]
{relevant_memories}
</memory>

<constraints>
[Bắt buộc tuân thủ]
✅ Đẩy tình tiết đúng theo dàn ý
✅ Tự nhiên tiếp nối phần cuối chương trước, không lặp lại sự kiện đã xảy ra
✅ Giữ tính cách và cách nói của nhân vật nhất quán
✅ Tương tác nhân vật phải khớp thiết lập quan hệ (sư đồ, bạn bè, đối địch...)
✅ Tình tiết tổ chức phải thể hiện thân phận thành viên và cấp bậc chức vụ
✅ Kiểm soát số chữ trong phạm vi mục tiêu
✅ Nếu có nhắc phục bút, hãy gài hoặc thu hồi phục bút tương ứng trong chương này một cách hợp lý

[🔴 Chỉ thị đặc biệt chống lặp]
✅ Kiểm tra phần mở đầu chương này có lặp nội dung "mốc nối" hay không
✅ Kiểm tra tình tiết chương này có lặp "tình tiết đã hoàn thành ở chương trước" hay không
✅ Đảm bảo chương này tiến tới sự kiện mới được dàn ý hoạch định

[Điều cấm]
❌ Xuất tiêu đề chương, số thứ tự và siêu thông tin khác
❌ Dùng câu tổng kết kiểu AI như "Tóm lại", "Tóm tắt lại"
❌ Dùng câu hỏi tu từ mở ở phần kết
❌ Thêm chú thích tác giả hoặc ghi chú sáng tác
❌ Kể lại sự kiện đã xảy ra ở chương trước (bao gồm miêu tả môi trường và hoạt động tâm lý)
❌ Dùng những câu sáo rỗng như "tiếp nối chương trước" hoặc "nối tiếp phần trên" ở phần mở đầu
❌ Hành vi nhân vật vượt năng lực giai đoạn nghề của họ
</constraints>

<output>
[Quy chuẩn đầu ra]
Xuất trực tiếp chính văn tiểu thuyết, bắt đầu từ cảnh hoặc hành động.
Không cần lời mở đầu, kết hay chữ giải thích.

Bắt đầu sáng tác ngay:
</output>"""

    # 单个角色生成提示词 V2（RTCO框架）
    SINGLE_CHARACTER_GENERATION = """<system>
Bạn là chuyên gia thiết lập nhân vật, giỏi tạo nhân vật tiểu thuyết đầy đặn, đa chiều.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ thiết kế]
Dựa trên nhu cầu người dùng và ngữ cảnh dự án, tạo một thiết lập nhân vật hoàn chỉnh.
</task>

<context priority="P0">
[Ngữ cảnh dự án]
{project_context}

[Nhu cầu người dùng]
{user_input}
</context>

<output priority="P0">
[Định dạng đầu ra]
Tạo object JSON thẻ nhân vật hoàn chỉnh:

{{
  "name": "Họ tên nhân vật (nếu người dùng không cung cấp thì tạo tên phù hợp với bối cảnh thế giới)",
  "age": "Tuổi (số cụ thể hoặc khoảng tuổi)",
  "gender": "nam/nữ/khác",
  "appearance": "Mô tả ngoại hình (100-150 chữ): chiều cao, vóc dáng, đặc điểm khuôn mặt, phong cách ăn mặc",
  "personality": "Đặc điểm tính cách (150-200 chữ): nét tính cách cốt lõi, ưu nhược điểm, thói quen đặc biệt",
  "background": "Câu chuyện nền (200-300 chữ): gia cảnh, trải nghiệm trưởng thành, bước ngoặt quan trọng, mối liên hệ với chủ đề",
  "traits": ["Đặc điểm 1", "Đặc điểm 2", "Đặc điểm 3"],
  "relationships_text": "Mô tả quan hệ giữa người với người bằng ngôn ngữ tự nhiên",
  "relationships": [
    {{
      "target_character_name": "Tên nhân vật đã tồn tại",
      "relationship_type": "Loại quan hệ",
      "intimacy_level": 75,
      "description": "Mô tả chi tiết quan hệ",
      "started_at": "Mốc thời gian trong truyện khi quan hệ bắt đầu (tuỳ chọn)"
    }}
  ],
  "organization_memberships": [
    {{
      "organization_name": "Tên tổ chức đã tồn tại",
      "position": "Tên chức vụ",
      "rank": 8,
      "loyalty": 80,
      "joined_at": "Thời điểm gia nhập (tuỳ chọn)",
      "status": "active"
    }}
  ],
  "career_info": {{
    "main_career_name": "Tên nghề chọn từ danh sách nghề chính khả dụng",
    "main_career_stage": 5,
    "sub_careers": [
      {{
        "career_name": "Tên nghề chọn từ danh sách nghề phụ khả dụng",
        "stage": 3
      }}
    ]
  }}
}}

[Giải thích thông tin nghề nghiệp]
Nếu ngữ cảnh dự án có danh sách nghề:
- Nghề chính: chọn nghề phù hợp nhất với nhân vật từ danh sách "nghề chính khả dụng"
- Giai đoạn nghề chính: thiết lập giai đoạn hợp lý theo thực lực nhân vật (từ 1 đến max_stage)
- Nghề phụ: có thể chọn 0-2 nghề phụ
- ⚠️ Điền Tên nghề thay vì ID, hệ thống sẽ tự động đối chiếu
- Lựa chọn nghề phải rất phù hợp với bối cảnh, năng lực và định vị nhân vật

[Tham chiếu loại quan hệ]
- Gia tộc: cha, mẹ, anh/em trai, chị/em gái, con cái, vợ/chồng, người yêu
- Xã giao: sư phụ, đệ tử, bạn, bạn học, đồng nghiệp, hàng xóm, tri kỷ
- Nghề nghiệp: cấp trên, cấp dưới, đối tác
- Đối địch: kẻ thù, thù nhà, đối thủ cạnh tranh, tử thù

[Phạm vi số]
- intimacy_level: -100 đến 100 (âm nghĩa là đối địch)
- loyalty: 0 đến 100
- rank: 0 đến 10
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Phù hợp bối cảnh thế giới: thiết lập nhân vật nhất quán với bối cảnh thế giới của dự án
✅ Liên hệ chủ đề: câu chuyện nền gắn với chủ đề dự án
✅ Đa chiều đầy đặn: tính cách phức tạp, có mâu thuẫn, không rập khuôn
✅ Phục vụ câu chuyện: thiết lập phải thúc đẩy diễn biến tình tiết
✅ Phù hợp nghề: lựa chọn nghề phải rất phù hợp với nhân vật

[Yêu cầu định vị nhân vật]
✅ Nhân vật chính: có không gian trưởng thành và động lực mục tiêu
✅ Phản diện: có động cơ hợp lý, không rập khuôn
✅ Nhân vật phụ: có nét riêng, không phải công cụ

[Ràng buộc quan hệ]
✅ relationships chỉ được tham chiếu nhân vật đã tồn tại
✅ organization_memberships chỉ được tham chiếu tổ chức đã tồn tại
✅ Khi không có quan hệ hoặc tổ chức, mảng tương ứng phải là []

[Ràng buộc định dạng]
✅ Xuất object JSON thuần, không đánh dấu markdown
✅ Nghiêm cấm dùng ký hiệu đặc biệt trong mô tả nội dung
✅ Danh từ riêng viết trực tiếp

[Điều cấm]
❌ Xuất markdown hoặc đánh dấu khối mã
❌ Dùng ký hiệu đặc biệt trong mô tả (ngoặc kép, ngoặc vuông...)
❌ Trích dẫn nhân vật hoặc tổ chức không tồn tại
❌ Thiết lập nhân vật rập khuôn
</constraints>"""

    # 单个组织生成提示词 V2（RTCO框架）
    SINGLE_ORGANIZATION_GENERATION = """<system>
Bạn là chuyên gia thiết lập tổ chức, giỏi tạo thiết lập tổ chức/thế lực hoàn chỉnh.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ thiết kế]
Dựa trên nhu cầu người dùng và ngữ cảnh dự án, tạo một thiết lập tổ chức/thế lực hoàn chỉnh.
</task>

<context priority="P0">
[Ngữ cảnh dự án]
{project_context}

[Nhu cầu người dùng]
{user_input}
</context>

<output priority="P0">
[Định dạng đầu ra]
Tạo object JSON thiết lập tổ chức hoàn chỉnh:

{{
  "name": "Tên tổ chức (nếu người dùng không cung cấp thì tạo tên phù hợp với bối cảnh thế giới)",
  "is_organization": true,
  "organization_type": "Loại tổ chức (bang phái/công ty/môn phái/học viện/cơ quan chính phủ/tổ chức tôn giáo...) ",
  "personality": "Đặc tính tổ chức (150-200 chữ): ý niệm cốt lõi, phong cách hành sự, giá trị văn hóa, cách vận hành",
  "background": "Bối cảnh tổ chức (200-300 chữ): lịch sử thành lập, quá trình phát triển, sự kiện quan trọng, địa vị hiện tại",
  "appearance": "Biểu hiện bên ngoài (100-150 chữ): vị trí trụ sở, công trình biểu tượng, biểu trưng tổ chức, đồng phục...",
  "organization_purpose": "Mục đích và tôn chỉ tổ chức: mục tiêu rõ ràng, tầm nhìn dài hạn, nguyên tắc hành động",
  "power_level": 75,
  "location": "Địa điểm: khu vực hoạt động chính, phạm vi thế lực",
  "motto": "Châm ngôn hoặc khẩu hiệu tổ chức",
  "traits": ["Đặc trưng 1", "Đặc trưng 2", "Đặc trưng 3"],
  "color": "Màu đại diện tổ chức (ví dụ: đỏ sẫm, vàng, đen...)",
  "organization_members": ["Thành viên quan trọng 1", "Thành viên quan trọng 2", "Thành viên quan trọng 3"]
}}

[Giải thích trường]
- power_level: số nguyên 0-100, thể hiện ảnh hưởng trong thế giới
- organization_members: danh sách tên thành viên quan trọng trong tổ chức (có thể liên kết nhân vật đã tồn tại)
- Thời điểm thành lập: mô tả trong background
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Phù hợp bối cảnh thế giới: thiết lập tổ chức nhất quán với bối cảnh thế giới của dự án
✅ Liên hệ chủ đề: bối cảnh gắn với chủ đề dự án
✅ Thúc đẩy tình tiết: tổ chức có thể thúc đẩy diễn biến câu chuyện
✅ Có cấu trúc tầng bậc: bên trong có cấp bậc và cơ cấu rõ ràng
✅ Tương tác thế lực: có quan hệ tương tác với các thế lực khác

[Yêu cầu định vị tổ chức]
✅ Cần thiết cho câu chuyện: không phải phông nền có cũng được không có cũng xong
✅ Mục tiêu hợp lý: không quá lý tưởng hóa hoặc rập khuôn
✅ Chi tiết cụ thể: mô tả chi tiết, rõ ràng, tránh chung chung

[Ràng buộc định dạng]
✅ Xuất object JSON thuần, không đánh dấu markdown
✅ Nghiêm cấm dùng ký hiệu đặc biệt trong mô tả nội dung
✅ Danh từ riêng viết trực tiếp

[Điều cấm]
❌ Xuất markdown hoặc đánh dấu khối mã
❌ Dùng ký hiệu đặc biệt trong mô tả (ngoặc kép, ngoặc vuông...)
❌ Thiết lập quá lý tưởng hóa hoặc rập khuôn
❌ Mô tả chung chung
</constraints>"""

    # 情节分析提示词 V2（RTCO框架 + 伏笔ID追踪）
    PLOT_ANALYSIS = """<system>
Bạn là biên tập viên tiểu thuyết và chuyên gia phân tích cốt truyện, giỏi mổ xẻ sâu nội dung chương.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ phân tích]
Phân tích toàn diện các yếu tố tình tiết, móc câu, phục bút, xung đột và diễn biến nhân vật của chương {chapter_number} «{title}».

[🔴 Nhiệm vụ theo dõi phục bút (quan trọng)]
Hệ thống đã cung cấp [danh sách phục bút đã gài]. Khi nhận diện chương có thu hồi phục bút:
1. Bắt buộc tìm ID phục bút tương ứng trong danh sách
2. Dùng trường reference_foreshadow_id để liên kết trong mảng foreshadows
3. Nếu không thể xác định đó là phục bút nào, điền null vào reference_foreshadow_id
</task>

<chapter priority="P0">
[Thông tin chương]
Chương: chương {chapter_number}
Tiêu đề: {title}
Số chữ: {word_count} chữ

[Nội dung chương]
{content}
</chapter>

<existing_foreshadows priority="P1">
[Danh sách phục bút đã gài - dùng để đối chiếu thu hồi]
Dưới đây là các phục bút đã gài trong dự án nhưng chưa được thu hồi. Nếu phát hiện nội dung chương thu hồi một phục bút, hãy dùng ID tương ứng:

{existing_foreshadows}
</existing_foreshadows>

<characters priority="P1">
[Thông tin nhân vật dự án - dùng để phân tích trạng thái nhân vật]
Dưới đây là danh sách nhân vật đã có trong dự án. Khi phân tích character_states và relationship_changes, hãy dùng chính xác tên các nhân vật này:

{characters_info}
</characters>

<analysis_framework priority="P0">
[Các chiều phân tích]

**1. Móc câu tình tiết (Hooks)**
Nhận diện các yếu tố then chốt thu hút người đọc:
- Móc câu hồi hộp: bí ẩn, câu hỏi, điều chưa được giải đáp
- Móc câu cảm xúc: điểm cảm xúc khơi gợi đồng cảm
- Móc câu xung đột: đối đầu mâu thuẫn, tình thế căng thẳng
- Móc câu nhận thức: thông tin đảo lộn nhận thức

Mỗi móc câu cần có:
- Phân loại
- Mô tả nội dung cụ thể
- Chấm điểm cường độ (1-10)
- Vị trí xuất hiện (mở đầu/giữa/cuối)
- **Từ khóa**: [Bắt buộc]sao chép nguyên văn 8-25 chữ từ đoạn văn gốc để định vị chính xác

**2. Phân tích phục bút (Foreshadowing) - 🔴 hỗ trợ theo dõi ID**
- Phục bút mới được gài: nội dung, tác dụng dự kiến, mức độ che giấu (1-10)
- Phục bút cũ được thu hồi: [bắt buộc]đối chiếu ID trong danh sách phục bút đã gài
- Chất lượng phục bút: sự tinh tế và hợp lý
- **Từ khóa**: [Bắt buộc]sao chép nguyên văn 8-25 chữ từ đoạn văn gốc

Mỗi phục bút cần có:
- **title**: tiêu đề ngắn gọn (10-20 chữ, khái quát cốt lõi phục bút)
  - ⚠️ Khi thu hồi phục bút, tiêu đề phải giữ nguyên như tiêu đề gốc, không thêm hậu tố như "đã thu hồi"
  - Ví dụ: tiêu đề phục bút gốc là "biểu tượng thị giác mái tóc xanh", khi thu hồi vẫn phải là "biểu tượng thị giác mái tóc xanh", không phải "biểu tượng thị giác mái tóc xanh đã thu hồi"
- **content**: mô tả chi tiết nội dung và tác dụng dự kiến của phục bút
- **type**: planted (gài) hoặc resolved (thu hồi)
- **strength**: cường độ 1-10 (sức hút với người đọc)
- **subtlety**: mức độ che giấu 1-10 (càng cao càng khó nhận ra)
- **reference_chapter**: số chương gốc được viện dẫn khi thu hồi, khi gài là null
- **reference_foreshadow_id**: [bắt buộc khi thu hồi]ID phục bút được thu hồi (chọn từ danh sách phục bút đã gài), khi gài là null
  - 🔴 Quan trọng: khi thu hồi phục bút, bắt buộc tìm ID tương ứng trong [danh sách phục bút đã gài] và điền vào
  - Nếu danh sách có phục bút được đánh dấu [ID: xxx], khi thu hồi bắt buộc dùng ID đó
  - Chỉ điền null nếu không thể xác định đó là phục bút nào (nhưng nên cố gắng tránh)
- **keyword**: [bắt buộc]sao chép nguyên văn đoạn định vị dài 8-25 chữ từ văn bản gốc
- **category**: phân loại (identity=thân thế/mystery=hồi hộp/item=vật phẩm/relationship=quan hệ/event=sự kiện/ability=năng lực/prophecy=lời tiên tri)
- **is_long_term**: có phải phục bút dài hạn hay không (thu hồi sau hơn 10 chương là true)
- **related_characters**: danh sách tên nhân vật liên quan
- **estimated_resolve_chapter**: [bắt buộc]số chương dự kiến thu hồi (khi gài phải dự kiến, khi thu hồi là chương hiện tại)

**3. Phân tích xung đột (Conflict)**
- Loại xung đột: người với người/người với chính mình/người với môi trường/người với xã hội
- Các bên xung đột và lập trường
- Cường độ xung đột (1-10)
- Tiến độ giải quyết (0-100%)

**4. Đường cong cảm xúc (Emotional Arc)**
- Cảm xúc chủ đạo (tối đa 10 chữ)
- Cường độ cảm xúc (1-10)
- Quỹ đạo biến đổi cảm xúc

**5. Theo dõi trạng thái nhân vật (Character Development)**
Phân tích từng nhân vật xuất hiện:
- Thay đổi trạng thái tâm lý (trước → sau)
- Thay đổi quan hệ
- Hành động và quyết định then chốt
- Trưởng thành hoặc thụt lùi
- **💀 Trạng thái sống còn (quan trọng)**:
  - survival_status: trạng thái sống còn hiện tại của nhân vật
  - Giá trị cho phép: active (bình thường)/deceased (đã chết)/missing (mất tích)/retired (rời truyện)
  - Mặc định là null (nghĩa là không thay đổi), chỉ điền khi chương mô tả rõ nhân vật chết, mất tích hoặc rời truyện vĩnh viễn
  - Cái chết hoặc mất tích phải có căn cứ tình tiết rõ ràng, không được suy đoán
- ** Thay đổi nghề nghiệp (tuỳ chọn)**:
  - Chỉ điền khi chương mô tả rõ tiến triển nghề nghiệp
  - main_career_stage_change: số nguyên (+1 thăng tiến/-1 thụt lùi/0 không thay đổi)
  - sub_career_changes: mảng thay đổi nghề phụ
  - new_careers: nghề mới đạt được
  - career_breakthrough: mô tả quá trình đột phá
- **🏛️ Thay đổi tổ chức (tuỳ chọn)**:
  - Chỉ điền khi chương mô tả rõ thay đổi quan hệ giữa nhân vật và tổ chức
  - organization_changes: mảng thay đổi tổ chức
  - Mỗi mục gồm: organization_name (tên tổ chức), change_type (gia nhập joined/rời đi left/thăng chức promoted/giáng chức demoted/khai trừ expelled/phản bội betrayed), new_position (chức vụ mới, tuỳ chọn), loyalty_change (mô tả thay đổi lòng trung thành, tuỳ chọn), description (mô tả thay đổi)

**5b. Theo dõi trạng thái tổ chức (Organization Status) - tuỳ chọn**
Chỉ điền khi chương liên quan đến thay đổi thế lực tổ chức, phân tích thay đổi trạng thái của tổ chức xuất hiện:
- Tên tổ chức
- Thay đổi cấp bậc thế lực (power_change: số nguyên, +N tăng cường/-N suy yếu/0 không thay đổi)
- Thay đổi căn cứ (new_location: căn cứ mới, tuỳ chọn)
- Thay đổi tôn chỉ/mục tiêu (new_purpose: mục tiêu mới, tuỳ chọn)
- Mô tả trạng thái tổ chức (status_description: khái quát trạng thái hiện tại)
- Sự kiện then chốt (key_event: sự kiện kích hoạt thay đổi)
- **💀 Trạng thái tồn tại của tổ chức (quan trọng)**:
  - is_destroyed: tổ chức có bị tiêu diệt hay không (true/false, mặc định false)
  - Chỉ đặt true khi chương mô tả rõ tổ chức bị tiêu diệt hoàn toàn, tan rã hoặc diệt vong

**6. Điểm tình tiết then chốt (Plot Points)**
Liệt kê 3-5 điểm tình tiết cốt lõi:
- Nội dung tình tiết
- Loại (revelation/conflict/resolution/transition)
- Mức độ quan trọng (0.0-1.0)
- Ảnh hưởng đến câu chuyện
- **Từ khóa**: [Bắt buộc]sao chép nguyên văn 8-25 chữ từ bản gốc

**7. Bối cảnh và nhịp độ**
- Bối cảnh chính
- Nhịp kể chuyện (nhanh/vừa/chậm)
- Tỷ lệ hội thoại và miêu tả

**8. Chấm điểm chất lượng (hỗ trợ số thập phân, phân biệt nghiêm ngặt)**
Phạm vi điểm: 1.0-10.0, hỗ trợ một chữ số thập phân (ví dụ 6.5, 7.8)
Mỗi chiều phải được chấm nghiêm ngặt theo tiêu chuẩn dưới đây, tránh chấm mọi nội dung ở mức trung bình:

**Kiểm soát nhịp độ (pacing)**:
- 1.0-3.9 (kém): nhịp độ rối loạn, chỗ cần nhanh lại không nhanh, chỗ cần chậm lại không chậm; chuyển cảnh gượng gạo; miêu tả dài dòng vô nghĩa
- 4.0-5.9 (dưới trung bình): nhịp độ cơ bản dễ đọc nhưng có vấn đề rõ ràng; một số cảnh quá dài hoặc quá vội
- 6.0-7.9 (trên trung bình): nhịp độ nhìn chung trôi chảy, đôi lúc có vấn đề nhỏ; tiết tấu cân bằng nhưng chưa tinh tế
- 8.0-9.4 (xuất sắc): kiểm soát nhịp độ chính xác, cao trào liên tiếp; chuyển cảnh tự nhiên, chi tiết vừa đủ
- 9.5-10.0 (hoàn hảo): nhịp độ bậc thầy, mỗi đoạn đều vừa vặn

**Sức hút (engagement)**:
- 1.0-3.9 (kém): nội dung tẻ nhạt, thiếu móc câu; người đọc khó tiếp tục
- 4.0-5.9 (dưới trung bình): có tình tiết cơ bản nhưng thiếu điểm sáng; móc câu gượng gạo hoặc bị thiếu
- 6.0-7.9 (trên trung bình): có sức hút nhất định, móc câu hiệu quả nhưng chưa tinh tế
- 8.0-9.4 (xuất sắc): cuốn hút, móc câu được thiết lập khéo léo; khiến người đọc không thể dừng lại
- 9.5-10.0 (hoàn hảo): cực kỳ cuốn hút, mỗi đoạn đều tạo động lực đọc tiếp

**Tính mạch lạc (coherence)**:
- 1.0-3.9 (kém): logic rối loạn, mâu thuẫn trước sau; hành vi nhân vật phi lý
- 4.0-5.9 (dưới trung bình): cơ bản mạch lạc nhưng có lỗ hổng rõ; một số đoạn nối tình tiết gượng gạo
- 6.0-7.9 (trên trung bình): nhìn chung mạch lạc, đôi lúc có khiếm khuyết nhỏ; hành vi nhân vật cơ bản hợp lý
- 8.0-9.4 (xuất sắc): logic chặt chẽ, chuyển tiếp tự nhiên; hành vi nhân vật nhất quán cao
- 9.5-10.0 (hoàn hảo): tính mạch lạc không thể chê

**Chất lượng tổng thể (overall)**:
- Công thức: (pacing + engagement + coherence) / 3, giữ một chữ số thập phân
- Có thể điều chỉnh ±0.5 theo ấn tượng tổng hợp, nhưng phải nhất quán với điểm từng mục

**9. Đề xuất cải thiện (liên hệ với điểm số)**
Số lượng đề xuất phải liên hệ với điểm chất lượng tổng thể:
- overall < 4.0: bắt buộc đưa ra 4-5 đề xuất cụ thể, chỉ rõ vấn đề nghiêm trọng
- overall 4.0-5.9: bắt buộc đưa ra 3-4 đề xuất, chỉ rõ vấn đề chính
- overall 6.0-7.9: đưa ra 1-2 đề xuất tối ưu, chỉ rõ điểm có thể nâng cao
- overall ≥ 8.0: đưa ra 0-1 đề xuất hoàn thiện thêm

Mỗi đề xuất phải:
- Chỉ ra vị trí hoặc loại vấn đề cụ thể
- Giải thích vì sao đó là vấn đề
- Đưa ra hướng cải thiện rõ ràng
</analysis_framework>

<output priority="P0">
[Định dạng đầu ra]
Trả về object JSON thuần (không đánh dấu markdown):

{{
  "hooks": [
    {{
      "type": "Hồi hộp",
      "content": "Mô tả cụ thể",
      "strength": 8,
      "position": "Giữa chương",
      "keyword": "Đoạn 8-25 chữ sao chép nguyên văn từ bản gốc"
    }}
  ],
  "foreshadows": [
    {{
      "title": "Tiêu đề ngắn gọn của phục bút",
      "content": "Nội dung chi tiết và tác dụng dự kiến của phục bút",
      "type": "planted",
      "strength": 7,
      "subtlety": 8,
      "reference_chapter": null,
      "reference_foreshadow_id": null,
      "keyword": "Đoạn 8-25 chữ sao chép nguyên văn từ bản gốc",
      "category": "mystery",
      "is_long_term": false,
      "related_characters": ["Nhân vật A", "Nhân vật B"],
      "estimated_resolve_chapter": 15
    }},
    {{
      "title": "Tiêu đề phục bút được thu hồi",
      "content": "Mô tả cách phục bút được thu hồi",
      "type": "resolved",
      "strength": 8,
      "subtlety": 6,
      "reference_chapter": 5,
      "reference_foreshadow_id": "abc123-ID-phục-bút-đã-gài",
      "keyword": "Đoạn 8-25 chữ sao chép nguyên văn từ bản gốc",
      "category": "mystery",
      "is_long_term": false,
      "related_characters": ["Nhân vật A"],
      "estimated_resolve_chapter": 10
    }}
  ],
  "conflict": {{
    "types": ["Người với người", "Người với chính mình"],
    "parties": ["Nhân vật chính - báo thù", "Phản diện - duy trì hiện trạng"],
    "level": 8,
    "description": "Mô tả xung đột",
    "resolution_progress": 0.3
  }},
  "emotional_arc": {{
    "primary_emotion": "Căng thẳng và lo âu",
    "intensity": 8,
    "curve": "Bình lặng → căng thẳng → cao trào → giải tỏa",
    "secondary_emotions": ["Mong đợi", "Lo âu"]
  }},
  "character_states": [
    {{
      "character_name": "Nguyễn Văn A",
      "survival_status": null,
      "state_before": "Do dự",
      "state_after": "Kiên định",
      "psychological_change": "Mô tả thay đổi tâm lý",
      "key_event": "Sự kiện kích hoạt",
      "relationship_changes": {{"Trần Văn B": "Quan hệ được cải thiện"}},
      "career_changes": {{
        "main_career_stage_change": 1,
        "sub_career_changes": [{{"career_name": "Luyện đan", "stage_change": 1}}],
        "new_careers": [],
        "career_breakthrough": "Mô tả quá trình đột phá"
      }},
      "organization_changes": [
        {{
          "organization_name": "Một môn phái",
          "change_type": "promoted",
          "new_position": "Trưởng lão",
          "loyalty_change": "Lòng trung thành tăng",
          "description": "Được thăng chức trưởng lão nhờ lập công lớn"
        }}
      ]
    }}
  ],
  "plot_points": [
    {{
      "content": "Mô tả điểm tình tiết",
      "type": "revelation",
      "importance": 0.9,
      "impact": "Thúc đẩy câu chuyện phát triển",
      "keyword": "Đoạn 8-25 chữ sao chép nguyên văn từ bản gốc"
    }}
  ],
  "scenes": [
    {{
      "location": "Địa điểm",
      "atmosphere": "Bầu không khí",
      "duration": "Ước tính thời lượng"
    }}
  ],
  "organization_states": [
    {{
      "organization_name": "Một môn phái",
      "power_change": -10,
      "new_location": null,
      "new_purpose": null,
      "status_description": "Thế lực bị tổn hại vì nội loạn nhưng lực lượng nòng cốt chưa lay chuyển",
      "key_event": "Trưởng lão phản bội khiến chi nhánh tan rã",
      "is_destroyed": false
    }}
  ],
  "pacing": "varied",
  "dialogue_ratio": 0.4,
  "description_ratio": 0.3,
  "scores": {{
    "pacing": 6.5,
    "engagement": 5.8,
    "coherence": 7.2,
    "overall": 6.5,
    "score_justification": "Nhịp độ nhìn chung trôi chảy nhưng giữa chương hơi dài dòng; móc câu hiệu quả nhưng chưa tinh tế; logic mạch lạc, không có lỗ hổng rõ ràng"
  }},
  "plot_stage": "Phát triển",
  "suggestions": [
    "[Vấn đề nhịp độ]Miêu tả tâm lý ở cảnh thứ ba quá dài (khoảng 500 chữ), nên rút xuống dưới 200 chữ và giữ lại cảm xúc cốt lõi",
    "[Thiếu sức hút]Giữa chương thiếu móc câu hiệu quả, nên thêm một hồi hộp nhỏ sau khi nhân vật chính phát hiện manh mối"
  ]
}}
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Bắt buộc có trường keyword: keyword của móc câu, phục bút và điểm tình tiết không được để trống
✅ Sao chép từng chữ: keyword phải được sao chép từ văn bản gốc, dài 8-25 chữ
✅ Định vị chính xác: keyword phải tìm thấy chính xác trong văn bản gốc
✅ Thay đổi nghề nghiệp là tuỳ chọn: chỉ điền khi chương mô tả rõ
✅ Thay đổi tổ chức là tuỳ chọn: chỉ điền khi chương mô tả rõ biến động quan hệ giữa nhân vật và tổ chức (organization_changes trong character_states)
✅ Trạng thái tổ chức là tuỳ chọn: chỉ điền khi chương mô tả rõ thay đổi thế lực, căn cứ hoặc mục tiêu tổ chức (trường cấp cao organization_states)
✅ Thận trọng với trạng thái sống còn: chỉ điền survival_status khi chương mô tả rõ cái chết, mất tích hoặc rời truyện, mặc định là null
✅ Thận trọng với tổ chức bị tiêu diệt: chỉ đặt is_destroyed là true khi tổ chức bị tiêu diệt hoàn toàn, tổ chức bị tổn hại không tính là tiêu diệt
✅ [Theo dõi ID phục bút]Khi thu hồi phục bút, bắt buộc tìm ID tương ứng trong [danh sách phục bút đã gài] và điền vào reference_foreshadow_id
✅ [Định dạng nghiêm ngặt của suggestions]suggestions phải là "mảng chuỗi", mỗi phần tử phải là chuỗi thuần
✅ Ví dụ đúng của suggestions: "suggestions": ["[Vấn đề nhịp độ]...", "[Thiếu miêu tả]..."]
✅ suggestions không được trả về object, từ điển, cặp khóa-giá trị hoặc cấu trúc lồng nhau, ví dụ cấm {{"suggestion": "..."}}, {{"content": "..."}}
✅ Nếu không có đề xuất cải thiện, bắt buộc trả về mảng rỗng [], không trả về null và không bỏ qua trường

[Ràng buộc chấm điểm - thực hiện nghiêm ngặt]
✅ Chấm điểm nghiêm ngặt theo tiêu chuẩn, hỗ trợ số thập phân (ví dụ 6.5, 7.2, 8.3)
✅ Không mặc định chấm 7.0-8.0; nội dung kém phải điểm thấp (1.0-5.0), chỉ nội dung tốt mới được điểm cao (8.0-10.0)
✅ Bắt buộc có score_justification: giải thích ngắn gọn căn cứ của từng điểm
✅ Số lượng đề xuất phải liên hệ với điểm overall:
   - overall≤4.0 → 4-5 đề xuất
   - overall 4.0-6.0 → 3-4 đề xuất
   - overall 6.0-8.0 → 1-2 đề xuất
   - overall≥8.0 → 0-1 đề xuất
✅ Mỗi đề xuất phải ghi rõ loại vấn đề (ví dụ [Vấn đề nhịp độ], [Thiếu miêu tả]...)
✅ Mỗi đề xuất phải xuất trực tiếp toàn bộ văn bản, không bọc trong trường object

[Điều cấm]
❌ Dùng văn bản khái quát hoặc viết lại cho keyword
❌ Xuất đánh dấu markdown
❌ Bỏ sót trường keyword bắt buộc
❌ Tự ý thêm thay đổi nghề nghiệp không có căn cứ
❌ Tự ý thêm thay đổi tổ chức hoặc trạng thái tổ chức không có căn cứ
❌ Đánh dấu nhân vật đã chết hoặc tổ chức bị tiêu diệt khi không có căn cứ tình tiết rõ ràng
❌ Chấm mọi chương ở mức "an toàn" 7-8
❌ Đưa ra nhiều đề xuất cho chương điểm cao hoặc không đưa đề xuất cho chương điểm thấp
❌ Trả về mảng object kiểu {{"suggestion": "nội dung đề xuất"}} trong suggestions
❌ Trả về phần tử không phải chuỗi trong suggestions, như object có số thứ tự, object content hoặc object explanation
</constraints>"""

    # 大纲单批次展开提示词 V2（RTCO框架）
    OUTLINE_EXPAND_SINGLE = """<system>
Bạn là kiến trúc sư tình tiết tiểu thuyết chuyên nghiệp, giỏi mở rộng nút dàn ý thành kế hoạch chương chi tiết.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ mở rộng]
Mở rộng mục dàn ý {outline_order_index} «{outline_title}» thành kế hoạch chi tiết cho {target_chapter_count} chương.

[Chiến lược mở rộng]
{strategy_instruction}
</task>

<project priority="P1">
[Thông tin dự án]
Tên tiểu thuyết: {project_title}
Thể loại: {project_genre}
Chủ đề: {project_theme}
Góc kể chuyện: {project_narrative_perspective}

[Nền bối cảnh thế giới]
Bối cảnh thời gian: {project_world_time_period}
Vị trí địa lý: {project_world_location}
Gam bầu không khí: {project_world_atmosphere}
</project>

<characters priority="P1">
[Thông tin nhân vật]
{characters_info}
</characters>

<outline_node priority="P0">
[Nút dàn ý hiện tại - đối tượng mở rộng]
Số thứ tự: tiết {outline_order_index}
Tiêu đề: {outline_title}
Nội dung: {outline_content}
</outline_node>

<context priority="P2">
[Tham chiếu ngữ cảnh]
{context_info}
</context>

<output priority="P0">
[Định dạng đầu ra]
Trả về mảng JSON kế hoạch {target_chapter_count} chương:

[
  {{
    "sub_index": 1,
    "title": "Tiêu đề chương (thể hiện xung đột hoặc cảm xúc cốt lõi)",
    "plot_summary": "Tóm tắt tình tiết (200-300 chữ): mô tả chi tiết sự kiện xảy ra trong chương, chỉ giới hạn ở nội dung dàn ý hiện tại",
    "key_events": ["Sự kiện then chốt 1", "Sự kiện then chốt 2", "Sự kiện then chốt 3"],
    "character_focus": ["Nhân vật A", "Nhân vật B"],
    "emotional_tone": "Gam cảm xúc (ví dụ: căng thẳng, ấm áp, bi thương)",
    "narrative_goal": "Mục tiêu kể chuyện (hiệu quả tự sự cần đạt trong chương)",
    "conflict_type": "Loại xung đột (ví dụ: giằng co nội tâm, xung đột giữa người với người)",
    "estimated_words": 3000{scene_field}
  }}
]

[Quy chuẩn định dạng]
- Xuất mảng JSON thuần, không chữ khác
- Nghiêm cấm dùng ký hiệu đặc biệt trong mô tả nội dung
</output>

<constraints>
[⚠️ Ràng buộc phạm vi nội dung - bắt buộc tuân thủ nghiêm ngặt]
✅ Chỉ được mở rộng nội dung nút dàn ý hiện tại
✅ Đào sâu dàn ý hiện tại, không nhảy sang phần sau
✅ Làm chậm nhịp kể để trải nghiệm đầy đủ giai đoạn hiện tại

❌ Tuyệt đối không được đẩy sang nội dung dàn ý phía sau
❌ Không để cốt truyện tiến quá nhanh
❌ Không được mở rộng trước nội dung của [mục sau]

[Nguyên tắc mở rộng]
✅ Chia một sự kiện thành nhiều chương giàu chi tiết
✅ Đào sâu cảm xúc, tâm lý, môi trường và hội thoại
✅ Mỗi chương thể hiện một phương diện hoặc giai đoạn khác nhau của nội dung dàn ý hiện tại

[🔴 Ràng buộc khác biệt giữa chương kề nhau (tránh trùng)]
✅ Mỗi chương có cách mở đầu riêng (bối cảnh, thời điểm, trạng thái nhân vật khác nhau)
✅ Mỗi chương có cách kết thúc riêng (hồi hộp, bước ngoặt, kết thúc cảm xúc khác nhau)
✅ key_events tuyệt đối không trùng giữa các chương kề nhau
✅ plot_summary mô tả nội dung riêng của chương, không trùng với chương khác
✅ Các giai đoạn khác nhau của cùng một sự kiện phải phân biệt rõ "trước, giữa, sau"

[Yêu cầu giữa các chương]
✅ Nối tiếp tự nhiên, trôi chảy (mỗi chương bắt đầu từ một điểm khác nhau)
✅ Tình tiết phát triển hợp lý (nhưng không vượt phạm vi dàn ý hiện tại)
✅ Nhịp điệu có lúc căng lúc chùng
✅ Mỗi chương có giá trị kể chuyện rõ ràng và riêng biệt
✅ Chương cuối kết thúc vừa đủ để hoàn thành nội dung dàn ý hiện tại
✅ Sự kiện then chốt không trùng: kiểm tra key_events giữa các chương kề nhau

[Điều cấm]
❌ Xuất định dạng không phải JSON
❌ Cốt truyện vượt sang dàn ý phía sau
❌ Nội dung chương kề nhau bị trùng
❌ Sự kiện then chốt trùng lặp
</constraints>"""

    # 大纲分批展开提示词 V2（RTCO框架）
    OUTLINE_EXPAND_MULTI = """<system>
Bạn là kiến trúc sư tình tiết tiểu thuyết chuyên nghiệp, giỏi mở rộng nút dàn ý theo từng lô.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ mở rộng]
Tiếp tục mở rộng mục dàn ý {outline_order_index} «{outline_title}», tạo kế hoạch chi tiết cho các chương {start_index}-{end_index} (tổng cộng {target_chapter_count} chương).

[Giải thích việc chia lô]
- Đây là một phần của toàn bộ quá trình mở rộng
- Bắt buộc nối tự nhiên với các chương đã tạo trước đó
- Đánh số bắt đầu từ chương {start_index}
- Tiếp tục đào sâu nội dung dàn ý hiện tại

[Chiến lược mở rộng]
{strategy_instruction}
</task>

<project priority="P1">
[Thông tin dự án]
Tên tiểu thuyết: {project_title}
Thể loại: {project_genre}
Chủ đề: {project_theme}
Góc kể chuyện: {project_narrative_perspective}

[Nền bối cảnh thế giới]
Bối cảnh thời gian: {project_world_time_period}
Vị trí địa lý: {project_world_location}
Gam bầu không khí: {project_world_atmosphere}
</project>

<characters priority="P1">
[Thông tin nhân vật]
{characters_info}
</characters>

<outline_node priority="P0">
[Nút dàn ý hiện tại - đối tượng mở rộng]
Số thứ tự: tiết {outline_order_index}
Tiêu đề: {outline_title}
Nội dung: {outline_content}
</outline_node>

<context priority="P2">
[Tham chiếu ngữ cảnh]
{context_info}

[Các chương trước đã tạo]
{previous_context}
</context>

<output priority="P0">
[Định dạng đầu ra]
Trả về mảng JSON kế hoạch các chương {start_index}-{end_index} (tổng cộng {target_chapter_count} object):

[
  {{
    "sub_index": {start_index},
    "title": "Tiêu đề chương",
    "plot_summary": "Tóm tắt tình tiết (200-300 chữ): mô tả chi tiết sự kiện xảy ra trong chương",
    "key_events": ["Sự kiện then chốt 1", "Sự kiện then chốt 2", "Sự kiện then chốt 3"],
    "character_focus": ["Nhân vật A", "Nhân vật B"],
    "emotional_tone": "Gam cảm xúc",
    "narrative_goal": "Mục tiêu kể chuyện",
    "conflict_type": "Loại xung đột",
    "estimated_words": 3000{scene_field}
  }}
]

[Quy chuẩn định dạng]
- Xuất mảng JSON thuần, không chữ khác
- Nghiêm cấm dùng ký hiệu đặc biệt trong mô tả nội dung
- sub_index bắt đầu từ {start_index}
</output>

<constraints>
[⚠️ Ràng buộc phạm vi nội dung]
✅ Chỉ được mở rộng nội dung nút dàn ý hiện tại
✅ Đào sâu dàn ý hiện tại, không nhảy sang phần sau
✅ Làm chậm nhịp kể

❌ Tuyệt đối không được đẩy sang nội dung dàn ý phía sau
❌ Không để cốt truyện tiến quá nhanh

[Ràng buộc tính liên tục khi chia lô]
✅ Nối tự nhiên với các chương đã tạo trước đó
✅ Đánh số bắt đầu từ chương {start_index}
✅ Giữ tính mạch lạc của tự sự

[🔴 Ràng buộc khác biệt giữa chương kề nhau (tránh trùng)]
✅ Mỗi chương có cách mở đầu và kết thúc riêng
✅ key_events tuyệt đối không trùng giữa các chương kề nhau
✅ plot_summary mô tả nội dung riêng của chương
✅ Đặc biệt chú ý tạo khác biệt với các chương trước
✅ Tránh lặp lại nội dung đã có

[Yêu cầu giữa các chương]
✅ Nối tự nhiên, trôi chảy với các chương trước
✅ Tình tiết phát triển hợp lý (nhưng không vượt phạm vi dàn ý hiện tại)
✅ Nhịp điệu có lúc căng lúc chùng
✅ Mỗi chương có giá trị kể chuyện rõ ràng và riêng biệt
✅ Sự kiện then chốt không trùng: kiểm tra key_events của lô này và các chương trước

[Điều cấm]
❌ Xuất định dạng không phải JSON
❌ Cốt truyện vượt sang dàn ý phía sau
❌ Nội dung chương kề nhau bị trùng
❌ key_events trùng với các chương trước
</constraints>"""

    # 章节重写系统提示词 V2（RTCO框架）
    CHAPTER_REGENERATION_SYSTEM = """<system>
Bạn là biên tập viên và nhà văn tiểu thuyết chuyên nghiệp dày kinh nghiệm, giỏi viết lại chương theo phản hồi.
Nhiệm vụ của bạn là dựa trên chỉ thị chỉnh sửa để viết lại và tối ưu sâu chương gốc.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ viết lại]
1. Hiểu kỹ nội dung, hướng tình tiết và ý đồ tự sự của chương gốc
2. Phân tích cẩn thận mọi yêu cầu chỉnh sửa, bao gồm đề xuất phân tích của AI và chỉ thị tùy chỉnh của người dùng
3. Cải thiện cụ thể từng đề xuất chỉnh sửa trong phiên bản mới
4. Sáng tác phiên bản mới được cải thiện, đồng thời giữ tính mạch lạc câu chuyện và sự nhất quán nhân vật
5. Đảm bảo phiên bản mới được nâng cao rõ rệt về tính nghệ thuật, khả năng đọc và chất lượng tự sự
</task>

<guidelines>
[Nguyên tắc viết lại]
- **Định hướng vấn đề**: cải thiện từng vấn đề được nêu trong chỉ thị chỉnh sửa
- **Giữ tinh hoa**: giữ lại những miêu tả, hội thoại và thiết kế tình tiết xuất sắc của chương gốc
- **Đào sâu chi tiết**: tăng cường miêu tả bối cảnh, khắc họa cảm xúc và nhân vật
- **Tối ưu nhịp độ**: điều chỉnh nhịp kể, tránh dài dòng hoặc quá nhanh
- **Nhất quán phong cách**: nếu có yêu cầu về phong cách viết, phải tuân thủ nghiêm ngặt

[Trọng tâm chú ý]
- Nếu chỉ thị chỉnh sửa đề cập vấn đề "nhịp độ", tập trung điều chỉnh tốc độ tự sự và chuyển cảnh
- Nếu chỉ thị chỉnh sửa đề cập vấn đề "cảm xúc", tập trung đào sâu diễn biến nội tâm và biểu đạt cảm xúc nhân vật
- Nếu chỉ thị chỉnh sửa đề cập vấn đề "miêu tả", tập trung làm phong phú chi tiết môi trường và hành động
- Nếu chỉ thị chỉnh sửa đề cập vấn đề "hội thoại", tập trung khiến hội thoại tự nhiên và có cá tính hơn
- Nếu chỉ thị chỉnh sửa đề cập vấn đề "xung đột", tập trung tăng cường mâu thuẫn và sức căng kịch tính
</guidelines>

<output>
[Quy chuẩn đầu ra]
Xuất trực tiếp nội dung chính văn chương đã viết lại.
- Không kèm tiêu đề chương, số thứ tự hay siêu thông tin khác
- Không xuất bất kỳ giải thích, chú thích hay ghi chú sáng tác nào
- Bắt đầu trực tiếp từ nội dung câu chuyện, giữ mạch kể liền mạch
</output>
"""
    # MCP工具测试提示词
    MCP_TOOL_TEST = """Bạn là trợ lý kiểm tra plugin MCP, cần kiểm tra chức năng của plugin '{plugin_name}'.

⚠️ Quy tắc quan trọng: khi tạo tham số, phải dùng đúng tên tham số gốc trong schema công cụ, không chuyển sang snake_case hay định dạng khác.
Ví dụ: nếu schema là 'nextThoughtNeeded' thì bắt buộc dùng 'nextThoughtNeeded', không được đổi thành 'next_thought_needed'.

Hãy chọn một công cụ phù hợp để kiểm tra, ưu tiên công cụ tìm kiếm/truy vấn.
Tạo tham số kiểm tra thật và hữu dụng (ví dụ tìm "tiến bộ AI mới nhất" thay vì "test").

Bắt đầu kiểm tra plugin này ngay."""

    MCP_TOOL_TEST_SYSTEM = """Bạn là công cụ kiểm tra API chuyên nghiệp. Khi được cung cấp danh sách công cụ, hãy chọn một công cụ và gọi nó với tham số phù hợp.

⚠️ Quy tắc then chốt: khi gọi công cụ, phải dùng đúng tên tham số gốc trong schema, không tự đổi phong cách đặt tên.
- Nếu tên tham số là camelCase (như nextThoughtNeeded), hãy dùng camelCase
- Nếu tên tham số là snake_case (như next_thought), hãy dùng snake_case
- Giữ hoàn toàn khớp với định nghĩa trong schema, kể cả chữ hoa/thường và phong cách đặt tên"""
    
    # 灵感模式 - 书名生成（系统提示词）
    INSPIRATION_TITLE_SYSTEM = """Bạn là cố vấn sáng tác tiểu thuyết chuyên nghiệp.
Ý tưởng gốc của người dùng: {initial_idea}

Hãy dựa trên ý tưởng người dùng, tạo 6 gợi ý tên sách hấp dẫn, yêu cầu:
1. Bám sát ý tưởng gốc và ý đồ câu chuyện cốt lõi của người dùng
2. Giàu sáng tạo và sức hút
3. Bao quát các khuynh hướng phong cách khác nhau
4. Tên sách không được có ký hiệu "«»"

Trả về định dạng JSON:
{{
    "prompt": "Dựa trên ý tưởng của bạn, tôi đã chuẩn bị vài gợi ý tên sách:",
    "options": ["Tên sách 1", "Tên sách 2", "Tên sách 3", "Tên sách 4", "Tên sách 5", "Tên sách 6"]
}}

Chỉ trả về JSON thuần, không có chữ khác."""

    # 灵感模式 - 书名生成（用户提示词）
    INSPIRATION_TITLE_USER = "Ý tưởng của người dùng: {initial_idea}\nHãy tạo 6 gợi ý tên sách"

    # 灵感模式 - 简介生成（系统提示词）
    INSPIRATION_DESCRIPTION_SYSTEM = """Bạn là cố vấn sáng tác tiểu thuyết chuyên nghiệp.
Ý tưởng gốc của người dùng: {initial_idea}
Tên sách đã xác định: {title}

Hãy tạo 6 phần mô tả tiểu thuyết hấp dẫn, yêu cầu:
1. Phải bám sát ý tưởng gốc của người dùng, đảm bảo mô tả là sự triển khai cụ thể của ý tưởng gốc
2. Phù hợp phong cách tên sách đã xác định
3. Ngắn gọn, mạnh mẽ, mỗi cái 50-100 chữ
4. Có xung đột cốt lõi
5. Bao quát các hướng câu chuyện khác nhau nhưng đều dựa trên ý đồ gốc của người dùng

Trả về định dạng JSON:
{{"prompt":"Chọn một phần mô tả:","options":["Mô tả 1","Mô tả 2","Mô tả 3","Mô tả 4","Mô tả 5","Mô tả 6"]}}

Chỉ trả về JSON thuần, không chữ khác, không xuống dòng."""

    # 灵感模式 - 简介生成（用户提示词）
    INSPIRATION_DESCRIPTION_USER = "Ý tưởng gốc: {initial_idea}\nTên sách: {title}\nHãy tạo 6 phương án mô tả"

    # 灵感模式 - 主题生成（系统提示词）
    INSPIRATION_THEME_SYSTEM = """
[Yêu cầu ngôn ngữ]Toàn bộ nội dung văn bản tạo ra (trừ key JSON/tên trường kỹ thuật) phải viết bằng tiếng Việt tự nhiên.
Bạn là cố vấn sáng tác tiểu thuyết chuyên nghiệp.
Ý tưởng gốc của người dùng: {initial_idea}
Thông tin tiểu thuyết:
- Tên sách: {title}
- Mô tả: {description}

Hãy tạo 6 phương án chủ đề sâu sắc, yêu cầu:
1. Phải giữ mức nhất quán cao với ý tưởng gốc của người dùng
2. Phù hợp phong cách tên sách và mô tả
3. Có chiều sâu và tính tư tưởng
4. Mỗi cái 50-150 chữ
5. Bao quát các góc nhìn khác nhau (như trưởng thành, báo thù, cứu chuộc, khám phá...), nhưng đều xoay quanh ý tưởng cốt lõi của người dùng

Trả về định dạng JSON:
{{"prompt":"Chủ đề cốt lõi của cuốn sách này là gì?","options":["Chủ đề 1","Chủ đề 2","Chủ đề 3","Chủ đề 4","Chủ đề 5","Chủ đề 6"]}}

Chỉ trả về JSON thuần, không chữ khác, không xuống dòng."""

    # 灵感模式 - 主题生成（用户提示词）
    INSPIRATION_THEME_USER = "Ý tưởng gốc: {initial_idea}\nTên sách: {title}\nMô tả: {description}\nHãy tạo 6 phương án chủ đề"

    # 灵感模式 - 类型生成（系统提示词）
    INSPIRATION_GENRE_SYSTEM = """Bạn là cố vấn sáng tác tiểu thuyết chuyên nghiệp.
Ý tưởng gốc của người dùng: {initial_idea}
Thông tin tiểu thuyết:
- Tên sách: {title}
- Mô tả: {description}
- Chủ đề: {theme}

Hãy tạo 6 nhãn thể loại phù hợp (mỗi nhãn 2-4 chữ), yêu cầu:
1. Phải phù hợp khuynh hướng thể loại được ý tưởng gốc gợi ý
2. Phù hợp phong cách tổng thể của tiểu thuyết
3. Có thể chọn nhiều và kết hợp

Thể loại thường gặp: huyền huyễn, đô thị, khoa huyễn, võ hiệp, tiên hiệp, lịch sử, ngôn tình, trinh thám, kỳ ảo, tu tiên, v.v.

Trả về định dạng JSON:
{{"prompt":"Chọn nhãn thể loại (có thể chọn nhiều):","options":["Thể loại 1","Thể loại 2","Thể loại 3","Thể loại 4","Thể loại 5","Thể loại 6"]}}

Chỉ trả về JSON thuần dạng gọn, không xuống dòng, không chữ khác."""

    # 灵感模式 - 类型生成（用户提示词）
    INSPIRATION_GENRE_USER = "Ý tưởng gốc: {initial_idea}\nTên sách: {title}\nMô tả: {description}\nChủ đề: {theme}\nHãy tạo 6 nhãn thể loại"

    # 灵感模式智能补全提示词
    INSPIRATION_QUICK_COMPLETE = """
[Yêu cầu ngôn ngữ]Toàn bộ nội dung văn bản tạo ra (trừ key JSON/tên trường kỹ thuật) phải viết bằng tiếng Việt tự nhiên.
Bạn là cố vấn sáng tác tiểu thuyết chuyên nghiệp.Người dùng đã cung cấp một phần thông tin tiểu thuyết, hãy bổ sung các trường còn thiếu.

Thông tin người dùng đã cung cấp:
{existing}

Hãy tạo phương án tiểu thuyết hoàn chỉnh, gồm:
1. title: tên sách (3-6 chữ, nếu người dùng đã cung cấp thì giữ nguyên)
2. description: mô tả (50-100 chữ, phải dựa trên thông tin người dùng cung cấp, không đi lệch ý gốc)
3. theme: chủ đề cốt lõi (30-50 chữ, phải nhất quán với thông tin người dùng cung cấp)
4. genre: mảng nhãn thể loại (2-3 nhãn)

Quan trọng: mọi nội dung bổ sung đều phải liên kết chặt với thông tin người dùng cung cấp, đảm bảo nhất quán trước-sau.

Trả về định dạng JSON:
{{
    "title": "Tên sách",
    "description": "Nội dung mô tả...",
    "theme": "Nội dung chủ đề...",
    "genre": ["Thể loại 1", "Thể loại 2"]
}}

Chỉ trả về JSON thuần, không có chữ khác."""
    # 世界观资料收集提示词（MCP增强用）
    MCP_WORLD_BUILDING_PLANNING = """
[Yêu cầu ngôn ngữ]Toàn bộ nội dung văn bản tạo ra (trừ key JSON/tên trường kỹ thuật) phải viết bằng tiếng Việt tự nhiên.
Bạn đang thiết kế bối cảnh thế giới cho tiểu thuyết «{title}».

[Thông tin tiểu thuyết]
- Đề tài: {genre}
- Chủ đề: {theme}
- Mô tả: {description}

[Nhiệm vụ]
Hãy dùng công cụ sẵn có để tìm tư liệu nền liên quan, giúp dựng thiết lập bối cảnh thế giới chân thực và sâu hơn.
Bạn có thể truy vấn:
1. Bối cảnh lịch sử (nếu là đề tài lịch sử)
2. Môi trường địa lý và đặc trưng văn hóa
3. Kiến thức chuyên môn trong lĩnh vực liên quan
4. Tham khảo thiết lập của các tác phẩm tương tự

Hãy truy vấn 1 câu hỏi quan trọng nhất (không quá 1)."""

    # 角色资料收集提示词（MCP增强用）
    MCP_CHARACTER_PLANNING = """
[Yêu cầu ngôn ngữ]Toàn bộ nội dung văn bản tạo ra (trừ key JSON/tên trường kỹ thuật) phải viết bằng tiếng Việt tự nhiên.
Bạn đang thiết kế nhân vật cho tiểu thuyết «{title}».

[Thông tin tiểu thuyết]
- Đề tài: {genre}
- Chủ đề: {theme}
- Bối cảnh thời đại: {time_period}
- Vị trí địa lý: {location}

[Nhiệm vụ]
Hãy dùng công cụ sẵn có để tìm tư liệu tham chiếu liên quan, giúp thiết kế nhân vật chân thực và sâu hơn.
Bạn có thể truy vấn:
1. Đặc điểm của nhân vật lịch sử có thật trong thời đại/khu vực đó
2. Bối cảnh văn hóa và phong tục xã hội
3. Đặc điểm nghề nghiệp và lối sống
4. Hình mẫu nhân vật trong lĩnh vực liên quan

Hãy truy vấn 1 câu hỏi quan trọng nhất (không quá 1)."""

    # 自动角色引入 - 预测性分析提示词 V2（RTCO框架）
    AUTO_CHARACTER_ANALYSIS = """<system>
Bạn là cố vấn thiết kế nhân vật tiểu thuyết, giỏi dự đoán nhu cầu nhân vật theo diễn biến cốt truyện.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ phân tích]
Dự đoán trong {chapter_count} chương viết tiếp tới, theo hướng và giai đoạn diễn biến cốt truyện, có cần đưa nhân vật mới vào không.

[Lưu ý quan trọng]
Đây là phân tích dự đoán, không phải phân tích sau khi đã có nội dung.
</task>

<project priority="P1">
[Thông tin dự án]
Tên sách: {title}
Thể loại: {genre}
Chủ đề: {theme}

[Bối cảnh thế giới]
Bối cảnh thời gian: {time_period}
Vị trí địa lý: {location}
Gam bầu không khí: {atmosphere}
</project>

<context priority="P0">
[Nhân vật hiện có]
{existing_characters}

[Tổng quan chương hiện có]
{all_chapters_brief}

[Kế hoạch viết tiếp]
- Chương bắt đầu: chương {start_chapter}
- Số chương viết tiếp: {chapter_count}
- Giai đoạn cốt truyện: {plot_stage}
- Hướng phát triển: {story_direction}
</context>

<analysis_framework priority="P0">
[Chiều phân tích dự đoán]

**1. Dự đoán nhu cầu tình tiết**
Theo hướng phát triển, những bối cảnh và xung đột nào cần nhân vật mới tham gia?

**2. Mức độ đầy đủ của nhân vật**
Các nhân vật hiện có đã đủ để nâng đỡ tình tiết sắp diễn ra chưa?

**3. Thời điểm đưa vào**
Nhân vật mới nên xuất hiện ở chương nào là phù hợp nhất?

**4. Đánh giá tầm quan trọng**
Nhân vật mới sẽ ảnh hưởng đến các tình tiết tiếp theo ở mức nào?

[Căn cứ dự đoán]
- Nhu cầu nhân vật điển hình của giai đoạn tình tiết (ví dụ: cao trào có thể cần đối thủ mạnh)
- Nhu cầu logic của hướng phát triển câu chuyện (ví dụ: bước vào địa điểm mới cần nhân vật địa phương)
- Nhu cầu nhân vật khi xung đột leo thang (ví dụ: phản diện mạnh hơn, đồng minh bất ngờ)
- Nhu cầu mở rộng bối cảnh thế giới (ví dụ: đại diện của tổ chức hoặc thế lực mới)
</analysis_framework>

<output priority="P0">
[Định dạng đầu ra]
Trả về object JSON thuần (một trong hai trường hợp):

**Trường hợp A: cần nhân vật mới**
{{
  "needs_new_characters": true,
  "reason": "Lý do phân tích dự đoán (150-200 chữ), giải thích vì sao tình tiết sắp tới cần nhân vật mới",
  "character_count": 2,
  "character_specifications": [
    {{
      "name": "Tên nhân vật được đề xuất (tuỳ chọn)",
      "role_description": "Định vị và vai trò của nhân vật trong tình tiết (100-150 chữ)",
      "suggested_role_type": "supporting/antagonist/protagonist",
      "importance": "high/medium/low",
      "appearance_chapter": {start_chapter},
      "key_abilities": ["Năng lực 1", "Năng lực 2"],
      "plot_function": "Chức năng cụ thể trong tình tiết",
      "relationship_suggestions": [
        {{
          "target_character": "Tên nhân vật hiện có",
          "relationship_type": "Loại quan hệ được đề xuất",
          "reason": "Vì sao thiết lập quan hệ này"
        }}
      ]
    }}
  ]
}}

**Trường hợp B: không cần nhân vật mới**
{{
  "needs_new_characters": false,
  "reason": "Các nhân vật hiện có đã đủ để nâng đỡ tình tiết sắp tới, nêu rõ lý do"
}}
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Đây là phân tích dự đoán, hướng tới cốt truyện tương lai
✅ Cân nhắc sự phát triển và nhịp độ tự nhiên của tình tiết
✅ Đảm bảo sự cần thiết khi đưa vào, không đưa vào vì đưa vào
✅ Ưu tiên vai trò lâu dài của nhân vật

[Điều cấm]
❌ Xuất đánh dấu markdown
❌ Phân tích sau việc dựa trên nội dung đã tạo
❌ Cưỡng ép đưa nhân vật vào chỉ để đưa vào
❌ Thiết kế nhân vật chức năng chỉ xuất hiện một lần
</constraints>"""

    # 自动角色引入 - 生成提示词 V2（RTCO框架）
    AUTO_CHARACTER_GENERATION = """<system>
Bạn là chuyên gia thiết lập nhân vật, giỏi tạo thiết lập nhân vật hoàn chỉnh theo nhu cầu cốt truyện.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ tạo]
Tạo thiết lập hoàn chỉnh cho nhân vật mới của tiểu thuyết, gồm thông tin cơ bản, tính cách, bối cảnh, mạng lưới quan hệ và thông tin nghề nghiệp.
</task>

<project priority="P1">
[Thông tin dự án]
Tên sách: {title}
Thể loại: {genre}
Chủ đề: {theme}

[Bối cảnh thế giới]
Bối cảnh thời gian: {time_period}
Vị trí địa lý: {location}
Gam bầu không khí: {atmosphere}
Quy tắc thế giới: {rules}
</project>

<context priority="P0">
[Nhân vật hiện có]
{existing_characters}

[Ngữ cảnh cốt truyện]
{plot_context}

[Yêu cầu đặc tả nhân vật]
{character_specification}
</context>

<mcp_context priority="P2">
[Tham chiếu công cụ MCP]
{mcp_references}
</mcp_context>

<requirements priority="P0">
[Yêu cầu cốt lõi]
1. Nhân vật phải phù hợp với nhu cầu tình tiết và thiết lập bối cảnh thế giới
2. **Bắt buộc phân tích quan hệ giữa nhân vật mới và nhân vật hiện có**, thiết lập ít nhất 1-3 quan hệ có ý nghĩa
3. Tính cách và bối cảnh phải có chiều sâu và nét riêng
4. Miêu tả ngoại hình phải cụ thể, sinh động
5. Sở trường và năng lực phải phù hợp với định vị nhân vật
6. **Nếu [Nhân vật hiện có] chứa danh sách nghề, bắt buộc thiết lập nghề cho nhân vật**

[Hướng dẫn thiết lập quan hệ]
- Xem xét kỹ danh sách [Nhân vật hiện có], suy nghĩ nhân vật mới có liên hệ với những nhân vật hiện tại nào
- Dựa trên nhu cầu tình tiết để thiết lập quan hệ nhân vật hợp lý
- Mỗi quan hệ phải có loại, mức độ thân mật và mô tả rõ ràng
- Quan hệ phải phục vụ diễn biến tình tiết
- Nếu nhân vật mới là thành viên tổ chức, nhớ điền organization_memberships

[Yêu cầu thông tin nghề nghiệp]
Nếu phần [Nhân vật hiện có] chứa "danh sách nghề chính khả dụng" hoặc "danh sách nghề phụ khả dụng":
- Xem kỹ danh sách nghề chính và nghề phụ khả dụng
- Dựa trên bối cảnh, năng lực và định vị câu chuyện của nhân vật để chọn nghề phù hợp nhất
- Nghề chính: chọn một nghề từ "danh sách nghề chính khả dụng", điền Tên nghề
- Giai đoạn nghề chính: dựa trên thông tin giai đoạn nghề và thực lực nhân vật để thiết lập giai đoạn hiện tại hợp lý
- Nghề phụ: có thể chọn 0-2 nghề phụ
- ⚠️ Quan trọng: bắt buộc điền tên nghề thay vì ID
</requirements>

<output priority="P0">
[Định dạng đầu ra]
Trả về object JSON thuần:

{{
  "name": "Họ tên nhân vật",
  "age": 25,
  "gender": "nam/nữ/khác",
  "role_type": "supporting",
  "personality": "Mô tả chi tiết đặc điểm tính cách (100-200 chữ)",
  "background": "Mô tả chi tiết câu chuyện nền (100-200 chữ)",
  "appearance": "Mô tả ngoại hình (50-100 chữ)",
  "traits": ["Đặc điểm 1", "Đặc điểm 2", "Đặc điểm 3"],
  "relationships_text": "Dùng ngôn ngữ tự nhiên mô tả mạng lưới quan hệ giữa nhân vật này và các nhân vật khác",
  
  "relationships": [
    {{
      "target_character_name": "Tên nhân vật đã tồn tại",
      "relationship_type": "Loại quan hệ",
      "intimacy_level": 75,
      "description": "Mô tả cụ thể quan hệ",
      "status": "active"
    }}
  ],
  "organization_memberships": [
    {{
      "organization_name": "Tên tổ chức đã tồn tại",
      "position": "Chức vụ",
      "rank": 5,
      "loyalty": 80
    }}
  ],
  
  "career_info": {{
    "main_career_name": "Tên nghề chọn từ danh sách nghề chính khả dụng",
    "main_career_stage": 5,
    "sub_careers": [
      {{
        "career_name": "Tên nghề chọn từ danh sách nghề phụ khả dụng",
        "stage": 3
      }}
    ]
  }}
}}

[Tham chiếu loại quan hệ]
Các loại quan hệ như gia tộc, xã giao, nghề nghiệp, đối địch

[Phạm vi số]
- intimacy_level: -100 đến 100 (âm nghĩa là đối địch)
- loyalty: 0 đến 100
- rank: 0 đến 10
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Khớp nhu cầu cốt truyện và thiết lập bối cảnh thế giới
✅ Bắt buộc có mảng relationships: ít nhất 1-3 quan hệ
✅ target_character_name phải khớp chính xác với [Nhân vật hiện có]
✅ organization_memberships chỉ được tham chiếu tổ chức đã tồn tại
✅ Lựa chọn nghề phải lấy từ danh sách khả dụng

[Điều cấm]
❌ Xuất đánh dấu markdown
❌ Dùng ký hiệu đặc biệt trong mô tả
❌ Trích dẫn nhân vật hoặc tổ chức không tồn tại
❌ Dùng ID nghề thay vì Tên nghề
</constraints>"""

    # 自动组织引入 - 预测性分析提示词（RTCO框架）
    AUTO_ORGANIZATION_ANALYSIS = """<system>
Bạn là cố vấn dựng thế giới tiểu thuyết, giỏi dự đoán nhu cầu tổ chức/thế lực theo diễn biến cốt truyện.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ phân tích]
Dự đoán trong {chapter_count} chương viết tiếp tới, dựa trên hướng và giai đoạn phát triển tình tiết, có cần đưa tổ chức hoặc thế lực mới vào hay không.

[Lưu ý quan trọng]
Đây là phân tích dự đoán, không phải phân tích sau khi đã có nội dung.
Tổ chức bao gồm: bang phái, môn phái, công ty, cơ quan chính phủ, tổ chức thần bí, gia tộc...
</task>

<project priority="P1">
[Thông tin dự án]
Tên sách: {title}
Thể loại: {genre}
Chủ đề: {theme}

[Bối cảnh thế giới]
Bối cảnh thời gian: {time_period}
Vị trí địa lý: {location}
Gam bầu không khí: {atmosphere}
</project>

<context priority="P0">
[Tổ chức hiện có]
{existing_organizations}

[Nhân vật hiện có]
{existing_characters}

[Tổng quan chương hiện có]
{all_chapters_brief}

[Kế hoạch viết tiếp]
- Chương bắt đầu: chương {start_chapter}
- Số chương viết tiếp: {chapter_count}
- Giai đoạn cốt truyện: {plot_stage}
- Hướng phát triển: {story_direction}
</context>

<analysis_framework priority="P0">
[Chiều phân tích dự đoán]

**1. Nhu cầu mở rộng bối cảnh thế giới**
Theo hướng phát triển, có cần thế lực hoặc tổ chức mới để làm phong phú bối cảnh thế giới không?

**2. Nhu cầu leo thang xung đột**
Tình tiết có cần thế lực đối lập, tổ chức cạnh tranh hoặc tập đoàn thần bí mới không?

**3. Nhu cầu quy thuộc nhân vật**
Các nhân vật hiện có có cần gia nhập hoặc đối đầu với tổ chức mới nào không?

**4. Nhu cầu thúc đẩy tình tiết**
Tổ chức mới có thể trở thành lực lượng then chốt thúc đẩy tình tiết không?

**5. Thời điểm đưa vào**
Tổ chức mới nên xuất hiện ở chương nào là phù hợp nhất?

[Căn cứ dự đoán]
- Nhu cầu tổ chức điển hình của giai đoạn tình tiết (ví dụ: cao trào có thể cần thế lực thù địch mạnh)
- Nhu cầu logic của hướng phát triển câu chuyện (ví dụ: bước vào địa điểm mới cần thế lực địa phương)
- Nhu cầu hoàn chỉnh bối cảnh thế giới (ví dụ: cục diện quyền lực cần nhiều thế lực)
- Nhu cầu trưởng thành của nhân vật (ví dụ: nhân vật chính cần gia nhập hoặc thành lập tổ chức)
</analysis_framework>

<output priority="P0">
[Định dạng đầu ra]
Trả về object JSON thuần (một trong hai trường hợp):

**Trường hợp A: cần tổ chức mới**
{{
"needs_new_organizations": true,
"reason": "Lý do phân tích dự đoán (150-200 chữ), giải thích vì sao tình tiết sắp tới cần tổ chức mới",
"organization_count": 1,
"organization_specifications": [
{{
  "name": "Tên tổ chức được đề xuất (tuỳ chọn)",
  "organization_description": "Định vị và vai trò của tổ chức trong tình tiết (100-150 chữ)",
  "organization_type": "bang phái/môn phái/công ty/chính phủ/gia tộc/tổ chức thần bí...",
  "importance": "high/medium/low",
  "appearance_chapter": {start_chapter},
  "power_level": 70,
  "plot_function": "Chức năng cụ thể trong tình tiết",
  "location": "Nơi tổ chức đặt trụ sở hoặc khu vực hoạt động",
  "motto": "Khẩu hiệu hoặc tôn chỉ tổ chức (tuỳ chọn)",
  "initial_members": [
    {{
      "character_name": "Tên nhân vật hiện có (nếu cần gia nhập)",
      "position": "Chức vụ",
      "reason": "Vì sao gia nhập"
    }}
  ],
  "relationship_suggestions": [
    {{
      "target_organization": "Tên tổ chức đã có",
      "relationship_type": "Loại quan hệ được đề xuất (ví dụ: Bạn bè, Đồng nghiệp, Kẻ thù...)",
      "reason": "Vì sao thiết lập quan hệ này"
    }}
  ]
}}
]
}}

**Trường hợp B: không cần tổ chức mới**
{{
"needs_new_organizations": false,
"reason": "Các tổ chức hiện có đã đủ để nâng đỡ tình tiết sắp tới, nêu rõ lý do"
}}
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Đây là phân tích dự đoán, hướng tới cốt truyện tương lai
✅ Cân nhắc sự phong phú và hoàn chỉnh của bối cảnh thế giới
✅ Đảm bảo sự cần thiết khi đưa vào, không đưa vào vì đưa vào
✅ Ưu tiên vai trò lâu dài của tổ chức
✅ Tổ chức phải là lực lượng then chốt thúc đẩy tình tiết

[Điều cấm]
❌ Xuất đánh dấu markdown
❌ Phân tích sau việc dựa trên nội dung đã tạo
❌ Cưỡng ép đưa tổ chức vào chỉ để đưa vào
❌ Thiết kế tổ chức chức năng chỉ tồn tại một lần
❌ Tạo tổ chức trùng chức năng với tổ chức hiện có
</constraints>"""

    # 自动组织引入 - 生成提示词（RTCO框架）
    AUTO_ORGANIZATION_GENERATION = """<system>
Bạn là chuyên gia dựng thế giới, giỏi tạo thiết lập tổ chức/thế lực hoàn chỉnh theo nhu cầu cốt truyện.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ tạo]
Tạo thiết lập hoàn chỉnh cho tổ chức mới của tiểu thuyết, gồm thông tin cơ bản, đặc tính tổ chức, lịch sử bối cảnh và cơ cấu thành viên.
</task>

<project priority="P1">
[Thông tin dự án]
Tên sách: {title}
Thể loại: {genre}
Chủ đề: {theme}

[Bối cảnh thế giới]
Bối cảnh thời gian: {time_period}
Vị trí địa lý: {location}
Gam bầu không khí: {atmosphere}
Quy tắc thế giới: {rules}
</project>

<context priority="P0">
[Tổ chức hiện có]
{existing_organizations}

[Nhân vật hiện có]
{existing_characters}

[Ngữ cảnh cốt truyện]
{plot_context}

[Yêu cầu đặc tả tổ chức]
{organization_specification}
</context>

<mcp_context priority="P2">
[Tham chiếu công cụ MCP]
{mcp_references}
</mcp_context>

<requirements priority="P0">
[Yêu cầu cốt lõi]
1. Tổ chức phải phù hợp với nhu cầu tình tiết và thiết lập bối cảnh thế giới
2. Tổ chức phải có mục đích, cơ cấu và đặc trưng rõ ràng
3. Đặc tính và bối cảnh tổ chức phải có chiều sâu và nét riêng
4. Biểu hiện bên ngoài phải cụ thể, sinh động
5. Cân nhắc quan hệ và tương tác với tổ chức hiện có
6. Nếu cần, có thể đề xuất để nhân vật hiện có gia nhập tổ chức
</requirements>

<output priority="P0">
[Định dạng đầu ra]
Trả về object JSON thuần:

{{
"name": "Tên tổ chức",
"is_organization": true,
"role_type": "supporting",
"organization_type": "Loại tổ chức (bang phái/môn phái/công ty/chính phủ/gia tộc/tổ chức thần bí...)",
"personality": "Mô tả chi tiết đặc tính tổ chức (150-200 chữ): cách vận hành, ý niệm cốt lõi, phong cách hành sự, giá trị văn hóa",
"background": "Câu chuyện nền của tổ chức (200-300 chữ): lịch sử thành lập, quá trình phát triển, sự kiện quan trọng, địa vị hiện tại",
"appearance": "Biểu hiện bên ngoài (100-150 chữ): vị trí trụ sở, công trình biểu tượng, biểu trưng tổ chức, trang phục thành viên",
"organization_purpose": "Mục đích và tôn chỉ tổ chức: mục tiêu rõ ràng, tầm nhìn dài hạn, nguyên tắc hành động",
"power_level": 75,
"location": "Địa điểm: khu vực hoạt động chính, phạm vi thế lực",
"motto": "Châm ngôn hoặc khẩu hiệu tổ chức",
"color": "Màu đại diện tổ chức",
"traits": ["Đặc trưng 1", "Đặc trưng 2", "Đặc trưng 3"],

"initial_members": [
{{
  "character_name": "Tên nhân vật đã tồn tại",
  "position": "Tên chức vụ",
  "rank": 8,
  "loyalty": 80,
  "joined_at": "Thời điểm gia nhập (tuỳ chọn)",
  "status": "active"
}}
],

"organization_relationships": [
{{
  "target_organization_name": "Tên tổ chức đã tồn tại",
  "relationship_type": "Loại quan hệ (ví dụ: Bạn bè, Đồng nghiệp, Đối tác, Kẻ thù...)",
  "description": "Mô tả cụ thể quan hệ"
}}
]
}}

[Phạm vi số]
- power_level: số nguyên 0-100, thể hiện ảnh hưởng trong thế giới
- rank: 0 đến 10 (cấp chức vụ)
- loyalty: 0 đến 100 (lòng trung thành của thành viên)
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Khớp nhu cầu cốt truyện và thiết lập bối cảnh thế giới
✅ Tổ chức phải có định vị và giá trị riêng
✅ character_name phải khớp chính xác với [Nhân vật hiện có]
✅ target_organization_name phải khớp chính xác với [Tổ chức hiện có]
✅ Tổ chức có thể thúc đẩy diễn biến tình tiết

[Điều cấm]
❌ Xuất đánh dấu markdown
❌ Dùng ký hiệu đặc biệt trong mô tả
❌ Trích dẫn nhân vật hoặc tổ chức không tồn tại
❌ Tạo tổ chức trùng chức năng với tổ chức hiện có
❌ Tạo tổ chức không có tác dụng thực tế đối với tình tiết
</constraints>"""

    # 职业体系生成提示词 V2（RTCO框架）
    CAREER_SYSTEM_GENERATION = """<system>
Bạn là nhà thiết kế hệ nghề chuyên nghiệp, giỏi thiết kế hệ nghề hoàn chỉnh cho các bối cảnh thế giới khác nhau.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ thiết kế]
Dựa trên thông tin bối cảnh thế giới và phần giới thiệu dự án, thiết kế một hệ nghề hoàn chỉnh và hợp lý.
Hệ nghề phải rất phù hợp với bối cảnh câu chuyện và thiết lập nhân vật trong phần giới thiệu dự án.

[Yêu cầu số lượng]
- Nghề chính: tạo chính xác 1 nghề
- Nghề phụ: tạo chính xác 1 nghề
</task>

<worldview priority="P0">
[Thông tin dự án]
Tên sách: {title}
Thể loại: {genre}
Chủ đề: {theme}
Mô tả: {description}

[Thiết lập bối cảnh thế giới]
Bối cảnh thời gian: {time_period}
Vị trí địa lý: {location}
Gam bầu không khí: {atmosphere}
Quy tắc thế giới: {rules}
</worldview>

<design_requirements priority="P0">
[Yêu cầu thiết kế]

**1. Nghề chính (main_careers) - bắt buộc tạo chính xác 1 nghề**
- Nghề chính là hướng phát triển cốt lõi của nhân vật
- Phải tuyệt đối phù hợp với quy tắc bối cảnh thế giới và bối cảnh câu chuyện trong phần giới thiệu
- Số giai đoạn của mỗi nghề chính có thể khác nhau (thể hiện độ phức tạp nghề nghiệp)
- Thiết kế nghề phải nâng đỡ tình tiết được mô tả trong phần giới thiệu

**2. Nghề phụ (sub_careers) - bắt buộc tạo chính xác 1 nghề**
- Nghề phụ bao gồm nhóm sản xuất, hỗ trợ và kỹ năng đặc biệt
- Số giai đoạn của mỗi nghề phụ có thể khác nhau
- Không để mọi nghề phụ có cùng số giai đoạn
- Nghề phụ phải hỗ trợ hoặc tăng cường cho nghề chính

**3. Thiết kế giai đoạn (stages)**
- Độ dài mảng stages của mỗi nghề phải bằng max_stage
- Tên giai đoạn phải phù hợp với bối cảnh văn hóa của thế giới
- Mô tả giai đoạn phải thể hiện lộ trình nâng cao năng lực rõ ràng
- Đảm bảo số giai đoạn giữa các nghề có sự khác biệt
- Số giai đoạn nghề chính đề xuất: 8-12
- Số giai đoạn nghề phụ đề xuất: 5-8

**4. Mức độ phù hợp với phần giới thiệu**
- Hệ nghề phải phù hợp với thiết lập câu chuyện trong phần giới thiệu dự án
- Nếu phần giới thiệu nhắc đến nghề hoặc năng lực cụ thể, ưu tiên thiết kế nghề liên quan
- Năng lực và đặc điểm nghề phải nâng đỡ diễn biến tình tiết trong phần giới thiệu
</design_requirements>

<output priority="P0">
[Định dạng đầu ra]
Trả về object JSON thuần:

{{
"main_careers": [
{{
  "name": "Tên nghề",
  "description": "Mô tả nghề (100-150 chữ)",
  "category": "Phân loại nghề",
  "stages": [
    {{"level": 1, "name": "Tên giai đoạn 1", "description": "Mô tả giai đoạn"}},
    {{"level": 2, "name": "Tên giai đoạn 2", "description": "Mô tả giai đoạn"}}
  ],
  "max_stage": số nguyên,
  "requirements": "Yêu cầu nghề và điều kiện tiên quyết",
  "special_abilities": "Năng lực đặc biệt của nghề",
  "worldview_rules": "Mối liên hệ với quy tắc bối cảnh thế giới",
  "attribute_bonuses": {{"strength": "+10%"}}
}}
],
"sub_careers": [
{{
  "name": "Tên nghề phụ",
  "description": "Mô tả nghề (80-120 chữ)",
  "category": "Hệ sản xuất/hệ hỗ trợ/hệ đặc biệt",
  "stages": [
    {{"level": 1, "name": "Tên giai đoạn 1", "description": "Mô tả giai đoạn"}}
  ],
  "max_stage": số nguyên,
  "requirements": "Yêu cầu nghề",
  "special_abilities": "Năng lực đặc biệt"
}}
]
}}
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Số nghề chính: bắt buộc tạo chính xác 1 nghề, không hơn không kém
✅ Số nghề phụ: bắt buộc tạo chính xác 1 nghề, không hơn không kém
✅ Số giai đoạn nghề chính đề xuất: 8-12
✅ Số giai đoạn nghề phụ đề xuất: 5-8
✅ Độ dài mảng stages phải bằng max_stage
✅ Đảm bảo hệ nghề rất phù hợp với bối cảnh thế giới
✅ Thiết kế nghề phải nâng đỡ tình tiết trong phần giới thiệu dự án

[Điều cấm]
❌ Mọi nghề đều dùng cùng số giai đoạn
❌ Xuất đánh dấu markdown
❌ Thiết kế nghề tách rời bối cảnh thế giới hoặc phần giới thiệu
❌ Bỏ qua thiết lập nghề hoặc năng lực được nhắc trong phần giới thiệu
</constraints>"""

    # 局部重写提示词（RTCO框架）
    PARTIAL_REGENERATE = """<system>
Bạn là trợ lý viết lại tiểu thuyết chuyên nghiệp, giỏi viết lại chính xác đoạn chỉ định theo yêu cầu người dùng, đồng thời đảm bảo nối mượt với ngữ cảnh trước/sau.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ viết lại]
Dựa trên yêu cầu chỉnh sửa của người dùng, viết lại đoạn văn được chọn dưới đây.

[Yêu cầu quan trọng]
1. Chỉ xuất nội dung đã viết lại, không kèm bất kỳ giải thích, tiền tố hay hậu tố nào
2. Giữ sự nối tiếp tự nhiên và giọng văn mạch lạc với phần trước và sau
3. Tuân thủ nghiêm ngặt yêu cầu chỉnh sửa của người dùng
4. Giữ tính nhất quán của phong cách tự sự tổng thể
</task>

<context priority="P0">
[Tham chiếu phần trước] (dùng để nối tiếp, không lặp lại)
{context_before}

[Văn bản gốc cần viết lại] (tổng cộng {original_word_count} chữ)
{selected_text}

[Tham chiếu phần sau] (dùng để nối tiếp, không lặp lại)
{context_after}
</context>

<user_requirements priority="P0">
[Yêu cầu chỉnh sửa của người dùng]
{user_instructions}

[Yêu cầu số chữ]
{length_requirement}
</user_requirements>

<style priority="P1">
[Phong cách viết]
{style_content}
</style>

<output>
[Quy chuẩn đầu ra]
Xuất trực tiếp nội dung đã viết lại, bắt đầu từ nội dung câu chuyện.
- Không xuất bất kỳ chữ giải thích hay thuyết minh nào
- Không xuất tiền tố như "Sau khi viết lại:"
- Không bọc nội dung trong dấu ngoặc kép
- Đảm bảo nội dung xuất ra có thể thay thế trực tiếp văn bản gốc

Hãy trực tiếp xuất nội dung đã viết lại:
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Nối trước sau: nội dung xuất ra phải nối tự nhiên với phần trước và chuyển tiếp mượt mà sang phần sau
✅ Nhất quán phong cách: giữ phong cách tự sự, giọng văn và ngôi kể giống văn bản gốc
✅ Ưu tiên yêu cầu: thực hiện nghiêm ngặt yêu cầu chỉnh sửa của người dùng
✅ Kiểm soát số chữ: tuân thủ yêu cầu số chữ

[Điều cấm]
❌ Lặp nội dung phần trước
❌ Lặp nội dung phần sau
❌ Thêm bất kỳ siêu thông tin hoặc lời thuyết minh nào
❌ Thay đổi ngôi kể hoặc góc nhìn tự sự
❌ Đi lệch yêu cầu chỉnh sửa của người dùng
</constraints>"""

    # 拆书导入-反向项目提炼提示词
    BOOK_IMPORT_REVERSE_PROJECT_SUGGESTION = """<system>
Bạn là biên tập hoạch định tiểu thuyết mạng dày dạn, giỏi suy ngược thông tin khởi tạo dự án từ chính văn tiểu thuyết.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ]
Dựa trên nội dung 3 chương đầu được cung cấp, chắt lọc thông tin khởi tạo cốt lõi của tiểu thuyết để tạo dự án mới.

[Mục tiêu]
Không đi lệch văn bản gốc, xuất thông tin có cấu trúc có thể dùng trực tiếp để khởi tạo dự án.
</task>

<input priority="P0">
[Thông tin đầu vào]
Tên sách: {title}
Nội dung 3 chương đầu:
{sampled_text}
</input>

<output priority="P0">
[Định dạng đầu ra]
Chỉ xuất một object JSON thuần (không markdown, không khối mã, không giải thích):

{{
  "description": "Giới thiệu tiểu thuyết",
  "theme": "Chủ đề cốt lõi",
  "genre": "Thể loại tiểu thuyết",
  "narrative_perspective": "第一人称 (ngôi thứ nhất) / 第三人称 (ngôi thứ ba) / 全知视角 (toàn tri)",
  "target_words": 100000
}}

[Yêu cầu trường]
1) description: 120-260 chữ, tập trung vào nhân vật chính, xung đột cốt lõi, mục tiêu tuyến chính và sức căng câu chuyện.
2) theme: 120-260 chữ, chắt lọc mệnh đề cốt lõi mà tác phẩm muốn thể hiện.
3) genre: 2-12 chữ, ví dụ đô thị, huyền huyễn, trinh thám, khoa huyễn, ngôn tình...
4) narrative_perspective: chỉ được là "第一人称" (ngôi thứ nhất), "第三人称" (ngôi thứ ba) hoặc "全知视角" (góc nhìn toàn tri).
5) target_words: số nguyên. Ước tính hợp lý theo quy mô tiểu thuyết mạng; nếu không thể phán đoán thì trả về 100000.
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Tuyệt đối dựa trên nội dung chính văn đã cung cấp, không tự ý thêm thiết lập then chốt
✅ Giữ thông tin nhất quán, tránh mâu thuẫn lẫn nhau
✅ Đầu ra phải là object JSON có thể phân tích
✅ genre của tiểu thuyết có thể gồm nhiều thể loại

[Điều cấm]
❌ Xuất bất kỳ chữ nào ngoài JSON
❌ Dùng markdown hoặc khối mã để bọc
❌ Để narrative_perspective xuất nội dung ngoài các giá trị enum
❌ Để target_words xuất giá trị không phải số nguyên
</constraints>"""

    # 拆书导入-反向生成章节大纲（严格对齐 OUTLINE_CREATE 结构）
    BOOK_IMPORT_REVERSE_OUTLINES = """<system>
Bạn là tổng biên tập tiểu thuyết mạng và hoạch định cốt truyện dày dạn, giỏi suy ngược dàn ý chương chuẩn hóa từ các chương đã hoàn thành.
</system>

[Yêu cầu ngôn ngữ]Mọi nội dung văn bản tạo ra (trừ tên trường JSON/key kỹ thuật) phải viết bằng tiếng Việt tự nhiên.

<task>
[Nhiệm vụ]
Dựa trên chính văn chương được cung cấp (mỗi lô tối đa 5 chương), tạo ngược cấu trúc dàn ý tương ứng cho từng chương.

[Mục tiêu cốt lõi]
Cấu trúc đầu ra phải hoàn toàn nhất quán với cấu trúc tạo dàn ý hiện có của hệ thống (khớp các trường của OUTLINE_CREATE), để dùng trực tiếp khi lưu vào cơ sở dữ liệu.
</task>

<project priority="P0">
[Thông tin dự án]
Tên sách: {title}
Thể loại: {genre}
Chủ đề: {theme}
Góc kể chuyện: {narrative_perspective}
</project>

<input priority="P0">
[Phạm vi lô]
Chương {start_chapter} - chương {end_chapter} (tổng cộng {expected_count} chương)

[Nội dung chương]
{chapters_text}
</input>

<output priority="P0">
[Định dạng đầu ra]
Chỉ xuất mảng JSON thuần (không markdown, không khối mã, không giải thích).
Độ dài mảng phải chính xác bằng {expected_count}.

Các trường của mỗi object phải chính xác là:
[
  {{
    "chapter_number": 1,
    "title": "Tiêu đề chương",
    "summary": "Tóm tắt chương (200-600 chữ): tình tiết chính, tương tác nhân vật, sự kiện then chốt, xung đột và bước ngoặt",
    "scenes": ["Mô tả cảnh 1", "Mô tả cảnh 2"],
    "characters": [
      {{"name": "Tên nhân vật 1", "type": "character"}},
      {{"name": "Tên tổ chức/thế lực 1", "type": "organization"}}
    ],
    "key_points": ["Điểm tình tiết 1", "Điểm tình tiết 2"],
    "emotion": "Gam cảm xúc chương này",
    "goal": "Mục tiêu kể chuyện chương này"
  }}
]

[Ràng buộc trường]
- chapter_number: phải nhất quán với số chương đầu vào
- title: phải nhất quán với tiêu đề chương đầu vào
- summary: chắt lọc ngược từ chính văn chương này, không được bịa sự kiện then chốt chưa xuất hiện
- scenes: 2-6 mục
- characters: có thể rỗng; type chỉ cho phép character hoặc organization
- key_points: 2-6 mục
- emotion: một câu
- goal: một câu
</output>

<constraints>
[Bắt buộc tuân thủ]
✅ Mỗi chương tương ứng chính xác một object, số lượng và thứ tự hoàn toàn nhất quán
✅ Tên trường, cấp trường và kiểu trường phải hoàn toàn nhất quán
✅ Chỉ chắt lọc dựa trên chính văn đầu vào, không tự ý mở rộng thiết lập
✅ Đầu ra phải được JSON phân tích trực tiếp

[Điều cấm]
❌ Xuất bất kỳ văn bản nào ngoài JSON
❌ Thiếu trường hoặc thêm trường mới
❌ chapter_number/title không nhất quán với đầu vào
❌ Dùng markdown hoặc khối mã
</constraints>"""

    @staticmethod
    def format_prompt(template: str, **kwargs) -> str:
        """
        格式化提示词模板
        
        Args:
            template: 提示词模板
            **kwargs: 模板参数
            
        Returns:
            格式化后的提示词
        """
        try:
            return template.format(**kwargs)
        except KeyError as e:
            raise ValueError(f"Thiếu tham số bắt buộc: {e}")
    

    @classmethod
    async def get_chapter_regeneration_prompt(cls, chapter_number: int, title: str, word_count: int, content: str,
                                        modification_instructions: str, project_context: Dict[str, Any],
                                        style_content: str, target_word_count: int,
                                        user_id: str = None, db = None) -> str:
        """
        获取章节重写提示词（支持用户自定义）
        
        Args:
            chapter_number: 章节序号
            title: 章节标题
            word_count: 原始字数
            content: 原始内容
            modification_instructions: 修改指令
            project_context: 项目上下文
            style_content: 写作风格
            target_word_count: 目标字数
            user_id: 用户ID（可选，用于获取自定义模板）
            db: 数据库会话（可选，用于查询自定义模板）
            
        Returns:
            完整的章节重写提示词
        """
        # 获取系统提示词模板（支持用户自定义）
        if user_id and db:
            system_template = await cls.get_template("CHAPTER_REGENERATION_SYSTEM", user_id, db)
        else:
            system_template = cls.CHAPTER_REGENERATION_SYSTEM
        
        prompt_parts = [system_template]
        
        # 原始章节信息
        prompt_parts.append(f"""## 📖 Thông tin chương gốc

**Chương**: chương {chapter_number}
**Tiêu đề**: {title}
**Số chữ**: {word_count} chữ

**Nội dung gốc**:
{content}

---
""")
        
        # 修改指令
        prompt_parts.append(modification_instructions)
        prompt_parts.append("\n---\n")
        
        # 项目背景信息
        prompt_parts.append(f"""## 🌍 Thông tin bối cảnh dự án

**Tên tiểu thuyết**: {project_context.get('project_title', 'Chưa đặt tên')}
**Đề tài**: {project_context.get('genre', 'Chưa thiết lập')}
**Chủ đề**: {project_context.get('theme', 'Chưa thiết lập')}
**Góc kể chuyện**: {project_context.get('narrative_perspective', '第三人称')}
**Thiết lập bối cảnh thế giới**:
- Bối cảnh thời đại: {project_context.get('time_period', 'Chưa thiết lập')}
- Vị trí địa lý: {project_context.get('location', 'Chưa thiết lập')}
- Gam bầu không khí: {project_context.get('atmosphere', 'Chưa thiết lập')}

---
""")
        
        # 角色信息
        if project_context.get('characters_info'):
            prompt_parts.append(f"""## 👥 Thông tin nhân vật

{project_context['characters_info']}

---
""")
        
        # 章节大纲
        if project_context.get('chapter_outline'):
            prompt_parts.append(f"""## 📝 Dàn ý chương này

{project_context['chapter_outline']}

---
""")
        
        # 前置章节上下文
        if project_context.get('previous_context'):
            prompt_parts.append(f"""## 📚 Ngữ cảnh các chương trước

{project_context['previous_context']}

---
""")
        
        # 写作风格要求
        if style_content:
            prompt_parts.append(f"""## 🎨 Yêu cầu phong cách viết

{style_content}

Khi sáng tác lại, hãy tuân thủ nghiêm ngặt phong cách viết trên.

---
""")
        
        # 创作要求
        prompt_parts.append(f"""## ✨ Yêu cầu sáng tác

1. **Giải quyết vấn đề**: cải thiện mọi vấn đề được nêu trong chỉ thị chỉnh sửa ở trên
2. **Giữ tính mạch lạc**: đảm bảo tình tiết, nhân vật và phong cách nhất quán với các chương trước sau
3. **Nâng cao chất lượng**: tốt hơn rõ rệt so với bản gốc về nhịp độ, cảm xúc và miêu tả
4. **Giữ tinh hoa**: giữ lại những phần xuất sắc và tình tiết then chốt của chương gốc
5. **Kiểm soát số chữ**: mục tiêu khoảng {target_word_count} chữ (có thể dao động ±20% phù hợp)
{f'6. **Nhất quán phong cách**: sáng tác nghiêm ngặt theo phong cách viết trên' if style_content else ''}

---

## 🎬 Bắt đầu sáng tác

Hãy bắt đầu sáng tác nội dung chương mới được cải thiện ngay bây giờ.

**Lưu ý quan trọng**:
- Trực tiếp xuất nội dung chính văn chương, bắt đầu từ nội dung câu chuyện
- **Không** xuất tiêu đề chương (như "Chương X", "Chương X: XXX")
- **Không** xuất bất kỳ lời thuyết minh, chú thích hay siêu dữ liệu nào
- Chỉ cần nội dung chính văn câu chuyện thuần túy

Bắt đầu ngay:
""")
        
        return "\n".join(prompt_parts)

    @classmethod
    async def get_mcp_tool_test_prompts(
        cls,
        plugin_name: str,
        user_id: str = None,
        db = None
    ) -> Dict[str, str]:
        """
        获取MCP工具测试的提示词（支持自定义）
        
        Args:
            plugin_name: 插件名称
            user_id: 用户ID（可选）
            db: 数据库会话（可选）
            
        Returns:
            包含user和system提示词的字典
        """
        # 获取用户自定义或系统默认的user提示词
        if user_id and db:
            user_template = await cls.get_template("MCP_TOOL_TEST", user_id, db)
        else:
            user_template = cls.MCP_TOOL_TEST
        
        # 获取用户自定义或系统默认的system提示词
        if user_id and db:
            system_template = await cls.get_template("MCP_TOOL_TEST_SYSTEM", user_id, db)
        else:
            system_template = cls.MCP_TOOL_TEST_SYSTEM
        
        return {
            "user": cls.format_prompt(user_template, plugin_name=plugin_name),
            "system": system_template
        }

    # ========== 自定义提示词支持 ==========
    
    @classmethod
    async def get_template_with_fallback(cls,
                                        template_key: str,
                                        user_id: str = None,
                                        db = None) -> str:
        """
        获取提示词模板（优先用户自定义，支持降级）
        
        Args:
            template_key: khóa mẫu
            user_id: 用户ID（可选，如果不提供则直接返回系统默认）
            db: 数据库会话（可选）
            
        Returns:
            提示词模板内容
        """
        # 如果没有提供user_id或db，直接返回系统默认
        if not user_id or not db:
            return getattr(cls, template_key, None)
        
        # 尝试获取用户自定义模板
        return await cls.get_template(template_key, user_id, db)
    
    @classmethod
    async def get_template(cls,
                          template_key: str,
                          user_id: str,
                          db) -> str:
        """
        获取提示词模板（优先用户自定义）
        
        Args:
            template_key: khóa mẫu
            user_id: 用户ID
            db: 数据库会话
            
        Returns:
            提示词模板内容
        """
        from sqlalchemy import select
        from app.models.prompt_template import PromptTemplate
        from app.logger import get_logger
        
        logger = get_logger(__name__)
        
        # 1. 尝试从数据库获取用户自定义模板
        result = await db.execute(
            select(PromptTemplate).where(
                PromptTemplate.user_id == user_id,
                PromptTemplate.template_key == template_key,
                PromptTemplate.is_active == True
            )
        )
        custom_template = result.scalar_one_or_none()
        
        if custom_template:
            logger.info(f"✅ 使用用户自定义提示词: user_id={user_id}, template_key={template_key}, template_name={custom_template.template_name}")
            return custom_template.template_content
        
        # 2. 降级到系统默认模板
        logger.info(f"⚪ 使用系统默认提示词: user_id={user_id}, template_key={template_key} (未找到自定义模板)")
        
        # 直接从类属性获取系统默认模板
        template_content = getattr(cls, template_key, None)
        
        if template_content is None:
            logger.warning(f"⚠️ 未找到系统默认模板: {template_key}")
        
        return template_content
    
    @classmethod
    def get_all_system_templates(cls) -> list:
        """
        获取所有系统默认模板的信息
        
        Returns:
            系统模板列表
        """
        templates = []
        
        # 定义所有模板及其元信息
        template_definitions = {
            "NOVEL_COVER_PROMPT_TEMPLATE": {
                "name": "Tạo bìa tiểu thuyết",
                "category": "Tạo bìa",
                "description": "Tạo prompt vẽ bìa tiểu thuyết dựa trên thông tin cơ bản của dự án, phù hợp bìa sách khổ dọc",
                "parameters": ["title", "genre", "theme", "description"]
            },
            "WORLD_BUILDING": {
                "name": "Dựng bối cảnh thế giới",
                "category": "Bối cảnh thế giới",
                "description": "Dùng để tạo thiết lập bối cảnh thế giới của tiểu thuyết, gồm bối cảnh thời gian, vị trí địa lý, gam bầu không khí và quy tắc thế giới",
                "parameters": ["title", "theme", "genre", "description"]
            },
            "BOOK_IMPORT_REVERSE_PROJECT_SUGGESTION": {
                "name": "Nhập phân tích sách - Chắt lọc dự án ngược",
                "category": "Nhập phân tích sách",
                "description": "Dựa trên nội dung 3 chương đầu, chắt lọc ngược phần giới thiệu, chủ đề, thể loại, góc kể chuyện và số chữ mục tiêu",
                "parameters": ["title", "sampled_text"]
            },
            "BOOK_IMPORT_REVERSE_OUTLINES": {
                "name": "Nhập phân tích sách - Dàn ý chương ngược",
                "category": "Nhập phân tích sách",
                "description": "Dựa trên chính văn chương, tạo ngược dàn ý có cấu trúc khớp OUTLINE_CREATE (một lô 5 chương)",
                "parameters": [
                    "title", "genre", "theme", "narrative_perspective",
                    "start_chapter", "end_chapter", "expected_count", "chapters_text"
                ]
            },
            "CHARACTERS_BATCH_GENERATION": {
                "name": "Tạo nhân vật hàng loạt",
                "category": "Tạo nhân vật",
                "description": "Tạo hàng loạt nhiều nhân vật và tổ chức, dựng mạng quan hệ nhân vật",
                "parameters": ["count", "time_period", "location", "atmosphere", "rules", "theme", "genre", "requirements"]
            },
            "SINGLE_CHARACTER_GENERATION": {
                "name": "Tạo nhân vật đơn lẻ",
                "category": "Tạo nhân vật",
                "description": "Tạo thiết lập chi tiết cho một nhân vật",
                "parameters": ["project_context", "user_input"]
            },
            "SINGLE_ORGANIZATION_GENERATION": {
                "name": "Tạo tổ chức",
                "category": "Tạo nhân vật",
                "description": "Tạo thiết lập chi tiết cho tổ chức/thế lực",
                "parameters": ["project_context", "user_input"]
            },
            "OUTLINE_CREATE": {
                "name": "Tạo dàn ý",
                "category": "Tạo dàn ý",
                "description": "Tạo dàn ý chương hoàn chỉnh dựa trên thông tin dự án",
                "parameters": ["title", "theme", "genre", "chapter_count", "narrative_perspective", "target_words", 
                             "time_period", "location", "atmosphere", "rules", "characters_info", "requirements", "mcp_references"]
            },
            "OUTLINE_CONTINUE": {
                "name": "Viết tiếp dàn ý",
                "category": "Tạo dàn ý",
                "description": "Viết tiếp dàn ý dựa trên các chương hiện có",
                "parameters": ["title", "theme", "genre", "narrative_perspective", "chapter_count", "time_period", 
                             "location", "atmosphere", "rules", "characters_info", "current_chapter_count", 
                             "all_chapters_brief", "recent_plot", "memory_context", "mcp_references", 
                             "plot_stage_instruction", "start_chapter", "end_chapter", "story_direction", "requirements"]
            },
            "CHAPTER_GENERATION_ONE_TO_MANY": {
                "name": "Sáng tác chương - chế độ 1-N (chương 1)",
                "category": "Sáng tác chương",
                "description": "Chế độ 1-N: sáng tác nội dung chương theo dàn ý (dùng cho chương 1, không có chương trước)",
                "parameters": ["project_title", "genre", "chapter_number", "chapter_title", "chapter_outline",
                             "target_word_count", "narrative_perspective", "characters_info"]
            },
            "CHAPTER_GENERATION_ONE_TO_MANY_NEXT": {
                "name": "Sáng tác chương - chế độ 1-N (từ chương 2 trở đi)",
                "category": "Sáng tác chương",
                "description": "Chế độ 1-N: sáng tác chương mới dựa trên nội dung chương trước (dùng từ chương 2 trở đi)",
                "parameters": ["project_title", "genre", "chapter_number", "chapter_title", "chapter_outline",
                             "target_word_count", "narrative_perspective", "characters_info", "continuation_point",
                             "foreshadow_reminders", "relevant_memories", "story_skeleton", "previous_chapter_summary"]
            },
            "CHAPTER_GENERATION_ONE_TO_ONE": {
                "name": "Sáng tác chương - chế độ 1-1 (chương 1)",
                "category": "Sáng tác chương",
                "description": "Chế độ 1-1: sáng tác chương (dùng cho chương 1, không có chương trước)",
                "parameters": ["project_title", "genre", "chapter_number", "chapter_title", "chapter_outline",
                             "target_word_count", "narrative_perspective", "characters_info", "chapter_careers"]
            },
            "CHAPTER_GENERATION_ONE_TO_ONE_NEXT": {
                "name": "Sáng tác chương - chế độ 1-1 (từ chương 2 trở đi)",
                "category": "Sáng tác chương",
                "description": "Chế độ 1-1: sáng tác chương mới dựa trên nội dung chương trước (dùng từ chương 2 trở đi)",
                "parameters": ["project_title", "genre", "chapter_number", "chapter_title", "chapter_outline",
                             "target_word_count", "narrative_perspective", "previous_chapter_content",
                             "characters_info", "chapter_careers", "foreshadow_reminders", "relevant_memories"]
            },
            "CHAPTER_REGENERATION_SYSTEM": {
                "name": "Prompt hệ thống viết lại chương",
                "category": "Viết lại chương",
                "description": "Prompt hệ thống dùng để viết lại chương",
                "parameters": ["chapter_number", "title", "word_count", "content", "modification_instructions",
                             "project_context", "style_content", "target_word_count"]
            },
            "PARTIAL_REGENERATE": {
                "name": "Viết lại cục bộ",
                "category": "Viết lại chương",
                "description": "Viết lại đoạn đã chọn theo yêu cầu chỉnh sửa của người dùng",
                "parameters": ["context_before", "original_word_count", "selected_text", "context_after",
                             "user_instructions", "length_requirement", "style_content"]
            },
            "PLOT_ANALYSIS": {
                "name": "Phân tích tình tiết",
                "category": "Phân tích tình tiết",
                "description": "Phân tích sâu tình tiết, móc câu, phục bút... của chương",
                "parameters": ["chapter_number", "title", "content", "word_count"]
            },
            "OUTLINE_EXPAND_SINGLE": {
                "name": "Mở rộng dàn ý một lô",
                "category": "Mở rộng tình tiết",
                "description": "Mở rộng nút dàn ý thành kế hoạch chương chi tiết (một lô)",
                "parameters": ["project_title", "project_genre", "project_theme", "project_narrative_perspective", 
                             "project_world_time_period", "project_world_location", "project_world_atmosphere", 
                             "characters_info", "outline_order_index", "outline_title", "outline_content", 
                             "context_info", "strategy_instruction", "target_chapter_count", "scene_instruction", "scene_field"]
            },
            "OUTLINE_EXPAND_MULTI": {
                "name": "Mở rộng dàn ý theo lô",
                "category": "Mở rộng tình tiết",
                "description": "Mở rộng nút dàn ý thành kế hoạch chương chi tiết (theo từng lô)",
                "parameters": ["project_title", "project_genre", "project_theme", "project_narrative_perspective", 
                             "project_world_time_period", "project_world_location", "project_world_atmosphere", 
                             "characters_info", "outline_order_index", "outline_title", "outline_content", 
                             "context_info", "previous_context", "strategy_instruction", "start_index", 
                             "end_index", "target_chapter_count", "scene_instruction", "scene_field"]
            },
            "MCP_TOOL_TEST": {
                "name": "Kiểm thử công cụ MCP (prompt người dùng)",
                "category": "Kiểm thử MCP",
                "description": "Prompt người dùng dùng để kiểm thử chức năng plugin MCP",
                "parameters": ["plugin_name"]
            },
            "MCP_TOOL_TEST_SYSTEM": {
                "name": "Kiểm thử công cụ MCP (prompt hệ thống)",
                "category": "Kiểm thử MCP",
                "description": "Prompt hệ thống dùng để kiểm thử chức năng plugin MCP",
                "parameters": []
            },
            "MCP_WORLD_BUILDING_PLANNING": {
                "name": "Lập kế hoạch bối cảnh thế giới MCP",
                "category": "Tăng cường MCP",
                "description": "Dùng công cụ MCP tìm tài liệu hỗ trợ thiết kế bối cảnh thế giới",
                "parameters": ["title", "genre", "theme", "description"]
            },
            "MCP_CHARACTER_PLANNING": {
                "name": "Lập kế hoạch nhân vật MCP",
                "category": "Tăng cường MCP",
                "description": "Dùng công cụ MCP tìm tài liệu hỗ trợ thiết kế nhân vật",
                "parameters": ["title", "genre", "theme", "time_period", "location"]
            },
            "AUTO_CHARACTER_ANALYSIS": {
                "name": "Phân tích nhân vật tự động",
                "category": "Tự động đưa nhân vật vào",
                "description": "Phân tích dàn ý mới tạo, đánh giá có cần đưa nhân vật mới vào hay không",
                "parameters": ["title", "genre", "theme", "time_period", "location", "atmosphere",
                             "existing_characters", "new_outlines", "start_chapter", "end_chapter"]
            },
            "AUTO_CHARACTER_GENERATION": {
                "name": "Tạo nhân vật tự động",
                "category": "Tự động đưa nhân vật vào",
                "description": "Tự động tạo thiết lập đầy đủ cho nhân vật mới theo nhu cầu tình tiết",
                "parameters": ["title", "genre", "theme", "time_period", "location", "atmosphere", "rules",
                             "existing_characters", "plot_context", "character_specification", "mcp_references"]
            },
            "AUTO_ORGANIZATION_ANALYSIS": {
                "name": "Phân tích tổ chức tự động",
                "category": "Tự động đưa tổ chức vào",
                "description": "Phân tích dàn ý mới tạo, đánh giá có cần đưa tổ chức mới vào hay không",
                "parameters": ["title", "genre", "theme", "time_period", "location", "atmosphere",
                             "existing_organizations", "existing_characters", "all_chapters_brief", "start_chapter", "chapter_count", "plot_stage", "story_direction"]
            },
            "AUTO_ORGANIZATION_GENERATION": {
                "name": "Tạo tổ chức tự động",
                "category": "Tự động đưa tổ chức vào",
                "description": "Tự động tạo thiết lập đầy đủ cho tổ chức mới theo nhu cầu tình tiết",
                "parameters": ["title", "genre", "theme", "time_period", "location", "atmosphere", "rules",
                             "existing_organizations", "existing_characters", "plot_context", "organization_specification", "mcp_references"]
            },
            "CAREER_SYSTEM_GENERATION": {
                "name": "Tạo hệ thống nghề nghiệp",
                "category": "Bối cảnh thế giới",
                "description": "Tự động tạo hệ thống nghề nghiệp hoàn chỉnh dựa trên bối cảnh thế giới và phần giới thiệu dự án, gồm nghề chính và nghề phụ",
                "parameters": ["title", "genre", "theme", "description", "time_period", "location", "atmosphere", "rules"]
            },
            "INSPIRATION_TITLE_SYSTEM": {
                "name": "Chế độ cảm hứng - Tạo tên sách (prompt hệ thống)",
                "category": "Chế độ cảm hứng",
                "description": "Prompt hệ thống tạo 6 gợi ý tên sách dựa trên ý tưởng gốc của người dùng",
                "parameters": ["initial_idea"]
            },
            "INSPIRATION_TITLE_USER": {
                "name": "Chế độ cảm hứng - Tạo tên sách (prompt người dùng)",
                "category": "Chế độ cảm hứng",
                "description": "Prompt người dùng tạo 6 gợi ý tên sách dựa trên ý tưởng gốc của người dùng",
                "parameters": ["initial_idea"]
            },
            "INSPIRATION_DESCRIPTION_SYSTEM": {
                "name": "Chế độ cảm hứng - Tạo giới thiệu (prompt hệ thống)",
                "category": "Chế độ cảm hứng",
                "description": "Prompt hệ thống tạo 6 lựa chọn giới thiệu dựa trên ý tưởng người dùng và tên sách",
                "parameters": ["initial_idea", "title"]
            },
            "INSPIRATION_DESCRIPTION_USER": {
                "name": "Chế độ cảm hứng - Tạo giới thiệu (prompt người dùng)",
                "category": "Chế độ cảm hứng",
                "description": "Prompt người dùng tạo 6 lựa chọn giới thiệu dựa trên ý tưởng người dùng và tên sách",
                "parameters": ["initial_idea", "title"]
            },
            "INSPIRATION_THEME_SYSTEM": {
                "name": "Chế độ cảm hứng - Tạo chủ đề (prompt hệ thống)",
                "category": "Chế độ cảm hứng",
                "description": "Prompt hệ thống tạo 6 lựa chọn chủ đề sâu sắc dựa trên tên sách và phần giới thiệu",
                "parameters": ["initial_idea", "title", "description"]
            },
            "INSPIRATION_THEME_USER": {
                "name": "Chế độ cảm hứng - Tạo chủ đề (prompt người dùng)",
                "category": "Chế độ cảm hứng",
                "description": "Prompt người dùng tạo 6 lựa chọn chủ đề sâu sắc dựa trên tên sách và phần giới thiệu",
                "parameters": ["initial_idea", "title", "description"]
            },
            "INSPIRATION_GENRE_SYSTEM": {
                "name": "Chế độ cảm hứng - Tạo thể loại (prompt hệ thống)",
                "category": "Chế độ cảm hứng",
                "description": "Prompt hệ thống tạo 6 nhãn thể loại phù hợp dựa trên thông tin tiểu thuyết",
                "parameters": ["initial_idea", "title", "description", "theme"]
            },
            "INSPIRATION_GENRE_USER": {
                "name": "Chế độ cảm hứng - Tạo thể loại (prompt người dùng)",
                "category": "Chế độ cảm hứng",
                "description": "Prompt người dùng tạo 6 nhãn thể loại phù hợp dựa trên thông tin tiểu thuyết",
                "parameters": ["initial_idea", "title", "description", "theme"]
            },
            "INSPIRATION_QUICK_COMPLETE": {
                "name": "Chế độ cảm hứng - Bổ sung thông minh",
                "category": "Chế độ cảm hứng",
                "description": "Bổ sung thông minh phương án tiểu thuyết hoàn chỉnh dựa trên thông tin một phần do người dùng cung cấp",
                "parameters": ["existing"]
            }
        }
        
        for key, info in template_definitions.items():
            template_content = getattr(cls, key, None)
            if template_content:
                templates.append({
                    "template_key": key,
                    "template_name": info["name"],
                    "category": info["category"],
                    "description": info["description"],
                    "parameters": info["parameters"],
                    "content": template_content
                })
        
        # 加载 Skill 提示词模板
        try:
            skill_templates = get_all_skills_cached()
            templates.extend(skill_templates)
        except Exception as e:
            from app.logger import get_logger
            get_logger(__name__).warning(f"Tải mẫu Skill thất bại: {e}")
        
        return templates
    
    @classmethod
    def get_system_template_info(cls, template_key: str) -> dict:
        """
        获取指定系统模板的信息
        
        Args:
            template_key: khóa mẫu
            
        Returns:
            模板信息字典
        """
        all_templates = cls.get_all_system_templates()
        for template in all_templates:
            if template["template_key"] == template_key:
                return template
        return None

# ========== 全局实例 ==========
prompt_service = PromptService()
