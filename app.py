import streamlit as st

st.set_page_config(page_title="DankApp", layout="wide", initial_sidebar_state="collapsed")

pg = st.navigation(
    [
        st.Page("pages/landing.py", title="Dashboard", icon="💀", default=True),
        st.Page("pages/shows.py", title="Shows", icon="🎤"),
        st.Page("pages/songs.py", title="Songs", icon="🎵"),
        st.Page("pages/stats.py", title="Stats", icon="📊"),
        st.Page("pages/randomizer.py", title="Randomizer", icon="🎲"),
        st.Page("pages/watch.py", title="Watch", icon="🎬"),
        st.Page("pages/playlists.py", title="Playlists", icon="🎧"),
    ],
    position="hidden",
)

pg.run()