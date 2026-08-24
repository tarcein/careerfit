import re

from models import JDAnalysis, ProfileData, QuestionAnalysis
from services.matching import build_matching_report


PERSONAL_QUESTION_TYPES = {"성장과정", "가치관", "성격 장단점"}
PERSONAL_QUESTION_KEYWORDS = ("책", "도서", "멘토", "존경", "인물", "가치관", "좌우명", "취미", "성장 배경")


def is_personal_question(question: str, analysis: QuestionAnalysis) -> bool:
    return analysis.question_type in PERSONAL_QUESTION_TYPES or any(
        keyword in question for keyword in PERSONAL_QUESTION_KEYWORDS
    )


def build_personal_material_report(
    question: str, analysis: QuestionAnalysis, materials: list[dict]
) -> list[dict]:
    target = " ".join(
        [question, analysis.question_type, *analysis.important_points, *analysis.required_story_elements]
    )
    target_tokens = _words(target)
    category_markers = {
        "책": ("책", "도서"),
        "멘토·존경 인물": ("멘토", "존경", "인물"),
        "가치관": ("가치관", "좌우명"),
        "취미": ("취미",),
        "성장 배경": ("성장", "배경"),
    }
    results = []
    for material in materials:
        material_text = " ".join(
            str(material.get(field, ""))
            for field in ("category", "title", "context", "memorable_point", "insight", "changed_action", "keywords")
        )
        overlap = len(target_tokens & _words(material_text)) / max(len(target_tokens), 1)
        category_fit = any(
            marker in question for marker in category_markers.get(material.get("category", ""), ())
        )
        completeness = sum(bool(material.get(field)) for field in ("context", "memorable_point", "insight", "changed_action"))
        score = round(category_fit * 60 + overlap * 30 + completeness / 4 * 10, 1)
        results.append(
            material
            | {
                "score": score,
                "reason": (
                    "문항이 요구한 소재 유형과 직접 일치합니다."
                    if category_fit
                    else "문항의 핵심 표현과 저장된 소재 내용을 기준으로 추천했습니다."
                ),
            }
        )
    return sorted(results, key=lambda item: (item["score"], item["updated_at"]), reverse=True)[:3]


def build_question_matching_report(
    jd_id: int,
    jd: JDAnalysis,
    analysis: QuestionAnalysis,
    experiences: list[dict],
    user_id: int = 1,
    candidate_profile: ProfileData | None = None,
) -> list[dict]:
    jd_matches = build_matching_report(jd_id, jd, experiences, False, user_id, None, candidate_profile)["matches"]
    by_id = {item["id"]: item for item in experiences}
    results: list[dict] = []
    for jd_match in jd_matches:
        experience = by_id[jd_match["experience_id"]]
        profile = experience["profile"]
        preference = _preference(experience, jd.job_title)
        question_fit = (
            _motivation_fit(jd, profile, preference, candidate_profile)
            if analysis.question_type == "지원동기"
            else _question_fit(analysis, profile, candidate_profile)
        )
        evidence_quality = min(
            1.0,
            float(profile.get("confidence", 0)) * 0.5 + min(len(experience["facts"]), 3) / 3 * 0.5,
        )
        quantitative = 1.0 if profile.get("quantitative_results") else 0.0
        jd_keys = ["semantic_similarity"]
        if jd.required_skills:
            jd_keys.append("required_skill_coverage")
        if jd.technical_skills or jd.tools:
            jd_keys.append("technical_skill_match")
        jd_max = sum({"semantic_similarity": 40, "required_skill_coverage": 25, "technical_skill_match": 15}[key] for key in jd_keys)
        jd_core = sum(jd_match["breakdown"].get(key, 0) for key in jd_keys) / jd_max
        breakdown = {
            "jd_fit": round(jd_core * 45, 2),
            "question_fit": round(question_fit * 35, 2),
            "evidence_quality": round(evidence_quality * 10, 2),
            "quantitative_result": round(quantitative * 10, 2),
        }
        matching_points = _matching_story_points(analysis, profile)
        caution_parts = [preference.get("ownership_notes", ""), profile.get("ownership_notes", "")]
        if preference.get("do_not_use"):
            caution_parts.append("사용 금지: " + preference["do_not_use"])
        results.append(
            {
                "experience_id": experience["id"],
                "experience_name": experience["experience_name"],
                "score": round(sum(breakdown.values()), 2),
                "breakdown": breakdown,
                "reason": _reason(
                    analysis.question_type,
                    experience["experience_name"],
                    matching_points,
                    jd.company,
                    jd.job_title,
                ),
                "core_episode": profile.get("problem") or profile.get("summary", ""),
                "emphasized_actions": profile.get("actions", [])[:3],
                "quantitative_results": profile.get("quantitative_results", []),
                "job_connection": preference.get("preferred_focus") or ", ".join(jd_match.get("matching_skills", [])[:4]),
                "evidence": [fact["evidence_text"] for fact in experience["facts"][:3]],
                "profile_evidence": jd_match.get("explanation", {}).get("profile_evidence", []),
                "profile_matching_skills": jd_match.get("profile_matching_skills", []),
                "caution": " / ".join(part for part in caution_parts if part),
            }
        )
    results.sort(key=lambda item: item["score"], reverse=True)
    for rank, item in enumerate(results[:3], 1):
        item["rank"] = rank
    return results[:3]


