# backend/services/whisper_worker.py

"""
Whisper STT 워커

- 입력 MQTT 토픽
  1) interview/{user_id}/audio/pcm
     → 브라우저 오디오 WebSocket이 보내는 Int16 PCM 을 FastAPI가 그대로 MQTT로 퍼블리시

  2) interview/{user_id}/speech/segment
     → speech_worker 가 음성 구간을 잡아서 start_ts/end_ts/duration 을 담아 쏨

- 출력 MQTT 토픽
  3) interview/{user_id}/speech/text
     → 이번 세그먼트에 대한 STT 텍스트 + 메타데이터를 JSON으로 발행
"""

import json
import time
from typing import Dict, Any, List

import numpy as np
import paho.mqtt.client as mqtt
from faster_whisper import WhisperModel

# ==============================
# MQTT 기본 설정
# ==============================
BROKER = "localhost"
PORT = 1883
KEEPALIVE = 60

CLIENT_ID = "whisper-worker"

# 토픽 패턴
AUDIO_PCM_TOPIC = "interview/+/audio/pcm"
SEGMENT_TOPIC = "interview/+/speech/segment"

# 결과 텍스트를 퍼블리시할 토픽 템플릿
def speech_text_topic(user_id: str) -> str:
    return f"interview/{user_id}/speech/text"


# ==============================
# 오디오 버퍼 관리
# ==============================
# 사용자별 PCM 버퍼(최근 N초만 유지하는 식으로 관리 가능)
user_pcm_buffers: Dict[str, bytearray] = {}
# 사용자별 마지막 오디오 수신 시각(디버깅용)
user_last_audio_ts: Dict[str, float] = {}

# 최대 버퍼 길이(샘플 기준) → 너무 길어지지 않게 잘라줄 때 사용
# (16kHz 기준 30초 = 480000 샘플 → 960000바이트)
SAMPLE_RATE = 16000
MAX_SAMPLES = SAMPLE_RATE * 30
SAMPLE_WIDTH = 2  # int16 = 2 bytes
MAX_BYTES = MAX_SAMPLES * SAMPLE_WIDTH

# 노이즈로 인한 헛소리 전사를 줄이기 위한 최소 RMS
MIN_AUDIO_RMS = 0.01

# ==============================
# Whisper 모델 로드
# ==============================
print("[whisper_worker] Loading faster-whisper model (small, int8) ...")
model = WhisperModel(
    "small",
    device="cpu",
    compute_type="int8",
)
print("[whisper_worker] Model loaded.")


# ==============================
# 유틸 함수들
# ==============================
def append_pcm(user_id: str, pcm_bytes: bytes) -> None:
    """사용자별로 Int16 PCM 바이트를 버퍼에 추가 (뒤에 쌓기)"""
    if not pcm_bytes:
        return

    # 길이가 짝수(=2의 배수)가 아니면 마지막 1바이트 잘라냄
    if len(pcm_bytes) % SAMPLE_WIDTH != 0:
        trimmed = len(pcm_bytes) - (len(pcm_bytes) % SAMPLE_WIDTH)
        pcm_bytes = pcm_bytes[:trimmed]

    buf = user_pcm_buffers.setdefault(user_id, bytearray())
    buf.extend(pcm_bytes)

    # 너무 커지면 뒤쪽 N바이트만 남기기
    if len(buf) > MAX_BYTES:
        # 뒤에서 MAX_BYTES 만큼만 유지
        user_pcm_buffers[user_id] = buf[-MAX_BYTES:]

    user_last_audio_ts[user_id] = time.time()


def trim_buffer(user_id: str, keep_sec: float = 1.0) -> None:
    """전사 후 이미 소비한 구간은 버퍼에서 제거해 반복 전사를 막음."""
    buf = user_pcm_buffers.get(user_id)
    if not buf:
        return

    keep_samples = int(SAMPLE_RATE * max(0.0, keep_sec))
    keep_bytes = keep_samples * SAMPLE_WIDTH

    if keep_bytes <= 0:
        user_pcm_buffers[user_id] = bytearray()
    elif len(buf) > keep_bytes:
        user_pcm_buffers[user_id] = buf[-keep_bytes:]


def get_recent_pcm(user_id: str, max_duration_sec: float = 10.0) -> np.ndarray:
    """
    최근 max_duration_sec 초 정도의 PCM을 잘라서 반환.
    - Int16 → float32 [-1.0, 1.0] 로 변환
    """
    buf = user_pcm_buffers.get(user_id)
    if not buf:
        return np.array([], dtype=np.float32)

    max_samples = int(SAMPLE_RATE * max_duration_sec)
    max_bytes = max_samples * SAMPLE_WIDTH

    if len(buf) > max_bytes:
        pcm_bytes = bytes(buf[-max_bytes:])
    else:
        pcm_bytes = bytes(buf)

    # 길이 방어: 짝수 byte 가 아니면 마지막 1바이트 잘라냄
    if len(pcm_bytes) % SAMPLE_WIDTH != 0:
        trimmed = len(pcm_bytes) - (len(pcm_bytes) % SAMPLE_WIDTH)
        pcm_bytes = pcm_bytes[:trimmed]

    if len(pcm_bytes) == 0:
        return np.array([], dtype=np.float32)

    # Int16 → float32 변환
    audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
    audio_float32 = audio_int16.astype(np.float32) / 32768.0

    return audio_float32


