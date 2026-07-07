import streamlit as st # type: ignore
import subprocess
import pandas as pd # type: ignore
import random
import time
import altair as alt

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

dead_weight_artists = ["Grateful Dead", "Jerry Garcia Band", "The Band", "Little Feat"]
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

# -------------------------
# UI
# -------------------------

st.subheader("DankApp: The Danktuary Archive Explorer")
st.markdown("""
<style>
.stTabs [data-baseweb="tab"] p {
    font-size: 17px !important;
    font-weight: 450 !important;
}
</style>
""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["Song Search", "Setlist Lookup", "Statistics", "Dead Weight Setlist Randomizer"])

# -------------------------
# TAB 1: SONG SEARCH
# -------------------------
 
with tab1:
    st.markdown("#### Song Search")
 
    with st.expander("Filters", expanded=False):
        st.checkbox("Dead Weight Only", key="t1_dead_weight", on_change=on_t1_dw_change)
 
        t1_artist = st.multiselect(
            "By Artist:",
            sorted(song_stats["Artist"].dropna().unique()),
            key="t1_artist"
        )
        t1_year = st.slider(
            "By Year:",
            min_year, max_year, (min_year, max_year),
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
            st.write(f"**Between {t1_year[0]} and {t1_year[1]}:**")
            times = stats['Times_Played']
            st.write(f"\"{selected_song}\" was played **{times}** {'time.' if times == 1 else 'times.'}")
            st.write(f"First played: **{stats['First_Played'].strftime('%m/%d/%Y')}**")
            days_ago = (pd.Timestamp.today() - stats['Last_Played']).days
            st.write(f"Last played: **{stats['Last_Played'].strftime('%m/%d/%Y')}**, or **{days_ago}** {'day ago.' if days_ago == 1 else 'days ago.'}")
 
            total_shows_since_debut = df[df["Date"] >= stats["First_Played"]]["Date"].nunique()
            shows_played = performances["Date"].nunique()
            pct = round((shows_played / total_shows_since_debut) * 100, 1)
            st.write(f"Since its debut in this window, **\"{selected_song}\"** has been played in **{pct}%** of setlists.")
 
        with st.expander("Graph By Year (All-Time)", expanded=False):
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
 
        with st.expander("Performance History (All-Time)", expanded=False):
            performances["Gap Since Previous"] = (
                performances["Date"].diff().dt.days
            ).fillna(0).astype(int) * -1
 
            df_display = performances.assign(
                Date=lambda x: x["Date"].dt.strftime("%m/%d/%Y")
            )[["Date", "Location", "Gap Since Previous"]]
 
            st.dataframe(
                df_display,
                column_config={
                    "Date": st.column_config.TextColumn("Date", width="small"),
                    "Gap Since Previous": st.column_config.NumberColumn("Gap Since Previous", width="small")
                },
                width="stretch",
                hide_index=True,
            )
 
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
 
    with col1:
        location_filter = st.selectbox(
            "By Location:",
            ["All"] + sorted(performances["Location"].dropna().unique().tolist()),
            index=0
        )
 
    with col2:
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
 
    if st.button("Clear a Setlist", key="clear_setlists1"):
        st.session_state.selected_show = None
        st.rerun()
 
    if selected_show:
        st.session_state.selected_show = selected_show
 
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
 
        st.markdown(f"##### You selected the {selected_location} setlist on {selected_date_str}.")
        st.write(f"You've played **{venue_shows}** {'set' if venue_shows == 1 else 'sets'} at {selected_location}") 
 
        if len(tied_songs) > 1:
            st.write(f"There are **{len(tied_songs)}** songs tied for most common at {selected_location}, each played **{most_common_count}** {'time' if most_common_count == 1 else 'times'}")
        else:
            most_common_at_venue = tied_songs.idxmax()
            st.write(f"**\"{most_common_at_venue}\"** is the most common at {selected_location} (**{most_common_count}** {'time' if most_common_count == 1 else 'times'} played)")
 
        st.dataframe(
            historical_setlist[["Track Number", "Title"]].rename(
                columns={"Track Number": "Number"}
            ),
            hide_index=True,
            width='stretch',
            column_config={
                "Number": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large")
            }
        )
 
# -------------------------
# TAB 3: STATISTICS
# -------------------------
 
with tab3:
    st.markdown("#### Song Statistics")
 
    with st.expander("Filters", expanded=False):
        st.checkbox("Dead Weight Only", key="t3_dead_weight", on_change=on_t3_dw_change)
 
        t3_artist = st.multiselect(
            "By Artist:",
            sorted(song_stats["Artist"].dropna().unique()),
            key="t3_artist"
        )
        t3_year = st.slider(
            "By Year:",
            min_year, max_year, (min_year, max_year),
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
            if st.button("Most Consecutive Shows"):
                st.session_state.active_stat = "consecutive"
 
    with st.expander("Setlist Stats", expanded=False):
        col1, col2, col3 = st.columns(3)
        with col1:
            if st.button("Most Common Openers"):
                st.session_state.active_stat = "openers"
        with col2:
            if st.button("Most Common Closers"):
                st.session_state.active_stat = "closers"
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
        bustouts.insert(0, "Rank", range(1, len(bustouts) + 1))

 
        st.subheader("Most Overdue Songs")
        st.dataframe(
            bustouts.assign(
                Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y")
            )[[
                "Rank", "Title", "Days_Since_Played", "Times_Played", "Overdue_Score_Normalized"
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
                    "Title": st.column_config.TextColumn(width="medium"),
                    "Longest Gap (Sets)": st.column_config.NumberColumn(width="medium"),
                    "From": st.column_config.TextColumn(width="small"),
                    "To": st.column_config.TextColumn(width="small"),
                }
            )
 
    elif active == "consecutive":
 
        all_dates = sorted(t3_df["Date"].unique())
        records = []
        for title in t3_df["Title"].unique():
            song_dates = set(t3_df[t3_df["Title"] == title]["Date"].unique())
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
 
            st.subheader("Active Consecutive Show Streaks")
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
 
        allowed_titles = set(t3_df["Title"].unique())
        closers = find_closers(df, allowed_titles)
 
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
            segue_counts = segue_counts[segue_counts["Times Played"] >= 3]
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
 
# -------------------------
# TAB 4: DEAD WEIGHT SETLIST RANDOMIZER
# -------------------------

with tab4:

    st.markdown("#### Dead Weight Setlist Randomizer v1.0")

    col1, col2 = st.columns(2)

    with col1:
        year = st.slider("Starting Year:", 2015, 2026)

        if st.button("Randomize Me!"):

            random_setlist = []
            used_songs = set()

            improv_titles = set(metadata[metadata["Type"] == "Improv"]["Title"])
            allowed_artists = ["The Band", "Grateful Dead", "Jerry Garcia Band", "Little Feat"]

            randomizer_df = df.merge(metadata[["Title", "Artist"]], on="Title", how="left")
            randomizer_df = randomizer_df[
                (randomizer_df["Artist"].isin(allowed_artists)) &
                (randomizer_df["Year"] >= year)
            ]
            randomizer_df = randomizer_df[~randomizer_df["Title"].isin(improv_titles)]

            # Track 1: Opener
            opener, opener_odds = weighted_pick(
                randomizer_df[randomizer_df["Track Number"] == 1]["Title"],
                used_songs
            )
            if opener:
                used_songs.add(opener)
                random_setlist.append({"Track": 1, "Kind": "Opener", "Title": opener, "Odds": f"{opener_odds}%"})

            # Track 2: Jam 1
            jam_titles = set(jam_metadata["Title"])
            jam_pool = randomizer_df[randomizer_df["Title"].isin(jam_titles)]

            jam1, jam1_odds = weighted_pick(jam_pool["Title"], used_songs)
            if jam1:
                used_songs.add(jam1)
                random_setlist.append({"Track": 2, "Kind": "Jam", "Title": jam1, "Odds": f"{jam1_odds}%"})

            # Tracks 3–7: recent rotation (last 10 shows)
            recent_dates = (
                randomizer_df["Date"].drop_duplicates()
                .sort_values()
                .tail(10)
            )
            recent_pool = randomizer_df[randomizer_df["Date"].isin(recent_dates)]["Title"]

            for track_num in range(3, 8):
                song, odds = weighted_pick(recent_pool, used_songs)
                if song:
                    used_songs.add(song)
                    random_setlist.append({"Track": track_num, "Kind": "Recent", "Title": song, "Odds": f"{odds}%"})

            random_setlist.append({"Track": None, "Kind": "Take 5", "Title": "Set Break", "Odds": "N/A"})

            # Track 8: Jam 2
            jam2, jam2_odds = weighted_pick(jam_pool["Title"], used_songs)
            if jam2:
                used_songs.add(jam2)
                random_setlist.append({"Track": 8, "Kind": "Jam", "Title": jam2, "Odds": f"{jam2_odds}%"})

            # Tracks 9–10: classics (weighted by times played)
            classics_pool = (
                randomizer_df.groupby("Title")
                .size()
                .reset_index(name="Times_Played")
                .sort_values("Times_Played", ascending=False)
            )
            for track_num in range(9, 11):
                available = classics_pool[~classics_pool["Title"].isin(used_songs)]
                if not available.empty:
                    songs = available["Title"].tolist()
                    weights = available["Times_Played"].tolist()
                    total = sum(weights)
                    chosen = random.choices(songs, weights=weights, k=1)[0]
                    odds = round((weights[songs.index(chosen)] / total) * 100, 1)
                    used_songs.add(chosen)
                    random_setlist.append({"Track": track_num, "Kind": "Classic", "Title": chosen, "Odds": f"{odds}%"})

            # Tracks 11–12: bustouts (weighted by days since last played)
            today = pd.Timestamp.today()
            bustout_pool = (
                randomizer_df.groupby("Title")["Date"]
                .max()
                .reset_index()
            )
            bustout_pool["Days_Since"] = (today - pd.to_datetime(bustout_pool["Date"])).dt.days
            for track_num in range(11, 13):
                available = bustout_pool[~bustout_pool["Title"].isin(used_songs)]
                if not available.empty:
                    songs = available["Title"].tolist()
                    weights = available["Days_Since"].tolist()
                    total = sum(weights)
                    chosen = random.choices(songs, weights=weights, k=1)[0]
                    odds = round((weights[songs.index(chosen)] / total) * 100, 1)
                    used_songs.add(chosen)
                    random_setlist.append({"Track": track_num, "Kind": "Bustout", "Title": chosen, "Odds": f"{odds}%"})

            # Track 13: Closer (from full df, filtered to allowed pool)
            allowed_titles = set(randomizer_df["Title"].unique())
            closers = find_closers(df, allowed_titles)

            closer, closer_odds = weighted_pick(pd.Series(closers), used_songs)
            if closer and closer not in improv_titles:
                used_songs.add(closer)
                random_setlist.append({"Track": 13, "Kind": "Closer", "Title": closer, "Odds": f"{closer_odds}%"})

            st.session_state.random_setlist = pd.DataFrame(random_setlist)

    with col2:
        if st.button("Clear This List", key="clear_setlists2"):
            st.session_state.random_setlist = None
            st.rerun()

    if st.session_state.get("random_setlist") is not None:

        random_messages = [
            "They're all Dark Star, man...",
            "Inspiration, move me brightly...",
            "Let my inspiration flow...",
            "Statistically improbable. Musically inevitable.",
            "Somewhere, Phil is shaking his head.",
            "Notes, notes, notes, so many notes!",
            "Why haven't we learned Help/Slip/Franklin's yet?",
            "The grass ain't greener, the wine ain't sweeter...",
        ]

        st.write(random.choice(random_messages))

        st.dataframe(
            st.session_state.random_setlist,
            hide_index=True,
            width='stretch',
            height=500,
            column_config={
                "Track": st.column_config.NumberColumn("#", width="small"),
                "Kind": st.column_config.TextColumn("Kind", width="small"),
                "Title": st.column_config.TextColumn("Song Title", width="large"),
                "Odds": st.column_config.TextColumn("Odds", width="small")
            }
        )

# -------------------------
# FOOTER UTILITIES
# -------------------------

st.markdown("")
st.markdown("")
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 1.3 | Believe it if you need it</div>",
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
        st.rerun()

# with col_f2:
#     if st.button("Refresh Database"):
#         with st.spinner("Updating archive..."):
#             subprocess.run(["python", "scanner.py"])
#             subprocess.run(["python", "analyze.py"])
#             subprocess.run(["python", "build_metadata.py"])
#         st.cache_data.clear()
#         success_message = st.empty()
#         success_message.success("Database updated! Refresh the page to see new songs.")
#         time.sleep(2)
#         success_message.empty()
#         st.rerun()