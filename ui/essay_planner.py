import os
from html import escape

import streamlit as st

from db import (
    approve_essay_outline,
    count_experience_uses,
    delete_essay_draft,
    delete_essay_outline,
    delete_essay_question,
    get_essay_question,
    get_fact_check_results,
    get_job_description,
    get_outline_context,
    get_profile,
    get_question_match_results,
    get_verified_experiences,
    list_personal_materials,
    list_approved_outlines,
    list_essay_drafts,
    list_essay_outlines,
    list_essay_questions,
    list_job_descriptions,
    save_essay_outline,
    save_essay_draft,
    save_essay_question,
    save_fact_check_results,
    save_question_match_results,
    update_essay_question,
)
from models import EssayOutline, FactCheckItem, JDAnalysis, OutlineSection, QuestionAnalysis
from services.ai_service import (
    MissingAPIKeyError,
    analyze_question,
    generate_essay_draft,
    generate_essay_outline,
    revise_essay_draft,
    revise_essay_outline,
)
from services.question_matching import (
    build_personal_material_report,
    build_question_matching_report,
    is_personal_question,
)
from services.application_review import evaluate_application, fact_check_draft
from ui import page_header


QUESTION_TYPES = [
    "지원동기", "직무역량", "문제해결", "도전", "협업", "갈등", "성장과정", "가치관",
    "성격 장단점", "입사 후 포부", "기타",
]


def render(user_id: int) -> None:
    page_header("Application studio", "자기소개서 설계", "문항 의도부터 경험 선택, 개요, 초안, 사실 검증까지 한 흐름으로 진행합니다.")
    jobs = list_job_descriptions(user_id)
    if not jobs:
        st.warning("먼저 JD Analyzer에서 채용공고를 분석하세요.")
        return
    labels = {f"{job['company']} · {job['job_title']} (#{job['id']})": job["id"] for job in jobs}
    question_tab, matching_tab, outline_tab, draft_tab = st.tabs(
        ["문항 등록", "문항 분석 · 경험 추천", "Outline Editor", "Draft · Fact Check"]
    )
    with question_tab:
        _render_question_input(labels, user_id)
    with matching_tab:
        _render_question_matching(labels, user_id)
    with outline_tab:
        _render_outline_editor(labels, user_id)
    with draft_tab:
        _render_draft_review(user_id)


def _render_question_input(job_labels: dict[str, int], user_id: int) -> None:
    selected = st.selectbox("대상 JD", job_labels, key="question_input_jd")
    jd = get_job_description(job_labels[selected], user_id)
    with st.form("new_essay_question"):
        question = st.text_area("자기소개서 문항", height=150)
        character_limit = st.number_input("글자 수 제한 (없으면 0)", min_value=0, step=50)
        note = st.text_area("추가 안내", height=80)
        submit = st.form_submit_button("문항 분석 및 저장", type="primary", use_container_width=True)
    if not os.getenv("OPENAI_API_KEY"):
        st.info("API 키가 없으면 문항 표현을 기준으로 로컬 의도 분석을 사용합니다.")
    if submit:
        try:
            analysis, used_ai = analyze_question(
                question, note, JDAnalysis.model_validate(jd["analysis"]), user_id
            )
            question_id = save_essay_question(
                jd["id"], question, int(character_limit) or None, note, analysis, user_id
            )
            st.success(f"{'AI' if used_ai else '로컬'} 분석으로 문항 #{question_id}을 저장했습니다.")
        except Exception as exc:
            st.error(f"문항 분석에 실패했습니다: {exc}")


