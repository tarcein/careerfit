import hashlib
import json
import os
from pathlib import Path

import streamlit as st

from config import MAX_UPLOAD_BYTES, SUPPORTED_EXTENSIONS, UPLOAD_DIR
from db import (
    add_uploaded_file,
    add_version,
    approve_all_experiences,
    approve_version,
    create_experience,
    delete_experience,
    get_experience,
    get_preference,
    get_profile,
    get_uploaded_files,
    list_experiences,
    list_uploaded_files,
    save_preference,
)
from models import ExperienceData, ExperiencePreference
from services.ai_service import MissingAPIKeyError, extract_experiences, revise_experience
from services.document_parser import DocumentError, parse_document
from ui import page_header


LIST_FIELDS = (
    "actions",
    "quantitative_results",
    "tools",
    "technical_skills",
    "soft_skills",
    "domain",
    "keywords",
    "lessons",
)
LONG_FIELDS = ("summary", "problem", "problem_context", "decision", "decision_reason", "result", "ownership_notes")
SHORT_FIELDS = ("experience_name", "category", "period", "role", "team_or_individual")
LABELS = {
    "experience_name": "경험명",
    "category": "카테고리",
    "period": "기간",
    "summary": "요약",
    "role": "역할",
    "team_or_individual": "팀/개인",
    "problem": "문제",
    "problem_context": "문제 맥락",
    "decision": "판단",
    "decision_reason": "판단 이유",
    "actions": "구체적 행동 (한 줄에 하나)",
    "result": "결과",
    "quantitative_results": "정량 결과 (한 줄에 하나)",
    "tools": "도구 (한 줄에 하나)",
    "technical_skills": "기술 역량 (한 줄에 하나)",
    "soft_skills": "소프트 스킬 (한 줄에 하나)",
    "domain": "도메인 (한 줄에 하나)",
    "keywords": "키워드 (한 줄에 하나)",
    "lessons": "배운 점 (한 줄에 하나)",
    "ownership_notes": "개인 역할 / 팀 성과 구분",
}


def render(user_id: int) -> None:
    page_header("Experience library", "경험 데이터베이스", "자료에서 경험을 추출하고, 직접 검토한 사실만 지원서에 활용합니다.")
    upload_tab, editor_tab = st.tabs(["자료 업로드 · 경험 추출", "Experience Editor"])
    with upload_tab:
        _render_upload(user_id)
    with editor_tab:
        _render_editor(user_id)


def _render_upload(user_id: int) -> None:
    st.subheader("1. 프로젝트 자료 등록")
    uploads = st.file_uploader(
        f"PDF, PPTX, DOCX, TXT, MD 파일을 여러 개 선택할 수 있습니다. (파일당 최대 {MAX_UPLOAD_BYTES // 1024 // 1024}MB)",
        type=[suffix.lstrip(".") for suffix in sorted(SUPPORTED_EXTENSIONS)],
        accept_multiple_files=True,
    )
    if st.button("선택한 파일 저장", disabled=not uploads, use_container_width=True):
        saved, duplicates = 0, 0
        errors: list[str] = []
        UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        for upload in uploads:
            content = upload.getvalue()
            safe_name = Path(upload.name).name
            try:
                extracted = parse_document(safe_name, content)
                digest = hashlib.sha256(content).hexdigest()
                destination = UPLOAD_DIR / f"{digest}{Path(safe_name).suffix.lower()}"
                destination.write_bytes(content)
                _, created = add_uploaded_file(
                    safe_name, Path(safe_name).suffix.lower(), digest, str(destination), extracted, user_id
                )
                saved += int(created)
                duplicates += int(not created)
            except DocumentError as exc:
                errors.append(f"{safe_name}: {exc}")
        if saved:
            st.success(f"{saved}개 파일의 텍스트를 추출해 저장했습니다.")
        if duplicates:
            st.info(f"내용이 같은 파일 {duplicates}개는 중복 저장하지 않았습니다.")
        for error in errors:
            st.error(error)

    files = list_uploaded_files(user_id)
    if not files:
        st.info("먼저 경험을 증명하는 자료를 업로드하세요.")
        return
    st.dataframe(files, hide_index=True, use_container_width=True)

    st.subheader("2. 경험 구조화")
    choices = {f"{item['filename']} · {item['text_length']:,}자 (#{item['id']})": item["id"] for item in files}
    selected_labels = st.multiselect("함께 분석할 문서", choices, default=list(choices)[: min(3, len(choices))])
    if not os.getenv("OPENAI_API_KEY"):
        st.info("OPENAI_API_KEY가 없어 근거 문장만 보존하는 로컬 초안을 생성합니다.")
    if st.button("선택 문서에서 경험 추출", type="primary", disabled=not selected_labels, use_container_width=True):
        selected_files = get_uploaded_files([choices[label] for label in selected_labels], user_id)
        with st.spinner("문서를 분석하고 있습니다..."):
            try:
                experiences, used_ai = extract_experiences(selected_files, get_profile(user_id), user_id)
                for experience in experiences:
                    create_experience(experience, selected_files, user_id)
                mode = "AI" if used_ai else "로컬 근거 보존형"
                st.success(f"{mode} 추출로 경험 {len(experiences)}개를 생성했습니다. Editor에서 검토해 주세요.")
            except Exception as exc:
                st.error(f"경험 추출에 실패했습니다: {exc}")


