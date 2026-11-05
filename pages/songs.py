import streamlit as st  # type: ignore
import streamlit.components.v1 as components
import pandas as pd  # type: ignore
import random
from shared import (
    page_menu, dank_header, dank_theme, dank_footer, dank_sign, dank_hex, dank_callout, card_html,
    click_table, url_from_browser, sync_url, load_data, build_filtered, parse_duration,
    make_dead_weight_callback, add_segue_labels, count_bar, force_columns_horizontal,
    show_index_all, _data_file_mtimes,
)

st.set_page_config(page_title="DankApp | Songs", page_icon="static/icon.png", layout="wide")
dank_theme()

SHOW_PAGE = "pages/shows.py"
MT = _data_file_mtimes()

BUCKET_ORDER = [
    "0–2 min", "2–4 min", "4–6 min", "6–8 min", "8–10 min", "10–12 min",
    "12–14 min", "14–16 min", "16–18 min", "18–20 min", "20+ min",
]

@st.cache_data(show_spinner=False)
def labeled_df(d):
    return add_segue_labels(d)

@st.cache_data(show_spinner=False)
def played_with(d, title):
    """Songs that shared a track (segue chain) with `title`, most often first."""
    s = d.sort_values(["Date", "Location", "Track Number"])
    show = s["Date"].astype(str) + "|" + s["Location"].astype(str)
    new_chain = show.ne(show.shift()) | s["Duration"].ne(s["Duration"].shift())
    s = s.assign(_c=new_chain.cumsum())

    mine = s.loc[s["Title"] == title, "_c"].unique()
    others = s[s["_c"].isin(mine) & (s["Title"] != title)].sort_values("Date")
    if others.empty:
        return others
    out = (
        others.groupby("Title")
        .agg(Times=("_c", "nunique"), Last=("Date", "max"), Loc=("Location", "last"))
        .reset_index()
        .sort_values(["Times", "Title"], ascending=[False, True])
        .assign(Last=lambda x: x["Last"].dt.strftime("%m/%d/%Y"))
        .rename(columns={"Times": "Times Together", "Last": "Last Together", "Loc": "Last Location"})
        .reset_index(drop=True)
    )
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out

df, song_stats, metadata, jam_metadata = load_data()
df2 = df.copy()                       # every take (for the show index)
df = df[df["Take"] == 1]              # Take 1 only, for stats

min_year = int(df["Year"].min())
max_year = int(df["Year"].max())

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

dank_header(subtitle="Every song we've played")

# -------------------------
# FILTERS + TITLE LIST
# -------------------------

st.session_state.setdefault("songs_year", (min_year, max_year))

with st.expander("Filters", expanded=False):
    st.checkbox(
        "Dead Weight Only", key="songs_dw",
        on_change=make_dead_weight_callback("songs_artist", "songs_year", "songs_dw", min_year, max_year),
    )
    f_artist = st.multiselect("By Artist:", sorted(song_stats["Artist"].dropna().unique()), key="songs_artist")
    f_year = st.slider("By Year:", min_year, max_year, key="songs_year")

f_df, f_stats = build_filtered(df, metadata, f_artist, f_year)
all_titles = sorted(f_stats["Title"].unique())

# -------------------------
# INCOMING LINKS (browser URL, other pages, old keys)
# -------------------------

incoming = url_from_browser("song")
for k in ("pending_song", "t1_pending_song_selection"):
    v = st.session_state.pop(k, None)
    incoming = v or incoming
if incoming:
    st.session_state["song_widget"] = incoming
    st.session_state["songs_browse_open"] = False

if st.session_state.get("song_widget") not in all_titles:
    st.session_state["song_widget"] = None      # also covers a filter hiding the song
st.session_state.setdefault("songs_browse_open", False)

# ---------- callbacks (run before the rerun, so setting widget keys is legal) ----------
def toggle_browse():
    st.session_state["songs_browse_open"] = not st.session_state["songs_browse_open"]

def pick_song(title):
    st.session_state["song_widget"] = title
    st.session_state["songs_browse_open"] = False

def pick_random(titles):
    if titles:
        pick_song(random.choice(titles))

def clear_song():
    st.session_state["song_widget"] = None

# -------------------------
# PICKER
# -------------------------

dank_sign("Find a Song")

selected_song = st.selectbox(
    "Search songs", all_titles, index=None,
    placeholder=f"Search {len(all_titles)} songs...",
    key="song_widget", label_visibility="collapsed",
)
sync_url(song=selected_song)

