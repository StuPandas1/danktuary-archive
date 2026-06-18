import streamlit as st # type: ignore
import subprocess
import pandas as pd # type: ignore
import random
import time
import os
import altair as alt
from urllib.parse import quote
import streamlit.components.v1 as components

times_played_mult = 1.3 # multiplier for how much weight to give times played in overdue score

# -------------------------
# DATA LOADING (CACHED)
# -------------------------

@st.cache_data
def load_data():
    df = pd.read_csv("band_archive.csv")
    song_stats = pd.read_csv("song_stats.csv")
    metadata = pd.read_csv("song_metadata.csv")
    jam_metadata = pd.read_csv("metadata_jam.csv")

    df["Date"] = pd.to_datetime(df["Date"])
    df["Year"] = df["Date"].dt.year

    song_stats = song_stats.merge(metadata, on="Title", how="left")

    return df, song_stats, metadata, jam_metadata

df, song_stats, metadata, jam_metadata = load_data()

min_year = int(df["Year"].min())
max_year = int(df["Year"].max())

dead_weight_artists = ["Grateful Dead", "Jerry Garcia Band", "The Band", "Little Feat", "Phish", "The Rolling Stones"]
dead_weight_year = 2022

# -------------------------
# SESSION STATE
# -------------------------

if "selected_song" not in st.session_state:
    st.session_state.selected_song = None

if "random_setlist" not in st.session_state:
    st.session_state.random_setlist = None

if "selected_show" not in st.session_state:
    st.session_state.selected_show = None

if "active_stat" not in st.session_state:
    st.session_state.active_stat = None

if "t1_year" not in st.session_state:
    st.session_state.t1_year = (min_year, max_year)

if "t3_year" not in st.session_state:  
    st.session_state.t3_year = (min_year, max_year)

# -------------------------
# DEAD WEIGHT CHECKBOX CALLBACKS
# -------------------------

def on_t1_dw_change():
    if st.session_state.t1_dead_weight:
        st.session_state.t1_artist = dead_weight_artists
        st.session_state.t1_year = (dead_weight_year, max_year)
    else:
        st.session_state.t1_artist = []
        st.session_state.t1_year = (min_year, max_year)

def on_t3_dw_change():
    if st.session_state.t3_dead_weight:
        st.session_state.t3_artist = dead_weight_artists
        st.session_state.t3_year = (dead_weight_year, max_year)
    else:
        st.session_state.t3_artist = []
        st.session_state.t3_year = (min_year, max_year)

# -------------------------
# HELPERS
# -------------------------

def build_filtered(artist_filter, year_range):
    filtered_df = df[
        (df["Year"] >= year_range[0]) &
        (df["Year"] <= year_range[1])
    ].copy()

    filtered_song_stats = filtered_df.groupby("Title").agg(
        Times_Played=("Title", "count"),
        First_Played=("Date", "min"),
        Last_Played=("Date", "max")
    ).reset_index()

    filtered_song_stats = filtered_song_stats.merge(metadata, on="Title", how="left")

    if artist_filter:
        filtered_song_stats = filtered_song_stats[
            filtered_song_stats["Artist"].isin(artist_filter)
        ]

    filtered_df = df[
        (df["Year"] >= year_range[0]) &
        (df["Year"] <= year_range[1]) &
        (df["Title"].isin(filtered_song_stats["Title"]))
    ].copy()

    filtered_song_stats["First_Played"] = pd.to_datetime(filtered_song_stats["First_Played"])
    filtered_song_stats["Last_Played"] = pd.to_datetime(filtered_song_stats["Last_Played"])

    return filtered_df, filtered_song_stats

def weighted_pick(series, used_songs):
    counts = series.value_counts()
    available = [
        (song, count)
        for song, count in counts.items()
        if song not in used_songs
    ]
    if not available:
        return None, None
    songs, weights = zip(*available)
    total = sum(weights)
    chosen = random.choices(songs, weights=weights, k=1)[0]
    odds = round((weights[songs.index(chosen)] / total) * 100, 1)
    return chosen, odds

def find_closers(source_df, allowed_titles=None):
    closers = []
    for date in source_df["Date"].unique():
        session = source_df[source_df["Date"] == date]
        if not session.empty:
            max_track = session["Track Number"].max()
            closer_row = session[session["Track Number"] == max_track]
            if not closer_row.empty:
                title = closer_row.iloc[0]["Title"]
                if allowed_titles is None or title in allowed_titles:
                    closers.append(title)
    return closers

def build_randomizer_pools(randomizer_df, jam_titles, today):
    jam_pool = randomizer_df[randomizer_df["Title"].isin(jam_titles)]["Title"].unique().tolist()
 
    recent_dates = (
        randomizer_df["Date"].drop_duplicates()
        .sort_values()
        .tail(10)
    )
    recent_pool = randomizer_df[randomizer_df["Date"].isin(recent_dates)]["Title"].unique().tolist()
 
    classics_pool = (
        randomizer_df.groupby("Title")
        .size()
        .reset_index(name="Times_Played")
    )
 
    bustout_pool = (
        randomizer_df.groupby("Title")["Date"]
        .max()
        .reset_index()
    )
    bustout_pool["Days_Since"] = (today - pd.to_datetime(bustout_pool["Date"])).dt.days
 
    opener_pool = randomizer_df[randomizer_df["Track Number"] == 1]["Title"].tolist()
 
    allowed_titles = set(randomizer_df["Title"].unique())
    closers = find_closers(df, allowed_titles)
 
    # build segue map: {song_a: {song_b: count}}
    segue_map = {}
    for date in randomizer_df["Date"].unique():
        session = randomizer_df[randomizer_df["Date"] == date].sort_values("Track Number")
        titles = session["Title"].tolist()
        for i in range(len(titles) - 1):
            a, b = titles[i], titles[i + 1]
            if a not in segue_map:
                segue_map[a] = {}
            segue_map[a][b] = segue_map[a].get(b, 0) + 1
 
    return jam_pool, recent_pool, classics_pool, bustout_pool, opener_pool, closers, segue_map
 
