"""
Daglo 마이크 기반 STT 워커 (client.py 스타일 + MQTT 연동)

- 마이크에서 16kHz PCM을 직접 읽어서
  Daglo Speech.StreamingRecognize로 스트리밍
- Daglo가 보내주는 최종 텍스트(result.is_final == True)를
  interview/{user_id}/speech/text 로 MQTT publish

기존 48k → MQTT → 다운샘플링 구조 때문에 음성이 깨져서
인식이 꼬이는 것 같아서,
Daglo 공식 client.py와 거의 같은 구조로 가되
출력만 우리 프로젝트 포맷에 맞추는 버전.
"""

import os
import time
import json
import signal

import pyaudio
import grpc
import paho.mqtt.client as mqtt

from backend.services.daglo import speech_pb2, speech_pb2_grpc

# ==============================
# 설정
# ==============================

# 인터뷰 유저 ID (지금까지 로그 기준)
USER_ID = "test-user-1"

# Daglo 서버
DAGLO_SERVER = os.getenv("DAGLO_SERVER", "apis.daglo.ai")

# 반드시 설정 필요: export DAGLO_API_TOKEN="..."
DAGLO_API_TOKEN = os.getenv("DAGLO_API_TOKEN")
if not DAGLO_API_TOKEN:
    raise RuntimeError(
        "[whisper_daglo_mic] 환경변수 DAGLO_API_TOKEN 이 설정되어 있지 않습니다.\n"
        "  예) export DAGLO_API_TOKEN=\"발급받은_토큰\""
    )

# 오디오 설정 (Daglo 가이드 기준)
RATE = 16000
CHUNK_SEC = 0.25  # 0.25초 (client.py와 동일)
CHUNK_SAMPLES = int(RATE * CHUNK_SEC)  # 4000 샘플
CHANNELS = 1
FORMAT = pyaudio.paInt16  # LINEAR16

# MQTT 설정
BROKER_HOST = "localhost"
BROKER_PORT = 1883
KEEPALIVE = 60
MQTT_CLIENT_ID = "whisper-daglo-mic-worker"


def speech_text_topic(user_id: str) -> str:
    return f"interview/{user_id}/speech/text"


# ==============================
# gRPC / MQTT 준비
# ==============================

def create_grpc_stub():
    creds = grpc.ssl_channel_credentials()
    channel = grpc.secure_channel(DAGLO_SERVER, creds)
    stub = speech_pb2_grpc.SpeechStub(channel)
    metadata = (("authorization", f"Bearer {DAGLO_API_TOKEN}"),)
    print(f"[whisper_daglo_mic] gRPC channel ready. server={DAGLO_SERVER}")
    return channel, stub, metadata


def create_mqtt_client():
    client = mqtt.Client(
        client_id=MQTT_CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv5,
    )

    def on_connect(c, userdata, flags, reason_code, properties=None):
        print(f"[whisper_daglo_mic] Connected to MQTT broker: rc={reason_code}")
        if reason_code != 0:
            print("[whisper_daglo_mic] MQTT connection failed")

    client.on_connect = on_connect
    client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
    return client


# ==============================
# RecognitionConfig & 요청 제너레이터
# ==============================

def build_config() -> speech_pb2.RecognitionConfig:
    # client.py와 동일한 설정 (필요 시 vad, punctuation 옵션 등 추가 가능)
    return speech_pb2.RecognitionConfig(
        language_code="ko-KR",
        interim_results=True,  # 중간 결과도 받지만, 우리는 최종만 MQTT로 보냄
    )


def request_generator(audio_stream, stop_flag):
    """
    Daglo StreamingRecognize에 넘길 요청 제너레이터.
    - 첫 요청은 config
    - 이후는 마이크에서 읽은 audio_content
    """
    config = build_config()
    # 첫 번째 요청: 설정
    yield speech_pb2.StreamingRecognizeRequest(config=config)

    # 이후 요청: 오디오 스트리밍
    while not stop_flag["stop"]:
        data = audio_stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
        if not data:
            break
        yield speech_pb2.StreamingRecognizeRequest(audio_content=data)

    # 마지막 빈 요청으로 스트림 종료 (client.py와 동일)
    yield speech_pb2.StreamingRecognizeRequest()


# ==============================
# 메인 루프
# ==============================

def main():
    # Ctrl+C로 깔끔하게 종료하기 위한 플래그
    stop_flag = {"stop": False}

    def signal_handler(sig, frame):
        print("\n[whisper_daglo_mic] Ctrl+C 감지, 종료 중...")
        stop_flag["stop"] = True

    signal.signal(signal.SIGINT, signal_handler)

    # gRPC, MQTT, PyAudio 초기화
    channel, stub, metadata = create_grpc_stub()
    mqtt_client = create_mqtt_client()
    mqtt_client.loop_start()  # MQTT는 별도 스레드에서 네트워크 루프

    audio = pyaudio.PyAudio()
    stream = audio.open(
        format=FORMAT,
        channels=CHANNELS,
        rate=RATE,
        input=True,
        frames_per_buffer=CHUNK_SAMPLES,
    )
    print("[whisper_daglo_mic] Mic stream opened. 이제 말하면 됩니다.")

    # total_duration 기반으로 구간 길이 계산
    last_total_duration = 0.0

    try:
        while not stop_flag["stop"]:
            print("[whisper_daglo_mic] Opening StreamingRecognize session...")
            try:
                responses = stub.StreamingRecognize(
                    request_generator(stream, stop_flag),
                    metadata=metadata,
                )

                for response in responses:
                    if stop_flag["stop"]:
                        break

                    result = response.result
                    if not result:
                        continue

                    transcript = (result.transcript or "").strip()
                    if not transcript:
                        continue

                    if result.is_final:
                        print(f"[whisper_daglo_mic] FINAL: {transcript}")
                    else:
                        # 중간 결과는 그냥 콘솔에만 띄워둠
                        print(f"[whisper_daglo_mic] PARTIAL: {transcript}", end="\r")
                        continue

                    # 여기까지 왔으면 최종 결과 → speech_rate_worker에게 보내기
                    total_dur = float(response.total_duration or 0.0)
                    seg_dur = max(total_dur - last_total_duration, 0.1)
                    last_total_duration = total_dur

                    payload = {
                        "user_id": USER_ID,
                        "timestamp": time.time(),
                        "duration": seg_dur,
                        "text": transcript,
                    }
                    topic = speech_text_topic(USER_ID)
                    mqtt_client.publish(topic, json.dumps(payload, ensure_ascii=False))
                    print(
                        f"[whisper_daglo_mic] Published STT to {topic} "
                        f"(dur={seg_dur:.2f}s)"
                    )

                print("[whisper_daglo_mic] StreamingRecognize session closed by server.")

            except grpc.RpcError as e:
                # 네트워크 끊김 등 에러 나도 다시 붙어서 계속 할 수 있게
                print(f"[whisper_daglo_mic] gRPC error: {e.code()}, {e.details()}")
                time.sleep(1.0)
                last_total_duration = 0.0  # 새 세션 기준으로 초기화

    finally:
        print("[whisper_daglo_mic] Shutting down...")
        stop_flag["stop"] = True
        stream.stop_stream()
        stream.close()
        audio.terminate()
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        channel.close()
        print("[whisper_daglo_mic] Bye.")


if __name__ == "__main__":
    main()