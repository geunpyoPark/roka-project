# backend/routers/analysis_api.py

from fastapi import APIRouter, HTTPException
from backend.services.analysis_cache import get_latest_analysis

router = APIRouter()


@router.get("/analysis/latest/{user_id}")
def read_latest_analysis(user_id: str):
    """
    특정 user_id에 대해 speech_rate_worker가 계산한
    "마지막 발화의 말속도 분석 결과"를 반환.
    예: /analysis/latest/test-user-1
    """
    data = get_latest_analysis(user_id)
    if data is None:
        raise HTTPException(status_code=404, detail="No analysis yet for this user")

    return data