import json
import os
import time
from pathlib import Path

from config import EMBEDDING_MODEL, MAX_AI_INPUT_CHARS, OPENAI_DRAFT_MODEL, OPENAI_MODEL
from db import log_ai_call
from models import (
    EssayDraftOutput,
    EssayOutline,
    EvidenceItem,
    ExperienceBatch,
    ExperienceData,
    ExperiencePreference,
    JDAnalysis,
    JDSkill,
    OutlineSection,
    ProfileData,
    QuestionAnalysis,
    RecommendationExplanationBatch,
)
from prompts.experience_extraction import SYSTEM_PROMPT as EXTRACTION_SYSTEM_PROMPT
from prompts.experience_extraction import build_user_prompt as build_extraction_prompt
from prompts.experience_revision import SYSTEM_PROMPT as REVISION_SYSTEM_PROMPT
from prompts.experience_revision import build_user_prompt as build_experience_revision_prompt
from prompts.jd_analysis import SYSTEM_PROMPT as JD_SYSTEM_PROMPT
from prompts.jd_analysis import build_user_prompt as build_jd_prompt
from prompts.recommendation_reason import SYSTEM_PROMPT as RECOMMENDATION_SYSTEM_PROMPT
from prompts.recommendation_reason import build_user_prompt as build_recommendation_prompt
from prompts.question_analysis import SYSTEM_PROMPT as QUESTION_SYSTEM_PROMPT
from prompts.question_analysis import build_user_prompt as build_question_prompt
from prompts.essay_outline import SYSTEM_PROMPT as OUTLINE_SYSTEM_PROMPT
from prompts.essay_outline import build_generation_prompt, build_revision_prompt as build_outline_revision_prompt
from prompts.essay_draft import SYSTEM_PROMPT as DRAFT_SYSTEM_PROMPT
from prompts.essay_draft import build_user_prompt as build_draft_prompt


class MissingAPIKeyError(RuntimeError):
    pass


KNOWN_SKILLS = (
    "Python",
    "SQL",
    "R",
    "Excel",
    "Tableau",
    "Power BI",
    "Java",
    "JavaScript",
    "React",
    "AWS",
    "GCP",
    "Azure",
    "Git",
    "Docker",
    "Kubernetes",
    "Machine Learning",
    "머신러닝",
    "통계",
    "데이터 분석",
    "데이터 시각화",
    "고객 분석",
    "문제 해결",
    "커뮤니케이션",
    "협업",
    "프로젝트 관리",
)
TECHNICAL_SKILLS = {
    "python", "sql", "r", "excel", "tableau", "power bi", "java", "javascript", "react", "aws", "gcp",
    "azure", "git", "docker", "kubernetes", "machine learning", "머신러닝", "통계", "데이터 분석", "데이터 시각화",
}
BEHAVIORAL_SKILLS = {"문제 해결", "커뮤니케이션", "협업", "프로젝트 관리"}


def extract_experiences(
    files: list[dict], profile: ProfileData, user_id: int = 1
) -> tuple[list[ExperienceData], bool]:
    if not os.getenv("OPENAI_API_KEY"):
        return [_local_evidence_draft(file) for file in files], False

    documents = _format_documents(files)
    profile_context = profile.model_dump_json(indent=2)
    prompt = build_extraction_prompt(profile_context, documents)
    batch = _parsed_response("experience_extraction", EXTRACTION_SYSTEM_PROMPT, prompt, ExperienceBatch, user_id)
    return [_ground_experience(item, files) for item in batch.experiences], True


def revise_experience(
    current: ExperienceData,
    facts: list[dict],
    correction: str,
    preference: ExperiencePreference,
    user_id: int = 1,
) -> ExperienceData:
    if not os.getenv("OPENAI_API_KEY"):
        raise MissingAPIKeyError("AI 재구성에는 OPENAI_API_KEY가 필요합니다. 수동 새 버전 저장은 계속 사용할 수 있습니다.")
    prompt = build_experience_revision_prompt(
        current.model_dump_json(indent=2),
        json.dumps(facts, ensure_ascii=False, indent=2),
        correction,
        preference.user_preference,
        preference.do_not_use,
        preference.preferred_focus,
        preference.ownership_notes,
    )
    revised = _parsed_response("experience_revision", REVISION_SYSTEM_PROMPT, prompt, ExperienceData, user_id)
    return revised.model_copy(update={"source_files": current.source_files, "evidence": current.evidence})


