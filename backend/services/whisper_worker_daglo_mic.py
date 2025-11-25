# backend/services/whisper_worker_daglo_mic.py

"""
Daglo Realtime STT (마이크 버전) + MQTT + Transcript 연동

- 마이크에서 16kHz PCM을 읽어서 Daglo gRPC StreamingRecognize로 보냄
- Daglo에서 최종 STT 문장이 나오면:
    1) MQTT: interview/{user_id}/speech/text 로 퍼블리시
    2) HTTP: POST /transcript/{user_id} 로 전송해서 프론트 TranscriptPanel에 쌓이게 함

환경 변수:
  - DAGLO_API_TOKEN   : Daglo API 토큰 (필수)
  - DAGLO_SERVER      : 기본 apis.daglo.ai
  - INTERVIEW_USER_ID : 기본 "test-user-1"
  - BACKEND_BASE      : 기본 "http://127.0.0.1:8000"
"""

import os
import time
import json
import queue
import threading
from typing import Optional

import grpc
import paho.mqtt.client as mqtt
import pyaudio
import requests

from backend.services.daglo import speech_pb2, speech_pb2_grpc


# ==============================
# 환경 설정
# ==============================

DAGLO_SERVER = os.getenv("DAGLO_SERVER", "apis.daglo.ai")
DAGLO_API_TOKEN = os.getenv("DAGLO_API_TOKEN")
if not DAGLO_API_TOKEN:
  raise RuntimeError(
      "[whisper_daglo_mic] 환경변수 DAGLO_API_TOKEN 이 설정되어 있지 않습니다. "
      'export DAGLO_API_TOKEN="발급받은_토큰" 으로 설정해 주세요.'
  )

USER_ID = os.getenv("INTERVIEW_USER_ID", "test-user-1")
BACKEND_BASE = os.getenv("BACKEND_BASE", "http://127.0.0.1:8000")

# Daglo 오디오 설정 (16k, mono, int16)
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # int16
CHUNK_SEC = 0.25
CHUNK_SAMPLES = int(SAMPLE_RATE * CHUNK_SEC)  # 4000
CHUNK_BYTES = CHUNK_SAMPLES * SAMPLE_WIDTH    # 8000

# MQTT 설정
BROKER_HOST = "localhost"
BROKER_PORT = 1883
KEEPALIVE = 60
MQTT_CLIENT_ID = "whisper-daglo-mic"
MQTT_TOPIC_TEXT = f"interview/{USER_ID}/speech/text"


# ==============================
# 전역 오브젝트
# ==============================

audio_queue: "queue.Queue[Optional[bytes]]" = queue.Queue()
stop_flag = threading.Event()

mqtt_client: Optional[mqtt.Client] = None


# ==============================
# Transcript API helper
# ==============================

def push_transcript_segment(
    text: str,
    speaker: str = "candidate",
    start_sec: Optional[float] = None,
    end_sec: Optional[float] = None,
) -> None:
  """
  STT 한 턴을 백엔드 /transcript/{user_id} 로 보내는 함수.
  지금은 speaker="candidate" 고정.
  """
  text = (text or "").strip()
  if not text:
      return

  payload: dict = {
      "speaker": speaker,
      "text": text,
  }
  if start_sec is not None:
      payload["start_sec"] = float(start_sec)
  if end_sec is not None:
      payload["end_sec"] = float(end_sec)

  url = f"{BACKEND_BASE}/transcript/{USER_ID}"
  try:
      resp = requests.post(url, json=payload, timeout=1.0)
      if not resp.ok:
          print(f"[transcript] POST {url} failed: {resp.status_code} {resp.text}")
  except Exception as e:
      print(f"[transcript] POST error: {e}")


# ==============================
# MQTT 초기화
# ==============================

def init_mqtt() -> mqtt.Client:
  def on_connect(client, userdata, flags, reason_code, properties=None):
      print(f"[whisper_daglo_mic] MQTT connected rc={reason_code}")

  client = mqtt.Client(
      client_id=MQTT_CLIENT_ID,
      callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
      protocol=mqtt.MQTTv5,
  )
  client.on_connect = on_connect
  client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
  client.loop_start()
  print(f"[whisper_daglo_mic] MQTT client started. broker={BROKER_HOST}:{BROKER_PORT}")
  return client


