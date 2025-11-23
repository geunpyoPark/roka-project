# backend/api/ws_speech.py

import asyncio
from typing import Dict

import paho.mqtt.client as mqtt
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

router = APIRouter()

BROKER_HOST = "localhost"
BROKER_PORT = 1883
KEEPALIVE = 60

# user_id -> asyncio.Queue (MQTT -> WS 전달용)
user_queues: Dict[str, asyncio.Queue] = {}

# 메인 이벤트 루프 (startup 이벤트에서 세팅)
main_loop: asyncio.AbstractEventLoop | None = None

# 전역 MQTT 클라이언트
mqtt_client = mqtt.Client(
    client_id="ws-speech-bridge",
    callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    protocol=mqtt.MQTTv5,
)


def set_main_loop(loop: asyncio.AbstractEventLoop):
    """FastAPI startup 시점에 메인 이벤트 루프를 주입."""
    global main_loop
    main_loop = loop
    print("[ws_speech] main_loop set.")


def feedback_topic(user_id: str) -> str:
    return f"interview/{user_id}/speech/feedback"


def on_connect(client, userdata, flags, reason_code, properties=None):
    print(f"[ws_speech] MQTT Connected: rc={reason_code}")
    # 여기서는 공통 subscribe 안 하고,
    # WebSocket 연결 시점에 user별 topic을 subscribe 한다.


def on_message(client, userdata, msg):
    global main_loop
    try:
        topic = msg.topic
        parts = topic.split("/")
        # interview / {user_id} / speech / feedback
        if len(parts) < 4:
            print("[ws_speech] Unexpected topic:", topic)
            return

        _, user_id, category, subtopic, *rest = parts
        if not (category == "speech" and subtopic == "feedback"):
            print("[ws_speech] Ignore topic:", topic)
            return

        payload = msg.payload.decode("utf-8")

        q = user_queues.get(user_id)
        if q is not None and main_loop is not None:
            # 다른 스레드 → asyncio.Queue 로 안전하게 전달
            asyncio.run_coroutine_threadsafe(q.put(payload), main_loop)
        else:
            # 해당 user의 WebSocket이 아직/더이상 없으면 무시
            pass

    except Exception as e:
        print(f"[ws_speech] on_message error: {e}")


def init_mqtt():
    """FastAPI startup 시 1회만 호출해서 MQTT 루프 시작."""
    mqtt_client.on_connect = on_connect
    mqtt_client.on_message = on_message
    mqtt_client.connect(BROKER_HOST, BROKER_PORT, KEEPALIVE)
    mqtt_client.loop_start()
    print("[ws_speech] MQTT client started.")


@router.websocket("/ws/speech/{user_id}")
async def websocket_speech(ws: WebSocket, user_id: str):
    await ws.accept()
    print(f"[ws_speech] WebSocket connected: user_id={user_id}")

    # user 전용 queue 생성
    q: asyncio.Queue = asyncio.Queue()
    user_queues[user_id] = q

    # 해당 user 의 feedback 토픽 구독
    topic = feedback_topic(user_id)
    mqtt_client.subscribe(topic)
    print(f"[ws_speech] Subscribed MQTT topic: {topic}")

    try:
        while True:
            data = await q.get()
            await ws.send_text(data)

    except WebSocketDisconnect:
        print(f"[ws_speech] WebSocket disconnected: user_id={user_id}")
    finally:
        # 정리
        user_queues.pop(user_id, None)
        mqtt_client.unsubscribe(topic)
        print(f"[ws_speech] Unsubscribed MQTT topic: {topic}")