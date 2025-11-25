# backend/services/tip_generator.py

"""
면접 Assist 코칭 텍스트를 생성해 주는 모듈.

- 기본 동작: llama-cpp-python + GGUF 로컬 LLM 사용 (환경변수로 모델 경로 지정)
- llama-cpp-python 미설치 / 모델 경로 없음 => 안전하게 더미 응답 반환 (테스트 모드)
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, Optional

LLM_AVAILABLE = False
LLM = None  # lazy-load


def _load_llm_if_needed():
    """
    GGUF 로컬 모델을 lazy-load.
    환경변수 LOCAL_GGUF_MODEL=/path/to/model.gguf 로 설정해 두었다고 가정.
    """
    global LLM_AVAILABLE, LLM
    if LLM_AVAILABLE:
        return

    model_path = os.getenv("LOCAL_GGUF_MODEL")
    if not model_path:
        print("[tip_generator] LOCAL_GGUF_MODEL 이 설정되지 않았습니다. 테스트 모드로 동작합니다.")
        return

    try:
        from llama_cpp import Llama  # type: ignore

        print(f"[tip_generator] GGUF 모델 로딩 중: {model_path}")
        LLM = Llama(
            model_path=model_path,
            n_ctx=4096,
            n_threads=4,  # 맥북 M4 프로니까 필요시 늘려도 됨
        )
        LLM_AVAILABLE = True
        print("[tip_generator] GGUF 모델 로딩 완료.")
    except Exception as e:
        print(f"[tip_generator] LLM 로딩 실패, 테스트 모드로 동작: {e}")
        LLM_AVAILABLE = False
        LLM = None


def _build_prompt(question: str, answer_text: str, wpm: Optional[float], speed_label: Optional[str]) -> str:
    """
    LLM에게 줄 프롬프트. JSON 형식으로만 답하도록 요구.
    """
    q = question.strip() or "면접관의 일반적인 질문"
    a = answer_text.strip() or "(지원자의 답변 내용이 충분하지 않음)"

    speed_info = ""
    if wpm is not None:
        speed_info += f"\n- 말하기 속도: 약 {wpm:.1f} WPM"
    if speed_label:
        speed_info += f"\n- 속도 평가: {speed_label}"

    prompt = f"""
너는 취업 면접 코치 AI다. 아래 정보를 보고, 지원자가 다음 답변을 더 잘할 수 있도록 한국어로 코칭을 해줘.

[면접관 질문]
{q}

[지원자 답변 요약용 원문]
{a}

[말하기 정보]{speed_info or "\n- (속도 정보 없음)"}

출력 형식은 반드시 JSON 형식으로만, 아래 구조를 지켜서 출력해라.

{{
  "summary": "이번 답변에 대한 전체적인 평가와 한 줄 요약 (2~3문장)",
  "bullets": [
    "다음 답변에서 이렇게 하면 좋은 점 1",
    "다음 답변에서 이렇게 하면 좋은 점 2",
    "필요하다면 3,4번까지"
  ],
  "speed_comment": "말하기 속도에 대한 구체적인 코멘트 (너무 빠름/느림 등). 없으면 빈 문자열."
}}

여분의 설명 문장이나 JSON 밖 텍스트는 절대 쓰지 말고, 위 JSON 객체 하나만 출력해라.
"""
    return prompt.strip()


def _parse_llm_json(text: str) -> Dict[str, Any]:
    """
    LLM 출력에서 JSON 부분만 깔끔히 파싱.
    코드블럭 ```json ... ``` 을 써도 대응.
    """
    text = text.strip()

    # 코드블럭 제거
    if "```" in text:
        parts = text.split("```")
        # ```json ... ``` 또는 ``` ... ```
        for p in parts:
            p = p.strip()
            if p.startswith("{") and p.endswith("}"):
                text = p
                break

    try:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("JSON dict 아님")
        return data
    except Exception as e:
        print(f"[tip_generator] JSON 파싱 실패: {e}, raw={text[:200]}")
        # 실패하면 대략적인 fallback
        return {
            "summary": "LLM 응답 파싱에 실패하여 기본 코멘트를 반환합니다.",
            "bullets": [
                "핵심 메시지를 먼저 한 문장으로 요약해서 말해 보세요.",
                "구체적인 사례(경험, 프로젝트)를 1개만 골라 깊게 설명해 보세요.",
            ],
            "speed_comment": "",
        }


def _generate_tip_sync(
    question: str,
    answer_text: str,
    wpm: Optional[float],
    speed_label: Optional[str],
) -> Dict[str, Any]:
    """
    동기 버전: 실제 LLM 호출 혹은 테스트 모드 응답 생성.
    FastAPI 쪽에서는 이걸 스레드풀로 돌릴 예정.
    """
    _load_llm_if_needed()

    # LLM 사용 가능하면
    if LLM_AVAILABLE and LLM is not None:
        prompt = _build_prompt(question, answer_text, wpm, speed_label)

        print("[tip_generator] LLM 호출 시작...")
        out = LLM(
            prompt,
            max_tokens=512,
            temperature=0.7,
            top_p=0.9,
            stop=None,
        )
        # llama_cpp 기본 출력 형식 맞게 조정
        if isinstance(out, dict):
            raw_text = out.get("choices", [{}])[0].get("text", "")
        else:
            raw_text = str(out)

        data = _parse_llm_json(raw_text)
        return data

    # 여기까지 오면: LLM 미사용 → 예전처럼 테스트용 기본 코멘트 반환
    print("[tip_generator] LLM 미사용: 테스트 모드 응답 반환.")
    return {
        "summary": "테스트 모드: 실제 로컬 LLM이 설정되지 않았습니다.",
        "bullets": [
            "LOCAL_GGUF_MODEL 환경변수를 설정하고 llama-cpp-python을 설치하면 로컬 LLM을 사용할 수 있습니다.",
            "지금은 UI 및 API 연결 테스트용 더미 응답입니다.",
        ],
        "speed_comment": "" if wpm is None else f"현재 속도는 약 {wpm:.1f} WPM 입니다.",
    }


async def generate_interview_tip(
    question: str,
    answer_text: str,
    wpm: Optional[float],
    speed_label: Optional[str],
) -> Dict[str, Any]:
    """
    FastAPI에서 await 하는 비동기 래퍼.
    내부에서는 동기 LLM 호출을 스레드풀에서 실행.
    """
    loop = asyncio.get_running_loop()
    result: Dict[str, Any] = await loop.run_in_executor(
        None,
        _generate_tip_sync,
        question,
        answer_text,
        wpm,
        speed_label,
    )
    return result