def publish_stt_json(text: str, duration: float) -> None:
  """
  speech_rate_worker 에서 쓰는 포맷으로 MQTT 퍼블리시.
  """
  if mqtt_client is None:
      return
  payload = {
      "user_id": USER_ID,
      "timestamp": time.time(),
      "duration": float(duration),
      "text": text,
  }
  mqtt_client.publish(MQTT_TOPIC_TEXT, json.dumps(payload, ensure_ascii=False))
  print(
      f"[whisper_daglo_mic] Published STT to {MQTT_TOPIC_TEXT} "
      f"(dur={duration:.2f}s, text={text!r})"
  )


# ==============================
# 마이크 캡처 (PyAudio)
# ==============================

def mic_thread():
  pa = pyaudio.PyAudio()
  stream = pa.open(
      format=pyaudio.paInt16,
      channels=CHANNELS,
      rate=SAMPLE_RATE,
      input=True,
      frames_per_buffer=CHUNK_SAMPLES,
  )
  print("[whisper_daglo_mic] 마이크 캡처 시작")

  try:
      while not stop_flag.is_set():
          data = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
          audio_queue.put(data)
  except Exception as e:
      print("[whisper_daglo_mic] mic_thread error:", e)
  finally:
      stream.stop_stream()
      stream.close()
      pa.terminate()
      audio_queue.put(None)  # 스트림 종료 알림
      print("[whisper_daglo_mic] 마이크 캡처 종료")


# ==============================
# Daglo gRPC 설정
# ==============================

def build_config() -> speech_pb2.RecognitionConfig:
  return speech_pb2.RecognitionConfig(
      language_code="ko-KR",
      interim_results=True,
  )


def request_generator():
  """
  gRPC StreamingRecognize용 request generator.
  첫 요청은 config, 이후 audio_content.
  """
  config = build_config()
  # 첫 요청: 설정
  yield speech_pb2.StreamingRecognizeRequest(config=config)

  # 이후: 오디오
  while True:
      chunk = audio_queue.get()
      if chunk is None:
          break
      yield speech_pb2.StreamingRecognizeRequest(audio_content=chunk)

  # 마지막 빈 요청
  yield speech_pb2.StreamingRecognizeRequest()


def main():
  global mqtt_client

  # MQTT
  mqtt_client = init_mqtt()

  # gRPC 채널
  creds = grpc.ssl_channel_credentials()
  channel = grpc.secure_channel(DAGLO_SERVER, creds)
  stub = speech_pb2_grpc.SpeechStub(channel)
  metadata = (("authorization", f"Bearer {DAGLO_API_TOKEN}"),)

  # 마이크 쓰레드 시작
  th = threading.Thread(target=mic_thread, daemon=True)
  th.start()

  print("[whisper_daglo_mic] Daglo STT 스트리밍 시작. Ctrl+C 로 종료하세요.")

  last_total_duration = 0.0

  try:
      responses = stub.StreamingRecognize(request_generator(), metadata=metadata)
      for resp in responses:
          result = resp.result
          if not result:
              continue

          transcript = (result.transcript or "").strip()
          if not transcript:
              continue

          if result.is_final:
              # Daglo가 주는 total_duration 기준으로 segment 길이 추정
              total_dur = float(getattr(resp, "total_duration", 0.0) or 0.0)
              seg_dur = max(total_dur - last_total_duration, 0.1)
              last_total_duration = total_dur

              print(f"[whisper_daglo_mic] FINAL: {transcript}")

              # 1) MQTT로 STT 결과 전송 (speech_rate_worker용)
              publish_stt_json(transcript, seg_dur)

              # 2) Transcript API로도 전송 (화자: candidate)
              push_transcript_segment(
                  text=transcript,
                  speaker="candidate",
                  # 필요하면 시간 정보 넣을 수 있음
                  start_sec=None,
                  end_sec=None,
              )
          else:
              # 부분 결과 로그만 (원하면 주석 처리 가능)
              print(f"[whisper_daglo_mic] PARTIAL: {transcript}", end="\r")

  except KeyboardInterrupt:
      print("\n[whisper_daglo_mic] KeyboardInterrupt -> 종료 요청")
  except grpc.RpcError as e:
      print("[whisper_daglo_mic] gRPC error:", e.code(), e.details())
  finally:
      stop_flag.set()
      th.join(timeout=1.0)
      channel.close()
      if mqtt_client is not None:
          mqtt_client.loop_stop()
          mqtt_client.disconnect()
      print("[whisper_daglo_mic] 종료 완료")


if __name__ == "__main__":
  main()