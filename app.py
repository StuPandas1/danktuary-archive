import streamlit as st  # type: ignore

st.set_page_config(page_title="DankApp", layout="wide", initial_sidebar_state="collapsed")

from auth_shared import get_authenticator
from shared import load_users_from_supabase

# 1. Fetch user records from Supabase
try:
    credentials = load_users_from_supabase()
    st.session_state["supabase_up"] = True
except Exception:
    credentials = {"usernames": {}}
    st.session_state["supabase_up"] = False

st.session_state["credentials"] = credentials

# 2. Setup Authenticator object
if st.session_state["supabase_up"]:
    authenticator = get_authenticator(credentials)
    st.session_state["authenticator"] = authenticator
    
    # 🌟 STEP 1: Always execute unrendered login check with a persistent KEY
    try:
        authenticator.login(location='unrendered', key="global_cookie_manager")
    except Exception:
        pass

# 3. 🌟 STEP 2: COOKIE SYNC AND AUTO-RERUN HYDRATION
# If a user hits refresh, Python finishes before JS updates the token. 
# We track if the cookie has completed its handshake using a tracking flag.
cookie_name = st.secrets["cookie"]["name"]
has_cookie_file = cookie_name in st.context.cookies

if has_cookie_file and st.session_state.get("authentication_status") is None:
    if not st.session_state.get("cookie_hydrated", False):
        st.session_state["cookie_hydrated"] = True
        st.rerun()  # Forces frame reload to receive the processed cookie data

# 4. GET AUTHENTICATION STATUS
auth_status = st.session_state.get("authentication_status")

# 5. DYNAMIC ROUTER LIFE-CYCLE
# If authenticated, expose all dashboard assets
if auth_status is True:
    pg = st.navigation([
        st.Page("pages/landing.py", title="Dashboard", icon="💀", default=True),
        st.Page("pages/tools.py", title="Useful Tools", icon="🛠️"),
        st.Page("pages/explore.py", title="Explore the Archive", icon="🔍"),
        st.Page("pages/listen.py", title="Listen", icon="🎧"),
    ], position="hidden")

# If unauthenticated, sandbox them to the login form entry on listen.py
else:
    pg = st.navigation([
        st.Page("pages/listen.py", title="Listen", icon="🎧", default=True)
    ], position="hidden")

pg.run()