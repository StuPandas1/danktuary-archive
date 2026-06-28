import streamlit as st  # type: ignore

st.set_page_config(page_title="DankApp", layout="wide", initial_sidebar_state="collapsed")


pg = st.navigation(
    [
        st.Page("pages/landing.py", title="Dashboard", icon="💀", default=True),
        st.Page("pages/tools.py", title="Useful Tools", icon="🛠️"),
        st.Page("pages/explore.py", title="Explore the Archive", icon="🔍"),
        # st.Page("pages/listen.py", title="Listen", icon="🎧"),
    ],
    position="hidden"
)

pg.run()
