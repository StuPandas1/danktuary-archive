import streamlit as st # type: ignore
import subprocess
import pandas as pd # type: ignore
import random
import time

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

if "artist_filter" not in st.session_state:
    st.session_state.artist_filter = []

# -------------------------
# UI
# -------------------------

st.title("Danktuary Archive") #title
st.markdown("""
<style>
.stTabs [data-baseweb="tab"] p {
    font-size: 17px !important;
    font-weight: 450 !important;
}
</style>
""", unsafe_allow_html=True)

tab1, tab2, tab3, tab4 = st.tabs(["Song Search", "Setlist Search", "Statistics", "Dead Weight Setlist Randomizer"])

# -------------------------
# SIDEBAR FILTERS
# -------------------------

dead_weight_artists = [
    "Grateful Dead",
    "Jerry Garcia Band",
    "The Band"
]

st.sidebar.markdown("### Filters")

dead_weight_only = st.sidebar.checkbox("Dead Weights Only")

if dead_weight_only:
    current = set(st.session_state.artist_filter)
    current.update(dead_weight_artists)
    st.session_state.artist_filter = list(current)
else:
    st.session_state.artist_filter = [
        artist
        for artist in st.session_state.artist_filter
        if artist not in dead_weight_artists
    ]

artist_filter = st.sidebar.multiselect(
    "By Artist:",
    sorted(song_stats["Artist"].dropna().unique()),
    key="artist_filter"
)

type_filter = st.sidebar.multiselect(
    "By Type:",
    sorted(song_stats["Type"].dropna().unique()),
    key="type_filter"
)

min_year = int(df["Year"].min())
max_year = int(df["Year"].max())

year_range = st.sidebar.slider(
    "By Year:",
    min_year,
    max_year,
    (min_year, max_year)
)

# -------------------------
# FILTER PIPELINE
# Step 1: year filter on raw df
# Step 2: rebuild stats from filtered df
# Step 3: apply artist/type filters to stats
# Step 4: filter df to only titles that survive step 3
# -------------------------

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

if type_filter:
    filtered_song_stats = filtered_song_stats[
        filtered_song_stats["Type"].isin(type_filter)
    ]

# Keep filtered_df in sync with whatever titles survived the stats filters
filtered_df = df[
    (df["Year"] >= year_range[0]) &
    (df["Year"] <= year_range[1]) &
    (df["Title"].isin(filtered_song_stats["Title"]))
].copy()

filtered_song_stats["First_Played"] = pd.to_datetime(filtered_song_stats["First_Played"])
filtered_song_stats["Last_Played"] = pd.to_datetime(filtered_song_stats["Last_Played"])

# -------------------------
# TAB 1: SONG SEARCH
# -------------------------

