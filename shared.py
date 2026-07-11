import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import random
import os
import re
import string
from urllib.parse import quote
from supabase import create_client, Client
import bcrypt

times_played_mult = 1.3  # multiplier for how much weight to give times played in overdue score

dead_weight_artists = ["Grateful Dead", "Jerry Garcia Band", "The Band", "Little Feat", "Phish", "The Rolling Stones", "Sam Cooke", "The Four Tops", "The Allman Brothers Band", "The Who"]
dead_weight_year = 2022

@st.cache_data
def load_all_recordings(_mtimes):
    """Load band_archive.csv including all takes, for the Listen page."""
    df = pd.read_csv("band_archive.csv")
    df["Date"] = pd.to_datetime(df["Date"])
    df["Year"] = df["Date"].dt.year
    return df

@st.cache_data
def get_show_list(_mtimes, type_filter):
    """Cached: only recomputes when the underlying CSVs change or the filter changes,
    instead of on every widget click."""
    df = load_all_recordings(_mtimes)
    performances = df.copy()
    performances["Show_Label"] = (
        performances["Date"].dt.strftime("%m/%d/%Y") + " — " + performances["Location"]
    )
    playable_shows = performances[performances["IA URL"].notna()]

    if type_filter == "Gigs":
        playable_shows = playable_shows[playable_shows["Type"] == "live"]
    elif type_filter == "Practices":
        playable_shows = playable_shows[playable_shows["Type"] == "practice"]

    unique_shows = (
        playable_shows.drop_duplicates(subset="Show_Label")
        .sort_values("Date", ascending=False)["Show_Label"]
        .tolist()
    )
    return performances, unique_shows


@st.cache_data
def get_playlist_for_show(_mtimes, show_label):
    """Cached per show — grouping only runs once per show, not once per rerun."""
    performances, _ = get_show_list(_mtimes, "All")
    show_tracks = performances[
        performances["Show_Label"] == show_label
    ].sort_values("Track Number").reset_index(drop=True)
    return group_tracks(show_tracks)

# -------------------------
# LOGIN INFO
# -------------------------

def get_supabase_client() -> Client:
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

def load_users_from_supabase():
    supabase = get_supabase_client()
    response = supabase.table("users").select("username, name, password_hash").execute()
    usernames = {
        row["username"]: {"name": row["name"], "password": row["password_hash"]}
        for row in response.data
    }
    return {
    "usernames": usernames,
    "pre_authorized": {"emails": []}
}

def create_user_in_supabase(username, name, password):
    supabase = get_supabase_client()
    existing = supabase.table("users").select("username").eq("username", username).execute()
    if existing.data:
        return False, "That username is already taken."
    password_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    supabase.table("users").insert({
        "username": username, "name": name, "password_hash": password_hash
    }).execute()
    return True, "Account created! Switch to the Log In tab."

# ------------------------
# PLAYLIST GENERATOR
# ------------------------

def group_tracks(show_tracks):
    """Groups consecutive tracks with identical duration (segues) into single entries.
    show_tracks must be sorted by Track Number, with Title/Duration/IA URL columns."""
    playlist = []
    i = 0
    while i < len(show_tracks):
        current = show_tracks.iloc[i]
        audio_url = current.get("IA URL")

        if pd.isna(audio_url):
            i += 1
            continue

        group_titles = [current["Title"]]
        j = i + 1
        while j < len(show_tracks) and show_tracks.iloc[j]["Duration"] == current["Duration"]:
            group_titles.append(show_tracks.iloc[j]["Title"])
            j += 1

        playlist.append({
            "label": " -> ".join(group_titles),
            "duration": current["Duration"],
            "url": audio_url,
        })
        i = j
    return playlist

def save_playlist_to_supabase(owner_username, playlist_name, tracks):
    supabase = get_supabase_client()
    existing = (
        supabase.table("playlists")
        .select("id")
        .eq("owner_username", owner_username)
        .eq("playlist_name", playlist_name)
        .execute()
    )
    if existing.data:
        return False, "You already have a playlist with that name."
    supabase.table("playlists").insert({
        "owner_username": owner_username,
        "playlist_name": playlist_name,
        "tracks": tracks,
    }).execute()
    return True, "Playlist saved!"

def load_playlists_from_supabase(owner_username):
    supabase = get_supabase_client()
    response = (
        supabase.table("playlists")
        .select("id, playlist_name, tracks")
        .eq("owner_username", owner_username)
        .execute()
    )
    return response.data

