import streamlit as st  # type: ignore
from shared import authenticate_user

st.set_page_config(page_title="DankApp", layout="wide", initial_sidebar_state="collapsed")

# Process Azure AD redirect BEFORE loading any pages
authenticate_user()

pg = st.navigation(
    [
        st.Page("pages/landing.py", title="Dashboard", icon="💀", default=True),
        st.Page("pages/tools.py", title="Useful Tools", icon="🛠️"),
        st.Page("pages/explore.py", title="Explore the Archive", icon="🔍"),
        st.Page("pages/listen.py", title="Listen", icon="🎧"),
    ],
    position="hidden"
)

pg.run()
