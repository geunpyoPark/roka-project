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

CLIENT_ID = "speech-segment-worker-v4"

# ====== 튜닝 포인트 ======
# 네 환경 기준:
#  - 말할 때: rms ~ 2000~10000
#  - 주변 잡음: 수십~수백
RMS_THRESHOLD = 600.0          # 말하는 걸로 인식할 최소 RMS (필요하면 400~1000 사이에서 튜닝)

# 말하기 최소 지속 시간 (초) - 이보다 짧으면 노이즈로 간주
MIN_SEGMENT_DURATION = 0.6

# 세그먼트 최대 길이(초) - 너무 길어지면 잘라냄
MAX_SEGMENT_DURATION = 10.0

# "진짜 끝났다"고 판단하기 위한 최소 침묵 길이(초)
MIN_SILENCE_DURATION = 0.4

# 각 사용자별 상태 저장
# sessions[user_id] = {
#   "state": "silent" or "speaking",
#   "segment_start": float | None,
#   "last_voice_ts": float | None,
#   "max_rms": float
# }
sessions: Dict[str, Dict[str, Any]] = {}


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[speech_worker v4] Connected to MQTT broker rc={reason_code}")
    client.subscribe("interview/+/audio/raw")
    print("[speech_worker v4] Subscribed: interview/+/audio/raw")


def on_message(client, userdata, msg):
    try:
        payload_str = msg.payload.decode("utf-8")
        data = json.loads(payload_str)
    except Exception as e:
        print("[speech_worker v4] JSON decode error:", e)
        print("  topic:", msg.topic)
        print("  raw payload:", msg.payload[:100])
        return

    # topic 예: interview/test-user-1/audio/raw
    parts = msg.topic.split("/")
    if len(parts) < 3:
        print("[speech_worker v4] Unexpected topic format:", msg.topic)
        return

    _, user_id, _, *_ = parts  # interview / {user_id} / audio / raw

    timestamp = float(data.get("timestamp", time.time()))
    rms = float(data.get("rms", 0.0))

    # 사용자 상태 초기화
    if user_id not in sessions:
        sessions[user_id] = {
            "state": "silent",
            "segment_start": None,
            "last_voice_ts": None,
            "max_rms": 0.0,
        }

    sess = sessions[user_id]

    # 현재 rms 기준으로 talking/silent 판정
    is_speaking = rms >= RMS_THRESHOLD
    prev_state = sess["state"]

    if is_speaking:
        # ---- 말하고 있는 구간 ----
        if prev_state == "silent":
            # 새 세그먼트 시작
            sess["state"] = "speaking"
            sess["segment_start"] = timestamp
            sess["last_voice_ts"] = timestamp
            sess["max_rms"] = rms
            print(
                f"[speech_worker v4] [{user_id}] SPEECH START at {timestamp:.3f} (rms={rms:.1f})"
            )
        else:
            # 이미 말하는 중 → 끝 시간/최대 RMS 갱신
            sess["last_voice_ts"] = timestamp
            if rms > sess["max_rms"]:
                sess["max_rms"] = rms

    else:
        # ---- 조용한 구간 ----
        if prev_state == "speaking":
            # 한 번에 바로 끝내지 말고,
            # 마지막으로 말한 시점(last_voice_ts)에서 일정 시간 이상 조용해야 "진짜 끝"으로 본다.
            last_voice_ts = sess["last_voice_ts"] or timestamp
            silence_duration = timestamp - last_voice_ts

            if silence_duration >= MIN_SILENCE_DURATION:
                # 여기서 세그먼트 종료로 확정
                start_ts = sess["segment_start"] or timestamp
                end_ts = last_voice_ts
                duration = max(0.0, end_ts - start_ts)

                if duration < MIN_SEGMENT_DURATION:
                    # 너무 짧은 세그먼트 → 노이즈로 버림
                    print(
                        f"[speech_worker v4] [{user_id}] SHORT segment ignored "
                        f"(dur={duration:.2f}s, max_rms={sess['max_rms']:.1f})"
                    )
                else:
                    # 정상 세그먼트 → MQTT 발행
                    if duration > MAX_SEGMENT_DURATION:
                        duration = MAX_SEGMENT_DURATION
                        end_ts = start_ts + duration

                    segment = {
                        "user_id": user_id,
                        "start_ts": start_ts,
                        "end_ts": end_ts,
                        "duration": duration,
                        "max_rms": sess["max_rms"],
                    }
                    segment_topic = f"interview/{user_id}/speech/segment"
                    client.publish(segment_topic, json.dumps(segment, ensure_ascii=False))
                    print(
                        f"[speech_worker v4] [{user_id}] SEGMENT "
                        f"{start_ts:.2f} ~ {end_ts:.2f} "
                        f"(dur={duration:.2f}s, max_rms={sess['max_rms']:.1f})"
                    )

                # 상태 초기화
                sess["state"] = "silent"
                sess["segment_start"] = None
                sess["last_voice_ts"] = None
                sess["max_rms"] = 0.0
            else:
                # 아직 침묵 시간이 짧음 → 여전히 "말하는 중"으로 간주
                # (state는 speaking 유지, segment는 이어짐)
                pass
        else:
            # silent → silent
            pass


def main():
    client = mqtt.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER, PORT, KEEPALIVE)
    print("[speech_worker v4] MQTT client connecting...")

    client.loop_forever()


if __name__ == "__main__":
    main()