# backend/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 분석 REST 라우터
from backend.routers.analysis import router as analysis_router

# MQTT에서 분석 결과를 가져와 캐시에 넣는 리스너
from backend.services.analysis_listener import start_analysis_listener

app = FastAPI(
    title="Interview AI Backend",
    description="Daglo + speech_rate 연동용 백엔드",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 단계
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# /analysis/{user_id}/latest
app.include_router(analysis_router)


@app.on_event("startup")
def startup_event():
    # FastAPI 시작 시 MQTT 분석 리스너 시작
    start_analysis_listener()


@app.get("/")
def root():
    return {"msg": "Interview AI Backend running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}