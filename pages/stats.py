import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import altair as alt  # type: ignore
import os
import streamlit.components.v1 as components  # type: ignore
import html
import random
import urllib.parse
import numpy as np
from shared import ( #type: ignore
    load_data, build_filtered, find_closers, parse_duration, dank_theme, dank_footer, dank_sign, force_columns_horizontal, dank_chart, card_html, add_segue_labels, count_bar, dank_hex,
    dank_callout, make_dead_weight_callback, page_menu, local_path_to_onedrive_url, dank_header, ranked_table, linked_table,
    dead_weight_artists, dead_weight_year
)

BUCKET_ORDER = [
    "0–2 min", "2–4 min", "4–6 min", "6–8 min", "8–10 min", "10–12 min",
    "12–14 min", "14–16 min", "16–18 min", "18–20 min", "20+ min",
]

@st.cache_data(show_spinner=False)
def labeled_df(d):
    return add_segue_labels(d)

@st.cache_data(show_spinner=False)
def build_performances(d):
    p = d.copy()
    p["Show_Label"] = p["Date"].dt.strftime("%m/%d/%Y") + " — " + p["Location"]
    p["Type_Order"] = p["Type"].map({"live": 0, "trip": 1, "practice": 2}).fillna(3)
    return p

@st.cache_data(show_spinner=False)
def longest_gaps(d):
    """Biggest number of shows missed between two plays of each song."""
    show_idx = {dt: i for i, dt in enumerate(sorted(d["Date"].unique()))}
    plays = d[["Title", "Date", "Location"]].drop_duplicates(["Title", "Date"]).copy()
    plays["idx"] = plays["Date"].map(show_idx)
    plays = plays.sort_values(["Title", "idx"])
    g = plays.groupby("Title")
    plays["Gap"] = g["idx"].diff() - 1
    plays["From"] = g["Date"].shift()
    plays["From Location"] = g["Location"].shift()
    plays = plays[plays["Gap"] > 0]
    if plays.empty:
        return plays
    best = plays.loc[plays.groupby("Title")["Gap"].idxmax()]
    out = pd.DataFrame({
        "Title": best["Title"],
        "Longest Gap (Sets)": best["Gap"].astype(int),
        "From": best["From"].dt.strftime("%m/%d/%Y"),
        "From Location": best["From Location"],
        "To": best["Date"].dt.strftime("%m/%d/%Y"),
        "To Location": best["Location"],
    })
    return out.sort_values("Longest Gap (Sets)", ascending=False).reset_index(drop=True)

@st.cache_data(show_spinner=False)
def long_jams(d, min_secs=1080):
    """Segue chains (same show, same Duration) of at least min_secs."""
    d = d.sort_values(["Date", "Track Number"])
    new_chain = d["Date"].ne(d["Date"].shift()) | d["Duration"].ne(d["Duration"].shift())
    jams = (
        d.assign(_g=new_chain.cumsum())
        .groupby("_g")
        .agg(Date=("Date", "first"), Location=("Location", "first"),
             Songs=("Title", " -> ".join), Duration=("Duration", "first"))
    )
    jams["secs"] = jams["Duration"].apply(parse_duration)
    jams = jams[jams["secs"] >= min_secs].sort_values("secs", ascending=False)
    jams["Date"] = jams["Date"].dt.strftime("%m/%d/%Y")
    return (jams.rename(columns={"Songs": "Song(s)"})
                .drop(columns="secs").reset_index(drop=True))


@st.cache_data(show_spinner=False)
def active_streaks(d):
    """Consecutive most-recent shows each song has appeared in."""
    day = d["Date"].dt.normalize()
    dates = sorted(day.unique())
    present = pd.crosstab(d["Title"], day).reindex(columns=dates, fill_value=0).gt(0)
    streak = present.iloc[:, ::-1].astype(int).cumprod(axis=1).sum(axis=1)
    out = streak[streak > 1].rename("Active Streak").reset_index()
    return out

@st.cache_data(show_spinner=False)
def venue_summary(d, loc):
    """(sets played, top play count, tied top songs) for one venue."""
    rows = d[d["Location"] == loc]
    counts = rows["Title"].value_counts()
    top = int(counts.max())
    return rows["Date"].nunique(), top, counts[counts == top].index.tolist()

