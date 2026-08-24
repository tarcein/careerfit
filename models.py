from typing import Literal

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    source_file: str = ""
    quote: str = ""


class ExperienceData(BaseModel):
    experience_name: str = ""
    category: str = ""
    period: str = ""
    summary: str = ""
    role: str = ""
    team_or_individual: str = "확인 필요"
    problem: str = ""
    problem_context: str = ""
    decision: str = ""
    decision_reason: str = ""
    actions: list[str] = Field(default_factory=list)
    result: str = ""
    quantitative_results: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    technical_skills: list[str] = Field(default_factory=list)
    soft_skills: list[str] = Field(default_factory=list)
    domain: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)
    source_files: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    ownership_notes: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ExperienceBatch(BaseModel):
    experiences: list[ExperienceData]


class ProfileData(BaseModel):
    nickname: str = ""
    target_role: str = ""
    industries: str = ""
    major: str = ""
    education: str = ""
    certifications: str = ""
    languages: str = ""
    technical_skills: str = ""
    courses: str = ""
    activities: str = ""
    role_description: str = ""


class PersonalMaterial(BaseModel):
    category: str = "기타"
    title: str = ""
    context: str = ""
    memorable_point: str = ""
    insight: str = ""
    changed_action: str = ""
    keywords: str = ""


class ExperiencePreference(BaseModel):
    target_role: str = "공통"
    user_preference: str = ""
    do_not_use: str = ""
    preferred_focus: str = ""
    ownership_notes: str = ""


class JDSkill(BaseModel):
    name: str
    importance: float = Field(default=0.7, ge=0.0, le=1.0)
    evidence: str = ""


class JDAnalysis(BaseModel):
    company: str = ""
    job_title: str = ""
    main_tasks: list[str] = Field(default_factory=list)
    required_skills: list[JDSkill] = Field(default_factory=list)
    preferred_skills: list[JDSkill] = Field(default_factory=list)
    technical_skills: list[JDSkill] = Field(default_factory=list)
    domain_knowledge: list[JDSkill] = Field(default_factory=list)
    behavioral_skills: list[JDSkill] = Field(default_factory=list)
    tools: list[JDSkill] = Field(default_factory=list)
    experience_requirements: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    important_sentences: list[str] = Field(default_factory=list)


class RecommendationExplanation(BaseModel):
    experience_id: int
    reason: str = ""
    jd_evidence: list[str] = Field(default_factory=list)
    experience_evidence: list[str] = Field(default_factory=list)
    caution: str = ""


class RecommendationExplanationBatch(BaseModel):
    explanations: list[RecommendationExplanation]


class QuestionAnalysis(BaseModel):
    question_type: str = "기타"
    evaluation_intent: list[str] = Field(default_factory=list)
    important_points: list[str] = Field(default_factory=list)
    recommended_experience_type: list[str] = Field(default_factory=list)
    required_story_elements: list[str] = Field(default_factory=list)
    avoid_points: list[str] = Field(default_factory=list)


class OutlineSection(BaseModel):
    order: int = Field(ge=1)
    title: str
    content: str = ""


class EssayOutline(BaseModel):
    framework: str = "STAR"
    key_message: str = ""
    sections: list[OutlineSection] = Field(default_factory=list)
    evidence_used: list[str] = Field(default_factory=list)
    fact_cautions: list[str] = Field(default_factory=list)
    experience_ids: list[int] = Field(default_factory=list)
    material_ids: list[int] = Field(default_factory=list)


class EssayDraftOutput(BaseModel):
    content: str


class FactCheckItem(BaseModel):
    sentence: str
    status: Literal["Verified", "Needs Review", "Unsupported"]
    evidence: list[str] = Field(default_factory=list)
    reason: str = ""
