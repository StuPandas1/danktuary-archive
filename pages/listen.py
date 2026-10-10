import streamlit as st  # type: ignore
import streamlit.components.v1 as components
import pandas as pd  # type: ignore
import urllib.parse
import html
import re
from shared import (
    page_menu, dank_header, dank_theme, dank_footer, dank_sign, dank_hex, dank_callout, card_html, linked_table,
    dank_playlist_player, get_supabase_client,
    load_playlists_from_supabase, delete_playlist_from_supabase,
    add_tracks_to_playlist, get_show_list, get_playlist_for_show,
    force_columns_horizontal, load_all_recordings, _data_file_mtimes,
    parse_duration, format_playlist_track_label,
)

st.set_page_config(page_title="DankApp | Listen to Dead Weight", page_icon="static/icon.png", layout="wide")
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

dank_header(subtitle="If you get confused...")

# -------------------------
# NOTES HELPERS
# -------------------------
# NOTE ON SCHEMA: replies rely on a nullable "parent_id" column on the
# show_notes table. Add it in Supabase before this goes live.

def load_notes(show_label):
    try:
        supabase = get_supabase_client()
        result = supabase.table("show_notes").select("*").eq("show_label", show_label).order("created_at").execute()
        return result.data or []
    except Exception:
        return []

def save_note(show_label, username, display_name, note, parent_id=None):
    try:
        supabase = get_supabase_client()
        payload = {
            "show_label": show_label,
            "username": username,
            "display_name": display_name,
            "note": note,
            "parent_id": parent_id,
        }
        supabase.table("show_notes").insert(payload).execute()
        return True
    except Exception:
        return False

def build_note_tree(notes):
    """Nests replies under their parent note. A reply whose parent is
    missing surfaces as a top-level note rather than vanishing."""
    by_id = {n["id"]: {**n, "replies": []} for n in notes if "id" in n}
    top_level = []
    for n in notes:
        node = by_id.get(n.get("id"))
        if node is None:
            continue
        parent_id = n.get("parent_id")
        if parent_id and parent_id in by_id and parent_id != n.get("id"):
            by_id[parent_id]["replies"].append(node)
        else:
            top_level.append(node)
    return top_level

def render_note(entry, show_label, depth=0):
    indent_px = depth * 24
    date_str = pd.Timestamp(entry["created_at"]).strftime("%m/%d/%Y")

    st.markdown(
        f"<div style='margin-left:{indent_px}px'>"
        f"<strong>{html.escape(entry['display_name'])}</strong> · "
        f"<span style='color:grey'>{date_str}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='margin-left:{indent_px}px; white-space:pre-wrap'>{html.escape(entry['note'])}</div>",
        unsafe_allow_html=True,
    )

    if st.user.is_logged_in:
        reply_open_key = f"note_reply_open_{entry['id']}"
        if st.button("↩️ Reply", key=f"note_reply_btn_{entry['id']}"):
            st.session_state[reply_open_key] = not st.session_state.get(reply_open_key, False)

        if st.session_state.get(reply_open_key):
            reply_text = st.text_area(
                "Reply:",
                key=f"note_reply_text_{entry['id']}",
                placeholder=f"Replying to {entry['display_name']}...",
            )
            if st.button("Post Reply", key=f"note_reply_submit_{entry['id']}"):
                if reply_text.strip():
                    success = save_note(show_label, username, name, reply_text.strip(), parent_id=entry["id"])
                    if success:
                        st.session_state[reply_open_key] = False
                        st.session_state.pop(f"note_reply_text_{entry['id']}", None)
                        st.rerun()
                    else:
                        st.error("Couldn't post reply right now.")
                else:
                    st.warning("Reply is empty.")

    for reply in entry.get("replies", []):
        render_note(reply, show_label, depth=depth + 1)

    if depth == 0:
        st.markdown("---")

def render_show_notes(show_label):
    st.markdown("---")
    dank_sign("Show Notes")

    show_notes = load_notes(show_label)

    if show_notes:
        for entry in build_note_tree(show_notes):
            render_note(entry, show_label)
    else:
        dank_hex("No notes yet for this show.")

    if st.user.is_logged_in:
        new_note = st.text_area(
            "Add a note:",
            placeholder="What stood out? What needs work?",
            key=f"note_{show_label}",
        )
        if st.button("Save Note", key=f"save_note_{show_label}"):
            if new_note.strip():
                success = save_note(show_label, username, name, new_note.strip())
                if success:
                    st.success("Note saved!")
                    st.rerun()
                else:
                    st.error("Couldn't save note right now.")
            else:
                st.warning("Note is empty.")
    else:
        st.info("Log in above to add notes or reply.")

