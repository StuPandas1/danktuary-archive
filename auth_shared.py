import streamlit as st
import streamlit_authenticator as stauth
from streamlit_cookies_manager import EncryptedCookieManager
import json
import time

def get_authenticator(credentials):
    if "authenticator" not in st.session_state:
        st.session_state["authenticator"] = stauth.Authenticate(
            credentials,
            st.secrets["cookie"]["name"],
            st.secrets["cookie"]["key"],
            0,  # disable streamlit_authenticator's own broken cookie handling
        )
    return st.session_state["authenticator"]

def get_cookie_manager():
    if "cookie_manager" not in st.session_state:
        st.session_state["cookie_manager"] = EncryptedCookieManager(
            prefix="dankapp/",
            password=st.secrets["cookie"]["key"],  # reuse your existing secret
        )
    return st.session_state["cookie_manager"]

_COOKIE_KEY = "dankapp_auth"

def restore_login_from_cookie(cookies, credentials):
    """On a fresh session, pull login state back out of our own cookie."""
    if st.session_state.get("authentication_status"):
        return  # already logged in this session

    raw = cookies.get(_COOKIE_KEY)
    if not raw:
        return
    try:
        payload = json.loads(raw)
        username, exp_date = payload["username"], payload["exp_date"]
    except (KeyError, ValueError, TypeError):
        return

    if time.time() > exp_date:
        if _COOKIE_KEY in cookies:
            del cookies[_COOKIE_KEY]
            cookies.save()
        return

    user_record = credentials.get("usernames", {}).get(username)
    if not user_record:
        return

    st.session_state["authentication_status"] = True
    st.session_state["username"] = username
    st.session_state["name"] = user_record.get("name", username)

def sync_login_cookie(cookies, expiry_days):
    """Keep our cookie in sync with session_state after a real login happens."""
    if not st.session_state.get("authentication_status"):
        return
    username = st.session_state.get("username")
    if not username:
        return

    raw = cookies.get(_COOKIE_KEY)
    if raw:
        try:
            payload = json.loads(raw)
            if payload.get("username") == username and payload.get("exp_date", 0) - time.time() > 86400:
                return  # still valid for >1 day, no need to rewrite
        except (ValueError, TypeError):
            pass

    cookies[_COOKIE_KEY] = json.dumps({
        "username": username,
        "exp_date": time.time() + expiry_days * 86400,
    })
    cookies.save()

def clear_login_cookie(cookies):
    if _COOKIE_KEY in cookies:
        del cookies[_COOKIE_KEY]
        cookies.save()