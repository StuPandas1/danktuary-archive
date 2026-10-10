import streamlit as st  # type: ignore
import streamlit.components.v1 as components
from shared import (
    page_menu, dank_header, dank_theme, dank_footer, dank_sign, dank_hex,
    load_playlists_from_supabase, save_playlist_to_supabase, update_playlist_in_supabase,
    get_show_list, get_playlist_for_show, style_playlist_draft_rows,
    force_columns_horizontal, load_all_recordings, _data_file_mtimes,
    format_playlist_track_label,
)

st.set_page_config(page_title="DankApp | Playlist Creator", page_icon="static/icon.png", layout="wide")
dank_theme()

df = load_all_recordings(_data_file_mtimes())

# -------------------------
# TOP ROW + HEADER
# -------------------------

username = st.user.email if st.user.is_logged_in else None
name = st.user.name if st.user.is_logged_in else None

force_columns_horizontal(gap="0.75rem", equal_width=True, key="top_row")
with st.container(key="top_row"):
    col1, col2 = st.columns(2, vertical_alignment="center")
    with col1:
        page_menu()
    with col2:
        if st.user.is_logged_in:
            if st.button("Logout", width="stretch"):
                st.logout()
        else:
            st.button("Log in with Google", on_click=st.login)

dank_header(subtitle="Build your own setlists")

# -------------------------
# SHOW LIST
# -------------------------

if "IA URL" not in df.columns:
    st.write("No streaming links found yet — run upload_to_archive.py to generate them.")
    st.stop()

performances, unique_shows = get_show_list(_data_file_mtimes(), "All")

if not unique_shows:
    st.write("No shows match this filter.")
    st.stop()

# -------------------------
# CALLBACK
# -------------------------

def on_load_playlist_change():
    """Loads a chosen saved playlist into the draft, re-fetching fresh
    from Supabase."""
    chosen = st.session_state.get("editor_load_select")
    if not chosen:
        return
    try:
        playlists = load_playlists_from_supabase(username)
    except Exception:
        return
    match = next((p for p in playlists if p["playlist_name"] == chosen), None)
    if match:
        st.session_state["playlist_draft"] = list(match["tracks"])
        st.session_state["editing_playlist_id"] = match["id"]
        st.session_state["editing_playlist_name"] = match["playlist_name"]
        st.session_state["new_playlist_name"] = match["playlist_name"]

def reset_draft(mode):
    st.session_state["playlist_edit_mode"] = mode
    st.session_state["playlist_draft"] = []
    st.session_state.pop("editing_playlist_id", None)
    st.session_state.pop("editing_playlist_name", None)
    st.session_state["editor_load_select"] = None
    st.session_state["new_playlist_name"] = ""

# -------------------------
# CREATE / EDIT
# -------------------------

dank_sign("Create/Edit a Playlist")

if not st.user.is_logged_in:
    st.info("Log in above to create or edit playlists.")
