import streamlit as st  # type: ignore

st.set_page_config(page_title="DankApp", layout="wide", initial_sidebar_state="collapsed")

from auth_shared import get_authenticator
from shared import load_users_from_supabase

# 1. Load your credentials and construct your Authenticator
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
    
    # 🌟 CRITICAL COOKIE STEP: Natively prompt the cookie recheck on EVERY execution
    try:
        authenticator.login(location='unrendered')
    except Exception:
        pass

# 2. Get the real-time auth status
auth_status = st.session_state.get("authentication_status")

# 3. DYNAMIC NAVIGATION GATEKEEPER
# If the user is logged in, show all pages normally.
if auth_status is True:
    pg = st.navigation([
        st.Page("pages/landing.py", title="Dashboard", icon="💀", default=True),
        st.Page("pages/tools.py", title="Useful Tools", icon="🛠️"),
        st.Page("pages/explore.py", title="Explore the Archive", icon="🔍"),
        st.Page("pages/listen.py", title="Listen", icon="🎧"),
    ], position="hidden")

# If they are NOT logged in, restrict the navigation tree ONLY to the login page
else:
    pg = st.navigation([
        st.Page("pages/listen.py", title="Listen", icon="🎧", default=True)
    ], position="hidden")

# 4. Fire the router
pg.run()