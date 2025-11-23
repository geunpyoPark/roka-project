# backend/services/speech_rate_worker.py

"""
speech_rate_worker

입력 토픽:
  interview/{user_id}/speech/text
    - whisper_worker에서 퍼블리시하는 STT 결과 JSON:
      {
        "user_id": "test-user-1",
        "timestamp": 1234567890.0,
        "duration": 3.0,         # 이 발화 구간 길이(초)
        "text": "구독과 좋아요 부탁드려요!"
      }

출력 토픽:
  interview/{user_id}/speech/analysis
    - 말속도 분석 + 피드백을 담은 JSON:
      {
        "user_id": "test-user-1",
        "timestamp": 1234567890.0,
        "duration": 3.0,
        "wpm": 120.0,
        "label": "조금 빠름",
        "text": "구독과 좋아요 부탁드려요!",
        "feedback": "전달력은 괜찮지만, 면접에서는 지금보다 10~20%만 천천히 말하면 더 안정적으로 들려요."
      }
"""

import json
import time
from typing import Dict, Any

import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT = 1883
KEEPALIVE = 60

IN_TOPIC = "interview/+/speech/text"
CLIENT_ID = "speech-rate-worker"


def speech_analysis_topic(user_id: str) -> str:
    return f"interview/{user_id}/speech/analysis"


# ==============================
#  말속도(WPM) 계산 & 라벨링
# ==============================

def calc_wpm(text: str, duration: float) -> float:
    """
    WPM(Word Per Minute) 계산.
    - 한국어라서 '단어 수'는 공백 기준 어절 개수로 정의.
    - duration: 이 발화 구간 길이(초)
    """
    duration = max(duration, 0.1)  # 0 나누기 방지용

    # 공백 기준 어절 수
    tokens = [t for t in text.strip().split() if t]
    word_count = len(tokens)

    # 분당 단어 수 = 단어수 * (60 / 초)
    wpm = word_count * (60.0 / duration)
    return round(wpm, 1)


def make_label(wpm: float) -> str:
    """
    WPM 값에 따라 말속도 라벨 정의.
    (면접 기준으로 설정)
    """
    if wpm < 70:
        return "너무 느림"
    elif 70 <= wpm < 110:
        return "조금 느림"
    elif 110 <= wpm < 150:
        return "적당함"
    elif 150 <= wpm < 190:
        return "조금 빠름"
    else:
        return "너무 빠름"


def make_feedback(label: str, wpm: float, text: str) -> str:
    """
    라벨 + WPM에 따라 면접 스타일 피드백 문장 생성.
    """
    text_len = len(text.strip())

    # 아주 짧은 추임새/단답은 가벼운 코멘트만
    if text_len <= 3:
        return "짧은 추임새라서 말 속도는 크게 신경 쓰지 않아도 괜찮아요."

    if label == "너무 느림":
        return (
            "전달이 다소 답답하게 느껴질 수 있는 속도예요. "
            "문장을 조금 더 끊어 말하되, 전체적으로는 지금보다 20~30% 정도 빠르게 말해보면 좋겠어요."
        )
    elif label == "조금 느림":
        return (
            "편안한 대화 속도이지만, 면접에서는 약간 늘어지는 인상을 줄 수 있어요. "
            "지금보다 10~20% 정도 속도를 올리고, 키워드에 힘을 주면 더 설득력 있어 보입니다."
        )
    elif label == "적당함":
        return (
            "면접용으로 아주 좋은 말하기 속도예요. "
            "지금처럼 문장 사이에 잠깐씩 쉬어주면서, 핵심 단어에만 조금 더 힘을 실어주면 더 좋겠습니다."
        )
    elif label == "조금 빠름":
        return (
            "조금 빠르게 말하는 편이라, 긴장한 느낌을 줄 수 있어요. "
            "문장 끝에서 0.5초 정도 숨을 고르는 습관을 들이면, 같은 속도에서도 훨씬 안정적으로 들립니다."
        )
    elif label == "너무 빠름":
        return (
            "상대가 내용을 따라가기 어려울 수 있는 속도예요. "
            "한 문장에 들어가는 단어 수를 줄이고, 문장 끝마다 짧게 멈추는 연습을 해보면 큰 도움이 될 거예요."
        )

    # 혹시 모를 기본값
    return "전체적인 말하기 흐름은 괜찮아요. 중요한 문장마다 속도와 멈춤을 조금만 더 의식해 보세요."


# ==============================
#  MQTT 콜백
# ==============================

def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[speech_rate_worker] Connected: rc={reason_code}")
    if reason_code == 0:
        client.subscribe(IN_TOPIC)
        print(f"[speech_rate_worker] Subscribed to {IN_TOPIC}")
    else:
        print("[speech_rate_worker] MQTT connection failed")


def on_message(client, userdata, msg):
    topic = msg.topic
    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print(f"[speech_rate_worker] Invalid JSON payload: {e}")
        return

    parts = topic.split("/")
    # interview / {user_id} / speech / text
    if len(parts) < 4:
        print("[speech_rate_worker] Unexpected topic:", topic)
        return

    _, user_id, category, subtopic, *rest = parts
    if not (category == "speech" and subtopic == "text"):
        print("[speech_rate_worker] Ignore topic:", topic)
        return

    text = (payload.get("text") or "").strip()
    duration = float(payload.get("duration") or 0.0)

    # 너무 짧은 발화는 분석 스킵 (ex. '음', '어', '네')
    if len(text) <= 1:
        print(f"[speech_rate_worker] Too short text ignored (user={user_id}, dur={duration:.2f}s, text='{text}')")
        return

    wpm = calc_wpm(text, duration)
    label = make_label(wpm)
    feedback = make_feedback(label, wpm, text)

    out_payload: Dict[str, Any] = {
        "user_id": user_id,
        "timestamp": time.time(),
        "duration": duration,
        "wpm": wpm,
        "label": label,
        "text": text,
        "feedback": feedback,
    }

    out_topic = speech_analysis_topic(user_id)
    client.publish(out_topic, json.dumps(out_payload, ensure_ascii=False))
    print(
        f"[speech_rate_worker][{user_id}] dur={duration:.2f}s, WPM={wpm}, "
        f"label={label}, text='{text}'"
    )


# ==============================
#  main
# ==============================

def main():
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        protocol=mqtt.MQTTv5,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
    print("[speech_rate_worker] Started. Waiting for STT text...")

    client.loop_forever()


if __name__ == "__main__":
    main()