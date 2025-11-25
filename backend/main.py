# backend/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.services.analysis_listener import start_analysis_listener
from backend.routers import analysis as analysis_router
from backend.routers import tips as tips_router
from backend.routers import transcript as transcript_router

app = FastAPI(
    title="Interview AI Backend",
    description="Daglo + speech_rate + Transcript 뷰어 백엔드",
    version="0.1.0",
)

# CORS (프론트 로컬 개발용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 개발 단계라 전체 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 라우터 등록 ---
# /analysis/{user_id}/latest
app.include_router(analysis_router.router)
# /tips/{user_id}
app.include_router(tips_router.router)
# /transcript/{user_id}
app.include_router(transcript_router.router)


@app.on_event("startup")
def startup_event():
    """
    FastAPI 시작 시 MQTT 분석 리스너 시작
    (speech_rate_worker → MQTT → analysis_listener → analysis_cache)
    """
    start_analysis_listener()


@app.get("/")
def root():
    return {"msg": "Interview AI Backend running"}


@app.get("/health")
def health_check():
    return {"status": "ok"}