def delete_playlist_from_supabase(playlist_id):
    supabase = get_supabase_client()
    supabase.table("playlists").delete().eq("id", playlist_id).execute()

def update_playlist_in_supabase(playlist_id, playlist_name, tracks):
    """Overwrites an existing playlist's name and track list."""
    supabase = get_supabase_client()
    supabase.table("playlists").update({
        "playlist_name": playlist_name,
        "tracks": tracks,
    }).eq("id", playlist_id).execute()
    return True, "Playlist updated!"

def add_tracks_to_playlist(playlist_id, new_tracks):
    """Appends new_tracks (deduped) onto an existing playlist without
    touching the draft/save flow — used for the 'add from this show
    straight into a playlist' feature."""
    supabase = get_supabase_client()
    existing = supabase.table("playlists").select("tracks").eq("id", playlist_id).execute()
    if not existing.data:
        raise ValueError("Playlist not found.")
    current_tracks = existing.data[0]["tracks"]
    for track in new_tracks:
        if track not in current_tracks:
            current_tracks.append(track)
    supabase.table("playlists").update({"tracks": current_tracks}).eq("id", playlist_id).execute()
    return True, "Tracks added!"

# -------------------------
# SCANNER INFO
# -------------------------

manual_fixes = {
    "alma's phat mama": "alma's fat mama",
    "alma": "alma's fat mama",
    "alma's": "alma's fat mama",

    "goodnight": "and we bid you goodnight",
    "we bid you goodnight": "and we bid you goodnight",
    "wbygn": "and we bid you goodnight",

    "atoms": "atoms in pursuit",

    "biodtl": "beat it on down the line",

    "bott": "back on the train",

    "brokedown": "brokedown palace",

    "dialogue": "chatter",
    "post jam recap": "chatter",
    "post-jam recap": "chatter",
    "pjr": "chatter",
    "the last word": "chatter",
    "the post jam": "chatter",
    "the post": "chatter",

    "china cat": "china cat sunflower",
    "china": "china cat sunflower",

    "cold rain snow": "cold rain and snow",

    "cripple creek": "up on cripple creek",

    "cumberland": "cumberland blues",

    "dancin": "dancin in the street",
    "dancing": "dancin in the street",
    "dancing in the street": "dancin in the street",
    "dancing in the streets": "dancin in the street",
    "dancin in the streets": "dancin in the street",
    "dits": "dancin in the street",

    "dark star jam": "dark star",

    "dear mr fantasy": "dear mr. fantasy",

    "dixie down": "the night they drove old dixie down",

    "eyes": "eyes of the world",

    "fire": "fire on the mountain",
    "fotm": "fire on the mountain",

    "flas": "feel like a stranger",
    "feels like a stranger": "feel like a stranger",
    "stranger": "feel like a stranger",

    "fotd": "friend of the devil",

    "franklin": "franklin's tower",
    "franklins": "franklin's tower",
    "franklin's": "franklin's tower",

    "gdtrfb": "goin down the road feelin bad",
    "goin down the road feeling bad": "goin down the road feelin bad",
    "going down the road feeling bad": "goin down the road feelin bad",

    "schoolgirl": "good morning little schoolgirl",

    "how sweet it is (to be loved by you)": "how sweet it is",

    "rider": "i know you rider",

    "opening jam": "jam",
    "opening jam in a": "jam",
    "opening noodles": "jam",

    "johnny b goode": "johnny b. goode",

    "knockin lost john": "knockin' lost john",

    "good times": "let the good times roll",
    "good times roll": "let the good times roll",

    "cleveland": "look out cleveland",

    "muncle": "me and my uncle",
    "me & my uncle": "me and my uncle",

    "half step": "mississippi half-step uptown toodeloo",
    "half-step": "mississippi half-step uptown toodeloo",
    "mississippi": "mississippi half-step uptown toodeloo",
    "mississippi half step uptown toodeloo": "mississippi half-step uptown toodeloo",
    "mississippi half-step": "mississippi half-step uptown toodeloo",
    "mississippi half step": "mississippi half-step uptown toodeloo",

    "new minglewood": "new minglewood blues",

    "new speedway": "new speedway boogie",

    "nfa": "not fade away",

    "osop": "other side of paradise",

    "playin": "playin in the band",
    "pitb": "playin in the band",
    "playing in the band": "playin in the band",

    "push": "push comes to shove",

    "samson": "samson and delilah",

    "scarlet": "scarlet begonias",

    "shakedown": "shakedown street",

    "sitting in limbo": "sitting here in limbo",

    "speak up": "speak up!",

    "tangled": "tangled up in blue",
    "tangled up": "tangled up in blue",

    "jed": "tennessee jed",

    "terrapin": "terrapin station",

    "music": "the music never stopped",
    "music never stopped": "the music never stopped",
    "tmns": "the music never stopped",

    "other one": "the other one",

    "weight": "the weight",

    "tleo": "they love each other",

    "lovelight": "turn on your lovelight",

    "viola": "viola lee blues",
    "viola lee": "viola lee blues",

    "way back": "way back home",

    "west la": "west l.a. fadeaway",
    "west la fadeaway": "west l.a. fadeaway",

    "wolfman": "wolfman's brother",
    "wolfman's": "wolfman's brother",

    "walcott": "w.s. walcott medicine show",
    "ws walcott": "w.s. walcott medicine show",
    "ws walcott medicine show": "w.s. walcott medicine show",
}

