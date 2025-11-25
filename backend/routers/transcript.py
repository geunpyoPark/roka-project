# backend/routers/transcript.py

from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.services.transcript_cache import (
    add_turn,
    get_transcript,
)

router = APIRouter(
    prefix="/transcript",
    tags=["transcript"],
)


class TranscriptItemIn(BaseModel):
    """프론트에서 전송할 요청 바디 형식"""

    speaker: str = Field(..., description='"interviewer" or "candidate"')
    text: str = Field(..., description="한 턴의 텍스트")
    start_sec: Optional[float] = Field(
        None, description="세그먼트 시작 시간 (초 단위, 선택)"
    )
    end_sec: Optional[float] = Field(
        None, description="세그먼트 끝 시간 (초 단위, 선택)"
    )


class TranscriptItemOut(BaseModel):
    """프론트로 돌려줄 응답 형식"""

    id: str
    speaker: str
    text: str
    start_sec: Optional[float] = None
    end_sec: Optional[float] = None
    created_at: float


@router.post("/{user_id}", response_model=TranscriptItemOut)
def add_transcript_turn(user_id: str, body: TranscriptItemIn):
    """
    특정 user_id에 대해 한 턴 추가.
    - 지금은 마이크 워커(whisper_worker_daglo_mic.py)에서 호출
    - Postman / curl로 테스트도 가능
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Empty text not allowed")

    item = add_turn(
        user_id=user_id,
        speaker=body.speaker,
        text=body.text,
        start_sec=body.start_sec,
        end_sec=body.end_sec,
    )
    return item


@router.get("/{user_id}", response_model=List[TranscriptItemOut])
def get_transcript_api(
    user_id: str,
    since_id: Optional[str] = Query(
        default=None,
        description="마지막으로 받은 id 이후의 것만 가져오고 싶을 때 사용",
    ),
):
    """
    특정 user_id의 전체/새로운 대화 로그 목록.
    - since_id 없으면 전체
    - since_id 있으면 그 이후만
    """
    return get_transcript(user_id, since_id=since_id)