def _render_question_matching(job_labels: dict[str, int], user_id: int) -> None:
    selected = st.selectbox("대상 JD", job_labels, key="question_match_jd")
    jd = get_job_description(job_labels[selected], user_id)
    questions = list_essay_questions(jd["id"], user_id)
    if not questions:
        st.info("선택한 JD에 등록된 문항이 없습니다.")
        return
    labels = {f"#{item['id']} · {item['question'][:60]}": item["id"] for item in questions}
    selected_question = st.selectbox("문항", labels, key="question_match_question")
    question = get_essay_question(labels[selected_question], user_id)
    analysis = QuestionAnalysis.model_validate(question["analysis"])
    candidate_profile = get_profile(user_id)
    _render_question_analysis_summary(question, analysis)

    with st.expander("분석 내용 수정"):
        with st.form(f"question_editor_{question['id']}"):
            question_text = st.text_area("문항", question["question"], height=120)
            optional_note = st.text_area("추가 안내", question["optional_note"], height=70)
            type_col, limit_col = st.columns(2)
            question_type = type_col.selectbox(
                "문항 유형", QUESTION_TYPES,
                index=QUESTION_TYPES.index(analysis.question_type) if analysis.question_type in QUESTION_TYPES else len(QUESTION_TYPES) - 1,
            )
            character_limit = limit_col.number_input(
                "글자 수 제한 (없으면 0)", min_value=0, value=question["character_limit"] or 0, step=50
            )
            left, right = st.columns(2)
            evaluation_intent = left.text_area("평가 의도", _join(analysis.evaluation_intent), height=110)
            important_points = right.text_area("중요 포인트", _join(analysis.important_points), height=110)
            experience_type = left.text_area(
                "추천 경험 유형", _join(analysis.recommended_experience_type), height=100
            )
            story_elements = right.text_area("필수 이야기 요소", _join(analysis.required_story_elements), height=100)
            avoid_points = st.text_area("피해야 할 내용", _join(analysis.avoid_points), height=90)
            save = st.form_submit_button("문항 분석 수정 저장", use_container_width=True)
        if save:
            updated = QuestionAnalysis(
                question_type=question_type,
                evaluation_intent=_lines(evaluation_intent),
                important_points=_lines(important_points),
                recommended_experience_type=_lines(experience_type),
                required_story_elements=_lines(story_elements),
                avoid_points=_lines(avoid_points),
            )
            update_essay_question(
                question["id"], question_text, int(character_limit) or None, optional_note, updated, user_id
            )
            st.success("문항 분석을 수정했습니다.")
            st.rerun()

    with st.expander("문항 삭제"):
        st.warning("이 문항의 추천 결과, 개요, Draft와 Fact Check가 함께 삭제됩니다.")
        confirmed = st.checkbox(
            "이 문항과 연결 데이터를 영구 삭제합니다.", key=f"delete_question_confirm_{question['id']}"
        )
        if st.button(
            "문항 영구 삭제",
            disabled=not confirmed,
            use_container_width=True,
            key=f"delete_question_{question['id']}",
        ):
            delete_essay_question(question["id"], user_id)
            st.session_state["delete_notice"] = (
                "문항과 연결된 추천·개요·Draft·Fact Check를 삭제했습니다. 복구할 수 없습니다."
            )
            st.rerun()

    verified = get_verified_experiences(user_id)
    materials = list_personal_materials(user_id)
    if is_personal_question(question["question"], analysis):
        _render_personal_matching(jd, question, analysis, candidate_profile, verified, materials, user_id)
        return
    if not verified:
        st.warning("Verified 경험이 없습니다.")
        return
    st.markdown(
        """<div class="cf-section-head"><div><div class="cf-section-kicker">Best evidence</div>
        <div class="cf-section-title">문항에 맞는 경험 추천</div></div>
        <div class="cf-section-copy">문항 의도와 JD 적합도, 근거 품질을 함께 계산한 결과입니다.</div></div>""",
        unsafe_allow_html=True,
    )
    report: list[dict] | None = None
    if st.button("문항 기준 TOP3 재추천", type="primary", use_container_width=True):
        report = build_question_matching_report(
            jd["id"], JDAnalysis.model_validate(jd["analysis"]), analysis, verified, user_id, candidate_profile
        )
        save_question_match_results(jd["id"], question["id"], report, user_id)
        st.success("문항 의도를 반영해 경험 순위를 다시 계산했습니다.")

    matches = report or get_question_match_results(question["id"], user_id)
    if not matches:
        st.info("재추천 버튼을 눌러 문항별 경험 TOP3를 계산하세요.")
        return
    _render_question_matches(matches)
    choices = {
        f"{item['rank']}위 · {item['experience_name']} · {item['score']:.1f}점": item["experience_id"]
        for item in matches
    }
    selected_experiences = st.multiselect(
        "개요에 사용할 경험 (첫 번째 선택이 주 경험)",
        choices,
        default=list(choices)[:1],
        max_selections=3,
        help="주 경험 하나를 중심으로 보조 경험을 최대 2개까지 연결합니다.",
    )
    if st.button(
        "선택 경험으로 Essay Outline 생성",
        type="primary",
        disabled=not selected_experiences,
        use_container_width=True,
    ):
        selected_ids = [choices[label] for label in selected_experiences]
        selected = [next(item for item in verified if item["id"] == item_id) for item_id in selected_ids]
        with st.spinner("근거를 확인하며 개요를 생성하고 있습니다..."):
            outline, used_ai = generate_essay_outline(
                JDAnalysis.model_validate(jd["analysis"]), question, selected, user_id, candidate_profile
            )
            save_essay_outline(question["id"], selected[0]["id"], outline, user_id)
        st.success(f"{'AI' if used_ai else '로컬 근거 기반'} 개요를 저장했습니다. Outline Editor에서 검토하세요.")


