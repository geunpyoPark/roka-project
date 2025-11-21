# backend/services/whisper_worker.py

"""
MQTT로 들어오는 PCM 오디오(interview/{user_id}/audio/pcm)를 받아서
 - 일정 길이만큼 버퍼링한 뒤
 - faster-whisper로 STT 수행
 - 결과 텍스트를 interview/{user_id}/speech/text 토픽으로 publish

파이프라인:
  audio_stream(WebSocket) -> MQTT: interview/{user_id}/audio/pcm (raw PCM)
  whisper_worker          -> MQTT: interview/{user_id}/speech/text (JSON)
  speech_rate_worker      -> MQTT: interview/{user_id}/speech/analysis ...
"""

import time
import json
from collections import defaultdict

import numpy as np
import paho.mqtt.client as mqtt
from faster_whisper import WhisperModel

# ------------------------------------------------
# MQTT 설정
# ------------------------------------------------
BROKER_HOST = "localhost"
BROKER_PORT = 1883

# 오디오 PCM 토픽 (user_id는 와일드카드)
# audio_stream 쪽에서 여기로 "raw PCM 바이트"를 publish 해야 함
SUB_TOPIC = "interview/+/audio/pcm"

# ------------------------------------------------
# 오디오 / 윈도우 설정
# ------------------------------------------------
# WebAudio AudioContext의 sampleRate (대부분 48kHz) 기준으로 가정
# 실제 값은 브라우저 콘솔에서 audioContext.sampleRate로 확인 가능
INPUT_SAMPLE_RATE = 48000
TARGET_SAMPLE_RATE = 16000   # whisper 기본 16kHz

# 몇 초 단위 오디오를 모아서 STT 할지
WINDOW_SECONDS = 2.5

# ------------------------------------------------
# Whisper 모델 로딩
# ------------------------------------------------
print("[whisper_worker] Loading faster-whisper model (tiny) ...")
whisper_model = WhisperModel(
    "tiny",
    device="cpu",
    compute_type="int8",  # M 시리즈 맥에서 속도/성능 밸런스
)
print("[whisper_worker] Model loaded.")

# 유저별 오디오 버퍼 상태 관리
# buffers[user_id] = { "audio": bytearray, "start_ts": float | None }
buffers = defaultdict(lambda: {"audio": bytearray(), "start_ts": None})


# ------------------------------------------------
# 유틸: 다운샘플링
# ------------------------------------------------
def downsample_pcm(int16_samples: np.ndarray) -> np.ndarray:
    """
    아주 단순한 다운샘플 (decimation) 48k -> 16k (3배)
    실제 제품에서는 resampy, torchaudio 등으로 리샘플링하는 게 좋지만,
    여기서는 구조 확인용 프로토타입으로 간단히 처리
    """
    if INPUT_SAMPLE_RATE == TARGET_SAMPLE_RATE:
        return int16_samples.astype(np.float32) / 32768.0

    factor = int(round(INPUT_SAMPLE_RATE / TARGET_SAMPLE_RATE))  # 48000/16000=3
    if factor <= 1:
        return int16_samples.astype(np.float32) / 32768.0

    # 간단 decimation: factor개 중 1개만 샘플링
    ds = int16_samples[::factor]
    return ds.astype(np.float32) / 32768.0


# ------------------------------------------------
# 핵심: 버퍼된 오디오로 STT 후 publish
# ------------------------------------------------
def transcribe_and_publish(client: mqtt.Client, user_id: str) -> None:
    """
    buffers[user_id]에 쌓인 오디오로 STT 후 결과를 speech/text로 publish
    """
    buf = buffers[user_id]
    audio_bytes = bytes(buf["audio"])
    if not audio_bytes:
        return

    # Int16 배열로 변환
    int16_samples = np.frombuffer(audio_bytes, dtype=np.int16)

    # 다운샘플링 + float32 [-1, 1]로 정규화
    audio_float = downsample_pcm(int16_samples)

    print(f"[whisper_worker] [{user_id}] Transcribing {len(audio_float)} samples...")

    # faster-whisper 호출
    segments, info = whisper_model.transcribe(
        audio_float,
        language="ko",   # 한국어 위주 → 고정
        beam_size=5,
    )

    text = "".join(seg.text for seg in segments).strip()
    if not text:
        print(f"[whisper_worker] [{user_id}] Empty transcription, skip.")
        # 버퍼는 비워줘야 다음 chunk가 쌓임
        buffers[user_id] = {"audio": bytearray(), "start_ts": None}
        return

    start_ts = buf["start_ts"] or time.time()
    end_ts = time.time()
    duration = end_ts - start_ts

    payload = {
        "user_id": user_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration": duration,
        "text": text,
    }

    out_topic = f"interview/{user_id}/speech/text"
    client.publish(out_topic, json.dumps(payload, ensure_ascii=False))
    print(f"[whisper_worker] [{user_id}] Published text to {out_topic}: {text!r}")

    # 버퍼 초기화
    buffers[user_id] = {"audio": bytearray(), "start_ts": None}


# ------------------------------------------------
# MQTT 콜백
# ------------------------------------------------
def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[whisper_worker] Connected to MQTT broker: rc={reason_code}")
    if reason_code == 0:
        client.subscribe(SUB_TOPIC)
        print(f"[whisper_worker] Subscribed to {SUB_TOPIC}")
    else:
        print("[whisper_worker] Connection failed")


def on_message(client, userdata, msg):
    """
    interview/{user_id}/audio/pcm 토픽에서 PCM chunk를 수신.
    일정 길이(WINDOW_SECONDS) 이상 모이면 한 번 transcription.
    """
    try:
        topic = msg.topic  # 예: interview/test-user-1/audio/pcm
        parts = topic.split("/")

        # ["interview", "{user_id}", "audio", "pcm"] 구조 기대
        if len(parts) < 4:
            print("[whisper_worker] Invalid topic:", topic)
            return

        user_id = parts[1]
        pcm_bytes = msg.payload  # raw PCM bytes (Int16 little-endian)

        buf = buffers[user_id]
        if buf["start_ts"] is None:
            buf["start_ts"] = time.time()

        buf["audio"].extend(pcm_bytes)

        # 몇 초 정도 쌓였는지 계산 (입력 샘플레이트 기준)
        num_samples = len(buf["audio"]) // 2  # int16 개수
        duration = num_samples / float(INPUT_SAMPLE_RATE)

        # 충분히 쌓였으면 한 번 transcription
        if duration >= WINDOW_SECONDS:
            transcribe_and_publish(client, user_id)

    except Exception as e:
        print("[whisper_worker] on_message error:", e)


# ------------------------------------------------
# 엔트리포인트
# ------------------------------------------------
def main():
    client_id = f"whisper-worker-{int(time.time())}"

    # ✅ paho-mqtt v2 스타일 (speech_rate_worker와 동일 패턴)
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv5,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    print("[whisper_worker] Started. Waiting for audio PCM...")
    client.loop_forever()


if __name__ == "__main__":
    main()