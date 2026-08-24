import hashlib
import math
import os
import re

from config import EMBEDDING_MODEL, MATCH_WEIGHTS
from db import get_cached_embedding, save_embedding
from models import JDAnalysis, JDSkill, ProfileData
from services.ai_service import create_embeddings, explain_recommendations


def build_matching_report(
    jd_id: int,
    jd: JDAnalysis,
    experiences: list[dict],
    use_ai_explanations: bool = True,
    user_id: int = 1,
    limit: int | None = 3,
    candidate_profile: ProfileData | None = None,
) -> dict:
    if not experiences:
        return {"matches": [], "gaps": [], "semantic_mode": "unavailable"}

    jd_text = _jd_text(jd)
    profile_text = _candidate_profile_text(candidate_profile)
    prepared = [_prepare_experience(item, jd.job_title, profile_text) for item in experiences]
    exp_texts = [item["text"] for item in prepared]
    semantic_scores, semantic_mode = _semantic_scores(jd_id, jd_text, prepared, exp_texts, user_id)

    matches: list[dict] = []
    required = _unique_skills(jd.required_skills)
    technical = _unique_skills(jd.technical_skills + jd.tools)
    all_relevant = _unique_skills(required + technical + jd.preferred_skills + jd.domain_knowledge)

    for item, semantic in zip(prepared, semantic_scores):
        profile = item["profile"]
        matching = [skill.name for skill in all_relevant if _contains_skill(item["text"], skill.name)]
        experience_matching = [skill for skill in matching if _contains_skill(item["experience_text"], skill)]
        profile_matching = [skill for skill in matching if skill not in experience_matching]
        missing = [skill.name for skill in required if skill.name not in matching]
        required_ratio = _weighted_coverage(required, item["text"])
        technical_ratio = _weighted_coverage(technical, item["text"])
        result_ratio = 1.0 if profile.get("quantitative_results") else (0.6 if profile.get("result") else 0.0)
        evidence_ratio = min(
            1.0,
            float(profile.get("confidence", 0)) * 0.5 + min(len(item["facts"]), 3) / 3 * 0.5,
        )
        breakdown = {
            "semantic_similarity": round(semantic * MATCH_WEIGHTS["semantic_similarity"], 2),
            "required_skill_coverage": round(required_ratio * MATCH_WEIGHTS["required_skill_coverage"], 2),
            "technical_skill_match": round(technical_ratio * MATCH_WEIGHTS["technical_skill_match"], 2),
            "relevant_result": round(result_ratio * MATCH_WEIGHTS["relevant_result"], 2),
            "evidence_reliability": round(evidence_ratio * MATCH_WEIGHTS["evidence_reliability"], 2),
        }
        score = round(sum(breakdown.values()), 2)
        evidence = [fact["evidence_text"] for fact in item["facts"][:3]]
        explanation = {
            "reason": _basic_reason(item["experience_name"], experience_matching, missing)
            + (f" My Profile의 {', '.join(profile_matching[:4])} 정보도 반영했습니다." if profile_matching else ""),
            "jd_evidence": [skill.evidence for skill in all_relevant if skill.name in matching and skill.evidence][:3],
            "experience_evidence": evidence,
            "caution": item["preference"].get("ownership_notes", "") or profile.get("ownership_notes", ""),
            "profile_evidence": _candidate_profile_evidence(candidate_profile),
        }
        matches.append(
            {
                "experience_id": item["id"],
                "experience_name": item["experience_name"],
                "score": score,
                "breakdown": breakdown,
                "matching_skills": matching,
                "profile_matching_skills": profile_matching,
                "missing_skills": missing,
                "preferred_focus": item["preference"].get("preferred_focus", ""),
                "explanation": explanation,
                "_candidate": {
                    "experience_id": item["id"],
                    "score": score,
                    "matching_skills": matching,
                    "missing_skills": missing,
                    "profile": {
                        key: profile.get(key)
                        for key in ("summary", "role", "problem", "actions", "result", "quantitative_results", "ownership_notes")
                    },
                    "evidence": evidence,
                    "preference": item["preference"],
                    "candidate_profile": candidate_profile.model_dump() if candidate_profile else {},
                },
            }
        )

    matches.sort(key=lambda item: item["score"], reverse=True)
    top = matches if limit is None else matches[:limit]
    if use_ai_explanations and os.getenv("OPENAI_API_KEY"):
        try:
            ai_explanations = explain_recommendations(jd, [item["_candidate"] for item in top], user_id)
            for item in top:
                if item["experience_id"] in ai_explanations:
                    item["explanation"] = ai_explanations[item["experience_id"]] | {
                        "experience_id": item["experience_id"],
                        "profile_evidence": _candidate_profile_evidence(candidate_profile),
                    }
        except Exception:
            pass

    for rank, item in enumerate(top, start=1):
        item["rank"] = rank
        item.pop("_candidate", None)
    return {
        "matches": top,
        "gaps": _gap_analysis(_unique_skills(required + technical + jd.domain_knowledge), prepared),
        "semantic_mode": semantic_mode,
    }