@st.cache_data(show_spinner=False)
def most_played_table(stats, d):
    """Most Played table with hidden first/last locations for show links."""
    t = (
        stats.sort_values("Times_Played", ascending=False)
        .assign(
            First_Played=lambda x: x["First_Played"].dt.strftime("%m/%d/%Y"),
            Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y"),
        )[["Title", "Times_Played", "First_Played", "Last_Played"]]
        .rename(columns={"Times_Played": "Times Played",
                         "First_Played": "First Played",
                         "Last_Played": "Last Played"})
        .reset_index(drop=True)
    )
    locs = d.sort_values("Date").groupby("Title")["Location"].agg(["first", "last"])
    t["First Location"] = t["Title"].map(locs["first"])
    t["Last Location"] = t["Title"].map(locs["last"])
    t.insert(0, "Rank", range(1, len(t) + 1))
    return t

@st.cache_data(show_spinner=False)
def opener_counts(d):
    return (d[d["Track Number"] == 1]["Title"].value_counts()
            .rename_axis("Title").reset_index(name="Times Opened"))


@st.cache_data(show_spinner=False)
def closer_counts(d):
    closers = find_closers(d, set(d["Title"].unique()))
    return (pd.Series(closers).value_counts()
            .rename_axis("Title").reset_index(name="Times Closed"))


@st.cache_data(show_spinner=False)
def segue_counts(d, min_plays=3):
    """Consecutive songs within a show, counted as pairs."""
    d = d.sort_values(["Date", "Track Number"])
    nxt = d.groupby("Date")["Title"].shift(-1)
    pairs = (d["Title"] + "  →  " + nxt)[nxt.notna()]
    out = pairs.value_counts().rename_axis("Segue").reset_index(name="Times Played")
    return out[out["Times Played"] >= min_plays].reset_index(drop=True)


