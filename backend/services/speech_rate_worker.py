"""
backend/services/speech_rate_worker.py

- Whisper 워커가 퍼블리시하는
    interview/{user_id}/speech/text
  을 받아서

  1) 말 속도(분당 단어 수 등) 계산
  2) "너무 빠름 / 적당함" 같은 라벨링
  3) 결과를 interview/{user_id}/speech/analysis 로 퍼블리시

- 너무 짧거나, 헛소리 가능성이 높은 세그먼트는 필터링한다.
"""

import json
import time
from typing import Dict, Any

import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
KEEPALIVE = 60

CLIENT_ID = "speech-rate-worker"

SUB_TOPIC_TEXT = "interview/+/speech/text"


def analysis_topic(user_id: str) -> str:
    return f"interview/{user_id}/speech/analysis"


# ==============================
# 말속도 계산 유틸
# ==============================

def count_words_rough(text: str) -> int:
    """
    한국어+영어 섞여 있는 문장을 대충 '단어 수'로 세는 함수.
    - 공백으로 먼저 자르고, 너무 짧은 토큰은 묶어서 1 단어로 보정.
    """
    text = text.strip()
    if not text:
        return 0

    tokens = text.split()
    if not tokens:
        # 공백이 거의 없으면 글자수 기반으로 대충 환산
        # (한글 5~6글자 ≈ 1 단어 정도로 가정)
        return max(1, len(text) // 5)

    # 공백 단위 토큰 수에 가중치 약간 더해서 반환
    return max(1, len(tokens))


def label_speed(wpm: float) -> str:
    """
    WPM(단어/분)에 따라 말속도 라벨을 단순하게 나눈다.
    실제 인터뷰에서는 값만 써도 되고, 라벨은 적당히 조정하면 된다.
    """
    if wpm < 80:
        return "조금 느림"
    elif wpm < 160:
        return "적당함"
    elif wpm < 220:
        return "조금 빠름"
    else:
        return "너무 빠름"


# ==============================
# MQTT 콜백
# ==============================

def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[speech_rate_worker] Connected: rc={reason_code}")
    client.subscribe(SUB_TOPIC_TEXT)
    print(f"[speech_rate_worker] Subscribed to {SUB_TOPIC_TEXT}")


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        parts = topic.split("/")
        if len(parts) < 4:
            print("[speech_rate_worker] Invalid topic:", topic)
            return
        _, user_id, category, subtopic, *rest = parts
        if category != "speech" or subtopic != "text":
            return

        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str)

        text = (data.get("text") or "").strip()
        duration = float(data.get("duration") or 0.0)

        # duration 이 0 이거나 너무 작으면, 최소 0.5초로 보정
        if duration < 0.5:
            duration = 0.5

        if not text:
            # 빈 텍스트는 바로 버리기
            print(
                f"[speech_rate_worker] Empty text segment ignored "
                f"(user={user_id}, dur={duration:.2f}s)"
            )
            return

        # 너무 짧은 텍스트(헛소리 가능성 높음)는 버리기
        if len(text) < 3:
            print(
                f"[speech_rate_worker] Too short text ignored "
                f"(user={user_id}, dur={duration:.2f}s, text='{text}')"
            )
            return

        # 단어 수 / 분당 단어 수 계산
        word_count = count_words_rough(text)
        wpm = word_count / (duration / 60.0)  # 단어/분
        cps = len(text) / duration           # 글자/초

        # 말속도 라벨
        speed_label = label_speed(wpm)

        # 말도 안 되는 값(예: 400 WPM 이상)은 헛소리거나 duration 추정이 잘못된 것으로 간주하고 버림
        if wpm > 400:
            print(
                f"[speech_rate_worker] Unrealistic WPM ignored "
                f"(user={user_id}, WPM={wpm:.1f}, dur={duration:.2f}s, text='{text[:20]}...')"
            )
            return

        result = {
            "user_id": user_id,
            "duration": duration,
            "words_per_min": wpm,
            "chars_per_sec": cps,
            "speed_label": speed_label,
            "text": text,
            "timestamp": time.time(),
        }

        out_topic = analysis_topic(user_id)
        client.publish(out_topic, json.dumps(result, ensure_ascii=False))
        print(
            f"[speech_rate_worker][{user_id}] dur={duration:.2f}s, "
            f"WPM={wpm:.1f}, label={speed_label}, text='{text}'"
        )

    except Exception as e:
        print(f"[speech_rate_worker] on_message error on topic {topic}: {e}")


def main():
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv5,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, KEEPALIVE)
    print("[speech_rate_worker] Started. Waiting for STT text...")
    client.loop_forever()


if __name__ == "__main__":
    main()