def build_gap_analysis(
    jd: JDAnalysis, experiences: list[dict], candidate_profile: ProfileData | None = None
) -> list[dict]:
    profile_text = _candidate_profile_text(candidate_profile)
    prepared = [_prepare_experience(item, jd.job_title, profile_text) for item in experiences]
    skills = _unique_skills(jd.required_skills + jd.technical_skills + jd.tools + jd.domain_knowledge)
    return _gap_analysis(skills, prepared)


def _semantic_scores(
    jd_id: int, jd_text: str, experiences: list[dict], exp_texts: list[str], user_id: int
) -> tuple[list[float], str]:
    if not os.getenv("OPENAI_API_KEY"):
        return [_lexical_similarity(jd_text, text) for text in exp_texts], "lexical fallback"
    entities = [("job_description", jd_id, jd_text)] + [
        ("experience_version", item["version_id"], item["text"]) for item in experiences
    ]
    vectors: list[list[float] | None] = []
    missing_indexes: list[int] = []
    for index, (entity_type, entity_id, text) in enumerate(entities):
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        vector = get_cached_embedding(entity_type, entity_id, EMBEDDING_MODEL, content_hash, user_id)
        vectors.append(vector)
        if vector is None:
            missing_indexes.append(index)
    try:
        if missing_indexes:
            generated = create_embeddings([entities[index][2] for index in missing_indexes], user_id)
            for index, vector in zip(missing_indexes, generated):
                entity_type, entity_id, text = entities[index]
                content_hash = hashlib.sha256(text.encode()).hexdigest()
                save_embedding(entity_type, entity_id, EMBEDDING_MODEL, content_hash, vector, user_id)
                vectors[index] = vector
        jd_vector = vectors[0]
        if jd_vector is None:
            raise ValueError("JD embedding이 없습니다.")
        return [_cosine(jd_vector, vector or []) for vector in vectors[1:]], "OpenAI embedding"
    except Exception:
        return [_lexical_similarity(jd_text, text) for text in exp_texts], "lexical fallback"


def _prepare_experience(experience: dict, target_role: str, candidate_profile_text: str = "") -> dict:
    preferences = experience["preferences"]
    preference = next(
        (item for item in preferences if item["target_role"].casefold() == target_role.casefold()),
        next((item for item in preferences if item["target_role"] == "공통"), {}),
    )
    profile = experience["profile"]
    parts: list[str] = []
    for key in (
        "experience_name", "category", "summary", "role", "problem", "problem_context", "decision",
        "decision_reason", "actions", "result", "quantitative_results", "tools", "technical_skills",
        "soft_skills", "domain", "keywords", "lessons",
    ):
        value = profile.get(key, "")
        parts.extend(value if isinstance(value, list) else [value])
    parts.extend([preference.get("user_preference", ""), preference.get("preferred_focus", "")])
    experience_text = "\n".join(str(part) for part in parts if part)
    for forbidden in preference.get("do_not_use", "").splitlines():
        if forbidden.strip():
            experience_text = experience_text.replace(forbidden.strip(), "")
    text = "\n".join(filter(None, [experience_text, candidate_profile_text]))
    return experience | {
        "text": text,
        "experience_text": experience_text,
        "candidate_profile_text": candidate_profile_text,
        "preference": preference,
    }