SEGUE_BOOST = 8.0  # multiplier for songs with historical segue from previous song
 
def apply_segue_boost(songs, weights, prev_song, segue_map):
    if prev_song is None or prev_song not in segue_map:
        return weights
    segues = segue_map[prev_song]
    return [
        w * SEGUE_BOOST if songs[i] in segues else w
        for i, w in enumerate(weights)
    ]
 
def pick_by_kind(kind, pools, used_songs, improv_titles, prev_song=None):
    jam_pool, recent_pool, classics_pool, bustout_pool, opener_pool, closer_pool, segue_map = pools
 
    if kind == "Opener":
        song, odds = weighted_pick(pd.Series(opener_pool), used_songs)
    elif kind == "Jam":
        available = [s for s in jam_pool if s not in used_songs]
        if not available:
            return None, None
        weights = [1.0] * len(available)
        weights = apply_segue_boost(available, weights, prev_song, segue_map)
        total = sum(weights)
        song = random.choices(available, weights=weights, k=1)[0]
        odds = round((weights[available.index(song)] / total) * 100, 1)
    elif kind == "Recent":
        available = [s for s in recent_pool if s not in used_songs]
        if not available:
            return None, None
        weights = [1.0] * len(available)
        weights = apply_segue_boost(available, weights, prev_song, segue_map)
        total = sum(weights)
        song = random.choices(available, weights=weights, k=1)[0]
        odds = round((weights[available.index(song)] / total) * 100, 1)
    elif kind == "Classic":
        available = classics_pool[~classics_pool["Title"].isin(used_songs)]
        if available.empty:
            return None, None
        songs = available["Title"].tolist()
        weights = available["Times_Played"].tolist()
        weights = apply_segue_boost(songs, weights, prev_song, segue_map)
        total = sum(weights)
        song = random.choices(songs, weights=weights, k=1)[0]
        odds = round((weights[songs.index(song)] / total) * 100, 1)
    elif kind == "Bustout":
        available = bustout_pool[~bustout_pool["Title"].isin(used_songs)]
        if available.empty:
            return None, None
        songs = available["Title"].tolist()
        weights = available["Days_Since"].tolist()
        weights = apply_segue_boost(songs, weights, prev_song, segue_map)
        total = sum(weights)
        song = random.choices(songs, weights=weights, k=1)[0]
        odds = round((weights[songs.index(song)] / total) * 100, 1)
    elif kind == "Closer":
        available = [s for s in closer_pool if s not in used_songs and s not in improv_titles]
        if not available:
            return None, None
        weights = [1.0] * len(available)
        weights = apply_segue_boost(available, weights, prev_song, segue_map)
        total = sum(weights)
        song = random.choices(available, weights=weights, k=1)[0]
        odds = round((weights[available.index(song)] / total) * 100, 1)
    else:
        return None, None
 
    return song, odds
 
def generate_setlist(num_songs, randomizer_df, jam_titles, improv_titles, today):
    pools = build_randomizer_pools(randomizer_df, jam_titles, today)
    used_songs = set()
    setlist = []
 
    middle_count = num_songs - 2
    middle_kinds = []
 
    middle_kinds.append("Jam")
    if middle_count >= 3:
        middle_kinds.append("Jam")
    kind_pool = ["Recent"] * 4 + ["Classic"] * 2 + ["Bustout"] * 2
    while len(middle_kinds) < middle_count:
        middle_kinds.append(random.choice(kind_pool))
    random.shuffle(middle_kinds)
 
    kinds = ["Opener"] + middle_kinds + ["Closer"]
 
    prev_song = None
    for i, kind in enumerate(kinds):
        song, odds = pick_by_kind(kind, pools, used_songs, improv_titles, prev_song)
        if song:
            used_songs.add(song)
            setlist.append({
                "#": i + 1,
                "Title": song,
                "Odds": f"{odds}%" if odds else "N/A",
                "Locked": False
            })
            prev_song = song
 
    return pd.DataFrame(setlist)

def local_path_to_onedrive_url(local_path):
    marker = "OneDrive\\LoveDeep"
    idx = local_path.find(marker)
    if idx == -1:
        return None
    relative = local_path[idx + len("OneDrive\\"):]
    relative = relative.replace("\\", "/")
    onedrive_path = f"/personal/436f797b4dd480a3/Documents/{relative}".rstrip("/")
    encoded_path = quote(onedrive_path, safe="")
    viewid = "5df66b5e-e8a6-4d4e-a4a3-babd050c831a"
    return f"https://onedrive.live.com/?id={encoded_path}&viewid={viewid}&view=0" 

def parse_duration(d):
    try:
        parts = str(d).split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return int(parts[0]) * 60 + int(parts[1])
    except:
        return 0
    
# -------------------------
# HEADER SECTION
# -------------------------

st.markdown("## DankApp: The Dankest App In Town")
st.markdown("---")

today_md = pd.Timestamp.today().strftime("%m/%d")
on_this_day_df = df[df["Date"].dt.strftime("%m/%d") == today_md].copy()
on_this_day_dates = sorted(on_this_day_df["Date"].unique())

if on_this_day_dates:
    st.markdown(f"##### **Today is {pd.Timestamp.today().day_name()}, {today_md}. On this day, we have {len(on_this_day_dates)} {'recording' if len(on_this_day_dates) == 1 else 'recordings'} in the archive:**")
    cols = st.columns(len(on_this_day_dates))
    for i, date in enumerate(on_this_day_dates):
        date_str = pd.Timestamp(date).strftime("%m/%d/%Y")
        location = on_this_day_df[on_this_day_df["Date"] == date]["Location"].iloc[0]
        label = f"{date_str} — {location}"

        with cols[i]:
            if st.button(label, key=f"otd_{date_str}"):
                st.session_state.selected_show = label
                if "selected_show_widget" in st.session_state:
                    del st.session_state["selected_show_widget"]
                st.session_state.jump_to_tab2 = True
