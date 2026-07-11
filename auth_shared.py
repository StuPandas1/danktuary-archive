import streamlit as st
import streamlit_authenticator as stauth
import secrets
import time
from datetime import datetime, timezone, timedelta
from supabase import create_client
from streamlit_cookies_controller import CookieController

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


def get_cookie_controller():
    """
    Must be called unconditionally near the top of app.py, every run,
    outside any expander/conditional, so the component actually mounts.
    Cached in session_state so read/write calls hit the same instance.
    """
    if "cookie_controller" not in st.session_state:
        st.session_state["cookie_controller"] = CookieController(key="dankapp_cookie_controller")
    return st.session_state["cookie_controller"]


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
    if st.session_state.get("authentication_status"):
        return

    controller = get_cookie_controller()
    all_cookies = controller.getAll()

    if all_cookies is None:
        retries = st.session_state.get("_cookie_retry_count", 0)
        if retries < 5:
            st.session_state["_cookie_retry_count"] = retries + 1
            time.sleep(0.15)
            st.rerun()
        return  # gave it 5 tries -- treat as no session this load

    token = all_cookies.get(_COOKIE_NAME)
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


def sync_login_cookie(expiry_days):
    if not st.session_state.get("authentication_status"):
        return
    if st.session_state.get("session_token"):
        return
    username = st.session_state.get("username")
    name = st.session_state.get("name")
    if not username:
        return
    token = create_session(username, name, expiry_days)
    st.session_state["session_token"] = token
    controller = get_cookie_controller()
    max_age = int(expiry_days * 86400)
    controller.set(_COOKIE_NAME, token, max_age=max_age)


def clear_login_cookie():
    token = st.session_state.get("session_token")
    delete_session(token)
    st.session_state["session_token"] = None
    controller = get_cookie_controller()
    controller.remove(_COOKIE_NAME)