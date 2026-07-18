"""
Watch page -- embedded YouTube playlist viewer for the Danktuary Archive.

Reads video_links.csv (columns: Title, URL). Each row's URL can be either
a YouTube playlist (e.g. https://www.youtube.com/playlist?list=PLxxxxxxxx)
or a single watch link (e.g. https://www.youtube.com/watch?v=xxxxxxxxxxx) --
both are detected and handled automatically.

Mobile-first, single-column layout:
  1. Picker -- dropdown, no visible label, sits above the video
  2. Embedded player -- for playlists: the whole playlist, or a single
     track if one was picked from the track list below. For single-video
     links: just that video, no tracklist section.
  3. Track list (playlists only) -- pulled live from YouTube via yt-dlp
     (no API key needed), clickable to jump to that track in the embed

Requires `yt-dlp` in requirements.txt.

Integration notes:
- Add to app.py's st.navigation(): st.Page("pages/watch.py", title="Watch", icon="🎬")
- Don't call st.set_page_config() here if app.py already sets it globally.
- If dank_header / page_menu / theme vars already live in shared.py, this
  file will pick them up automatically (see HAVE_SHARED below) -- delete
  _inject_base_theme_fallback() once that's wired in.
- Not auth-gated by default, matching that auth is scoped to Listen only.
  Wrap main() with your auth_shared guard if you want this behind login too.
"""

import os
import re

import pandas as pd
import streamlit as st
import yt_dlp

try:
    from shared import dank_header, page_menu
    HAVE_SHARED = True
except ImportError:
    HAVE_SHARED = False

VIDEO_CSV_PATH = "video_links.csv"  # adjust if your CSV lives elsewhere
TRACKLIST_CACHE_TTL = 60 * 60 * 6  # 6 hours


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


def parse_youtube_url(url: str):
    """Identify whether a link is a playlist or a single video, and pull its ID.
    Returns (kind, id) where kind is 'playlist', 'video', or None if neither
    pattern matches. A watch URL with both v= and list= (a video inside a
    playlist) is treated as 'playlist', since that's the richer experience."""
    playlist_match = re.search(r"[?&]list=([a-zA-Z0-9_-]+)", url)
    if playlist_match:
        return "playlist", playlist_match.group(1)
    video_match = re.search(r"(?:[?&]v=|youtu\.be/|/embed/)([a-zA-Z0-9_-]{11})", url)
    if video_match:
        return "video", video_match.group(1)
    return None, None


def format_duration(seconds):
    if not seconds:
        return ""
    seconds = int(seconds)
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


@st.cache_data(ttl=TRACKLIST_CACHE_TTL, show_spinner="Loading tracklist...")
def fetch_playlist_tracks(playlist_url: str):
    """Flat-extract a YouTube playlist's video titles/ids via yt-dlp.
    No download, no API key -- just reads the playlist page."""
    ydl_opts = {
        "extract_flat": "in_playlist",
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)
    except Exception as e:
        return {"error": str(e), "tracks": []}

    entries = info.get("entries") or []
    tracks = []
    for e in entries:
        if not e:
            continue
        tracks.append({
            "title": e.get("title") or "Untitled",
            "video_id": e.get("id"),
            "duration": e.get("duration"),
        })
    return {"error": None, "tracks": tracks}