browse_open = st.session_state["songs_browse_open"]
force_columns_horizontal(equal_width=True, gap="0.5rem", key="btnrow_songs")
with st.container(key="btnrow_songs"):
    b1, b2, b3 = st.columns(3)
    with b1:
        st.button("Close List" if browse_open else "Browse A–Z", key="songs_browse_btn", width="stretch",
                  type="primary" if browse_open else "secondary", on_click=toggle_browse)
    with b2:
        st.button("Random", key="songs_random", width="stretch",
                  disabled=not all_titles, on_click=pick_random, args=(all_titles,))
    with b3:
        st.button("Clear", key="songs_clear", width="stretch",
                  disabled=not selected_song, on_click=clear_song)

if browse_open:
    st.markdown(f'<div class="song-browse-hint"> Select from {len(all_titles)} songs</div>',
                unsafe_allow_html=True)
    with st.container(height=320, key="songs_scroll"):
        for i, t in enumerate(sorted(all_titles, key=str.lower)):
            kind = "trackon" if t == selected_song else "trackrow"
            with st.container(key=f"{kind}_sng_{i}"):
                st.button(t, key=f"sng_row_{i}", width="stretch", on_click=pick_song, args=(t,))

# -------------------------
# SELECTED SONG
# -------------------------

if not selected_song:
    dank_callout("Pick a song to see where and when we've played it.")
else:
    st.divider()
    match = f_stats[f_stats["Title"] == selected_song]
    if not match.empty:
        s = match.iloc[0]
        gigs = f_df[(f_df["Title"] == selected_song) & (f_df["Type"] == "live")]
        if gigs.empty:
            gig_value = "0"
        else:
            gig_value = f"{len(gigs)} ({gigs['Date'].max():%m/%d/%y})"        
        dank_sign(selected_song)
        cards = [
            card_html(int(s["Times_Played"]), "Times Played", accent=True, nowrap=True),
            card_html(gig_value, "At Gigs (Last)", nowrap=True),
            card_html(s["First_Played"].strftime("%m/%d/%y"), "First Played", nowrap=True),
            card_html(s["Last_Played"].strftime("%m/%d/%y"), "Last Played", nowrap=True),
        ]
        st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    labeled = labeled_df(df)
    perf = (labeled[labeled["Title"] == selected_song]
            .sort_values("Date", ascending=False).copy())
    perf["Gap"] = perf["Date"].diff(-1).dt.days

    tab_hist, tab_with, tab_year, tab_len = st.tabs(["Appearances", "Plays With", "Graph By Year", "Graph By Length"])

    # ---- every appearance; tap a show to open it (and play it) ----
    with tab_hist:
        has_audio = dict(zip(show_index_all(df2, MT)["Show_Label"], show_index_all(df2, MT)["Has_Audio"]))
        labels = perf["Date"].dt.strftime("%m/%d/%Y") + " — " + perf["Location"]
        history = pd.DataFrame({
            "Show": labels,
            "Title": perf["Segue Label"],
            "Duration": perf["Duration"].astype(str),
            "Gap": perf["Gap"].map(lambda g: "—" if pd.isna(g) else str(int(g))),
            "Audio": labels.map(lambda l: "🎧" if has_audio.get(l) else ""),
        }).reset_index(drop=True)
        n = len(history)
        dank_hex(f"**{selected_song}**", f"{n} appearance{'' if n == 1 else 's'}")
        click_table(history, key="tbl_song_hist", show_cols={"Show": None}, show_goto=SHOW_PAGE)

    # ---- songs it's most often played together with ----
    with tab_with:
        pairs = played_with(df, selected_song)
        if pairs.empty:
            dank_hex(f"**{selected_song}**", "Always played on its own")
        else:
            n = len(pairs)
            dank_hex(f"**{selected_song}** is played with", f"{n} other song{'' if n == 1 else 's'}")
            click_table(pairs, key="tbl_song_with", song_cols=("Title",),
                        show_cols={"Last Together": "Last Location"}, show_goto=SHOW_PAGE)
            
    # ---- plays per year ----
    with tab_year:
        yearly = (perf.groupby(perf["Date"].dt.year).size()
                  .reindex(range(min_year, max_year + 1), fill_value=0)
                  .rename_axis("Year").reset_index(name="Times Played"))
        yearly["Year"] = yearly["Year"].astype(str)
        st.altair_chart(count_bar(yearly, "Year", ""), width="stretch")

    # ---- plays by length ----
    with tab_len:
        secs = perf["Duration"].dropna().apply(parse_duration)
        idx = (secs // 120).clip(upper=10).astype(int)
        counts = (idx.map(lambda i: BUCKET_ORDER[i]).value_counts()
                  .reindex(BUCKET_ORDER, fill_value=0)
                  .rename_axis("Length").reset_index(name="Times Played"))
        counts = counts[counts["Times Played"] > 0]
        st.altair_chart(count_bar(counts, "Length", "", sort=BUCKET_ORDER), width="stretch")

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