# backend/services/whisper_worker_daglo_mic.py
"""
Daglo Realtime STT (마이크 입력 버전) + 화자 분리 데모

- 로컬 마이크에서 16kHz PCM 캡쳐 (PyAudio)
- Daglo gRPC StreamingRecognize 호출
- 최종 텍스트가 나올 때마다:
    1) MQTT 로 STT 텍스트 퍼블리시  (speech_rate_worker 용)
    2) FastAPI 백엔드의 /transcript/{user_id} 에 POST
       → speaker: "interviewer" 또는 "candidate"
"""

import os
import sys
import time
import queue
import threading
from typing import Optional

import grpc
import numpy as np
import paho.mqtt.client as mqtt
import pyaudio
import requests

# backend 모듈 import 위해 sys.path 보정
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from backend.services.daglo import speech_pb2, speech_pb2_grpc

# ==============================
# 환경 설정
# ==============================

DAGLO_SERVER = os.getenv("DAGLO_SERVER", "apis.daglo.ai")
DAGLO_API_TOKEN = os.getenv("DAGLO_API_TOKEN")
if not DAGLO_API_TOKEN:
    raise RuntimeError(
        "[whisper_daglo_mic] 환경변수 DAGLO_API_TOKEN 이 설정되어 있지 않습니다."
    )

# FastAPI 백엔드 주소 (Transcript POST용)
BACKEND_BASE = os.getenv("BACKEND_BASE", "http://127.0.0.1:8000")

# 테스트용 user_id
USER_ID = os.getenv("INTERVIEW_USER_ID", "test-user-1")

# 마이크 / 오디오 설정
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # int16
CHUNK_SEC = 0.25
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_SEC)  # 4000
CHUNK_BYTES = CHUNK_SAMPLES * SAMPLE_WIDTH

# MQTT 설정
BROKER_HOST = "localhost"
BROKER_PORT = 1883
KEEPALIVE = 60
MQTT_CLIENT_ID = "whisper-daglo-mic-worker"

SPEECH_TEXT_TOPIC = f"interview/{USER_ID}/speech/text"

# ==============================
# 글로벌 상태
# ==============================

GRPC_STUB: Optional[speech_pb2_grpc.SpeechStub] = None
GRPC_METADATA = None

audio_queue: "queue.Queue[bytes | None]" = queue.Queue()

# Daglo total_duration 추적
last_total_duration: float = 0.0

# 화자 분리용 turn index
TURN_INDEX = 0


# ==============================
# 화자 분리 (데모용 로직)
# ==============================

def guess_speaker(text: str, turn_index: int) -> str:
    """
    아주 단순한 화자 분리 데모 로직.
    - 질문스러운 문장(?, '~인가요', '~습니까') → interviewer
    - 그 외 → candidate
    - 애매하면 turn_index 짝/홀로 번갈아가며 interviewer/candidate
    나중에 진짜 diarization 모델을 붙일 때 이 함수만 갈아끼우면 됨.
    """
    t = text.strip()
    if not t:
        return "candidate"

    # 1) 물음표가 있으면 질문으로 간주
    if "?" in t:
        return "interviewer"

    # 2) 한국어 질문 어미들 (간단 예시)
    question_endings = [
        "나요", "나요?", "습니까", "습니까?", "세요?", "죠?", "인지요?", "인지요",
        "인가요", "인가요?"
    ]
    if any(t.endswith(end) for end in question_endings):
        return "interviewer"

    # 3) fallback: 턴 번호 기반 번갈아 태깅
    if turn_index % 2 == 0:
        return "interviewer"
    else:
        return "candidate"


# ==============================
# MQTT 콜백
# ==============================

def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[whisper_daglo_mic] MQTT connected rc={reason_code}")


def create_mqtt_client() -> mqtt.Client:
    client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        protocol=mqtt.MQTTv5,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
    client.loop_start()
    print(
        f"[whisper_daglo_mic] MQTT client started. "
        f"broker={BROKER_HOST}:{BROKER_PORT}"
    )
    return client


# ==============================
# Transcript POST 유틸
# ==============================

def post_transcript_segment(
    user_id: str,
    speaker: str,
    text: str,
    start_sec: Optional[float],
    end_sec: Optional[float],
):
    """
    FastAPI 백엔드의 /transcript/{user_id} 엔드포인트에 한 턴 보내기.
    backend/routers/transcript.py 의 AppendRequest 형식을 따름.
    """
    url = f"{BACKEND_BASE}/transcript/{user_id}"
    payload = {
        "speaker": speaker,
        "text": text,
        "start_ts": start_sec,
        "end_ts": end_sec,
    }
    try:
        resp = requests.post(url, json=payload, timeout=1.0)
        if not resp.ok:
            print(
                f"[whisper_daglo_mic] POST /transcript 실패 "
                f"status={resp.status_code}, body={resp.text}"
            )
    except Exception as e:
        print(f"[whisper_daglo_mic] POST /transcript 오류: {e}")


# ==============================
# Daglo gRPC 설정 & 요청/응답
# ==============================

def build_config() -> speech_pb2.RecognitionConfig:
    return speech_pb2.RecognitionConfig(
        language_code="ko-KR",
        interim_results=True,
    )


