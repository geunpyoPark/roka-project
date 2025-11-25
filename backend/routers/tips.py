# backend/routers/tips.py

from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.tip_generator import generate_interview_tip


router = APIRouter(
    prefix="/tips",
    tags=["tips"],
)


class TipRequest(BaseModel):
    """프론트에서 보내 줄 요청 바디 형식"""

    question: str = Field(..., description="면접관 질문")
    answer_text: str = Field(
        ...,
        description="지원자의 최근 답변 전체 텍스트 (STT 결과)",
    )
    wpm: Optional[float] = Field(
        None,
        description="말하기 속도 (words per minute)",
    )
    speed_label: Optional[str] = Field(
        None,
        description='속도 라벨 (예: "너무 빠름", "적당함", "조금 느림")',
    )


class TipResponse(BaseModel):
    """프론트로 돌려줄 응답 형식"""

    summary: str
    bullets: List[str]
    speed_comment: Optional[str] = None


@router.post("/{user_id}", response_model=TipResponse)
async def create_tip(user_id: str, body: TipRequest) -> TipResponse:
    """
    특정 user_id의 최근 답변에 대한 면접 팁 생성.
    실제로는 user_id로 세션을 구분해서 로그를 쌓아도 되고,
    지금은 단순히 Gemini에 프롬프트를 날리는 형태.
    """
    try:
        data = await generate_interview_tip(
            question=body.question,
            answer_text=body.answer_text,
            wpm=body.wpm,
            speed_label=body.speed_label,
        )
    except Exception as e:
        # 로그 찍고 에러 반환
        raise HTTPException(status_code=500, detail=f"Tip generation failed: {e}")

    return TipResponse(
        summary=data.get("summary", ""),
        bullets=data.get("bullets", []),
        speed_comment=data.get("speed_comment"),
    )