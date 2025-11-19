import time
from fastapi import APIRouter, WebSocket

# 🔥 수정된 import 경로 — 이것이 정답
from ..services.whisper_service import transcribe_audio
from ..services.speech_rate import calc_cps, speed_label
from ..services.speech_chunk import make_chunks

router = APIRouter()

@router.websocket("/ws/audio")
async def audio_stream(websocket: WebSocket):
    await websocket.accept()
    
    print("🎧 WebSocket 연결됨")

    audio_buffer = b""
    start_time = time.time()

    while True:
        try:
            data = await websocket.receive_bytes()
            audio_buffer += data
            
            if len(audio_buffer) > 16000 * 2 * 1:  # 1 sec @ 16kHz, 16bit
                duration = time.time() - start_time

                text, segments = transcribe_audio(audio_buffer)

                cps, char_count = calc_cps(text, duration)
                label = speed_label(cps)
                chunks = make_chunks(segments)

                result = {
                    "transcript": text,
                    "chunks": chunks,
                    "duration_sec": duration,
                    "chars_per_sec": cps,
                    "speed_label": label,
                    "char_count": char_count
                }

                await websocket.send_json(result)

                # reset
                audio_buffer = b""
                start_time = time.time()

        except Exception as e:
            print("WebSocket 종료:", e)
            break
