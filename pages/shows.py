import streamlit as st  # type: ignore
import streamlit.components.v1 as components
import pandas as pd  # type: ignore
import html
import random
from shared import (
    page_menu, dank_header, dank_theme, dank_footer, dank_sign, dank_hex, dank_callout, card_html,
    click_table, url_from_browser, sync_url, slug_to_show,
    dank_playlist_player, get_supabase_client, load_playlists_from_supabase, add_tracks_to_playlist,
    force_columns_horizontal, load_all_recordings, _data_file_mtimes, parse_duration,
    with_onedrive_urls, show_index_all, tracks_for_show,
)

st.set_page_config(page_title="DankApp | Shows", page_icon="static/icon.png", layout="wide")
dank_theme()

# Songs page doesn't exist yet. Until it does, song taps open Song Lookup on Stats.
# When pages/songs.py is built, change this to "pages/songs.py".
SONG_PAGE = "pages/songs.py"

MT = _data_file_mtimes()
df = load_all_recordings(MT).copy()
df["Date"] = pd.to_datetime(df["Date"], errors="coerce")

# -------------------------
# TOP ROW + HEADER
# -------------------------

username = st.user.email if st.user.is_logged_in else None
name = st.user.name if st.user.is_logged_in else None

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

dank_header(subtitle="Every show, every song")

# -------------------------
# HELPERS
# -------------------------

def _format_seconds(total_seconds):
    total_seconds = int(round(total_seconds))
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"

def _norm(title):
    return title.strip().lower() if isinstance(title, str) else ""

@st.cache_data(show_spinner=False)
def show_rows(_d, label, mtimes):
    """Take-1 rows for one show, in track order (audio or not)."""
    date_s, loc = label.split(" — ", 1)
    dt = pd.to_datetime(_d["Date"], errors="coerce")
    rows = _d[(dt.dt.strftime("%m/%d/%Y") == date_s) & (_d["Location"] == loc)]
    rows = rows[pd.to_numeric(rows["Take"], errors="coerce").fillna(1) == 1]
    return rows.sort_values("Track Number").reset_index(drop=True)

@st.cache_data(show_spinner=False)
def play_index(_d, mtimes):
    """{normalized title: [(date, location), ...]} for every Take-1 play."""
    a = _d[pd.to_numeric(_d["Take"], errors="coerce").fillna(1) == 1]
    idx = {}
    for t, d, l in zip(a["Title"], a["Date"], a["Location"]):
        if pd.isna(d) or not isinstance(t, str):
            continue
        idx.setdefault(_norm(t), []).append((d, l))
    return idx

@st.cache_data(show_spinner=False)
def venue_summary(_d, loc, mtimes):
    """(sets played, top play count, tied top songs) for one venue, Take 1 only."""
    r = _d[(_d["Location"] == loc) & (pd.to_numeric(_d["Take"], errors="coerce").fillna(1) == 1)]
    counts = r["Title"].value_counts()
    if counts.empty:
        return 0, 0, []
    top = int(counts.max())
    return r["Date"].nunique(), top, counts[counts == top].index.tolist()

