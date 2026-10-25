import streamlit as st  # type: ignore
import streamlit.components.v1 as components
import pandas as pd  # type: ignore
import html
import re
import random
from shared import (
    page_menu, dank_header, dank_theme, dank_footer, dank_sign, dank_hex, dank_callout, card_html, click_table, url_from_browser,
    dank_playlist_player, get_supabase_client,
    load_playlists_from_supabase, delete_playlist_from_supabase,
    add_tracks_to_playlist, song_show_map,
    force_columns_horizontal, load_all_recordings, _data_file_mtimes,
    parse_duration, format_playlist_track_label, sync_url, slug_to_show,
    with_onedrive_urls, show_index, tracks_for_show,
)

st.set_page_config(page_title="DankApp | Listen to Dead Weight", page_icon="static/icon.png", layout="wide")
dank_theme()

# one place for the mode names, so a typo can't silently break the toggle
MODE_SET, MODE_SONG, MODE_PL = "By Setlist", "By Song", "Playlists"

df = load_all_recordings(_data_file_mtimes())
MT = _data_file_mtimes()

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

dank_header(subtitle="Listen to the music play")

# -------------------------
# NOTES HELPERS
# -------------------------
# NOTE ON SCHEMA: replies rely on a nullable "parent_id" column on the
# show_notes table. Add it in Supabase before this goes live.

@st.cache_data(ttl=60, show_spinner=False)
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
        load_notes.clear()          # so the new note shows up immediately
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

@st.cache_data(show_spinner=False)
def song_date_index(_archive_df, mtimes):
    """{normalized title: [(date, location), ...]} for Take-1 plays."""
    a = _archive_df[pd.to_numeric(_archive_df["Take"], errors="coerce") == 1]
    t = pd.DataFrame({
        "k": a["Title"].map(_normalize_song_title),
        "d": pd.to_datetime(a["Date"], errors="coerce"),
        "l": a["Location"],
    }).dropna(subset=["k", "d"])
    return t.groupby("k").apply(lambda g: list(zip(g["d"], g["l"])), include_groups=False).to_dict()

@st.cache_data(show_spinner=False)
def history_for_show(_archive_df, show_label, mtimes):
    """History table rows + biggest bustout for one show."""
    idx = song_date_index(_archive_df, mtimes)
    show_date = _extract_show_date(show_label)
    titles = _get_show_setlist_titles(show_label, _archive_df)
    rows, bustout = [], None
    for title in titles:
        plays = idx.get(_normalize_song_title(title), [])
        prior = [p for p in plays if show_date is None or p[0] < show_date]
        last = max(prior, key=lambda p: p[0]) if prior else None
        rows.append({
            "Song": title,
            "Total Plays": len(plays) if plays else "First time!",
            "Previous Play": last[0].strftime("%m/%d/%Y") if last else "First time!",
            "Previous Location": last[1] if last else "",
        })
        if last is not None and show_date is not None:
            days = (show_date - last[0]).days
            if bustout is None or days > bustout[1]:
                bustout = (title, days)
    return rows, bustout, bool(titles)


def render_setlist_stats(playlist, archive_df, show_label):
    stats = compute_setlist_stats(playlist)
    rows, bustout, matched = history_for_show(archive_df, show_label, MT)
    bustout_value = f"{html.escape(bustout[0])} ({bustout[1]:,} days)" if bustout else "None"

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
    if not matched:
        dank_hex("Couldn't match this show to the archive")
    else:
        history = pd.DataFrame(rows).astype(str)     # mixed numbers and "First time!" text
        click_table(history, key="tbl_song_history",
            song_cols=("Song",),
            show_cols={"Previous Play": "Previous Location"},
            goto="pages/stats.py")

# -------------------------
# BROWSE DATA
# -------------------------

shows = show_index(df, MT)
if shows.empty:
    dank_hex("No playable recordings found")
    st.stop()

# playlists load in every mode (the "add tracks" expander needs them)
my_playlists, playlist_labels = None, {}
if st.user.is_logged_in:
    try:
        my_playlists = load_playlists_from_supabase(username)
        playlist_labels = {p["playlist_name"]: p for p in my_playlists}
    except Exception:
        st.error("Couldn't load your playlists right now.")

# ---------- arriving from a shared link (?show=...), once per session ----------
if not st.session_state.get("listen_deeplink_done"):
    st.session_state["listen_deeplink_done"] = True
    q = slug_to_show(url_from_browser("show"))
    if q in set(shows["Show_Label"]):
        st.session_state["now_playing"] = ("show", q)
        st.session_state["listen_sel"] = q
        st.session_state["listen_mode"] = MODE_SET
        st.session_state["listen_list_open"] = False
        
