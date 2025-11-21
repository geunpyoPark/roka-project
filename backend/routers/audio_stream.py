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
    count = len(pcm_bytes) // 2
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

    # TODO: 나중에는 토큰/쿼리에서 user_id 받아오도록 변경 가능
    user_id = "test-user-1"

    try:
        while True:
            # 브라우저에서 Int16Array로 보낸 오디오
            pcm_bytes: bytes = await websocket.receive_bytes()

            # 1) 메타데이터용 RMS 계산
            rms = compute_rms(pcm_bytes)
            num_samples = len(pcm_bytes) // 2
            ts = time.time()

            meta_payload = {
                "timestamp": ts,
                "user_id": user_id,
                "num_samples": num_samples,
                "rms": rms,
                "note": "audio chunk received from websocket",
            }

            # a) 기존처럼 메타데이터 토픽 (speech_worker용)
            meta_topic = f"interview/{user_id}/audio/raw"
            publish(meta_topic, json.dumps(meta_payload))

            # b) 새로 추가: 실제 PCM 파형 토픽 (whisper_worker용)
            pcm_topic = f"interview/{user_id}/audio/pcm"
            # paho-mqtt는 bytes payload도 지원하니까 그대로 보냄
            publish(pcm_topic, pcm_bytes)

    except Exception as e:
        print("WebSocket closed in /audio-stream:", e)