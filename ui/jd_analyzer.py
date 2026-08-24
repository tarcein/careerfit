import os
from html import escape

import streamlit as st

from db import (
    delete_job_description,
    get_job_description,
    get_match_results,
    get_profile,
    get_verified_experiences,
    list_job_descriptions,
    save_job_description,
    save_match_results,
    update_job_description,
)
from models import JDAnalysis, JDSkill
from services.ai_service import analyze_jd
from services.matching import build_gap_analysis, build_matching_report
from ui import page_header


SKILL_GROUPS = (
    ("required_skills", "필수 역량"),
    ("preferred_skills", "우대 역량"),
    ("technical_skills", "기술 스택"),
    ("domain_knowledge", "도메인 지식"),
    ("behavioral_skills", "협업·행동 역량"),
    ("tools", "도구"),
)


def render(user_id: int) -> None:
    page_header("Job intelligence", "JD 분석 리포트", "채용공고의 핵심 요구사항을 구조화하고 내 경험과 근거 중심으로 비교합니다.")
    st.markdown(
        '<div class="cf-flow"><span><b>1</b> 공고 입력</span><i>›</i><span><b>2</b> 요구역량 구조화</span>'
        '<i>›</i><span><b>3</b> 경험 매칭</span><i>›</i><span><b>4</b> Gap 확인</span></div>',
        unsafe_allow_html=True,
    )
    input_tab, analysis_tab = st.tabs(["JD 등록", "분석 리포트"])
    with input_tab:
        _render_input(user_id)
    with analysis_tab:
        _render_analysis(user_id)


def _render_input(user_id: int) -> None:
    with st.form("new_jd"):
        left, right = st.columns(2)
        company = left.text_input("회사명")
        job_title = right.text_input("지원 직무")
        raw_text = st.text_area("채용공고 전체 내용", height=360)
        submitted = st.form_submit_button("JD 분석 및 저장", type="primary", use_container_width=True)
    if not os.getenv("OPENAI_API_KEY"):
        st.info("OPENAI_API_KEY가 없어 명시된 기술과 필수·우대 문구를 찾는 로컬 분석기를 사용합니다.")
    if submitted:
        try:
            with st.spinner("채용공고를 구조화하고 있습니다..."):
                analysis, used_ai = analyze_jd(company, job_title, raw_text, user_id)
                jd_id = save_job_description(analysis, raw_text, user_id)
            st.success(f"{'AI' if used_ai else '로컬'} 분석 결과를 저장했습니다. JD #{jd_id}")
        except Exception as exc:
            st.error(f"JD 분석에 실패했습니다: {exc}")


def _render_analysis(user_id: int) -> None:
    jobs = list_job_descriptions(user_id)
    if not jobs:
        st.info("먼저 새 JD를 분석하세요.")
        return
    labels = {f"{item['company']} · {item['job_title']} (#{item['id']})": item["id"] for item in jobs}
    selected = st.selectbox("채용공고 선택", labels)
    detail = get_job_description(labels[selected], user_id)
    if not detail:
        st.error("채용공고를 찾을 수 없습니다.")
        return
    current = JDAnalysis.model_validate(detail["analysis"])
    candidate_profile = get_profile(user_id)
    report_tab, management_tab = st.tabs(["리포트", "수정 · 관리"])
    with report_tab:
        _render_jd_report(detail, current, candidate_profile, user_id)
    with management_tab:
        _render_jd_management(detail, current, user_id)


def _render_jd_report(detail: dict, current: JDAnalysis, candidate_profile, user_id: int) -> None:
    _render_jd_summary(current)
    st.markdown("### 내 경험 매칭")
    st.caption("JD 요구사항과 Verified 경험, My Profile 근거를 함께 비교합니다.")
    verified = get_verified_experiences(user_id)
    if not verified:
        st.warning("먼저 My Experiences에서 경험 버전을 승인해 Verified 상태로 만들어 주세요.")
        return
    use_ai_reason = st.checkbox(
        "추천 이유를 AI로 보강",
        value=bool(os.getenv("OPENAI_API_KEY")),
        disabled=not os.getenv("OPENAI_API_KEY"),
        help="점수와 순위는 Python이 계산하며 AI는 근거 설명만 작성합니다.",
    )
    report: dict | None = None
    if st.button("TOP3 추천 및 Gap Analysis 실행", type="primary", use_container_width=True):
        with st.spinner("Verified 경험을 비교하고 있습니다..."):
            report = build_matching_report(
                detail["id"], current, verified, use_ai_reason, user_id, candidate_profile=candidate_profile
            )
            save_match_results(detail["id"], report["matches"], user_id)
        st.success(f"추천 계산을 완료했습니다. 의미 유사도: {report['semantic_mode']}")

    saved_matches = get_match_results(detail["id"], user_id)
    if report:
        matches, gaps = report["matches"], report["gaps"]
    else:
        matches, gaps = (
            saved_matches,
            build_gap_analysis(current, verified, candidate_profile) if saved_matches else [],
        )
    if not matches:
        st.info("추천 실행 버튼을 눌러 경험 TOP3를 계산하세요.")
        return
    _render_matches(matches)
    st.markdown("### 역량 Gap")
    _render_gaps(gaps)


