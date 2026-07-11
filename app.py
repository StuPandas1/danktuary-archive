import streamlit as st

st.set_page_config(page_title="DankApp", layout="wide", initial_sidebar_state="collapsed")

from auth_shared import get_authenticator, restore_login_from_cookie, sync_login_cookie
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

# restore login from our own signed cookie — synchronous, no stauth needed
restore_login_from_cookie(credentials)

if st.session_state["supabase_up"]:
    authenticator = get_authenticator(credentials)
    st.session_state["authenticator"] = authenticator

if "session_token" not in st.session_state:
    st.session_state["session_token"] = None

pg.run()

# write/refresh cookie after page runs if logged in
if st.session_state.get("supabase_up") and st.session_state.get("authentication_status"):
    sync_login_cookie(st.secrets["cookie"]["expiry_days"])