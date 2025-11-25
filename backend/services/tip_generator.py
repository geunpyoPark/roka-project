# backend/services/tip_generator.py

import os
import json
from typing import Any, Dict, Optional, List

import httpx


GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")  # .env 등에 설정해 두기


async def _call_gemini(prompt: str) -> str:
    """
    Google Gemini(또는 재민아이 API)를 직접 호출하는 부분.
    실제 엔드포인트/모델명은 너 환경에 맞게 수정하면 돼.
    """
    if not GEMINI_API_KEY:
        # 키가 없으면 일단 디버깅용 더미 응답
        return "테스트 모드: 실제 Gemini 키가 설정되지 않았습니다."

    # 기본 Gemini REST 엔드포인트 예시
    url = (
        "https://generativelanguage.googleapis.com/v1beta/"
        "models/gemini-1.5-flash:generateContent"
    )

    params = {"key": GEMINI_API_KEY}
    payload = {
        "contents": [
            {
                "parts": [
                    {"text": prompt}
                ]
            }
        ]
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(url, params=params, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # 가장 첫 번째 candidate의 text만 뽑는 단순 버전
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        return json.dumps(data, ensure_ascii=False)


async def generate_interview_tip(
    *,
    question: str,
    answer_text: str,
    wpm: Optional[float] = None,
    speed_label: Optional[str] = None,
) -> Dict[str, Any]:
    """
    면접 질문 + 답변 + 말하기 속도 정보를 바탕으로
    Gemini에게 '면접 피드백'을 요청하고, JSON 형태로 정리해서 반환.
    """

    prompt = f"""
너는 '면접 코치 AI'야. 아래 정보를 바탕으로 지원자에게 짧고 실용적인 피드백을 한국어로 만들어 줘.

[질문]
{question}

[지원자의 답변 전문(STT)]
{answer_text}

[말하기 속도 정보]
- WPM(분당 단어 수): {wpm}
- 속도 라벨: {speed_label}

요구사항:
1. 전체적인 피드백을 한 문단 정도로 요약해 줘. (summary)
2. 지원자가 다음 답변에서 바로 써먹을 수 있는 구체적인 팁 3~5개를 bullet point로 만들어 줘. (bullets)
3. 말하기 속도에 대한 한 줄 코멘트를 작성해 줘. 예: "조금 빠른 편이라 중요한 문장에서만 속도를 살짝 낮추면 좋습니다." (speed_comment)
4. 아래 JSON 형식으로만 답해. JSON 외의 설명/문장은 절대 쓰지 마.

반환 형식(JSON):
{{
  "summary": "...",
  "bullets": ["...", "...", "..."],
  "speed_comment": "..."
}}
    """.strip()

    raw = await _call_gemini(prompt)

    # 모델이 JSON으로 잘 안 줄 수도 있으니 방어 로직
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        obj = {
            "summary": raw.strip(),
            "bullets": [],
            "speed_comment": "",
        }

    # 기본값 보정
    summary = obj.get("summary") or "요약 피드백을 생성하지 못했습니다."
    bullets = obj.get("bullets") or []
    if not isinstance(bullets, list):
        bullets = [str(bullets)]
    speed_comment = obj.get("speed_comment") or ""

    return {
        "summary": summary,
        "bullets": bullets,
        "speed_comment": speed_comment,
    }