def _render_jd_management(detail: dict, current: JDAnalysis, user_id: int) -> None:
    st.markdown("### 분석 결과 수정")
    st.caption("AI가 구조화한 항목이 원문과 다르면 여기에서 직접 고칠 수 있습니다.")
    with st.form(f"jd_editor_{detail['id']}"):
        left, right = st.columns(2)
        company = left.text_input("회사명", current.company)
        job_title = right.text_input("지원 직무", current.job_title)
        raw_text = st.text_area("채용공고 원문", detail["raw_text"], height=220)
        main_tasks = st.text_area("주요 업무 (한 줄에 하나)", _join(current.main_tasks), height=120)
        skill_values: dict[str, str] = {}
        columns = st.columns(2)
        for index, (field, label) in enumerate(SKILL_GROUPS):
            with columns[index % 2]:
                skill_values[field] = st.text_area(
                    f"{label} · 이름 | 중요도 | 근거", _skills_text(getattr(current, field)), height=130
                )
        experience_requirements = st.text_area(
            "경력 요건 (한 줄에 하나)", _join(current.experience_requirements), height=90
        )
        keywords = st.text_area("핵심 키워드 (한 줄에 하나)", _join(current.keywords), height=90)
        important_sentences = st.text_area(
            "중요 문장 (한 줄에 하나)", _join(current.important_sentences), height=110
        )
        save = st.form_submit_button("수정 결과 저장", type="primary", use_container_width=True)
    if save:
        try:
            updated = JDAnalysis(
                company=company.strip(),
                job_title=job_title.strip(),
                main_tasks=_lines(main_tasks),
                **{field: _parse_skills(value) for field, value in skill_values.items()},
                experience_requirements=_lines(experience_requirements),
                keywords=_lines(keywords),
                important_sentences=_lines(important_sentences),
            )
            if not updated.company or not updated.job_title or not raw_text.strip():
                raise ValueError("회사명, 지원 직무, 채용공고 원문은 비워둘 수 없습니다.")
            update_job_description(detail["id"], updated, raw_text, user_id)
            st.success("수정된 JD 분석 결과를 저장했습니다.")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    st.markdown("### 위험 영역")
    with st.expander("JD와 연결 데이터 삭제"):
        st.warning("이 JD의 문항, 추천 결과, 개요, Draft와 Fact Check가 함께 삭제됩니다.")
        confirmed = st.checkbox("이 JD와 연결 데이터를 영구 삭제합니다.", key=f"delete_jd_confirm_{detail['id']}")
        if st.button(
            "JD 영구 삭제", disabled=not confirmed, use_container_width=True, key=f"delete_jd_{detail['id']}"
        ):
            delete_job_description(detail["id"], user_id)
            st.session_state["delete_notice"] = (
                "JD와 연결된 문항·추천·개요·Draft·Fact Check를 삭제했습니다. 복구할 수 없습니다."
            )
            st.rerun()


def _render_jd_summary(jd: JDAnalysis) -> None:
    st.markdown(
        f"""<div class="cf-jd-hero"><div><div class="cf-jd-eyebrow">Selected job description</div>
        <div class="cf-jd-title">{escape(jd.company)} · {escape(jd.job_title)}</div></div></div>""",
        unsafe_allow_html=True,
    )
    metrics = st.columns(4)
    metrics[0].metric("주요 업무", len(jd.main_tasks))
    metrics[1].metric("필수 역량", len(jd.required_skills))
    metrics[2].metric("우대 역량", len(jd.preferred_skills))
    metrics[3].metric("기술·도구", len(jd.technical_skills) + len(jd.tools))

    sections = [
        ("주요 업무", jd.main_tasks, False),
        ("필수 역량", [item.name for item in jd.required_skills], True),
        ("우대 역량", [item.name for item in jd.preferred_skills], True),
        ("기술 스택 · 도구", [item.name for item in jd.technical_skills + jd.tools], True),
        ("도메인 · 협업", [item.name for item in jd.domain_knowledge + jd.behavioral_skills], True),
        ("핵심 키워드", jd.keywords, True),
    ]
    for index in range(0, len(sections), 2):
        columns = st.columns(2)
        for column, (title, items, use_chips) in zip(columns, sections[index : index + 2]):
            with column:
                st.markdown(_summary_card(title, items, use_chips), unsafe_allow_html=True)


