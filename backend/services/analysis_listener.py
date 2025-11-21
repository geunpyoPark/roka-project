# backend/services/analysis_listener.py

"""
speech_rate_worker, whisper_worker가 퍼블리시하는

  interview/{user_id}/speech/analysis
  interview/{user_id}/speech/text

를 MQTT로 구독해서,
backend/services/analysis_cache.py 의
  update_analysis / update_text
을 호출해 메모리에 캐싱하는 리스너.
"""

import json
from typing import Any

import paho.mqtt.client as mqtt
from backend.services.analysis_cache import (
    update_analysis,
    update_text,
)

BROKER_HOST = "localhost"
BROKER_PORT = 1883

SUB_TOPIC_ANALYSIS = "interview/+/speech/analysis"
SUB_TOPIC_TEXT = "interview/+/speech/text"

_mqtt_client: mqtt.Client | None = None


def _on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[analysis_listener] Connected to MQTT broker: rc={reason_code}")
    if reason_code == 0:
        client.subscribe(SUB_TOPIC_ANALYSIS)
        client.subscribe(SUB_TOPIC_TEXT)
        print(f"[analysis_listener] Subscribed to {SUB_TOPIC_ANALYSIS}")
        print(f"[analysis_listener] Subscribed to {SUB_TOPIC_TEXT}")
    else:
        print("[analysis_listener] MQTT connection failed")


def _on_message(client, userdata, msg):
    try:
        topic = msg.topic  # 예: interview/test-user-1/speech/analysis
        parts = topic.split("/")
        if len(parts) < 4:
            print("[analysis_listener] Invalid topic:", topic)
            return

        user_id = parts[1]
        category = parts[2]   # "speech"
        subtopic = parts[3]   # "analysis" or "text"

        payload_str = msg.payload.decode("utf-8")
        data: dict[str, Any] = json.loads(payload_str)

        if category == "speech" and subtopic == "analysis":
            update_analysis(user_id, data)
            print(
                f"[analysis_listener] Cached analysis for {user_id}: "
                f"speed={data.get('speed_label')}"
            )
        elif category == "speech" and subtopic == "text":
            update_text(user_id, data)
            txt_preview = (data.get("text") or "")[:20]
            print(
                f"[analysis_listener] Cached text for {user_id}: '{txt_preview}'"
            )
        else:
            print("[analysis_listener] Unknown topic:", topic)

    except Exception as e:
        print("[analysis_listener] on_message error:", e)
        print("  topic:", msg.topic)
        print("  payload:", msg.payload[:200])


def start_analysis_listener():
    """
    backend.main.startup_event()에서 한 번 호출하면 됨.
    별도 스레드(loop_start)로 MQTT를 돌리면서
    analysis_cache에 최신 분석/텍스트를 계속 업데이트.
    """
    global _mqtt_client
    if _mqtt_client is not None:
        # 이미 시작되어 있으면 두 번 시작하지 않음
        return

    client = mqtt.Client(
        client_id=f"analysis-listener-{id(object())}",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv5,
    )
    client.on_connect = _on_connect
    client.on_message = _on_message

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()

    _mqtt_client = client
    print("[analysis_listener] MQTT loop started.")