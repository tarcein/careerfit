SYSTEM_PROMPT = """
당신은 자기소개서 초안이 아니라 근거 기반 작성 개요를 만든다.

규칙:
1. My Profile, Verified Experience Profile, 원본 evidence, 개인 소재, 사용자 지침에 있는 사실만 사용한다.
2. 존재하지 않는 역할·행동·성과·수치·기간을 만들지 않는다.
3. 팀 성과와 개인 역할을 구분하고 불명확한 부분은 fact_cautions에 기록한다.
4. do_not_use 내용은 개요에서 제외한다.
5. 문항 의도에 맞는 STAR, STAR-F, KKK, 두괄식 + Storytelling 중 하나를 선택한다.
6. sections에는 핵심 메시지, 상황/맥락, 문제, 판단, 행동, 결과, 배운 점, 직무 연결이 필요한 범위에서 포함되어야 한다.
7. evidence_used는 입력된 원본 evidence 문구를 그대로 사용한다.
8. 문장 초안 대신 각 부분에 들어갈 사실과 작성 방향을 간결하게 적는다.
9. 개인형 문항은 프로젝트를 억지로 연결하지 말고 선택된 개인 소재를 중심으로 구성한다.
""".strip()


def build_generation_prompt(
    jd_json: str,
    question_json: str,
    candidate_profile_json: str,
    experience_json: str,
    facts_json: str,
    preference_json: str,
    personal_material_json: str,
    character_limit: int | None,
) -> str:
    return f"""JD 분석:
{jd_json}

문항과 의도 분석:
{question_json}

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

최종 글자 제한: {character_limit or '없음'}
"""


def build_revision_prompt(
    current_json: str,
    request: str,
    candidate_profile_json: str,
    facts_json: str,
    preference_json: str,
    personal_material_json: str,
) -> str:
    return f"""기존 개요:
{current_json}

사용자 수정 요청:
{request}

사용자가 직접 저장한 My Profile:
{candidate_profile_json}

사용 가능한 불변 evidence:
{facts_json}

사용자 활용 지침:
{preference_json}

사용자가 직접 저장한 개인 소재:
{personal_material_json}
"""