# -------------------------
# SETLIST STATS HELPERS
# -------------------------

def _format_seconds(total_seconds):
    total_seconds = int(round(total_seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"

def compute_setlist_stats(playlist):
    parsed = []
    for track in playlist:
        try:
            seconds = parse_duration(track.get("duration", ""))
            if seconds:
                parsed.append((track, seconds))
        except Exception:
            continue

    total_seconds = sum(s for _, s in parsed)
    return {
        "track_count": len(playlist),
        "total_seconds": total_seconds,
        "avg_seconds": (total_seconds / len(parsed)) if parsed else 0,
        "longest": max(parsed, key=lambda x: x[1]) if parsed else None,
        "shortest": min(parsed, key=lambda x: x[1]) if parsed else None,
    }

def _normalize_song_title(title):
    if not isinstance(title, str):
        return ""
    return title.strip().lower()

def _extract_show_date(show_label):
    if not isinstance(show_label, str):
        return None
    candidate = re.split(r"\s[-–—]\s", show_label, maxsplit=1)[0].strip()
    parsed = pd.to_datetime(candidate, errors="coerce")
    return None if pd.isna(parsed) else parsed

def _extract_show_location(show_label):
    if not isinstance(show_label, str):
        return None
    parts = re.split(r"\s[-–—]\s", show_label, maxsplit=1)
    return parts[1].strip() if len(parts) == 2 else None

def _get_show_setlist_titles(show_label, archive_df):
    show_date = _extract_show_date(show_label)
    if show_date is None or "Title" not in archive_df.columns or "Date" not in archive_df.columns:
        return []

    archive_dates = pd.to_datetime(archive_df["Date"], errors="coerce")
    date_match = archive_dates.dt.date == show_date.date()
    take_one = pd.to_numeric(archive_df["Take"], errors="coerce") == 1

    show_location = _extract_show_location(show_label)
    rows = pd.DataFrame()
    if show_location and "Location" in archive_df.columns:
        location_match = archive_df["Location"].astype(str).str.strip().str.lower() == show_location.lower()
        rows = archive_df[date_match & take_one & location_match]

    if rows.empty:
        rows = archive_df[date_match & take_one]

    if "Track Number" in rows.columns:
        rows = rows.sort_values(by="Track Number")

    titles = []
    seen = set()
    for title in rows["Title"]:
        key = _normalize_song_title(title)
        if key and key not in seen:
            seen.add(key)
            titles.append(title)
    return titles

def get_song_history(title, archive_df, before_date=None):
    target = _normalize_song_title(title)
    if not target or "Title" not in archive_df.columns or "Take" not in archive_df.columns:
        return 0, None

    take_one = pd.to_numeric(archive_df["Take"], errors="coerce") == 1
    title_match = archive_df["Title"].apply(_normalize_song_title) == target
    matches = archive_df[take_one & title_match]
    if matches.empty:
        return 0, None

    dates = pd.to_datetime(matches["Date"], errors="coerce").dropna()
    times_played = len(dates)

    if before_date is not None:
        prior_dates = dates[dates < before_date]
    else:
        prior_dates = dates[dates < dates.max()] if not dates.empty else dates

    last_played = prior_dates.max() if not prior_dates.empty else None
    return times_played, last_played

def render_setlist_stats(playlist, archive_df, show_label):
    stats = compute_setlist_stats(playlist)

    current_show_date = _extract_show_date(show_label)
    setlist_titles = _get_show_setlist_titles(show_label, archive_df)

    # one pass over the songs: history rows + biggest bustout
    rows = []
    bustout = None  # (title, days)
    for title in setlist_titles:
        count, last_played = get_song_history(title, archive_df, before_date=current_show_date)
        rows.append({
            "Song": title,
            "Total Plays": count if count else "First time!",
            "Previous Play": last_played.strftime("%m/%d/%Y") if last_played is not None else "First time!",
        })
        if last_played is not None and current_show_date is not None:
            days = (current_show_date - last_played).days
            if bustout is None or days > bustout[1]:
                bustout = (title, days)

    if bustout:
        bustout_value = f"{html.escape(bustout[0])} ({bustout[1]:,} days)"
    else:
        bustout_value = "None"

    cards = [
        card_html(stats["track_count"], "Tracks", accent=True),
        card_html(_format_seconds(stats["total_seconds"]), "Total Runtime"),
        card_html(_format_seconds(stats["avg_seconds"]), "Avg Track"),
        card_html(bustout_value, "Biggest Bustout"),
    ]
    st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    if stats["longest"] and stats["shortest"]:
        longest_track, longest_secs = stats["longest"]
        shortest_track, shortest_secs = stats["shortest"]
        dank_callout(
            f"🏆 Longest: **{longest_track['label']}** ({_format_seconds(longest_secs)})",
            f"⚡ Shortest: **{shortest_track['label']}** ({_format_seconds(shortest_secs)})",
            img=None,
        )

    dank_hex("Song History")
    if not setlist_titles:
        dank_hex("Couldn't match this show to the archive")
    else:
        linked_table(pd.DataFrame(rows), song_col="Song")

# -------------------------
# SELECTION CALLBACKS
# -------------------------

def on_setlist_select_change():
    """Selecting a setlist deactivates any chosen saved playlist."""
    st.session_state["player_mode"] = "setlist"
    st.session_state["listen_playlist_select"] = None

def on_playlist_select_change():
    """Selecting a saved playlist deactivates any chosen setlist."""
    st.session_state["player_mode"] = "playlist"
    st.session_state["listen_show_select"] = None

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
# PICKERS
# -------------------------

force_columns_horizontal(equal_width=True, key="pick_row")
with st.container(key="pick_row"):
    col_setlist, col_playlist = st.columns(2)

    with col_setlist:
        dank_sign("Choose a Setlist", size="md")
        selected_show = st.selectbox(
            "Choose a setlist",
            unique_shows,
            index=None,
            placeholder="Type to search...",
            key="listen_show_select",
            on_change=on_setlist_select_change,
            label_visibility="collapsed",
        )

    my_playlists = None
    playlist_labels = {}

    with col_playlist:
        dank_sign("Or a Playlist", direction="left", size="md")

        if not st.user.is_logged_in:
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
                    "Or a saved playlist",
                    list(playlist_labels.keys()),
                    index=None,
                    placeholder="Type to search...",
                    key="listen_playlist_select",
                    on_change=on_playlist_select_change,
                    label_visibility="collapsed",
                )
            elif my_playlists is not None:
                dank_hex("No saved playlists yet")

player_mode = st.session_state.get("player_mode")

# ---- Setlist playback ----
if player_mode == "setlist" and selected_show:
    st.divider()
    playlist = get_playlist_for_show(_data_file_mtimes(), selected_show)

    if playlist:
        dank_playlist_player(selected_show, playlist)

        with st.expander("📊 Setlist Stats", True):
            render_setlist_stats(playlist, df, selected_show)
    else:
        dank_hex("No playable tracks found for this show")

    if st.user.is_logged_in and playlist:
        with st.expander("➕ Add tracks from this show to a playlist"):
            show_checked = []
            for i, track in enumerate(playlist):
                label = f"{track['label']}  ·  {track['duration']}"
                if st.checkbox(label, key=f"addshow_check_{selected_show}_{i}"):
                    show_checked.append(track)

            add_target_options = list(playlist_labels.keys()) if playlist_labels else []
            if not add_target_options:
                st.caption("No saved playlists yet — create one first with the Playlist Creator button above.")
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

    render_show_notes(selected_show)

# ---- Saved playlist playback ----
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

    force_columns_horizontal(equal_width=True, key="edit_delete_row")
    with st.container(key="edit_delete_row"):
        col_edit, col_delete = st.columns(2)
        with col_edit:
            if st.button("✏️ Edit this playlist", width="stretch"):
                # hand the playlist to the creator page, then go there
                st.session_state["playlist_draft"] = list(chosen_playlist["tracks"])
                st.session_state["editing_playlist_id"] = chosen_playlist["id"]
                st.session_state["editing_playlist_name"] = chosen_playlist_name
                st.session_state["playlist_edit_mode"] = "edit"
                st.session_state["new_playlist_name"] = chosen_playlist_name
                st.session_state["editor_load_select"] = chosen_playlist_name
                st.switch_page("pages/playlist_creator.py")
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

st.divider()

if st.user.is_logged_in:
    dank_callout("Skip the bathroom songs, man.")
    with st.container(key="hex_to_creator"):
        if st.button("🎶 Click to Create a Playlist", key="to_creator_btn",
                     width="stretch"):
            st.switch_page("pages/playlist_creator.py")
else:
    dank_callout("Gotta login if you want playlists, man.")
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