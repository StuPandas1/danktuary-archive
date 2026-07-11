import streamlit as st
import streamlit_authenticator as stauth
import secrets
from datetime import datetime, timezone, timedelta
from supabase import create_client

_SESSION_PARAM = "session"


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
    """
    Reads the session token from the URL query string, not a cookie.
    st.query_params comes straight from the request line -- it's not
    filtered by Community Cloud's proxy the way headers/cookies are,
    and needs no component/iframe round-trip.
    """
    if st.session_state.get("authentication_status"):
        return

    token = st.query_params.get(_SESSION_PARAM)
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
            if _SESSION_PARAM in st.query_params:
                del st.query_params[_SESSION_PARAM]
            return
        st.session_state["authentication_status"] = True
        st.session_state["username"] = session["username"]
        st.session_state["name"] = session["name"]
        st.session_state["session_token"] = token
    except Exception:
        return


def sync_login_cookie(expiry_days):
    """Writes the session token into the URL query string."""
    if not st.session_state.get("authentication_status"):
        return
    existing = st.session_state.get("session_token")
    if existing and st.query_params.get(_SESSION_PARAM) == existing:
        return  # already synced
    username = st.session_state.get("username")
    name = st.session_state.get("name")
    if not username:
        return
    token = existing or create_session(username, name, expiry_days)
    st.session_state["session_token"] = token
    st.query_params[_SESSION_PARAM] = token


def clear_login_cookie():
    token = st.session_state.get("session_token")
    delete_session(token)
    st.session_state["session_token"] = None
    if _SESSION_PARAM in st.query_params:
        del st.query_params[_SESSION_PARAM]