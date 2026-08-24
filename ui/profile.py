import streamlit as st

from db import delete_personal_material, get_profile, list_personal_materials, save_personal_material, save_profile
from models import PersonalMaterial, ProfileData
from ui import page_header


def render(user_id: int) -> None:
    page_header("Candidate profile", "내 지원 프로필", "한 번 정리한 기본 정보는 JD 분석과 자기소개서 전 과정에 재사용됩니다.")
    profile = get_profile(user_id)

    with st.form("profile_form"):
        left, right = st.columns(2)
        with left:
            nickname = st.text_input("이름 또는 닉네임", profile.nickname)
            target_role = st.text_input("희망 직무", profile.target_role)
            industries = st.text_input("관심 산업", profile.industries)
            major = st.text_input("전공", profile.major)
            education = st.text_area("학력", profile.education)
            certifications = st.text_area("자격증", profile.certifications)
        with right:
            languages = st.text_area("어학", profile.languages)
            technical_skills = st.text_area("기술 스택", profile.technical_skills)
            courses = st.text_area("교육 과정", profile.courses)
            activities = st.text_area("기타 활동", profile.activities)
            role_description = st.text_area(
                "희망 직무 설명", profile.role_description, help="관심 업무와 준비 방향을 간단히 작성하세요."
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
        st.success("프로필을 저장했습니다.")

    st.divider()
    _render_personal_materials(user_id)


MATERIAL_CATEGORIES = ["책", "멘토·존경 인물", "가치관", "취미", "성장 배경", "기타"]


def _render_personal_materials(user_id: int) -> None:
    st.subheader("개인 소재 보관함")
    st.caption("프로젝트가 필요 없는 책·멘토·가치관 문항에 사용할 사실을 저장합니다.")
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

    materials = list_personal_materials(user_id)
    if not materials:
        st.info("저장된 개인 소재가 없습니다.")
        return
    for material in materials:
        with st.expander(f"{material['category']} · {material['title']}"):
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
                delete = right.form_submit_button(
                    "영구 삭제", disabled=not confirm_delete, use_container_width=True
                )
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
                delete_personal_material(material["id"], user_id)
                st.session_state["delete_notice"] = "개인 소재와 연결된 개요·Draft를 삭제했습니다."
                st.rerun()
