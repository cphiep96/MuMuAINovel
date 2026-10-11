"""Story beats and editable shot contracts; no paid model calls during preview."""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict
from typing import Any

from fastapi import HTTPException

from app.services.video_export.storyboard import (
    SourceChapter, StoryboardOptions, StoryboardScene, estimate_duration, normalize_text,
)

FIELDS = ('startState','endState','location','timeOfDay','lighting','action','camera','transition','characters')
TIME_CHANGE = re.compile(r'^(?:Đêm (?:đầu tiên|hôm ấy|hôm đó)|Sáng (?:hôm sau|hôm ấy)|Ngày hôm sau|Tối hôm đó|Một tuần sau|The next (?:morning|day)|That night)\b', re.I)


def story_beats(content: str, max_chars: int) -> list[str]:
    """Keep paragraph boundaries and quoted dialogue intact, including closing quotes."""
    result=[]
    for paragraph in re.split(r'\n\s*\n', content or ''):
        text=normalize_text(paragraph)
        if not text:
            continue
        units=[]
        start=0
        quoted=False
        for index,char in enumerate(text):
            if char in '“「': quoted=True
            elif char in '”」': quoted=False
            elif char=='"': quoted=not quoted
            end=char in '.!?…。！？' and not quoted
            closes=char in '”」"' and not quoted and index>0 and text[index-1] in '.!?…'
            if end or closes:
                unit=text[start:index+1].strip()
                if unit:units.append(unit)
                start=index+1
        if text[start:].strip():units.append(text[start:].strip())
        buffer=''
        for unit in units:
            if buffer and (len(buffer)+len(unit)+1>max_chars or TIME_CHANGE.match(unit)):
                result.append(buffer);buffer=''
            buffer=f'{buffer} {unit}'.strip()
        if buffer:result.append(buffer)
    return result


def fingerprint(chapters: list[SourceChapter], options: StoryboardOptions) -> str:
    payload={'chapters':[asdict(c) for c in chapters], 'chars':options.narration_chars_per_scene}
    return hashlib.sha256(json.dumps(payload,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def validate_direction(raw: Any) -> dict:
    if not isinstance(raw,dict) or any(key not in FIELDS for key in raw):
        raise HTTPException(400,'Ràng buộc cảnh không hợp lệ')
    result={}
    for key,value in raw.items():
        if key=='characters':
            if not isinstance(value,list) or len(value)>10 or any(not isinstance(v,str) or not v.strip() or len(v)>500 for v in value):
                raise HTTPException(400,'Danh sách nhân vật cảnh không hợp lệ')
            if value:result[key]=[v.strip() for v in value]
        else:
            if not isinstance(value,str) or len(value)>1500:
                raise HTTPException(400,'Ràng buộc cảnh vượt giới hạn độ dài')
            if value.strip():result[key]=value.strip()
    return result


def build_continuity_storyboard(chapters: list[SourceChapter], options: StoryboardOptions,
                               *, reviewed_plan=None, reviewed_fingerprint=None):
    stamp=fingerprint(chapters,options)
    scenes=[]
    directions=[]
    for chapter in chapters:
        beats=story_beats(chapter.content,options.narration_chars_per_scene)
        previous=''
        moment='Giữ cùng thời điểm với cảnh trước; chưa xác định giờ cụ thể.'
        for index,beat in enumerate(beats):
            changes=bool(TIME_CHANGE.match(beat))
            if changes:
                moment=beat.split('.',1)[0][:250]
            direction={
                'startState':f'Tiếp tục đúng trạng thái cuối cảnh trước: {previous[-650:]}' if previous and not changes else 'Bắt đầu tại trạng thái được mô tả trong đoạn hiện tại.',
                'endState':'Chỉ hoàn thành hành động trong đoạn hiện tại; không diễn trước sự kiện cảnh sau.',
                'timeOfDay':moment,
                'lighting':'Giữ thời tiết, hướng sáng và độ sáng như cảnh trước; không tự đổi ngày/đêm.' if not changes else 'Chỉ đổi ánh sáng theo mốc thời gian mới được nêu rõ.',
                'action':beat[:1500],
                'camera':'Một cú máy liên tục, chuyển động chậm, không tự đổi địa điểm trong clip.',
                'transition':'Chuyển thời gian rõ ràng' if changes else 'Nối trực tiếp cùng diễn biến',
            }
            next_beat=beats[index+1] if index+1<len(beats) else ''
            prompt=(f'Cinematic adaptation of chapter {chapter.title}. ONE SHOT, not a montage.\n'
                    'Only show people actually present in the current passage. Do not bring in cast from other scenes.\n'
                    'Prose and reported speech describe visual action; do not read them aloud.\n'
                    f'CURRENT PASSAGE:\n{beat}\n'
                    f'PREVIOUS PASSAGE (context only; do not repeat its completed actions):\n{previous[-650:]}\n'
                    f'NEXT PASSAGE (context only; do not perform these events yet):\n{next_beat[:650]}')
            scenes.append(StoryboardScene(len(scenes),chapter.id,chapter.chapter_number,chapter.title,
                                           beat,estimate_duration(beat,options.chars_per_second),prompt))
            directions.append(direction)
            previous=beat
    if not scenes:raise HTTPException(400,'Không có nội dung để tạo storyboard')
    if reviewed_plan is not None:
        if reviewed_fingerprint!=stamp or len(reviewed_plan)!=len(scenes):
            raise HTTPException(409,'Nội dung hoặc cách chia cảnh đã thay đổi; hãy duyệt storyboard lại.')
        for index,item in enumerate(reviewed_plan):
            if not isinstance(item,dict) or item.get('scene_index')!=index:
                raise HTTPException(400,'Thứ tự storyboard không hợp lệ')
            directions[index]=validate_direction(item.get('direction'))
    return scenes,directions,stamp