# ---------- arriving from another page (landing / stats) ----------
if "pending_listen_show" in st.session_state:
    label = st.session_state.pop("pending_listen_show")
    st.session_state["listen_sel"] = label
    st.session_state["now_playing"] = ("show", label)
    st.session_state["listen_mode"] = MODE_SET
    st.session_state["listen_list_open"] = False

st.session_state.setdefault("now_playing", ("show", shows.iloc[0]["Show_Label"]))

# defaults: open on the latest show, lists visible
if st.session_state.get("listen_mode") not in (MODE_SET, MODE_SONG, MODE_PL):
    st.session_state["listen_mode"] = MODE_SET       # also fixes stale values from old sessions
st.session_state.setdefault("listen_sel", shows.iloc[0]["Show_Label"])
st.session_state.setdefault("listen_sel_song", None)
for k in ("listen_list_open", "listen_songs_open", "listen_hits_open"):
    st.session_state.setdefault(k, True)

# ---------- callbacks (run before the rerun, so setting widget keys is legal) ----------
def toggle(key):
    st.session_state[key] = not st.session_state.get(key, True)

def play_show(label):
    st.session_state["now_playing"] = ("show", label)

def play_playlist():
    name = st.session_state.get("listen_playlist_select")
    if name:
        st.session_state["now_playing"] = ("playlist", name)

def pick_show(label):
    st.session_state["listen_sel"] = label
    st.session_state["listen_list_open"] = False        # picking a show hides the list
    play_show(label)

def pick_random_show(labels):
    if labels:
        pick_show(random.choice(labels))

def on_song_change():
    st.session_state["listen_sel_song"] = None          # new song: nothing loaded yet
    st.session_state["listen_songs_open"] = False
    st.session_state["listen_hits_open"] = True

def pick_song(title):
    st.session_state["listen_song"] = title
    on_song_change()

def pick_random_song(titles):
    if titles:
        pick_song(random.choice(titles))

def pick_hit(label):
    st.session_state["listen_sel_song"] = label
    st.session_state["listen_hits_open"] = False        # picking a recording hides its list
    play_show(label)

def delete_playlist_cb(playlist_id, playlist_name):
    try:
        delete_playlist_from_supabase(playlist_id)
        st.session_state["listen_playlist_select"] = None
        st.session_state["pl_flash"] = f"Deleted '{playlist_name}'."
    except Exception:
        st.session_state["pl_flash"] = "Couldn't delete right now — the account database is unreachable."
    if st.session_state.get("now_playing") == ("playlist", playlist_name):
        st.session_state["now_playing"] = None

def render_show_buttons(frame, sel, prefix, hint=True):
    """Scrollable button rows: date · venue · total duration. The playing show is highlighted."""
    if hint:
        st.markdown(f'<div class="song-browse-hint"> Select from {len(frame)} recordings</div>',
                    unsafe_allow_html=True)
    with st.container(height=320, key=f"listen_scroll_{prefix}"):
        for i, r in enumerate(frame.itertuples()):
            dur = _format_seconds(r.Secs) if r.Secs else "—"
            kind_cls = "trackon" if r.Show_Label == sel else "trackrow"
            with st.container(key=f"{kind_cls}_{prefix}_{i}"):
                st.button(
                    f"{r.Date:%m/%d/%Y}  ·  {r.Location}  ·  {dur}",
                    key=f"{prefix}_row_{i}", width="stretch",
                    on_click=(pick_show if prefix == "set" else pick_hit), args=(r.Show_Label,),
                )

def playing_show_label():
    state = st.session_state.get("now_playing")
    return state[1] if state and state[0] == "show" else None

# -------------------------
# BROWSE AREA
# -------------------------

