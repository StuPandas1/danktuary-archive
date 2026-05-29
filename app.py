import streamlit as st # type: ignore
import pandas as pd # type: ignore
import subprocess 
import random
import time

#timing
from datetime import datetime

# load data
df = pd.read_csv("band_archive.csv")
song_stats = pd.read_csv("song_stats.csv")
metadata = pd.read_csv("song_metadata.csv")

if "selected_song" not in st.session_state:
    st.session_state.selected_song = None

if "random_setlist" not in st.session_state:
    st.session_state.random_setlist = None

if "selected_show" not in st.session_state:
    st.session_state.selected_show = None

if "bustouts" not in st.session_state:
    st.session_state.bustouts = None

if "most_played" not in st.session_state:
    st.session_state.most_played = None

if "artist_filter" not in st.session_state:
    st.session_state.artist_filter = []

df["Date"] = pd.to_datetime(df["Date"])
df["Year"] = df["Date"].dt.year

song_stats = song_stats.merge(
    metadata,
    on="Title",
    how="left"
)

times_played_mult=1.3

st.title("Danktuary Archive") #title

st.markdown("""
<style>

.stTabs [data-baseweb="tab"] p {
    font-size: 17px !important;
    font-weight: 450 !important;
}

</style>
""", unsafe_allow_html=True)

tab1, tab2, tab3 = st.tabs([
    "Song Search",
    "Setlists",
    "Statistics"
])

# -------------------------
# GLOBAL FILTERS
# -------------------------

st.sidebar.markdown("### Filters")

dead_weight_only = st.sidebar.checkbox(
    "Dead Weights Only"
)

dead_weight_artists = [
    "Grateful Dead",
    "Jerry Garcia Band",
    "The Band"
]

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

filtered_song_stats = song_stats.copy()

# YEAR FILTER
filtered_df = df.copy()

filtered_df = filtered_df[
    (filtered_df["Year"] >= year_range[0]) &
    (filtered_df["Year"] <= year_range[1])
]

# REBUILD STATS FROM FILTERED DATA
filtered_song_stats = filtered_df.groupby("Title").agg(
    Times_Played=("Title", "count"),
    First_Played=("Date", "min"),
    Last_Played=("Date", "max")
).reset_index()

# RE-MERGE METADATA
filtered_song_stats = filtered_song_stats.merge(
    metadata,
    on="Title",
    how="left"
)

# ARTIST FILTER
if artist_filter:
    filtered_song_stats = filtered_song_stats[
        filtered_song_stats["Artist"].isin(artist_filter)
    ]

# TYPE FILTER
if type_filter:
    filtered_song_stats = filtered_song_stats[
        filtered_song_stats["Type"].isin(type_filter)
    ]

# FILTER MAIN DATABASE
filtered_df = df[
    df["Title"].isin(
        filtered_song_stats["Title"]
    )
]

filtered_song_stats["First_Played"] = pd.to_datetime(filtered_song_stats["First_Played"])
filtered_song_stats["Last_Played"] = pd.to_datetime(filtered_song_stats["Last_Played"])

# -------------------------
# SONG SEARCH SECTION
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

    #SEARCH DISPLAY

    selected_song = st.session_state.selected_song #search display

    if selected_song:

        matching_stats = filtered_song_stats[
            filtered_song_stats["Title"] == selected_song
        ]

        if not matching_stats.empty:

            stats = matching_stats.iloc[0]

            st.subheader(selected_song)

            st.write(f"Times Played: {stats['Times_Played']}")
            st.write(
                f"First Played: {stats['First_Played'].strftime('%m/%d/%Y')}"
            )
            st.write(
                f"Last Played: {stats['Last_Played'].strftime('%m/%d/%Y')}"
            )
            st.write(f"Artist: {stats['Artist']}")

        # -------------------------
        # PERFORMANCE HISTORY
        # -------------------------

        st.subheader("Performance History")

        performances = df[
            df["Title"] == selected_song
        ].sort_values("Date", ascending=False)

        st.dataframe(
            performances.assign(
                    Date=lambda x: x["Date"].dt.strftime("%m/%d/%Y")
            )[
                [
                    "Date",
                    "Location",
                    "Track Number"
                ]
            ],
            width='stretch',
            hide_index=True
        )


