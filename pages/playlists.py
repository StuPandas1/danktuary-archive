import streamlit as st  # type: ignore
import streamlit.components.v1 as components  # type: ignore
import pandas as pd  # type: ignore
import html
from shared import (  # type: ignore
    page_menu, dank_header, dank_theme, dank_footer, dank_sign, dank_hex, dank_callout, card_html,
    force_columns_horizontal, load_all_recordings, _data_file_mtimes, parse_duration,
    dank_playlist_player, with_onedrive_urls, show_index, tracks_for_show,
    format_playlist_track_label, style_playlist_draft_rows,
    load_playlists_from_supabase, save_playlist_to_supabase,
    update_playlist_in_supabase, delete_playlist_from_supabase,
)

st.set_page_config(page_title="DankApp | Playlists", page_icon="static/icon.png", layout="wide")
dank_theme()

MODE_LISTEN, MODE_BUILD = "Listen", "Build"
MT = _data_file_mtimes()

# -------------------------
# HELPERS
# -------------------------

def _format_seconds(total):
    total = int(round(total))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def _total_secs(tracks):
    total = 0
    for t in tracks:
        try:
            total += parse_duration(t.get("duration", "")) or 0
        except Exception:
            pass
    return total

def render_footer():
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

# -------------------------
# TOP ROW + HEADER
# -------------------------

force_columns_horizontal(gap="0.75rem", equal_width=True, key="top_row")
with st.container(key="top_row"):
    c1, c2 = st.columns(2, vertical_alignment="center")
    with c1:
        page_menu()
    with c2:
        if st.user.is_logged_in:
            if st.button("Logout", width="stretch"):
                st.logout()
        else:
            st.button("Log in with Google", on_click=st.login)

dank_header(subtitle="Skip the bathroom songs")

if not st.user.is_logged_in:
    dank_callout("Gotta log in to use playlists, man.", "Log in at the top to build and play your own.")
    render_footer()
    st.stop()

username = st.user.email

# -------------------------
# DATA
# -------------------------

df = load_all_recordings(MT).copy()
shows = show_index(df, MT)                     # shows with audio, newest first
show_labels = shows["Show_Label"].tolist()

playlists = {}
try:
    playlists = {p["playlist_name"]: p for p in load_playlists_from_supabase(username)}
except Exception:
    st.error("Couldn't load your playlists right now.")

# -------------------------
# STATE (settled before any widget is created)
# -------------------------

st.session_state.setdefault("pl_mode", MODE_LISTEN)
st.session_state.setdefault("pl_now", None)            # name of the playlist in the player
st.session_state.setdefault("pl_draft", [])
st.session_state.setdefault("pl_draft_id", None)
st.session_state.setdefault("pl_ver", 0)               # bumps to reset the track checkboxes
st.session_state.setdefault("pl_confirm_del", False)

open_mode = st.session_state.pop("pl_open", None)      # another page asked for a mode
if open_mode in (MODE_LISTEN, MODE_BUILD):
    st.session_state["pl_mode"] = open_mode
if st.session_state["pl_mode"] not in (MODE_LISTEN, MODE_BUILD):
    st.session_state["pl_mode"] = MODE_LISTEN
if st.session_state["pl_now"] not in playlists:
    st.session_state["pl_now"] = None

# pending values for widgets, applied before those widgets exist
if "pl_name_pending" in st.session_state:
    st.session_state["pl_name_input"] = st.session_state.pop("pl_name_pending")
if "pl_select_pending" in st.session_state:
    st.session_state["pl_select"] = st.session_state.pop("pl_select_pending")
if st.session_state.get("pl_select") not in playlists:
    st.session_state["pl_select"] = None

# -------------------------
# CALLBACKS (run before the rerun, so setting widget keys is legal)
# -------------------------

def play_selected():
    st.session_state["pl_now"] = st.session_state.get("pl_select")
    st.session_state["pl_confirm_del"] = False

def start_edit(name):
    """Load a saved playlist into the builder."""
    try:
        match = next((p for p in load_playlists_from_supabase(st.user.email)
                      if p["playlist_name"] == name), None)
    except Exception:
        match = None
    if not match:
        st.session_state["pl_flash"] = ("warn", "Couldn't load that playlist.")
        return
    st.session_state["pl_draft"] = list(match["tracks"])
    st.session_state["pl_draft_id"] = match["id"]
    st.session_state["pl_name_pending"] = match["playlist_name"]
    st.session_state["pl_mode"] = MODE_BUILD

def load_for_edit():
    name = st.session_state.get("pl_load")
    if name:
        start_edit(name)

def new_playlist():
    st.session_state["pl_draft"] = []
    st.session_state["pl_draft_id"] = None
    st.session_state["pl_name_pending"] = ""
    st.session_state["pl_load"] = None
    st.session_state["pl_ver"] += 1

