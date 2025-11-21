# backend/main.py

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

# 오디오 WebSocket → MQTT 퍼블리시 라우터
from backend.routers.audio_stream import router as audio_router
# 분석 REST 조회용 라우터 (있다면)
from backend.routers.analysis import router as analysis_router

# FastAPI 프로세스에서 쓸 전역 MQTT 퍼블리시 클라이언트
from backend.mqtt_client import connect_mqtt
# 말속도/텍스트 분석 MQTT → 메모리 캐시 리스너
from backend.services.analysis_listener import start_analysis_listener

# ===============================
#  FastAPI 앱 생성
# ===============================
app = FastAPI(
    title="Interview AI Backend",
    description="WebSocket audio → MQTT → Whisper/SpeechRate 파이프라인 백엔드",
    version="0.1.0",
)

# ===============================
#  CORS 설정
# ===============================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],          # 개발 단계에서 전체 허용
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ===============================
#  라우터 등록
# ===============================
app.include_router(audio_router)     # /audio-stream WebSocket
app.include_router(analysis_router)  # /analysis/{user_id}/latest (있다면)


# ===============================
#  애플리케이션 시작 이벤트
# ===============================
@app.on_event("startup")
def startup_event():
    """
    FastAPI가 뜰 때 한 번 실행.
    - backend/mqtt_client.py 의 전역 MQTT 클라이언트 connect()
    - analysis_listener MQTT 구독 시작
    """
    # FastAPI → MQTT 퍼블리시용 (audio_stream에서 사용)
    connect_mqtt()
    # MQTT → 메모리 캐시용 리스너 시작 (analysis_cache 업데이트)
    start_analysis_listener()


# ===============================
#  기본/헬스 체크 엔드포인트
# ===============================
@app.get("/")
def root():
    return {"msg": "Interview AI - Audio Stream Active"}

@app.get("/health")
def health_check():
    """
    간단한 헬스 체크용 엔드포인트.
    배포 후 로드밸런서/모니터링에서 사용 가능.
    """
    return {"status": "ok"}