def analyze_jd(company: str, job_title: str, raw_text: str, user_id: int = 1) -> tuple[JDAnalysis, bool]:
    if not company.strip() or not job_title.strip() or not raw_text.strip():
        raise ValueError("회사명, 지원 직무, 채용공고를 모두 입력해 주세요.")
    if not os.getenv("OPENAI_API_KEY"):
        return _local_jd_analysis(company.strip(), job_title.strip(), raw_text), False
    analysis = _parsed_response(
        "jd_analysis", JD_SYSTEM_PROMPT, build_jd_prompt(company, job_title, raw_text), JDAnalysis, user_id
    )
    grounded = analysis.model_copy(update={"company": company.strip(), "job_title": job_title.strip()})
    return _ground_jd_analysis(grounded, raw_text), True


def create_embeddings(texts: list[str], user_id: int = 1) -> list[list[float]]:
    if not os.getenv("OPENAI_API_KEY"):
        raise MissingAPIKeyError("Embedding 생성에는 OPENAI_API_KEY가 필요합니다.")
    from openai import OpenAI

    started = time.perf_counter()
    summary = f"items={len(texts)}, chars={sum(map(len, texts))}"
    try:
        response = OpenAI().embeddings.create(model=EMBEDDING_MODEL, input=texts)
        vectors = [item.embedding for item in response.data]
        tokens = getattr(getattr(response, "usage", None), "total_tokens", None)
        log_ai_call(
            "embedding", EMBEDDING_MODEL, summary, f"vectors={len(vectors)}", tokens, _elapsed_ms(started), True,
            user_id=user_id,
        )
        return vectors
    except Exception as exc:
        log_ai_call(
            "embedding", EMBEDDING_MODEL, summary, "", None, _elapsed_ms(started), False, str(exc)[:1000], user_id
        )
        raise


def explain_recommendations(jd: JDAnalysis, candidates: list[dict], user_id: int = 1) -> dict[int, dict]:
    if not os.getenv("OPENAI_API_KEY") or not candidates:
        return {}
    prompt = build_recommendation_prompt(
        jd.model_dump_json(indent=2), json.dumps(candidates, ensure_ascii=False, indent=2)
    )
    batch = _parsed_response(
        "recommendation_reason", RECOMMENDATION_SYSTEM_PROMPT, prompt, RecommendationExplanationBatch, user_id
    )
    valid_ids = {candidate["experience_id"] for candidate in candidates}
    return {
        item.experience_id: item.model_dump()
        for item in batch.explanations
        if item.experience_id in valid_ids
    }


def analyze_question(
    question: str,
    optional_note: str,
    jd: JDAnalysis,
    user_id: int = 1,
) -> tuple[QuestionAnalysis, bool]:
    if not question.strip():
        raise ValueError("자기소개서 문항을 입력해 주세요.")
    if not os.getenv("OPENAI_API_KEY"):
        return _local_question_analysis(question), False
    analysis = _parsed_response(
        "question_analysis",
        QUESTION_SYSTEM_PROMPT,
        build_question_prompt(question, optional_note, jd.model_dump_json(indent=2)),
        QuestionAnalysis,
        user_id,
    )
    return analysis, True


