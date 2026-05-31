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
 
    df["Date"] = pd.to_datetime(df["Date"])
    df["Year"] = df["Date"].dt.year
 
    song_stats = song_stats.merge(metadata, on="Title", how="left")
 
    return df, song_stats, metadata
 
df, song_stats, metadata = load_data()

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

tab1, tab2, tab3 = st.tabs(["Song Search", "Setlists", "Statistics"])

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
# TAB 2: SETLISTS
# -------------------------

with tab2:
    st.markdown("#### Setlists")

    col1, col2 = st.columns([2.6,1])
    
    with col1:

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

        if selected_show:
            st.session_state.selected_show = selected_show
            st.session_state.random_setlist = None

    with col2:
 
        if st.button("Setlist Randomizer (v0.2)"):
 
            st.session_state.selected_show = None
 
            improv_titles = set(metadata[metadata["Type"] == "Improv"]["Title"])
            randomizer_df = filtered_df[~filtered_df["Title"].isin(improv_titles)]
 
            random_setlist = []
            used_songs = set()
 
            for track_num in range(1, 10):
 
                slot_songs = randomizer_df[
                    randomizer_df["Track Number"] == track_num
                ]["Title"]
 
                slot_counts = slot_songs.value_counts()
                available = [(s, c) for s, c in slot_counts.items() if s not in used_songs]
 
                if available:
                    songs, weights = zip(*available)
                    total = sum(weights)
                    chosen_song = random.choices(songs, weights=weights, k=1)[0]
                    chosen_odds = round((weights[songs.index(chosen_song)] / total) * 100, 1)
                    used_songs.add(chosen_song)
                    random_setlist.append({"Track": track_num, "Title": chosen_song, "Odds": f"{chosen_odds}%"})
 
            closers = []
            for date in randomizer_df["Date"].unique():
                session = randomizer_df[randomizer_df["Date"] == date]
                if not session.empty:
                    max_track = session["Track Number"].max()
                    closer_row = session[session["Track Number"] == max_track]
                    if not closer_row.empty:
                        closers.append(closer_row.iloc[0]["Title"])
 
            closer_counts = pd.Series(closers).value_counts()
            available_closers = [(s, c) for s, c in closer_counts.items() if s not in used_songs and s not in improv_titles]
 
            if available_closers:
                songs, weights = zip(*available_closers)
                total = sum(weights)
                random_closer = random.choices(songs, weights=weights, k=1)[0]
                closer_odds = round((weights[songs.index(random_closer)] / total) * 100, 1)
                used_songs.add(random_closer)
                random_setlist.append({"Track": 10, "Title": random_closer, "Odds": f"{closer_odds}%"})
 
            st.session_state.random_setlist = pd.DataFrame(random_setlist)
 
        if st.button("Clear a Setlist", key="clear_setlists"):
            st.session_state.random_setlist = None
            st.session_state.selected_show = None
            st.rerun()
 
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
        
    elif st.session_state.get("random_setlist") is not None: #random setlist display

        st.markdown("##### They're all dark star, man")

        st.dataframe(
            st.session_state.random_setlist,
            hide_index=True,
            width='stretch',
            column_config={
                "Track": st.column_config.NumberColumn("#", width="small"),
                "Title": st.column_config.TextColumn("Song Title", width="large"),
                "Odds": st.column_config.TextColumn("Odds", width="small")                
                }
            )
        
# -------------------------
# TAB 3: STATISTICS
# -------------------------

with tab3: #song stats
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
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 1.1 | Believe it if you need it </div>",
    unsafe_allow_html=True
)