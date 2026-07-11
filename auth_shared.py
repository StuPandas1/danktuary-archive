import streamlit as st
import streamlit.components.v1 as components
import streamlit_authenticator as stauth
import secrets
from datetime import datetime, timezone, timedelta
from supabase import create_client

_COOKIE_NAME = "dankapp_session"

def get_supabase():
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

def get_authenticator(credentials):
    if "authenticator" not in st.session_state:
        st.session_state["authenticator"] = stauth.Authenticate(
            credentials,
            st.secrets["cookie"]["name"],
            st.secrets["cookie"]["key"],
            st.secrets["cookie"]["expiry_days"],
        )
    return st.session_state["authenticator"]

def create_session(username, name, expiry_days):
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(days=expiry_days)
    get_supabase().table("sessions").insert({
        "username": username,
        "name": name,
        "token": token,
        "expires_at": expires_at.isoformat()
    }).execute()
    return token

def delete_session(token):
    if token:
        get_supabase().table("sessions").delete().eq("token", token).execute()

def restore_login_from_cookie(credentials):
    """Read-only, synchronous — no rerun loop needed."""
    if st.session_state.get("authentication_status"):
        return

    token = st.context.cookies.get(_COOKIE_NAME)
    if not token:
        return

    try:
        result = get_supabase().table("sessions").select("*").eq("token", token).execute()
        if not result.data:
            return
        session = result.data[0]
        expires_at = datetime.fromisoformat(session["expires_at"])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires_at:
            delete_session(token)
            return
        st.session_state["authentication_status"] = True
        st.session_state["username"] = session["username"]
        st.session_state["name"] = session["name"]
        st.session_state["session_token"] = token
    except Exception:
        return

def _write_cookie_js(name, value, max_age_seconds):
    components.html(
        f"""
        <script>
        document.cookie = "{name}={value}; max-age={max_age_seconds}; path=/; SameSite=Lax";
        </script>
        """,
        height=0,
        width=0,
    )

def _clear_cookie_js(name):
    components.html(
        f"""
        <script>
        document.cookie = "{name}=; max-age=0; path=/; SameSite=Lax";
        </script>
        """,
        height=0,
        width=0,
    )

def sync_login_cookie(expiry_days):
    if not st.session_state.get("authentication_status"):
        return
    if st.session_state.get("session_token"):
        return  # already have a token this session, nothing new to write
    username = st.session_state.get("username")
    name = st.session_state.get("name")
    if not username:
        return
    
def clear_login_cookie():
    token = st.session_state.get("session_token")
    delete_session(token)
    st.session_state["session_token"] = None
    _clear_cookie_js(_COOKIE_NAME)