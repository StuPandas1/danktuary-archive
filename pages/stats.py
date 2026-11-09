import streamlit as st  # type: ignore
import streamlit.components.v1 as components  # type: ignore
import pandas as pd  # type: ignore
import altair as alt  # type: ignore
import numpy as np
from zoneinfo import ZoneInfo
from shared import (  # type: ignore
    load_data, build_filtered, find_closers, parse_duration, dank_theme, dank_footer, dank_sign,
    force_columns_horizontal, dank_chart, dank_hex, dank_callout, page_menu, dank_header,
    ranked_table, linked_table, click_table, sync_url, url_from_browser, slug_to_show,
    clean_title, times_played_mult, dead_weight_artists, dead_weight_year,
)

st.set_page_config(page_title="DankApp | Stats", page_icon="static/icon.png", layout="wide")
dank_theme()

SONG_PAGE = "pages/songs.py"
SHOW_PAGE = "pages/shows.py"

# Old shared links (/stats?song=... or /stats?show=...) now belong to the new pages.
_old_song = st.query_params.get("song")
_old_show = slug_to_show(st.query_params.get("show"))
if _old_song:
    st.session_state["pending_song"] = _old_song
    st.switch_page(SONG_PAGE)
if _old_show:
    st.session_state["pending_show"] = _old_show
    st.switch_page(SHOW_PAGE)

# -------------------------
# DATA
# -------------------------

df, song_stats, metadata, jam_metadata = load_data()
df = df[df["Take"] == 1]                      # every stat here is Take 1 only
min_year = int(df["Year"].min())
max_year = int(df["Year"].max())
today_naive = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).tz_localize(None).normalize()

# -------------------------
# CACHED HELPERS
# -------------------------

@st.cache_data(show_spinner=False)
def most_played_table(stats, d):
    t = (
        stats.sort_values("Times_Played", ascending=False)
        .assign(
            First_Played=lambda x: x["First_Played"].dt.strftime("%m/%d/%Y"),
            Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y"),
        )[["Title", "Times_Played", "First_Played", "Last_Played"]]
        .rename(columns={"Times_Played": "Times Played", "First_Played": "First Played",
                         "Last_Played": "Last Played"})
        .reset_index(drop=True)
    )
    locs = d.sort_values("Date").groupby("Title")["Location"].agg(["first", "last"])
    t["First Location"] = t["Title"].map(locs["first"])
    t["Last Location"] = t["Title"].map(locs["last"])
    t.insert(0, "Rank", range(1, len(t) + 1))
    return t

@st.cache_data(show_spinner=False)
def most_played_in_year(d, year):
    y = d[d["Date"].dt.year == year].sort_values("Date")
    if y.empty:
        return y
    return (
        y.groupby("Title")
        .agg(Plays=("Title", "size"), Last=("Date", "max"), Last_Location=("Location", "last"))
        .reset_index()
        .sort_values(["Plays", "Title"], ascending=[False, True])
        .assign(Last=lambda x: x["Last"].dt.strftime("%m/%d/%Y"))
        .rename(columns={"Plays": "Times Played", "Last": "Last Played", "Last_Location": "Last Location"})
        .reset_index(drop=True)
    )

