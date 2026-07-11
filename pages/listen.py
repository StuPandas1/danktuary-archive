import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import json
import os
import streamlit_authenticator as stauth
import time
from shared import (
    load_data, page_menu, dank_header, dank_playlist_player, suppress_selectbox_keyboard,
    load_users_from_supabase, create_user_in_supabase,
    group_tracks, save_playlist_to_supabase, load_playlists_from_supabase, delete_playlist_from_supabase,
    update_playlist_in_supabase, add_tracks_to_playlist,
    get_show_list, get_playlist_for_show,
    style_playlist_draft_rows,
    load_all_recordings, _data_file_mtimes
)
from auth_shared import sync_login_cookie, clear_login_cookie
import bcrypt

df = load_all_recordings(_data_file_mtimes())

page_menu()
dank_header(subtitle="If you get confused...")
suppress_selectbox_keyboard()

# -------------------------
# AUTH (degrades gracefully if Supabase is unreachable)
# -------------------------
supabase_up = st.session_state.get("supabase_up", False)
auth_status = st.session_state.get("authentication_status")
name = st.session_state.get("name")
username = st.session_state.get("username")
credentials = st.session_state.get("credentials", {"usernames": {}})
authenticator = st.session_state.get("authenticator")

if not supabase_up:
    st.warning("⚠️ Login is temporarily unavailable...")
else:
    if not auth_status:
        with st.expander("🔐 Band Login", expanded=False):
            login_tab, signup_tab = st.tabs(["Log In", "Create Account"])

            with login_tab:
                with st.form("login_form"):
                    login_username = st.text_input("Username")
                    login_password = st.text_input("Password", type="password")
                    submitted = st.form_submit_button("Log In")
                if submitted:
                    user = credentials["usernames"].get(login_username)
                    if user and bcrypt.checkpw(login_password.encode(), user["password"].encode()):
                        st.session_state["authentication_status"] = True
                        st.session_state["name"] = user["name"]
                        st.session_state["username"] = login_username
                        sync_login_cookie(st.secrets["cookie"]["expiry_days"])
                        st.rerun()
                    else:
                        st.error("Incorrect username or password.")

            with signup_tab:
                with st.form("signup_form"):
                    new_username = st.text_input("Choose a username")
                    new_name = st.text_input("Your name")
                    new_password = st.text_input("Choose a password", type="password")
                    new_password_confirm = st.text_input("Confirm password", type="password")
                    signup_submitted = st.form_submit_button("Create Account")

                if signup_submitted:
                    if not new_username or not new_name or not new_password:
                        st.error("Please fill in all fields.")
                    elif new_password != new_password_confirm:
                        st.error("Passwords don't match.")
                    else:
                        success, message = create_user_in_supabase(new_username, new_name, new_password)
                        if success:
                            st.success(message)
                        else:
                            st.error(message)
    else:
        col1, col2 = st.columns([5, 1])
        with col1:
            st.success(f"Logged in as {name}")
        with col2:
            if st.button("Log out"):
                st.session_state["authentication_status"] = None
                st.session_state["name"] = None
                st.session_state["username"] = None
                clear_login_cookie()
                st.rerun()
            
# -------------------------
# NOTES HELPERS
# -------------------------

NOTES_FILE = "show_notes.json"

def load_notes():
    if os.path.exists(NOTES_FILE):
        with open(NOTES_FILE, "r") as f:
            return json.load(f)
    return {}

def save_notes(notes):
    with open(NOTES_FILE, "w") as f:
        json.dump(notes, f, indent=2)

# -------------------------
# TOP-LEVEL NAVIGATION
# -------------------------
# Session-state-driven, not st.tabs() — st.tabs() has caused content-bleed
# issues in this app before (especially with the iframe-based audio player),
# so only the active section's Python runs at all.

if "active_section" not in st.session_state:
    st.session_state["active_section"] = "Listen to Music"

nav_col1, nav_col2 = st.columns(2)
with nav_col1:
    if st.button(
        "🎧 Listen to Music",
        width="stretch",
        type="primary" if st.session_state["active_section"] == "Listen to Music" else "secondary",
    ):
        st.session_state["active_section"] = "Listen to Music"
        st.rerun()
