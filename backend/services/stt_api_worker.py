"""
외부 STT API 기반 워커 (스트리밍용)

- 입력 MQTT 토픽
  interview/{user_id}/audio/pcm   : WebSocket → FastAPI → MQTT 로 넘어온 Int16 PCM

- 출력 MQTT 토픽
  interview/{user_id}/speech/text : STT 결과 텍스트 + 메타데이터(JSON)

Whisper / HuggingFace 대신
HTTP 기반 STT API(예: 다글로 API, NCP Clova Speech, Google STT 등)를 호출하는 버전.
"""

import os
import io
import json
import time
import wave
from typing import Dict

import numpy as np
import paho.mqtt.client as mqtt
import requests

# ==============================
# MQTT 설정
# ==============================
BROKER_HOST = "localhost"
BROKER_PORT = 1883
KEEPALIVE = 60

CLIENT_ID = "stt-api-worker"

AUDIO_PCM_TOPIC = "interview/+/audio/pcm"


def speech_text_topic(user_id: str) -> str:
    return f"interview/{user_id}/speech/text"


# ==============================
# 오디오 버퍼 / STT 파라미터
# ==============================

# WebAudio 기본 샘플레이트 48k 기준
SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2  # int16, mono

WINDOW_SEC = 3.0           # STT 윈도우 길이
STT_INTERVAL_SEC = 3.0     # 같은 유저에 대해 STT 최소 간격
MIN_RMS = 0.01             # 거의 무음인 경우만 스킵

WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_SEC)
WINDOW_BYTES = WINDOW_SAMPLES * SAMPLE_WIDTH

# user_id -> PCM bytearray
user_pcm_buffers: Dict[str, bytearray] = {}
# user_id -> 마지막 STT 실행 시각
user_last_stt_ts: Dict[str, float] = {}
# user_id -> 마지막 퍼블리시 텍스트
user_last_text: Dict[str, str] = {}

# ==============================
# 외부 STT API 설정 (다글로 / Naver / Google 등)
# ==============================

# 예시: 환경변수로 세팅 (export STT_API_URL=... / STT_API_KEY=...)
STT_API_URL = os.getenv("STT_API_URL", "https://example.com/stt")  # <- 여기 실제 엔드포인트로 변경
STT_API_KEY = os.getenv("STT_API_KEY", "WpcuRvuD87O2Edvvkd8j3yhk")             # <- 실제 API 키로 변경

# 필요하다면 추가 파라미터들 (언어코드, 옵션 등)
STT_LANG = os.getenv("STT_LANG", "ko-KR")  # 엔진에 맞게 수정


# ==============================
# 유틸 함수
# ==============================
def append_pcm(user_id: str, pcm_bytes: bytes) -> None:
    """user_id별 Int16 PCM 바이트를 버퍼에 추가"""
    if not pcm_bytes:
        return

    # 길이가 2의 배수 아니면 마지막 1바이트 자르기
    if len(pcm_bytes) % SAMPLE_WIDTH != 0:
        trimmed = len(pcm_bytes) - (len(pcm_bytes) % SAMPLE_WIDTH)
        pcm_bytes = pcm_bytes[:trimmed]

    buf = user_pcm_buffers.setdefault(user_id, bytearray())
    buf.extend(pcm_bytes)

    # 버퍼가 너무 길어지면 뒤쪽 WINDOW_BYTES * 3 정도만 유지 (9초 분량)
    max_bytes = WINDOW_BYTES * 3
    if len(buf) > max_bytes:
        user_pcm_buffers[user_id] = buf[-max_bytes:]


def get_window_audio(user_id: str) -> np.ndarray:
    """버퍼에서 최근 WINDOW_SEC 만큼 잘라 float32 [-1,1] 로 반환"""
    buf = user_pcm_buffers.get(user_id)
    if not buf or len(buf) < WINDOW_BYTES:
        return np.array([], dtype=np.float32)

    pcm_bytes = bytes(buf[-WINDOW_BYTES:])  # 최근 WINDOW_SEC 구간

    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio = audio_int16.astype(np.float32) / 32768.0
    return audio


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


def clean_text(text: str) -> str:
    return (text or "").strip()


def audio_to_wav_bytes(audio: np.ndarray, sample_rate: int) -> bytes:
    """
    float32 [-1,1] mono → 16bit PCM WAV bytes 로 변환.
    대부분의 STT API가 audio/wav 형식 받으니까 이렇게 감싸서 보낼 거야.
    """
    # [-1,1] → int16
    audio_int16 = np.clip(audio * 32767.0, -32768, 32767).astype("<i2")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())
    return buf.getvalue()


