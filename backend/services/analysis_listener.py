# backend/services/analysis_listener.py

"""
speech_rate_worker 와 whisper_worker 가 퍼블리시하는 결과를 구독해서
메모리에 저장해 두는 리스너.

입력 토픽:
  - interview/{user_id}/speech/analysis  : 말속도/WPM 분석 결과
  - interview/{user_id}/speech/text      : STT 텍스트 결과
"""

import json
import threading
import paho.mqtt.client as mqtt

from backend.services.analysis_cache import (
    update_analysis,
    update_text,
)

BROKER_HOST = "localhost"
BROKER_PORT = 1883
KEEPALIVE = 60

# 두 토픽 모두 구독
ANALYSIS_TOPIC = "interview/+/speech/analysis"
TEXT_TOPIC = "interview/+/speech/text"
CLIENT_ID = "analysis-listener"


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[analysis_listener] Connected: rc={reason_code}")
    if reason_code == 0:
        # 두 토픽 모두 subscribe
        client.subscribe(ANALYSIS_TOPIC)
        client.subscribe(TEXT_TOPIC)
        print(f"[analysis_listener] Subscribed to {ANALYSIS_TOPIC} and {TEXT_TOPIC}")
    else:
        print("[analysis_listener] MQTT connection failed")


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print(f"[analysis_listener] Invalid JSON payload: {e}")
        return

    parts = topic.split("/")
    # interview / {user_id} / speech / {analysis|text}
    if len(parts) < 4:
        print("[analysis_listener] Unexpected topic:", topic)
        return

    _, user_id, category, subtopic, *rest = parts

    if category != "speech":
        print("[analysis_listener] Ignore non-speech topic:", topic)
        return

    # 말속도 분석 결과
    if subtopic == "analysis":
        update_analysis(user_id, payload)
        print(
            f"[analysis_listener] Updated ANALYSIS for user={user_id}: "
            f"text='{payload.get('text')}', wpm={payload.get('wpm')}, "
            f"label={payload.get('label')}"
        )

    # STT 텍스트 결과
    elif subtopic == "text":
        update_text(user_id, payload)
        print(
            f"[analysis_listener] Updated TEXT for user={user_id}: "
            f"text='{payload.get('text')}'"
        )

    else:
        print("[analysis_listener] Ignore subtopic:", subtopic)


def start_analysis_listener():
    """
    FastAPI startup 이벤트에서 호출.
    별도 스레드로 MQTT loop를 돌린다.
    """
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv5,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
    print("[analysis_listener] MQTT client started.")

    th = threading.Thread(target=client.loop_forever, daemon=True)
    th.start()