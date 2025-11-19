from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from backend.routers.audio_stream import router as audio_router
# 또는 상대 import로
# from .routers.audio_stream import router as audio_router

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(audio_router)

@app.get("/")
def root():
    return {"msg": "Interview AI - Audio Stream Active"}