def _render_editor(user_id: int) -> None:
    experiences = list_experiences(user_id)
    if not experiences:
        st.info("추출된 경험이 없습니다. 먼저 자료를 업로드하고 경험을 추출하세요.")
        return

    pending_count = sum(item["review_status"] != "Verified" for item in experiences)
    if pending_count:
        with st.expander(f"전체 경험 승인 · {pending_count}개 대기 중"):
            st.warning("검토하지 않은 현재 버전까지 모두 Verified 처리됩니다.")
            confirmed = st.checkbox(
                "현재 프로필의 모든 경험을 확인했습니다.", key=f"verify_all_confirm_{user_id}"
            )
            if st.button(
                "전체 경험 Verified 처리",
                disabled=not confirmed,
                use_container_width=True,
                key=f"verify_all_{user_id}",
            ):
                approved = approve_all_experiences(user_id)
                st.success(f"경험 {approved}개를 Verified 처리했습니다.")
                st.rerun()

    labels = {
        f"{row['experience_name']} · {row['review_status']} · v{row['version_number']} (#{row['id']})": row["id"]
        for row in experiences
    }
    selected_label = st.selectbox("검토할 경험", labels)
    detail = get_experience(labels[selected_label], user_id)
    if not detail:
        st.error("경험을 찾을 수 없습니다.")
        return

    status_color = {"AI Extracted": "orange", "User Editing": "blue", "Verified": "green"}[detail["review_status"]]
    st.markdown(f"상태: :{status_color}[**{detail['review_status']}**] · 현재 버전 v{detail['version_number']}")

    evidence_tab, profile_tab, correction_tab, history_tab = st.tabs(
        ["Original Evidence", "AI Extracted Profile", "User Correction · Preference", "Version History"]
    )
    with evidence_tab:
        if detail["facts"]:
            for fact in detail["facts"]:
                st.caption(fact["filename"])
                st.info(fact["evidence_text"])
        else:
            st.warning("연결된 원문 근거가 없습니다. 이 경험은 승인 전에 반드시 확인해야 합니다.")

    with profile_tab:
        st.json(detail["profile"], expanded=True)

    with correction_tab:
        _render_correction_form(detail, user_id)

    with history_tab:
        _render_history(detail, user_id)

    with st.expander("경험 삭제"):
        st.warning("이 경험의 버전, 선호 설정, 매칭 결과, 자기소개서 개요와 초안이 함께 삭제됩니다. 업로드 원본 파일은 유지됩니다.")
        confirmed = st.checkbox(
            f"'{detail['experience_name']}' 경험을 영구 삭제합니다.",
            key=f"delete_confirm_{detail['id']}",
        )
        if st.button(
            "경험 영구 삭제",
            disabled=not confirmed,
            use_container_width=True,
            key=f"delete_experience_{detail['id']}",
        ):
            delete_experience(detail["id"], user_id)
            st.session_state["delete_notice"] = (
                "경험과 연결 데이터를 삭제했습니다. 복구할 수 없으며 업로드 원본 파일은 유지됩니다."
            )
            st.rerun()