dank_hex("Search for Recordings")
with st.container(key="browse_area"):
    mode = st.segmented_control(
        "Browse", [MODE_SET, MODE_SONG, MODE_PL],
        key="listen_mode", label_visibility="collapsed",
    ) or MODE_SET

    # ===================== BY SETLIST =====================
    if mode == MODE_SET:
        recent = sorted(shows["Date"].dt.year.unique(), reverse=True)
        year_opts = ["All"] + [str(y) for y in recent[:5]] + (["Older"] if len(recent) > 5 else [])

        with st.expander("Filters"):
            type_pick = st.pills("Type", ["All", "Gigs", "Practice"], default="All",
                                 key="listen_type", label_visibility="collapsed") or "All"
            year_pick = st.pills("Year", year_opts, default="All",
                                 key="listen_year", label_visibility="collapsed") or "All"

        f = shows
        if type_pick == "Gigs":
            f = f[f["Type"] == "live"]
        elif type_pick == "Practice":
            f = f[f["Type"] != "live"]
        if year_pick == "Older":
            f = f[f["Date"].dt.year < recent[4]]
        elif year_pick != "All":
            f = f[f["Date"].dt.year == int(year_pick)]
        labels = f["Show_Label"].tolist()

        today_md = pd.Timestamp.now(tz="America/New_York").strftime("%m/%d")
        on_this_day = shows.loc[shows["Date"].dt.strftime("%m/%d") == today_md, "Show_Label"].tolist()
        list_open = st.session_state["listen_list_open"]

        force_columns_horizontal(equal_width=True, gap="0.5rem", key="btnrow_listen")
        with st.container(key="btnrow_listen"):
            b1, b2, b3 = st.columns(3)
            with b1:
                st.button("Close List" if list_open else "Open List", key="listen_list_toggle",
                          width="stretch", type="primary" if list_open else "secondary",
                          on_click=toggle, args=("listen_list_open",))
            with b2:
                st.button("Random", key="listen_rand_show", width="stretch",
                          disabled=not labels, on_click=pick_random_show, args=(labels,))
            with b3:
                st.button("On This Day", key="listen_rand_otd", width="stretch",
                          disabled=not on_this_day, on_click=pick_random_show, args=(on_this_day,))

        if f.empty:
            dank_hex("No recordings match those filters")
        elif list_open:
            render_show_buttons(f, playing_show_label(), "set")

    # ===================== BY SONG =====================
    elif mode == MODE_SONG:
        sm = song_show_map(df, MT)
        titles = sorted(sm["Title"].unique(), key=str.lower)
        if st.session_state.get("listen_song") not in titles:
            st.session_state["listen_song"] = None

        # search bar first
        st.selectbox(
            "Search songs", titles, index=None,
            placeholder=f"Search from {len(titles)} songs...",
            key="listen_song", on_change=on_song_change, label_visibility="collapsed",
        )
        song = st.session_state["listen_song"]

        songs_open = st.session_state["listen_songs_open"]
        force_columns_horizontal(equal_width=True, gap="0.5rem", key="btnrow_listen_song")
        with st.container(key="btnrow_listen_song"):
            b1, b2 = st.columns(2)
            with b1:
                st.button("Hide songs" if songs_open else "Show songs", key="listen_songs_toggle",
                          width="stretch", type="primary" if songs_open else "secondary",
                          on_click=toggle, args=("listen_songs_open",))
            with b2:
                st.button("🎲 Random Song", key="listen_rand_song", width="stretch",
                          on_click=pick_random_song, args=(titles,))

        if songs_open:
            st.markdown(f'<div class="song-browse-hint"> Select from {len(titles)} songs</div>',
                        unsafe_allow_html=True)
            with st.container(height=320, key="listen_scroll_songs"):
                for i, t in enumerate(titles):
                    kind_cls = "trackon" if t == song else "trackrow"
                    with st.container(key=f"{kind_cls}_song_{i}"):
                        st.button(t, key=f"song_row_{i}", width="stretch",
                                  on_click=pick_song, args=(t,))

        if song:
            hits = shows[shows["Show_Label"].isin(sm.loc[sm["Title"] == song, "Show_Label"])]
            n = len(hits)
            if st.session_state["listen_hits_open"]:
                dank_hex(f"**{song}**", f"Select from {n} recording{'' if n == 1 else 's'}")
                render_show_buttons(hits, playing_show_label(), "hit", hint=False)
                st.button("Hide this list", key="listen_hits_hide", width="stretch",
                          type="primary", on_click=toggle, args=("listen_hits_open",))
            else:
                st.button(f"Show recordings of {song}", key="listen_hits_show", width="stretch",
                          on_click=toggle, args=("listen_hits_open",))
        else:
            dank_hex("Pick a song to see every recording of it")
            
    # ===================== PLAYLISTS =====================
    else:
        flash = st.session_state.pop("pl_flash", None)
        if flash:
            st.success(flash)
        if not st.user.is_logged_in:
            dank_hex("Log in to use playlists")
        elif not playlist_labels:
            dank_hex("No saved playlists yet")
        else:
            if st.session_state.get("listen_playlist_select") not in playlist_labels:
                st.session_state["listen_playlist_select"] = None
            st.selectbox(
                "Choose a playlist", list(playlist_labels.keys()), index=None,
                placeholder="Pick a playlist...", key="listen_playlist_select",
                label_visibility="collapsed", on_change=play_playlist,
            )