@st.cache_data(show_spinner=False)
def gig_counts(d):
    return (
        d[d["Type"] == "live"].sort_values("Date")
        .groupby("Title")
        .agg(Times_Played=("Title", "count"),
             Last_Played=("Date", "max"),
             Last_Location=("Location", "last"))
        .reset_index()
        .sort_values("Times_Played", ascending=False)
        .assign(Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y"))
        .rename(columns={"Times_Played": "Times Played", "Last_Played": "Last Played",
                         "Last_Location": "Last Location"})
        .reset_index(drop=True)
    )


@st.cache_data(show_spinner=False)
def studio_lengths(d):
    """Total minutes per Danktuary Studios session (80+ min only)."""
    s = d[d["Location"] == "Danktuary Studios"].sort_values(["Date", "Track Number"])
    s = s[~s["Duration"].eq(s.groupby("Date")["Duration"].shift())]   # drop segue repeats
    mins = s["Duration"].apply(parse_duration).groupby(s["Date"]).sum().div(60)
    out = mins.rename("Total Minutes").reset_index()
    return out[out["Total Minutes"] >= 80].reset_index(drop=True)

st.set_page_config(page_title="DankApp | Heady Stats", page_icon="static/icon.png", layout="wide")
dank_theme()

df, song_stats, metadata, jam_metadata = load_data()
df2 = df.copy()
df = df[df["Take"] == 1]

page_menu()

min_year = int(df["Year"].min())
max_year = int(df["Year"].max())

force_columns_horizontal(gap="8px", equal_width=True)

# -------------------------
# SESSION STATE
# -------------------------

if "selected_song" not in st.session_state:
    st.session_state.selected_song = None

if "selected_show" not in st.session_state:
    st.session_state.selected_show = None

if "active_stat" not in st.session_state:
    st.session_state.active_stat = None

if "t1_year" not in st.session_state:
    st.session_state.t1_year = (min_year, max_year)

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Song Search"
# Deep-link support:
#   /explore?song=<title>  -> selects a song, jumps to Song Search
#   /explore?show=<label>  -> selects a show, jumps to Setlist Lookup
query_song = st.query_params.get("song")
query_show = st.query_params.get("show")
 
if query_song and query_song != st.session_state.selected_song:
    st.session_state.t1_pending_song_selection = query_song
    st.session_state.active_tab = "Song Lookup"
    st.query_params.clear()
elif query_show and query_show != st.session_state.selected_show:
    st.session_state.pending_show_selection = query_show
    st.session_state.active_tab = "Setlist Lookup"
    st.query_params.clear()
 

dank_header(subtitle="Heady Stats")

tab_groups = [
    ("Search by Song/Setlist", ["Song Lookup", "Setlist Lookup"]),  # these are used by query-param redirects!!
    ("Poke Around the Data", ["Song Stats", "Setlist Stats"]),
]

for g, (label, names) in enumerate(tab_groups):
    st.caption(label)
    with st.container(key=f"tabs_stats_{g}"):
        row_cols = st.columns(len(names))
        for col, name in zip(row_cols, names):
            with col:
                button_type = "primary" if st.session_state.active_tab == name else "secondary"
                if st.button(name, key=f"tabbtn_{name}", width="stretch", type=button_type):
                    st.session_state.active_tab = name
                    st.rerun()

st.divider()

# -------------------------
# SHARED HELPER: DW filter for stats tabs
# -------------------------

def get_stats_df(dw_key):
    """Returns (filtered_df, filtered_stats) based on the DW checkbox."""
    dead_weight_only = st.checkbox("Dead Weight Only", key=dw_key)
    if dead_weight_only:
        return build_filtered(df, metadata, dead_weight_artists, (dead_weight_year, max_year))
    return build_filtered(df, metadata, [], (min_year, max_year))

# -------------------------
# TAB 1: SONG LOOKUP
# -------------------------

if st.session_state.active_tab == "Song Lookup":
    dank_sign("Song Lookup")

    with st.expander("Filters", expanded=False):
        st.checkbox(
            "Dead Weight Only",
            key="t1_dead_weight",
            on_change=make_dead_weight_callback("t1_artist", "t1_year", "t1_dead_weight", min_year, max_year)
        )
        t1_artist = st.multiselect(
            "By Artist:",
            sorted(song_stats["Artist"].dropna().unique()),
            key="t1_artist"
        )
        t1_year = st.slider("By Year:", min_year, max_year, key="t1_year")

    t1_df, t1_stats = build_filtered(df, metadata, t1_artist, t1_year)
    all_titles = sorted(t1_stats["Title"].unique())

    # Widgets can't be set after they're drawn in the same run, so buttons
    # stash a value here and it's applied before the selectbox is created.
    if "t1_pending_song_selection" in st.session_state:
        st.session_state.t1_song_widget = st.session_state.pop("t1_pending_song_selection")

    # A filter change can drop the selected song from the options.
    if st.session_state.get("t1_song_widget") not in all_titles:
        st.session_state.t1_song_widget = None

    selected_song = st.selectbox(
        "Get shown the light...",
        all_titles,
        index=None,
        placeholder="Type to search...",
        key="t1_song_widget"
    )
    st.session_state.selected_song = selected_song

    st.session_state.setdefault("t1_show_browse", False)
    with st.container(key="btnrow_song"):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button(
                "Hide list" if st.session_state.t1_show_browse else "Browse A–Z",
                key="t1_browse_btn",
                width="stretch",
                type="primary" if st.session_state.t1_show_browse else "secondary",
            ):
                st.session_state.t1_show_browse = not st.session_state.t1_show_browse
                st.rerun()
        with col2:
            if st.button("Random Song", width="stretch"):
                st.session_state.t1_pending_song_selection = random.choice(all_titles)
                st.rerun()
        with col3:
            if st.button("Clear Song", width="stretch"):
                st.session_state.t1_pending_song_selection = None
                st.rerun()

    if st.session_state.t1_show_browse:
        song_links = "".join(
            f'<a href="/stats?song={urllib.parse.quote(t, safe="")}" target="_self">{html.escape(t)}</a>'
            for t in sorted(all_titles, key=str.lower)
        )
        st.markdown(f'<div class="song-browse">{song_links}</div>', unsafe_allow_html=True)

    if selected_song:
        match = t1_stats[t1_stats["Title"] == selected_song]

        if not match.empty:
            s = match.iloc[0]
            days_ago = (pd.Timestamp.today() - s["Last_Played"]).days
            st.divider()
            dank_sign(f"{selected_song}: Song Info", direction="right")    
            cards = [
                card_html(int(s["Times_Played"]), "Times Played", accent=True),
                card_html(s["First_Played"].strftime("%m/%d/%Y"), "First Played"),
                card_html(s["Last_Played"].strftime("%m/%d/%Y"), "Last Played"),
                card_html(f"{days_ago:,}", "Day Ago" if days_ago == 1 else "Days Ago"),
            ]
            st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

        labeled = labeled_df(df)
        perf = (
            labeled[labeled["Title"] == selected_song]
            .sort_values("Date", ascending=False)
            .copy()
        )
        perf["Gap"] = perf["Date"].diff(-1).dt.days
        perf = perf.rename(columns={"Segue Label": "SegueLabel"})

        tab_hist, tab_year, tab_len = st.tabs(["Performance History", "Graph By Year", "Graph By Length"])

        # ---- performance history ----
        with tab_hist:
            dank_hex(f"{selected_song}: Performance History")
            rows_html = []
            for r in perf.itertuples():
                show_label = f"{r.Date.strftime('%m/%d/%Y')} — {r.Location}"
                gap_display = "—" if pd.isna(r.Gap) else str(int(r.Gap))
                rows_html.append(
                    "<tr>"
                    f'<td><a href="/stats?show={urllib.parse.quote(show_label, safe="")}" target="_self">{html.escape(show_label)}</a></td>'
                    f"<td>{html.escape(str(r.SegueLabel))}</td>"
                    f"<td>{html.escape(str(r.Duration))}</td>"
                    f"<td>{gap_display}</td>" 
                    "</tr>"
                )
            st.markdown(
                '<table class="perf-history-table"><thead><tr>'
                "<th>Show</th><th>Title</th><th>Duration</th><th>Gap</th>"
                f"</tr></thead><tbody>{''.join(rows_html)}</tbody></table>",
                unsafe_allow_html=True,
            )

        # ---- plays per year ----
        with tab_year:
            dank_hex(f"{selected_song}: Plays by Year")
            yearly = (
                perf.groupby(perf["Date"].dt.year).size()
                .reindex(range(min_year, max_year + 1), fill_value=0)
                .rename_axis("Year").reset_index(name="Times Played")
            )
            yearly["Year"] = yearly["Year"].astype(str)
            st.altair_chart(count_bar(yearly, "Year", ""), width="stretch")

        # ---- plays by length ----
        with tab_len:
            dank_hex(f"{selected_song}: Plays by Length")
            secs = perf["Duration"].dropna().apply(parse_duration)
            idx = (secs // 120).clip(upper=10).astype(int)
            counts = (
                idx.map(lambda i: BUCKET_ORDER[i]).value_counts()
                .reindex(BUCKET_ORDER, fill_value=0)
                .rename_axis("Length").reset_index(name="Times Played")
            )
            counts = counts[counts["Times Played"] > 0]
            st.altair_chart(
                count_bar(counts, "Length", "", sort=BUCKET_ORDER),
                width="stretch",
            )
             
# -------------------------
# TAB 2: SETLIST LOOKUP
# -------------------------

elif st.session_state.active_tab == "Setlist Lookup":
    dank_sign("Setlist Lookup")

    performances = build_performances(df2)

    with st.expander("Filters", expanded=False):
        col1, col2 = st.columns(2)
        with col1:
            location_filter = st.selectbox(
                "By Location:",
                ["All"] + sorted(performances["Location"].dropna().unique().tolist()),
            )
        with col2:
            year_filter = st.selectbox(
                "By Year:",
                ["All"] + sorted(performances["Year"].dropna().unique().tolist(), reverse=True),
            )

    applied = [str(f) for f in (location_filter, year_filter) if f != "All"]
    if applied:
        st.caption("Filtered by: " + ", ".join(applied))

    mask = pd.Series(True, index=performances.index)
    if location_filter != "All":
        mask &= performances["Location"] == location_filter
    if year_filter != "All":
        mask &= performances["Year"] == year_filter

    unique_shows = (
        performances[mask]
        .drop_duplicates(subset="Show_Label")
        .sort_values("Date", ascending=False)["Show_Label"]
        .tolist()
    )
    # apply a button's pick before the selectbox is created
    if "pending_show_selection" in st.session_state:
        st.session_state.selected_show_widget = st.session_state.pop("pending_show_selection")
    if st.session_state.get("selected_show_widget") not in unique_shows:
        st.session_state.selected_show_widget = None

    selected_show = st.selectbox(
        "Hundreds of shows but one will do",
        unique_shows,
        index=None,
        placeholder="Type to search...",
        key="selected_show_widget",
    )
    st.session_state.selected_show = selected_show

    today_md = pd.Timestamp.now(tz="America/New_York").strftime("%m/%d")
    on_this_day = [s for s in unique_shows if s.startswith(today_md)]

    with st.container(key="btnrow_setlist"):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Random Show", width="stretch") and unique_shows:
                st.session_state.pending_show_selection = random.choice(unique_shows)
                st.rerun()
        with col2:
            if st.button("Random On This Day", width="stretch"):
                if on_this_day:
                    st.session_state.pending_show_selection = random.choice(on_this_day)
                    st.rerun()
                st.toast("No shows found on this date in past years.")
        with col3:
            if st.button("Clear Setlist", key="clear_setlists1", width="stretch"):
                st.session_state.pending_show_selection = None
                st.rerun()

    if selected_show:
        show_date, show_loc = selected_show.split(" — ", 1)
        hist = (
            performances[performances["Show_Label"] == selected_show]
            .sort_values("Track Number")
            .reset_index(drop=True)
        )

        # a row sharing its Duration with the next row is mid-segue
        segue = hist["Duration"].eq(hist["Duration"].shift(-1))
        first_of_chain = ~hist["Duration"].eq(hist["Duration"].shift())
        total_secs = int(hist.loc[first_of_chain, "Duration"].apply(parse_duration).sum())

        venue_sets, top_count, top_songs = venue_summary(df, show_loc)
        if len(top_songs) > 1:
            fav_value, fav_label = f"{len(top_songs)} tied", f"Venue Favorites ({top_count}x each)"
        else:
            fav_value, fav_label = top_songs[0], f"Venue Favorite ({top_count}x)"

        st.divider()
        dank_sign(f"{show_loc} — {show_date}")
        cards = [
            card_html(len(hist), "Tracks", accent=True),
            card_html(f"{total_secs // 60}:{total_secs % 60:02d}", "Total Time"),
            card_html(venue_sets, "Set at Venue" if venue_sets == 1 else "Sets at Venue"),
            card_html(html.escape(str(fav_value)), fav_label),
        ]
        st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

        # listen
        if "IA URL" in hist.columns and hist["IA URL"].notna().any():
            if st.button("🎧 Listen on DankApp", key=f"listen_btn_{selected_show}", width="stretch"):
                st.session_state["listen_show_select"] = selected_show
                st.session_state["listen_playlist_select"] = None
                st.session_state["player_mode"] = "setlist"
                st.switch_page("pages/listen.py")
        elif "OneDrive Share URL" in hist.columns and hist["OneDrive Share URL"].notna().any():
            st.link_button("☁️ Listen in OneDrive ↗",
                           hist["OneDrive Share URL"].dropna().iloc[0], width="stretch")

        # setlist table
        durations = hist["Duration"].where(~segue, "--")
        rows_html = []
        for num, title, dur, is_segue in zip(hist["Track Number"], hist["Title"], durations, segue):
            link = f'<a href="/stats?song={urllib.parse.quote(title, safe="")}" target="_self">{html.escape(title)}</a>'
            rows_html.append(
                f"<tr><td>{html.escape(str(num))}</td>"
                f"<td>{link}{' →' if is_segue else ''}</td>"
                f"<td>{html.escape(str(dur))}</td></tr>"
            )
        st.markdown(
            '<table class="setlist-table"><thead><tr>'
            "<th>#</th><th>Title</th><th>Duration</th>"
            f"</tr></thead><tbody>{''.join(rows_html)}</tbody></table>",
            unsafe_allow_html=True,
        )

# -------------------------
# TAB 3: SONG STATS
# -------------------------

elif st.session_state.active_tab == "Song Stats":
    dank_sign("Song Stats")

    t3_df, t3_stats = get_stats_df("song_stats_dw")

    # key -> (button label, table heading)
    SONG_STATS = {
        "most_played":  ("Most Played",  "Most Played Songs"),
        "longest_gap":  ("Longest Gaps", "Longest Historical Gap Between Plays"),
        "longest_jams": ("Longest Jams", "Longest Jams"),
        "song_streak":  ("Streaks",      "Active Setlist Streaks"),
    }
    active = st.session_state.get("song_active_stat")
    if active not in SONG_STATS:
        active = "most_played"          # sensible default, so the page isn't empty

    with st.container(key="tabs_songstats"):
        for col, (key, (label, _)) in zip(st.columns(len(SONG_STATS)), SONG_STATS.items()):
            with col:
                if st.button(label, key=f"songstat_{key}", width="stretch",
                             type="primary" if active == key else "secondary"):
                    st.session_state.song_active_stat = key
                    st.rerun()

    dank_hex(SONG_STATS[active][1])

    if active == "most_played":
        linked_table(
            most_played_table(t3_stats, t3_df),
            show_cols={"First Played": "First Location", "Last Played": "Last Location"},
        )

    elif active == "longest_gap":
        gap_df = longest_gaps(t3_df)
        if gap_df.empty:
            dank_hex("No gaps to show")
        else:
            gap_df.insert(0, "Rank", range(1, len(gap_df) + 1))
            linked_table(gap_df, show_cols={"From": "From Location", "To": "To Location"})

    elif active == "longest_jams":
        jams_df = long_jams(t3_df)
        if jams_df.empty:
            dank_hex("No jams over 18 minutes")
        else:
            jams_df.insert(0, "Rank", range(1, len(jams_df) + 1))
            linked_table(jams_df, song_col=None, show_col="Date", show_loc_col="Location")

    elif active == "song_streak":
        streaks = active_streaks(t3_df)
        if streaks.empty:
            dank_callout("No active streaks, man.")
        else:
            linked_table(ranked_table(streaks, sort_col="Active Streak"))
 
# -------------------------
# TAB 4: SETLIST STATS
# -------------------------

# -------------------------
# TAB 4: SETLIST STATS
# -------------------------

elif st.session_state.active_tab == "Setlist Stats":
    dank_sign("Setlist Stats")

    t3_df, t3_stats = get_stats_df("setlist_stats_dw")

    # key -> (button label, table heading)
    SETLIST_STATS = {
        "openers":         ("Openers",   "Most Common Openers"),
        "closers":         ("Closers",   "Most Common Closers"),
        "segues":          ("Segues",    "Most Common Segues"),
        "most_common_gig": ("At Gigs",   "Most Common at Gigs"),
        "heatmap":         ("Months",    "Activity by Month"),
        "length_graph":    ("Set Length", "Danktuary Studios Set Length"),
    }
    active = st.session_state.get("setlist_active_stat")
    if active not in SETLIST_STATS:
        active = "openers"

    with st.container(key="tabs_setstats"):
        for col, (key, (label, _)) in zip(st.columns(len(SETLIST_STATS)), SETLIST_STATS.items()):
            with col:
                if st.button(label, key=f"setstat_{key}", width="stretch",
                             type="primary" if active == key else "secondary"):
                    st.session_state.setlist_active_stat = key
                    st.rerun()

    dank_hex(SETLIST_STATS[active][1])

    if active == "openers":
        table = opener_counts(t3_df)
        table.insert(0, "Rank", range(1, len(table) + 1))
        linked_table(table)

    elif active == "closers":
        table = closer_counts(t3_df)
        table.insert(0, "Rank", range(1, len(table) + 1))
        linked_table(table)

    elif active == "segues":
        table = segue_counts(t3_df)
        if table.empty:
            dank_hex("No segues played 3+ times")
        else:
            table.insert(0, "Rank", range(1, len(table) + 1))
            linked_table(table, song_col=None)      # two songs per cell, so no single link

    elif active == "most_common_gig":
        table = gig_counts(t3_df)
        if table.empty:
            dank_hex("No gig recordings found")
        else:
            table.insert(0, "Rank", range(1, len(table) + 1))
            linked_table(table, show_cols={"Last Played": "Last Location"})

    elif active == "heatmap":
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        shows = t3_df.drop_duplicates(subset="Date")
        monthly = (
            shows.groupby(shows["Date"].dt.month).size()
            .reindex(range(1, 13), fill_value=0)
            .rename_axis("Month").reset_index(name="Shows")
        )
        monthly["Month Name"] = monthly["Month"].map(lambda m: month_names[m - 1])
        top = int(monthly["Shows"].max())

        chart = alt.Chart(monthly).mark_bar(
            cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#ffb81c"
        ).encode(
            x=alt.X("Month Name:O", sort=month_names, axis=alt.Axis(title=None, labelAngle=0)),
            y=alt.Y("Shows:Q",
                    scale=alt.Scale(domain=[0, top + 1], nice=False),
                    axis=alt.Axis(tickMinStep=1, tickCount=min(top + 1, 6), format="d", title="Shows")),
            tooltip=[alt.Tooltip("Month Name:O", title="Month"), alt.Tooltip("Shows:Q", title="Shows")],
        ).properties(height=250)
        st.altair_chart(dank_chart(chart), width="stretch")

    elif active == "length_graph":
        length_df = studio_lengths(t3_df)

        if length_df.empty:
            dank_hex("No qualifying Danktuary setlists (80+ min)")
        else:
            slope, intercept = np.polyfit(
                length_df["Date"].map(pd.Timestamp.toordinal), length_df["Total Minutes"], 1
            )
            chart_start = length_df["Date"].min()
            chart_end = length_df["Date"].max()          # end at the last real show
            trend_df = pd.DataFrame({
                "Date": [chart_start, chart_end],
                "Total Minutes": [slope * d.toordinal() + intercept for d in (chart_start, chart_end)],
            })
            trend_start, trend_end = trend_df["Total Minutes"]

            longest = length_df.loc[length_df["Total Minutes"].idxmax()]
            longest_df = pd.DataFrame([{
                "Date": longest["Date"], "Total Minutes": longest["Total Minutes"],
                "Label": f"Longest: {longest['Total Minutes']:.0f} min",
            }])

            y_vals = pd.concat([length_df["Total Minutes"], trend_df["Total Minutes"]])
            y_scale = alt.Scale(
                domain=[int(np.floor((y_vals.min() - 5) / 10) * 10),
                        int(np.ceil((y_vals.max() + 15) / 10) * 10)],
                nice=False, zero=False,
            )
            x_scale = alt.Scale(domain=[chart_start, chart_end], nice=False)

            quarter_starts = pd.date_range(
                start=chart_start.to_period("Q").start_time, end=chart_end, freq="QS"
            )
            x_axis = alt.Axis(
                title=None, values=list(quarter_starts), labelAngle=0, labelOverlap="greedy",
                labelExpr="'Q' + (floor(month(datum.value)/3)+1) + ' ' + year(datum.value)",
            )

            x = alt.X("Date:T", scale=x_scale)
            y = alt.Y("Total Minutes:Q", scale=y_scale)

            line = alt.Chart(length_df).mark_line(
                color="#ffb81c", point=alt.OverlayMarkDef(color="#ffb81c", size=30)
            ).encode(
                x=alt.X("Date:T", scale=x_scale, axis=x_axis),
                y=alt.Y("Total Minutes:Q", scale=y_scale,
                        axis=alt.Axis(title="Minutes", tickCount=5, format="d")),
                tooltip=[alt.Tooltip("Date:T", title="Date"),
                         alt.Tooltip("Total Minutes:Q", title="Minutes", format=".0f")],
            )
            trend = alt.Chart(trend_df).mark_line(color="#ff5a4a", strokeDash=[4, 4]).encode(x=x, y=y)
            peak = alt.Chart(longest_df).mark_point(color="#00FF00", size=90, filled=True).encode(x=x, y=y)
            peak_label = alt.Chart(longest_df).mark_text(
                align="right", dx=-8, dy=-10, fontSize=11, color="#f1ead8",
                font="Poppins", fontWeight=600,
            ).encode(x=x, y=y, text="Label:N")

            st.altair_chart(
                dank_chart((line + trend + peak + peak_label).properties(height=280)),
                width="stretch",
            )
            st.caption(
                f"📈 Trend: {trend_start:.0f} min → {trend_end:.0f} min  \n"
                f"🎧 Longest Set: {longest['Total Minutes']:.0f} min ({longest['Date']:%m/%d/%Y})"
            )
else:
    dank_callout("Select a tab, man.")

# -------------------------
# FOOTER
# -------------------------
st.divider()

if st.button("⬆ Back to top"):
    components.html("""
        <script>
        var doc = window.parent.document;
        var selectors = [
            'section.main',
            '.main',
            '[data-testid="stAppViewContainer"]',
            '[data-testid="stMain"]',
            '.stApp',
            'div[data-testid="stAppViewBlockContainer"]'
        ];
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