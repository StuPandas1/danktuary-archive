import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import random

times_played_mult = 1.3  # multiplier for how much weight to give times played in overdue score
""
dead_weight_artists = ["Grateful Dead", "Jerry Garcia Band", "The Band", "Little Feat", "Phish", "The Rolling Stones", "Sam Cooke"]
dead_weight_year = 2022


# -------------------------
# PAGE MENU (dropdown)
# -------------------------

def page_menu():
    with st.popover("☰ Menu"):
        if st.button("Dashboard", width="stretch"):
            st.switch_page("pages/landing.py")
        if st.button("Useful Tools", width="stretch"):
            st.switch_page("pages/tools.py")
        if st.button("Explore the Archive", width="stretch"):
            st.switch_page("pages/explore.py")


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


# -------------------------
# SHARED HELPERS
# -------------------------

def parse_duration(d):
    try:
        parts = str(d).split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return 0


def build_filtered(df, metadata, artist_filter, year_range):
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
# DEAD WEIGHT CHECKBOX CALLBACKS
# -------------------------

def make_dead_weight_callback(artist_key, year_key, checkbox_key, min_year, max_year):
    def callback():
        if st.session_state[checkbox_key]:
            st.session_state[artist_key] = dead_weight_artists
            st.session_state[year_key] = (dead_weight_year, max_year)
        else:
            st.session_state[artist_key] = []
            st.session_state[year_key] = (min_year, max_year)
    return callback
