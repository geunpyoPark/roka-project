# backend/routers/audio_stream.py

from fastapi import APIRouter, WebSocket
from backend.mqtt_client import publish
import time
import json
import math
import struct

router = APIRouter()


def compute_rms(pcm_bytes: bytes) -> float:
    """Int16 PCM 바이트에서 RMS(에너지) 계산"""
    count = len(pcm_bytes) // 2  # 2바이트 = int16 한 개
    if count == 0:
        return 0.0

    samples = struct.unpack("<" + "h" * count, pcm_bytes)
    ssum = 0
    for s in samples:
        ssum += s * s
    return math.sqrt(ssum / count)


@router.websocket("/audio-stream")
async def audio_stream(websocket: WebSocket):
    await websocket.accept()
    user_id = "test-user-1"  # 일단 고정

    print("[audio_stream] WebSocket connected")

    try:
        while True:
            # 브라우저에서 Int16Array.buffer 로 보냄 → bytes 로 받음
            data: bytes = await websocket.receive_bytes()

            # 디버깅용: 길이/샘플수/에너지 확인
            num_samples = len(data) // 2
            rms = compute_rms(data)
            # 너무 시끄러우면 로그만 남기고...
            print(
                f"[audio_stream] recv {num_samples} samples, rms={rms:.2f}"
            )

            ts = time.time()

            raw_payload = {
                "timestamp": ts,
                "user_id": user_id,
                "num_samples": num_samples,
                "rms": rms,
                "note": "audio chunk received from websocket",
            }

            # 1) 메타데이터만 담은 raw 토픽
            publish(
                f"interview/{user_id}/audio/raw",
                json.dumps(raw_payload, ensure_ascii=False),
            )

            # 2) 실제 PCM 바이트 (STT용)
            publish(f"interview/{user_id}/audio/pcm", data)

    except Exception as e:
        print("[audio_stream] WebSocket closed or error:", e)