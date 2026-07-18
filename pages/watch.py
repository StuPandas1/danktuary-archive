
import os
import re
import pandas as pd
import streamlit as st

try:
    from shared import dank_header, page_menu
    HAVE_SHARED = True
except ImportError:
    HAVE_SHARED = False

VIDEO_CSV_PATH = "video_links.csv"  # adjust if your CSV lives elsewhere


@st.cache_data
def load_video_links(path: str, _mtime: float) -> pd.DataFrame:
    """Load playlist title/URL pairs. _mtime param busts the cache on file change."""
    df = pd.read_csv(path)
    df = df.dropna(subset=["Title", "URL"]).copy()
    df["Title"] = df["Title"].astype(str).str.strip()
    df["URL"] = df["URL"].astype(str).str.strip()
    df = df[(df["Title"] != "") & (df["URL"] != "")]
    return df.reset_index(drop=True)


def get_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def extract_playlist_id(url: str):
    """Pull the list= param out of a YouTube playlist URL."""
    match = re.search(r"[?&]list=([a-zA-Z0-9_-]+)", url)
    return match.group(1) if match else None


def render_embed(playlist_id: str):
    embed_url = f"https://www.youtube.com/embed/videoseries?list={playlist_id}"
    st.components.v1.iframe(embed_url, height=480, scrolling=False)


def _inject_local_theme():
    """Fallback dark theme if shared.py isn't wired up yet. Safe to delete
    once you're pulling the real theme from shared.py."""
    st.markdown(
        """
        <style>
        :root {
            --dank-charcoal: #1e1e1e;
            --dank-amber: #d9a441;
            --dank-sage: #8ba888;
        }
        div[data-testid="stAppViewContainer"] { background-color: var(--dank-charcoal); }
        .watch-title-btn button {
            width: 100%;
            text-align: left;
            border: 1px solid var(--dank-sage);
            color: var(--dank-amber);
            background-color: transparent;
        }
        .watch-title-btn button:hover {
            border-color: var(--dank-amber);
            color: var(--dank-sage);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    if not HAVE_SHARED:
        _inject_local_theme()
        st.title("🎬 Watch")
        st.caption("Gig and practice footage, straight from YouTube.")
    else:
        dank_header("We'll do it live")

    df = load_video_links(VIDEO_CSV_PATH, get_mtime(VIDEO_CSV_PATH))

    if df.empty:
        st.info("No playlists found in video_links.csv yet.")
        return

    if "watch_selected_title" not in st.session_state:
        st.session_state.watch_selected_title = df.iloc[0]["Title"]

    col_list, col_player = st.columns([1, 3], gap="large")

    with col_list:
        st.subheader("Playlists")
        for i, row in df.iterrows():
            title = row["Title"]
            is_active = title == st.session_state.watch_selected_title
            label = f"▸ {title}" if is_active else title
            st.markdown('<div class="watch-title-btn">', unsafe_allow_html=True)
            if st.button(label, key=f"watch_btn_{i}", use_container_width=True):
                st.session_state.watch_selected_title = title
                st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)

    with col_player:
        selected_row = df[df["Title"] == st.session_state.watch_selected_title].iloc[0]
        st.subheader(selected_row["Title"])
        playlist_id = extract_playlist_id(selected_row["URL"])
        if playlist_id:
            render_embed(playlist_id)
        else:
            st.warning("Couldn't parse a playlist ID from this URL.")
            st.markdown(f"[Open on YouTube]({selected_row['URL']})")


if __name__ == "__main__":
    main()