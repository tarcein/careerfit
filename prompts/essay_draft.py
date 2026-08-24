SYSTEM_PROMPT = """
당신은 승인된 자기소개서 개요를 완성된 초안으로 바꾼다.

규칙:
1. My Profile, Verified Experience Profile, 원본 evidence, 개인 소재, 승인 개요에 있는 사실만 사용한다.
2. 존재하지 않는 역할·행동·성과·수치·기간을 만들지 않는다.
3. 팀 성과와 개인 역할을 구분한다.
4. do_not_use 내용은 사용하지 않고 user_preference와 preferred_focus를 반영한다.
5. 문항에 직접 답하고 활동 나열보다 문제 해결 흐름을 중심으로 작성한다.
6. JD 키워드를 억지로 반복하지 않는다.
7. 글자 제한이 있으면 공백 포함 제한의 90~100% 안에 반드시 맞추고 절대 초과하지 않는다.
8. 제출 전에 공백과 문장부호를 포함한 글자 수를 확인하고, 90%보다 짧으면 근거 안에서 구체성을 보강한다.
9. 개인형 문항은 프로젝트 경험을 억지로 넣지 않고 선택된 개인 소재의 맥락·영향·행동 변화를 중심으로 쓴다.
""".strip()


def build_user_prompt(
    jd_json: str,
    question_json: str,
    outline_json: str,
    candidate_profile_json: str,
    experience_json: str,
    facts_json: str,
    preference_json: str,
    personal_material_json: str,
    character_limit: int | None,
) -> str:
    return f"""JD 분석:
{jd_json}

자기소개서 문항:
{question_json}

승인된 개요:
{outline_json}

사용자가 직접 저장한 My Profile (전공·학력·자격증·어학·기술 스택):
{candidate_profile_json}

Verified Experience Profiles (첫 번째가 주 경험):
{experience_json}

불변 원본 evidence:
{facts_json}

각 경험의 사용자 활용 지침:
{preference_json}

사용자가 직접 저장한 개인 소재:
{personal_material_json}

공백 포함 글자 제한: {character_limit or '없음'}
목표 분량: {f'{round(character_limit * 0.9)}~{character_limit}자 (이 범위 밖이면 제출하지 말고 다시 조정)' if character_limit else '자연스러운 분량'}
"""