def generate_essay_outline(
    jd: JDAnalysis,
    question: dict,
    experience: dict | list[dict] | None,
    user_id: int = 1,
    candidate_profile: ProfileData | None = None,
    personal_materials: list[dict] | None = None,
) -> tuple[EssayOutline, bool]:
    experiences = experience if isinstance(experience, list) else ([experience] if experience else [])
    materials = personal_materials or []
    if not experiences and not materials:
        raise ValueError("개요에 사용할 경험 또는 개인 소재를 선택해 주세요.")
    analysis = QuestionAnalysis.model_validate(question["analysis"])
    preferences = [_selected_preference(item, jd.job_title) for item in experiences]
    if not os.getenv("OPENAI_API_KEY"):
        return _local_outline(jd, analysis, experiences, preferences, candidate_profile, materials), False
    prompt = build_generation_prompt(
        jd.model_dump_json(indent=2),
        json.dumps(question, ensure_ascii=False, indent=2),
        candidate_profile.model_dump_json(indent=2) if candidate_profile else "{}",
        json.dumps([item["profile"] for item in experiences], ensure_ascii=False, indent=2),
        json.dumps([fact for item in experiences for fact in item["facts"]], ensure_ascii=False, indent=2),
        json.dumps(preferences, ensure_ascii=False, indent=2),
        json.dumps(materials, ensure_ascii=False, indent=2),
        question.get("character_limit"),
    )
    outline = _parsed_response("essay_outline", OUTLINE_SYSTEM_PROMPT, prompt, EssayOutline, user_id)
    return _ground_outline(outline, experiences, materials), True


def revise_essay_outline(
    current: EssayOutline,
    request: str,
    experience: dict | list[dict] | None,
    target_role: str,
    user_id: int = 1,
    candidate_profile: ProfileData | None = None,
    personal_materials: list[dict] | None = None,
) -> EssayOutline:
    if not request.strip():
        raise ValueError("AI 수정 요청을 입력해 주세요.")
    if not os.getenv("OPENAI_API_KEY"):
        raise MissingAPIKeyError("AI 개요 수정에는 OPENAI_API_KEY가 필요합니다. 수동 새 버전 저장은 가능합니다.")
    experiences = experience if isinstance(experience, list) else ([experience] if experience else [])
    materials = personal_materials or []
    preferences = [_selected_preference(item, target_role) for item in experiences]
    prompt = build_outline_revision_prompt(
        current.model_dump_json(indent=2),
        request,
        candidate_profile.model_dump_json(indent=2) if candidate_profile else "{}",
        json.dumps([fact for item in experiences for fact in item["facts"]], ensure_ascii=False, indent=2),
        json.dumps(preferences, ensure_ascii=False, indent=2),
        json.dumps(materials, ensure_ascii=False, indent=2),
    )
    outline = _parsed_response("essay_outline_revision", OUTLINE_SYSTEM_PROMPT, prompt, EssayOutline, user_id)
    return _ground_outline(outline, experiences, materials)


def generate_essay_draft(
    context: dict, user_id: int = 1, use_ai: bool = True
) -> tuple[EssayDraftOutput, bool]:
    question = context["question"]
    experiences = context.get("experiences") or []
    materials = context.get("materials") or []
    preferences = [_selected_preference(item, context["jd"]["job_title"]) for item in experiences]
    limit = question.get("character_limit")
    if not use_ai or not os.getenv("OPENAI_API_KEY"):
        return EssayDraftOutput(content=_local_draft(context["outline"], limit)), False
    prompt = build_draft_prompt(
        json.dumps(context["jd"]["analysis"], ensure_ascii=False, indent=2),
        json.dumps(question, ensure_ascii=False, indent=2),
        json.dumps(context["outline"], ensure_ascii=False, indent=2),
        json.dumps(context.get("profile", {}), ensure_ascii=False, indent=2),
        json.dumps([item["profile"] for item in experiences], ensure_ascii=False, indent=2),
        json.dumps([fact for item in experiences for fact in item["facts"]], ensure_ascii=False, indent=2),
        json.dumps(preferences, ensure_ascii=False, indent=2),
        json.dumps(materials, ensure_ascii=False, indent=2),
        limit,
    )
    draft = _parsed_response(
        "essay_draft", DRAFT_SYSTEM_PROMPT, prompt, EssayDraftOutput, user_id, OPENAI_DRAFT_MODEL
    )
    minimum = round(limit * 0.9) if limit else 0
    if minimum and len(draft.content.strip()) < minimum:
        retry_prompt = f"""{prompt}

이전 초안은 공백 포함 {len(draft.content.strip())}자로 최소 {minimum}자에 미달했다.
아래 초안을 바탕으로 새로운 사실을 만들지 말고, 제공된 개요와 근거의 구체성을 충분히 풀어
공백 포함 {minimum}~{limit}자에 반드시 맞춘 완성본을 다시 작성하라.

이전 초안:
{draft.content.strip()}
"""
        draft = _parsed_response(
            "essay_draft_length_retry",
            DRAFT_SYSTEM_PROMPT,
            retry_prompt,
            EssayDraftOutput,
            user_id,
            OPENAI_DRAFT_MODEL,
        )
    content = _fit_character_limit(draft.content, limit)
    if minimum and len(content) < minimum:
        raise ValueError(
            f"AI 초안이 {len(content)}자로 목표 분량 {minimum}~{limit}자에 미달했습니다. 다시 생성해 주세요."
        )
    return EssayDraftOutput(content=content), True