def _summary_card(title: str, items: list[str], use_chips: bool) -> str:
    if not items:
        content = '<span class="cf-empty">분석된 항목 없음</span>'
    elif use_chips:
        content = "".join(f'<span class="cf-chip">{escape(item)}</span>' for item in items)
    else:
        content = "<ul>" + "".join(f"<li>{escape(item)}</li>" for item in items) + "</ul>"
    return f'<div class="cf-jd-card"><div class="cf-jd-card-title">{escape(title)}</div>{content}</div>'


def _render_matches(matches: list[dict]) -> None:
    score_labels = {
        "semantic_similarity": "의미 유사도",
        "required_skill_coverage": "필수 역량 충족",
        "technical_skill_match": "기술 역량 일치",
        "relevant_result": "성과 관련성",
        "evidence_reliability": "근거 신뢰도",
    }
    for match in matches:
        with st.container(border=True):
            heading, score = st.columns([5, 1])
            heading.markdown(f'<span class="cf-rank">TOP {match["rank"]}</span>', unsafe_allow_html=True)
            heading.markdown(f"#### {match['experience_name']}")
            score.metric("Fit score", f"{match['score']:.1f}")
            breakdown = match["breakdown"]
            st.progress(min(float(match["score"]) / 100, 1.0))
            left, right = st.columns(2)
            left.markdown("**일치하는 역량**")
            left.markdown(_chips(match.get("matching_skills", [])), unsafe_allow_html=True)
            if match.get("profile_matching_skills"):
                left.caption("My Profile에서 확인: " + ", ".join(match["profile_matching_skills"]))
            right.markdown("**보완할 역량**")
            right.markdown(_chips(match.get("missing_skills", []), missing=True), unsafe_allow_html=True)
            explanation = match["explanation"]
            st.markdown("**왜 이 경험인가요?**")
            st.write(explanation.get("reason", ""))
            if match.get("preferred_focus"):
                st.info("Preferred Focus: " + match["preferred_focus"])
            if explanation.get("caution"):
                st.warning("주의: " + explanation["caution"])
            with st.expander("점수와 근거 자세히 보기"):
                st.dataframe(
                    [{"평가 항목": score_labels.get(key, key), "점수": value} for key, value in breakdown.items()],
                    hide_index=True,
                    use_container_width=True,
                )
                if explanation.get("jd_evidence"):
                    st.caption("JD 근거: " + " / ".join(explanation["jd_evidence"]))
                if explanation.get("experience_evidence"):
                    st.caption("경험 근거: " + " / ".join(explanation["experience_evidence"]))
                if explanation.get("profile_evidence"):
                    st.caption("프로필 근거: " + " / ".join(explanation["profile_evidence"]))


def _render_gaps(gaps: list[dict]) -> None:
    settings = {
        "Strong": ("근거 충분", "strong"),
        "Partial": ("부분 근거", "partial"),
        "Missing": ("준비 필요", "missing"),
    }
    columns = st.columns(3)
    for column, (status, (label, class_name)) in zip(columns, settings.items()):
        items = [item for item in gaps if item["status"] == status]
        content = "".join(
            f'<div class="cf-gap-item"><div class="cf-gap-skill">{escape(item["skill"])}</div>'
            f'<div class="cf-gap-evidence">{escape(" · ".join(item.get("evidence", [])) or "확인 근거 없음")}</div></div>'
            for item in items
        ) or '<span class="cf-empty">해당 역량 없음</span>'
        with column:
            st.markdown(
                f'<div class="cf-gap-card cf-gap-{class_name}"><div class="cf-gap-title">{label}'
                f'<span class="cf-gap-count">{len(items)}</span></div>{content}</div>',
                unsafe_allow_html=True,
            )


def _chips(items: list[str], missing: bool = False) -> str:
    if not items:
        return '<span class="cf-empty">없음</span>'
    class_name = "cf-chip cf-chip-missing" if missing else "cf-chip"
    return "".join(f'<span class="{class_name}">{escape(item)}</span>' for item in items)


def _skills_text(skills: list[JDSkill]) -> str:
    return "\n".join(f"{skill.name} | {skill.importance:g} | {skill.evidence}" for skill in skills)


def _parse_skills(value: str) -> list[JDSkill]:
    skills: list[JDSkill] = []
    for line_number, line in enumerate(_lines(value), start=1):
        parts = [part.strip() for part in line.split("|", 2)]
        try:
            importance = float(parts[1]) if len(parts) > 1 and parts[1] else 0.7
        except ValueError as exc:
            raise ValueError(f"역량 {line_number}번째 줄의 중요도는 0~1 숫자여야 합니다.") from exc
        if not 0 <= importance <= 1:
            raise ValueError(f"역량 {line_number}번째 줄의 중요도는 0~1 범위여야 합니다.")
        skills.append(JDSkill(name=parts[0], importance=importance, evidence=parts[2] if len(parts) > 2 else ""))
    return skills


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _join(values: list[str]) -> str:
    return "\n".join(values)