# -------------------------
# MAIN SCREEN DISPLAYS FOR FEATURES
# -------------------------
with tab2:
    st.markdown("#### Setlists")
    
    # -------------------------
    # RANDOM SETLIST
    # -------------------------
    col1, col2 = st.columns([2.6,1])
    
    with col1:

        show_query = st.text_input(
            "Search setlists by date or location:"
        )

        performances = df.copy()

        performances["Show_Label"] = (
            performances["Date"].dt.strftime("%m/%d/%Y")
            + " — "
            + performances["Location"]
        )

        if show_query:

            matching_shows = performances[
                performances["Show_Label"]
                .str.lower()
                .str.contains(show_query.lower())
            ]

            matching_shows = matching_shows.sort_values(
                "Date",
                ascending=False
            )

            unique_shows = matching_shows["Show_Label"].unique()    

            selected_show = st.selectbox(
                "Setlist Search Results",
                unique_shows,
                key="selected_show"    
            )

    if st.session_state.selected_show:
        selected_date = (
            st.session_state.selected_show
            .split(" — ")[0]
        )

        historical_setlist = performances[
            performances["Date"]
            .dt.strftime("%m/%d/%Y")
            == selected_date
        ].sort_values("Track Number")

        st.dataframe(
            historical_setlist[
                [
                    "Track Number",
                    "Title",
                ]
            ].rename(columns={
                "Track Number": "Track"
            }),

            hide_index=True,
            width='stretch',

            column_config={
                "Track": st.column_config.NumberColumn(
                    width="small"
                ),
                "Title": st.column_config.TextColumn(
                    width="large"
                )
            }
        )

    with col2:

        if st.button("Setlist Randomizer (v0.1)"):

            random_setlist = []
            used_songs = set()

            # TRACKS 1–11
            for track_num in range(1, 12):

                possible_songs = filtered_df[
                    filtered_df["Track Number"] == track_num
                ]["Title"].unique()

                available_songs = [
                    song for song in possible_songs
                    if song not in used_songs
                ]

                if available_songs:

                    chosen_song = random.choice(available_songs)

                    used_songs.add(chosen_song)

                    random_setlist.append({
                        "Track": track_num,
                        "Title": chosen_song
                    })

            # FIND REAL CLOSERS
            closers = []

            for date in filtered_df["Date"].unique():

                session = filtered_df[filtered_df["Date"] == date]

                if not session.empty:

                    max_track = session["Track Number"].max()

                    closer_row = session[
                        session["Track Number"] == max_track
                    ]

                    if not closer_row.empty:

                        closer_song = closer_row.iloc[0]["Title"]

                        closers.append(closer_song)

            # RANDOM CLOSER

            available_closers = [
                song for song in closers
                if song not in used_songs
            ]

            if available_closers:
                random_closer = random.choice(available_closers)
            
                used_songs.add(random_closer)

                random_setlist.append({
                    "Track": 12,
                    "Title": random_closer
                })

            st.session_state.random_setlist = pd.DataFrame(random_setlist)

        if st.button("Clear a Setlist", key="clear_setlists"):

            st.session_state.random_setlist = None 

            if "selected_show" in st.session_state:
                del st.session_state["selected_show"]
 
            st.rerun()

    if st.session_state.get("random_setlist") is not None: #random setlist display

        st.markdown("##### They're all dark star, man")

        st.dataframe(
            st.session_state.random_setlist,
            hide_index=True,
            width='stretch',

            column_config={
                "Track": st.column_config.NumberColumn(
                "#",
                width="small"
                ),

                "Title": st.column_config.TextColumn(
                    "Song Title",
                    width="large"
                )
        }
        )

with tab3: #song stats
    st.markdown("#### Song Statistics")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("Most Overdue Songs"):

            today = pd.Timestamp.today()

            filtered_song_stats["Days_Since_Played"] = (
                today - filtered_song_stats["Last_Played"]
            ).dt.days

            filtered_song_stats["Overdue_Score"] = (
                filtered_song_stats["Days_Since_Played"]
                * (filtered_song_stats["Times_Played"] ** times_played_mult)
            )

            bustouts = filtered_song_stats.sort_values(
                "Overdue_Score",
                ascending=False
            )

            bustouts["Overdue_Score"] = (
                    bustouts["Overdue_Score"].round(1)
                )   
            
            max_score = bustouts["Overdue_Score"].max()

            bustouts["Overdue_Score_Normalized"] = (
                bustouts["Overdue_Score"] / max_score
            ) * 100

            bustouts["Overdue_Score_Normalized"] = (
                bustouts["Overdue_Score_Normalized"].round(1)
            )   

            st.session_state.bustouts = pd.DataFrame(bustouts)
            

    with col2:
        if st.button("Most Played Songs"):
            
            most_played = filtered_song_stats.sort_values(
                "Times_Played",
                ascending=False
            )

            st.session_state.most_played = most_played
            st.session_state.bustouts = None
    
    with col3:
        if st.button("Clear Statistics"):

            st.session_state.bustouts = None
            st.session_state.most_played = None 

            st.rerun()

    if st.session_state.get("bustouts") is not None: #overdue song display
        
        st.subheader("Most Overdue Songs")
    
        st.dataframe(
            st.session_state.bustouts.assign(
                Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y")
                )[[
                    "Title",
                    "Days_Since_Played",
                    "Times_Played",
                    "Overdue_Score_Normalized"
                ]]
                .rename(columns={
            "Days_Since_Played": "Days Since Played",
            "Times_Played": "Times Played",
            "Overdue_Score_Normalized": "Overdue Score (Normalized)"
            }),
            width='stretch',
            hide_index=True
        )
    # -------------------------
    # MOST PLAYED
    # -------------------------

    if st.session_state.get("most_played") is not None:

            st.subheader("Most Played Songs")

            st.dataframe(
                st.session_state.most_played.assign(
                    First_Played=lambda x: x["First_Played"].dt.strftime("%m/%d/%Y"),
                    Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y")
                )[
                    [
                        "Title",
                        "Times_Played",
                        "First_Played",
                        "Last_Played"
                    ]
                ].rename(columns={
                    "Times_Played": "Times Played",
                    "First_Played": "First Played",
                    "Last_Played": "Last Played"
                }),

                width='stretch',
                hide_index=True
            )    


# -------------------------
# REFRESH DATABASE
# -------------------------

st.sidebar.markdown("---")
st.sidebar.markdown("### Utilities")


# CLEAR PLAYLIST AND BUSTOUTS
if st.sidebar.button("Master List Clearer"):

    st.session_state.bustouts = None
    st.session_state.random_setlist = None   
    st.session_state.most_played = None 
    if "selected_show" in st.session_state:
        del st.session_state["selected_show"]
    st.rerun()

# # REFRESH DATABASE
# if st.sidebar.button("Refresh Database"):

#     with st.spinner("Updating archive..."):

#         subprocess.run(["python", "scanner.py"])
#         subprocess.run(["python", "analyze.py"])
#         subprocess.run(["python", "build_metadata.py"])

#     success_message = st.empty()
#     success_message.success("Database updated! Refresh the page to see new songs.")
#     time.sleep(2)
#     success_message.empty()
#     st.rerun()