def revise_essay_draft(
    context: dict,
    current_content: str,
    request: str,
    paragraph_index: int | None = None,
    user_id: int = 1,
) -> EssayDraftOutput:
    if not os.getenv("OPENAI_API_KEY"):
        raise MissingAPIKeyError("AI Draft 수정에는 OPENAI_API_KEY가 필요합니다.")
    if not request.strip():
        raise ValueError("Draft 수정 요청을 입력해 주세요.")
    paragraphs = [item.strip() for item in current_content.split("\n\n") if item.strip()]
    if paragraph_index is not None and paragraph_index not in range(len(paragraphs)):
        raise ValueError("수정할 문단을 찾을 수 없습니다.")
    experiences = context.get("experiences") or []
    materials = context.get("materials") or []
    target = paragraphs[paragraph_index] if paragraph_index is not None else current_content.strip()
    scope = "선택 문단의 교체 문단만" if paragraph_index is not None else "수정된 전체 초안"
    prompt = f"""자기소개서 문항:
{json.dumps(context['question'], ensure_ascii=False, indent=2)}

승인 개요:
{json.dumps(context['outline'], ensure_ascii=False, indent=2)}

My Profile:
{json.dumps(context.get('profile', {}), ensure_ascii=False, indent=2)}

Verified Experience와 원본 Evidence:
{json.dumps(experiences, ensure_ascii=False, indent=2)}

개인 소재:
{json.dumps(materials, ensure_ascii=False, indent=2)}

현재 전체 초안:
{current_content.strip()}

수정 대상:
{target}

수정 요청:
{request.strip()}

규칙: 기존 근거 밖의 사실을 만들지 말고 글자 제한 {context['question'].get('character_limit') or '없음'}을 지켜라.
content에는 {scope} 반환하라.
"""
    revised = _parsed_response(
        "essay_draft_revision", DRAFT_SYSTEM_PROMPT, prompt, EssayDraftOutput, user_id, OPENAI_DRAFT_MODEL
    )
    if paragraph_index is not None:
        paragraphs[paragraph_index] = revised.content.strip()
        content = "\n\n".join(paragraphs)
    else:
        content = revised.content.strip()
    limit = context["question"].get("character_limit")
    if limit and len(content) > limit:
        raise ValueError(f"수정 결과가 글자 제한을 {len(content) - limit}자 초과했습니다. 요청을 조정해 주세요.")
    return EssayDraftOutput(content=content)