with nav_col2:
    if st.button(
        "🎶 Playlist Creator",
        width="stretch",
        type="primary" if st.session_state["active_section"] == "Create a Playlist" else "secondary",
    ):
        st.session_state["active_section"] = "Create a Playlist"
        st.session_state.pop("editing_playlist_id", None)
        st.session_state.pop("editing_playlist_name", None)
        st.session_state["playlist_draft"] = []
        st.session_state["new_playlist_name"] = ""
        st.session_state["editor_load_select"] = None
        st.rerun()

st.markdown("---")

# -------------------------
# SHARED SHOW LIST (used across sections, cached)
# -------------------------

if "IA URL" not in df.columns:
    st.write("No streaming links found yet — run upload_to_archive.py to generate them.")
    st.stop()

performances, unique_shows = get_show_list(_data_file_mtimes(), "All")

if not unique_shows:
    st.write("No shows match this filter.")
    st.stop()


def format_playlist_track_label(track, index=None):
    """Formats a track for display inside a playlist context, including
    the (date — location) of the show it came from, since a playlist can
    span multiple shows."""
    show = track.get("show", "")
    prefix = f"{index + 1}. " if index is not None else ""
    if show:
        return f"{prefix}{track['label']} ({show})"
    return f"{prefix}{track['label']}"


def on_setlist_select_change():
    """Selecting a setlist deactivates any chosen saved playlist, so only
    one player is ever active at a time."""
    st.session_state["player_mode"] = "setlist"
    st.session_state["listen_playlist_select"] = None


def on_playlist_select_change():
    """Selecting a saved playlist deactivates any chosen setlist."""
    st.session_state["player_mode"] = "playlist"
    st.session_state["listen_show_select"] = None


def on_load_playlist_change():
    """Loads a chosen saved playlist into the Create/Edit draft — re-fetches
    fresh from Supabase rather than relying on closures over an earlier
    render's data."""
    chosen = st.session_state.get("editor_load_select")
    if not chosen:
        return
    try:
        playlists = load_playlists_from_supabase(st.session_state.get("username"))
    except Exception:
        return
    match = next((p for p in playlists if p["playlist_name"] == chosen), None)
    if match:
        st.session_state["playlist_draft"] = list(match["tracks"])
        st.session_state["editing_playlist_id"] = match["id"]
        st.session_state["editing_playlist_name"] = match["playlist_name"]
        st.session_state["new_playlist_name"] = match["playlist_name"]


# =========================================================
# LISTEN TO MUSIC SECTION
# =========================================================