@st.cache_data(show_spinner=False)
def recently_played(stats, d):
    latest = (d.sort_values(["Date", "Track Number"]).groupby("Title")
              .last().reset_index()[["Title", "Location"]])
    t = (
        stats.merge(latest, on="Title", how="left")
        .sort_values(["Last_Played", "Title"], ascending=[False, True])
        .assign(Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y"))
        .rename(columns={"Last_Played": "Last Played", "Times_Played": "Total Plays",
                         "Location": "Last Location"})
        [["Title", "Last Played", "Total Plays", "Last Location"]]
        .reset_index(drop=True)
    )
    t.insert(0, "Rank", range(1, len(t) + 1))          # rank always means "how recent"
    return t

@st.cache_data(show_spinner=False)
def bustout_table(stats, d, today):
    b = stats.copy()
    b["Days"] = (today - b["Last_Played"]).dt.days
    score = b["Days"] * (b["Times_Played"] ** times_played_mult)
    top = score.max()
    locs = d.sort_values("Date").groupby("Title")["Location"].last()
    return pd.DataFrame({
        "Title": b["Title"],
        "Days Since": b["Days"].astype(int),
        "Last Played": b["Last_Played"].dt.strftime("%m/%d/%Y"),
        "Times Played": b["Times_Played"],
        "Overdue Score": ((score / top) * 100).round(1) if top else 0.0,
        "Last Location": b["Title"].map(locs),
    })

@st.cache_data(show_spinner=False)
def longest_gaps(d):
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
def long_jams(d, min_secs=1080, single_only=False):
    d = d.sort_values(["Date", "Track Number"])
    new_chain = d["Date"].ne(d["Date"].shift()) | d["Duration"].ne(d["Duration"].shift())
    jams = (
        d.assign(_g=new_chain.cumsum()).groupby("_g")
        .agg(Date=("Date", "first"), Location=("Location", "first"),
             Songs=("Title", " -> ".join), Duration=("Duration", "first"),
             n=("Title", "size"))
    )
    if single_only:
        jams = jams[jams["n"] == 1]
    jams["secs"] = jams["Duration"].apply(parse_duration)
    jams = jams[jams["secs"] >= min_secs].sort_values("secs", ascending=False)
    jams["Date"] = jams["Date"].dt.strftime("%m/%d/%Y")
    return (jams.rename(columns={"Songs": "Song(s)"})
                .drop(columns=["secs", "n"]).reset_index(drop=True))

@st.cache_data(show_spinner=False)
def active_streaks(d):
    day = d["Date"].dt.normalize()
    dates = sorted(day.unique())
    present = pd.crosstab(d["Title"], day).reindex(columns=dates, fill_value=0).gt(0)
    streak = present.iloc[:, ::-1].astype(int).cumprod(axis=1).sum(axis=1)
    return streak[streak > 1].rename("Active Streak").reset_index()

@st.cache_data(show_spinner=False)
def practiced_not_live(d, d_all):
    live_titles = set(d_all.loc[d_all["Type"] == "live", "Title"])
    p = d[(d["Type"] == "practice") & ~d["Title"].isin(live_titles)].sort_values("Date")
    if p.empty:
        return p
    return (
        p.groupby("Title")
        .agg(Times=("Title", "size"), Last=("Date", "max"), Last_Location=("Location", "last"))
        .reset_index()
        .sort_values(["Times", "Title"], ascending=[False, True])
        .assign(Last=lambda x: x["Last"].dt.strftime("%m/%d/%Y"))
        .rename(columns={"Times": "Times Practiced", "Last": "Last Practiced",
                         "Last_Location": "Last Location"})
        .reset_index(drop=True)
    )

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
    d = d.sort_values(["Date", "Track Number"])
    nxt = d.groupby("Date")["Title"].shift(-1)
    pairs = (d["Title"] + "  →  " + nxt)[nxt.notna()]
    out = pairs.value_counts().rename_axis("Segue").reset_index(name="Times Played")
    return out[out["Times Played"] >= min_plays].reset_index(drop=True)

@st.cache_data(show_spinner=False)
def gig_counts(d):
    return (
        d[d["Type"] == "live"].sort_values("Date").groupby("Title")
        .agg(Times_Played=("Title", "count"), Last_Played=("Date", "max"), Last_Location=("Location", "last"))
        .reset_index()
        .sort_values("Times_Played", ascending=False)
        .assign(Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y"))
        .rename(columns={"Times_Played": "Times Played", "Last_Played": "Last Played",
                         "Last_Location": "Last Location"})
        .reset_index(drop=True)
    )

@st.cache_data(show_spinner=False)
def studio_lengths(d):
    s = d[d["Location"] == "Danktuary Studios"].sort_values(["Date", "Track Number"])
    s = s[~s["Duration"].eq(s.groupby("Date")["Duration"].shift())]
    mins = s["Duration"].apply(parse_duration).groupby(s["Date"]).sum().div(60)
    out = mins.rename("Total Minutes").reset_index()
    return out[out["Total Minutes"] >= 80].reset_index(drop=True)

def ranked(table):
    table = table.copy()
    table.insert(0, "Rank", range(1, len(table) + 1))
    return table

# -------------------------
# STAT RENDERERS: each takes (t_df, t_stats) and draws its own controls + table
# -------------------------

def stat_most_played(t_df, t_stats):
    years = sorted(t_df["Date"].dt.year.unique().tolist())
    options = ["All Time"] + years
    if st.session_state.get("stats_year_pick") not in options:
        st.session_state["stats_year_pick"] = "All Time"
    pick = st.select_slider("Year", options=options, key="stats_year_pick")

    if pick == "All Time":
        click_table(most_played_table(t_stats, t_df), key="tbl_mp", song_cols=("Title",),
                    show_cols={"First Played": "First Location", "Last Played": "Last Location"},
                    song_goto=SONG_PAGE, show_goto=SHOW_PAGE)
        return

    table = most_played_in_year(t_df, pick)
    if table.empty:
        dank_hex(f"No recordings in {pick}")
        return
    n = t_df.loc[t_df["Date"].dt.year == pick, "Date"].nunique()
    dank_hex(f"**{pick}**", f"{n} recording{'' if n == 1 else 's'}")
    click_table(ranked(table), key="tbl_year", song_cols=("Title",),
                show_cols={"Last Played": "Last Location"},
                song_goto=SONG_PAGE, show_goto=SHOW_PAGE)

def stat_recent(t_df, t_stats):
    sort = st.radio("Sort by:", ["Date", "Title"], horizontal=True, key="stats_recent_sort")
    table = recently_played(t_stats, t_df)
    if sort == "Title":
        table = table.sort_values("Title", key=lambda s: s.str.lower()).reset_index(drop=True)
    click_table(table, key="tbl_recent", song_cols=("Title",),
                show_cols={"Last Played": "Last Location"}, song_goto=SONG_PAGE, show_goto=SHOW_PAGE)

def stat_bustout(_t_df, _t_stats):
    # Bustouts default to Dead Weight only, so this stat has its own checkbox.
    dw = st.checkbox("Dead Weight Only", value=True, key="stats_bust_dw")
    if dw:
        b_df, b_stats = build_filtered(df, metadata, dead_weight_artists, (dead_weight_year, max_year))
    else:
        b_df, b_stats = build_filtered(df, metadata, [], (min_year, max_year))
    if b_stats.empty:
        dank_hex("No songs match")
        return
    sort = st.radio("Sort by:", ["Score", "Days Since"], horizontal=True, key="stats_bust_sort")
    table = bustout_table(b_stats, b_df, today_naive)
    table = (table.sort_values("Overdue Score" if sort == "Score" else "Days Since", ascending=False)
             .reset_index(drop=True))
    click_table(ranked(table), key="tbl_bust", song_cols=("Title",),
                show_cols={"Last Played": "Last Location"}, song_goto=SONG_PAGE, show_goto=SHOW_PAGE)

def stat_gaps(t_df, t_stats):
    gap_df = longest_gaps(t_df)
    if gap_df.empty:
        dank_hex("No gaps to show")
        return
    click_table(ranked(gap_df), key="tbl_gap", song_cols=("Title",),
                show_cols={"From": "From Location", "To": "To Location"},
                song_goto=SONG_PAGE, show_goto=SHOW_PAGE)

def stat_jams(t_df, t_stats):
    single = st.checkbox("Single tracks only (no segues)", key="stats_jams_single")
    jams_df = long_jams(t_df, single_only=single)
    if jams_df.empty:
        dank_hex("No single-track jams over 18 minutes" if single else "No jams over 18 minutes")
        return
    click_table(ranked(jams_df), key="tbl_jams", show_cols={"Date": "Location"}, show_goto=SHOW_PAGE)

def stat_streaks(t_df, t_stats):
    streaks = active_streaks(t_df)
    if streaks.empty:
        dank_callout("No active streaks, man.")
        return
    click_table(ranked_table(streaks, sort_col="Active Streak"), key="tbl_streak",
                song_cols=("Title",), song_goto=SONG_PAGE)

def stat_practice_only(t_df, t_stats):
    table = practiced_not_live(t_df, df)
    if table.empty:
        dank_hex("Everything we've practiced has been played live")
        return
    click_table(ranked(table), key="tbl_practice", song_cols=("Title",),
                show_cols={"Last Practiced": "Last Location"}, song_goto=SONG_PAGE, show_goto=SHOW_PAGE)

def stat_unplayed(_t_df, _t_stats):
    try:
        total = pd.read_csv("total_songs.csv").dropna(subset=["Title"])
        total["Title"] = total["Title"].apply(clean_title)
    except FileNotFoundError:
        dank_hex("total_songs.csv not found")
        return
    unplayed = (total[~total["Title"].isin(set(df["Title"].unique()))]
                .sort_values(["Title", "Artist"]).reset_index(drop=True))
    n = len(unplayed)
    dank_hex(f"**{n}** {'song' if n == 1 else 'songs'} to learn...")
    if n:
        linked_table(unplayed[["Title", "Artist"]].rename(columns={"Title": "Song Title"}), song_col=None)

def stat_openers(t_df, t_stats):
    click_table(ranked(opener_counts(t_df)), key="tbl_open", song_cols=("Title",), song_goto=SONG_PAGE)

def stat_closers(t_df, t_stats):
    click_table(ranked(closer_counts(t_df)), key="tbl_close", song_cols=("Title",), song_goto=SONG_PAGE)

def stat_segues(t_df, t_stats):
    table = segue_counts(t_df)
    if table.empty:
        dank_hex("No segues played 3+ times")
        return
    linked_table(ranked(table), song_col=None)      # two songs per cell, so nothing to open

def stat_gigs(t_df, t_stats):
    table = gig_counts(t_df)
    if table.empty:
        dank_hex("No gig recordings found")
        return
    click_table(ranked(table), key="tbl_gig", song_cols=("Title",),
                show_cols={"Last Played": "Last Location"}, song_goto=SONG_PAGE, show_goto=SHOW_PAGE)

def stat_months(t_df, t_stats):
    names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    shows = t_df.drop_duplicates(subset="Date")
    monthly = (shows.groupby(shows["Date"].dt.month).size()
               .reindex(range(1, 13), fill_value=0)
               .rename_axis("Month").reset_index(name="Shows"))
    monthly["Month Name"] = monthly["Month"].map(lambda m: names[m - 1])
    top = int(monthly["Shows"].max())
    chart = alt.Chart(monthly).mark_bar(
        cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#ffb81c"
    ).encode(
        x=alt.X("Month Name:O", sort=names, axis=alt.Axis(title=None, labelAngle=0)),
        y=alt.Y("Shows:Q", scale=alt.Scale(domain=[0, top + 1], nice=False),
                axis=alt.Axis(tickMinStep=1, tickCount=min(top + 1, 6), format="d", title="Shows")),
        tooltip=[alt.Tooltip("Month Name:O", title="Month"), alt.Tooltip("Shows:Q", title="Shows")],
    ).properties(height=250)
    st.altair_chart(dank_chart(chart), width="stretch")

def stat_set_length(t_df, t_stats):
    length_df = studio_lengths(t_df)
    if length_df.empty:
        dank_hex("No qualifying Danktuary setlists (80+ min)")
        return
    slope, intercept = np.polyfit(length_df["Date"].map(pd.Timestamp.toordinal), length_df["Total Minutes"], 1)
    start, end = length_df["Date"].min(), length_df["Date"].max()
    trend_df = pd.DataFrame({
        "Date": [start, end],
        "Total Minutes": [slope * ts.toordinal() + intercept for ts in (start, end)],
    })
    trend_start, trend_end = trend_df["Total Minutes"]
    longest = length_df.loc[length_df["Total Minutes"].idxmax()]
    longest_df = pd.DataFrame([{"Date": longest["Date"], "Total Minutes": longest["Total Minutes"],
                                "Label": f"Longest: {longest['Total Minutes']:.0f} min"}])

    y_vals = pd.concat([length_df["Total Minutes"], trend_df["Total Minutes"]])
    y_scale = alt.Scale(domain=[int(np.floor((y_vals.min() - 5) / 10) * 10),
                                int(np.ceil((y_vals.max() + 15) / 10) * 10)], nice=False, zero=False)
    x_scale = alt.Scale(domain=[start, end], nice=False)
    quarters = pd.date_range(start=start.to_period("Q").start_time, end=end, freq="QS")
    x_axis = alt.Axis(title=None, values=list(quarters), labelAngle=0, labelOverlap="greedy",
                      labelExpr="'Q' + (floor(month(datum.value)/3)+1) + ' ' + year(datum.value)")
    x = alt.X("Date:T", scale=x_scale)
    y = alt.Y("Total Minutes:Q", scale=y_scale)

    line = alt.Chart(length_df).mark_line(
        color="#ffb81c", point=alt.OverlayMarkDef(color="#ffb81c", size=30)
    ).encode(
        x=alt.X("Date:T", scale=x_scale, axis=x_axis),
        y=alt.Y("Total Minutes:Q", scale=y_scale, axis=alt.Axis(title="Minutes", tickCount=5, format="d")),
        tooltip=[alt.Tooltip("Date:T", title="Date"), alt.Tooltip("Total Minutes:Q", title="Minutes", format=".0f")],
    )
    trend = alt.Chart(trend_df).mark_line(color="#ff5a4a", strokeDash=[4, 4]).encode(x=x, y=y)
    peak = alt.Chart(longest_df).mark_point(color="#00FF00", size=90, filled=True).encode(x=x, y=y)
    peak_label = alt.Chart(longest_df).mark_text(
        align="right", dx=-8, dy=-10, fontSize=11, color="#f1ead8", font="Poppins", fontWeight=600,
    ).encode(x=x, y=y, text="Label:N")

    st.altair_chart(dank_chart((line + trend + peak + peak_label).properties(height=280)), width="stretch")
    st.caption(f"📈 Trend: {trend_start:.0f} min → {trend_end:.0f} min  \n"
               f"🎧 Longest Set: {longest['Total Minutes']:.0f} min ({longest['Date']:%m/%d/%Y})")

# -------------------------
# REGISTRY: key -> (group, dropdown label, heading, renderer, Dead Weight checkbox)
# Dead Weight: "global" = shared checkbox, "own" = stat has its own, "none" = not applicable
# -------------------------

GROUPS = ["Songs", "Setlists"]
STATS = {
    "most-played":     ("Songs", "Most Played", "Most Played Songs", stat_most_played, "global"),
    "recently-played": ("Songs", "Recently Played", "Most Recently Played", stat_recent, "global"),
    "bustout":         ("Songs", "Bustout Tracker", "Most Overdue Songs", stat_bustout, "own"),
    "longest-gaps":    ("Songs", "Longest Gaps", "Longest Historical Gap Between Plays", stat_gaps, "global"),
    "longest-jams":    ("Songs", "Longest Jams", "Longest Jams", stat_jams, "global"),
    "streaks":         ("Songs", "Streaks", "Active Setlist Streaks", stat_streaks, "global"),
    "practice-only":   ("Songs", "Practice Only", "Practiced But Never Played Live", stat_practice_only, "global"),
    "unplayed":        ("Songs", "Unplayed Songs", "Songs We Haven't Played", stat_unplayed, "none"),
    "openers":         ("Setlists", "Openers", "Most Common Openers", stat_openers, "global"),
    "closers":         ("Setlists", "Closers", "Most Common Closers", stat_closers, "global"),
    "segues":          ("Setlists", "Segues", "Most Common Segues", stat_segues, "global"),
    "at-gigs":         ("Setlists", "At Gigs", "Most Common at Gigs", stat_gigs, "global"),
    "months":          ("Setlists", "Months", "Activity by Month", stat_months, "global"),
    "set-length":      ("Setlists", "Set Length", "Danktuary Studios Set Length", stat_set_length, "global"),
}

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

dank_header(subtitle="Heady Stats")

# -------------------------
# PICKER (state is settled before the widgets are created)
# -------------------------

incoming = url_from_browser("stat")                  # shared link, back/forward
if incoming in STATS:
    st.session_state["stats_pick"] = incoming
    st.session_state["stats_group"] = STATS[incoming][0]

if incoming == "by-year":          # merged into Most Played
    incoming = "most-played"

st.session_state.setdefault("stats_pick", "most-played")
if st.session_state["stats_pick"] not in STATS:
    st.session_state["stats_pick"] = "most-played"
if st.session_state.get("stats_group") not in GROUPS:
    st.session_state["stats_group"] = STATS[st.session_state["stats_pick"]][0]
group = st.session_state["stats_group"]
if STATS[st.session_state["stats_pick"]][0] != group:        # switched groups: first stat of the new one
    st.session_state["stats_pick"] = next(k for k, v in STATS.items() if v[0] == group)

st.segmented_control("Group", GROUPS, key="stats_group", label_visibility="collapsed")
st.selectbox(
    "Pick a stat", [k for k, v in STATS.items() if v[0] == group],
    format_func=lambda k: STATS[k][1], key="stats_pick", label_visibility="collapsed",
)

pick = st.session_state["stats_pick"]
_, _, heading, render, dw_mode = STATS[pick]
sync_url(stat=pick, song=None, show=None, date=None)

dw_on = False
if dw_mode == "global":
    dw_on = st.checkbox("Dead Weight Only", key="stats_dw")

if dw_on:
    t_df, t_stats = build_filtered(df, metadata, dead_weight_artists, (dead_weight_year, max_year))
else:
    t_df, t_stats = build_filtered(df, metadata, [], (min_year, max_year))

st.divider()
dank_hex(heading)
render(t_df, t_stats)

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