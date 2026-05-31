import streamlit as st # type: ignore
import pandas as pd # type: ignore
import subprocess 
import random
import time

#timing
from datetime import datetime

# load data
df = pd.read_csv("band_archive.csv")
raw_song_stats = pd.read_csv("song_stats.csv")
metadata = pd.read_csv("song_metadata.csv")

# convert dates
df["Date"] = pd.to_datetime(df["Date"])
df["Year"] = df["Date"].dt.year

times_played_mult=1.3 #multiplier variable for overdue score calculation

#session states 
if "selected_song" not in st.session_state:
    st.session_state.selected_song = None

if "selected_show" not in st.session_state:
    st.session_state.selected_show = None

if "show_openers" not in st.session_state:
    st.session_state.show_openers = False

if "show_closers" not in st.session_state:
    st.session_state.show_closers = False

# GLOBAL FILTERS
st.sidebar.header("Filters")

year_range = st.sidebar.slider(
    "Year Range",
    int(df["Year"].min()),
    int(df["Year"].max()),
    (int(df["Year"].min()), int(df["Year"].max()))
)

artist_filter = st.sidebar.multiselect(
    "Artist",
    sorted(df["Artist"].unique()),
    default=[]
)

type_filter = st.sidebar.multiselect(
    "Type",
    sorted(df["Type"].unique()),
    default=[]
)

#commands for filtering and stats
def get_filtered_df(df, year_range, artist_filter, type_filter):
    filtered = df.copy()

    # Year filter
    filtered = filtered[
        (filtered["Year"] >= year_range[0]) &
        (filtered["Year"] <= year_range[1])
    ]

    # Artist filter
    if artist_filter:
        filtered = filtered[filtered["Artist"].isin(artist_filter)]

    # Type filter (e.g. song, jam, cover, etc.)
    if type_filter:
        filtered = filtered[filtered["Type"].isin(type_filter)]

    return filtered

def get_openers(filtered_df):
    openers_df = filtered_df[filtered_df["Track Number"] == 1]
    openers = (
        openers_df["Title"]
        .value_counts()
        .reset_index()
    )
    openers.columns = ["Title", "Times Opened"]
    return openers

def get_closers(filtered_df):
    # assumes highest track number = closer per show
    closers_df = (
        filtered_df
        .sort_values("Track Number")
        .groupby(["Date", "Location"])
        .last()
        .reset_index()
    )
    closers = (
        closers_df["Title"]
        .value_counts()
        .reset_index()
    )
    closers.columns = ["Title", "Times Closed"]
    return closers

def get_song_stats(filtered_df, metadata):
    stats = (
        filtered_df.groupby("Title")
        .agg(
            Times_Played=("Title", "count"),
            First_Played=("Date", "min"),
            Last_Played=("Date", "max")
        )
        .reset_index()
    )
    return stats.merge(metadata, on="Title", how="left")

def get_bustouts(filtered_df):
    counts = filtered_df["Title"].value_counts()

    return counts[counts == 1].reset_index().rename(
        columns={"index": "Title", "Title": "Times Played"}
    )

filtered_df = get_filtered_df(df, year_range, artist_filter, type_filter)
song_stats = get_song_stats(filtered_df, metadata)
openers = get_openers(filtered_df)
closers = get_closers(filtered_df)
bustouts = get_bustouts(filtered_df)


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

year_range = st.sidebar.slider(
    "Year Range",
    int(df["Year"].min()),
    int(df["Year"].max()),
    (int(df["Year"].min()), int(df["Year"].max()))
)

song_stats = get_song_stats(filtered_df, metadata)
openers = get_openers(filtered_df)
closers = get_closers(filtered_df)

# -------------------------
# SONG SEARCH SECTION
# -------------------------

tab1, tab2, tab3 = st.tabs(["Song Search", "Setlists", "Statistics"])

with tab1:
    st.markdown("#### Song Search")

    search_song = st.selectbox(
        "Get shown the light...",
        sorted(song_stats["Title"].unique()),
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

        matching_stats = song_stats[
            song_stats["Title"] == selected_song
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
            for track_num in range(1, 10):

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
                    "Track": 10,
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

            song_stats["Days_Since_Played"] = (
                today - song_stats["Last_Played"]
            ).dt.days

            song_stats["Overdue_Score"] = (
                song_stats["Days_Since_Played"]
                * (song_stats["Times_Played"] ** times_played_mult)
            )

            bustouts = song_stats.sort_values(
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
        
        if st.button("Most Common Openers"):
            openers = filtered_df[filtered_df["Track Number"] == 1]
            openers = (
                openers["Title"]
                .value_counts()
                .reset_index()
            )
            openers.columns = ["Title", "Times Opened"]

            st.subheader("Most Common Openers")

            st.dataframe(
                st.session_state.most_common_openers,
                width="stretch",
                hide_index=True
            )
                

    with col2:
        if st.button("Most Played Songs"):
            most_played = song_stats.sort_values(
                "Times_Played",
                ascending=False
            )

        if st.button("Most Common Closers",
            key="closers_button"
        ):
            closers = (
                filtered_df
                .sort_values("Track Number")
                .groupby(["Date", "Location"])
                .last()
                .reset_index()
            )

            closers = (
                closers["Title"]
                .value_counts()
                .reset_index()
            )

            closers.columns = [
                "Title",
                "Times Closed"
            ]
        
        if st.session_state.most_common_closers is not None:

            st.subheader("Most Common Closers")

            st.dataframe(
                st.session_state.most_common_closers,
                width="stretch",
                hide_index=True
            )

        
    with col3:
        if st.button("Clear Statistics"):

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
    st.session_state.most_common_closers = None
    st.session_state.most_common_openers = None
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
