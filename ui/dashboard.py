from datetime import date
from html import escape

import streamlit as st

from db import APPLICATION_STATUSES, list_application_folders, update_application_tracking
from ui import page_header


STATUS_PROGRESS = {
    "관심": 0.1,
    "준비 중": 0.25,
    "작성 중": 0.45,
    "제출 완료": 0.6,
    "서류 합격": 0.75,
    "면접 진행": 0.9,
    "최종 합격": 1.0,
}


def render(user_id: int) -> None:
    page_header(
        "Application tracker",
        "지원 관리",
        "지원 회사별 진행 상태, 마감 일정, 작성 현황과 메모를 한곳에서 관리합니다.",
    )
    _render_application_folders(user_id)


def _render_application_folders(user_id: int) -> None:
    folders = list_application_folders(user_id)
    st.markdown(
        """<div class="cf-section-head"><div><div class="cf-section-kicker">Application pipeline</div>
        <div class="cf-section-title">회사별 지원 보관함</div></div>
        <div class="cf-section-copy">마감 일정과 작성 현황을 한눈에 확인하고, 필요한 지원서부터 이어서 준비하세요.</div></div>""",
        unsafe_allow_html=True,
    )
    if not folders:
        st.info("JD를 등록하면 회사별 지원 현황을 관리할 수 있습니다.")
        return
    terminal = {"최종 합격", "불합격", "보류"}
    active = sum(item["application_status"] not in terminal for item in folders)
    submitted = sum(item["application_status"] in {"제출 완료", "서류 합격", "면접 진행", "최종 합격"} for item in folders)
    near_deadline = sum(
        bool(item["deadline"])
        and 0 <= (date.fromisoformat(item["deadline"]) - date.today()).days <= 7
        and item["application_status"] not in terminal
        for item in folders
    )
    a, b, c, d = st.columns(4)
    a.metric("전체 지원", len(folders))
    b.metric("진행 중", active)
    c.metric("제출 완료 이상", submitted)
    d.metric("7일 내 마감", near_deadline)

    filter_col, sort_col = st.columns([1, 1])
    status_filter = filter_col.selectbox(
        "상태 필터", ["전체", *APPLICATION_STATUSES], key="application_status_filter"
    )
    sort_mode = sort_col.selectbox(
        "정렬", ["마감 임박순", "최근 등록순", "진행 단계순"], key="application_sort"
    )
    visible = [
        item for item in folders if status_filter == "전체" or item["application_status"] == status_filter
    ]
    if sort_mode == "최근 등록순":
        visible.sort(key=lambda item: item["id"], reverse=True)
    elif sort_mode == "진행 단계순":
        visible.sort(key=lambda item: STATUS_PROGRESS.get(item["application_status"], 0), reverse=True)
    else:
        visible.sort(key=lambda item: item["deadline"] or "9999-12-31")
    st.caption(f"{len(visible)}개 지원 폴더 표시 중")

    for folder in visible:
        status = folder["application_status"]
        status_tone = (
            "success" if status == "최종 합격" else
            "danger" if status == "불합격" else
            "muted" if status == "보류" else
            "submitted" if status in {"제출 완료", "서류 합격", "면접 진행"} else "active"
        )
        deadline_label = "마감일 미정"
        deadline_tone = ""
        overdue = False
        if folder["deadline"]:
            days = (date.fromisoformat(folder["deadline"]) - date.today()).days
            overdue = days < 0 and status not in terminal
            deadline_label = "마감 지남" if overdue else ("D-day" if days == 0 else f"D-{days}")
            deadline_tone = "cf-deadline-over" if overdue else ("cf-deadline-soon" if days <= 7 else "")

        with st.container(border=True):
            st.markdown(
                f"""<div class="cf-app-head"><div>
                <div class="cf-app-company">{escape(folder['company'])}</div>
                <div class="cf-app-role">{escape(folder['job_title'])}</div></div>
                <div class="cf-app-badges">
                <span class="cf-status cf-status-{status_tone}">{escape(status)}</span>
                <span class="cf-deadline {deadline_tone}">{escape(deadline_label)}</span>
                </div></div>""",
                unsafe_allow_html=True,
            )
            if status in STATUS_PROGRESS:
                st.progress(STATUS_PROGRESS[status], text=f"지원 진행률 · {round(STATUS_PROGRESS[status] * 100)}%")
            if overdue:
                st.error(f"마감일 {folder['deadline']}이 지났습니다. 상태 또는 일정을 확인하세요.")
            st.markdown(
                f"""<div class="cf-app-meta">
                <div class="cf-app-meta-item"><div class="cf-app-meta-label">문항</div><div class="cf-app-meta-value">{folder['question_count']}</div></div>
                <div class="cf-app-meta-item"><div class="cf-app-meta-label">OUTLINE</div><div class="cf-app-meta-value">{folder['outline_count']}</div></div>
                <div class="cf-app-meta-item"><div class="cf-app-meta-label">DRAFT</div><div class="cf-app-meta-value">{folder['draft_count']}</div></div>
                </div>""",
                unsafe_allow_html=True,
            )
            if folder["latest_draft_at"]:
                st.caption(f"최근 Draft: {folder['latest_draft_at']}")
            st.markdown(
                f'<div class="cf-app-memo">{escape(folder["application_memo"])}</div>'
                if folder["application_memo"]
                else '<div class="cf-app-empty">아직 저장된 지원 메모가 없습니다.</div>',
                unsafe_allow_html=True,
            )
            with st.expander("지원 현황 수정"):
                with st.form(f"application_folder_{folder['id']}"):
                    edited_status = st.selectbox(
                        "지원 상태",
                        APPLICATION_STATUSES,
                        index=APPLICATION_STATUSES.index(status),
                    )
                    edited_deadline = st.date_input(
                        "마감일",
                        value=date.fromisoformat(folder["deadline"]) if folder["deadline"] else None,
                    )
                    clear_deadline = st.checkbox("마감일 비우기", disabled=not folder["deadline"])
                    memo = st.text_area(
                        "지원 메모",
                        folder["application_memo"],
                        placeholder="담당자, 전형 일정, 준비할 내용 등을 기록하세요.",
                    )
                    save = st.form_submit_button("지원 현황 저장", type="primary", use_container_width=True)
                if save:
                    update_application_tracking(
                        folder["id"],
                        edited_status,
                        "" if clear_deadline else (edited_deadline.isoformat() if edited_deadline else ""),
                        memo,
                        user_id,
                    )
                    st.success("지원 현황을 저장했습니다.")
                    st.rerun()