def _render_question_analysis_summary(question: dict, analysis: QuestionAnalysis) -> None:
    limit = f"{question['character_limit']:,}자" if question["character_limit"] else "제한 없음"
    st.markdown(
        f"""<div class="cf-question-hero"><div class="cf-question-badges">
        <span class="cf-question-type">{escape(analysis.question_type)}</span>
        <span class="cf-question-limit">{limit}</span></div>
        <div class="cf-question-copy">{escape(question['question'])}</div></div>""",
        unsafe_allow_html=True,
    )
    first = st.columns(3)
    _analysis_card(first[0], "평가 의도", analysis.evaluation_intent)
    _analysis_card(first[1], "핵심 포인트", analysis.important_points)
    _analysis_card(first[2], "필수 이야기 요소", analysis.required_story_elements)
    second = st.columns(2)
    _analysis_card(second[0], "추천 경험 유형", analysis.recommended_experience_type)
    _analysis_card(second[1], "피해야 할 내용", analysis.avoid_points, caution=True)


def _analysis_card(column, title: str, items: list[str], caution: bool = False) -> None:
    content = "".join(f"<li>{escape(item)}</li>" for item in items) or "<li>분석된 내용 없음</li>"
    tone = " cf-analysis-card-caution" if caution else ""
    column.markdown(
        f"<div class=\"cf-analysis-card{tone}\"><div class=\"cf-analysis-title\">{title}</div>"
        f"<ul>{content}</ul></div>",
        unsafe_allow_html=True,
    )


def _render_question_matches(matches: list[dict]) -> None:
    score_labels = {
        "jd_fit": "JD 적합도",
        "question_fit": "문항 적합도",
        "evidence_quality": "근거 품질",
        "quantitative_result": "수치 성과",
    }
    for match in matches:
        with st.container(border=True):
            st.markdown(
                f"""<div class="cf-match-head"><div><span class="cf-rank">TOP {match['rank']}</span>
                <span class="cf-match-name">{escape(match['experience_name'])}</span></div>
                <div class="cf-match-score">{match['score']:.1f}<small>/100</small></div></div>
                <div class="cf-match-reason">{escape(match.get('reason', ''))}</div>""",
                unsafe_allow_html=True,
            )
            st.progress(min(float(match["score"]) / 100, 1.0))
            breakdown = "".join(
                f"<div><span>{score_labels.get(key, key)}</span><b>{value:.1f}</b></div>"
                for key, value in match["breakdown"].items()
            )
            st.markdown(f'<div class="cf-match-breakdown">{breakdown}</div>', unsafe_allow_html=True)
            with st.expander("추천 근거 자세히 보기", expanded=match["rank"] == 1):
                left, right = st.columns(2)
                left.markdown("**핵심 에피소드**")
                left.write(match.get("core_episode", "") or "확인된 문제/요약 없음")
                right.markdown("**강조할 행동**")
                right.write(" / ".join(match.get("emphasized_actions", [])) or "확인된 행동 없음")
                if match.get("quantitative_results"):
                    st.caption("사용 가능한 수치: " + " / ".join(match["quantitative_results"]))
                if match.get("job_connection"):
                    st.info("직무 연결: " + match["job_connection"])
                if match.get("evidence"):
                    st.caption("Evidence: " + " / ".join(match["evidence"]))
                if match.get("profile_evidence"):
                    st.caption("My Profile 근거: " + " / ".join(match["profile_evidence"]))
                if match.get("caution"):
                    st.warning("주의: " + match["caution"])


