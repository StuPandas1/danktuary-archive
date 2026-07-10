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

st.session_state["credentials"] = credentials

if st.session_state["supabase_up"]:
    authenticator = get_authenticator(credentials)
    st.session_state["authenticator"] = authenticator
    
    # 🌟 STEP 1: Pass an explicit, static string KEY to the unrendered login check.
    # Without a key, the JavaScript component drops cookie tracking on a hard refresh.
    try:
        authenticator.login(location='unrendered', key="global_cookie_tracker")
    except Exception:
        pass

    # 🌟 STEP 2: NATIVE STREAMLIT COOKIE FAILSAFE
    # If a hard refresh wiped st.session_state, but the browser still has the cookie,
    # force a quick automatic rerun to allow the JS component to finish hydrating Python.
    cookie_name = st.secrets["cookie"]["name"]
    has_cookie = cookie_name in st.context.cookies
    
    if has_cookie and st.session_state.get("authentication_status") is None:
        st.rerun()

pg.run()