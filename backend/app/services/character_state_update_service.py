"""角色状态更新服务 - 根据章节分析结果自动更新角色心理状态、关系和组织成员"""
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, or_, and_
from app.models.character import Character
from app.models.relationship import CharacterRelationship, Organization, OrganizationMember
from app.logger import get_logger
import uuid

logger = get_logger(__name__)

# 亲密度调整关键词映射
INTIMACY_ADJUSTMENTS = {
    # 正向变化
    "cải thiện": +10, "sâu sắc hơn": +15, "tin tưởng": +10, "thân thiết": +15,
    "thân thiện": +10, "công nhận": +10, "hợp tác": +5, "hòa giải": +20,
    "thích": +15, "yêu": +20, "tôn trọng": +10, "biết ơn": +10,
    "khởi sắc": +10, "thắt chặt": +10, "thân mật": +15, "trung thành": +10,
    # 负向变化
    "xấu đi": -10, "xa cách": -15, "phản bội": -30, "thù địch": -25,
    "mâu thuẫn": -10, "xung đột": -15, "nghi ngờ": -10, "không tin tưởng": -15,
    "ghét": -20, "oán hận": -25, "đoạn tuyệt": -30, "ngờ vực": -10,
    "căng thẳng": -5, "tan vỡ": -25, "trở mặt": -25, "ghen tị": -10,
    # 特殊变化
    "mới quen": 0, "gặp gỡ": 0, "liên minh": +10, "chia cách": -5,
}


