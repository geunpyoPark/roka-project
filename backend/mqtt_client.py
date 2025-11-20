# backend/mqtt_client.py

from paho.mqtt import client as mqtt_client
import json

BROKER = "localhost"
PORT = 1883
CLIENT_ID = "interview-backend"

# 전역 MQTT 클라이언트
mqtt = None


def on_connect(client, userdata, flags, reason_code, properties=None):
    """
    MQTT 브로커에 연결됐을 때 호출되는 콜백
    """
    if reason_code == 0:
        print("✅ MQTT connected successfully")
    else:
        print(f"❌ MQTT connection failed, reason_code={reason_code}")


def connect_mqtt():
    """
    FastAPI가 시작될 때 한 번만 호출해서
    전역 mqtt 클라이언트를 만들어 두는 함수
    """
    global mqtt
    if mqtt is not None:
        # 이미 연결돼 있으면 재사용
        return mqtt

    # paho-mqtt 2.x 대응: callback_api_version을 명시적으로 설정
    client = mqtt_client.Client(
        client_id=CLIENT_ID,
        callback_api_version=mqtt_client.CallbackAPIVersion.VERSION2,
    )

    client.on_connect = on_connect
    client.connect(BROKER, PORT)
    client.loop_start()  # 백그라운드 스레드에서 네트워크 루프 시작

    mqtt = client
    print("✅ MQTT client initialized")
    return mqtt


def publish(topic: str, payload):
    """
    모든 MQTT publish는 이 함수로 보내기

    payload는 dict 또는 str 둘 다 허용:
    - dict면 JSON 문자열로 변환해서 전송
    - str이면 그대로 전송
    """
    global mqtt

    if mqtt is None:
        # 혹시라도 아직 연결 안 돼 있으면 여기서 연결
        connect_mqtt()

    if isinstance(payload, dict):
        msg = json.dumps(payload, ensure_ascii=False)
    else:
        msg = str(payload)

    result = mqtt.publish(topic, msg)

    if result.rc != mqtt_client.MQTT_ERR_SUCCESS:
        print(f"❌ MQTT publish failed: rc={result.rc}, topic={topic}")
    else:
        # 디버그용 로그 (시끄러우면 주석 처리해도 됨)
        print(f"📨 MQTT published → {topic}: {msg}")