@st.cache_data(ttl=TRACKLIST_CACHE_TTL, show_spinner="Loading track info...")
def fetch_video_info(video_url: str):
    """Pull a single video's title/id/duration via yt-dlp, for the one-row
    tracklist shown under single-watch-link entries."""
    ydl_opts = {
        "extract_flat": True,
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
    except Exception as e:
        return {"error": str(e), "track": None}

    track = {
        "title": info.get("title") or "Untitled",
        "video_id": info.get("id"),
        "duration": info.get("duration"),
    }
    return {"error": None, "track": track}


def _responsive_embed(embed_url: str):
    """Render a YouTube iframe that holds a true 16:9 ratio at any column
    width, via the aspect-ratio-box CSS trick (padding-top: 56.25%). A fixed
    height with unset width breaks proportions on narrow mobile columns and
    looks short on wide desktop ones -- this fixes both."""
    st.markdown(
        f"""
        <div style="position: relative; width: 100%; padding-top: 56.25%; margin-bottom: 0.5rem;">
            <iframe
                src="{embed_url}"
                style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; border: 0;"
                allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture"
                allowfullscreen>
            </iframe>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_playlist_embed(playlist_id: str, video_id: str = None):
    if video_id:
        embed_url = f"https://www.youtube.com/embed/{video_id}?list={playlist_id}"
    else:
        embed_url = f"https://www.youtube.com/embed/videoseries?list={playlist_id}"
    _responsive_embed(embed_url)


def render_video_embed(video_id: str):
    embed_url = f"https://www.youtube.com/embed/{video_id}"
    _responsive_embed(embed_url)


def render_tracklist(tracks, active_video_id, clickable=True, key_prefix="watch_track"):
    """Render a list of numbered track rows. Used for both the full playlist
    tracklist and the single-track row under a lone watch link, so the two
    always stay visually identical. When clickable=False (single-video case),
    the row still renders with the same formatting but as a disabled button --
    there's only one track, so clicking it wouldn't do anything."""
    for i, track in enumerate(tracks):
        is_active = clickable and track["video_id"] == active_video_id
        row_class = "track-row-active" if (is_active or not clickable) else "track-row"
        dur = format_duration(track["duration"])
        label = f"{i + 1}. {track['title']}" + (f"  ·  {dur}" if dur else "")
        st.markdown(f'<div class="{row_class}">', unsafe_allow_html=True)
        clicked = st.button(
            label,
            key=f"{key_prefix}_{i}",
            use_container_width=True,
            disabled=not clickable,
        )
        st.markdown("</div>", unsafe_allow_html=True)
        if clickable and clicked:
            st.session_state.watch_selected_video_id = track["video_id"]
            st.rerun()


def _inject_base_theme_fallback():
    """Fallback dark background only -- skip this once shared.py's real
    theme is wired in (see HAVE_SHARED above)."""
    st.markdown(
        """
        <style>
        :root {
            --dank-charcoal: #1e1e1e;
            --dank-amber: #d9a441;
            --dank-sage: #8ba888;
        }
        div[data-testid="stAppViewContainer"] { background-color: var(--dank-charcoal); }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _inject_track_list_css():
    """Styling for the dropdown + track list. Page-specific, always applied.
    Uses var(--dank-*, fallback) so it works with or without shared.py's theme."""
    st.markdown(
        """
        <style>
        div[data-testid="stSelectbox"] label { display: none; }
        .track-row button {
            width: 100%;
            text-align: left;
            border: none;
            border-bottom: 1px solid rgba(255,255,255,0.08);
            border-radius: 0;
            background-color: transparent;
            color: var(--dank-amber, #d9a441);
            padding: 6px 8px;
        }
        .track-row button:hover {
            background-color: rgba(139, 168, 136, 0.15);
            color: var(--dank-sage, #8ba888);
        }
        .track-row-active button {
            color: var(--dank-sage, #8ba888);
            font-weight: 600;
        }
        .track-row-active button:disabled {
            color: var(--dank-sage, #8ba888);
            opacity: 1;
            cursor: default;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def main():
    if HAVE_SHARED:
        dank_header("See the man with the stage fright...")
    else:
        _inject_base_theme_fallback()
        st.title("🎬 Watch")

    _inject_track_list_css()

    df = load_video_links(VIDEO_CSV_PATH, get_mtime(VIDEO_CSV_PATH))

    if df.empty:
        st.info("No playlists found in video_links.csv yet.")
        return

    titles = df["Title"].tolist()

    if "watch_selected_title" not in st.session_state:
        st.session_state.watch_selected_title = titles[0]
    if "watch_selected_video_id" not in st.session_state:
        st.session_state.watch_selected_video_id = None

    # 1. Playlist picker -- dropdown, no visible label, mobile-friendly
    st.write("Pick something to watch:")
    selected_title = st.selectbox(
        "Playlist",
        options=titles,
        index=titles.index(st.session_state.watch_selected_title),
        label_visibility="collapsed",
        key="watch_playlist_picker",
    )
    if selected_title != st.session_state.watch_selected_title:
        st.session_state.watch_selected_title = selected_title
        st.session_state.watch_selected_video_id = None  # reset to playlist start

    selected_row = df[df["Title"] == st.session_state.watch_selected_title].iloc[0]
    link_type, link_id = parse_youtube_url(selected_row["URL"])

    if link_type is None:
        st.warning("Couldn't parse a YouTube ID from this URL.")
        st.markdown(f"[Open on YouTube]({selected_row['URL']})")
        return

    if link_type == "video":
        # Single watch link -- embed it, then show its title as a one-row
        # tracklist (same formatting as playlists, just non-interactive).
        render_video_embed(link_id)
        result = fetch_video_info(selected_row["URL"])
        if result["error"]:
            st.caption("Couldn't load track info for this video right now.")
        else:
            render_tracklist([result["track"]], active_video_id=link_id, clickable=False)
        return

    # link_type == "playlist" from here on
    playlist_id = link_id

    # 2. Embedded player
    render_playlist_embed(playlist_id, st.session_state.watch_selected_video_id)

    # 3. Interactive track list, pulled live from YouTube
    result = fetch_playlist_tracks(selected_row["URL"])
    if result["error"]:
        st.caption("Couldn't load the tracklist for this playlist right now.")
    else:
        tracks = result["tracks"]
        header_col, refresh_col = st.columns([5, 1])
        with header_col:
            st.caption(f"{len(tracks)} tracks")

        with st.container(height=1000):
            st.write("Jump to another track in this playlist:")
            render_tracklist(tracks, active_video_id=st.session_state.watch_selected_video_id)
        
        with refresh_col:
            if st.button("🔄", help="Refresh tracklist", key="watch_refresh_tracks"):
                fetch_playlist_tracks.clear()
                st.rerun()


if __name__ == "__main__":
    main()