@st.cache_data(show_spinner=False)
def show_detail(_d, label, mtimes):
    """Everything the stats panel needs for one show, built from the CSV
    (so shows without audio get it too). Returns None if there are no rows."""
    date_s, loc = label.split(" — ", 1)
    show_date = pd.to_datetime(date_s, format="%m/%d/%Y")
    rows = show_rows(_d, label, mtimes)
    if rows.empty:
        return None
    idx = play_index(_d, mtimes)

    # a run of rows sharing one Duration is a segue chain (one file)
    secs = rows["Duration"].apply(parse_duration)
    seg_next = rows["Duration"].eq(rows["Duration"].shift(-1))
    chain = (~rows["Duration"].eq(rows["Duration"].shift())).cumsum()
    chains = pd.DataFrame({"c": chain, "s": secs, "t": rows["Title"]}) \
        .groupby("c").agg(s=("s", "first"), t=("t", " -> ".join))
    total = int(chains["s"].sum())
    longest = chains.loc[chains["s"].idxmax()]
    shortest = chains.loc[chains["s"].idxmin()]

    table, bustout = [], None
    for num, title, dur, seg in zip(rows["Track Number"], rows["Title"], rows["Duration"], seg_next):
        plays = idx.get(_norm(title), [])
        prior = [p for p in plays if p[0] < show_date]
        last = max(prior, key=lambda p: p[0]) if prior else None
        table.append({
            "#": str(num),
            "Title": title + (" →" if seg else ""),
            "Duration": "--" if seg else str(dur),
            "Total Plays": str(len(plays)) if plays else "First time!",
            "Previous Play": last[0].strftime("%m/%d/%Y") if last else "First time!",
            "Previous Location": last[1] if last else "",
            "_song": title,
        })
        if last:
            days = (show_date - last[0]).days
            if bustout is None or days > bustout[1]:
                bustout = (title, days)

    sets, top, tied = venue_summary(_d, loc, mtimes)
    return {
        "songs": len(rows), "total": total,
        "longest": (longest["t"], int(longest["s"])),
        "shortest": (shortest["t"], int(shortest["s"])),
        "bustout": bustout, "sets": sets, "top": top, "tied": tied,
        "table": pd.DataFrame(table),
    }
@st.cache_data(show_spinner=False)
def show_totals(_d, mtimes):
    """One row per show: Date, Location, Secs (segue chains counted once), Songs. Take 1 only."""
    t = _d.dropna(subset=["Date"])
    t = t[pd.to_numeric(t["Take"], errors="coerce").fillna(1) == 1].sort_values(["Date", "Track Number"])
    first = t["Duration"].ne(t.groupby(["Date", "Location"])["Duration"].shift())
    secs = t.loc[first, "Duration"].apply(parse_duration)
    totals = secs.groupby([t.loc[first, "Date"], t.loc[first, "Location"]]).sum()
    songs = t.groupby(["Date", "Location"]).size()
    return pd.DataFrame({"Secs": totals, "Songs": songs}).reset_index()

@st.cache_data(show_spinner=False)
def venue_detail(_d, loc, mtimes):
    """First/last set, average set length, top 10 songs and every set at one venue."""
    tot = show_totals(_d, mtimes)
    v = tot[tot["Location"] == loc].sort_values("Date", ascending=False)
    if v.empty:
        return None
    r = _d[(_d["Location"] == loc) & (pd.to_numeric(_d["Take"], errors="coerce").fillna(1) == 1)]
    top = (r["Title"].value_counts().rename_axis("Title").reset_index(name="Times Played")
           .sort_values(["Times Played", "Title"], ascending=[False, True])
           .head(10).reset_index(drop=True))
    top.insert(0, "#", range(1, len(top) + 1))
    sets = pd.DataFrame({
        "Date": v["Date"].dt.strftime("%m/%d/%Y"),
        "Songs": v["Songs"].astype(str),
        "Total Time": v["Secs"].map(_format_seconds),
        "Venue": loc,                      # hidden; lets a date tap open that show
    }).reset_index(drop=True)
    return {
        "first": v["Date"].min(), "last": v["Date"].max(),
        "avg": float(v["Secs"].mean()), "overall_avg": float(tot["Secs"].mean()),
        "top": top, "sets": sets,
    }

# -------------------------
# NOTES
# -------------------------
# NOTE ON SCHEMA: replies rely on a nullable "parent_id" column on show_notes.

@st.cache_data(ttl=60, show_spinner=False)
def load_notes(show_label):
    try:
        sb = get_supabase_client()
        result = sb.table("show_notes").select("*").eq("show_label", show_label).order("created_at").execute()
        return result.data or []
    except Exception:
        return []

def save_note(show_label, username, display_name, note, parent_id=None):
    try:
        sb = get_supabase_client()
        sb.table("show_notes").insert({
            "show_label": show_label, "username": username,
            "display_name": display_name, "note": note, "parent_id": parent_id,
        }).execute()
        load_notes.clear()
        return True
    except Exception:
        return False

