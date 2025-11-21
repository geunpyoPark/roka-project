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

    # "<h" = little-endian int16, count개
    samples = struct.unpack("<" + "h" * count, pcm_bytes)
    ssum = 0
    for s in samples:
        ssum += s * s
    return math.sqrt(ssum / count)


@router.websocket("/audio-stream")
async def audio_stream(websocket: WebSocket):
    # WebSocket 연결 수락
    await websocket.accept()

    # 일단 하드코딩, 나중에 쿼리파라미터나 토큰으로 교체 가능
    user_id = "test-user-1"

    try:
        while True:
            # 브라우저에서 Int16Array → 바이너리로 보내는 것을 받음
            data = await websocket.receive_bytes()

            # PCM RMS 계산
            rms = compute_rms(data)
            num_samples = len(data) // 2  # int16 개수

            payload = {
                "timestamp": time.time(),
                "user_id": user_id,
                "num_samples": num_samples,
                "rms": rms,
                "note": "audio chunk received from websocket",
            }

            # MQTT 토픽 설계
            topic = f"interview/{user_id}/audio/raw"

            # 🔥 여기서 dict 그대로 넘기면 mqtt_client.publish 안에서 JSON으로 변환됨
            publish(topic, payload)

    except Exception as e:
        print("WebSocket closed:", e)