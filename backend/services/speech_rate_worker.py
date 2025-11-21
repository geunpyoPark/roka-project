# backend/services/speech_rate_worker.py

"""
STT 텍스트를 받아서 말 속도(WPM)를 계산하고
MQTT로 분석 결과를 퍼블리시하는 워커.

입력 토픽:
  interview/{user_id}/speech/text

출력 토픽:
  interview/{user_id}/speech/analysis
"""

import json
import time
from typing import Dict, Any

import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
KEEPALIVE = 60

CLIENT_ID = "speech-rate-worker"

# STT 결과가 오는 토픽 패턴
SUB_TOPIC = "interview/+/speech/text"


def analysis_topic(user_id: str) -> str:
    return f"interview/{user_id}/speech/analysis"


# ---------------- 유틸 ----------------

def compute_metrics(text: str, duration: float) -> Dict[str, Any]:
    """
    텍스트와 구간 길이(초)를 가지고 기본 지표 계산.
    duration 이 너무 작거나 0이면 최소 0.5초로 보정.
    말도 안 되게 큰 duration(예: 수백 초)는 30초로 클램프.
    """
    if duration <= 0:
        duration = 0.5
    if duration > 30.0:
        duration = 30.0

    clean = text.strip()
    # 공백 제외한 글자 수
    num_chars = len(clean.replace(" ", ""))
    # 단어 수(공백 기준)
    num_words = len(clean.split()) if clean else 0

    chars_per_sec = num_chars / duration if duration > 0 else 0.0
    words_per_sec = num_words / duration if duration > 0 else 0.0
    words_per_min = words_per_sec * 60.0

    # 한국어 면접 기준 대략적인 속도 레이블 (임시값, 나중에 튜닝)
    if words_per_min < 80:
        label = "조금 느림"
    elif words_per_min < 140:
        label = "적당함"
    elif words_per_min < 200:
        label = "조금 빠름"
    else:
        label = "너무 빠름"

    return {
        "num_chars": num_chars,
        "num_words": num_words,
        "chars_per_sec": chars_per_sec,
        "words_per_sec": words_per_sec,
        "words_per_min": words_per_min,
        "speed_label": label,
    }


# ---------------- MQTT 콜백 ----------------

def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[speech_rate_worker] Connected: rc={reason_code}")
    client.subscribe(SUB_TOPIC)
    print(f"[speech_rate_worker] Subscribed to {SUB_TOPIC}")


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        parts = topic.split("/")
        # interview / {user_id} / speech / text
        if len(parts) < 4:
            print("[speech_rate_worker] Unexpected topic:", topic)
            return

        _, user_id, category, subtopic, *rest = parts
        if category != "speech" or subtopic != "text":
            print("[speech_rate_worker] Ignore topic:", topic)
            return

        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str)

        text = (data.get("text") or "").strip()
        start_ts = float(data.get("start_ts", time.time()))
        end_ts = float(data.get("end_ts", start_ts))
        duration = float(data.get("duration", max(end_ts - start_ts, 0.5)))

        # 🔽 최소 필터: 텍스트가 아예 없으면 분석해도 의미가 없으니 조용히 무시
        if not text:
            print(
                f"[speech_rate_worker] Empty text segment ignored "
                f"(user={user_id}, dur={duration:.2f}s)"
            )
            return

        metrics = compute_metrics(text, duration)
        wpm = metrics["words_per_min"]
        label = metrics["speed_label"]

        out_payload: Dict[str, Any] = {
            "user_id": user_id,
            "start_ts": start_ts,
            "end_ts": end_ts,
            "duration": duration,
            "text": text,
            **metrics,
        }

        out_topic = analysis_topic(user_id)
        client.publish(out_topic, json.dumps(out_payload, ensure_ascii=False))

        print(
            f"[speech_rate_worker][{user_id}] dur={duration:.2f}s, "
            f"WPM={wpm:.1f}, label={label}, text='{text}'"
        )

    except Exception as e:
        print(f"[speech_rate_worker] on_message error on topic {topic}: {e}")


# ---------------- main ----------------

def main():
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, KEEPALIVE)
    print("[speech_rate_worker] Started. Waiting for STT text...")

    client.loop_forever()


if __name__ == "__main__":
    main()