junk_terms = [
    " take 2",
    " take 3",
    " demo",
    "(voice lesson)",
    " (ending)",
    " (opening)",
    " ending",
    " intro",
    " - master",
    "(soundcheck)",
    " (2)", " (3)", " (4)", " (5)", " (1)",
    " (6)", " (7)", " (8)", " (9)",
    "(instrumental)",
    "(dave guitar)",
    "(dave vox)",
    "(chris vox)",
    "(matt guitar)"
]

segue_fixes = {
    "scarlet fire": "scarlet_ fire",
    "china rider": "china_ rider",
    "china cat rider": "china_ rider",
    "help slip frank": "help_slip_frank",
    "walcott cumberland": "walcott_ cumberland"
}

def clean_title(raw):
    if not isinstance(raw, str):
        return ""
    title = raw.strip().lower()
    title = title.replace("  ", " ")
    title = re.sub(r"\s+jam$", "", title)
    if title in manual_fixes:
        title = manual_fixes[title]
    return string.capwords(title)

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

def dank_playlist_player(show_label, tracks):
    """Render a single playlist player with auto-advance.

    tracks: list of dicts, each with keys: label, subtitle, url
    """
    import streamlit.components.v1 as components
    import json

    tracks_json = json.dumps(tracks)
    height = 90 + len(tracks) * 46 + 40

    components.html(f"""
    <style>
    body {{
        margin: 0;
        font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
    }}
    .dank-playlist-card {{
        background-color: #1c1b1a;
        border-radius: 14px;
        border-bottom: 3px solid #d4a24c;
        padding: 20px 20px 14px 20px;
        box-sizing: border-box;
    }}
    .dank-playlist-title {{
        color: #ece7de;
        font-size: 16px;
        font-weight: 700;
        letter-spacing: -0.01em;
        margin-bottom: 12px;
    }}
    .dank-playlist-card audio {{
        width: 100%;
        border-radius: 8px;
        outline: none;
        margin-bottom: 14px;
    }}
    .dank-track-list {{
        display: flex;
        flex-direction: column;
        gap: 2px;
    }}
    .dank-track {{
        display: flex;
        align-items: baseline;
        gap: 10px;
        padding: 10px 10px;
        border-radius: 6px;
        cursor: pointer;
        border-bottom: 2px solid transparent;
        transition: background-color 0.15s ease;
    }}
    .dank-track:hover {{
        background-color: #2a2826;
    }}
    .dank-track.active {{
        border-bottom: 2px solid #d4a24c;
        background-color: #2a2826;
    }}
    .dank-track-num {{
        color: #7a8b6f;
        font-size: 12px;
        font-weight: 600;
        min-width: 18px;
    }}
    .dank-track-title {{
        color: #ece7de;
        font-size: 14px;
        font-weight: 500;
        flex: 1;
    }}
    .dank-track.active .dank-track-title {{
        color: #d4a24c;
        font-weight: 700;
    }}
    .dank-track-duration {{
        color: #8a857c;
        font-size: 12px;
    }}
    </style>
    <div class="dank-playlist-card">
        <div class="dank-playlist-title">{show_label}</div>
        <audio id="dank-player" controls preload="none"></audio>
        <div class="dank-track-list" id="dank-track-list"></div>
    </div>
    <script>
    const tracks = {tracks_json};
    const player = document.getElementById('dank-player');
    const listEl = document.getElementById('dank-track-list');
    let currentIndex = 0;

    function renderList() {{
        listEl.innerHTML = '';
        tracks.forEach((track, i) => {{
            const row = document.createElement('div');
            row.className = 'dank-track' + (i === currentIndex ? ' active' : '');
            row.innerHTML = `
                <div class="dank-track-num">${{i + 1}}</div>
                <div class="dank-track-title">${{track.label}}</div>
                <div class="dank-track-duration">${{track.duration || ''}}</div>
            `;
            row.addEventListener('click', () => loadTrack(i, true));
            listEl.appendChild(row);
        }});
    }}

    function loadTrack(index, autoplay) {{
        if (index < 0 || index >= tracks.length) return;
        currentIndex = index;
        player.src = tracks[index].url;
        if (autoplay) {{
            player.play().catch(() => {{}});
        }}
        renderList();
    }}

    player.addEventListener('ended', () => {{
        if (currentIndex + 1 < tracks.length) {{
            loadTrack(currentIndex + 1, true);
        }}
    }});

    loadTrack(0, false);
    </script>
    """, height=height)

