# backend/routers/analysis.py

from fastapi import APIRouter, HTTPException
from backend.services.analysis_cache import (
    get_latest_analysis,
    get_latest_text,
)

router = APIRouter(
    prefix="/analysis",
    tags=["analysis"],
)


@router.get("/{user_id}/latest")
def get_latest_analysis_api(user_id: str):
    """
    특정 user_id의 최신 말속도 분석 결과 반환.
    (speech_rate_worker → MQTT → analysis_listener → 메모리 캐시)
    """
    data = get_latest_analysis(user_id)
    if not data:
        raise HTTPException(status_code=404, detail="No analysis yet for this user_id")
    return data


@router.get("/{user_id}/latest-text")
def get_latest_text_api(user_id: str):
    """
    특정 user_id의 최신 STT 텍스트 결과 반환.
    (whisper_worker_daglo_mic → MQTT → analysis_listener → 메모리 캐시)
    """
    data = get_latest_text(user_id)
    if not data:
        raise HTTPException(status_code=404, detail="No text yet for this user_id")
    return data