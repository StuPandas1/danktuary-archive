import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import json
import os
import streamlit_authenticator as stauth
from shared import (
    load_data, page_menu, dank_header, dank_playlist_player, suppress_selectbox_keyboard,
    load_users_from_supabase, create_user_in_supabase,
    group_tracks, save_playlist_to_supabase, load_playlists_from_supabase, delete_playlist_from_supabase,
    get_show_list, get_playlist_for_show,
    force_columns_horizontal, style_playlist_draft_rows,
    load_all_recordings, _data_file_mtimes
)

df = load_all_recordings(_data_file_mtimes())

page_menu()
dank_header(subtitle="If you get confused...")
suppress_selectbox_keyboard()

# -------------------------
# AUTH (degrades gracefully if Supabase is unreachable)
# -------------------------

auth_status = st.session_state.get("authentication_status")
name = st.session_state.get("name")
supabase_up = True

try:
    credentials = load_users_from_supabase()
except Exception:
    supabase_up = False
    credentials = {"usernames": {}}
    auth_status = None
    name = None

if not supabase_up:
    st.warning(
        "⚠️ Login is temporarily unavailable (can't reach the account database right now). "
        "You can still browse and listen to shows below — notes and playlists will "
        "come back once the connection is restored."
    )
else:
    authenticator = stauth.Authenticate(
        credentials,
        st.secrets["cookie"]["name"],
        st.secrets["cookie"]["key"],
        st.secrets["cookie"]["expiry_days"]
    )

    if not auth_status:
        with st.expander("🔐 Band Login", expanded=False):
            login_tab, signup_tab = st.tabs(["Log In", "Create Account"])

            with login_tab:
                authenticator.login(location="main")
                auth_status = st.session_state.get("authentication_status")
                name = st.session_state.get("name")
                if auth_status is False:
                    st.error("Incorrect username or password.")

            with signup_tab:
                with st.form("signup_form", clear_on_submit=True):
                    new_username = st.text_input("Choose a username")
                    new_name = st.text_input("Your name (shown on notes)")
                    new_password = st.text_input("Choose a password", type="password")
                    new_password_confirm = st.text_input("Confirm password", type="password")
                    submitted = st.form_submit_button("Create Account")

                if submitted:
                    if not new_username or not new_name or not new_password:
                        st.warning("Please fill out all fields.")
                    elif new_password != new_password_confirm:
                        st.warning("Passwords don't match.")
                    elif len(new_password) < 6:
                        st.warning("Password should be at least 6 characters.")
                    else:
                        success, message = create_user_in_supabase(new_username, new_name, new_password)
                        if success:
                            st.success(message)
                        else:
                            st.warning(message)
    else:
        col1, col2 = st.columns([5, 1])
        with col1:
            st.success(f"Logged in as {name}")
        with col2:
            authenticator.logout("Log out", location="main")

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
# SHARED SHOW LIST (used by both tabs, cached)
# -------------------------

if "IA URL" not in df.columns:
    st.write("No streaming links found yet — run upload_to_archive.py to generate them.")
    st.stop()

type_filter = st.radio(
    "Show type:",
    ["All", "Gigs", "Practices"],
    horizontal=True
)

performances, unique_shows = get_show_list(_data_file_mtimes(), type_filter)

if not unique_shows:
    st.write("No shows match this filter.")
    st.stop()

# -------------------------
# TABS
# -------------------------

if "active_section" not in st.session_state:
    st.session_state["active_section"] = "Listen"

col1, col2 = st.columns(2)
with col1:
    if st.button("🎧 Listen", width="stretch", type="primary" if st.session_state["active_section"] == "Listen" else "secondary"):
        st.session_state["active_section"] = "Listen"
        st.rerun()
with col2:
    if st.button("🎶 Playlists", width="stretch", type="primary" if st.session_state["active_section"] == "Playlists" else "secondary"):
        st.session_state["active_section"] = "Playlists"
        st.rerun()

st.markdown("---")

# -------------------------
# LISTEN TAB (fully functional even if Supabase is down)
# -------------------------

if st.session_state["active_section"] == "Listen":
    selected_show = st.selectbox(
        "Pick a show to listen to",
        unique_shows,
        index=None,
        placeholder="Type to search...",
        key="listen_show_select",
    )

    if selected_show:
        playlist = get_playlist_for_show(_data_file_mtimes(), selected_show)

        if playlist:
            dank_playlist_player(selected_show, playlist)
        else:
            st.write("No playable tracks found for this show.")

        # -------------------------
        # SHOW NOTES (logged in only)
        # -------------------------

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

# -------------------------
# PLAYLISTS TAB (requires Supabase — shows a clear message if it's down)
# -------------------------

if st.session_state["active_section"] == "Playlists":
    if not supabase_up:
        st.info("🎶 Playlists need the account database, which is temporarily unreachable. Try again shortly.")
    elif not auth_status:
        st.info("Log in above to create and save playlists.")
    else:
        username = st.session_state.get("username")

        st.markdown("#### 🎶 Create a Playlist")

        if "playlist_draft" not in st.session_state:
            st.session_state["playlist_draft"] = []

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
                    full_label = f"{i + 1}. {track['label']} — {track['show']}"
                    col_label, col_up, col_down, col_remove = st.columns([6, 1, 1, 1])
                    with col_label:
                        st.markdown(
                            f'<div class="dank-track-label" title="{full_label}">{full_label}</div>',
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

            playlist_name = st.text_input("Playlist name", key="new_playlist_name")
            if st.button("💾 Save Playlist"):
                if not playlist_name.strip():
                    st.warning("Give your playlist a name first.")
                else:
                    try:
                        success, message = save_playlist_to_supabase(
                            username, playlist_name.strip(), st.session_state["playlist_draft"]
                        )
                        if success:
                            st.success(message)
                            st.session_state["playlist_draft"] = []
                            st.rerun()
                        else:
                            st.warning(message)
                    except Exception:
                        st.error("Couldn't save right now — the account database is unreachable. Your draft is still here, try again shortly.")

        # -------------------------
        # MY PLAYLISTS
        # -------------------------

        st.markdown("---")
        st.markdown("#### 📂 My Playlists")

        try:
            my_playlists = load_playlists_from_supabase(username)
        except Exception:
            my_playlists = None
            st.error("Couldn't load your saved playlists right now — the account database is unreachable.")

        if my_playlists is not None:
            if not my_playlists:
                st.write("No saved playlists yet — build one above.")
            else:
                playlist_labels = {p["playlist_name"]: p for p in my_playlists}
                chosen_name = st.selectbox(
                    "Load a saved playlist",
                    list(playlist_labels.keys()),
                    index=None,
                    placeholder="Choose a playlist...",
                    key="load_playlist_select",
                )

                if chosen_name:
                    chosen_playlist = playlist_labels[chosen_name]
                    dank_playlist_player(chosen_name, chosen_playlist["tracks"])

                    if st.button(f"🗑️ Delete '{chosen_name}'"):
                        try:
                            delete_playlist_from_supabase(chosen_playlist["id"])
                            st.success(f"Deleted '{chosen_name}'.")
                            st.rerun()
                        except Exception:
                            st.error("Couldn't delete right now — the account database is unreachable.")

st.divider()

st.markdown(
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 2.0 | Believe it if you need it</div>",
    unsafe_allow_html=True
)
st.markdown("")