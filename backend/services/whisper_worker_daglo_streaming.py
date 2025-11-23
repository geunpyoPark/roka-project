"""
Daglo Realtime STT 연동 워커 (MQTT 48k PCM → Daglo gRPC 스트리밍 → MQTT 텍스트)

- 입력 MQTT 토픽
  interview/{user_id}/audio/pcm : WebSocket → FastAPI → MQTT 로 넘어온 Int16 PCM(48kHz)

- 출력 MQTT 토픽
  interview/{user_id}/speech/text : Daglo STT 결과 텍스트(JSON)

구조는 Daglo 공식 client.py와 동일한 gRPC StreamingRecognize 패턴을 사용하되,
PyAudio 대신 MQTT로 들어온 오디오 버퍼를 사용하도록 바꾼 버전.
"""

import os
import sys
import json
import time
import threading
import queue
from typing import Dict

import numpy as np
import grpc
import paho.mqtt.client as mqtt

# =====================================
#  패키지 임포트 경로 보정 (backend 인식용)
# =====================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(CURRENT_DIR))  # ~/roka-project
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

from backend.services.daglo import speech_pb2, speech_pb2_grpc  # noqa: E402


# ==============================
# Daglo gRPC 설정
# ==============================

# Daglo 서버 (기본값: 공식 가이드와 동일)
DAGLO_SERVER = os.getenv("DAGLO_SERVER", "apis.daglo.ai")

# 반드시 환경변수로 설정해 두기:
#   export DAGLO_API_TOKEN="발급받은_토큰"
DAGLO_API_TOKEN = os.getenv("DAGLO_API_TOKEN")

if not DAGLO_API_TOKEN:
    raise RuntimeError(
        "[whisper_daglo] 환경변수 DAGLO_API_TOKEN 이 설정되어 있지 않습니다. "
        '터미널에서 `export DAGLO_API_TOKEN="..."` 로 설정해 주세요.'
    )

# gRPC용 샘플레이트 (Daglo 요구 사항: 16kHz, 1ch, LINEAR16)
DAGLO_SAMPLE_RATE = 16000
CHUNK_SEC = 0.25  # client.py와 동일: 0.25초 프레임
CHUNK_SAMPLES_16K = int(DAGLO_SAMPLE_RATE * CHUNK_SEC)  # 4000 샘플
CHUNK_BYTES_16K = CHUNK_SAMPLES_16K * 2  # int16 → 2바이트

# ==============================
# WebAudio / MQTT 입력 설정 (48kHz → 16kHz 다운샘플링)
# ==============================

WEB_SAMPLE_RATE = 48000
SAMPLE_WIDTH = 2  # int16

# 0.25초 분량의 48k 샘플 개수 및 바이트 수
CHUNK_SAMPLES_48K = int(WEB_SAMPLE_RATE * CHUNK_SEC)     # 12000
CHUNK_BYTES_48K = CHUNK_SAMPLES_48K * SAMPLE_WIDTH       # 24000

# user_id 별 48k PCM 버퍼
user_buffers_48k: Dict[str, bytearray] = {}

# ==============================
# MQTT 설정
# ==============================

BROKER_HOST = "localhost"
BROKER_PORT = 1883
KEEPALIVE = 60

CLIENT_ID = "whisper-daglo-worker"

AUDIO_PCM_TOPIC = "interview/+/audio/pcm"


def speech_text_topic(user_id: str) -> str:
    return f"interview/{user_id}/speech/text"


# ==============================
# gRPC Stub & 메타데이터 (전역)
# ==============================

GRPC_STUB = None
GRPC_METADATA = None  # 인증 헤더용


# ==============================
# Daglo 세션 클래스 (user_id 별로 1개씩)
# ==============================

