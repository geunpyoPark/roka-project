# speech_rate_worker.py
"""
MQTT로 들어오는 'speech/text' 메시지를 받아서
 - kiwi로 문장을 쪼개고
 - 말하는 데 걸린 시간으로 말속도 계산하고
 - 결과를 'speech/analysis' 토픽으로 다시 publish

토픽 구조(입력):
  interview/{user_id}/speech/text

payload 예시(whisper_worker에서 보낼 예정):
  {
    "user_id": "test-user-1",
    "start_ts": 1763654900.12,
    "end_ts": 1763654903.45,
    "text": "자기소개를 하겠습니다. 저는 ..."
  }

출력 토픽:
  interview/{user_id}/speech/analysis
"""

import json
import time
import math
import paho.mqtt.client as mqtt
from kiwipiepy import Kiwi

BROKER_HOST = "localhost"
BROKER_PORT = 1883

# 사용자 여러 명을 지원하려고 +로 와일드카드
SUB_TOPIC = "interview/+/speech/text"

kiwi = Kiwi()


def classify_speed(chars_per_sec: float) -> str:
    """
    말속도 레벨 분류 (대략적인 기준)
    - slow:  <= 3 글자/초
    - normal: 3 ~ 7 글자/초
    - fast:  > 7 글자/초
    """
    if chars_per_sec <= 3.0:
        return "slow"
    elif chars_per_sec <= 7.0:
        return "normal"
    else:
        return "fast"


def analyze_text(text: str, duration: float):
    """
    kiwi로 문장 단위로 쪼개고, 전체 글자수/토큰 정보, 말속도 계산
    """
    text = text.strip()
    if not text:
        return None

    # 문장 단위 분리
    sents = kiwi.split_into_sents(text)
    # 형태소 토큰
    tokens = kiwi.tokenize(text)

    # 공백/줄바꿈 제거한 "말한 글자 수" 기준
    no_space = "".join(ch for ch in text if not ch.isspace())
    num_chars = len(no_space)

    # 토큰 개수
    num_tokens = len(tokens)

    # duration이 0 또는 매우 작으면 안전하게 1초로 보정
    if duration <= 0.1:
        duration = 1.0

    chars_per_sec = num_chars / duration
    tokens_per_sec = num_tokens / duration
    speed_level = classify_speed(chars_per_sec)

    # 문장별로도 간단히 정보 남겨보자
    chunks = []
    for s in sents:
        sent_text = s.text.strip()
        if not sent_text:
            continue
        sent_no_space = "".join(ch for ch in sent_text if not ch.isspace())
        chunks.append(
            {
                "text": sent_text,
                "num_chars": len(sent_no_space),
            }
        )

    return {
        "text": text,
        "duration": duration,
        "num_chars": num_chars,
        "num_tokens": num_tokens,
        "chars_per_sec": chars_per_sec,
        "tokens_per_sec": tokens_per_sec,
        "speed_level": speed_level,
        "chunks": chunks,
    }


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[speech_rate_worker] Connected to MQTT broker: rc={reason_code}")
    if reason_code == 0:
        client.subscribe(SUB_TOPIC)
        print(f"[speech_rate_worker] Subscribed to {SUB_TOPIC}")
    else:
        print("[speech_rate_worker] Connection failed")


def on_message(client, userdata, msg):
    try:
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)

        user_id = data.get("user_id", "unknown")
        text = data.get("text", "").strip()

        start_ts = data.get("start_ts")
        end_ts = data.get("end_ts")

        # duration 계산
        if isinstance(start_ts, (int, float)) and isinstance(end_ts, (int, float)):
            duration = max(0.0, end_ts - start_ts)
        else:
            # timestamp가 없으면 길이 기반 대충 추정해도 되지만,
            # 지금은 그냥 duration=None으로 두고 analyze_text에서 1초로 보정
            duration = 0.0

        print(f"[speech_rate_worker] [{user_id}] TEXT: {text!r}")

        result = analyze_text(text, duration)
        if result is None:
            print(f"[speech_rate_worker] [{user_id}] Empty text, skip.")
            return

        # 결과에 user_id, start_ts, end_ts도 같이 실어 보내기
        result_payload = {
            "user_id": user_id,
            "start_ts": start_ts,
            "end_ts": end_ts,
            **result,
        }

        out_topic = f"interview/{user_id}/speech/analysis"
        client.publish(out_topic, json.dumps(result_payload, ensure_ascii=False))
        print(
            f"[speech_rate_worker] Published analysis to {out_topic} "
            f"(chars/sec={result['chars_per_sec']:.2f}, level={result['speed_level']})"
        )

    except Exception as e:
        print("[speech_rate_worker] on_message error:", e)


def main():
    client_id = f"speech-rate-worker-{int(time.time())}"

    # ✅ callback_api_version을 정식 enum으로 지정 (VERSION2 권장)
    client = mqtt.Client(
        mqtt.CallbackAPIVersion.VERSION2,
        client_id=client_id,
        protocol=mqtt.MQTTv5,
    )

    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    print("[speech_rate_worker] Started. Waiting for messages...")
    client.loop_forever()


if __name__ == "__main__":
    main()