# ==============================
# STT 호출 부분 (핵심)
# ==============================
def call_stt_api(audio: np.ndarray, sample_rate: int) -> str:
    """
    외부 STT API 호출해서 텍스트만 뽑아 반환.
    실제 다글로 API 스펙에 맞게 headers / files / data / 응답 parsing 수정하면 됨.
    """
    wav_bytes = audio_to_wav_bytes(audio, sample_rate)

    headers = {
        "Authorization": f"Bearer {STT_API_KEY}",  # 엔진에 맞게 수정
        # "X-API-Key": STT_API_KEY,  # 어떤 API는 이런 방식일 수도 있음
    }

    # 대부분 multipart/form-data 로 파일 업로드
    files = {
        "file": ("audio.wav", wav_bytes, "audio/wav"),
    }

    # 언어, 기타 옵션들
    data = {
        "language": STT_LANG,
        # "some_option": "value",  # 실제 스펙에 맞게 추가
    }

    resp = requests.post(
        STT_API_URL,
        headers=headers,
        files=files,
        data=data,
        timeout=15,
    )
    resp.raise_for_status()

    # ★★ 여기서 응답 포맷에 맞게 텍스트를 뽑아야 함 ★★
    # 예시 1) {"text": "인식 결과"} 형식
    try:
        j = resp.json()
    except Exception:
        print("[stt-api-worker] STT API response is not JSON, raw:", resp.text[:200])
        return ""

    # 여기를 실제 키 이름에 맞게 수정
    # 예: Naver Clova Speech는 ["text"]가 아니라 다른 구조일 수 있음
    text = j.get("text", "")
    return clean_text(text)


def maybe_run_stt(client: mqtt.Client, user_id: str) -> None:
    """
    PCM 청크가 들어올 때마다 호출.
    - 마지막 STT 실행 시각과 윈도우 길이를 보고 조건 만족 시 STT 수행.
    """
    now = time.time()
    last_ts = user_last_stt_ts.get(user_id, 0.0)
    if now - last_ts < STT_INTERVAL_SEC:
        return

    audio = get_window_audio(user_id)
    if audio.size == 0:
        return

    audio_rms = rms(audio)
    print(
        f"[stt-api-worker] [{user_id}] Try STT (samples={audio.size}, "
        f"window={WINDOW_SEC:.2f}s, rms={audio_rms:.4f})"
    )

    if audio_rms < MIN_RMS:
        print(f"[stt-api-worker] [{user_id}] Too quiet (RMS={audio_rms:.4f}), skip.")
        return

    # ---------- 외부 STT API 호출 ----------
    try:
        text = call_stt_api(audio, SAMPLE_RATE)
    except Exception as e:
        print(f"[stt-api-worker] [{user_id}] STT API error: {e}")
        return

    if not text:
        print(f"[stt-api-worker] [{user_id}] -> empty / nonsense, skip publish")
        return

    print(f"[stt-api-worker] [{user_id}] STT TEXT: '{text}'")

    user_last_stt_ts[user_id] = now

    last_text = user_last_text.get(user_id)
    if last_text == text:
        print(f"[stt-api-worker] [{user_id}] Same as last text, (still publish for now)")
    user_last_text[user_id] = text

    payload = {
        "user_id": user_id,
        "timestamp": now,
        "duration": WINDOW_SEC,
        "text": text,
    }
    topic = speech_text_topic(user_id)
    client.publish(topic, json.dumps(payload, ensure_ascii=False))
    print(f"[stt-api-worker] Published STT to {topic}")


# ==============================
# MQTT 콜백
# ==============================
def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[stt-api-worker] Connected to MQTT broker: rc={reason_code}")
    if reason_code == 0:
        client.subscribe(AUDIO_PCM_TOPIC)
        print(f"[stt-api-worker] Subscribed to {AUDIO_PCM_TOPIC}")
    else:
        print("[stt-api-worker] MQTT connection failed")


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        parts = topic.split("/")
        # interview / {user_id} / audio / pcm
        if len(parts) < 4:
            print("[stt-api-worker] Unexpected topic:", topic)
            return

        _, user_id, category, subtopic, *rest = parts

        if category == "audio" and subtopic == "pcm":
            append_pcm(user_id, msg.payload)
            maybe_run_stt(client, user_id)
        else:
            print("[stt-api-worker] Ignore topic:", topic)

    except Exception as e:
        print(f"[stt-api-worker] on_message error on topic {topic}: {e}")


# ==============================
# main
# ==============================
def main():
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv5,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
    print("[stt-api-worker] Started. Waiting for streaming PCM...")

    client.loop_forever()


if __name__ == "__main__":
    main()