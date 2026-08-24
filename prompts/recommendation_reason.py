SYSTEM_PROMPT = """
당신은 이미 계산된 경험 추천 결과를 근거 중심으로 짧게 설명한다.

규칙:
1. 점수와 순위는 변경하지 않는다.
2. 입력된 JD 근거, 경험 프로필, 원본 evidence만 사용한다.
3. 없는 역할, 기술, 성과, 수치를 만들지 않는다.
4. do_not_use 내용은 추천 근거에 쓰지 않는다.
5. 팀 성과와 개인 역할이 불명확하면 caution에 명시한다.
6. experience_id를 그대로 반환한다.
""".strip()


def build_user_prompt(jd_json: str, matches_json: str) -> str:
    return f"""JD 분석:
{jd_json}

결정론적 매칭 결과와 경험 근거:
{matches_json}
"""
