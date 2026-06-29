import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import random
import os
from urllib.parse import quote

times_played_mult = 1.3  # multiplier for how much weight to give times played in overdue score

dead_weight_artists = ["Grateful Dead", "Jerry Garcia Band", "The Band", "Little Feat"]
dead_weight_year = 2022


# -------------------------
# ONEDRIVE LINK CONVERTER
# -------------------------

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


# -------------------------
# DANK HEADER (shared banner)
# -------------------------

def dank_header(subtitle="The Danktuary Archive Explorer", anchor_id="dankapp-top"):
    st.markdown(f"""
    <style>
    .dank-header {{
        background-color: #1c1b1a;
        border-radius: 10px;
        border-bottom: 3px solid #d4a24c;
        padding: 18px 20px 16px 20px;
        margin-bottom: 20px;
    }}
    .dank-header-title {{
        color: #ece7de;
        font-size: 32px;
        font-weight: 700;
        letter-spacing: -0.01em;
        line-height: 1.1;
        margin-bottom: 4px;
    }}
    .dank-header-subtitle {{
        color: #7a8b6f;
        font-size: 14px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }}
    </style>
    <div class="dank-header" id="{anchor_id}">
        <div class="dank-header-title">DankApp</div>
        <div class="dank-header-subtitle">{subtitle}</div>
    </div>
    """, unsafe_allow_html=True)


# -------------------------
# AUDIO PLAYER
# -------------------------

def dank_audio_player(title, subtitle, audio_url):
    import streamlit.components.v1 as components
    components.html(f"""
    <style>
    body {{
        margin: 0;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }}
    .dank-player-card {{
        background-color: #1c1b1a;
        border-radius: 14px;
        border-bottom: 3px solid #d4a24c;
        padding: 20px 20px 18px 20px;
        box-sizing: border-box;
    }}
    .dank-player-title {{
        color: #ece7de;
        font-size: 18px;
        font-weight: 700;
        letter-spacing: -0.01em;
        margin-bottom: 2px;
    }}
    .dank-player-subtitle {{
        color: #7a8b6f;
        font-size: 12px;
        font-weight: 500;
        text-transform: uppercase;
        letter-spacing: 0.06em;
        margin-bottom: 14px;
    }}
    .dank-player-card audio {{
        width: 100%;
        border-radius: 8px;
        outline: none;
    }}
    </style>
    <div class="dank-player-card">
        <div class="dank-player-title">{title}</div>
        <div class="dank-player-subtitle">{subtitle}</div>
        <audio controls preload="none">
            <source src="{audio_url}">
            Your browser does not support the audio element.
        </audio>
    </div>
    """, height=130)


# -------------------------
# PAGE MENU (dropdown)
# -------------------------

def page_menu():
    with st.popover("☰ Menu"):
        if st.button("Dashboard", width="stretch"):
            st.switch_page("pages/landing.py")
        if st.button("Listen", width="stretch"):
            st.switch_page("pages/listen.py")
        if st.button("Useful Tools", width="stretch"):
            st.switch_page("pages/tools.py")
        if st.button("Explore the Archive", width="stretch"):
            st.switch_page("pages/explore.py")


# -------------------------
# DATA LOADING (CACHED)
# -------------------------

def _data_file_mtimes():
    """Returns a tuple of last-modified times for all data files.
    Passing this into load_data() means the cache automatically
    invalidates whenever any of the underlying CSVs change."""
    files = ["band_archive.csv", "song_stats.csv", "song_metadata.csv", "metadata_jam.csv"]
    return tuple(os.path.getmtime(f) for f in files)


@st.cache_data
def _load_data_cached(_mtimes):
    df = pd.read_csv("band_archive.csv")
    song_stats = pd.read_csv("song_stats.csv")
    metadata = pd.read_csv("song_metadata.csv")
    jam_metadata = pd.read_csv("metadata_jam.csv")

    df["Date"] = pd.to_datetime(df["Date"])
    df["Year"] = df["Date"].dt.year

    song_stats = song_stats.merge(metadata, on="Title", how="left")

    return df, song_stats, metadata, jam_metadata


def load_data():
    return _load_data_cached(_data_file_mtimes())


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
# SETLIST RANDOMIZER
# -------------------------

SEGUE_BOOST = 8.0  # multiplier for songs with historical segue from previous song


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
    closers = find_closers(randomizer_df, allowed_titles)

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