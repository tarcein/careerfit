SYSTEM_PROMPT = """
당신은 자기소개서 문항의 평가 의도를 구조화한다.

규칙:
1. question_type은 지원동기, 직무역량, 문제해결, 도전, 협업, 갈등, 성장과정, 가치관, 성격 장단점, 입사 후 포부, 기타 중 하나다.
2. 문항과 선택한 JD에 실제로 드러난 평가 요소만 작성한다.
3. 답변에 필요한 이야기 요소와 피해야 할 내용을 구체적이고 짧게 작성한다.
4. 지원동기는 기업·직무 관심과 개인 경험의 연결을 우선한다.
""".strip()


def build_user_prompt(question: str, optional_note: str, jd_json: str) -> str:
    return f"""자기소개서 문항:
{question}

추가 안내:
{optional_note or '없음'}

JD 분석:
{jd_json}
"""