else:
    editing_id = st.session_state.get("editing_playlist_id")
    editing_name = st.session_state.get("editing_playlist_name")

    if "playlist_draft" not in st.session_state:
        st.session_state["playlist_draft"] = []

    if "playlist_edit_mode" not in st.session_state:
        st.session_state["playlist_edit_mode"] = "edit" if editing_id else "new"

    try:
        existing_playlists = load_playlists_from_supabase(username)
    except Exception:
        existing_playlists = None
        st.error("Couldn't load your playlists right now.")

    # ---- Mode toggle ----
    force_columns_horizontal(equal_width=True, key="hex_mode_toggle_row")
    with st.container(key="hex_mode_toggle_row"):
        mode_col1, mode_col2 = st.columns(2)
        with mode_col1:
            if st.button(
                "🆕 Start a List",
                width="stretch",
                type="primary" if st.session_state["playlist_edit_mode"] == "new" else "secondary",
            ):
                if st.session_state["playlist_edit_mode"] != "new":
                    reset_draft("new")
                    st.rerun()
        with mode_col2:
            if st.button(
                "📂 Load a List",
                width="stretch",
                type="primary" if st.session_state["playlist_edit_mode"] == "edit" else "secondary",
                disabled=not existing_playlists,
            ):
                if st.session_state["playlist_edit_mode"] != "edit":
                    reset_draft("edit")
                    st.rerun()

    st.markdown("---")

    # ---- Only the active mode's panel renders ----
    if st.session_state["playlist_edit_mode"] == "edit":
        if not existing_playlists:
            st.caption("No saved playlists yet — start a new one instead.")
        else:
            st.selectbox(
                "Choose a playlist to edit",
                [p["playlist_name"] for p in existing_playlists],
                index=None,
                placeholder="Choose a playlist...",
                key="editor_load_select",
                on_change=on_load_playlist_change,
            )
            editing_id = st.session_state.get("editing_playlist_id")
            editing_name = st.session_state.get("editing_playlist_name")
            if editing_name:
                st.caption(f"✏️ Currently editing: **{editing_name}**")
    else:
        editing_id = None

    builder_show = st.selectbox(
        "To add tracks, first select a show:",
        unique_shows,
        index=None,
        placeholder="Type to search...",
        key="playlist_builder_show",
    )

    if builder_show:
        builder_grouped = get_playlist_for_show(_data_file_mtimes(), builder_show)

        dank_hex("Track Selection")

        checked_tracks = []
        for i, track in enumerate(builder_grouped):
            label = f"{track['label']}  ·  {track['duration']}"
            if st.checkbox(label, key=f"track_check_{builder_show}_{i}"):
                checked_tracks.append(track)

        if st.button("➕ Add selected to new playlist"):
            for track in checked_tracks:
                track_with_show = {**track, "show": builder_show}
                if track_with_show not in st.session_state["playlist_draft"]:
                    st.session_state["playlist_draft"].append(track_with_show)
            for i in range(len(builder_grouped)):
                st.session_state.pop(f"track_check_{builder_show}_{i}", None)
            st.rerun()

    if st.session_state["playlist_draft"]:
        dank_hex("Current Playlist Draft")
        draft = st.session_state["playlist_draft"]
        style_playlist_draft_rows()

        force_columns_horizontal(min_col_width="28px", key="playlist_draft_rows")
        with st.container(key="playlist_draft_rows"):
            for i, track in enumerate(draft):
                full_label = format_playlist_track_label(track, index=i)
                col_label, col_up, col_down, col_remove = st.columns([6, 1, 1, 1])
                with col_label:
                    st.markdown(
                        f'<div class="dank-track-label">{full_label}</div>',
                        unsafe_allow_html=True,
                    )
                with col_up:
                    if st.button("↑", key=f"move_up_{i}", disabled=(i == 0)):
                        draft[i - 1], draft[i] = draft[i], draft[i - 1]
                        st.rerun()
                with col_down:
                    if st.button("↓", key=f"move_down_{i}", disabled=(i == len(draft) - 1)):
                        draft[i + 1], draft[i] = draft[i], draft[i + 1]
                        st.rerun()
                with col_remove:
                    if st.button("✕", key=f"remove_draft_{i}"):
                        draft.pop(i)
                        st.rerun()

        if "new_playlist_name" not in st.session_state:
            st.session_state["new_playlist_name"] = editing_name if editing_name else ""

        playlist_name = st.text_input("Playlist name", key="new_playlist_name")

        if st.button("💾 Save Playlist"):
            if not playlist_name.strip():
                st.warning("Give your playlist a name first.")
            else:
                try:
                    if editing_id:
                        success, message = update_playlist_in_supabase(
                            editing_id, playlist_name.strip(), st.session_state["playlist_draft"]
                        )
                    else:
                        success, message = save_playlist_to_supabase(
                            username, playlist_name.strip(), st.session_state["playlist_draft"]
                        )
                    if success:
                        st.session_state["playlist_draft"] = []
                        st.session_state.pop("editing_playlist_id", None)
                        st.session_state.pop("editing_playlist_name", None)
                        st.session_state["player_mode"] = None
                        st.switch_page("pages/listen.py")
                    else:
                        st.warning(message)
                except Exception:
                    st.error("Couldn't save right now — the account database is unreachable. Your draft is still here, try again shortly.")
    else:
        if not builder_show:
            dank_hex("No show selected.")

st.divider()
with st.container(key="hex_to_listen"):
    if st.button("🎧 Back to Listen", key="to_listen_btn", width="stretch"):
        st.switch_page("pages/listen.py")

# -------------------------
# FOOTER
# -------------------------
st.divider()

if st.button("⬆ Back to top"):
    components.html("""
        <script>
        var doc = window.parent.document;
        var selectors = ['section.main', '.main', '[data-testid="stAppViewContainer"]',
            '[data-testid="stMain"]', '.stApp', 'div[data-testid="stAppViewBlockContainer"]'];
        selectors.forEach(function(sel) {
            var el = doc.querySelector(sel);
            if (el) { el.scrollTo(0, 0); el.scrollTop = 0; }
        });
        doc.documentElement.scrollTop = 0;
        doc.body.scrollTop = 0;
        window.parent.scrollTo(0, 0);
        </script>
    """, height=0)

dank_footer()