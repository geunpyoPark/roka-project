# backend/speech_worker.py
"""
MQTT로 퍼블리시된 오디오 RMS(raw) 를 구독해서
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

CLIENT_ID = "speech-segment-worker"

# 말하기/침묵 판정 임계값 (필요하면 나중에 조절)
RMS_THRESHOLD = 50.0
# 말하기 최소 지속 시간 (초) - 이보다 짧으면 그냥 잡음으로 간주
MIN_SEGMENT_DURATION = 0.3


# 각 사용자별 상태를 저장할 딕셔너리
# sessions[user_id] = {
#   "state": "silent" or "speaking",
#   "segment_start": float | None,
#   "last_ts": float | None,
#   "max_rms": float
# }
sessions: Dict[str, Dict[str, Any]] = {}


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[speech_worker] Connected to MQTT broker rc={reason_code}")

    # interview/+/audio/raw 구독
    client.subscribe("interview/+/audio/raw")
    print("[speech_worker] Subscribed: interview/+/audio/raw")


def on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str)
    except Exception as e:
        print("[speech_worker] JSON decode error:", e)
        print("  topic:", msg.topic)
        print("  raw payload:", msg.payload[:100])
        return

    # topic 예: interview/test-user-1/audio/raw
    parts = msg.topic.split("/")
    if len(parts) < 3:
        print("[speech_worker] Unexpected topic format:", msg.topic)
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
                f"[speech_worker] [{user_id}] SPEECH START at {timestamp:.3f} (rms={rms:.1f})"
            )
        else:
            # 말하는 중 계속
            sess["last_ts"] = timestamp
            if rms > sess["max_rms"]:
                sess["max_rms"] = rms

    else:
        # silent
        if prev_state == "speaking":
            # 바로 말이 끊긴 시점 → 세그먼트 종료로 볼 수 있음
            sess["state"] = "silent"
            end_ts = sess["last_ts"] if sess["last_ts"] is not None else timestamp
            start_ts = sess["segment_start"] or timestamp
            duration = max(0.0, end_ts - start_ts)

            if duration >= MIN_SEGMENT_DURATION:
                segment = {
                    "user_id": user_id,
                    "start_ts": start_ts,
                    "end_ts": end_ts,
                    "duration": duration,
                    "max_rms": sess["max_rms"],
                }

                segment_topic = f"interview/{user_id}/speech/segment"
                # 세그먼트 요약을 MQTT로 퍼블리시
                client.publish(segment_topic, json.dumps(segment))
                print(
                    f"[speech_worker] [{user_id}] SEGMENT "
                    f"{start_ts:.2f} ~ {end_ts:.2f} "
                    f"(dur={duration:.2f}s, max_rms={sess['max_rms']:.1f})"
                )
            else:
                # 너무 짧은 소리 → 무시 (키보드 소리, 잡음 등)
                print(
                    f"[speech_worker] [{user_id}] SHORT noise ignored "
                    f"(dur={duration:.2f}s, max_rms={sess['max_rms']:.1f})"
                )

            # 세그먼트 정보 초기화
            sess["segment_start"] = None
            sess["last_ts"] = None
            sess["max_rms"] = 0.0
        else:
            # 지금도 silent, 원래도 silent → 아무 작업 X
            pass


def main():
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, KEEPALIVE)
    print("[speech_worker] MQTT client connecting...")

    # 블로킹 루프
    client.loop_forever()


if __name__ == "__main__":
    main()