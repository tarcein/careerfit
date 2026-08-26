from html import escape

import streamlit as st

from config import SUPPORTED_EXTENSIONS
from db import delete_personal_material, get_profile, list_personal_materials, save_personal_material, save_profile
from models import PersonalMaterial, ProfileData
from services.ai_service import extract_profile_from_resume
from services.document_parser import DocumentError, parse_document
from ui import page_header


def render(user_id: int) -> None:
    page_header("Candidate profile", "내 지원 프로필", "한 번 정리한 기본 정보는 JD 분석과 자기소개서 전 과정에 재사용됩니다.")
    if st.session_state.pop("profile_saved", False):
        st.success("프로필을 저장했습니다.")
    if notice := st.session_state.pop("resume_profile_notice", None):
        st.success(notice)
    profile = get_profile(user_id)
    _render_profile_overview(profile)
    _render_resume_import(profile, user_id)

    with st.form("profile_form"):
        st.markdown('<div class="cf-form-section"><b>기본 정보</b><span>지원 방향을 구분하는 핵심 정보</span></div>', unsafe_allow_html=True)
        name_col, role_col, industry_col = st.columns(3)
        nickname = name_col.text_input("이름 또는 닉네임", profile.nickname)
        target_role = role_col.text_input("희망 직무", profile.target_role)
        industries = industry_col.text_input("관심 산업", profile.industries)

        st.markdown('<div class="cf-form-section"><b>학력과 자격</b><span>지원 요건 판단에 활용되는 객관 정보</span></div>', unsafe_allow_html=True)
        left, right = st.columns(2)
        major = left.text_input("전공", profile.major)
        education = left.text_area("학력", profile.education, height=90)
        certifications = right.text_area("자격증", profile.certifications, height=90)
        languages = right.text_area("어학", profile.languages, height=90)

        st.markdown('<div class="cf-form-section"><b>역량과 지원 방향</b><span>JD 분석과 자기소개서에 반복 활용됩니다</span></div>', unsafe_allow_html=True)
        left, right = st.columns(2)
        technical_skills = left.text_area("기술 스택", profile.technical_skills, height=110)
        courses = left.text_area("교육 과정", profile.courses, height=100)
        activities = right.text_area("기타 활동", profile.activities, height=100)
        role_description = right.text_area(
            "희망 직무 설명", profile.role_description, height=110,
            help="관심 업무와 준비 방향을 간단히 작성하세요.",
        )
        submitted = st.form_submit_button("프로필 저장", type="primary", use_container_width=True)

    if submitted:
        save_profile(
            ProfileData(
                nickname=nickname,
                target_role=target_role,
                industries=industries,
                major=major,
                education=education,
                certifications=certifications,
                languages=languages,
                technical_skills=technical_skills,
                courses=courses,
                activities=activities,
                role_description=role_description,
            ),
            user_id,
        )
        st.session_state["profile_saved"] = True
        st.rerun()

    st.divider()
    _render_personal_materials(user_id)


def _render_resume_import(profile: ProfileData, user_id: int) -> None:
    with st.expander("이력서로 프로필 자동 채우기"):
        st.caption("현재 비어 있는 프로필 항목만 채웁니다. 추출 결과는 저장 후 직접 검토·수정할 수 있습니다.")
        resume = st.file_uploader(
            "이력서 파일",
            type=[suffix.lstrip(".") for suffix in sorted(SUPPORTED_EXTENSIONS)],
            key=f"profile_resume_{user_id}",
        )
        if st.button(
            "이력서 분석하고 빈 항목 채우기",
            type="primary",
            disabled=resume is None,
            use_container_width=True,
            key=f"profile_resume_submit_{user_id}",
        ):
            try:
                with st.spinner("이력서에서 프로필 정보를 찾고 있습니다..."):
                    text = parse_document(resume.name, resume.getvalue())
                    imported, used_ai = extract_profile_from_resume(text, profile, user_id)
                filled = [
                    field
                    for field in ProfileData.model_fields
                    if not getattr(profile, field).strip() and getattr(imported, field).strip()
                ]
                if not filled:
                    st.warning("새로 채울 수 있는 프로필 정보를 찾지 못했습니다.")
                else:
                    save_profile(imported, user_id)
                    mode = "AI" if used_ai else "로컬 규칙"
                    st.session_state["resume_profile_notice"] = (
                        f"{mode}으로 프로필 {len(filled)}개 항목을 채웠습니다. 내용을 확인해 주세요."
                    )
                    st.rerun()
            except (DocumentError, ValueError) as exc:
                st.warning(str(exc))
            except Exception as exc:
                st.error(f"이력서 분석에 실패했습니다: {exc}")


MATERIAL_CATEGORIES = ["책", "멘토·존경 인물", "가치관", "취미", "성장 배경", "기타"]


def _render_profile_overview(profile: ProfileData) -> None:
    values = profile.model_dump()
    completed = sum(bool(str(value).strip()) for value in values.values())
    completion = round(completed / len(values) * 100)
    nickname = profile.nickname.strip() or "내 프로필"
    role = profile.target_role.strip() or "희망 직무를 입력해 주세요"
    industry = profile.industries.strip() or "관심 산업 미설정"
    st.markdown(
        f"""<div class="cf-profile-overview"><div class="cf-profile-avatar">{escape(nickname[:1])}</div>
        <div class="cf-profile-identity"><div class="cf-profile-name">{escape(nickname)}</div>
        <div class="cf-profile-role">{escape(role)} <span>·</span> {escape(industry)}</div></div>
        <div class="cf-profile-completion"><b>{completion}%</b><span>프로필 완성도</span></div></div>""",
        unsafe_allow_html=True,
    )
    st.progress(completion / 100)


