# backend/speech_worker.py
"""
MQTT로 퍼블리시된 오디오 RMS(raw)를 구독해서
'말하기 구간(segments)'을 잡아주는 워커.

입력 토픽:
  interview/{user_id}/audio/raw

출력 토픽:
  interview/{user_id}/speech/segment
"""

import json
import time
from typing import Dict, Any

import paho.mqtt.client as mqtt

# --- MQTT 기본 설정 ---
BROKER = "localhost"
PORT = 1883
KEEPALIVE = 60

CLIENT_ID = "speech-segment-worker-v3"

# ====== 튜닝 포인트 ======
# 네 환경 기준 대략:
#  - 말할 때: rms ~ 2000~10000
#  - 주변 잡음: 수십~수백
RMS_THRESHOLD = 800.0      # 필요하면 500~1500 사이 조절

# 말하기 최소 지속 시간 (초) - 이보다 짧으면 노이즈로 간주해서 버림
MIN_SEGMENT_DURATION = 0.8

# 세그먼트 최대 길이(초) - 10초 이상이면 잘라냄
MAX_SEGMENT_DURATION = 10.0

# 각 사용자별 상태 저장
# sessions[user_id] = {
#   "state": "silent" or "speaking",
#   "segment_start": float | None,
#   "last_ts": float | None,
#   "max_rms": float
# }
sessions: Dict[str, Dict[str, Any]] = {}


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[speech_worker v3] Connected to MQTT broker rc={reason_code}")
    client.subscribe("interview/+/audio/raw")
    print("[speech_worker v3] Subscribed: interview/+/audio/raw")


def on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str)
    except Exception as e:
        print("[speech_worker v3] JSON decode error:", e)
        print("  topic:", msg.topic)
        print("  raw payload:", msg.payload[:100])
        return

    # topic 예: interview/test-user-1/audio/raw
    parts = msg.topic.split("/")
    if len(parts) < 3:
        print("[speech_worker v3] Unexpected topic format:", msg.topic)
        return

    _, user_id, _, *_ = parts  # interview / {user_id} / audio / raw

    timestamp = float(data.get("timestamp", time.time()))
    rms = float(data.get("rms", 0.0))

    # 사용자 상태 초기화
    if user_id not in sessions:
        sessions[user_id] = {
            "state": "silent",
            "segment_start": None,
            "last_ts": None,
            "max_rms": 0.0,
        }

    sess = sessions[user_id]

    # 현재 rms 기준으로 talking/silent 판정
    is_speaking = rms >= RMS_THRESHOLD
    prev_state = sess["state"]

    # ---- 상태 업데이트 ----
    if is_speaking:
        if prev_state == "silent":
            # 새 세그먼트 시작
            sess["state"] = "speaking"
            sess["segment_start"] = timestamp
            sess["last_ts"] = timestamp
            sess["max_rms"] = rms
            print(
                f"[speech_worker v3] [{user_id}] SPEECH START at {timestamp:.3f} (rms={rms:.1f})"
            )
        else:
            # 말하는 중 계속
            sess["last_ts"] = timestamp
            if rms > sess["max_rms"]:
                sess["max_rms"] = rms

    else:
        # silent 상태
        if prev_state == "speaking":
            # 말이 끊긴 시점 → 세그먼트 종료
            sess["state"] = "silent"
            end_ts = sess["last_ts"] if sess["last_ts"] is not None else timestamp
            start_ts = sess["segment_start"] or timestamp
            duration = max(0.0, end_ts - start_ts)

            # 0.8초 미만이면 그냥 노이즈로 버림
            if duration < MIN_SEGMENT_DURATION:
                print(
                    f"[speech_worker v3] [{user_id}] SHORT noise ignored "
                    f"(dur={duration:.2f}s, max_rms={sess['max_rms']:.1f})"
                )
            else:
                # 너무 길면 잘라냄
                if duration > MAX_SEGMENT_DURATION:
                    duration = MAX_SEGMENT_DURATION

                segment = {
                    "user_id": user_id,
                    "start_ts": start_ts,
                    "end_ts": start_ts + duration,
                    "duration": duration,
                    "max_rms": sess["max_rms"],
                }

                segment_topic = f"interview/{user_id}/speech/segment"
                client.publish(segment_topic, json.dumps(segment, ensure_ascii=False))
                print(
                    f"[speech_worker v3] [{user_id}] SEGMENT "
                    f"{start_ts:.2f} ~ {start_ts + duration:.2f} "
                    f"(dur={duration:.2f}s, max_rms={sess['max_rms']:.1f})"
                )

            # 세그먼트 정보 초기화
            sess["segment_start"] = None
            sess["last_ts"] = None
            sess["max_rms"] = 0.0
        else:
            # silent → silent : 아무 작업 없음
            pass


def main():
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, KEEPALIVE)
    print("[speech_worker v3] MQTT client connecting...")

    client.loop_forever()


if __name__ == "__main__":
    main()