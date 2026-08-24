import streamlit as st

from db import (
    authenticate_account,
    create_user,
    get_account,
    has_accounts,
    init_db,
    list_users,
    register_account,
)
from ui import dashboard, essay_planner, experiences, jd_analyzer, profile


st.set_page_config(page_title="CareerFit AI", page_icon="🎯", layout="wide")


@st.cache_resource
def _initialize_database() -> None:
    init_db()


_initialize_database()


def _finish_authentication(account_id: int) -> None:
    st.session_state["account_id"] = account_id
    st.session_state.pop("active_user_id", None)
    st.rerun()


def _render_auth() -> None:
    first_setup = not has_accounts()
    _, center, _ = st.columns([1, 1.15, 1])
    with center:
        st.markdown(
            """<div style="text-align:center;margin:7vh 0 1.6rem">
            <div class="cf-brand-mark" style="margin:0 auto .8rem">CF</div>
            <h1 style="margin:0">CareerFit AI</h1>
            <p style="color:#64748b">내 지원 자료를 안전하게 분리해 관리하세요.</p></div>""",
            unsafe_allow_html=True,
        )
        if first_setup:
            st.info("첫 계정을 만들면 현재 저장된 프로필과 지원 자료가 이 계정에 연결됩니다.")
            with st.form("initial_account"):
                name = st.text_input("이름", placeholder="예: 홍길동")
                email = st.text_input("이메일", placeholder="name@example.com")
                password = st.text_input("비밀번호", type="password", help="8자 이상")
                password_confirm = st.text_input("비밀번호 확인", type="password")
                submitted = st.form_submit_button("첫 계정 만들기", type="primary", use_container_width=True)
            if submitted:
                if password != password_confirm:
                    st.error("비밀번호가 일치하지 않습니다.")
                else:
                    try:
                        _finish_authentication(register_account(email, password, name))
                    except ValueError as exc:
                        st.error(str(exc))
            return

        login_tab, signup_tab = st.tabs(["로그인", "회원가입"])
        with login_tab:
            with st.form("login"):
                email = st.text_input("이메일", key="login_email")
                password = st.text_input("비밀번호", type="password", key="login_password")
                submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)
            if submitted:
                account = authenticate_account(email, password)
                if account:
                    _finish_authentication(account["id"])
                else:
                    st.error("이메일 또는 비밀번호가 올바르지 않습니다.")
        with signup_tab:
            with st.form("signup"):
                name = st.text_input("이름", key="signup_name")
                email = st.text_input("이메일", key="signup_email")
                password = st.text_input("비밀번호", type="password", help="8자 이상", key="signup_password")
                password_confirm = st.text_input("비밀번호 확인", type="password", key="signup_confirm")
                submitted = st.form_submit_button("회원가입", type="primary", use_container_width=True)
            if submitted:
                if password != password_confirm:
                    st.error("비밀번호가 일치하지 않습니다.")
                else:
                    try:
                        _finish_authentication(register_account(email, password, name))
                    except ValueError as exc:
                        st.error(str(exc))

