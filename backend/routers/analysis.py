# backend/routers/analysis.py

from fastapi import APIRouter, HTTPException

from backend.services.analysis_cache import get_latest

router = APIRouter(
    prefix="/analysis",
    tags=["analysis"],
)


@router.get("/{user_id}/latest")
def get_latest_analysis(user_id: str):
    """
    특정 user_id의 최신 말속도 분석 결과를 반환.
    - speech_rate_worker -> MQTT -> analysis_listener -> analysis_cache
    - 그 결과를 여기서 조회
    """
    data = get_latest(user_id)
    if not data:
        raise HTTPException(status_code=404, detail="No analysis yet for this user_id")
    return data