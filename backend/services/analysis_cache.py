# backend/services/analysis_cache.py

from typing import Dict, Any
from threading import Lock

# user_id -> 마지막 말속도 분석 결과
_latest_analysis: Dict[str, Dict[str, Any]] = {}
# user_id -> 마지막 STT 텍스트 결과
_latest_text: Dict[str, Dict[str, Any]] = {}

_lock = Lock()


def update_analysis(user_id: str, analysis: Dict[str, Any]) -> None:
    """
    말속도 분석 결과를 user_id 기준으로 메모리에 저장.
    (speech_rate_worker 결과)
    """
    with _lock:
        _latest_analysis[user_id] = analysis


def update_text(user_id: str, text_data: Dict[str, Any]) -> None:
    """
    STT 텍스트 결과를 user_id 기준으로 메모리에 저장.
    (whisper_worker 결과)
    """
    with _lock:
        _latest_text[user_id] = text_data


def get_latest_analysis(user_id: str) -> Dict[str, Any] | None:
    """
    해당 user_id의 최신 말속도 분석 결과 반환 (없으면 None).
    """
    with _lock:
        return _latest_analysis.get(user_id)


def get_latest_text(user_id: str) -> Dict[str, Any] | None:
    """
    해당 user_id의 최신 STT 텍스트 결과 반환 (없으면 None).
    """
    with _lock:
        return _latest_text.get(user_id)


# ✅ 예전에 작성한 코드에서 `get_latest(user_id)`를 쓰고 있으니까
#    호환성용 alias도 하나 만들어 둠.
def get_latest(user_id: str) -> Dict[str, Any] | None:
    """
    옛날 코드 호환용: 최신 말속도 분석 결과를 반환.
    (내부적으로 get_latest_analysis 호출)
    """
    return get_latest_analysis(user_id)