def build_note_tree(notes):
    by_id = {n["id"]: {**n, "replies": []} for n in notes if "id" in n}
    top_level = []
    for n in notes:
        node = by_id.get(n.get("id"))
        if node is None:
            continue
        pid = n.get("parent_id")
        if pid and pid in by_id and pid != n.get("id"):
            by_id[pid]["replies"].append(node)
        else:
            top_level.append(node)
    return top_level

def render_note(entry, show_label, depth=0):
    indent_px = depth * 24
    date_str = pd.Timestamp(entry["created_at"]).strftime("%m/%d/%Y")
    st.markdown(
        f"<div style='margin-left:{indent_px}px'>"
        f"<strong>{html.escape(entry['display_name'])}</strong> · "
        f"<span style='color:grey'>{date_str}</span></div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        f"<div style='margin-left:{indent_px}px; white-space:pre-wrap'>{html.escape(entry['note'])}</div>",
        unsafe_allow_html=True,
    )
    if st.user.is_logged_in:
        open_key = f"note_reply_open_{entry['id']}"
        if st.button("↩️ Reply", key=f"note_reply_btn_{entry['id']}"):
            st.session_state[open_key] = not st.session_state.get(open_key, False)
        if st.session_state.get(open_key):
            reply_text = st.text_area("Reply:", key=f"note_reply_text_{entry['id']}",
                                      placeholder=f"Replying to {entry['display_name']}...")
            if st.button("Post Reply", key=f"note_reply_submit_{entry['id']}"):
                if reply_text.strip():
                    if save_note(show_label, username, name, reply_text.strip(), parent_id=entry["id"]):
                        st.session_state[open_key] = False
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
    notes = load_notes(show_label)
    if notes:
        for entry in build_note_tree(notes):
            render_note(entry, show_label)
    else:
        dank_hex("No notes yet for this show.")
    if st.user.is_logged_in:
        new_note = st.text_area("Add a note:", placeholder="What stood out? What needs work?",
                                key=f"note_{show_label}")
        if st.button("Save Note", key=f"save_note_{show_label}"):
            if new_note.strip():
                if save_note(show_label, username, name, new_note.strip()):
                    st.success("Note saved!")
                    st.rerun()
                else:
                    st.error("Couldn't save note right now.")
            else:
                st.warning("Note is empty.")
    else:
        st.info("Log in above to add notes or reply.")

# -------------------------
# DATA + STATE
# -------------------------

shows = show_index_all(df, MT)
if shows.empty:
    dank_hex("No shows found")
    st.stop()

all_labels = set(shows["Show_Label"])
latest = shows.iloc[0]["Show_Label"]

playlist_labels = {}
if st.user.is_logged_in:
    try:
        playlist_labels = {p["playlist_name"]: p for p in load_playlists_from_supabase(username)}
    except Exception:
        st.error("Couldn't load your playlists right now.")

# the browser changed the URL (shared link, back/forward)
q = slug_to_show(url_from_browser("date"))
if q in all_labels:
    st.session_state["show_sel"] = q
    st.session_state["show_list_open"] = False

# another page sent us here (new key first, then the old ones from unmigrated pages)
for k in ("pending_show", "pending_listen_show", "pending_show_selection"):
    v = st.session_state.pop(k, None)
    if v in all_labels:
        st.session_state["show_sel"] = v
        st.session_state["show_list_open"] = False

st.session_state.setdefault("show_sel", latest)
if st.session_state["show_sel"] not in all_labels:
    st.session_state["show_sel"] = latest
st.session_state.setdefault("show_list_open", True)

# ---------- callbacks ----------
def toggle_list():
    st.session_state["show_list_open"] = not st.session_state["show_list_open"]

def pick_show(label):
    st.session_state["show_sel"] = label
    st.session_state["show_list_open"] = False

def pick_random(labels):
    if labels:
        pick_show(random.choice(labels))