st.divider()

# ---------- what's playing ----------
np_now = st.session_state.get("now_playing")
kind, ident = np_now if np_now else (None, None)
if kind == "playlist" and ident not in playlist_labels:
    kind = None                                   # deleted, or logged out
sync_url(show=ident if kind == "show" else None)

# ---------- player (own container, survives mode switches) ----------
player_slot = st.container(key="player_slot")
playlist = []
with player_slot:
    if kind == "show":
        playlist = tracks_for_show(df, ident, MT)
        if playlist:
            playable = with_onedrive_urls(playlist, df)
            dank_playlist_player(ident, playable)
            if len(playable) < len(playlist):
                st.caption(f"{len(playlist) - len(playable)} track(s) couldn't be loaded right now.")
        else:
            dank_hex("No playable tracks found for this show")
    elif kind == "playlist":
        chosen_playlist = playlist_labels[ident]
        display_tracks = [
            {"label": format_playlist_track_label(t), "duration": t.get("duration", ""),
             "url": t.get("url", ""), "path": t.get("path", "")}
            for t in chosen_playlist["tracks"]
        ]
        dank_playlist_player(ident, with_onedrive_urls(display_tracks, df))

# ---------- details for whatever is playing ----------
if kind == "show" and playlist:
    st.divider()
    with st.expander("📊 Setlist Stats", True):
        render_setlist_stats(playlist, df, ident)

    if st.user.is_logged_in:
        with st.expander("➕ Add tracks from this show to a playlist"):
            show_checked = []
            for i, track in enumerate(playlist):
                label = f"{track['label']}  ·  {track['duration']}"
                if st.checkbox(label, key=f"addshow_check_{ident}_{i}"):
                    show_checked.append(track)

            add_target_options = list(playlist_labels.keys()) if playlist_labels else []
            if not add_target_options:
                st.caption("No saved playlists yet — create one first with the Playlist Creator button below.")
            else:
                target_choice = st.selectbox(
                    "Add checked tracks to:", add_target_options, index=None,
                    placeholder="Choose a playlist...", key=f"add_target_{ident}",
                )
                if st.button("➕ Add checked tracks", key=f"add_confirm_{ident}"):
                    if not show_checked:
                        st.warning("Check at least one track first.")
                    elif not target_choice:
                        st.warning("Pick a playlist to add to.")
                    else:
                        target_playlist = playlist_labels[target_choice]
                        tracks_to_add = [{**t, "show": ident} for t in show_checked]
                        try:
                            add_tracks_to_playlist(target_playlist["id"], tracks_to_add)
                            st.success(f"Added to '{target_choice}'.")
                            for i in range(len(playlist)):
                                st.session_state.pop(f"addshow_check_{ident}_{i}", None)
                            st.rerun()
                        except Exception:
                            st.error("Couldn't add right now — the account database is unreachable.")

    render_show_notes(ident)

elif kind == "playlist":
    st.divider()
    chosen_playlist = playlist_labels[ident]
    force_columns_horizontal(equal_width=True, key="edit_delete_row")
    with st.container(key="edit_delete_row"):
        col_edit, col_delete = st.columns(2)
        with col_edit:
            if st.button("✏️ Edit this playlist", width="stretch"):
                st.session_state["playlist_draft"] = list(chosen_playlist["tracks"])
                st.session_state["editing_playlist_id"] = chosen_playlist["id"]
                st.session_state["editing_playlist_name"] = ident
                st.session_state["playlist_edit_mode"] = "edit"
                st.session_state["new_playlist_name"] = ident
                st.session_state["editor_load_select"] = ident
                st.switch_page("pages/playlist_creator.py")
        with col_delete:
            st.button("🗑️ Delete this playlist", width="stretch",
                      on_click=delete_playlist_cb,
                      args=(chosen_playlist["id"], ident))

st.divider()

if st.user.is_logged_in:
    dank_callout("Skip the bathroom songs, man.")
    with st.container(key="hex_to_creator"):
        if st.button("🎶 Click to Create a Playlist", key="to_creator_btn", width="stretch"):
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