def add_tracks(show, tracks, whole):
    ver = st.session_state["pl_ver"]
    draft = st.session_state["pl_draft"]
    for i, t in enumerate(tracks):
        if whole or st.session_state.get(f"pbchk_{ver}_{i}"):
            item = {**t, "show": show}
            if item not in draft:
                draft.append(item)
    st.session_state["pl_ver"] = ver + 1

def move_track(i, step):
    d = st.session_state["pl_draft"]
    j = i + step
    if 0 <= j < len(d):
        d[i], d[j] = d[j], d[i]

def remove_track(i):
    d = st.session_state["pl_draft"]
    if 0 <= i < len(d):
        d.pop(i)

def save_draft():
    name = (st.session_state.get("pl_name_input") or "").strip()
    draft = st.session_state["pl_draft"]
    if not name:
        st.session_state["pl_flash"] = ("warn", "Give your playlist a name first.")
        return
    if not draft:
        st.session_state["pl_flash"] = ("warn", "Add at least one track first.")
        return
    try:
        if st.session_state["pl_draft_id"]:
            ok, msg = update_playlist_in_supabase(st.session_state["pl_draft_id"], name, draft)
        else:
            ok, msg = save_playlist_to_supabase(st.user.email, name, draft)
    except Exception:
        st.session_state["pl_flash"] = ("err", "Couldn't save right now. Your draft is still here, try again shortly.")
        return
    if not ok:
        st.session_state["pl_flash"] = ("warn", msg)
        return
    st.session_state["pl_draft"] = []
    st.session_state["pl_draft_id"] = None
    st.session_state["pl_name_pending"] = ""
    st.session_state["pl_now"] = name
    st.session_state["pl_select_pending"] = name
    st.session_state["pl_mode"] = MODE_LISTEN
    st.session_state["pl_flash"] = ("ok", f"Saved '{name}'.")

def ask_delete():
    st.session_state["pl_confirm_del"] = True

def cancel_delete():
    st.session_state["pl_confirm_del"] = False

def do_delete(playlist_id, name):
    try:
        delete_playlist_from_supabase(playlist_id)
        st.session_state["pl_now"] = None
        st.session_state["pl_select_pending"] = None
        st.session_state["pl_flash"] = ("ok", f"Deleted '{name}'.")
    except Exception:
        st.session_state["pl_flash"] = ("err", "Couldn't delete right now. The account database is unreachable.")
    st.session_state["pl_confirm_del"] = False

# -------------------------
# PLAYER (fixed slot at the top, survives mode switches)
# -------------------------

player_slot = st.container(key="pl_player_slot")
st.divider()

# -------------------------
# MODE TOGGLE + FLASH
# -------------------------

st.segmented_control("Mode", [MODE_LISTEN, MODE_BUILD], key="pl_mode", label_visibility="collapsed")
mode = st.session_state.get("pl_mode") or MODE_LISTEN

flash = st.session_state.pop("pl_flash", None)
if flash:
    {"ok": st.success, "warn": st.warning, "err": st.error}[flash[0]](flash[1])

# =========================================================
# LISTEN
# =========================================================

if mode == MODE_LISTEN:
    names = sorted(playlists.keys(), key=str.lower)
    if not names:
        dank_hex("No saved playlists yet")
        st.button("🎶 Build your first one", key="pl_first", width="stretch",
                  type="primary", on_click=lambda: st.session_state.update(pl_mode=MODE_BUILD))
    else:
        st.selectbox(
            "Choose a playlist", names, index=None, placeholder=f"Pick from {len(names)} playlists...",
            key="pl_select", on_change=play_selected, label_visibility="collapsed",
        )

        now = st.session_state["pl_now"]
        if now:
            p = playlists[now]
            force_columns_horizontal(equal_width=True, gap="0.5rem", key="btnrow_pl_edit")
            with st.container(key="btnrow_pl_edit"):
                b1, b2 = st.columns(2)
                with b1:
                    st.button("✏️ Edit", key="pl_edit_btn", width="stretch",
                              on_click=start_edit, args=(now,))
                with b2:
                    st.button("🗑️ Delete", key="pl_del_btn", width="stretch", on_click=ask_delete)

            if st.session_state["pl_confirm_del"]:
                dank_callout(f"Delete **{now}**?", "This can't be undone.", img=None)
                force_columns_horizontal(equal_width=True, gap="0.5rem", key="btnrow_pl_confirm")
                with st.container(key="btnrow_pl_confirm"):
                    y, n = st.columns(2)
                    with y:
                        st.button("Yes, delete it", key="pl_del_yes", width="stretch", type="primary",
                                  on_click=do_delete, args=(p["id"], now))
                    with n:
                        st.button("Cancel", key="pl_del_no", width="stretch", on_click=cancel_delete)