def render_show_buttons(frame, sel):
    st.markdown(f'<div class="song-browse-hint"> Select from {len(frame)} shows</div>',
                unsafe_allow_html=True)
    with st.container(height=320, key="shows_scroll"):
        for i, r in enumerate(frame.itertuples()):
            dur = _format_seconds(r.Secs) if r.Secs else "—"
            mark = "  🎧" if r.Has_Audio else ""
            kind = "trackon" if r.Show_Label == sel else "trackrow"
            with st.container(key=f"{kind}_shw_{i}"):
                st.button(f"{r.Date:%m/%d/%Y}  ·  {r.Location}  ·  {dur}{mark}",
                          key=f"shw_row_{i}", width="stretch",
                          on_click=pick_show, args=(r.Show_Label,))

# -------------------------
# BROWSE
# -------------------------

dank_hex("Find a Show")
with st.container(key="browse_area"):
    years = sorted(shows["Date"].dt.year.unique(), reverse=True)
    year_opts = ["All"] + [str(y) for y in years[:5]] + (["Older"] if len(years) > 5 else [])

    with st.expander("Filters"):
        type_pick = st.pills("Type", ["All", "Gigs", "Practice"], default="All", key="shows_type") or "All"
        year_pick = st.pills("Year", year_opts, default="All", key="shows_year") or "All"
        venue_pick = st.selectbox("Venue", ["All"] + sorted(shows["Location"].unique()), key="shows_venue")

    f = shows
    if type_pick == "Gigs":
        f = f[f["Type"] == "live"]
    elif type_pick == "Practice":
        f = f[f["Type"] != "live"]
    if year_pick == "Older":
        f = f[f["Date"].dt.year < years[4]]
    elif year_pick != "All":
        f = f[f["Date"].dt.year == int(year_pick)]
    if venue_pick != "All":
        f = f[f["Location"] == venue_pick]
    labels = f["Show_Label"].tolist()

    today_md = pd.Timestamp.now(tz="America/New_York").strftime("%m/%d")
    on_this_day = shows.loc[shows["Date"].dt.strftime("%m/%d") == today_md, "Show_Label"].tolist()
    list_open = st.session_state["show_list_open"]

    force_columns_horizontal(equal_width=True, gap="0.5rem", key="btnrow_shows")
    with st.container(key="btnrow_shows"):
        b1, b2, b3 = st.columns(3)
        with b1:
            st.button("Close List" if list_open else "Open List", key="shows_toggle", width="stretch",
                      type="primary" if list_open else "secondary", on_click=toggle_list)
        with b2:
            st.button("Random", key="shows_random", width="stretch",
                      disabled=not labels, on_click=pick_random, args=(labels,))
        with b3:
            st.button("On This Day", key="shows_otd", width="stretch",
                      disabled=not on_this_day, on_click=pick_random, args=(on_this_day,))

    if f.empty:
        dank_hex("No shows match those filters")
    elif list_open:
        render_show_buttons(f, st.session_state["show_sel"])

st.divider()

# -------------------------
# SELECTED SHOW
# -------------------------

sel = st.session_state["show_sel"]
row = shows[shows["Show_Label"] == sel].iloc[0]
sync_url(date=sel)

dank_sign(f"{row['Location']} — {row['Date']:%m/%d/%Y}")

player_slot = st.container(key="player_slot")
playlist = []
with player_slot:
    if row["Has_Audio"]:
        playlist = tracks_for_show(df, sel, MT, True)           # every take
        if playlist:
            playable = with_onedrive_urls(playlist, df)
            dank_playlist_player(sel, playable)
            if len(playable) < len(playlist):
                st.caption(f"{len(playlist) - len(playable)} track(s) couldn't be loaded right now.")
        else:
            dank_hex("No playable tracks found for this show")
    else:
        dank_hex("No recording of this one", "Setlist only")

detail = show_detail(df, sel, MT)