def request_generator():
    """
    gRPC StreamingRecognize에 전달할 제너레이터.
    처음 1번은 config, 이후는 audio_content.
    """
    config = build_config()
    # 첫 요청: 설정
    yield speech_pb2.StreamingRecognizeRequest(config=config)

    # 이후: audio_queue에서 PCM 조각 소비
    while True:
        chunk = audio_queue.get()  # type: ignore[assignment]
        if chunk is None:
            break
        yield speech_pb2.StreamingRecognizeRequest(audio_content=chunk)

    # 마지막 빈 요청
    yield speech_pb2.StreamingRecognizeRequest()


def handle_response(
    mqtt_client: mqtt.Client,
    response: speech_pb2.StreamingRecognizeResponse,
):
    global last_total_duration, TURN_INDEX

    result = response.result
    if not result:
        return

    transcript = (result.transcript or "").strip()
    if not transcript:
        return

    if result.is_final:
        print(f"[whisper_daglo_mic] FINAL: {transcript}")
    else:
        # 부분 결과는 로그만
        print(f"[whisper_daglo_mic] PARTIAL: {transcript}", end="\r")
        return

    # 최종 결과만 아래 처리
    total_dur = float(response.total_duration or 0.0)
    seg_dur = max(total_dur - last_total_duration, 0.1)
    start_sec = max(total_dur - seg_dur, 0.0)
    end_sec = total_dur
    last_total_duration = total_dur

    # --- 1) MQTT로 STT 퍼블리시 (speech_rate_worker 용) ---
    payload = {
        "user_id": USER_ID,
        "timestamp": time.time(),
        "duration": seg_dur,
        "text": transcript,
    }
    mqtt_client.publish(
        SPEECH_TEXT_TOPIC,
        payload=str(payload).replace("'", '"'),  # 간단 JSON 직렬화
    )
    print(
        f"[whisper_daglo_mic] Published STT to {SPEECH_TEXT_TOPIC} "
        f"(dur={seg_dur:.2f}s, text='{transcript}')"
    )

    # --- 2) 화자 추정 + Transcript API에 전송 ---
    speaker = guess_speaker(transcript, TURN_INDEX)
    TURN_INDEX += 1

    post_transcript_segment(
        user_id=USER_ID,
        speaker=speaker,
        text=transcript,
        start_sec=start_sec,
        end_sec=end_sec,
    )


def run_daglo_stream(mqtt_client: mqtt.Client):
    """
    Daglo StreamingRecognize 호출 루프.
    """
    global GRPC_STUB, GRPC_METADATA, last_total_duration

    creds = grpc.ssl_channel_credentials()
    channel = grpc.secure_channel(DAGLO_SERVER, creds)
    GRPC_STUB = speech_pb2_grpc.SpeechStub(channel)
    GRPC_METADATA = (("authorization", f"Bearer {DAGLO_API_TOKEN}"),)

    print(f"[whisper_daglo_mic] gRPC channel ready. server={DAGLO_SERVER}")
    last_total_duration = 0.0

    try:
        while True:
            try:
                print("[whisper_daglo_mic] Daglo STT 스트리밍 시작. Ctrl+C 로 종료하세요.")
                responses = GRPC_STUB.StreamingRecognize(
                    request_generator(),
                    metadata=GRPC_METADATA,
                )

                for res in responses:
                    handle_response(mqtt_client, res)

                print("[whisper_daglo_mic] Stream closed by server.")
                break
            except grpc.RpcError as e:
                print(
                    f"[whisper_daglo_mic] gRPC error: {e.code()}, {e.details()}"
                )
                time.sleep(1.0)
                last_total_duration = 0.0
    finally:
        channel.close()
        print("[whisper_daglo_mic] gRPC channel closed.")


# ==============================
# 마이크 캡쳐 스레드
# ==============================

def mic_capture_loop():
    pa = pyaudio.PyAudio()
    stream = pa.open(
        format=pa.get_format_from_width(SAMPLE_WIDTH),
        channels=CHANNELS,
        rate=SAMPLE_RATE,
        input=True,
        frames_per_buffer=CHUNK_SAMPLES,
    )
    print("[whisper_daglo_mic] 마이크 캡처 시작")

    try:
        while True:
            data = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            audio_queue.put(data)
    except KeyboardInterrupt:
        print("[whisper_daglo_mic] KeyboardInterrupt: 마이크 종료 요청")
    finally:
        audio_queue.put(None)
        stream.stop_stream()
        stream.close()
        pa.terminate()
        print("[whisper_daglo_mic] 마이크 캡처 종료")


# ==============================
# main
# ==============================

def main():
    mqtt_client = create_mqtt_client()

    # 마이크 스레드
    mic_thread = threading.Thread(target=mic_capture_loop, daemon=True)
    mic_thread.start()

    # Daglo gRPC 루프 (메인 스레드)
    try:
        run_daglo_stream(mqtt_client)
    except KeyboardInterrupt:
        print("[whisper_daglo_mic] 종료 요청 (Ctrl+C)")
    finally:
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        print("[whisper_daglo_mic] MQTT disconnected")


if __name__ == "__main__":
    main()