def _render_personal_matching(
    jd: dict,
    question: dict,
    analysis: QuestionAnalysis,
    candidate_profile,
    verified: list[dict],
    materials: list[dict],
    user_id: int,
) -> None:
    st.info("개인 소재형 문항입니다. 프로젝트를 선택하지 않고 개인 소재만으로도 개요를 만들 수 있습니다.")
    if not materials:
        st.warning("My Profile의 개인 소재 보관함에 책·멘토·가치관 등의 소재를 먼저 저장해 주세요.")
        return
    recommendations = build_personal_material_report(question["question"], analysis, materials)
    st.subheader("추천 개인 소재")
    for rank, material in enumerate(recommendations, 1):
        with st.expander(
            f"{rank}위 · {material['category']} · {material['title']} · {material['score']:.1f}점",
            expanded=rank == 1,
        ):
            st.write(material["reason"])
            if material.get("insight"):
                st.markdown("**나에게 준 영향**")
                st.write(material["insight"])
            if material.get("changed_action"):
                st.markdown("**행동 변화**")
                st.write(material["changed_action"])

    material_choices = {
        f"{item['category']} · {item['title']} · {item['score']:.1f}점": item["id"]
        for item in recommendations
    }
    selected_material_labels = st.multiselect(
        "개요에 사용할 개인 소재",
        material_choices,
        default=list(material_choices)[:1],
        max_selections=3,
    )
    experience_choices = {item["experience_name"]: item["id"] for item in verified}
    selected_experience_labels = st.multiselect(
        "프로젝트 경험 추가 (선택사항)",
        experience_choices,
        max_selections=2,
        help="필요한 경우에만 보조 근거로 추가하세요.",
    )
    if st.button(
        "선택 소재로 Essay Outline 생성",
        type="primary",
        disabled=not selected_material_labels,
        use_container_width=True,
    ):
        material_ids = [material_choices[label] for label in selected_material_labels]
        experience_ids = [experience_choices[label] for label in selected_experience_labels]
        selected_materials = [item for item in materials if item["id"] in material_ids]
        selected_experiences = [item for item in verified if item["id"] in experience_ids]
        try:
            with st.spinner("개인 소재를 문항 의도에 맞게 구성하고 있습니다..."):
                outline, used_ai = generate_essay_outline(
                    JDAnalysis.model_validate(jd["analysis"]),
                    question,
                    selected_experiences,
                    user_id,
                    candidate_profile,
                    selected_materials,
                )
                save_essay_outline(
                    question["id"],
                    selected_experiences[0]["id"] if selected_experiences else None,
                    outline,
                    user_id,
                )
            st.success(f"{'AI' if used_ai else '로컬'} 개인 소재 개요를 저장했습니다.")
        except ValueError as exc:
            st.warning(str(exc))


