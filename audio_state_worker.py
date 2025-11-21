# audio_state_worker.py
import json
import time
import paho.mqtt.client as mqtt

BROKER_HOST = "localhost"
BROKER_PORT = 1883

# 말하기 / 침묵 판단 임계값 (rms 기준, 로그 보면서 조정)
RMS_THRESHOLD = 50.0        # 이 값보다 크면 "말하는 중"이라고 간주
HOLD_TIME = 0.5             # 0.5초 이내에 소리가 계속 나면 상태 유지

last_speech_time = 0.0
current_state = "silent"    # or "speaking"

client = mqtt.Client()

def publish_state(user_id: str, state: str):
    global current_state
    if state == current_state:
        return  # 상태가 같으면 굳이 재발행 X

    current_state = state
    topic = f"interview/{user_id}/audio/state"
    payload = {
        "timestamp": time.time(),
        "user_id": user_id,
        "state": state,
    }
    client.publish(topic, json.dumps(payload))
    print("STATE:", topic, payload)


def on_connect(client, userdata, flags, reason_code, properties=None):
    print("MQTT connected:", reason_code)
    # raw 오디오 구독
    client.subscribe("interview/+/audio/raw")


def on_message(client, userdata, msg):
    global last_speech_time

    try:
        payload = json.loads(msg.payload.decode("utf-8"))
    except Exception as e:
        print("JSON decode error:", e)
        return

    user_id = payload.get("user_id", "unknown")
    rms = float(payload.get("rms", 0.0))
    ts = payload.get("timestamp", time.time())

    # 1) RMS가 threshold 이상이면 "말하고 있다"로 본다.
    if rms >= RMS_THRESHOLD:
        last_speech_time = ts
        publish_state(user_id, "speaking")
    else:
        # 2) RMS가 작더라도, 최근에 말한지 0.5초 이내면 "speaking" 유지
        if ts - last_speech_time > HOLD_TIME:
            publish_state(user_id, "silent")


def main():
    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()