else:
    st.markdown(f"##### **Today is {pd.Timestamp.today().day_name()}, {today_md}. No recordings found on this day. Maybe you should jam today, eh?**")

##Add a random fun fact generator here

st.markdown("---")

total_secs_all = df["Duration"].apply(parse_duration).sum()
total_days = total_secs_all // 86400
total_hours_remainder = (total_secs_all % 86400) // 3600
total_mins_remainder = (total_secs_all % 3600) // 60
longest_jam_duration = df["Duration"].apply(parse_duration).max()
longest_mins = longest_jam_duration // 60
longest_secs = longest_jam_duration % 60

with st.expander("Heady Stats Dashboard", expanded=True):

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric("Total Recordings", df["Date"].nunique())
        st.metric("Total Songs Played", len(df))

    with col2:
        st.metric("Total Gigs", df[df["Type"] == "live"]["Date"].nunique())
        st.metric("Unique Songs", df["Title"].nunique())

    with col3:
        st.metric("Total Time Played", f"{total_days}d {total_hours_remainder}h {total_mins_remainder}m")
        st.metric("Most Played", f"{df["Title"].value_counts().idxmax()} ({df["Title"].value_counts().max()})")

    with col4:
        st.metric("Days Since Last Played", (pd.Timestamp.today() - df["Date"].max()).days)
        st.metric("Longest Track", f"{longest_mins}:{longest_secs:02d}")

st.divider()

st.markdown("##### Ready to explore the archives? Check out the tabs below.")

