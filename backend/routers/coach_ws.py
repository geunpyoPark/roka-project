# backend/routers/coach_ws.py

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import asyncio
import time

from backend.services.analysis_cache import (
    get_latest_analysis,
    get_latest_text,
)

router = APIRouter()

@router.websocket("/coach-events/{user_id}")
async def coach_events(websocket: WebSocket, user_id: str):
    """
    프론트엔드에서 면접 코치 페이지 접속 시 연결하는 WebSocket.

    - backend/services/analysis_cache 가 MQTT를 통해 캐싱해 둔
      speech/analysis, speech/text 를 주기적으로 읽어와서
      클라이언트로 push 해준다.
    """
    await websocket.accept()
    print(f"[coach_ws] WebSocket connected: user_id={user_id}")

    last_analysis_ts = 0.0
    last_text_ts = 0.0

    try:
        while True:
            await asyncio.sleep(0.3)  # 0.3초 간격으로 폴링

            # 1) 말속도 분석 결과
            analysis = get_latest_analysis(user_id)
            if analysis:
                # end_ts 또는 timestamp 기반으로 "변경 여부" 체크
                ts = float(analysis.get("end_ts") or analysis.get("timestamp") or 0.0)
                if ts > last_analysis_ts:
                    last_analysis_ts = ts

                    msg = {
                        "type": "speech",
                        "wpm": analysis.get("words_per_min"),
                        "chars_per_sec": analysis.get("chars_per_sec"),
                        "label": analysis.get("speed_label") or analysis.get("level"),
                        "duration": analysis.get("duration"),
                        "text": analysis.get("text", ""),
                    }
                    await websocket.send_json(msg)

            # 2) (옵션) 순수 STT 텍스트도 별도로 보내고 싶으면 사용
            #    whisper_worker가 별도 speech/text 토픽으로 보내는 경우
            text_data = get_latest_text(user_id)
            if text_data:
                ts2 = float(text_data.get("end_ts") or text_data.get("timestamp") or 0.0)
                if ts2 > last_text_ts:
                    last_text_ts = ts2
                    msg2 = {
                        "type": "transcript",
                        "text": text_data.get("text", ""),
                    }
                    await websocket.send_json(msg2)

    except WebSocketDisconnect:
        print(f"[coach_ws] WebSocket disconnected: user_id={user_id}")
    except Exception as e:
        print(f"[coach_ws] Error in ws for user {user_id}: {e}")
        try:
            await websocket.close()
        except Exception:
            pass