def rms(audio: np.ndarray) -> float:
    if audio.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(audio))))


def transcribe_segment(user_id: str, segment_meta: Dict[str, Any]) -> None:
    """
    특정 user_id 에 대해, 현재까지 쌓인 PCM에서
    최근 N초(예: 10초)를 Whisper로 변환하고 결과를 MQTT로 발행.
    """
    audio = get_recent_pcm(user_id, max_duration_sec=10.0)

    if audio.size == 0:
        print(f"[whisper_worker] [{user_id}] No PCM data available for STT.")
        return

    audio_rms = rms(audio)
    if audio_rms < MIN_AUDIO_RMS:
        # 소음이나 잡음만 있는 경우 흔히 "구독과 좋아요" 같은 헛소리를 생성하므로 건너뜀
        print(
            f"[whisper_worker] [{user_id}] Skip STT (low RMS={audio_rms:.4f}, likely noise)"
        )
        trim_buffer(user_id, keep_sec=0.5)
        return

    print(f"[whisper_worker] [{user_id}] Running Whisper on {len(audio)} samples...")

    # faster-whisper 는 numpy array 또는 파형 파일 경로를 입력받을 수 있음
    # 여기서는 numpy array 로 바로 입력
    segments, info = model.transcribe(
        audio,
        language="ko",    # 한국어 위주라면 명시
        beam_size=5,
        vad_filter=True,
    )

    texts: List[str] = []
    for seg in segments:
        texts.append(seg.text)

    full_text = "".join(texts).strip()

    print(f"[whisper_worker] [{user_id}] STT TEXT: '{full_text}'")

    # speech_rate_worker 가 쓰기 좋게 메타데이터 포함해서 퍼블리시
    out_payload = {
        "user_id": user_id,
        "start_ts": segment_meta.get("start_ts"),
        "end_ts": segment_meta.get("end_ts"),
        "duration": segment_meta.get("duration"),
        "text": full_text,
    }

    topic = speech_text_topic(user_id)
    client: mqtt.Client = segment_meta["_client"]  # on_message에서 넘겨줌
    client.publish(topic, json.dumps(out_payload, ensure_ascii=False))
    # 이미 사용한 오디오는 버퍼에서 잘라 반복 전사를 방지
    trim_buffer(user_id, keep_sec=1.0)


# ==============================
# MQTT 콜백
# ==============================
def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[whisper_worker] Connected to MQTT broker: rc={reason_code}")
    client.subscribe(AUDIO_PCM_TOPIC)
    client.subscribe(SEGMENT_TOPIC)
    print(f"[whisper_worker] Subscribed to {AUDIO_PCM_TOPIC}")
    print(f"[whisper_worker] Subscribed to {SEGMENT_TOPIC}")


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        parts = topic.split("/")
        # interview / {user_id} / audio|speech / ...
        if len(parts) < 4:
            print("[whisper_worker] Unexpected topic:", topic)
            return

        _, user_id, category, subtopic, *rest = parts

        if category == "audio" and subtopic == "pcm":
            # 🔹 raw PCM 바이트 처리
            append_pcm(user_id, msg.payload)
            # 디버깅용 (원하면 주석 해제)
            # print(f"[whisper_worker] [{user_id}] Received PCM chunk: {len(msg.payload)} bytes")

        elif category == "speech" and subtopic == "segment":
            # 🔹 speech_worker가 보내준 JSON 세그먼트 메타 처리
            payload_str = msg.payload.decode("utf-8")
            seg = json.loads(payload_str)

            start_ts = float(seg.get("start_ts", 0.0))
            end_ts = float(seg.get("end_ts", 0.0))
            duration = float(seg.get("duration", 0.0))

            print(
                f"[whisper_worker] [{user_id}] Segment event received "
                f"({start_ts:.2f} ~ {end_ts:.2f}, dur={duration:.2f}s)"
            )

            # segment_meta 에 client 핸들을 같이 전달해서 publish 에서 재사용
            seg_meta = {
                "user_id": user_id,
                "start_ts": start_ts,
                "end_ts": end_ts,
                "duration": duration,
                "_client": client,
            }

            # ✅ 여기에서만 STT 실행
            transcribe_segment(user_id, seg_meta)

        else:
            print("[whisper_worker] Unknown category/subtopic:", category, subtopic)

    except Exception as e:
        print(f"[whisper_worker] on_message error on topic {topic}: {e}")


# ==============================
# main
# ==============================
def main():
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, KEEPALIVE)
    print("[whisper_worker] Started. Waiting for PCM + segments...")

    client.loop_forever()


if __name__ == "__main__":
    main()