class DagloSession:
    """
    한 user_id 에 대해:
    - Daglo Speech.StreamingRecognize 스트림 1개
    - audio_queue 에 들어온 16k PCM 조각을 gRPC로 전송
    - 응답을 받아 MQTT로 텍스트 퍼블리시
    """

    def __init__(self, user_id: str, stub: speech_pb2_grpc.SpeechStub,
                 metadata, mqtt_client: mqtt.Client):
        self.user_id = user_id
        self.stub = stub
        self.metadata = metadata
        self.mqtt_client = mqtt_client

        self.audio_queue: "queue.Queue[bytes | None]" = queue.Queue()
        self.last_total_duration: float = 0.0  # Daglo total_duration 기반 구간 길이 계산용

        # 전체 문장 누적 (짧은 토막 방지용)
        self.full_transcript: str = ""

        self.thread = threading.Thread(target=self._run_stream, daemon=True)
        self.thread.start()
        print(f"[whisper_daglo] Started DagloSession for user={user_id}")

    # RecognitionConfig 생성 (client.py와 동일 구조)
    def _build_config(self) -> speech_pb2.RecognitionConfig:
        return speech_pb2.RecognitionConfig(
            language_code="ko-KR",
            interim_results=True,
        )

    # gRPC 요청 제너레이터: 첫 요청은 config, 이후는 audio_content
    def _request_generator(self):
        config = self._build_config()
        # 첫 번째 요청: 설정
        yield speech_pb2.StreamingRecognizeRequest(config=config)

        # 이후 요청: 오디오 데이터
        while True:
            chunk = self.audio_queue.get()  # bytes 또는 None
            if chunk is None:
                # EOS 시그널 → 마지막 빈 요청 전송 후 종료
                break
            yield speech_pb2.StreamingRecognizeRequest(audio_content=chunk)

        # 마지막 요청: 빈 메시지로 스트림 종료 (client.py와 동일)
        yield speech_pb2.StreamingRecognizeRequest()

    def _append_piece(self, piece: str) -> str:
        """
        최종 결과 토막(piece)을 full_transcript에 합치는 로직.
        - 같은 토막 반복 방지
        - 필요 시 공백 추가
        """
        piece = piece.strip()
        if not piece:
            return self.full_transcript

        # 직전 full_transcript 끝부분과 중복되면 그냥 무시
        tail = self.full_transcript[-(len(piece) + 1):] if self.full_transcript else ""
        if piece in tail:
            return self.full_transcript

        # 공백 처리 후 이어붙이기
        if self.full_transcript and not self.full_transcript.endswith((" ", ".", "!", "?", "…")):
            self.full_transcript += " "
        self.full_transcript += piece
        return self.full_transcript

    def _should_publish(self, text: str) -> bool:
        """
        너무 짧은 텍스트(한 글자, 추임새 수준)는 publish 안 하도록 필터.
        speech_rate_worker에서도 추가로 필터 있지만 여기서 1차 필터.
        """
        core = text.replace(" ", "").replace("요", "")
        return len(core) >= 3  # 최소 3글자 이상일 때만 전송

    def _handle_response(self, response: speech_pb2.StreamingRecognizeResponse):
        result = response.result
        if not result:
            return

        transcript = (result.transcript or "").strip()
        if not transcript:
            return

        # 부분 결과 / 최종 결과 로그
        if result.is_final:
            print(f"[whisper_daglo] [{self.user_id}] FINAL piece: {transcript}")
        else:
            print(f"[whisper_daglo] [{self.user_id}] PARTIAL: {transcript}", end="\r")

        # speech_rate_worker 에는 최종 결과만 보내는 게 깔끔함
        if not result.is_final:
            return

        # full_transcript 갱신
        full_text = self._append_piece(transcript)
        print(f"[whisper_daglo] [{self.user_id}] FULL text: {full_text}")

        if not self._should_publish(full_text):
            print(f"[whisper_daglo] [{self.user_id}] Text too short, skip publish")
            return

        # 구간 duration 계산: total_duration 증가분
        total_dur = float(response.total_duration or 0.0)
        seg_dur = max(total_dur - self.last_total_duration, 0.1)
        self.last_total_duration = total_dur

        payload = {
            "user_id": self.user_id,
            "timestamp": time.time(),
            "duration": seg_dur,
            "text": full_text,
        }
        topic = speech_text_topic(self.user_id)
        self.mqtt_client.publish(topic, json.dumps(payload, ensure_ascii=False))
        print(f"[whisper_daglo] [{self.user_id}] Published STT to {topic} (dur={seg_dur:.2f}s)")

    def _run_stream(self):
        """
        Daglo StreamingRecognize 호출 루프.
        audio_queue 에 오디오가 들어올 때까지 블록되며,
        응답을 받아서 _handle_response 로 처리.
        """
        while True:
            try:
                print(f"[whisper_daglo] [{self.user_id}] Opening StreamingRecognize...")
                response_iterator = self.stub.StreamingRecognize(
                    self._request_generator(),
                    metadata=self.metadata,
                )

                for response in response_iterator:
                    self._handle_response(response)

                print(f"[whisper_daglo] [{self.user_id}] Stream closed by server.")
                break  # 서버가 정상적으로 닫으면 루프 종료

            except grpc.RpcError as e:
                print(f"[whisper_daglo] [{self.user_id}] gRPC error: {e.code()}, {e.details()}")
                # 에러 발생 시 잠깐 대기 후 스트림 재시도
                time.sleep(1.0)
                # total_duration 초기화 (새 스트림 기준으로 다시)
                self.last_total_duration = 0.0
                # 재시작 시, audio_queue 는 그대로 유지 (남은 오디오 계속 전송)


