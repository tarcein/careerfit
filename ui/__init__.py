from html import escape

import streamlit as st


def page_header(eyebrow: str, title: str, description: str) -> None:
    st.markdown(
        f"""<div class="cf-page-hero"><div class="cf-page-eyebrow">{escape(eyebrow)}</div>
        <h1 class="cf-page-title">{escape(title)}</h1>
        <div class="cf-page-description">{escape(description)}</div></div>""",
        unsafe_allow_html=True,
    )