def _render_outline_editor(job_labels: dict[str, int], user_id: int) -> None:
    selected = st.selectbox("대상 JD", job_labels, key="outline_jd")
    jd = get_job_description(job_labels[selected], user_id)
    questions = list_essay_questions(jd["id"], user_id)
    if not questions:
        st.info("등록된 문항이 없습니다.")
        return
    question_labels = {f"#{item['id']} · {item['question'][:60]}": item["id"] for item in questions}
    selected_question = st.selectbox("문항", question_labels, key="outline_question")
    question_id = question_labels[selected_question]
    outlines = list_essay_outlines(question_id, user_id)
    if not outlines:
        st.info("문항별 경험 추천에서 경험을 선택하고 개요를 생성하세요.")
        return
    outline_labels = {
        f"v{item['version_number']} · {item['experience_name']}" + (" · 승인됨" if item["is_approved"] else ""): item
        for item in outlines
    }
    selected_outline = st.selectbox("개요 버전", outline_labels, key="outline_version")
    row = outline_labels[selected_outline]
    current = EssayOutline.model_validate(row["outline"])
    context = get_outline_context(row["id"], user_id)
    if not context:
        st.error("개요에 연결된 경험 또는 개인 소재를 찾을 수 없습니다.")
        return
    experiences = context["experiences"]
    materials = context["materials"]
    source_names = [
        *(f"경험 · {item['experience_name']}" for item in experiences),
        *(f"개인 소재 · {item['title']}" for item in materials),
    ]
    st.caption("사용 소재: " + " → ".join(source_names))

    with st.form(f"outline_editor_{row['id']}"):
        framework_options = ["STAR", "STAR-F", "KKK", "두괄식 + Storytelling"]
        framework = st.selectbox(
            "작성 구조", framework_options, index=framework_options.index(current.framework) if current.framework in framework_options else 0
        )
        key_message = st.text_area("핵심 메시지", current.key_message, height=90)
        sections = st.data_editor(
            [section.model_dump() for section in current.sections],
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "order": st.column_config.NumberColumn("순서", min_value=1, step=1),
                "title": st.column_config.TextColumn("항목", required=True),
                "content": st.column_config.TextColumn("내용", width="large"),
            },
            key=f"outline_sections_{row['id']}",
        )
        st.caption("사용 Evidence: " + (" / ".join(current.evidence_used) or "없음"))
        fact_cautions = st.text_area("사실 및 사용 주의사항", _join(current.fact_cautions), height=100)
        ai_request = st.text_area("AI 수정 요청", placeholder="예: 성과보다 문제를 발견한 과정을 더 강조해줘")
        manual_save = st.form_submit_button("수동 새 버전 저장", use_container_width=True)
        ai_save = st.form_submit_button("AI 수정 새 버전 생성", type="primary", use_container_width=True)

    if manual_save or ai_save:
        try:
            records = sections.to_dict("records") if hasattr(sections, "to_dict") else sections
            ordered = sorted(
                (item for item in records if str(item.get("title", "")).strip()),
                key=lambda item: int(item.get("order") or 999),
            )
            edited = EssayOutline(
                framework=framework,
                key_message=key_message,
                sections=[
                    OutlineSection(order=index, title=str(item["title"]).strip(), content=str(item.get("content", "")))
                    for index, item in enumerate(ordered, 1)
                ],
                evidence_used=current.evidence_used,
                fact_cautions=_lines(fact_cautions),
                experience_ids=current.experience_ids,
                material_ids=current.material_ids,
            )
            if ai_save:
                edited = revise_essay_outline(
                    edited, ai_request, experiences, jd["job_title"], user_id, get_profile(user_id), materials
                )
            save_essay_outline(question_id, row["experience_id"], edited, user_id)
            st.success("새 개요 버전을 저장했습니다.")
            st.rerun()
        except (ValueError, MissingAPIKeyError) as exc:
            st.warning(str(exc))
        except Exception as exc:
            st.error(f"개요 저장에 실패했습니다: {exc}")

    if st.button("선택 개요 버전 승인", type="primary", use_container_width=True):
        approve_essay_outline(row["id"], user_id)
        st.success("개요를 승인했습니다. Phase 4 초안 생성에 사용할 수 있습니다.")
        st.rerun()

    with st.expander("개요 버전 삭제"):
        st.warning("이 개요 버전의 Draft와 Fact Check도 함께 삭제됩니다.")
        confirmed = st.checkbox(
            "선택한 개요 버전을 영구 삭제합니다.", key=f"delete_outline_confirm_{row['id']}"
        )
        if st.button(
            "개요 버전 영구 삭제",
            disabled=not confirmed,
            use_container_width=True,
            key=f"delete_outline_{row['id']}",
        ):
            delete_essay_outline(row["id"], user_id)
            st.session_state["delete_notice"] = (
                "개요 버전과 연결된 Draft·Fact Check를 삭제했습니다. 복구할 수 없습니다."
            )
            st.rerun()