if st.session_state["active_section"] == "Listen to Music":

    col_setlist, col_playlist = st.columns(2)

    with col_setlist:
        st.markdown("#### 🎧 Pick a Setlist")
        selected_show = st.selectbox(
            "Choose a show",
            unique_shows,
            index=None,
            placeholder="Type to search...",
            key="listen_show_select",
            on_change=on_setlist_select_change,
        )

    my_playlists = None
    playlist_labels = {}

    with col_playlist:
        st.markdown("#### 🎶 Pick a Saved Playlist")

        if not supabase_up:
            st.info("Playlists are unavailable right now.")
        elif not auth_status:
            st.info("Log in above to view saved playlists.")
        else:
            try:
                my_playlists = load_playlists_from_supabase(username)
            except Exception:
                st.error("Couldn't load your playlists right now.")

            if my_playlists is not None:
                playlist_labels = {p["playlist_name"]: p for p in my_playlists}

            if playlist_labels:
                st.selectbox(
                    "Choose a playlist",
                    list(playlist_labels.keys()),
                    index=None,
                    placeholder="Type to search...",
                    key="listen_playlist_select",
                    on_change=on_playlist_select_change,
                )
            elif my_playlists is not None:
                st.write("No saved playlists yet — use the 🎶 Create a Playlist button above.")

    st.markdown("---")

    player_mode = st.session_state.get("player_mode")

    # ---- Setlist playback (with setlist-only extras) ----
    if player_mode == "setlist" and selected_show:
        playlist = get_playlist_for_show(_data_file_mtimes(), selected_show)

        if playlist:
            dank_playlist_player(selected_show, playlist)
        else:
            st.write("No playable tracks found for this show.")

        if auth_status and supabase_up and playlist:
            with st.expander("➕ Add tracks from this show to a playlist"):
                show_checked = []
                for i, track in enumerate(playlist):
                    label = f"{track['label']}  ·  {track['duration']}"
                    if st.checkbox(label, key=f"addshow_check_{selected_show}_{i}"):
                        show_checked.append(track)

                add_target_options = list(playlist_labels.keys()) if playlist_labels else []
                if not add_target_options:
                    st.caption("No saved playlists yet — create one first with the button above.")
                else:
                    target_choice = st.selectbox(
                        "Add checked tracks to:",
                        add_target_options,
                        index=None,
                        placeholder="Choose a playlist...",
                        key=f"add_target_{selected_show}",
                    )
                    if st.button("➕ Add checked tracks", key=f"add_confirm_{selected_show}"):
                        if not show_checked:
                            st.warning("Check at least one track first.")
                        elif not target_choice:
                            st.warning("Pick a playlist to add to.")
                        else:
                            target_playlist = playlist_labels[target_choice]
                            tracks_to_add = [{**t, "show": selected_show} for t in show_checked]
                            try:
                                add_tracks_to_playlist(target_playlist["id"], tracks_to_add)
                                st.success(f"Added to '{target_choice}'.")
                                for i in range(len(playlist)):
                                    st.session_state.pop(f"addshow_check_{selected_show}_{i}", None)
                                st.rerun()
                            except Exception:
                                st.error("Couldn't add right now — the account database is unreachable.")

        if auth_status:
            st.markdown("---")
            st.markdown("#### 📝 Show Notes")

            notes = load_notes()
            show_notes = notes.get(selected_show, [])

            if show_notes:
                for entry in show_notes:
                    st.markdown(f"**{entry['user']}** · *{entry['date']}*")
                    st.write(entry["note"])
                    st.markdown("---")
            else:
                st.write("No notes yet for this show.")

            new_note = st.text_area("Add a note:", placeholder="What stood out? What needs work?", key=f"note_{selected_show}")

            if st.button("Save Note"):
                if new_note.strip():
                    if selected_show not in notes:
                        notes[selected_show] = []
                    notes[selected_show].append({
                        "user": name,
                        "date": pd.Timestamp.today().strftime("%m/%d/%Y"),
                        "note": new_note.strip()
                    })
                    save_notes(notes)
                    st.success("Note saved!")
                    st.rerun()
                else:
                    st.warning("Note is empty.")
        elif supabase_up:
            st.markdown("---")
            st.info("Log in above to add and view show notes.")

    # ---- Saved playlist playback (no extras) ----
    elif player_mode == "playlist" and playlist_labels and st.session_state.get("listen_playlist_select"):
        chosen_playlist_name = st.session_state["listen_playlist_select"]
        chosen_playlist = playlist_labels[chosen_playlist_name]

        display_tracks = [
            {
                "label": format_playlist_track_label(t),
                "duration": t.get("duration", ""),
                "url": t.get("url", ""),
            }
            for t in chosen_playlist["tracks"]
        ]
        dank_playlist_player(chosen_playlist_name, display_tracks)

        col_edit, col_delete = st.columns(2)
        with col_edit:
            if st.button("✏️ Edit this playlist", width="stretch"):
                st.session_state["playlist_draft"] = list(chosen_playlist["tracks"])
                st.session_state["editing_playlist_id"] = chosen_playlist["id"]
                st.session_state["editing_playlist_name"] = chosen_playlist_name
                st.session_state["active_section"] = "Create a Playlist"
                st.rerun()
        with col_delete:
            if st.button("🗑️ Delete this playlist", width="stretch"):
                try:
                    delete_playlist_from_supabase(chosen_playlist["id"])
                    st.success(f"Deleted '{chosen_playlist_name}'.")
                    st.session_state["listen_playlist_select"] = None
                    st.session_state["player_mode"] = None
                    st.rerun()
                except Exception:
                    st.error("Couldn't delete right now — the account database is unreachable.")

