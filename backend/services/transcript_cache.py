# backend/services/transcript_cache.py

from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional, TypedDict
import time
import uuid


class TranscriptItem(TypedDict, total=False):
    id: str
    speaker: str          # "interviewer" or "candidate"
    text: str
    start_sec: float
    end_sec: float
    created_at: float


# 유저별로 최근 N턴까지만 메모리에 유지
_MAX_TURNS = 300
_store: Dict[str, Deque[TranscriptItem]] = defaultdict(
    lambda: deque(maxlen=_MAX_TURNS)
)


def add_turn(
    user_id: str,
    speaker: str,
    text: str,
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
) -> TranscriptItem:
    """
    user_id별로 한 턴 추가.
    - speaker: "interviewer" | "candidate"
    - text: STT로 나온 한 문장/구간
    - start_sec / end_sec: 필요하면 나중에 채우는 용도
    """
    now = time.time()
    item: TranscriptItem = {
        "id": str(uuid.uuid4()),
        "speaker": speaker,
        "text": text,
        "created_at": now,
    }
    if start_sec is not None:
        item["start_sec"] = float(start_sec)
    if end_sec is not None:
        item["end_sec"] = float(end_sec)

    _store[user_id].append(item)
    return item


def get_transcript(user_id: str, since_id: Optional[str] = None) -> List[TranscriptItem]:
    """
    - since_id 없으면 해당 user_id의 전체 로그 반환
    - since_id 있으면, 그 id 이후의 것만 반환 (증분 업데이트용)
    """
    items = list(_store.get(user_id, []))
    if not since_id:
        return items

    result: List[TranscriptItem] = []
    found = False
    for it in items:
        if found:
            result.append(it)
        elif it["id"] == since_id:
            found = True
    return result