def _render_draft_review(user_id: int) -> None:
    approved = list_approved_outlines(user_id)
    if not approved:
        st.info("먼저 Outline Editor에서 사용할 개요 버전을 승인하세요.")
        return
    labels = {
        f"{item['company']} · {item['job_title']} · 문항 #{item['question_id']} · {item['experience_name']}": item["id"]
        for item in approved
    }
    selected = st.selectbox("승인 개요", labels, key="draft_outline")
    outline_id = labels[selected]
    context = get_outline_context(outline_id, user_id)
    if not context:
        st.error("승인 개요 정보를 찾을 수 없습니다.")
        return

    saved_limit = context["question"].get("character_limit")
    draft_limit_value = st.number_input(
        "Draft 글자 수 제한",
        min_value=0,
        value=saved_limit or 0,
        step=50,
        help="공백 포함 기준입니다. 0은 제한 없음으로 처리합니다.",
        key=f"draft_limit_{outline_id}",
    )
    draft_limit = int(draft_limit_value) or None
    if draft_limit:
        st.info(f"이번 Draft는 공백 포함 {round(draft_limit * 0.9)}~{draft_limit}자를 목표로 생성합니다.")
    else:
        st.warning("현재 글자 수 제한이 없습니다. 원하는 분량이 있다면 위에 숫자를 입력하세요.")

    use_ai = st.toggle(
        "OpenAI로 초안 작성",
        value=bool(os.getenv("OPENAI_API_KEY")),
        help="끄면 승인 개요의 근거만 연결한 로컬 초안을 만듭니다.",
    )
    if not use_ai:
        st.caption("로컬 모드는 문장을 새로 작성하지 않고 개요 내용을 제한 안에서 연결한 미리보기입니다.")
    button_label = f"{draft_limit}자 맞춤 Draft 생성" if draft_limit else "제한 없이 Draft 생성"
    if st.button(button_label, type="primary", use_container_width=True):
        try:
            if draft_limit != saved_limit:
                question = context["question"]
                update_essay_question(
                    question["id"],
                    question["question"],
                    draft_limit,
                    question["optional_note"],
                    QuestionAnalysis.model_validate(question["analysis"]),
                    user_id,
                )
                context = context | {"question": question | {"character_limit": draft_limit}}
            draft, used_ai = generate_essay_draft(context, user_id, use_ai)
            save_essay_draft(outline_id, draft.content, user_id)
            st.success(f"{'AI' if used_ai else '로컬'} 초안을 {len(draft.content)}자로 저장했습니다.")
            st.rerun()
        except Exception as exc:
            st.error(f"초안 생성에 실패했습니다: {exc}")

    drafts = list_essay_drafts(outline_id, user_id)
    if not drafts:
        st.caption("초안을 생성하면 직접 편집하고 사실 검증할 수 있습니다.")
        return
    draft_labels = {
        f"Draft #{item['id']} · {item['created_at']}": item for item in drafts
    }
    selected_draft = st.selectbox("초안 버전", draft_labels, key="draft_version")
    draft = draft_labels[selected_draft]
    content = st.text_area(
        "자기소개서 초안",
        draft["content"],
        height=360,
        key=f"draft_content_{draft['id']}",
    )
    limit = context["question"].get("character_limit")
    over_limit = bool(limit and len(content) > limit)
    st.caption(
        f"공백 포함 {len(content)}자"
        + (f" / 제한 {limit}자 · {'초과 ' + str(len(content) - limit) if over_limit else '남음 ' + str(limit - len(content))}자" if limit else "")
    )
    if over_limit:
        st.error("글자 제한을 초과했습니다. 저장하거나 Fact Check하기 전에 내용을 줄여 주세요.")
    left, right = st.columns(2)
    if left.button("수정본을 새 Draft로 저장", disabled=over_limit, use_container_width=True):
        try:
            save_essay_draft(outline_id, content, user_id)
            st.success("수정본을 새 Draft로 저장했습니다.")
            st.rerun()
        except ValueError as exc:
            st.warning(str(exc))
    if right.button(
        "Fact Check · 품질 검사", type="primary", disabled=over_limit, use_container_width=True
    ):
        target_draft_id = draft["id"]
        if content.strip() != draft["content"].strip():
            target_draft_id = save_essay_draft(outline_id, content, user_id)
        checks = fact_check_draft(
            content, context["experiences"], context["profile"], context["materials"]
        )
        save_fact_check_results(outline_id, target_draft_id, checks, user_id)
        st.success("문장별 근거 검증을 완료했습니다.")
        st.rerun()

    with st.expander("AI로 부분 수정", expanded=False):
        paragraphs = [item.strip() for item in content.split("\n\n") if item.strip()]
        target_options = {"전체 초안": None} | {
            f"{index + 1}문단 · {paragraph[:45]}": index for index, paragraph in enumerate(paragraphs)
        }
        target_label = st.selectbox(
            "수정 범위", target_options, key=f"draft_revision_target_{draft['id']}"
        )
        presets = {
            "더 구체적으로": "선택 범위의 사실과 행동을 근거 안에서 더 구체적으로 표현해줘.",
            "두괄식으로": "핵심 결론이 첫 문장에 오도록 두괄식으로 수정해줘.",
            "더 간결하게": "중복 표현을 제거하고 의미는 유지하면서 더 간결하게 수정해줘.",
            "직무 연결 강화": "억지스러운 키워드 반복 없이 지원 직무와의 연결을 명확하게 해줘.",
            "직접 입력": "",
        }
        preset = st.selectbox("수정 방식", presets, key=f"draft_revision_preset_{draft['id']}")
        custom_request = st.text_area(
            "직접 수정 요청",
            placeholder="예: 첫 문장에서 책 이름보다 배운 태도를 먼저 강조해줘",
            key=f"draft_revision_request_{draft['id']}",
            disabled=preset != "직접 입력",
        )
        if not os.getenv("OPENAI_API_KEY"):
            st.caption("AI 부분 수정에는 OPENAI_API_KEY가 필요합니다.")
        if st.button(
            "수정본을 새 Draft로 저장",
            type="primary",
            disabled=not os.getenv("OPENAI_API_KEY"),
            use_container_width=True,
            key=f"revise_draft_{draft['id']}",
        ):
            try:
                revised = revise_essay_draft(
                    context,
                    content,
                    custom_request if preset == "직접 입력" else presets[preset],
                    target_options[target_label],
                    user_id,
                )
                save_essay_draft(outline_id, revised.content, user_id)
                st.success(f"AI 수정본을 {len(revised.content)}자로 새 Draft에 저장했습니다.")
                st.rerun()
            except (ValueError, MissingAPIKeyError) as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"Draft 수정에 실패했습니다: {exc}")

    with st.expander("Draft 버전 삭제"):
        st.warning("선택한 Draft와 해당 Fact Check 결과가 함께 삭제됩니다.")
        confirmed = st.checkbox(
            "선택한 Draft 버전을 영구 삭제합니다.", key=f"delete_draft_confirm_{draft['id']}"
        )
        if st.button(
            "Draft 버전 영구 삭제",
            disabled=not confirmed,
            use_container_width=True,
            key=f"delete_draft_{draft['id']}",
        ):
            delete_essay_draft(draft["id"], user_id)
            st.session_state["delete_notice"] = "Draft 버전과 Fact Check를 삭제했습니다. 복구할 수 없습니다."
            st.rerun()

    stored_checks = get_fact_check_results(draft["id"], user_id)
    if not stored_checks:
        return
    checks = [FactCheckItem.model_validate(item) for item in stored_checks]
    _render_fact_checks(checks)
    # ponytail: 반복 사용 통계는 주 경험만 집계한다. 보조 경험 분석이 필요해지면 관계 테이블로 정규화한다.
    use_count = (
        count_experience_uses(context["jd"]["id"], context["experience"]["id"], user_id)
        if context["experience"]
        else 0
    )
    quality = evaluate_application(content, context, checks, use_count)
    _render_quality(quality)