def _question_fit(analysis: QuestionAnalysis, profile: dict, candidate_profile: ProfileData | None = None) -> float:
    fields = {
        "problem": bool(profile.get("problem")),
        "decision": bool(profile.get("decision") or profile.get("decision_reason")),
        "actions": bool(profile.get("actions")),
        "result": bool(profile.get("result") or profile.get("quantitative_results")),
        "lessons": bool(profile.get("lessons")),
        "collaboration": bool(
            profile.get("soft_skills")
            or profile.get("ownership_notes")
            or profile.get("team_or_individual") not in {"", "확인 필요"}
        ),
        "technical": bool(
            profile.get("technical_skills")
            or profile.get("tools")
            or (candidate_profile and (candidate_profile.technical_skills or candidate_profile.certifications))
        ),
        "domain": bool(profile.get("domain") or (candidate_profile and (candidate_profile.major or candidate_profile.industries))),
    }
    needed = {
        "문제해결": ("problem", "decision", "actions", "result"),
        "협업": ("collaboration", "actions", "result"),
        "갈등": ("problem", "collaboration", "actions", "lessons"),
        "도전": ("problem", "actions", "result", "lessons"),
        "직무역량": ("technical", "actions", "result"),
        "지원동기": ("domain", "lessons", "technical"),
        "입사 후 포부": ("technical", "lessons", "result"),
    }.get(analysis.question_type, ("actions", "result", "lessons"))
    structural = sum(fields[key] for key in needed) / len(needed)
    intent_text = " ".join(analysis.important_points + analysis.required_story_elements)
    profile_text = " ".join(
        str(value) if not isinstance(value, list) else " ".join(map(str, value)) for value in profile.values()
    )
    if candidate_profile:
        profile_text += " " + " ".join(str(value) for value in candidate_profile.model_dump().values() if value)
    return min(1.0, structural * 0.8 + _word_overlap(intent_text, profile_text) * 0.2)


def _motivation_fit(
    jd: JDAnalysis, profile: dict, preference: dict, candidate_profile: ProfileData | None = None
) -> float:
    jd_text = " ".join(
        [
            jd.company,
            jd.job_title,
            *jd.main_tasks,
            *jd.keywords,
            *(skill.name for skill in jd.required_skills + jd.technical_skills + jd.domain_knowledge),
        ]
    )
    experience_text = " ".join(
        [
            profile.get("summary", ""),
            *profile.get("technical_skills", []),
            *profile.get("domain", []),
            *profile.get("lessons", []),
            preference.get("preferred_focus", ""),
        ]
    )
    if candidate_profile:
        experience_text += " " + " ".join(str(value) for value in candidate_profile.model_dump().values() if value)
    role_connection = _word_overlap(jd_text, experience_text)
    has_focus = bool(preference.get("preferred_focus"))
    has_learning = bool(profile.get("lessons"))
    return min(1.0, role_connection * 0.6 + has_focus * 0.25 + has_learning * 0.15)


def _matching_story_points(analysis: QuestionAnalysis, profile: dict) -> list[str]:
    available = {
        "문제": profile.get("problem"),
        "판단": profile.get("decision") or profile.get("decision_reason"),
        "행동": profile.get("actions"),
        "결과": profile.get("result") or profile.get("quantitative_results"),
        "배운 점": profile.get("lessons"),
        "협업": profile.get("soft_skills") or profile.get("ownership_notes"),
    }
    return [name for name, value in available.items() if value]


def _preference(experience: dict, target_role: str) -> dict:
    return next(
        (item for item in experience["preferences"] if item["target_role"].casefold() == target_role.casefold()),
        next((item for item in experience["preferences"] if item["target_role"] == "공통"), {}),
    )


def _word_overlap(left: str, right: str) -> float:
    left_words = _words(left)
    right_words = _words(right)
    return len(left_words & right_words) / len(left_words) if left_words else 0.0


def _words(value: str) -> set[str]:
    return set(re.findall(r"[0-9a-z가-힣]{2,}", value.casefold()))


def _reason(
    question_type: str,
    experience_name: str,
    points: list[str],
    company: str,
    job_title: str,
) -> str:
    if question_type == "지원동기":
        return (
            f"{company} {job_title}에 대한 관심과 기여 방향을 먼저 설명하고, "
            f"{experience_name}은 그 연결을 증명하는 근거로 사용하세요."
        )
    return f"{experience_name}은(는) {question_type} 문항에 필요한 {', '.join(points[:4]) or '경험 근거'}를 포함합니다."