with tab1:
    st.markdown("#### Song Search")

    search_song = st.selectbox(
        "Get shown the light...",
        sorted(filtered_song_stats["Title"].unique()),
        index=None,
        placeholder="Type to search..."
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Load Song History"):
            st.session_state.selected_song = search_song

    with col2:
        if st.button("Clear Song History"):
            st.session_state.selected_song = None
            st.rerun()

    selected_song = st.session_state.selected_song #search display

    if selected_song:

        matching_stats = filtered_song_stats[
            filtered_song_stats["Title"] == selected_song
        ]

        if not matching_stats.empty:
            stats = matching_stats.iloc[0]

            st.subheader(selected_song)
            st.write(f"Times Played: {stats['Times_Played']}")
            st.write(f"First Played: {stats['First_Played'].strftime('%m/%d/%Y')}")
            st.write(f"Last Played: {stats['Last_Played'].strftime('%m/%d/%Y')}")
            st.write(f"Artist: {stats['Artist']}")

        st.subheader("Performance History")

        performances = df[df["Title"] == selected_song].sort_values("Date", ascending=False)

        st.dataframe(
            performances.assign(
                    Date=lambda x: x["Date"].dt.strftime("%m/%d/%Y")
            )[["Date", "Location", "Track Number"]],
            width='stretch',
            hide_index=True
        )

# -------------------------
# TAB 2: SETLIST SEARCH
# -------------------------

with tab2:
    st.markdown("#### Setlist Search")

    performances = df.copy()
    performances["Show_Label"] = (
        performances["Date"].dt.strftime("%m/%d/%Y")
        + " — "
        + performances["Location"]
    )

    type_order = {"live": 0, "trip": 1, "practice": 2}
    performances["Type_Order"] = performances["Type"].map(type_order).fillna(3)

    show_type_filter = st.pills(
        "Lookin' for a setlist",
        ["Gigs & Trips", "Jam Sessions"],
        selection_mode="multi",
        default=["Gigs & Trips", "Jam Sessions"]
    )

    selected_types = []
    if "Gigs & Trips" in show_type_filter:
        selected_types += ["live", "trip"]
    if "Jam Sessions" in show_type_filter:
        selected_types += ["practice"]

    filtered_performances = performances.copy()
    if selected_types:
        filtered_performances = filtered_performances[
            filtered_performances["Type"].isin(selected_types)
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

        if st.session_state.selected_show: #show select display
                
            selected_label = st.session_state.selected_show
            
            historical_setlist = performances[
                performances["Show_Label"] == selected_label
            ].sort_values("Track Number")

            st.markdown(f"##### {st.session_state.selected_show}")

            st.dataframe(
                historical_setlist[["Track Number","Title",]].rename(
                    columns={"Track Number": "Number"}
                ),
                hide_index=True,
                width='stretch',
                column_config={
                    "Track": st.column_config.NumberColumn(width="small"),
                    "Title": st.column_config.TextColumn(width="large")
                }
            )

# -------------------------
# TAB 3: STATISTICS
# -------------------------

with tab3: 
    st.markdown("#### Song Statistics")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Most Overdue Songs"):
            st.session_state.active_stat = "bustouts"
        if st.button("Most Common Openers"):
            st.session_state.active_stat = "openers"
 
    with col2:
        if st.button("Most Played Songs"):
            st.session_state.active_stat = "most_played"
        if st.button("Most Common Closers"):
            st.session_state.active_stat = "closers"
 
    with col3:
        if st.button("Clear Statistics"):
            st.session_state.active_stat = None
            st.rerun()
 
    active = st.session_state.get("active_stat")
 
    if active == "bustouts":
 
        today = pd.Timestamp.today()
        bustouts = filtered_song_stats.copy()
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
            width='stretch',
            hide_index=True
        )
 
    elif active == "most_played":
 
        most_played = filtered_song_stats.sort_values("Times_Played", ascending=False)
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
            width='stretch',
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small")
            }
        )
 
    elif active == "openers":

        openers = filtered_df[filtered_df["Track Number"] == 1]
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
            width='stretch',
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
                "Times Opened": st.column_config.NumberColumn(width="small")
            }
        )
 
    elif active == "closers":
 
        closers = []
        for date in filtered_df["Date"].unique():
            session = filtered_df[filtered_df["Date"] == date]
            if not session.empty:
                max_track = session["Track Number"].max()
                closer_row = session[session["Track Number"] == max_track]
                if not closer_row.empty:
                    closers.append(closer_row.iloc[0]["Title"])
 
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
            width='stretch',
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
                "Times Closed": st.column_config.NumberColumn(width="small")
            }
        )


# -------------------------
# TAB 4: SETLIST RANDOMIZER
# -------------------------

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

with tab4:

    st.markdown("#### Dead Weight Setlist Randomizer v1.0")

    col1,col2 = st.columns(2)

    with col1: 
        year = st.slider(
                "Starting Year:",
                2015,
                2026,
        )

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

            # Tracks 3–7: pull from recent rotation of last 10 shows
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
             
            # Tracks 9–10: classics (weighted by times played overall)
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
 
            # Closer (track 13)
            closers = []
            for date in randomizer_df["Date"].unique():
                session = randomizer_df[randomizer_df["Date"] == date]
                if not session.empty:
                    max_track = session["Track Number"].max()
                    closer_row = session[session["Track Number"] == max_track]
                    if not closer_row.empty:
                        closers.append(closer_row.iloc[0]["Title"])
 
            closer, closer_odds = weighted_pick(pd.Series(closers), used_songs)
            if closer and closer not in improv_titles:
                used_songs.add(closer)
                random_setlist.append({"Track": 13, "Kind": "Closer", "Title": closer, "Odds": f"{closer_odds}%"})
 
            st.session_state.random_setlist = pd.DataFrame(random_setlist)

    with col2:
        if st.button("Clear This List", key="clear_setlists2"):
            st.session_state.random_setlist = None
            st.rerun()

    if st.session_state.get("random_setlist") is not None: #random setlist display
        
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
# SIDEBAR UTILITIES
# -------------------------

st.sidebar.markdown("---")
st.sidebar.markdown("### Utilities")

if st.sidebar.button("Master List Clearer"):
    st.session_state.active_stat = None
    st.session_state.random_setlist = None
    if "selected_show" in st.session_state:
        del st.session_state["selected_show"]
    st.rerun()

# if st.sidebar.button("Refresh Database"):
#     with st.spinner("Updating archive..."):
#         subprocess.run(["python", "scanner.py"])
#         subprocess.run(["python", "analyze.py"])
#         subprocess.run(["python", "build_metadata.py"])
#     st.cache_data.clear()
#     success_message = st.empty()
#     success_message.success("Database updated! Refresh the page to see new songs.")
#     time.sleep(2)
#     success_message.empty()
#     st.rerun()

st.markdown("")
st.markdown("")
st.markdown("")
st.markdown("---")
st.markdown(
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 1.2 | Believe it if you need it </div>",
    unsafe_allow_html=True
)