st.markdown("""
<style>
.stTabs [data-baseweb="tab"] p {
    font-size: 17px !important;
    font-weight: 450 !important;
}
</style>
""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["Song Search", "Setlist Lookup", "Statistics", "Dead Weight Setlist Randomizer"])

if st.session_state.get("jump_to_tab2"):
    components.html("""
        <script>
        var tabs = window.parent.document.querySelectorAll('.stTabs [data-baseweb="tab"]');
        if (tabs.length > 1) { tabs[1].click(); }
        </script>
    """, height=0)
    st.session_state.jump_to_tab2 = False
    
# -------------------------
# TAB 1: SONG SEARCH
# -------------------------
 
with tab1:
    st.markdown("#### Song Search")
 
    with st.expander("Filters", expanded=True):
        st.checkbox("Dead Weight Only", key="t1_dead_weight", on_change=on_t1_dw_change)
 
        t1_artist = st.multiselect(
            "By Artist:",
            sorted(song_stats["Artist"].dropna().unique()),
            key="t1_artist"
        )
        t1_year = st.slider(
            "By Year:",
            min_year, max_year,
            key="t1_year"
        )
 
    t1_df, t1_stats = build_filtered(t1_artist, t1_year)
 
    search_song = st.selectbox(
        "Get shown the light...",
        sorted(t1_stats["Title"].unique()),
        index=None,
        placeholder="Type to search..."
    )
 
    col1, col2, col3 = st.columns(3)
 
    with col1:
        if st.button("Load Song History"):
            st.session_state.selected_song = search_song
 
    with col2:
        if st.button("Random Song"):
            st.session_state.selected_song = random.choice(sorted(t1_stats["Title"].unique()))
 
    with col3:
        if st.button("Clear Song History"):
            st.session_state.selected_song = None
            st.rerun()
 
    selected_song = st.session_state.selected_song
 
    if selected_song:
 
        matching_stats = t1_stats[t1_stats["Title"] == selected_song]
        performances = df[df["Title"] == selected_song].sort_values("Date", ascending=False)
 
        if not matching_stats.empty:
            stats = matching_stats.iloc[0]
 
            st.subheader(selected_song)
            times = stats['Times_Played']
            st.write(f"**Between {stats['First_Played'].year} and {stats['Last_Played'].year},** \"{selected_song}\" was played **{times}** {'time.' if times == 1 else 'times.'}")
            st.write(f"First played: **{stats['First_Played'].strftime('%m/%d/%Y')}**")
            days_ago = (pd.Timestamp.today() - stats['Last_Played']).days
            st.write(f"Last played: **{stats['Last_Played'].strftime('%m/%d/%Y')}**, or **{days_ago}** {'day ago.' if days_ago == 1 else 'days ago.'}")
 
            true_debut = df[df["Title"] == selected_song]["Date"].min()
            total_shows_since_debut = df[df["Date"] >= true_debut]["Date"].nunique()
            shows_played = df[(df["Title"] == selected_song) & (df["Date"] >= true_debut)]["Date"].nunique()
            pct = round((shows_played / total_shows_since_debut) * 100, 1)
            st.write(f"Since {stats['First_Played'].strftime('%m/%d/%Y')}, **\"{selected_song}\"** has been played in **{pct}%** of setlists.")
 
 
        with st.expander("Graph By Year (All Time)", expanded=False):
            yearly_counts = (
                performances.groupby(performances["Date"].dt.year)
                .size()
                .reset_index(name="Times Played")
            ).rename(columns={"Date": "Year"})
 
            all_years = pd.DataFrame({"Year": range(min_year, max_year + 1)})
 
            yearly_counts = (
                all_years
                .merge(yearly_counts, on="Year", how="left")
                .fillna(0)
            )
            yearly_counts["Times Played"] = yearly_counts["Times Played"].astype(int)
            yearly_counts["Year"] = yearly_counts["Year"].astype(str)
 
            chart = alt.Chart(yearly_counts).mark_bar(
                cornerRadiusTopLeft=4,
                cornerRadiusTopRight=4,
                color="#4a9eff"
            ).encode(
                x=alt.X("Year:O", axis=alt.Axis(labelAngle=0, title=None)),
                y=alt.Y("Times Played:Q", axis=alt.Axis(tickMinStep=1, title="Times Played"), scale=alt.Scale(domain=[0, yearly_counts["Times Played"].max() + 1])),
                tooltip=[
                    alt.Tooltip("Year:O", title="Year"),
                    alt.Tooltip("Times Played:Q", title="Times Played")
                ]
            ).properties(
                height=250,
                title=alt.TitleParams(selected_song, anchor="middle")
            ).configure_axis(
                grid=False,
                labelColor="#888",
                tickColor="#888"
            ).configure_view(
                strokeWidth=0
            )
 
            st.altair_chart(chart, width='stretch')
 
        with st.expander("Performance History (All Time)", expanded=False):
            performances["Gap Since Previous"] = (
                performances["Date"].diff().dt.days
            ).fillna(0).astype(int) * -1
 
            # detect segues: check if adjacent tracks in same show share duration
            segue_labels = []
            for idx, row in performances.iterrows():
                date = row["Date"]
                track = row["Track Number"]
                duration = row["Duration"]
 
                session = df[(df["Date"] == date)].sort_values("Track Number")
                tracks = session["Track Number"].tolist()
                durations = session["Duration"].tolist()
                titles = session["Title"].tolist()
 
                pos = tracks.index(track) if track in tracks else -1
                label = ""
 
                if pos >= 0:
                    prev_same = pos > 0 and durations[pos - 1] == duration
                    next_same = pos < len(durations) - 1 and durations[pos + 1] == duration
 
                    if prev_same and next_same:
                        label = f"{titles[pos-1]} -> {titles[pos]} -> {titles[pos+1]}"
                    elif prev_same:
                        label = f"{titles[pos-1]} -> {titles[pos]}"
                    elif next_same:
                        label = f"{titles[pos]} -> {titles[pos+1]}"
                    else:
                        label = titles[pos]
 
                segue_labels.append(label)
 
            performances = performances.copy()
            performances["Segue"] = segue_labels
 
            df_display = performances.assign(
                Show=lambda x: x["Date"].dt.strftime("%m/%d/%Y") + " — " + x["Location"]
            )[["Show", "Segue", "Duration", "Gap Since Previous"]]
 
            st.dataframe(
                df_display,
                column_config={
                    "Show": st.column_config.TextColumn("Show", width="medium"),
                    "Duration": st.column_config.TextColumn("Duration", width="small"),
                    "Segue": st.column_config.TextColumn("Segue", width="large"),
                    "Gap Since Previous": st.column_config.NumberColumn("Gap Since Previous", width="small")
                },
                width="stretch",
                hide_index=True,
            )
        with st.expander("Graph By Length ", expanded=False):
            def parse_duration(d):
                try:
                    parts = str(d).split(":")
                    return int(parts[0]) * 60 + int(parts[1])
                except:
                    return 0

            def bucket_duration(secs):
                if secs < 120:   return "0–2 min"
                elif secs < 240: return "2–4 min"
                elif secs < 360: return "4–6 min"
                elif secs < 480: return "6–8 min"
                elif secs < 600: return "8–10 min"
                elif secs < 720: return "10–12 min"
                elif secs < 840: return "12–14 min"
                elif secs < 960: return "14–16 min"
                elif secs < 1080: return "16–18 min"
                elif secs < 1200: return "18–20 min"
                else:             return "20+ min"

            bucket_order = [
                "0–2 min", "2–4 min", "4–6 min", "6–8 min", "8–10 min",
                "10–12 min", "12–14 min", "14–16 min", "16–18 min", "18–20 min", "20+ min"
            ]

            perf_durations = performances["Duration"].dropna()
            buckets = perf_durations.apply(lambda d: bucket_duration(parse_duration(d)))

            bucket_counts = (
                buckets.value_counts()
                .reindex(bucket_order, fill_value=0)
                .reset_index()
            )
            bucket_counts.columns = ["Length", "Times Played"]
            bucket_counts = bucket_counts[bucket_counts["Times Played"] > 0]  # drop empty buckets

            length_chart = alt.Chart(bucket_counts).mark_bar(
                cornerRadiusTopLeft=4,
                cornerRadiusTopRight=4,
                color="#4a9eff"
            ).encode(
                x=alt.X("Length:O", sort=bucket_order, axis=alt.Axis(labelAngle=0, title=None)),
                y=alt.Y("Times Played:Q", axis=alt.Axis(tickMinStep=1, title="Times Played")),
                tooltip=[
                    alt.Tooltip("Length:O", title="Length"),
                    alt.Tooltip("Times Played:Q", title="Times Played")
                ]
            ).properties(
                height=250,
                title=alt.TitleParams(selected_song, anchor="middle")
            ).configure_axis(
                grid=False,
                labelColor="#888",
                tickColor="#888"
            ).configure_view(
                strokeWidth=0
            )

            st.altair_chart(length_chart, width='stretch')
    
# -------------------------
# TAB 2: SETLIST LOOKUP
# -------------------------
 
with tab2:
    st.markdown("#### Setlist Lookup")
 
    performances = df.copy()
    performances["Show_Label"] = (
        performances["Date"].dt.strftime("%m/%d/%Y")
        + " — "
        + performances["Location"]
    )
 
    type_order = {"live": 0, "trip": 1, "practice": 2}
    performances["Type_Order"] = performances["Type"].map(type_order).fillna(3)
 
    col1, col2 = st.columns(2)
 
    with col1: #location filter
        location_filter = st.selectbox(
            "By Location:",
            ["All"] + sorted(performances["Location"].dropna().unique().tolist()),
            index=0
        )
 
    with col2: # year filter
        year_filter = st.selectbox(
            "By Year:",
            ["All"] + sorted(performances["Year"].dropna().unique().tolist(), reverse=True),
            index=0
        )
 
    filtered_performances = performances.copy()
    if location_filter != "All":
        filtered_performances = filtered_performances[
            filtered_performances["Location"] == location_filter
        ]
    if year_filter != "All":
        filtered_performances = filtered_performances[
            filtered_performances["Year"] == year_filter
        ]
 
    unique_shows = (
        filtered_performances.drop_duplicates(subset="Show_Label")
        .sort_values(["Type_Order", "Date"], ascending=[True, False])["Show_Label"]
        .values
    )
 
    selected_show = st.selectbox(
        "Hundreds of shows but one will do",
        unique_shows,
        index=None,
        placeholder="Type to search...",
        key="selected_show_widget"
    )
 
    col1, col2, col3 = st.columns(3)
 
    with col1:
        if st.button("Random Show"):
            surprise = random.choice(unique_shows)
            st.session_state.selected_show = surprise
            if "selected_show_widget" in st.session_state:
                del st.session_state["selected_show_widget"]
            st.rerun()
 
    with col2:
        today_md = pd.Timestamp.today().strftime("%m/%d")
        on_this_day = [s for s in unique_shows if s.startswith(today_md)]
        if st.button("Random On This Day"):
            if on_this_day:
                st.session_state.selected_show = random.choice(on_this_day)
                if "selected_show_widget" in st.session_state:
                    del st.session_state["selected_show_widget"]
                st.rerun()
            else:
                st.toast("No shows found on this date in past years.")
 
    with col3:
        if st.button("Clear Setlist", key="clear_setlists1"):
            st.session_state.selected_show = None
            if "selected_show_widget" in st.session_state:
                del st.session_state["selected_show_widget"]
            st.rerun()
 
    if selected_show:
        st.session_state.selected_show = selected_show
 
    if st.session_state.selected_show:
        selected_label = st.session_state.selected_show
 
        historical_setlist = performances[
            performances["Show_Label"] == selected_label
        ].sort_values("Track Number")
 
        selected_date_str = selected_label.split(" — ")[0]
        selected_location = selected_label.split(" — ")[1]
 
        venue_shows = performances[performances["Location"] == selected_location]["Date"].nunique()
        venue_counts = performances[performances["Location"] == selected_location]["Title"].value_counts()
        most_common_count = venue_counts.max()
        tied_songs = venue_counts[venue_counts == most_common_count]

        deduped = historical_setlist.copy().reset_index(drop=True)
        deduped = deduped[
            (deduped["Duration"] != deduped["Duration"].shift(1))
        ]
        total_secs = deduped["Duration"].apply(parse_duration).sum()
        total_mins = total_secs // 60
        total_secs_remainder = total_secs % 60

        st.write(f"**{selected_location} - {selected_date_str}**")
        st.write(f"Total setlist duration: **{total_mins}:{total_secs_remainder:02d}**")
        st.write(f"There {'is' if venue_shows == 1 else 'are'} **{venue_shows}** {'set' if venue_shows == 1 else 'sets'} at {selected_location}.")
 
        if len(tied_songs) > 1:
            st.write(f"There are **{len(tied_songs)}** songs tied for most commonly played at {selected_location}, each played **{most_common_count}** {'time.' if most_common_count == 1 else 'times.'}")
        else:
            most_common_at_venue = tied_songs.idxmax()
            st.write(f"The most commonly played song at {selected_location} is **\"{most_common_at_venue}\"**, played **{most_common_count}** {'time.' if most_common_count == 1 else 'times.'}")

        sample_filepath = historical_setlist["File Path"].dropna().iloc[0] if not historical_setlist["File Path"].dropna().empty else None

        if sample_filepath:
            folder_path = os.path.dirname(sample_filepath)
            onedrive_url = local_path_to_onedrive_url(folder_path)
            if onedrive_url:
                st.markdown(f"[Listen in OneDrive ↗]({onedrive_url})")

        display_setlist = historical_setlist[["Track Number", "Title", "Duration"]].rename(
            columns={"Track Number": "Number"}
        ).copy().reset_index(drop=True)
 
        segue_indices = set()
        for i in range(len(display_setlist) - 1):
            if display_setlist.at[i, "Duration"] == display_setlist.at[i + 1, "Duration"]:
                display_setlist.at[i, "Title"] = display_setlist.at[i, "Title"] + " ->"
                segue_indices.add(i + 1)  # only blank the song being segued INTO

        for i in segue_indices:
            display_setlist.at[i, "Duration"] = "---"
 
        st.dataframe(
            display_setlist,
            hide_index=True,
            width='stretch',
            height=len(display_setlist) * 35 + 38,
            column_config={
                "Number": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
                "Duration": st.column_config.TextColumn(width="small")
            }
        )

# -------------------------
# TAB 3: STATISTICS
# -------------------------
 
with tab3:
    st.markdown("#### Statistics")
 
    with st.expander("Filters", expanded=True):
        st.checkbox("Dead Weight Only", key="t3_dead_weight", on_change=on_t3_dw_change)
 
        t3_artist = st.multiselect(
            "By Artist:",
            sorted(song_stats["Artist"].dropna().unique()),
            key="t3_artist"
        )
        t3_year = st.slider(
            "By Year:",
            min_year, max_year,
            key="t3_year"
        )
 
    t3_df, t3_stats = build_filtered(t3_artist, t3_year)
 
    with st.expander("Song Stats", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Most Overdue"):
                st.session_state.active_stat = "bustouts"
            if st.button("Most Played"):
                st.session_state.active_stat = "most_played"
        with col2:
            if st.button("Most Recently Played"):
                st.session_state.active_stat = "recent"
            if st.button("Longest Historical Gap"):
                st.session_state.active_stat = "longest_gap"
        with col3:
            if st.button("Active Streaks"):
                st.session_state.active_stat = "consecutive"
            if st.button("Longest Jams"):
                st.session_state.active_stat = "longest_jams"
 
    with st.expander("Setlist Stats", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Most Common Openers"):
                st.session_state.active_stat = "openers"
            if st.button("Activity Heatmap"):
                st.session_state.active_stat = "heatmap"
        with col2:
            if st.button("Most Common Closers"):
                st.session_state.active_stat = "closers"
            if st.button("Most Common At Gigs"):
                st.session_state.active_stat = "most_common_gig"
        with col3:
            if st.button("Most Common Segues"):
                st.session_state.active_stat = "segues"
 
    active = st.session_state.get("active_stat")
 
    if active == "bustouts":
 
        today = pd.Timestamp.today()
        bustouts = t3_stats.copy()
        bustouts["Days_Since_Played"] = (today - bustouts["Last_Played"]).dt.days
        bustouts["Overdue_Score"] = (
            bustouts["Days_Since_Played"]
            * (bustouts["Times_Played"] ** times_played_mult)
        )
        bustouts = bustouts.sort_values("Overdue_Score", ascending=False)
        bustouts["Overdue_Score"] = bustouts["Overdue_Score"].round(1)
        max_score = bustouts["Overdue_Score"].max()
        bustouts["Overdue_Score_Normalized"] = (
            (bustouts["Overdue_Score"] / max_score) * 100
        ).round(1)
 
        st.subheader("Most Overdue Songs")
        st.dataframe(
            bustouts.assign(
                Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y")
            )[[
                "Title", "Days_Since_Played", "Times_Played", "Overdue_Score_Normalized"
            ]].rename(columns={
                "Days_Since_Played": "Days Since Played",
                "Times_Played": "Times Played",
                "Overdue_Score_Normalized": "Overdue Score (Normalized)"
            }),
            width="stretch",
            hide_index=True
        )
 
    elif active == "most_played":
 
        most_played = t3_stats.sort_values("Times_Played", ascending=False)
        most_played_display = (
            most_played.assign(
                First_Played=lambda x: x["First_Played"].dt.strftime("%m/%d/%Y"),
                Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y")
            )[[
                "Title", "Times_Played", "First_Played", "Last_Played"
            ]].rename(columns={
                "Times_Played": "Times Played",
                "First_Played": "First Played",
                "Last_Played": "Last Played"
            })
        )
        most_played_display.insert(0, "Rank", range(1, len(most_played_display) + 1))
 
        st.subheader("Most Played Songs")
        st.dataframe(
            most_played_display,
            width="stretch",
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small")
            }
        )
 
    elif active == "recent":
 
        recent = t3_stats.sort_values("Last_Played", ascending=False)
        recent_display = (
            recent.assign(
                Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y")
            )[[
                "Title", "Last_Played", "Times_Played"
            ]].rename(columns={
                "Last_Played": "Last Played",
                "Times_Played": "Times Played"
            })
        )
        recent_display.insert(0, "Rank", range(1, len(recent_display) + 1))
 
        st.subheader("Most Recently Played")
        st.dataframe(
            recent_display,
            width="stretch",
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
            }
        )
 
    elif active == "longest_gap":
 
        all_dates = sorted(t3_df["Date"].unique())
        date_index = {date: i for i, date in enumerate(all_dates)}
 
        records = []
        for title in t3_df["Title"].unique():
            song_dates = sorted(t3_df[t3_df["Title"] == title]["Date"].unique())
            if len(song_dates) > 1:
                max_gap = 0
                best_from = None
                best_to = None
                for i in range(1, len(song_dates)):
                    gap = date_index[song_dates[i]] - date_index[song_dates[i - 1]] - 1
                    if gap > max_gap:
                        max_gap = gap
                        best_from = song_dates[i - 1]
                        best_to = song_dates[i]
                if best_from is not None:
                    records.append({
                        "Title": title,
                        "Longest Gap (Sets)": max_gap,
                        "From": pd.Timestamp(best_from).strftime("%m/%d/%Y"),
                        "To": pd.Timestamp(best_to).strftime("%m/%d/%Y")
                    })
 
        if records:
            gap_df = (
                pd.DataFrame(records)
                .sort_values("Longest Gap (Sets)", ascending=False)
                .reset_index(drop=True)
            )
            gap_df.insert(0, "Rank", range(1, len(gap_df) + 1))
 
            st.subheader("Longest Historical Gap Between Plays")
            st.dataframe(
                gap_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Rank": st.column_config.NumberColumn(width="small"),
                    "Title": st.column_config.TextColumn(width="large"),
                    "Longest Gap (Sets)": st.column_config.NumberColumn(width="small"),
                    "From": st.column_config.TextColumn(width="small"),
                    "To": st.column_config.TextColumn(width="small"),
                }
            )
        else:
            st.subheader("Longest Historical Gap Between Plays")            
            st.write("No gaps found.")
 
    elif active == "consecutive":

        all_dates = sorted(df["Date"].dt.normalize().unique())
        records = []
        for title in t3_df["Title"].unique():
            song_dates = set(t3_df[t3_df["Title"] == title]["Date"].dt.normalize().unique())
            current_streak = 0
            for date in all_dates:
                if date in song_dates:
                    current_streak += 1
                else:
                    current_streak = 0
            if current_streak > 1:
                records.append({"Title": title, "Active Streak": current_streak})

        if records:
            consec_df = (
                pd.DataFrame(records)
                .sort_values("Active Streak", ascending=False)
                .reset_index(drop=True)
            )
            consec_df.insert(0, "Rank", range(1, len(consec_df) + 1))

            st.subheader("Active Setlist Streaks")
            st.dataframe(
                consec_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Rank": st.column_config.NumberColumn(width="small"),
                    "Title": st.column_config.TextColumn(width="large"),
                    "Active Streak": st.column_config.NumberColumn(width="small")
                }
            )
        else:
            st.subheader("Active Setlist Streaks")
            st.write("No active streaks.")
            
    elif active == "openers":
 
        openers = t3_df[t3_df["Track Number"] == 1]
        opener_counts = (
            openers.groupby("Title")
            .size()
            .reset_index(name="Times Opened")
            .sort_values("Times Opened", ascending=False)
        )
        opener_counts.insert(0, "Rank", range(1, len(opener_counts) + 1))
 
        st.subheader("Most Common Openers")
        st.dataframe(
            opener_counts,
            width="stretch",
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
                "Times Opened": st.column_config.NumberColumn(width="small")
            }
        )
 
    elif active == "closers":
 
        year_filtered_df = df[
            (df["Year"] >= t3_year[0]) &
            (df["Year"] <= t3_year[1])
        ]
        allowed_titles = set(t3_df["Title"].unique())
        closers = find_closers(year_filtered_df, allowed_titles)
 
        closer_counts = (
            pd.Series(closers)
            .value_counts()
            .reset_index()
        )
        closer_counts.columns = ["Title", "Times Closed"]
        closer_counts.insert(0, "Rank", range(1, len(closer_counts) + 1))
 
        st.subheader("Most Common Closers")
        st.dataframe(
            closer_counts,
            width="stretch",
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
                "Times Closed": st.column_config.NumberColumn(width="small")
            }
        )
 
    elif active == "segues":
 
        segues = []
        for date in t3_df["Date"].unique():
            session = t3_df[t3_df["Date"] == date].sort_values("Track Number")
            titles = session["Title"].tolist()
            for i in range(len(titles) - 1):
                segues.append(f"{titles[i]}  →  {titles[i + 1]}")
 
        if segues:
            segue_counts = (
                pd.Series(segues)
                .value_counts()
                .reset_index()
            )
            segue_counts.columns = ["Segue", "Times Played"]
            segue_counts = segue_counts[segue_counts["Times Played"] >= 5]
            segue_counts = segue_counts.reset_index(drop=True)
            segue_counts.insert(0, "Rank", range(1, len(segue_counts) + 1))
 
            st.subheader("Most Common Segues")
            st.dataframe(
                segue_counts,
                width="stretch",
                hide_index=True,
                column_config={
                    "Rank": st.column_config.NumberColumn(width="small"),
                    "Segue": st.column_config.TextColumn(width="large"),
                    "Times Played": st.column_config.NumberColumn(width="small")
                }
            )

    elif active == "longest_jams":
 
        def parse_duration(d):
            try:
                parts = str(d).split(":")
                return int(parts[0]) * 60 + int(parts[1])
            except:
                return 0
 
        jam_records = []
        for date in t3_df["Date"].unique():
            session = t3_df[t3_df["Date"] == date].sort_values("Track Number").reset_index(drop=True)
            i = 0
            while i < len(session):
                current = session.iloc[i]
                duration = current["Duration"]
                group_titles = [current["Title"]]
 
                # group consecutive tracks with same duration
                j = i + 1
                while j < len(session) and session.iloc[j]["Duration"] == duration:
                    group_titles.append(session.iloc[j]["Title"])
                    j += 1
 
                label = " -> ".join(group_titles)
                secs = parse_duration(duration)
                jam_records.append({
                    "Date": pd.Timestamp(date).strftime("%m/%d/%Y"),
                    "Song(s)": label,
                    "Duration": duration,
                    "Duration (secs)": secs
                })
                i = j
 
        if jam_records:
            jams_df = (
                pd.DataFrame(jam_records)
                .query("`Duration (secs)` >= 1080")
                .sort_values("Duration (secs)", ascending=False)
                .drop(columns=["Duration (secs)"])
                .reset_index(drop=True)
            )
            jams_df.insert(0, "Rank", range(1, len(jams_df) + 1))
 
            st.subheader("Longest Jams")
            st.dataframe(
                jams_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Rank": st.column_config.NumberColumn(width="small"),
                    "Date": st.column_config.TextColumn(width="small"),
                    "Song(s)": st.column_config.TextColumn(width="large"),
                    "Duration": st.column_config.TextColumn(width="small")
                }
            )

    elif active == "heatmap":

        heatmap_df = t3_df.drop_duplicates(subset="Date").copy()
        heatmap_df["Year"] = heatmap_df["Date"].dt.year
        heatmap_df["Month"] = heatmap_df["Date"].dt.month

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        counts = (
            heatmap_df.groupby(["Year", "Month"])
            .size()
            .reset_index(name="Shows")
        )
        counts["Month Name"] = counts["Month"].apply(lambda m: month_names[m - 1])

        heatmap_chart = alt.Chart(counts).mark_rect(
            cornerRadius=3
        ).encode(
            x=alt.X("Month Name:O",
                    sort=month_names,
                    axis=alt.Axis(title=None, labelAngle=0)),
            y=alt.Y("Year:O",
                    sort="descending",
                    axis=alt.Axis(title=None)),
            color=alt.Color("Shows:Q",
                            scale=alt.Scale(scheme="blues"),
                            legend=alt.Legend(title="Sets")),
            tooltip=[
                alt.Tooltip("Year:O", title="Year"),
                alt.Tooltip("Month Name:O", title="Month"),
                alt.Tooltip("Shows:Q", title="Sets")
            ]
        ).properties(
            height=max(150, len(counts["Year"].unique()) * 40),
            title=alt.TitleParams("# Sets by Month & Year", anchor="middle")
        ).configure_axis(
            grid=False,
            labelColor="#888",
        ).configure_view(
            strokeWidth=0
        )

        st.subheader("Activity Heatmap")
        st.altair_chart(heatmap_chart, width='stretch')

    elif active == "most_common_gig":

        gig_df = t3_df[t3_df["Type"] == "live"]

        gig_counts = (
            gig_df.groupby("Title")
            .agg(
                Times_Played=("Title", "count"),
                Last_Played=("Date", "max")
            )
            .reset_index()
            .sort_values("Times_Played", ascending=False)
            .reset_index(drop=True)
        )
        gig_counts["Last_Played"] = pd.to_datetime(gig_counts["Last_Played"]).dt.strftime("%m/%d/%Y")
        gig_counts.insert(0, "Rank", range(1, len(gig_counts) + 1))

        st.subheader("Most Common Songs at Gigs")
        st.dataframe(
            gig_counts.rename(columns={
                "Times_Played": "Times Played at Gigs",
                "Last_Played": "Last Played at Gig"
            }),
            width="stretch",
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
                "Times Played at Gigs": st.column_config.NumberColumn(width="small"),
                "Last Played at Gig": st.column_config.TextColumn(width="small")
            }
        )
#  -------------------------
# TAB 4: DEAD WEIGHT SETLIST RANDOMIZER
# -------------------------
 
with tab4:
 
    st.markdown("#### Dead Weight Setlist Randomizer v1.0")
 
    improv_titles = set(metadata[metadata["Type"] == "Improv"]["Title"])
    jam_titles = set(jam_metadata["Title"])
    today = pd.Timestamp.today()
 
    randomizer_df = df.merge(metadata[["Title", "Artist"]], on="Title", how="left")
    randomizer_df = randomizer_df[
        (randomizer_df["Artist"].isin(dead_weight_artists)) &
        (randomizer_df["Year"] >= 2022)
    ]
    randomizer_df = randomizer_df[~randomizer_df["Title"].isin(improv_titles)]
 
    random_messages = [
        "They're all Dark Star, man...",
        "Inspiration, move me brightly...",
        "If I had my way, I would tear this ol' building down...",
        "Ain't nobody messing with you but you...",
        "Look out, Cleveland.",
        "Notes, notes, notes, so many notes!",
        "Why haven't we learned Help/Slip/Franklin's yet?",
        "Playin' in the band, talkin' to my friends...",
        "The grass ain't greener, the wine ain't sweeter...",
        "I picked a good one, it looked like it could run...",
        "The one thing we need is a left handed monkey wrench."
]
# Row 1: slider + generate
    col1, col2 = st.columns([1, 1])
 
    with col1:
        num_songs = st.slider("Number of Songs:", 4, 15, 10)
 
    with col2:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("Create Setlist", width='stretch'):
            st.session_state.random_setlist = generate_setlist(
                num_songs, randomizer_df, jam_titles, improv_titles, today
            )
            st.session_state.setlist_version = st.session_state.get("setlist_version", 0) + 1
            st.session_state.random_message = random.choice(random_messages)
 
    # Row 2: re-roll + clear (only show if setlist exists)
    if st.session_state.get("random_setlist") is not None:
 
        col1, col2 = st.columns(2)
 
        with col1:
            if st.button("Re-Roll Unchecked", width='stretch'):
                current = st.session_state.random_setlist.copy()
                locked_songs = set(current[current["Locked"] == True]["Title"].tolist())
                new = generate_setlist(num_songs, randomizer_df, jam_titles, improv_titles, today)
 
                merged = []
                locked_rows = current[current["Locked"] == True].set_index("#")
                new_unlocked = new[~new["Title"].isin(locked_songs)].reset_index(drop=True)
                new_idx = 0
 
                for i in range(1, num_songs + 1):
                    if i in locked_rows.index:
                        row = locked_rows.loc[i].to_dict()
                        row["#"] = i
                        merged.append(row)
                    else:
                        if new_idx < len(new_unlocked):
                            row = new_unlocked.iloc[new_idx].to_dict()
                            row["#"] = i
                            merged.append(row)
                            new_idx += 1
 
                st.session_state.random_setlist = pd.DataFrame(merged)
                st.session_state.setlist_version = st.session_state.get("setlist_version", 0) + 1
                st.session_state.random_message = random.choice(random_messages)
 
        with col2:
            if st.button("Clear Setlist", width='stretch', key="clear_setlists2"):
                st.session_state.random_setlist = None
                st.session_state.setlist_version = 0
                st.rerun()
 
        if st.session_state.get("random_message"):
            st.write(st.session_state.random_message)
 
        # use version in key so editor resets properly when setlist regenerates
        editor_key = f"setlist_editor_{st.session_state.get('setlist_version', 0)}"
 
        # sync any pending lock edits from previous rerun before rendering
        if editor_key in st.session_state:
            edited_state = st.session_state[editor_key].get("edited_rows", {})
            for row_idx, changes in edited_state.items():
                if "Locked" in changes:
                    st.session_state.random_setlist.at[
                        st.session_state.random_setlist.index[row_idx], "Locked"
                    ] = changes["Locked"]
 
        st.data_editor(
            st.session_state.random_setlist[["#", "Title", "Locked"]],
            hide_index=True,
            width="stretch",
            column_config={
                "#": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
                "Locked": st.column_config.CheckboxColumn("🔒", width="small")
            },
            disabled=["#", "Title"],
            key=editor_key
        )
 
# -------------------------
# FOOTER UTILITIES
# -------------------------

st.markdown("")
st.markdown("")
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 1.4.0 | Believe it if you need it</div>",
    unsafe_allow_html=True
)
st.markdown("")
st.markdown("")

col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    if st.button("Master List Clearer"):
        st.session_state.active_stat = None
        st.session_state.random_setlist = None
        if "selected_show" in st.session_state:
            del st.session_state["selected_show"]
        st.session_state.selected_show = None
        if "selected_show_widget" in st.session_state:
            del st.session_state["selected_show_widget"]
        st.rerun()

with col_f2:
    if st.button("Refresh Database"):
        with st.spinner("Updating archive..."):
            subprocess.run(["python", "scanner.py"])
            subprocess.run(["python", "analyze.py"])
            subprocess.run(["python", "build_metadata.py"])
        st.cache_data.clear()
        success_message = st.empty()
        success_message.success("Database updated!")
        time.sleep(2)
        success_message.empty()
        st.rerun()