def _parsed_response(
    task: str, system_prompt: str, user_prompt: str, output_model, user_id: int = 1, model: str = OPENAI_MODEL
):
    from openai import OpenAI

    started = time.perf_counter()
    summary = f"chars={len(user_prompt)}, task={task}"
    try:
        response = OpenAI().responses.parse(
            model=model,
            input=[
                {"role": "developer", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            text_format=output_model,
        )
        parsed = response.output_parsed
        if parsed is None:
            raise ValueError("모델이 구조화된 결과를 반환하지 않았습니다.")
        usage = getattr(response, "usage", None)
        tokens = getattr(usage, "total_tokens", None)
        output_json = parsed.model_dump_json()
        log_ai_call(task, model, summary, output_json, tokens, _elapsed_ms(started), True, user_id=user_id)
        return parsed
    except Exception as exc:
        log_ai_call(task, model, summary, "", None, _elapsed_ms(started), False, str(exc)[:1000], user_id)
        raise


def _format_documents(files: list[dict]) -> str:
    chunks: list[str] = []
    remaining = MAX_AI_INPUT_CHARS
    for file in files:
        header = f"\n===== FILE: {file['filename']} =====\n"
        body = file["extracted_text"][: max(0, remaining - len(header))]
        chunks.append(header + body)
        remaining -= len(header) + len(body)
        if remaining <= 0:
            break
    return "".join(chunks)


def _local_evidence_draft(file: dict) -> ExperienceData:
    lines = [line.strip() for line in file["extracted_text"].splitlines() if line.strip()]
    evidence = [EvidenceItem(source_file=file["filename"], quote=line) for line in lines[:3]]
    return ExperienceData(
        experience_name=Path(file["filename"]).stem,
        category="문서 기반 초안",
        summary=" ".join(lines)[:500],
        source_files=[file["filename"]],
        evidence=evidence,
        ownership_notes="AI 미사용 초안: 개인 기여와 팀 성과를 사용자가 확인해야 합니다.",
        confidence=0.2,
    )


def _local_jd_analysis(company: str, job_title: str, raw_text: str) -> JDAnalysis:
    lines = [line.strip(" -•\t") for line in raw_text.splitlines() if line.strip()]
    lowered = raw_text.casefold()
    found: list[JDSkill] = []
    required: list[JDSkill] = []
    preferred: list[JDSkill] = []
    for name in KNOWN_SKILLS:
        if name.casefold() not in lowered:
            continue
        evidence = next((line for line in lines if name.casefold() in line.casefold()), "")
        skill = JDSkill(name=name, importance=0.7, evidence=evidence)
        found.append(skill)
        if any(marker in evidence.casefold() for marker in ("필수", "자격", "required", "must")):
            required.append(skill.model_copy(update={"importance": 0.95}))
        elif any(marker in evidence.casefold() for marker in ("우대", "preferred", "plus")):
            preferred.append(skill.model_copy(update={"importance": 0.65}))
    task_lines = [
        line for line in lines if any(marker in line.casefold() for marker in ("담당", "업무", "responsib", "수행"))
    ] or lines[:5]
    important = [
        line for line in lines if any(marker in line.casefold() for marker in ("필수", "우대", "자격", "required", "preferred"))
    ][:10]
    return JDAnalysis(
        company=company,
        job_title=job_title,
        main_tasks=task_lines[:10],
        required_skills=_unique_skills(required),
        preferred_skills=_unique_skills(preferred),
        technical_skills=_unique_skills([item for item in found if item.name.casefold() in TECHNICAL_SKILLS]),
        behavioral_skills=_unique_skills([item for item in found if item.name in BEHAVIORAL_SKILLS]),
        tools=_unique_skills(
            [item for item in found if item.name.casefold() in {"excel", "tableau", "power bi", "git", "docker"}]
        ),
        keywords=[item.name for item in _unique_skills(found)],
        important_sentences=important,
    )


def _local_question_analysis(question: str) -> QuestionAnalysis:
    lowered = question.casefold()
    rules = (
        (("지원동기", "지원한 이유", "지원 이유"), "지원동기"),
        (("입사 후", "포부"), "입사 후 포부"),
        (("협업", "팀워크", "함께"), "협업"),
        (("갈등", "의견 충돌"), "갈등"),
        (("문제", "해결"), "문제해결"),
        (("도전", "실패", "극복"), "도전"),
        (("직무 역량", "역량", "전문성"), "직무역량"),
        (("성장과정", "성장 과정"), "성장과정"),
        (("가치관",), "가치관"),
        (("장단점", "장점", "단점"), "성격 장단점"),
    )
    question_type = next((kind for markers, kind in rules if any(marker in lowered for marker in markers)), "기타")
    intent_by_type = {
        "지원동기": ["기업과 직무에 대한 구체적 관심", "개인 경험과 지원 직무의 연결"],
        "입사 후 포부": ["입사 후 기여 방향", "경험을 직무에 적용하는 계획"],
        "협업": ["협업 과정", "본인의 구체적 역할과 기여"],
        "갈등": ["갈등 원인 이해", "조율 행동과 결과"],
        "문제해결": ["문제 정의", "판단 근거와 해결 행동"],
        "도전": ["도전의 난점", "시도와 학습"],
        "직무역량": ["직무 관련 기술과 행동", "근거 있는 결과"],
    }
    intent = intent_by_type.get(question_type, ["문항이 요구하는 경험과 행동", "구체적인 근거"])
    return QuestionAnalysis(
        question_type=question_type,
        evaluation_intent=intent,
        important_points=intent,
        recommended_experience_type=[question_type],
        required_story_elements=_story_elements(question_type),
        avoid_points=["근거 없는 수치", "팀 성과를 개인 성과로 표현", "활동 나열만 하는 답변"],
    )


def _story_elements(question_type: str) -> list[str]:
    return {
        "지원동기": ["관심 계기", "관련 경험", "직무 연결", "기여 방향"],
        "협업": ["공동 목표", "본인 역할", "소통 행동", "팀 결과"],
        "갈등": ["갈등 상황", "상대 관점", "조율 행동", "결과와 학습"],
        "문제해결": ["문제", "원인 또는 맥락", "판단", "행동", "결과"],
        "도전": ["난점", "시도", "변화", "결과", "학습"],
        "직무역량": ["직무 관련 문제", "기술 또는 방법", "본인 행동", "검증된 결과"],
    }.get(question_type, ["상황", "본인 행동", "결과", "배운 점"])


def _local_outline(
    jd: JDAnalysis,
    analysis: QuestionAnalysis,
    experiences: list[dict],
    preferences: list[dict],
    candidate_profile: ProfileData | None = None,
    personal_materials: list[dict] | None = None,
) -> EssayOutline:
    materials = personal_materials or []
    profile = experiences[0]["profile"] if experiences else {}
    preference = preferences[0] if preferences else {}
    framework = "두괄식 + Storytelling" if materials or analysis.question_type == "지원동기" else (
        "STAR-F" if analysis.question_type in {"직무역량", "문제해결"} else "STAR"
    )
    sections = [
        ("핵심 메시지", profile.get("summary", "")),
        ("상황과 맥락", profile.get("problem_context") or profile.get("summary", "")),
        ("문제", profile.get("problem", "")),
        ("판단과 선택 이유", " / ".join(filter(None, [profile.get("decision", ""), profile.get("decision_reason", "")]))),
        ("구체적인 행동", " / ".join(profile.get("actions", []))),
        ("결과", " / ".join(filter(None, [profile.get("result", ""), *profile.get("quantitative_results", [])]))),
        ("배운 점", " / ".join(profile.get("lessons", []))),
    ]
    for material in materials:
        sections.extend(
            [
                (f"개인 소재 · {material['title']}", material.get("context", "")),
                ("기억에 남은 지점", material.get("memorable_point", "")),
                ("나에게 준 영향", material.get("insight", "")),
                ("행동 변화", material.get("changed_action", "")),
            ]
        )
    for supporting in experiences[1:]:
        supporting_profile = supporting["profile"]
        supporting_content = " / ".join(
            filter(None, [supporting_profile.get("summary", ""), supporting_profile.get("result", "")])
        )
        if supporting_content:
            sections.append((f"보조 경험 · {supporting['experience_name']}", supporting_content))
    if candidate_profile:
        profile_points = [
            f"{label}: {getattr(candidate_profile, field)}"
            for field, label in (
                ("major", "전공"),
                ("education", "학력"),
                ("certifications", "자격증"),
                ("languages", "어학"),
                ("technical_skills", "기술 스택"),
                ("courses", "교육 과정"),
            )
            if getattr(candidate_profile, field)
        ]
        if profile_points:
            sections.append(("지원자 프로필 근거", " / ".join(profile_points)))
    sections.append(
        ("지원 직무 연결", preference.get("preferred_focus") or f"{jd.job_title}에서 활용할 수 있는 지점을 연결")
    )
    filtered = [(title, content) for title, content in sections if content]
    evidence = [fact["evidence_text"] for item in experiences for fact in item["facts"]][:8]
    cautions = []
    for item, item_preference in zip(experiences, preferences):
        cautions.extend(
            text
            for text in (item_preference.get("ownership_notes", ""), item["profile"].get("ownership_notes", ""))
            if text
        )
        if item_preference.get("do_not_use"):
            cautions.append("사용 금지: " + item_preference["do_not_use"])
    return EssayOutline(
        framework=framework,
        key_message=profile.get("summary", "")
        or ((materials[0].get("insight") or materials[0]["title"]) if materials else ""),
        sections=[OutlineSection(order=index, title=title, content=content) for index, (title, content) in enumerate(filtered, 1)],
        evidence_used=evidence,
        fact_cautions=cautions,
        experience_ids=[item["id"] for item in experiences],
        material_ids=[item["id"] for item in materials],
    )


def _selected_preference(experience: dict, target_role: str) -> dict:
    return next(
        (item for item in experience["preferences"] if item["target_role"].casefold() == target_role.casefold()),
        next((item for item in experience["preferences"] if item["target_role"] == "공통"), {}),
    )


def _ground_outline(
    outline: EssayOutline, experiences: list[dict], personal_materials: list[dict] | None = None
) -> EssayOutline:
    allowed = {fact["evidence_text"] for experience in experiences for fact in experience["facts"]}
    return outline.model_copy(
        update={
            "evidence_used": [item for item in outline.evidence_used if item in allowed],
            "experience_ids": [item["id"] for item in experiences],
            "material_ids": [item["id"] for item in (personal_materials or [])],
        }
    )


def _local_draft(outline: dict, character_limit: int | None) -> str:
    parts = [section["content"].strip() for section in outline.get("sections", []) if section.get("content", "").strip()]
    content = " ".join(part if part.endswith((".", "!", "?")) else part + "." for part in parts)
    return _fit_character_limit(content, character_limit)


def _fit_character_limit(content: str, character_limit: int | None) -> str:
    content = content.strip()
    if not character_limit or len(content) <= character_limit:
        return content
    shortened = content[:character_limit].rstrip()
    sentence_end = max(shortened.rfind(mark) for mark in (".", "!", "?", "。"))
    if sentence_end + 1 >= character_limit * 0.9:
        return shortened[: sentence_end + 1]
    word_end = shortened.rfind(" ")
    return shortened[:word_end].rstrip() if word_end > 0 else shortened


def _unique_skills(skills: list[JDSkill]) -> list[JDSkill]:
    return list({skill.name.casefold(): skill for skill in skills}.values())


def _ground_jd_analysis(analysis: JDAnalysis, raw_text: str) -> JDAnalysis:
    updates = {}
    for field in (
        "required_skills", "preferred_skills", "technical_skills", "domain_knowledge", "behavioral_skills", "tools"
    ):
        updates[field] = [
            skill for skill in getattr(analysis, field) if skill.evidence.strip() and skill.evidence.strip() in raw_text
        ]
    updates["important_sentences"] = [line for line in analysis.important_sentences if line.strip() in raw_text]
    return analysis.model_copy(update=updates)


def _ground_experience(experience: ExperienceData, files: list[dict]) -> ExperienceData:
    by_name = {file["filename"]: file["extracted_text"] for file in files}
    valid_evidence = [
        item for item in experience.evidence if item.source_file in by_name and item.quote.strip() in by_name[item.source_file]
    ]
    all_text = "\n".join(by_name.values())
    valid_numbers = [item for item in experience.quantitative_results if item.strip() and item.strip() in all_text]
    valid_sources = [name for name in experience.source_files if name in by_name]
    return experience.model_copy(
        update={
            "evidence": valid_evidence,
            "quantitative_results": valid_numbers,
            "source_files": valid_sources or list(by_name),
            "confidence": min(experience.confidence, 0.5) if not valid_evidence else experience.confidence,
        }
    )


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)