class CharacterStateUpdateService:
    """角色状态更新服务 - 根据章节分析结果自动更新角色心理状态和关系"""

    @staticmethod
    async def update_from_analysis(
        db: AsyncSession,
        project_id: str,
        character_states: List[Dict[str, Any]],
        chapter_id: str,
        chapter_number: int
    ) -> Dict[str, Any]:
        """
        根据章节分析结果更新角色状态和关系
        
        Args:
            db: 数据库会话
            project_id: 项目ID
            character_states: 角色状态变化列表（来自PlotAnalysis）
            chapter_id: 章节ID
            chapter_number: 章节编号
            
        Returns:
            更新结果字典
        """
        if not character_states:
            logger.info("📋 角色状态列表为空，跳过状态和关系更新")
            return {
                "state_updated_count": 0,
                "relationship_created_count": 0,
                "relationship_updated_count": 0,
                "org_updated_count": 0,
                "changes": []
            }

        result = {
            "state_updated_count": 0,
            "relationship_created_count": 0,
            "relationship_updated_count": 0,
            "org_updated_count": 0,
            "changes": []
        }

        logger.info(f"🔍 开始分析第{chapter_number}章的角色状态、关系和组织变化...")

        # 预加载项目所有角色（含组织，按名称索引，减少重复查询）
        all_characters_result = await db.execute(
            select(Character).where(Character.project_id == project_id)
        )
        all_characters = all_characters_result.scalars().all()
        
        # 非组织角色按名称索引
        characters_by_name: Dict[str, Character] = {
            c.name: c for c in all_characters if not c.is_organization
        }
        
        # 预加载组织信息（按组织角色名称索引）
        orgs_result = await db.execute(
            select(Organization).where(Organization.project_id == project_id)
        )
        all_orgs = orgs_result.scalars().all()
        
        # 构建 character_id -> name 的反向映射
        char_id_to_name: Dict[str, str] = {c.id: c.name for c in all_characters}
        
        # 组织名称 -> Organization 映射
        org_by_name: Dict[str, Organization] = {}
        for org in all_orgs:
            org_char_name = char_id_to_name.get(org.character_id)
            if org_char_name:
                org_by_name[org_char_name] = org

        for char_state in character_states:
            char_name = char_state.get('character_name')
            if not char_name:
                continue

            character = characters_by_name.get(char_name)
            if not character:
                logger.warning(f"  ⚠️ 角色不存在: {char_name}，跳过状态更新")
                continue

            # 0. 检查角色存活状态变化
            survival_status = char_state.get('survival_status')
            if survival_status and survival_status in ('deceased', 'missing', 'retired'):
                await CharacterStateUpdateService._update_survival_status(
                    db=db,
                    project_id=project_id,
                    character=character,
                    new_status=survival_status,
                    chapter_number=chapter_number,
                    key_event=char_state.get('key_event', ''),
                    changes=result["changes"]
                )
                result["state_updated_count"] += 1
                # 死亡/失踪后不再更新心理状态等，直接跳到下一个角色
                continue

            # 1. 更新心理状态
            state_updated = await CharacterStateUpdateService._update_psychological_state(
                character=character,
                char_state=char_state,
                chapter_number=chapter_number,
                changes=result["changes"]
            )
            if state_updated:
                result["state_updated_count"] += 1

            # 2. 更新关系
            relationship_changes = char_state.get('relationship_changes', {})
            if relationship_changes and isinstance(relationship_changes, dict):
                created, updated = await CharacterStateUpdateService._update_relationships(
                    db=db,
                    project_id=project_id,
                    character=character,
                    relationship_changes=relationship_changes,
                    chapter_number=chapter_number,
                    chapter_id=chapter_id,
                    characters_by_name=characters_by_name,
                    changes=result["changes"]
                )
                result["relationship_created_count"] += created
                result["relationship_updated_count"] += updated

            # 3. 更新组织成员关系
            organization_changes = char_state.get('organization_changes', [])
            if organization_changes and isinstance(organization_changes, list):
                org_updated = await CharacterStateUpdateService._update_organization_memberships(
                    db=db,
                    project_id=project_id,
                    character=character,
                    organization_changes=organization_changes,
                    chapter_number=chapter_number,
                    org_by_name=org_by_name,
                    changes=result["changes"]
                )
                result["org_updated_count"] += org_updated

        # 提交所有更改
        total_changes = (
            result["state_updated_count"] +
            result["relationship_created_count"] +
            result["relationship_updated_count"] +
            result["org_updated_count"]
        )
        if total_changes > 0:
            await db.commit()
            logger.info(
                f"✅ 角色状态更新完成: "
                f"trạng thái tâm lý {result['state_updated_count']}, "
                f"quan hệ mới {result['relationship_created_count']}, "
                f"quan hệ cập nhật {result['relationship_updated_count']}, "
                f"thay đổi tổ chức {result['org_updated_count']}"
            )
        else:
            logger.info("📋 本章没有角色状态或关系变化")

        return result

    @staticmethod
    async def _update_survival_status(
        db: AsyncSession,
        project_id: str,
        character: Character,
        new_status: str,
        chapter_number: int,
        key_event: str,
        changes: List[str]
    ) -> None:
        """
        更新角色存活状态及级联影响
        
        死亡/失踪时：
        - 更新 Character.status 和 status_changed_chapter
        - 更新所有活跃关系状态为 past
        - 更新所有组织成员身份为 deceased/retired
        """
        STATUS_DESC = {
            'deceased': 'Đã chết',
            'missing': 'Mất tích',
            'retired': 'Rời sân khấu'
        }
        
        status_desc = STATUS_DESC.get(new_status, new_status)
        
        # 防止低章节覆盖
        if (character.status_changed_chapter is not None
                and chapter_number < character.status_changed_chapter):
            logger.info(f"  ⏭️ {character.name} 状态已在第{character.status_changed_chapter}章变更，跳过")
            return
        
        old_status = character.status or 'active'
        character.status = new_status
        character.status_changed_chapter = chapter_number
        character.current_state = f"{status_desc} (chương {chapter_number})"
        character.state_updated_chapter = chapter_number
        
        event_desc = f": {key_event[:50]}" if key_event else ""
        changes.append(f"💀 {character.name} {status_desc}{event_desc}")
        logger.info(f"  💀 {character.name} 状态: {old_status} → {new_status}")
        
        # 级联更新：所有活跃关系变为 past
        rels_result = await db.execute(
            select(CharacterRelationship).where(
                and_(
                    CharacterRelationship.project_id == project_id,
                    CharacterRelationship.status == 'active',
                    or_(
                        CharacterRelationship.character_from_id == character.id,
                        CharacterRelationship.character_to_id == character.id
                    )
                )
            )
        )
        active_rels = rels_result.scalars().all()
        for rel in active_rels:
            rel.status = 'past'
            rel.ended_at = f"Chương {chapter_number}"
        if active_rels:
            logger.info(f"  📋 {character.name} {status_desc}，{len(active_rels)}条关系标记为past")
        
        # 级联更新：所有组织成员身份
        member_status = 'deceased' if new_status == 'deceased' else 'retired'
        members_result = await db.execute(
            select(OrganizationMember).where(
                and_(
                    OrganizationMember.character_id == character.id,
                    OrganizationMember.status == 'active'
                )
            )
        )
        active_members = members_result.scalars().all()
        for member in active_members:
            member.status = member_status
            member.left_at = f"Chương {chapter_number}"
            member.notes = (
                f"{member.notes or ''}\n[Chương {chapter_number}] Nhân vật {status_desc}"
            ).strip()
        if active_members:
            logger.info(f"  📋 {character.name} {status_desc}，{len(active_members)}个组织身份标记为{member_status}")

    @staticmethod
    async def _update_psychological_state(
        character: Character,
        char_state: Dict[str, Any],
        chapter_number: int,
        changes: List[str]
    ) -> bool:
        """
        更新角色心理状态
        
        Args:
            character: 角色对象
            char_state: 角色状态数据
            chapter_number: 章节号
            changes: 变更日志列表
            
        Returns:
            是否有实际更新
        """
        state_after = char_state.get('state_after')
        if not state_after:
            return False

        # 章节号校验：防止低章节分析覆盖高章节状态
        if (character.state_updated_chapter is not None
                and chapter_number < character.state_updated_chapter):
            logger.info(
                f"  ⏭️ {character.name} 的心理状态已被第{character.state_updated_chapter}章更新，"
                f"bỏ qua cập nhật cho chương {chapter_number}"
            )
            return False

        old_state = character.current_state
        character.current_state = state_after
        character.state_updated_chapter = chapter_number

        state_before = char_state.get('state_before', 'Chưa rõ')
        psychological_change = char_state.get('psychological_change', '')

        change_desc = f"👤 {character.name} Trạng thái tâm lý: {state_before} → {state_after}"
        if psychological_change:
            change_desc += f" ({psychological_change[:50]})"
        changes.append(change_desc)

        logger.info(f"  ✅ {character.name} 心理状态更新: {state_before} → {state_after}")
        return True

    @staticmethod
    async def _update_relationships(
        db: AsyncSession,
        project_id: str,
        character: Character,
        relationship_changes: Dict[str, Any],
        chapter_number: int,
        chapter_id: str,
        characters_by_name: Dict[str, Character],
        changes: List[str]
    ) -> tuple[int, int]:
        """
        更新角色关系
        
        关系名称直接使用AI分析返回的变化描述，不强制映射到预定义类型。
        relationship_type_id 仅在能明确匹配时作为辅助设置。
        
        Args:
            db: 数据库会话
            project_id: 项目ID
            character: 角色A
            relationship_changes: 关系变化字典 {"角色名": "变化描述" 或 {"change": ..., ...}}
            chapter_number: 章节号
            chapter_id: 章节ID
            characters_by_name: 角色名到角色对象的映射
            changes: 变更日志列表
            
        Returns:
            (新建数量, 更新数量)
        """
        created_count = 0
        updated_count = 0

        for target_name, change_info in relationship_changes.items():
            try:
                # 解析变化信息（支持两种格式）
                if isinstance(change_info, str):
                    change_desc = change_info
                elif isinstance(change_info, dict):
                    change_desc = change_info.get('change', str(change_info))
                else:
                    change_desc = str(change_info)

                if not change_desc:
                    continue

                # 查找目标角色
                target_character = characters_by_name.get(target_name)
                if not target_character:
                    logger.warning(f"  ⚠️ 关系目标角色不存在: {target_name}，跳过")
                    continue

                # 避免自身关系
                if character.id == target_character.id:
                    continue

                # 查询是否已存在关系（A→B 或 B→A）
                existing_rel_result = await db.execute(
                    select(CharacterRelationship).where(
                        and_(
                            CharacterRelationship.project_id == project_id,
                            or_(
                                and_(
                                    CharacterRelationship.character_from_id == character.id,
                                    CharacterRelationship.character_to_id == target_character.id
                                ),
                                and_(
                                    CharacterRelationship.character_from_id == target_character.id,
                                    CharacterRelationship.character_to_id == character.id
                                )
                            )
                        )
                    )
                )
                existing_rel = existing_rel_result.scalar_one_or_none()

                # 计算亲密度调整
                intimacy_delta = CharacterStateUpdateService._calculate_intimacy_delta(change_desc)

                if existing_rel:
                    # 更新已有关系
                    # 更新关系名称为最新的变化描述（以AI分析结果为准）
                    existing_rel.relationship_name = change_desc
                    
                    # 追加变更记录到描述
                    chapter_note = f"[Chương {chapter_number}] {change_desc}"
                    if existing_rel.description:
                        existing_rel.description = f"{existing_rel.description}\n{chapter_note}"
                    else:
                        existing_rel.description = chapter_note

                    # 调整亲密度
                    if intimacy_delta != 0:
                        old_intimacy = existing_rel.intimacy_level or 0
                        new_intimacy = max(-100, min(100, old_intimacy + intimacy_delta))
                        existing_rel.intimacy_level = new_intimacy
                        logger.info(
                            f"  📊 {character.name}↔{target_name} 亲密度: "
                            f"{old_intimacy} → {new_intimacy} ({'+' if intimacy_delta > 0 else ''}{intimacy_delta})"
                        )

                    updated_count += 1
                    changes.append(
                        f"🔄 {character.name}↔{target_name} cập nhật quan hệ: {change_desc}"
                    )
                    logger.info(f"  ✅ 更新关系: {character.name}↔{target_name} - {change_desc}")

                else:
                    # 创建新关系 — 关系名称直接使用AI的变化描述
                    # 设定初始亲密度
                    initial_intimacy = max(-100, min(100, 50 + intimacy_delta))

                    new_relationship = CharacterRelationship(
                        id=str(uuid.uuid4()),
                        project_id=project_id,
                        character_from_id=character.id,
                        character_to_id=target_character.id,
                        relationship_type_id=None,  # 不强制关联预定义类型
                        relationship_name=change_desc,  # 直接使用AI分析返回的描述
                        intimacy_level=initial_intimacy,
                        status="active",
                        description=f"[Chương {chapter_number}] {change_desc}",
                        source="analysis"
                    )
                    db.add(new_relationship)

                    created_count += 1
                    changes.append(
                        f"✨ {character.name}→{target_name} quan hệ mới: {change_desc}"
                    )
                    logger.info(
                        f"  ✅ 创建关系: {character.name}→{target_name} "
                        f"({change_desc}, độ thân thiết: {initial_intimacy})"
                    )

            except Exception as item_error:
                logger.error(
                    f"  ❌ 更新 {character.name}→{target_name} 关系失败: {str(item_error)}"
                )

        return created_count, updated_count

    @staticmethod
    async def _update_organization_memberships(
        db: AsyncSession,
        project_id: str,
        character: Character,
        organization_changes: List[Dict[str, Any]],
        chapter_number: int,
        org_by_name: Dict[str, Organization],
        changes: List[str]
    ) -> int:
        """
        更新角色的组织成员关系
        
        Args:
            db: 数据库会话
            project_id: 项目ID
            character: 角色对象
            organization_changes: 组织变动列表
            chapter_number: 章节号
            org_by_name: 组织名称到Organization对象的映射
            changes: 变更日志列表
            
        Returns:
            更新数量
        """
        updated_count = 0
        
        # 忠诚度变化关键词映射
        LOYALTY_ADJUSTMENTS = {
            "tăng": +10, "củng cố": +10, "kiên định": +15, "trung thành": +15,
            "dao động": -15, "nghi ngờ": -10, "bất mãn": -10, "giảm": -10,
            "phản bội": -50, "làm phản": -50, "ác cảm": -20, "thất vọng": -15,
        }
        
        for org_change in organization_changes:
            try:
                org_name = org_change.get('organization_name')
                change_type = org_change.get('change_type', '')
                new_position = org_change.get('new_position')
                loyalty_change_desc = org_change.get('loyalty_change', '')
                description = org_change.get('description', '')
                
                if not org_name:
                    continue
                
                # 查找组织
                organization = org_by_name.get(org_name)
                if not organization:
                    logger.warning(f"  ⚠️ 组织不存在: {org_name}，跳过组织变动更新")
                    continue
                
                # 查找已有成员关系
                existing_member_result = await db.execute(
                    select(OrganizationMember).where(
                        and_(
                            OrganizationMember.organization_id == organization.id,
                            OrganizationMember.character_id == character.id
                        )
                    )
                )
                existing_member = existing_member_result.scalar_one_or_none()
                
                # 计算忠诚度变化
                loyalty_delta = 0
                if loyalty_change_desc:
                    for keyword, adjustment in LOYALTY_ADJUSTMENTS.items():
                        if keyword in loyalty_change_desc:
                            loyalty_delta += adjustment
                    loyalty_delta = max(-50, min(50, loyalty_delta))
                
                if change_type == 'joined':
                    # 加入组织
                    if existing_member:
                        # 已存在，可能是重新加入
                        if existing_member.status != 'active':
                            existing_member.status = 'active'
                            existing_member.left_at = None
                            if new_position:
                                existing_member.position = new_position
                            existing_member.notes = (
                                f"{existing_member.notes or ''}\n[Chương {chapter_number}] Tham gia lại: {description}"
                            ).strip()
                            updated_count += 1
                            changes.append(f"🏛️ {character.name} tham gia lại {org_name}")
                            logger.info(f"  ✅ {character.name} 重新加入 {org_name}")
                    else:
                        # 创建新成员关系
                        new_member = OrganizationMember(
                            id=str(uuid.uuid4()),
                            organization_id=organization.id,
                            character_id=character.id,
                            position=new_position or 'Thành viên',
                            rank=0,
                            loyalty=max(0, min(100, 50 + loyalty_delta)),
                            status='active',
                            joined_at=f"Chương {chapter_number}",
                            source='analysis',
                            notes=f"[Chương {chapter_number}] {description}" if description else None
                        )
                        db.add(new_member)
                        organization.member_count = (organization.member_count or 0) + 1
                        updated_count += 1
                        changes.append(f"🏛️ {character.name} tham gia {org_name}({new_position or 'Thành viên'})")
                        logger.info(f"  ✅ {character.name} 加入 {org_name} 为 {new_position or 'Thành viên'}")
                
                elif change_type in ('left', 'expelled', 'betrayed'):
                    # 离开/被开除/叛变
                    if existing_member and existing_member.status == 'active':
                        status_map = {
                            'left': 'retired',
                            'expelled': 'expelled',
                            'betrayed': 'expelled'
                        }
                        existing_member.status = status_map.get(change_type, 'retired')
                        existing_member.left_at = f"Chương {chapter_number}"
                        if loyalty_delta != 0:
                            existing_member.loyalty = max(0, min(100, (existing_member.loyalty or 50) + loyalty_delta))
                        existing_member.notes = (
                            f"{existing_member.notes or ''}\n[Chương {chapter_number}] {change_type}: {description}"
                        ).strip()
                        updated_count += 1
                        type_desc = {'left': 'Rời đi', 'expelled': 'Bị khai trừ', 'betrayed': 'Làm phản'}
                        changes.append(f"🏛️ {character.name} {type_desc.get(change_type, change_type)} {org_name}")
                        logger.info(f"  ✅ {character.name} {type_desc.get(change_type, change_type)} {org_name}")
                
                elif change_type == 'promoted':
                    # 晋升
                    if existing_member:
                        old_position = existing_member.position
                        if new_position:
                            existing_member.position = new_position
                        existing_member.rank = (existing_member.rank or 0) + 1
                        if loyalty_delta != 0:
                            existing_member.loyalty = max(0, min(100, (existing_member.loyalty or 50) + loyalty_delta))
                        elif loyalty_delta == 0:
                            # 晋升默认提升忠诚度
                            existing_member.loyalty = max(0, min(100, (existing_member.loyalty or 50) + 5))
                        existing_member.notes = (
                            f"{existing_member.notes or ''}\n[Chương {chapter_number}] Thăng chức: {old_position} → {new_position or 'Vị trí cao hơn'}: {description}"
                        ).strip()
                        updated_count += 1
                        changes.append(f"🏛️ {character.name} thăng chức tại {org_name}: {old_position} → {new_position or 'Vị trí cao hơn'}")
                        logger.info(f"  ✅ {character.name} 在 {org_name} 晋升为 {new_position or '更高职位'}")
                    else:
                        logger.warning(f"  ⚠️ {character.name} 不是 {org_name} 的成员，无法晋升")
                
                elif change_type == 'demoted':
                    # 降级
                    if existing_member:
                        old_position = existing_member.position
                        if new_position:
                            existing_member.position = new_position
                        existing_member.rank = max(0, (existing_member.rank or 0) - 1)
                        if loyalty_delta != 0:
                            existing_member.loyalty = max(0, min(100, (existing_member.loyalty or 50) + loyalty_delta))
                        elif loyalty_delta == 0:
                            # 降级默认降低忠诚度
                            existing_member.loyalty = max(0, min(100, (existing_member.loyalty or 50) - 5))
                        existing_member.notes = (
                            f"{existing_member.notes or ''}\n[Chương {chapter_number}] Giáng chức: {old_position} → {new_position or 'Vị trí thấp hơn'}: {description}"
                        ).strip()
                        updated_count += 1
                        changes.append(f"🏛️ {character.name} giáng chức tại {org_name}: {old_position} → {new_position or 'Vị trí thấp hơn'}")
                        logger.info(f"  ✅ {character.name} 在 {org_name} 降级为 {new_position or '更低职位'}")
                    else:
                        logger.warning(f"  ⚠️ {character.name} 不是 {org_name} 的成员，无法降级")
                
                else:
                    # 其他类型的变化（如忠诚度变化等）
                    if existing_member and loyalty_delta != 0:
                        old_loyalty = existing_member.loyalty or 50
                        existing_member.loyalty = max(0, min(100, old_loyalty + loyalty_delta))
                        existing_member.notes = (
                            f"{existing_member.notes or ''}\n[Chương {chapter_number}] {change_type}: {description}"
                        ).strip()
                        updated_count += 1
                        changes.append(
                            f"🏛️ {character.name} thay đổi mức trung thành tại {org_name}: "
                            f"{old_loyalty} → {existing_member.loyalty}"
                        )
                        logger.info(
                            f"  ✅ {character.name} 在 {org_name} 忠诚度: "
                            f"{old_loyalty} → {existing_member.loyalty}"
                        )
                    
            except Exception as item_error:
                logger.error(
                    f"  ❌ 更新 {character.name} 的组织 {org_change.get('organization_name', '未知')} 变动失败: {str(item_error)}"
                )
        
        return updated_count

    @staticmethod
    async def update_organization_states(
        db: AsyncSession,
        project_id: str,
        organization_states: List[Dict[str, Any]],
        chapter_number: int
    ) -> Dict[str, Any]:
        """
        根据章节分析结果更新组织自身状态（势力等级、据点、宗旨等）
        
        Args:
            db: 数据库会话
            project_id: 项目ID
            organization_states: 组织状态变化列表（来自分析结果顶级字段）
            chapter_number: 章节编号
            
        Returns:
            更新结果字典
        """
        if not organization_states:
            return {"updated_count": 0, "changes": []}
        
        result = {"updated_count": 0, "changes": []}
        
        logger.info(f"🏛️ 开始更新第{chapter_number}章的组织自身状态...")
        
        # 预加载项目所有组织角色
        all_chars_result = await db.execute(
            select(Character).where(
                Character.project_id == project_id,
                Character.is_organization == True
            )
        )
        org_chars = all_chars_result.scalars().all()
        org_char_by_name: Dict[str, Character] = {c.name: c for c in org_chars}
        
        # 预加载组织详情
        char_ids = [c.id for c in org_chars]
        if not char_ids:
            logger.info("🏛️ 项目中无组织，跳过组织状态更新")
            return result
        
        orgs_result = await db.execute(
            select(Organization).where(Organization.character_id.in_(char_ids))
        )
        all_orgs = orgs_result.scalars().all()
        org_by_char_id: Dict[str, Organization] = {org.character_id: org for org in all_orgs}
        
        for org_state in organization_states:
            try:
                org_name = org_state.get('organization_name')
                if not org_name:
                    continue
                
                org_char = org_char_by_name.get(org_name)
                if not org_char:
                    logger.warning(f"  ⚠️ 组织不存在: {org_name}，跳过状态更新")
                    continue
                
                organization = org_by_char_id.get(org_char.id)
                if not organization:
                    logger.warning(f"  ⚠️ 组织 {org_name} 无详情记录，跳过状态更新")
                    continue
                
                updated = False
                change_parts = []
                
                # 检查组织是否被覆灭
                is_destroyed = org_state.get('is_destroyed', False)
                if is_destroyed:
                    # 组织覆灭：级联处理
                    org_char.status = 'destroyed'
                    org_char.status_changed_chapter = chapter_number
                    org_char.current_state = f"Bị tiêu diệt (chương {chapter_number})"
                    org_char.state_updated_chapter = chapter_number
                    organization.power_level = 0
                    
                    # 所有活跃成员标记为retired
                    members_result = await db.execute(
                        select(OrganizationMember).where(
                            and_(
                                OrganizationMember.organization_id == organization.id,
                                OrganizationMember.status == 'active'
                            )
                        )
                    )
                    active_members = members_result.scalars().all()
                    for member in active_members:
                        member.status = 'retired'
                        member.left_at = f"Chương {chapter_number}"
                        member.notes = (
                            f"{member.notes or ''}\n[Chương {chapter_number}] Tổ chức bị tiêu diệt"
                        ).strip()
                    
                    key_event = org_state.get('key_event', '')
                    event_desc = f": {key_event[:40]}" if key_event else ""
                    result["updated_count"] += 1
                    change_summary = f"💀 {org_name} bị tiêu diệt{event_desc}, ảnh hưởng đến {len(active_members)} thành viên"
                    result["changes"].append(change_summary)
                    logger.info(f"  💀 {change_summary}")
                    continue  # 覆灭后不再更新其他属性
                
                # 势力等级变化
                power_change = org_state.get('power_change', 0)
                if power_change and isinstance(power_change, (int, float)):
                    old_power = organization.power_level or 50
                    new_power = max(0, min(100, old_power + int(power_change)))
                    if new_power != old_power:
                        organization.power_level = new_power
                        change_parts.append(f"Thế lực: {old_power}→{new_power}")
                        updated = True
                
                # 据点变化
                new_location = org_state.get('new_location')
                if new_location and isinstance(new_location, str):
                    old_location = organization.location or 'Chưa thiết lập'
                    organization.location = new_location
                    change_parts.append(f"Cứ điểm: {old_location}→{new_location}")
                    updated = True
                
                # 宗旨/目标变化
                new_purpose = org_state.get('new_purpose')
                if new_purpose and isinstance(new_purpose, str):
                    old_purpose = (org_char.organization_purpose or 'Chưa thiết lập')[:30]
                    org_char.organization_purpose = new_purpose
                    change_parts.append("Đã thay đổi tôn chỉ")
                    updated = True
                
                # 状态描述 -> 更新到 Character 的 current_state
                status_desc = org_state.get('status_description')
                if status_desc and isinstance(status_desc, str):
                    org_char.current_state = status_desc
                    org_char.state_updated_chapter = chapter_number
                    if not change_parts:  # 如果只有状态描述没有其他变化
                        change_parts.append(f"Trạng thái: {status_desc[:30]}")
                    updated = True
                
                if updated:
                    result["updated_count"] += 1
                    key_event = org_state.get('key_event', '')
                    change_summary = f"🏛️ Trạng thái của {org_name} thay đổi: {', '.join(change_parts)}"
                    if key_event:
                        change_summary += f" (do: {key_event[:40]})"
                    result["changes"].append(change_summary)
                    logger.info(f"  ✅ {change_summary}")
                    
            except Exception as item_error:
                logger.error(
                    f"  ❌ 更新组织 {org_state.get('organization_name', '未知')} 状态失败: {str(item_error)}"
                )
        
        if result["updated_count"] > 0:
            await db.commit()
            logger.info(f"✅ 组织状态更新完成: {result['updated_count']}个组织")
        
        return result

    @staticmethod
    def _calculate_intimacy_delta(change_desc: str) -> int:
        """
        根据变化描述计算亲密度调整值
        
        Args:
            change_desc: 关系变化描述文本
            
        Returns:
            亲密度调整值
        """
        delta = 0
        matched = False
        for keyword, adjustment in INTIMACY_ADJUSTMENTS.items():
            if keyword in change_desc:
                delta += adjustment
                matched = True

        # 限制单次调整幅度
        if matched:
            delta = max(-30, min(30, delta))

        return delta