def _render_fact_checks(checks: list[FactCheckItem]) -> None:
    st.subheader("문장별 Fact Check")
    st.dataframe(
        [
            {
                "상태": item.status,
                "문장": item.sentence,
                "근거": " / ".join(item.evidence),
                "판정 이유": item.reason,
            }
            for item in checks
        ],
        hide_index=True,
        use_container_width=True,
    )


def _render_quality(quality: dict) -> None:
    st.subheader("지원서 품질 검사")
    a, b, c, d = st.columns(4)
    a.metric("종합 점수", f"{quality['overall_score']}점")
    b.metric("JD 역량 반영", f"{quality['jd_skill_coverage']}%")
    c.metric("문항 구조 충족", f"{quality['question_coverage']}%")
    d.metric("Verified 문장", quality["fact_counts"]["Verified"])
    if not quality["character_limit_ok"]:
        st.warning("문항 글자 제한을 초과했습니다.")
    if quality["fact_counts"]["Unsupported"]:
        st.error(f"Unsupported 문장이 {quality['fact_counts']['Unsupported']}개 있습니다.")
    if quality["repeated_experience"]:
        st.warning(f"같은 JD의 {quality['experience_use_count']}개 문항에서 동일 경험을 사용 중입니다.")
    if quality["technical_keyword_overload"]:
        st.warning("기술 키워드 반복 비중이 높습니다.")
    if quality["do_not_use_violations"]:
        st.error("사용 금지 내용 위반: " + " / ".join(quality["do_not_use_violations"]))
    if quality["missing_skills"]:
        st.caption("초안에서 확인되지 않은 JD 역량: " + " / ".join(quality["missing_skills"]))


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def _join(values: list[str]) -> str:
    return "\n".join(values)