st.markdown(
    """
    <style>
      :root {
        --cf-primary: #4f46e5;
        --cf-primary-soft: #eef2ff;
        --cf-text: #172033;
        --cf-muted: #64748b;
        --cf-border: #e2e8f0;
        --cf-surface: #ffffff;
        --cf-background: #f6f8fc;
      }

      html, body, input, textarea, select {
        font-family: Inter, Pretendard, "Noto Sans KR", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      [data-testid="stIconMaterial"] {font-family: "Material Symbols Rounded" !important;}
      [data-testid="stAppViewContainer"] {background: var(--cf-background);}
      [data-testid="stHeader"] {background: transparent;}
      .block-container {max-width: 1160px; padding: 2.5rem 2.25rem 4rem;}

      h1, h2, h3, h4, h5 {color: var(--cf-text); letter-spacing: -.025em;}
      h1 {font-size: 2rem !important; font-weight: 760 !important; margin-bottom: .35rem !important;}
      h2 {font-size: 1.4rem !important; margin-top: 2rem !important;}
      h3 {font-size: 1.12rem !important; margin-top: 1.5rem !important;}
      p, label, li {line-height: 1.65;}
      [data-testid="stCaptionContainer"] p {color: var(--cf-muted); font-size: .9rem;}
      hr {border-color: var(--cf-border) !important; margin: 1.75rem 0 !important;}

      [data-testid="stSidebar"] {background: var(--cf-surface); border-right: 1px solid var(--cf-border);}
      [data-testid="stSidebarContent"] {padding: 1.15rem .9rem;}
      .cf-brand {display: flex; align-items: center; gap: .75rem; margin: .2rem .25rem 1.4rem;}
      .cf-brand-mark {display: grid; place-items: center; width: 2.35rem; height: 2.35rem; border-radius: .75rem;
        background: linear-gradient(135deg, #4f46e5, #7c3aed); color: white; font-weight: 800; box-shadow: 0 8px 18px #4f46e52e;}
      .cf-brand-title {font-weight: 780; color: var(--cf-text); line-height: 1.15;}
      .cf-brand-copy {font-size: .75rem; color: var(--cf-muted); margin-top: .2rem;}
      .cf-phase {margin: .25rem; padding: .6rem .75rem; border-radius: .65rem; background: var(--cf-primary-soft);
        color: #4338ca; font-size: .78rem; font-weight: 650; text-align: center;}
      [data-testid="stSidebar"] [role="radiogroup"] {gap: .28rem;}
      [data-testid="stSidebar"] [role="radiogroup"] label {padding: .58rem .68rem; border-radius: .65rem; transition: .15s ease;}
      [data-testid="stSidebar"] [role="radiogroup"] label:hover {background: #f8fafc;}
      [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {background: var(--cf-primary-soft); color: #4338ca; font-weight: 650;}

      [data-testid="stForm"], [data-testid="stExpander"] {
        background: var(--cf-surface); border: 1px solid var(--cf-border) !important; border-radius: .85rem !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, .025);
      }
      [data-testid="stForm"] {padding: 1.25rem;}
      [data-testid="stExpander"] summary {font-weight: 650; color: #334155;}
      [data-testid="stExpander"] details[open] summary {border-bottom: 1px solid #f1f5f9; padding-bottom: .75rem;}

      [data-baseweb="tab-list"] {gap: .35rem; border-bottom: 1px solid var(--cf-border);}
      button[data-baseweb="tab"] {height: 2.75rem; padding: 0 .95rem; border-radius: .65rem .65rem 0 0; color: var(--cf-muted);}
      button[data-baseweb="tab"][aria-selected="true"] {background: var(--cf-primary-soft); color: #4338ca; font-weight: 700;}

      [data-baseweb="input"] > div, [data-baseweb="textarea"] > div, [data-baseweb="select"] > div {
        border-color: #cbd5e1 !important; border-radius: .65rem !important; background: white;
      }
      [data-baseweb="input"] > div:focus-within, [data-baseweb="textarea"] > div:focus-within, [data-baseweb="select"] > div:focus-within {
        border-color: var(--cf-primary) !important; box-shadow: 0 0 0 3px #4f46e51a !important;
      }
      [data-testid="stFileUploaderDropzone"] {background: #fafbff; border: 1px dashed #a5b4fc; border-radius: .85rem;}

      [data-testid="stBaseButton-primary"] {background: var(--cf-primary); border: 0; border-radius: .65rem; font-weight: 680; box-shadow: 0 5px 12px #4f46e526;}
      [data-testid="stBaseButton-primary"]:hover {background: #4338ca;}
      [data-testid="stBaseButton-secondary"] {background: white; border-color: #cbd5e1; border-radius: .65rem; font-weight: 620;}
      [data-testid="stBaseButton-secondary"]:hover {border-color: #818cf8; color: #4338ca;}

      [data-testid="stMetric"] {background: white; border: 1px solid var(--cf-border); padding: 1.05rem 1.1rem; border-radius: .85rem;
        box-shadow: 0 4px 14px rgba(15, 23, 42, .035);}
      [data-testid="stMetricLabel"] {color: var(--cf-muted);}
      [data-testid="stMetricValue"] {color: var(--cf-text); font-weight: 760;}
      [data-testid="stAlert"] {border-radius: .75rem; border-width: 1px;}
      [data-testid="stDataFrame"], [data-testid="stJson"] {border: 1px solid var(--cf-border); border-radius: .75rem; overflow: hidden; background: white;}

      .cf-page-hero {position: relative; margin: -.25rem 0 1.55rem; padding: .25rem 0 1.35rem; border-bottom: 1px solid var(--cf-border);}
      .cf-page-eyebrow {margin-bottom: .45rem; color: #6366f1; font-size: .72rem; font-weight: 780; letter-spacing: .11em; text-transform: uppercase;}
      .cf-page-title {margin: 0 !important; color: var(--cf-text); font-size: 2.05rem !important; font-weight: 790 !important;
        line-height: 1.22; letter-spacing: -.035em;}
      .cf-page-description {max-width: 720px; margin-top: .5rem; color: var(--cf-muted); font-size: .95rem; line-height: 1.65;}
      .cf-flow {display: flex; align-items: center; flex-wrap: wrap; gap: .55rem; margin: 0 0 1.3rem; color: #64748b; font-size: .78rem;}
      .cf-flow span {padding: .38rem .62rem; border: 1px solid var(--cf-border); border-radius: 999px; background: white;}
      .cf-flow b {display: inline-grid; place-items: center; width: 1.15rem; height: 1.15rem; margin-right: .25rem; border-radius: 50%;
        background: var(--cf-primary-soft); color: #4338ca; font-size: .68rem;}
      .cf-flow i {color: #a5b4fc; font-style: normal; font-size: 1rem;}

      .cf-jd-hero {display: flex; justify-content: space-between; align-items: center; gap: 1rem; margin: 1rem 0 1.1rem;
        padding: 1.15rem 1.25rem; border: 1px solid #c7d2fe; border-radius: .9rem; background: linear-gradient(135deg, #ffffff, #eef2ff);}
      .cf-jd-eyebrow {font-size: .75rem; color: #6366f1; font-weight: 750; text-transform: uppercase; letter-spacing: .08em;}
      .cf-jd-title {font-size: 1.25rem; color: var(--cf-text); font-weight: 760; margin-top: .22rem;}
      .cf-jd-card {min-height: 8.2rem; margin: .35rem 0 .7rem; padding: 1rem 1.05rem; border: 1px solid var(--cf-border);
        border-radius: .8rem; background: white; box-shadow: 0 3px 12px rgba(15, 23, 42, .03);}
      .cf-jd-card-title {font-size: .82rem; color: #475569; font-weight: 740; margin-bottom: .7rem;}
      .cf-jd-card ul {margin: 0; padding-left: 1.15rem; color: #334155;}
      .cf-jd-card li {margin: .25rem 0; font-size: .9rem;}
      .cf-chip {display: inline-block; margin: 0 .35rem .4rem 0; padding: .28rem .55rem; border-radius: 999px;
        background: #eef2ff; color: #4338ca; font-size: .78rem; font-weight: 650; border: 1px solid #dfe3ff;}
      .cf-chip-missing {background: #fff7ed; color: #c2410c; border-color: #fed7aa;}
      .cf-empty {font-size: .84rem; color: #94a3b8;}
      .cf-score-line {display: flex; justify-content: space-between; align-items: baseline; margin: .25rem 0 .15rem;}
      .cf-score-label {color: var(--cf-muted); font-size: .82rem;}
      .cf-score-value {color: #4338ca; font-size: 1.15rem; font-weight: 780;}
      .cf-rank {display: inline-flex; align-items: center; padding: .25rem .48rem; border-radius: .45rem; background: #111827;
        color: white; font-size: .68rem; font-weight: 800; letter-spacing: .04em;}
      [data-testid="stVerticalBlockBorderWrapper"] {border-color: var(--cf-border) !important; border-radius: .9rem !important;
        background: white; box-shadow: 0 4px 16px rgba(15, 23, 42, .035);}
      .cf-gap-title {display: flex; justify-content: space-between; align-items: center; margin-bottom: .8rem; font-weight: 750; color: var(--cf-text);}
      .cf-gap-count {display: grid; place-items: center; min-width: 1.55rem; height: 1.55rem; border-radius: 50%; background: #f1f5f9; font-size: .75rem;}
      .cf-gap-card {min-height: 12rem; padding: 1rem; border: 1px solid var(--cf-border); border-radius: .85rem; background: white;}
      .cf-gap-item {margin-bottom: .55rem; padding: .62rem .68rem; border-radius: .6rem; background: #f8fafc;}
      .cf-gap-skill {font-size: .84rem; font-weight: 700; color: #334155;}
      .cf-gap-evidence {margin-top: .18rem; color: #94a3b8; font-size: .7rem; line-height: 1.4;}
      .cf-gap-strong {border-top: 3px solid #10b981;}
      .cf-gap-partial {border-top: 3px solid #f59e0b;}
      .cf-gap-missing {border-top: 3px solid #f97316;}

      .cf-profile-overview {display: flex; align-items: center; gap: .9rem; margin: .9rem 0 .45rem; padding: 1.15rem 1.25rem;
        border: 1px solid #c7d2fe; border-radius: .9rem; background: linear-gradient(135deg, #ffffff, #eef2ff);}
      .cf-profile-avatar {display: grid; place-items: center; flex: 0 0 3rem; width: 3rem; height: 3rem; border-radius: .85rem;
        background: linear-gradient(135deg, #4f46e5, #7c3aed); color: white; font-size: 1.15rem; font-weight: 800; box-shadow: 0 7px 16px #4f46e52b;}
      .cf-profile-identity {min-width: 0; flex: 1;}
      .cf-profile-name {color: var(--cf-text); font-size: 1.08rem; font-weight: 780;}
      .cf-profile-role {margin-top: .2rem; color: #64748b; font-size: .82rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;}
      .cf-profile-role span {color: #a5b4fc; padding: 0 .18rem;}
      .cf-profile-completion {display: flex; flex-direction: column; align-items: flex-end; padding-left: 1rem; border-left: 1px solid #dbe2f4;}
      .cf-profile-completion b {color: #4338ca; font-size: 1.25rem; font-weight: 820;}
      .cf-profile-completion span {color: #94a3b8; font-size: .68rem; font-weight: 680;}
      .cf-form-section {display: flex; align-items: baseline; gap: .6rem; margin: 1.25rem 0 .55rem; padding-bottom: .45rem; border-bottom: 1px solid #eef2f7;}
      .cf-form-section:first-child {margin-top: 0;}
      .cf-form-section b {color: #334155; font-size: .88rem;}
      .cf-form-section span {color: #94a3b8; font-size: .7rem;}
      .cf-section-count {display: inline-grid; place-items: center; min-width: 1.5rem; height: 1.5rem; margin-left: .25rem; padding: 0 .35rem;
        border-radius: 999px; background: #eef2ff; color: #4f46e5; font-size: .72rem; vertical-align: .12rem;}
      .cf-material-head {display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: .65rem;}
      .cf-material-category {display: inline-flex; padding: .25rem .5rem; border: 1px solid #c7d2fe; border-radius: 999px;
        background: #eef2ff; color: #4338ca; font-size: .68rem; font-weight: 750;}
      .cf-material-title {margin-left: .45rem; color: var(--cf-text); font-size: 1rem; font-weight: 760;}
      .cf-material-context {margin-bottom: .75rem; color: #64748b; font-size: .84rem; line-height: 1.6; white-space: pre-wrap;}
      .cf-material-grid {display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: .5rem; margin-bottom: .65rem;}
      .cf-material-grid div {padding: .65rem .72rem; border-radius: .62rem; background: #f8fafc; border: 1px solid #eef2f7;}
      .cf-material-grid span {color: #94a3b8; font-size: .66rem; font-weight: 700;}
      .cf-material-grid p {margin: .16rem 0 0; color: #334155; font-size: .8rem; line-height: 1.5;}
      .cf-profile-chips {display: flex; flex-wrap: wrap; gap: .3rem; margin-bottom: .45rem;}
      .cf-profile-chip {padding: .22rem .45rem; border-radius: 999px; background: #f1f5f9; color: #64748b; font-size: .66rem; font-weight: 650;}

      .cf-question-hero {margin: 1rem 0 .8rem; padding: 1.2rem 1.3rem; border: 1px solid #c7d2fe; border-radius: .9rem;
        background: linear-gradient(135deg, #ffffff, #f5f3ff); box-shadow: 0 4px 16px rgba(79, 70, 229, .05);}
      .cf-question-badges {display: flex; gap: .4rem; margin-bottom: .7rem;}
      .cf-question-type, .cf-question-limit {display: inline-flex; padding: .28rem .55rem; border-radius: 999px;
        font-size: .7rem; font-weight: 760; border: 1px solid #c7d2fe;}
      .cf-question-type {background: #4f46e5; color: white; border-color: #4f46e5;}
      .cf-question-limit {background: white; color: #6366f1;}
      .cf-question-copy {color: var(--cf-text); font-size: 1.02rem; font-weight: 690; line-height: 1.65; white-space: pre-wrap;}
      .cf-analysis-card {min-height: 10.5rem; margin: .35rem 0 .7rem; padding: .95rem 1rem; border: 1px solid var(--cf-border);
        border-top: 3px solid #818cf8; border-radius: .78rem; background: white;}
      .cf-analysis-card-caution {border-top-color: #fb923c; background: #fffcf8;}
      .cf-analysis-title {margin-bottom: .55rem; color: #475569; font-size: .78rem; font-weight: 780; letter-spacing: .02em;}
      .cf-analysis-card ul {margin: 0; padding-left: 1.05rem; color: #334155;}
      .cf-analysis-card li {margin: .28rem 0; font-size: .84rem; line-height: 1.5;}
      .cf-match-head {display: flex; align-items: center; justify-content: space-between; gap: 1rem; margin-bottom: .65rem;}
      .cf-match-name {margin-left: .55rem; color: var(--cf-text); font-size: 1.05rem; font-weight: 760;}
      .cf-match-score {color: #4338ca; font-size: 1.35rem; font-weight: 800; white-space: nowrap;}
      .cf-match-score small {margin-left: .15rem; color: #94a3b8; font-size: .68rem; font-weight: 650;}
      .cf-match-reason {margin-bottom: .7rem; color: #64748b; font-size: .84rem; line-height: 1.55;}
      .cf-match-breakdown {display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .45rem; margin: .7rem 0 .25rem;}
      .cf-match-breakdown div {padding: .55rem .62rem; border-radius: .58rem; background: #f8fafc; border: 1px solid #eef2f7;}
      .cf-match-breakdown span {display: block; color: #94a3b8; font-size: .64rem; font-weight: 680;}
      .cf-match-breakdown b {display: block; margin-top: .12rem; color: #334155; font-size: .9rem;}

      .cf-section-head {display: flex; justify-content: space-between; align-items: end; gap: 1rem; margin: 2rem 0 1rem;}
      .cf-section-kicker {color: #6366f1; font-size: .7rem; font-weight: 800; letter-spacing: .1em; text-transform: uppercase;}
      .cf-section-title {margin-top: .2rem; color: var(--cf-text); font-size: 1.35rem; font-weight: 780; letter-spacing: -.025em;}
      .cf-section-copy {max-width: 520px; color: var(--cf-muted); font-size: .84rem; line-height: 1.55; text-align: right;}
      .cf-app-head {display: flex; justify-content: space-between; align-items: flex-start; gap: 1rem; padding: .1rem 0 .8rem;}
      .cf-app-company {color: #6366f1; font-size: .72rem; font-weight: 800; letter-spacing: .08em; text-transform: uppercase;}
      .cf-app-role {margin-top: .18rem; color: var(--cf-text); font-size: 1.12rem; font-weight: 760; letter-spacing: -.02em;}
      .cf-app-badges {display: flex; justify-content: flex-end; flex-wrap: wrap; gap: .4rem;}
      .cf-status, .cf-deadline {display: inline-flex; align-items: center; padding: .3rem .58rem; border-radius: 999px;
        font-size: .72rem; font-weight: 730; border: 1px solid transparent; white-space: nowrap;}
      .cf-status-active {background: #eef2ff; color: #4338ca; border-color: #c7d2fe;}
      .cf-status-submitted {background: #eff6ff; color: #1d4ed8; border-color: #bfdbfe;}
      .cf-status-success {background: #ecfdf5; color: #047857; border-color: #a7f3d0;}
      .cf-status-danger {background: #fff1f2; color: #be123c; border-color: #fecdd3;}
      .cf-status-muted {background: #f1f5f9; color: #64748b; border-color: #e2e8f0;}
      .cf-deadline {background: #f8fafc; color: #475569; border-color: #e2e8f0;}
      .cf-deadline-soon {background: #fff7ed; color: #c2410c; border-color: #fed7aa;}
      .cf-deadline-over {background: #fff1f2; color: #be123c; border-color: #fecdd3;}
      .cf-app-meta {display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: .55rem; margin: .65rem 0 .75rem;}
      .cf-app-meta-item {padding: .68rem .75rem; border-radius: .65rem; background: #f8fafc; border: 1px solid #eef2f7;}
      .cf-app-meta-label {color: #94a3b8; font-size: .68rem; font-weight: 700;}
      .cf-app-meta-value {margin-top: .12rem; color: #334155; font-size: 1rem; font-weight: 760;}
      .cf-app-memo {margin: .55rem 0 .2rem; padding: .72rem .8rem; border-left: 3px solid #c7d2fe; border-radius: 0 .55rem .55rem 0;
        background: #fafbff; color: #475569; font-size: .82rem; line-height: 1.55;}
      .cf-app-empty {padding: .7rem 0; color: #94a3b8; font-size: .8rem;}

      @media (max-width: 700px) {
        .block-container {padding: 1.5rem 1rem 3rem;}
        h1 {font-size: 1.65rem !important;}
        .cf-section-head, .cf-app-head {align-items: flex-start; flex-direction: column;}
        .cf-section-copy {text-align: left;}
        .cf-app-badges {justify-content: flex-start;}
        .cf-match-head {align-items: flex-start;}
        .cf-match-breakdown {grid-template-columns: repeat(2, minmax(0, 1fr));}
        .cf-profile-overview {align-items: flex-start; flex-wrap: wrap;}
        .cf-profile-completion {width: 100%; align-items: flex-start; padding: .65rem 0 0; border-left: 0; border-top: 1px solid #dbe2f4;}
        .cf-form-section {align-items: flex-start; flex-direction: column; gap: .15rem;}
        .cf-material-grid {grid-template-columns: 1fr;}
      }
    </style>
    """,
    unsafe_allow_html=True,
)

