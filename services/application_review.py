import re

from models import FactCheckItem


def fact_check_draft(
    content: str,
    experience: dict | list[dict],
    candidate_profile: dict | None = None,
    personal_materials: list[dict] | None = None,
) -> list[FactCheckItem]:
    experiences = experience if isinstance(experience, list) else [experience]
    facts = [fact["evidence_text"] for item in experiences for fact in item["facts"] if fact.get("evidence_text")]
    experience_profile_text = " ".join(_flatten(item["profile"]) for item in experiences)
    profile_labels = {
        "target_role": "희망 직무",
        "industries": "관심 산업",
        "major": "전공",
        "education": "학력",
        "certifications": "자격증",
        "languages": "어학",
        "technical_skills": "기술 스택",
        "courses": "교육 과정",
        "activities": "기타 활동",
        "role_description": "희망 직무 설명",
    }
    candidate_facts = [
        f"My Profile {profile_labels.get(key, key)}: {value}"
        for key, value in (candidate_profile or {}).items()
        if key != "nickname" and value
    ]
    candidate_facts.extend(
        f"개인 소재 {item['category']} · {item['title']}: "
        + " / ".join(
            str(item.get(field, ""))
            for field in ("context", "memorable_point", "insight", "changed_action", "keywords")
            if item.get(field)
        )
        for item in (personal_materials or [])
    )
    supported_text = " ".join([*facts, experience_profile_text, *candidate_facts])
    preferences = [preference for item in experiences for preference in item.get("preferences", [])]
    forbidden = [
        line.strip()
        for item in preferences
        for line in item.get("do_not_use", "").splitlines()
        if len(line.strip()) >= 2
    ]
    ownership_text = " ".join(
        [
            *(item["profile"].get("ownership_notes", "") for item in experiences),
            *(item.get("ownership_notes", "") for item in preferences),
        ]
    )
    results: list[FactCheckItem] = []
    for sentence in _sentences(content):
        violation = next((item for item in forbidden if item.casefold() in sentence.casefold()), "")
        unsupported_numbers = [number for number in _numbers(sentence) if number not in _numbers(supported_text)]
        ownership_claim = any(word in sentence for word in ("혼자", "단독", "전부 직접", "모두 직접"))
        if violation:
            results.append(FactCheckItem(
                sentence=sentence,
                status="Unsupported",
                reason=f"사용 금지 내용과 일치합니다: {violation}",
            ))
            continue
        if unsupported_numbers:
            results.append(FactCheckItem(
                sentence=sentence,
                status="Unsupported",
                reason="근거에서 확인되지 않는 수치: " + ", ".join(unsupported_numbers),
            ))
            continue
        if ownership_claim and not any(word in ownership_text for word in ("혼자", "단독", "전부 직접", "모두 직접")):
            results.append(FactCheckItem(
                sentence=sentence,
                status="Unsupported",
                reason="개인 단독 수행을 뒷받침하는 역할 근거가 없습니다.",
            ))
            continue
        ranked = sorted(((_similarity(sentence, fact), fact) for fact in facts), reverse=True)
        evidence = [fact for score, fact in ranked[:2] if score >= 0.3]
        if evidence:
            results.append(FactCheckItem(
                sentence=sentence,
                status="Verified",
                evidence=evidence,
                reason="원본 Evidence와 핵심 표현이 일치합니다.",
            ))
        else:
            candidate_evidence = [
                fact
                for score, fact in sorted(((_similarity(sentence, fact), fact) for fact in candidate_facts), reverse=True)[:2]
                if score >= 0.3
            ]
            profile_match = _similarity(sentence, experience_profile_text)
            results.append(FactCheckItem(
                sentence=sentence,
                status="Needs Review",
                evidence=candidate_evidence,
                reason=(
                    "저장된 My Profile에는 연결되지만 원본 증빙 문서 확인이 필요합니다."
                    if candidate_evidence
                    else (
                        "승인된 Experience Profile에는 연결되지만 원본 Evidence 직접 일치가 약합니다."
                        if profile_match >= 0.3
                        else "Experience DB와 My Profile에서 직접 뒷받침하는 근거를 찾지 못했습니다."
                    )
                ),
            ))
    return results