# user_id → DagloSession
sessions: Dict[str, DagloSession] = {}


def get_or_create_session(user_id: str, mqtt_client: mqtt.Client) -> DagloSession:
    sess = sessions.get(user_id)
    if sess is None:
        if GRPC_STUB is None or GRPC_METADATA is None:
            raise RuntimeError("[whisper_daglo] gRPC STUB/Metadata not initialized.")
        sess = DagloSession(user_id, GRPC_STUB, GRPC_METADATA, mqtt_client)
        sessions[user_id] = sess
    return sess


# ==============================
# 48k → 16k 다운샘플링 유틸
# ==============================

def downsample_48k_to_16k(chunk_bytes_48k: bytes) -> bytes:
    """
    48kHz, int16 PCM → 16kHz, int16 PCM 으로 단순 다운샘플링.
    (0.25초 분량: 12000 샘플 → 4000 샘플)

    * 매우 단순히 3개 샘플 중 1개만 취하는 방식 (audio[::3])
    * 고급 리샘플링이 필요하면 scipy.signal.resample 등을 사용할 수 있음.
    """
    audio_48 = np.frombuffer(chunk_bytes_48k, dtype=np.int16).astype(np.float32)

    # 48k → 16k : 3배 decimation
    audio_16 = audio_48[::3]

    # 클리핑 후 int16 변환
    audio_16 = np.clip(audio_16, -32768, 32767).astype(np.int16)
    return audio_16.tobytes()


# ==============================
# MQTT 콜백
# ==============================

def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[whisper_daglo] Connected to MQTT broker: rc={reason_code}")
    if reason_code == 0:
        client.subscribe(AUDIO_PCM_TOPIC)
        print(f"[whisper_daglo] Subscribed to {AUDIO_PCM_TOPIC}")
    else:
        print("[whisper_daglo] MQTT connection failed")


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        parts = topic.split("/")
        # interview / {user_id} / audio / pcm
        if len(parts) < 4:
            print("[whisper_daglo] Unexpected topic:", topic)
            return

        _, user_id, category, subtopic, *rest = parts
        if not (category == "audio" and subtopic == "pcm"):
            print("[whisper_daglo] Ignore topic:", topic)
            return

        # 세션 생성(없으면) + 48k 버퍼에 데이터 추가
        sess = get_or_create_session(user_id, client)

        buf = user_buffers_48k.setdefault(user_id, bytearray())
        buf.extend(msg.payload)

        # 0.25초 분량(24000 bytes)씩 잘라서 16k로 다운샘플 후 세션 큐에 넣기
        while len(buf) >= CHUNK_BYTES_48K:
            chunk_48 = bytes(buf[:CHUNK_BYTES_48K])
            del buf[:CHUNK_BYTES_48K]

            # 디버그용 RMS 계산 (선택)
            audio_48 = np.frombuffer(chunk_48, dtype=np.int16).astype(np.float32)
            audio_norm = audio_48 / 32768.0
            rms_val = float(np.sqrt(np.mean(audio_norm * audio_norm)))
            print(
                f"[whisper_daglo] [{user_id}] 48k chunk: bytes={len(chunk_48)}, "
                f"rms={rms_val:.4f}"
            )

            chunk_16 = downsample_48k_to_16k(chunk_48)
            if len(chunk_16) != CHUNK_BYTES_16K:
                print(
                    f"[whisper_daglo] [{user_id}] Warning: 16k chunk size mismatch "
                    f"{len(chunk_16)} != {CHUNK_BYTES_16K}"
                )

            # Daglo 스트림으로 전송할 오디오 큐에 push
            sess.audio_queue.put(chunk_16)

    except Exception as e:
        print(f"[whisper_daglo] on_message error on topic {topic}: {e}")


# ==============================
# main
# ==============================

def main():
    global GRPC_STUB, GRPC_METADATA

    # 1) Daglo gRPC 채널 & Stub 준비 (client.py와 동일)
    creds = grpc.ssl_channel_credentials()
    channel = grpc.secure_channel(DAGLO_SERVER, creds)
    GRPC_STUB = speech_pb2_grpc.SpeechStub(channel)
    GRPC_METADATA = (
        ("authorization", f"Bearer {DAGLO_API_TOKEN}"),
    )
    print(f"[whisper_daglo] gRPC channel ready. server={DAGLO_SERVER}")

    # 2) MQTT 클라이언트 설정
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv5,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
    print("[whisper_daglo] Started. Waiting for MQTT 48k PCM...")

    # MQTT 네트워크 루프를 메인 스레드에서 돌림 (Ctrl+C로 종료)
    try:
        client.loop_forever()
    finally:
        channel.close()
        print("[whisper_daglo] gRPC channel closed.")


if __name__ == "__main__":
    main()