def _candidate_profile_text(profile: ProfileData | None) -> str:
    if not profile:
        return ""
    return "\n".join(str(value) for key, value in profile.model_dump().items() if key != "nickname" and value)


def _candidate_profile_evidence(profile: ProfileData | None) -> list[str]:
    if not profile:
        return []
    labels = {
        "major": "전공",
        "education": "학력",
        "certifications": "자격증",
        "languages": "어학",
        "technical_skills": "기술 스택",
        "courses": "교육 과정",
    }
    return [f"{labels[key]}: {getattr(profile, key)}" for key in labels if getattr(profile, key)]


def _jd_text(jd: JDAnalysis) -> str:
    skills = jd.required_skills + jd.preferred_skills + jd.technical_skills + jd.domain_knowledge + jd.behavioral_skills + jd.tools
    return "\n".join(jd.main_tasks + [item.name for item in skills] + jd.keywords + jd.important_sentences)


def _weighted_coverage(skills: list[JDSkill], text: str) -> float:
    total = sum(skill.importance for skill in skills)
    return sum(skill.importance for skill in skills if _contains_skill(text, skill.name)) / total if total else 0.0


def _contains_skill(text: str, skill: str) -> bool:
    compact_text, compact_skill = _compact(text), _compact(skill)
    return bool(compact_skill and compact_skill in compact_text)


def _lexical_similarity(left: str, right: str) -> float:
    left_grams, right_grams = _ngrams(left), _ngrams(right)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / len(left_grams | right_grams)


def _ngrams(text: str) -> set[str]:
    compact = _compact(text)
    return {compact[index : index + 2] for index in range(max(0, len(compact) - 1))}


def _compact(text: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]+", "", text.casefold())


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    denominator = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(x * x for x in right))
    return max(0.0, min(1.0, sum(x * y for x, y in zip(left, right)) / denominator)) if denominator else 0.0


def _unique_skills(skills: list[JDSkill]) -> list[JDSkill]:
    return list({skill.name.casefold(): skill for skill in skills if skill.name.strip()}.values())


def _basic_reason(experience_name: str, matching: list[str], missing: list[str]) -> str:
    if matching:
        return f"{experience_name}에서 {', '.join(matching[:4])} 관련 근거가 확인되어 추천했습니다."
    return f"{experience_name}은 의미 유사도와 결과·근거 신뢰도를 기준으로 비교했습니다."


def _gap_analysis(skills: list[JDSkill], experiences: list[dict]) -> list[dict]:
    gaps: list[dict] = []
    for skill in skills:
        strong = [
            item["experience_name"] for item in experiences if _contains_skill(item["experience_text"], skill.name)
        ]
        profile_strong = bool(experiences and _contains_skill(experiences[0]["candidate_profile_text"], skill.name))
        partial = [
            item["experience_name"]
            for item in experiences
            if item["experience_name"] not in strong
            and _lexical_similarity(item["experience_text"], skill.name) >= 0.08
        ]
        profile_partial = bool(
            experiences
            and not profile_strong
            and _lexical_similarity(experiences[0]["candidate_profile_text"], skill.name) >= 0.08
        )
        status = "Strong" if strong or profile_strong else ("Partial" if partial or profile_partial else "Missing")
        evidence = [*strong, *(["My Profile"] if profile_strong else [])] or [
            *partial,
            *(["My Profile"] if profile_partial else []),
        ]
        gaps.append({"skill": skill.name, "status": status, "evidence": evidence})
    return gaps