def evaluate_application(
    content: str,
    context: dict,
    checks: list[FactCheckItem],
    experience_use_count: int,
) -> dict:
    jd = context["jd"]["analysis"]
    question = context["question"]
    experiences = context.get("experiences") or []
    skill_groups = ("required_skills", "preferred_skills", "technical_skills", "tools", "domain_knowledge")
    skills = list(dict.fromkeys(
        item["name"] for group in skill_groups for item in jd.get(group, []) if item.get("name")
    ))
    matched_skills = [skill for skill in skills if skill.casefold() in content.casefold()]
    jd_coverage = round(len(matched_skills) / len(skills) * 100) if skills else 100

    question_type = question["analysis"].get("question_type", "기타")
    required_sections = {
        "문제해결": ("문제", "판단", "행동", "결과"),
        "협업": ("상황", "행동", "결과"),
        "갈등": ("문제", "행동", "결과", "배운"),
        "도전": ("문제", "행동", "결과", "배운"),
        "직무역량": ("행동", "결과", "직무"),
        "지원동기": ("핵심", "직무", "활용"),
    }.get(question_type, ("핵심", "행동", "결과"))
    outline_titles = " ".join(section["title"] for section in context["outline"].get("sections", []))
    covered_sections = [item for item in required_sections if item in outline_titles]
    question_coverage = round(len(covered_sections) / len(required_sections) * 100)

    fact_counts = {status: sum(item.status == status for item in checks) for status in ("Verified", "Needs Review", "Unsupported")}
    fact_score = round(fact_counts["Verified"] / len(checks) * 100) if checks else 0
    limit = question.get("character_limit")
    character_ok = not limit or len(content) <= limit
    quantitative_source = [
        result for experience in experiences for result in experience["profile"].get("quantitative_results", [])
    ]
    quantitative_included = not quantitative_source or any(number in content for number in _numbers(" ".join(quantitative_source)))
    forbidden = [
        line.strip()
        for experience in experiences
        for item in experience.get("preferences", [])
        for line in item.get("do_not_use", "").splitlines()
        if len(line.strip()) >= 2 and line.strip().casefold() in content.casefold()
    ]
    skill_mentions = sum(content.casefold().count(skill.casefold()) for skill in skills)
    technical_overload = skill_mentions >= 8 and skill_mentions / max(len(_tokens(content)), 1) > 0.12
    score = round(
        jd_coverage * 0.25
        + question_coverage * 0.2
        + fact_score * 0.3
        + (10 if character_ok else 0)
        + (10 if quantitative_included else 0)
        + (5 if not forbidden and not fact_counts["Unsupported"] else 0)
    )
    return {
        "overall_score": min(score, 100),
        "character_count": len(content),
        "character_limit": limit,
        "character_limit_ok": character_ok,
        "jd_skill_coverage": jd_coverage,
        "matched_skills": matched_skills,
        "missing_skills": [skill for skill in skills if skill not in matched_skills],
        "question_coverage": question_coverage,
        "covered_story_elements": covered_sections,
        "quantitative_evidence": quantitative_included,
        "fact_counts": fact_counts,
        "repeated_experience": experience_use_count > 1,
        "experience_use_count": experience_use_count,
        "technical_keyword_overload": technical_overload,
        "do_not_use_violations": forbidden,
    }


def _sentences(content: str) -> list[str]:
    return [item.strip() for item in re.split(r"(?<=[.!?])\s+|\n+", content) if item.strip()]


def _numbers(value: str) -> list[str]:
    return re.findall(r"\d+(?:[.,]\d+)?%?", value)


def _tokens(value: str) -> set[str]:
    return set(re.findall(r"[0-9a-z가-힣]{2,}", value.casefold()))


def _similarity(left: str, right: str) -> float:
    left_tokens = _tokens(left)
    if not left_tokens:
        return 0.0
    return len(left_tokens & _tokens(right)) / len(left_tokens)


def _flatten(value) -> str:
    if isinstance(value, dict):
        return " ".join(_flatten(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_flatten(item) for item in value)
    return str(value or "")
