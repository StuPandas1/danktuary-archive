import streamlit as st
import streamlit_authenticator as stauth
from streamlit.components.v1 import html as components_html
import hmac
import hashlib
import time

def get_authenticator(credentials):
    if "authenticator" not in st.session_state:
        st.session_state["authenticator"] = stauth.Authenticate(
            credentials,
            st.secrets["cookie"]["name"],
            st.secrets["cookie"]["key"],
            0,  # we handle persistence ourselves now
        )
    return st.session_state["authenticator"]

_COOKIE_NAME = "dankapp_auth"

def _sign(username: str, exp: int) -> str:
    secret = st.secrets["cookie"]["key"].encode()
    msg = f"{username}|{exp}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()

def restore_login_from_cookie(credentials):
    """Reads our own signed cookie straight from the request headers. Synchronous, no waiting."""
    if st.session_state.get("authentication_status"):
        return

    raw = st.context.cookies.get(_COOKIE_NAME)
    if not raw:
        return
    try:
        username, exp_str, sig = raw.split("|")
        exp = int(exp_str)
    except ValueError:
        return
    if time.time() > exp:
        return
    if not hmac.compare_digest(sig, _sign(username, exp)):
        return  # tampered or forged cookie, ignore it

    user_record = credentials.get("usernames", {}).get(username)
    if not user_record:
        return

    st.session_state["authentication_status"] = True
    st.session_state["username"] = username
    st.session_state["name"] = user_record.get("name", username)

def sync_login_cookie(expiry_days: float):
    if not st.session_state.get("authentication_status"):
        return
    username = st.session_state.get("username")
    if not username:
        return
    exp = int(time.time() + expiry_days * 86400)
    sig = _sign(username, exp)
    value = f"{username}|{exp}|{sig}"
    max_age = int(expiry_days * 86400)
    components_html(
        f"""
        <script>
        try {{
            window.parent.document.cookie = "{_COOKIE_NAME}={value}; path=/; max-age={max_age}; SameSite=Lax";
        }} catch (e) {{
            console.error("DankApp cookie write failed:", e);
        }}
        </script>
        """,
        height=0,
    )

def clear_login_cookie():
    components_html(
        f"""
        <script>
        try {{
            window.parent.document.cookie = "{_COOKIE_NAME}=; path=/; max-age=0; SameSite=Lax";
        }} catch (e) {{
            console.error("DankApp cookie clear failed:", e);
        }}
        </script>
        """,
        height=0,
    )