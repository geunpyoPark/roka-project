# backend/services/interview_tip.py

from typing import Optional

"""
면접 답변(텍스트) + 말 속도(WPM)를 받아
간단한 피드백 문장을 만들어주는 모듈.

나중에 여기에서 Gemini / 파인튜닝 모델을 호출하도록 바꿀 거고,
지금은 규칙 기반으로만 동작하도록 구현.
"""


def generate_tip(answer_text: str, wpm: Optional[float] = None) -> str:
    answer_text = (answer_text or "").strip()

    tips: list[str] = []

    # 1) 말 속도 피드백
    if wpm is not None:
        if wpm > 170:
            tips.append(
                "전체적으로 말 속도가 빠른 편이에요. 중요한 문장 앞뒤에는 한 박자 쉬어 주면서 억양을 조금만 더 떨어뜨려 보세요."
            )
        elif wpm < 110:
            tips.append(
                "말 속도가 다소 느린 편이에요. 중간중간 핵심 키워드를 또렷하게 강조하면서 속도를 조금만 올려주는 연습을 해보세요."
            )
        else:
            tips.append(
                "말 속도가 안정적인 편이에요. 지금 속도를 유지하되, 문장 끝을 또렷하게 마무리하는 데만 신경 써 보세요."
            )

    # 2) 답변 길이 기반 피드백
    length = len(answer_text)

    if length == 0:
        tips.append("아직 인식된 답변이 없어요. 한 문장 이상으로 답변한 뒤 다시 시도해 주세요.")
    elif length < 40:
        tips.append(
            "답변 분량이 조금 짧아요. 상황(What) → 행동(How) → 결과(Result) 순서로 한두 문장씩만 더 구체적으로 설명해보면 좋아요."
        )
    elif length > 400:
        tips.append(
            "답변이 꽤 긴 편이에요. 가장 중요한 2~3개의 키포인트만 남기고, 불필요한 배경 설명은 줄이면 더 설득력 있게 들립니다."
        )
    else:
        tips.append(
            "분량은 적당해요. 마지막 문장에서 ‘그래서 이 경험을 통해 ~을 배웠다’처럼 배운 점을 한 줄로 정리해주면 더 좋습니다."
        )

    # 3) 단순 키워드 기반(예시용)
    lower = answer_text.lower()
    if "팀" in answer_text or "협업" in answer_text:
        tips.append("팀 프로젝트를 말할 때는 본인 역할과 기여도를 꼭 한 번은 명확하게 짚어 주세요.")
    if "실패" in answer_text or "어려움" in answer_text:
        tips.append("실패나 어려움을 말할 때는 ‘그래서 무엇을 배웠는지’를 마지막에 정리해주면 인상이 좋아집니다.")

    return " ".join(tips)