account = get_account(st.session_state.get("account_id"))
if account is None:
    _render_auth()
    st.stop()

with st.sidebar:
    st.markdown(
        """<div class="cf-brand"><div class="cf-brand-mark">CF</div><div>
        <div class="cf-brand-title">CareerFit AI</div>
        <div class="cf-brand-copy">경험 근거로 설계하는 지원 전략</div></div></div>""",
        unsafe_allow_html=True,
    )
    with st.expander("새 프로필 만들기"):
        with st.form("create_profile"):
            new_profile_name = st.text_input("프로필 이름", placeholder="예: 데이터 분석 지원")
            create_profile = st.form_submit_button("프로필 추가", use_container_width=True)
        if create_profile:
            try:
                st.session_state["active_user_id"] = create_user(new_profile_name, account["id"])
                st.success("새 프로필을 만들었습니다.")
            except ValueError as exc:
                st.error(str(exc))

    users = list_users(account["id"])
    user_ids = [user["id"] for user in users]
    if st.session_state.get("active_user_id") not in user_ids:
        st.session_state["active_user_id"] = user_ids[0]
    user_names = {user["id"]: user["display_name"] for user in users}
    active_user_id = st.selectbox(
        "현재 프로필",
        user_ids,
        format_func=lambda user_id: f"{user_names[user_id]} (#{user_id})",
        key="active_user_id",
    )
    st.caption(f"{account['display_name']} · {account['email']}")
    if st.button("로그아웃", use_container_width=True):
        st.session_state.pop("account_id", None)
        st.session_state.pop("active_user_id", None)
        st.rerun()
    st.divider()
    page = st.radio(
        "Navigation",
        ["My Profile", "My Experiences", "JD Analyzer", "Essay Planner", "Career Dashboard"],
        format_func={
            "My Profile": "👤  프로필",
            "My Experiences": "📚  경험 관리",
            "JD Analyzer": "🔎  JD 분석",
            "Essay Planner": "✍️  자기소개서",
            "Career Dashboard": "📋  지원 관리",
        }.get,
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown('<div class="cf-phase">Phase 4 · Application Tracker</div>', unsafe_allow_html=True)

if notice := st.session_state.pop("delete_notice", None):
    st.success(notice)

if page == "My Profile":
    profile.render(active_user_id)
elif page == "My Experiences":
    experiences.render(active_user_id)
elif page == "JD Analyzer":
    jd_analyzer.render(active_user_id)
elif page == "Essay Planner":
    essay_planner.render(active_user_id)
elif page == "Career Dashboard":
    dashboard.render(active_user_id)
else:
    st.title(page)
    st.info("준비 중인 화면입니다.")