def _render_correction_form(detail: dict, user_id: int) -> None:
    experience_id = detail["id"]
    existing_roles = [item["target_role"] for item in detail["preferences"]] or ["공통"]
    role_options = existing_roles + (["새 직무 추가"] if "새 직무 추가" not in existing_roles else [])
    selected_role = st.selectbox("활용 직무 프로필", role_options, key=f"role_select_{experience_id}")
    target_role = (
        st.text_input("새 직무명", key=f"new_role_{experience_id}") if selected_role == "새 직무 추가" else selected_role
    )
    preference = get_preference(experience_id, target_role or "공통", user_id)
    current = ExperienceData.model_validate(detail["profile"])

    with st.form(f"correction_{experience_id}_{selected_role}"):
        st.markdown("##### 구조화 프로필 직접 수정")
        values: dict = {}
        short_columns = st.columns(2)
        for index, field in enumerate(SHORT_FIELDS):
            with short_columns[index % 2]:
                values[field] = st.text_input(LABELS[field], getattr(current, field))
        for field in LONG_FIELDS:
            values[field] = st.text_area(LABELS[field], getattr(current, field), height=90)
        for field in LIST_FIELDS:
            values[field] = st.text_area(LABELS[field], "\n".join(getattr(current, field)), height=80)
        confidence = st.slider("근거 신뢰도", 0.0, 1.0, float(current.confidence), 0.05)

        st.markdown("##### 사실 수정과 활용 지침")
        correction = st.text_area("User Correction", help="AI가 잘못 추출한 사실을 적으세요.")
        user_preference = st.text_area("User Preference", preference.user_preference)
        do_not_use = st.text_area("Do Not Use", preference.do_not_use)
        preferred_focus = st.text_area("Preferred Focus", preference.preferred_focus)
        preference_ownership = st.text_area("Ownership Notes (활용 지침)", preference.ownership_notes)
        change_note = st.text_input("버전 변경 설명", "사용자 검토 및 수정")
        manual_submit = st.form_submit_button("수동 새 버전 저장", use_container_width=True)
        ai_submit = st.form_submit_button("AI 반영 새 버전 생성", type="primary", use_container_width=True)

    if not (manual_submit or ai_submit):
        return
    if not target_role.strip():
        st.error("직무명을 입력해 주세요.")
        return

    saved_preference = ExperiencePreference(
        target_role=target_role.strip(),
        user_preference=user_preference,
        do_not_use=do_not_use,
        preferred_focus=preferred_focus,
        ownership_notes=preference_ownership,
    )
    save_preference(experience_id, saved_preference, user_id)
    profile_values = values | {field: _lines(values[field]) for field in LIST_FIELDS}
    edited = ExperienceData(
        **profile_values,
        source_files=current.source_files,
        evidence=current.evidence,
        confidence=confidence,
    )
    try:
        if ai_submit:
            with st.spinner("수정 요청을 근거와 대조해 반영하고 있습니다..."):
                revised = revise_experience(edited, detail["facts"], correction, saved_preference, user_id)
            add_version(experience_id, revised, change_note or "AI 사용자 수정 반영", "AI", correction, user_id)
        else:
            add_version(experience_id, edited, change_note or "사용자 직접 수정", "User", correction, user_id)
        st.success("새 버전을 저장했습니다. Version History에서 비교 후 승인하세요.")
        st.rerun()
    except MissingAPIKeyError as exc:
        st.warning(str(exc))
    except Exception as exc:
        st.error(f"새 버전 생성에 실패했습니다: {exc}")


def _render_history(detail: dict, user_id: int) -> None:
    versions = detail["versions"]
    version_labels = {
        f"v{item['version_number']} · {item['created_by']} · {item['change_note']}"
        + (" · 승인됨" if item["is_approved"] else ""): item
        for item in versions
    }
    current_label = next(iter(version_labels))
    compare_label = st.selectbox("비교할 과거 버전", list(version_labels), index=min(1, len(version_labels) - 1))
    left, right = st.columns(2)
    with left:
        st.caption(compare_label)
        st.json(version_labels[compare_label]["profile"], expanded=False)
    with right:
        st.caption(current_label)
        st.json(version_labels[current_label]["profile"], expanded=False)

    approve_label = st.selectbox("최종 승인 또는 복원할 버전", list(version_labels), key=f"approve_{detail['id']}")
    if st.button("선택 버전 승인", type="primary", use_container_width=True):
        approve_version(detail["id"], version_labels[approve_label]["id"], user_id)
        st.success(f"{approve_label}을 승인했습니다.")
        st.rerun()


def _lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]