def _render_personal_materials(user_id: int) -> None:
    materials = list_personal_materials(user_id)
    st.markdown(
        f"""<div class="cf-section-head"><div><div class="cf-section-kicker">Personal stories</div>
        <div class="cf-section-title">개인 소재 보관함 <span class="cf-section-count">{len(materials)}</span></div></div>
        <div class="cf-section-copy">책·멘토·가치관처럼 프로젝트가 필요 없는 문항에 활용합니다.</div></div>""",
        unsafe_allow_html=True,
    )
    with st.expander("새 개인 소재 추가", expanded=not materials):
        with st.form("new_personal_material", clear_on_submit=True):
            category = st.selectbox("소재 유형", MATERIAL_CATEGORIES)
            title = st.text_input("소재 제목", placeholder="예: 팩트풀니스 / 나의 첫 팀장 / 데이터로 판단하는 태도")
            context = st.text_area("소재와 배경", placeholder="무엇 또는 누구이며, 언제 접했는지 적어주세요.")
            memorable_point = st.text_area("기억에 남은 내용", placeholder="인상 깊었던 말, 장면, 특징")
            insight = st.text_area("나에게 준 영향", placeholder="생각이나 가치관이 어떻게 달라졌는지")
            changed_action = st.text_area("행동 변화", placeholder="실제로 달라진 습관이나 행동")
            keywords = st.text_input("키워드", placeholder="예: 데이터, 검증, 편견, 학습")
            create = st.form_submit_button("개인 소재 저장", type="primary", use_container_width=True)
    if create:
        try:
            material_id = save_personal_material(
                PersonalMaterial(
                    category=category,
                    title=title,
                    context=context,
                    memorable_point=memorable_point,
                    insight=insight,
                    changed_action=changed_action,
                    keywords=keywords,
                ),
                user_id,
            )
            st.success(f"개인 소재 #{material_id}을 저장했습니다.")
            st.rerun()
        except ValueError as exc:
            st.warning(str(exc))

    if not materials:
        st.info("저장된 개인 소재가 없습니다.")
        return
    for material in materials:
        with st.container(border=True):
            _render_material_card(material)
            with st.expander("내용 수정 또는 삭제"):
                with st.form(f"personal_material_{material['id']}"):
                    edit_category = st.selectbox(
                        "소재 유형",
                        MATERIAL_CATEGORIES,
                        index=MATERIAL_CATEGORIES.index(material["category"])
                        if material["category"] in MATERIAL_CATEGORIES else len(MATERIAL_CATEGORIES) - 1,
                    )
                    edit_title = st.text_input("소재 제목", material["title"])
                    edit_context = st.text_area("소재와 배경", material["context"])
                    edit_memorable = st.text_area("기억에 남은 내용", material["memorable_point"])
                    edit_insight = st.text_area("나에게 준 영향", material["insight"])
                    edit_action = st.text_area("행동 변화", material["changed_action"])
                    edit_keywords = st.text_input("키워드", material["keywords"])
                    confirm_delete = st.checkbox("이 소재와 연결된 개요·Draft도 함께 삭제")
                    left, right = st.columns(2)
                    update = left.form_submit_button("수정 저장", use_container_width=True)
                    delete = right.form_submit_button("영구 삭제", use_container_width=True)
            if update:
                save_personal_material(
                    PersonalMaterial(
                        category=edit_category,
                        title=edit_title,
                        context=edit_context,
                        memorable_point=edit_memorable,
                        insight=edit_insight,
                        changed_action=edit_action,
                        keywords=edit_keywords,
                    ),
                    user_id,
                    material["id"],
                )
                st.success("개인 소재를 수정했습니다.")
                st.rerun()
            if delete:
                if not confirm_delete:
                    st.warning("연결 데이터 삭제 확인에 체크해 주세요.")
                else:
                    delete_personal_material(material["id"], user_id)
                    st.session_state["delete_notice"] = "개인 소재와 연결된 개요·Draft를 삭제했습니다."
                    st.rerun()


def _render_material_card(material: dict) -> None:
    keywords = [item.strip() for item in material["keywords"].replace("/", ",").split(",") if item.strip()]
    keyword_html = "".join(f"<span class=\"cf-profile-chip\">{escape(item)}</span>" for item in keywords)
    context = material["context"] or material["memorable_point"] or "소재 배경이 아직 입력되지 않았습니다."
    st.markdown(
        f"""<div class="cf-material-head"><div><span class="cf-material-category">{escape(material['category'])}</span>
        <span class="cf-material-title">{escape(material['title'])}</span></div></div>
        <div class="cf-material-context">{escape(context)}</div>
        <div class="cf-material-grid"><div><span>나에게 준 영향</span><p>{escape(material['insight'] or '입력되지 않음')}</p></div>
        <div><span>행동 변화</span><p>{escape(material['changed_action'] or '입력되지 않음')}</p></div></div>
        <div class="cf-profile-chips">{keyword_html}</div>""",
        unsafe_allow_html=True,
    )
