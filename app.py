import streamlit as st  # type: ignore

st.set_page_config(page_title="DankApp", layout="wide", initial_sidebar_state="collapsed")

pg = st.navigation(
    [
        st.Page("Pages/landing.py", title="Dashboard", icon="💀", default=True),
        st.Page("Pages/tools.py", title="Useful Tools", icon="🛠️"),
        st.Page("Pages/explore.py", title="Explore the Archive", icon="🔍"),
    ],
    position="hidden"
)

pg.run()