# =========================================================
# CREATE / EDIT PLAYLIST SECTION
# =========================================================

if st.session_state["active_section"] == "Create a Playlist":

    st.markdown("#### 🎶 Create/Edit a Playlist")

    editing_id = st.session_state.get("editing_playlist_id")
    editing_name = st.session_state.get("editing_playlist_name")

    if not supabase_up:
        st.info("Playlists are unavailable right now — the account database is unreachable.")
    elif not auth_status:
        st.info("Log in above to create or edit playlists.")
    else:
        if "playlist_draft" not in st.session_state:
            st.session_state["playlist_draft"] = []

        if "playlist_edit_mode" not in st.session_state:
            st.session_state["playlist_edit_mode"] = "edit" if editing_id else "new"

        try:
            existing_playlists = load_playlists_from_supabase(username)
        except Exception:
            existing_playlists = None
            st.error("Couldn't load your playlists right now.")

        # ---- Mode toggle: only one panel shows at a time ----
        mode_col1, mode_col2 = st.columns(2)
        with mode_col1:
            if st.button(
                "🆕 Start a New Playlist",
                width="stretch",
                type="primary" if st.session_state["playlist_edit_mode"] == "new" else "secondary",
            ):
                if st.session_state["playlist_edit_mode"] != "new":
                    st.session_state["playlist_edit_mode"] = "new"
                    st.session_state["playlist_draft"] = []
                    st.session_state.pop("editing_playlist_id", None)
                    st.session_state.pop("editing_playlist_name", None)
                    st.session_state["editor_load_select"] = None
                    st.session_state["new_playlist_name"] = ""
                    st.rerun()
        with mode_col2:
            if st.button(
                "📂 Load Existing Playlist",
                width="stretch",
                type="primary" if st.session_state["playlist_edit_mode"] == "edit" else "secondary",
                disabled=not existing_playlists,
            ):
                if st.session_state["playlist_edit_mode"] != "edit":
                    st.session_state["playlist_edit_mode"] = "edit"
                    st.session_state["playlist_draft"] = []
                    st.session_state.pop("editing_playlist_id", None)
                    st.session_state.pop("editing_playlist_name", None)
                    st.session_state["editor_load_select"] = None
                    st.session_state["new_playlist_name"] = ""
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
            "Pick a show to grab tracks from",
            unique_shows,
            index=None,
            placeholder="Type to search...",
            key="playlist_builder_show",
        )

        if builder_show:
            builder_grouped = get_playlist_for_show(_data_file_mtimes(), builder_show)

            st.write("Select tracks to add:")
            checked_tracks = []
            for i, track in enumerate(builder_grouped):
                label = f"{track['label']}  ·  {track['duration']}"
                is_checked = st.checkbox(label, key=f"track_check_{builder_show}_{i}")
                if is_checked:
                    checked_tracks.append(track)

            if st.button("➕ Add selected to playlist"):
                for track in checked_tracks:
                    track_with_show = {**track, "show": builder_show}
                    if track_with_show not in st.session_state["playlist_draft"]:
                        st.session_state["playlist_draft"].append(track_with_show)
                for i in range(len(builder_grouped)):
                    st.session_state.pop(f"track_check_{builder_show}_{i}", None)
                st.rerun()

        if st.session_state["playlist_draft"]:
            st.write("**Current draft:**")
            draft = st.session_state["playlist_draft"]
            style_playlist_draft_rows()

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
                            st.success(message)
                            st.session_state["playlist_draft"] = []
                            st.session_state.pop("editing_playlist_id", None)
                            st.session_state.pop("editing_playlist_name", None)
                            st.session_state["active_section"] = "Listen to Music"
                            st.session_state["player_mode"] = None
                            st.rerun()
                        else:
                            st.warning(message)
                    except Exception:
                        st.error("Couldn't save right now — the account database is unreachable. Your draft is still here, try again shortly.")
        else:
            st.caption("Pick a show above and add some tracks to get started.")

st.divider()

st.markdown(
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 2.0 | Believe it if you need it</div>",
    unsafe_allow_html=True
)
st.markdown("")