# -------------------------
# MOBILE KEYBOARD SUPPRESSION FOR SELECTBOX
# -------------------------

def suppress_selectbox_keyboard():
    """Stops the mobile virtual keyboard from popping up when tapping
    a st.selectbox, while keeping tap-to-open-dropdown behavior intact."""
    import streamlit.components.v1 as components
    components.html("""
    <script>
    function suppressKeyboard() {
        const inputs = window.parent.document.querySelectorAll(
            'div[data-baseweb="select"] input'
        );
        inputs.forEach((input) => {
            input.setAttribute('inputmode', 'none');
            input.setAttribute('readonly', 'readonly');
        });
    }
    suppressKeyboard();
    const observer = new MutationObserver(suppressKeyboard);
    observer.observe(window.parent.document.body, {childList: true, subtree: true});
    </script>
    """, height=0)

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
# FORCE HORIZ ROW/PLAYLIST FORMATTING
# -------------------------

def force_columns_horizontal():
    """Injects CSS once per page load so st.columns() rows never stack
    vertically on mobile, regardless of viewport width."""
    st.markdown("""
    <style>
    div[data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important;
        gap: 0.4rem !important;
    }
    div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {
        width: auto !important;
        min-width: 0 !important;
        flex: initial !important;
    }
    </style>
    """, unsafe_allow_html=True)

def style_playlist_draft_rows():
    """Scoped CSS for the playlist draft rows — keeps buttons fixed-width and
    pinned to the right, while letting long track titles wrap onto multiple
    lines instead of being cut off."""
    st.markdown("""
    <style>
    .st-key-playlist_draft_rows div[data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap !important;
        align-items: flex-start !important;
        gap: 0.3rem !important;
    }
    .st-key-playlist_draft_rows div[data-testid="stColumn"] {
        min-width: 0 !important;
    }
    .st-key-playlist_draft_rows div[data-testid="stColumn"]:first-child {
        flex: 1 1 auto !important;
    }
    .st-key-playlist_draft_rows div[data-testid="stColumn"]:not(:first-child) {
        flex: 0 0 auto !important;
        width: 38px !important;
    }
    .st-key-playlist_draft_rows button {
        padding: 0.25rem 0.4rem !important;
        min-width: 0 !important;
        width: 100% !important;
    }
    .dank-track-label {
        white-space: normal;
        word-break: break-word;
        font-size: 14px;
        padding-top: 0.35rem;
        line-height: 1.3;
    }
    </style>
    """, unsafe_allow_html=True)

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
    df = pd.read_csv("band_archive.csv", dtype={"Duration": str})
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

def ranked_table(display_df, sort_col=None, ascending=False, rename=None, columns=None, presorted=False):
    """Sort (unless presorted), rename, add rank, and return a dataframe ready for st.dataframe."""
    out = display_df if presorted else display_df.sort_values(sort_col, ascending=ascending)
    out = out.copy()
    if rename:
        out = out.rename(columns=rename)
    if columns:
        out = out[columns]
    out = out.reset_index(drop=True)
    out.insert(0, "Rank", range(1, len(out) + 1))
    return out

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