# =========================================================
# BUILD
# =========================================================

else:
    draft = st.session_state["pl_draft"]
    editing = st.session_state["pl_draft_id"] is not None
    dank_sign("Edit Playlist" if editing else "New Playlist")

    force_columns_horizontal(equal_width=True, gap="0.5rem", key="btnrow_pl_build")
    with st.container(key="btnrow_pl_build"):
        b1, b2 = st.columns(2)
        with b1:
            st.button("🆕 Start Over", key="pl_new_btn", width="stretch", on_click=new_playlist)
        with b2:
            st.button("⬅ Back to Listen", key="pl_back_btn", width="stretch",
                      on_click=lambda: st.session_state.update(pl_mode=MODE_LISTEN))

    if playlists:
        st.selectbox("Load a playlist to edit", sorted(playlists.keys(), key=str.lower), index=None,
                     placeholder="Load a playlist to edit...", key="pl_load",
                     on_change=load_for_edit, label_visibility="collapsed")

    # ---- pick a show, tick tracks ----
    dank_hex("Add Tracks")
    build_show = st.selectbox(
        "Pick a show", show_labels, index=None,
        placeholder=f"Pick a show to grab tracks from ({len(show_labels)} with audio)...",
        key="pl_build_show", label_visibility="collapsed",
    )
    if build_show:
        tracks = tracks_for_show(df, build_show, MT, True)         # every take, so any can be saved
        if not tracks:
            dank_hex("No playable tracks in this show")
        else:
            ver = st.session_state["pl_ver"]
            with st.container(height=min(60 + 40 * len(tracks), 360), key="pl_tracks_scroll"):
                for i, t in enumerate(tracks):
                    st.checkbox(f"{t['label']}  ·  {t['duration']}", key=f"pbchk_{ver}_{i}")
            force_columns_horizontal(equal_width=True, gap="0.5rem", key="btnrow_pl_add")
            with st.container(key="btnrow_pl_add"):
                a1, a2 = st.columns(2)
                with a1:
                    st.button("➕ Add Selected", key="pl_add_sel", width="stretch",
                              on_click=add_tracks, args=(build_show, tracks, False))
                with a2:
                    st.button("➕ Add Whole Show", key="pl_add_all", width="stretch",
                              on_click=add_tracks, args=(build_show, tracks, True))

    # ---- the draft ----
    if not draft:
        dank_hex("Nothing in the draft yet")
    else:
        dank_hex("Current Draft", f"{len(draft)} tracks · {_format_seconds(_total_secs(draft))}")
        style_playlist_draft_rows()
        force_columns_horizontal(min_col_width="28px", key="playlist_draft_rows")
        with st.container(key="playlist_draft_rows"):
            for i, t in enumerate(draft):
                col_label, col_up, col_down, col_x = st.columns([6, 1, 1, 1])
                with col_label:
                    st.markdown(
                        f'<div class="dank-track-label">{html.escape(format_playlist_track_label(t, index=i))}</div>',
                        unsafe_allow_html=True,
                    )
                with col_up:
                    st.button("↑", key=f"pl_up_{i}", disabled=(i == 0),
                              on_click=move_track, args=(i, -1))
                with col_down:
                    st.button("↓", key=f"pl_dn_{i}", disabled=(i == len(draft) - 1),
                              on_click=move_track, args=(i, 1))
                with col_x:
                    st.button("✕", key=f"pl_rm_{i}", on_click=remove_track, args=(i,))

    st.text_input("Playlist name", key="pl_name_input", placeholder="Name your playlist...")
    st.button("💾 Save Playlist", key="pl_save", width="stretch", type="primary",
              disabled=not draft, on_click=save_draft)

# =========================================================
# FILL THE PLAYER SLOT (after state has settled)
# =========================================================

now = st.session_state["pl_now"]
with player_slot:
    if now:
        p = playlists[now]
        display_tracks = [
            {"label": format_playlist_track_label(t), "duration": t.get("duration", ""),
             "url": t.get("url", ""), "path": t.get("path", "")}
            for t in p["tracks"]
        ]
        if not display_tracks:
            dank_hex("This playlist is empty", "Edit it to add tracks")
        else:
            dank_playlist_player(now, with_onedrive_urls(display_tracks, df))
            cards = [
                card_html(len(display_tracks), "Tracks", accent=True),
                card_html(_format_seconds(_total_secs(display_tracks)), "Total Time"),
            ]
            st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)
    elif mode == MODE_LISTEN:
        dank_callout("Pick a playlist below to start listening.")

render_footer()