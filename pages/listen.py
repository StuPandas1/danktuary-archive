import streamlit as st  # type: ignore
from shared import slug_to_show  # type: ignore

# Old /listen links (and /listen?show=...) now live on the Shows page.
show = slug_to_show(st.query_params.get("show"))
if show:
    st.session_state["pending_show"] = show

st.query_params.clear()
st.switch_page("pages/shows.py")