import streamlit as st  # type: ignore

st.set_page_config(page_title="DankApp", layout="wide", initial_sidebar_state="collapsed")

from auth_shared import get_authenticator, get_cookie_manager, restore_login_from_cookie, sync_login_cookie
from shared import load_users_from_supabase

# Must come early, before anything else that depends on login state.
cookies = get_cookie_manager()
if not cookies.ready():
    st.stop()

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
except Exception as e:
    st.write("DEBUG supabase error:", repr(e))
    credentials = {"usernames": {}}
    st.session_state["supabase_up"] = False

if st.session_state["supabase_up"]:
    authenticator = get_authenticator(credentials)
    st.session_state["authenticator"] = authenticator

    restore_login_from_cookie(cookies, credentials)
    sync_login_cookie(cookies, st.secrets["cookie"]["expiry_days"])

pg.run()