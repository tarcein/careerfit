SYSTEM_PROMPT = """
당신은 기존 경험 프로필을 사용자의 사실 수정 및 활용 지침에 맞게 재구성한다.

규칙:
1. 원본 근거와 기존 프로필에 없는 사실, 수치, 역할, 성과를 만들지 않는다.
2. user_correction은 사실관계 수정으로 반영한다.
3. user_preference와 preferred_focus는 서술 강조점에 반영한다.
4. do_not_use에 해당하는 내용은 새 프로필에서 제외한다.
5. ownership_notes를 따라 개인 역할과 팀 성과를 명확히 구분한다.
6. evidence의 원문 인용과 source_file은 변경하거나 새로 만들지 않는다.
""".strip()


def build_user_prompt(
    current_profile: str,
    source_facts: str,
    correction: str,
    preference: str,
    do_not_use: str,
    preferred_focus: str,
    ownership_notes: str,
) -> str:
    return f"""현재 프로필:
{current_profile}

불변 원본 근거:
{source_facts}

사용자 사실 수정:
{correction or '없음'}

활용 선호:
{preference or '없음'}

사용 금지:
{do_not_use or '없음'}

강조점:
{preferred_focus or '없음'}

개인/팀 역할 지침:
{ownership_notes or '없음'}
"""

