import streamlit as st  # type: ignore

st.set_page_config(page_title="DankApp", layout="wide", initial_sidebar_state="collapsed")

from auth_shared import get_authenticator
from shared import load_users_from_supabase

pg = st.navigation(
    [
        st.Page("pages/landing.py", title="Dashboard", icon="💀", default=True),
        st.Page("pages/tools.py", title="Useful Tools", icon="🛠️"),
        st.Page("pages/explore.py", title="Explore the Archive", icon="🔍"),
        st.Page("pages/listen.py", title="Listen", icon="🎧"),
    ],
    position="hidden"
)

try:
    credentials = load_users_from_supabase()
    st.session_state["supabase_up"] = True
except Exception:
    credentials = {"usernames": {}}
    st.session_state["supabase_up"] = False

if st.session_state["supabase_up"]:
    authenticator = get_authenticator(credentials)
    try:
        authenticator.login(location="unrendered")
    except Exception as e:
        st.write("DEBUG cookie login error:", repr(e))  # keep this for now
    st.session_state["authenticator"] = authenticator

pg.run()