with st.expander("📊 Show Stats Dashboard", True):
    if detail is None:
        dank_hex("No setlist on file for this show")
    else:
        cards = [
            card_html(detail["songs"], "Songs", accent=True),
            card_html(_format_seconds(detail["total"]), "Total Time"),
        ]
        st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

        lt, ls = detail["longest"]
        st_, ss = detail["shortest"]
        if detail["bustout"]:
            bust_line = f"🎺 Biggest Bustout: **{detail['bustout'][0]}** ({detail['bustout'][1]:,} days)"
        else:
            bust_line = "🎺 Biggest Bustout: none"
        dank_callout(
            f"🏆 Longest: **{lt}** ({_format_seconds(ls)})\n"
            f"⚡ Shortest: **{st_}** ({_format_seconds(ss)})",
            bust_line,
            img=None,
        )

        dank_hex("Setlist")
        click_table(detail["table"], key="tbl_show",
                    song_cols={"Title": "_song"},
                    show_cols={"Previous Play": "Previous Location"},
                    hide=("_song",), song_goto=SONG_PAGE)

if detail is not None:
    with st.expander("🏟️ Venue Stats Dashboard", False):
        vd = venue_detail(df, row["Location"], MT)
        n_sets = detail["sets"]
        if len(detail["tied"]) > 1:
            fav_val, fav_lbl = f"{len(detail['tied'])} tied", f"Venue Favorites ({detail['top']}x each)"
        elif detail["tied"]:
            fav_val, fav_lbl = html.escape(detail["tied"][0]), f"Venue Favorite ({detail['top']}x)"
        else:
            fav_val, fav_lbl = "—", "Venue Favorite"

        cards = [
            card_html(n_sets, "Set at Venue" if n_sets == 1 else "Sets at Venue", accent=True),
            card_html(_format_seconds(vd["avg"]), "Avg Set Length", nowrap=True),

        ]
        if vd:
            cards += [
                card_html(vd["first"].strftime("%m/%d/%y"), "First Set", nowrap=True),
                card_html(vd["last"].strftime("%m/%d/%y"), "Last Set", nowrap=True),
            ]
        st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

        if vd:
            diff = vd["avg"] - vd["overall_avg"]
            if abs(diff) >= 30:
                st.caption(f"Sets here run about {abs(diff) / 60:.0f} min "
                           f"{'longer' if diff > 0 else 'shorter'} than the average across all venues.")

            tab_top, tab_sets = st.tabs(["Top 10 Songs", "All Sets"])
            with tab_top:
                click_table(vd["top"], key="tbl_venue_top", song_cols=("Title",), song_goto=SONG_PAGE)
            with tab_sets:
                click_table(vd["sets"], key="tbl_venue_sets", show_cols={"Date": "Venue"})
        
if st.user.is_logged_in and playlist:
    with st.expander("➕ Add tracks from this show to a playlist"):
        checked = []
        for i, track in enumerate(playlist):
            if st.checkbox(f"{track['label']}  ·  {track['duration']}", key=f"addshow_check_{sel}_{i}"):
                checked.append(track)

        targets = list(playlist_labels.keys())
        if not targets:
            st.caption("No saved playlists yet. Create one with the Playlist Creator button below.")
        else:
            target = st.selectbox("Add checked tracks to:", targets, index=None,
                                  placeholder="Choose a playlist...", key=f"add_target_{sel}")
            if st.button("➕ Add checked tracks", key=f"add_confirm_{sel}"):
                if not checked:
                    st.warning("Check at least one track first.")
                elif not target:
                    st.warning("Pick a playlist to add to.")
                else:
                    try:
                        add_tracks_to_playlist(playlist_labels[target]["id"],
                                               [{**t, "show": sel} for t in checked])
                        st.success(f"Added to '{target}'.")
                        for i in range(len(playlist)):
                            st.session_state.pop(f"addshow_check_{sel}_{i}", None)
                        st.rerun()
                    except Exception:
                        st.error("Couldn't add right now. The account database is unreachable.")

render_show_notes(sel)

st.divider()

if st.user.is_logged_in:
    dank_callout("Skip the bathroom songs, man.")
    if st.button("🎶 Click to Create a Playlist", key="shows_to_creator", width="stretch"):
        st.session_state["pl_open"] = "Build"
        st.switch_page("pages/playlists.py")
else:
    dank_callout("Gotta login if you want playlists, man.")

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
