from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.routers.audio_stream import router as audio_router
from backend.mqtt_client import connect_mqtt

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audio_router)


@app.on_event("startup")
def startup_event():
    # FastAPI 시작할 때 MQTT 한 번 연결
    connect_mqtt()


@app.get("/")
def root():
    return {"msg": "Interview AI - Audio Stream Active"}