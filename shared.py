import base64
import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import random
import os
import re
import string
import html as _html
import urllib.parse
import altair as alt
import numpy as np
from streamlit_js_eval import streamlit_js_eval
from urllib.parse import quote
from supabase import create_client, Client
from pathlib import Path

STATIC = Path(__file__).parent / "static"

times_played_mult = 1.3  # multiplier for how much weight to give times played in overdue score

dead_weight_artists = ["Grateful Dead", "David Bowie", "Jerry Garcia Band", 
                       "The Band", "Little Feat", "Phish", "The Rolling Stones", 
                       "Sam Cooke", "The Four Tops", "The Allman Brothers Band", "The Who", 
                       "Sublime", "AC/DC", "The Doors", "The Beatles", "Pink Floyd", "Led Zeppelin",
                       "Funkadelic", "The Beach Boys", "Velvet Underground", "Herbie Hancock", "Talking Heads",
                       "Stevie Ray Vaughan", "Jimi Hendrix", "Traditional", "Lynyrd Skynyrd", "Traffic", "Jackson 5",
                       "Otis Redding", "Tommy James", "Fleetwood Mac", "Dr. Dog", "Neil Young", "Bob Seger", "Levon Helm",
                       "Hall And Oates", "The Staple Singers", "Eric Clapton", "The 5th Dimension", "The Doobie Brothers", "The Meters",
                       "Van Morrison", "Brewer & Shipley", "Billy Preston", "Creedence Clearwater Revival", "Paul McCartney", "Assembly of Dust", ""
                       "Bob Dylan", "Otis Day & The Knights", "Ray Charles", "The Supremes"
                       ]
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

def login_screen():
    st.header("🔒 Danktuary Archive")
    st.subheader("This app is private. Please log in.")
    st.button("Log in with Google", on_click=st.login)

def get_supabase():
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

def get_display_name(email):
    try:
        result = get_supabase().table("profiles").select("display_name").eq("email", email).execute()
        if result.data:
            return result.data[0]["display_name"]
    except Exception:
        pass
    return None

def set_display_name(email, display_name):
    get_supabase().table("profiles").upsert({"email": email, "display_name": display_name}).execute()

def get_supabase_client() -> Client:
    return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])

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
# DANK STYLE
# -------------------------

def img_b64(filename):
    return base64.b64encode((STATIC / filename).read_bytes()).decode()

def dank_theme():
    st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;800&display=swap');

/* =========================================================
   TOKENS + BASE
   ========================================================= */
:root {
    --dw-ink:#151412; --dw-cream:#f1ead8; --dw-panel:#201e1b;
    --dw-green:#00FF00; --dw-green-deep:#0a5c0a;
    --dw-marigold:#ffb81c; --dw-tomato:#ff5a4a; --dw-violet:#8b5cf6;
}
html, body, [class*="st-"], .stMarkdown { font-family:'Poppins', sans-serif; }

/* restore Streamlit's icon font */
[data-testid="stIconMaterial"], .material-symbols-rounded, .material-icons {
    font-family:"Material Symbols Rounded" !important;
}

/* =========================================================
   NATIVE WIDGETS
   ========================================================= */
h3, h4 { color:var(--dw-marigold) !important; font-weight:800 !important; letter-spacing:-0.01em; }

[data-testid="stExpander"] {
    background:var(--dw-panel);
    border:2px solid rgba(241,234,216,.25) !important;
    border-radius:8px !important;
    box-shadow:4px 4px 0 var(--dw-marigold);
}
[data-testid="stMetricValue"] { color:var(--dw-green); font-weight:800; }
[data-testid="stMetricLabel"] p { text-transform:uppercase; letter-spacing:.06em; font-size:12px; }

/* regular buttons */
.stButton > button { border-radius:6px; font-weight:600; border-width:2px; }

button[data-testid="stBaseButton-primary"], button[kind="primary"] {
    background:var(--dw-green) !important;
    border:2px solid var(--dw-ink) !important;
    box-shadow:3px 3px 0 var(--dw-marigold);
}
button[data-testid="stBaseButton-primary"] p, button[kind="primary"] p {
    color:var(--dw-ink) !important; font-weight:800 !important;
}
button[data-testid="stBaseButton-secondary"], button[kind="secondary"] {
    background:var(--dw-panel) !important;
    border:2px solid rgba(241,234,216,.35) !important;
}
button[data-testid="stBaseButton-secondary"] p, button[kind="secondary"] p {
    color:var(--dw-cream) !important;
}

/* =========================================================
   HEADER
   ========================================================= */
.dank-header {
    position:relative; overflow:hidden;
    background:var(--dw-ink);
    border:4px solid var(--dw-green); border-radius:8px;
    box-shadow:6px 6px 0 var(--dw-marigold);
    padding:18px 20px; margin-bottom:22px; min-height:100px;
}
.dank-header-title { color:var(--dw-green); font-size:34px; font-weight:800;
                     letter-spacing:-0.02em; line-height:1; }
.dank-header-subtitle { color:var(--dw-cream); font-size:13px; font-weight:600;
                        text-transform:uppercase; letter-spacing:.1em; margin-top:6px; }
.dank-header-mascot {
    position:absolute; right:16px; top:50%; transform:translateY(-50%);
    height:calc(100% - 20px); width:auto; max-width:none; object-fit:contain;
}
@media (max-width:600px){
    .dank-header { min-height:110px; }
    .dank-header-mascot { height:calc(100% - 16px); right:8px; }
}

/* =========================================================
   STAT CARDS
   ========================================================= */
.dank-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; }
.dank-card {
    position:relative;
    background:var(--dw-cream); color:var(--dw-ink);
    border:3px solid var(--dw-ink); border-radius:10px;
    box-shadow:5px 5px 0 var(--dw-green);
    padding:20px 18px 16px 18px; margin-bottom:14px;
}
.dank-card::before {
    content:""; position:absolute; inset:5px;
    border:2px solid var(--dw-ink); border-radius:6px; pointer-events:none;
}
.dank-card::after {
    content:""; position:absolute; inset:0; pointer-events:none;
    background:
        radial-gradient(circle at 12px 12px, var(--dw-ink) 2px, transparent 2.5px),
        radial-gradient(circle at calc(100% - 12px) 12px, var(--dw-ink) 2px, transparent 2.5px),
        radial-gradient(circle at 12px calc(100% - 12px), var(--dw-ink) 2px, transparent 2.5px),
        radial-gradient(circle at calc(100% - 12px) calc(100% - 12px), var(--dw-ink) 2px, transparent 2.5px);
}
.dank-card:nth-child(4n+2) { box-shadow:5px 5px 0 var(--dw-marigold); }
.dank-card:nth-child(4n+3) { box-shadow:5px 5px 0 var(--dw-tomato); }
.dank-card:nth-child(4n+4) { box-shadow:5px 5px 0 var(--dw-violet); }
.dank-card-value { color:var(--dw-ink); font-size:26px; font-weight:800; line-height:1.1; overflow-wrap:anywhere; }
.dank-card-accent { color:var(--dw-green-deep); }
.dank-card-label { color:#555; font-size:12px; font-weight:600;
                   text-transform:uppercase; letter-spacing:.06em; margin-top:4px; }

/* =========================================================
   CALLOUT
   ========================================================= */
.dank-callout {
    display:flex; align-items:center; gap:14px;
    background:var(--dw-panel); border:3px solid var(--dw-marigold);
    border-radius:8px; padding:10px 14px; margin:8px 0;
    color:var(--dw-cream); font-weight:800; line-height:1.3;
}
.dank-callout img { height:64px; width:auto; flex-shrink:0; }
.dank-callout-sub { font-weight:500; font-size:14px; }
.dank-callout b { color:var(--dw-green); font-weight:800; }

/* =========================================================
   ROAD SIGNS: ARROWS
   ========================================================= */
.dank-sign { display:inline-block; margin:8px 0 16px; }
.dank-sign-edge  { background:var(--dw-ink);   padding:4px; }
.dank-sign-rim   { background:var(--dw-cream); padding:4px; }
.dank-sign-line  { background:var(--dw-ink);   padding:2px; }
.dank-sign-inner {
    position:relative; background:var(--dw-marigold); color:var(--dw-ink);
    font-weight:800; font-size:20px; line-height:1.1;
    text-transform:uppercase; letter-spacing:.04em;
}
.dank-sign-inner::after { content:""; position:absolute; inset:0; pointer-events:none; }
.dank-sign-sm .dank-sign-inner { font-size:15px; }

.dank-sign-right :is(.dank-sign-edge,.dank-sign-rim,.dank-sign-line,.dank-sign-inner) {
    clip-path:polygon(0 0, calc(100% - 22px) 0, 100% 50%, calc(100% - 22px) 100%, 0 100%);
}
.dank-sign-left :is(.dank-sign-edge,.dank-sign-rim,.dank-sign-line,.dank-sign-inner) {
    clip-path:polygon(22px 0, 100% 0, 100% 100%, 22px 100%, 0 50%);
}
.dank-sign-right .dank-sign-inner { padding:10px 38px 10px 20px; }
.dank-sign-left  .dank-sign-inner { padding:10px 20px 10px 38px; }
.dank-sign-right.dank-sign-sm .dank-sign-inner { padding:8px 32px 8px 18px; }
.dank-sign-left.dank-sign-sm  .dank-sign-inner { padding:8px 18px 8px 32px; }

.dank-sign-right .dank-sign-inner::after {
    background:
        radial-gradient(circle at 9px 9px, var(--dw-ink) 2px, transparent 2.5px),
        radial-gradient(circle at 9px calc(100% - 9px), var(--dw-ink) 2px, transparent 2.5px),
        radial-gradient(circle at calc(100% - 12px) 50%, var(--dw-ink) 2px, transparent 2.5px);
}
.dank-sign-left .dank-sign-inner::after {
    background:
        radial-gradient(circle at calc(100% - 9px) 9px, var(--dw-ink) 2px, transparent 2.5px),
        radial-gradient(circle at calc(100% - 9px) calc(100% - 9px), var(--dw-ink) 2px, transparent 2.5px),
        radial-gradient(circle at 12px 50%, var(--dw-ink) 2px, transparent 2.5px);
}
.dank-sign-left { float:right; }

/* =========================================================
   ROAD SIGNS: HEX LABEL (not clickable)
   ========================================================= */
.dank-hex { display:block; width:100%; margin:0; }
.dank-hex :is(.dank-sign-edge,.dank-sign-rim,.dank-sign-line,.dank-sign-inner) {
    clip-path:polygon(18px 0, calc(100% - 18px) 0, 100% 50%, calc(100% - 18px) 100%, 18px 100%, 0 50%);
}
.dank-hex .dank-sign-inner {
    padding:6px 34px; text-align:center; font-size:14px; font-weight:600;
    text-transform:none; letter-spacing:.01em;
}
.dank-hex .dank-sign-inner b { font-weight:800; }
.dank-hex .dank-sign-inner::after {
    background:
        radial-gradient(circle at 14px 50%, var(--dw-ink) 2px, transparent 2.5px),
        radial-gradient(circle at calc(100% - 14px) 50%, var(--dw-ink) 2px, transparent 2.5px);
}
div[data-testid="stElementContainer"]:has(.dank-hex),
div[data-testid="stMarkdownContainer"]:has(.dank-hex) { margin:0 !important; padding:0 !important; }

/* =========================================================
   BUTTONS
   Default = dark panel with cream text and cream rivets.
   Primary (selected) = green with ink text and ink rivets.
   ========================================================= */
.stButton > button {
    --rivet: var(--dw-cream);
    background-color:var(--dw-panel) !important;
    background-image:
        radial-gradient(circle at 11px 50%, var(--rivet) 2.5px, transparent 3px),
        radial-gradient(circle at calc(100% - 11px) 50%, var(--rivet) 2.5px, transparent 3px) !important;
    border:3px solid rgba(241,234,216,.35) !important;
    border-radius:8px !important;
    box-shadow:4px 4px 0 var(--dw-marigold) !important;
    min-height:44px; padding:6px 28px !important;
    transition:transform .08s ease, box-shadow .08s ease, filter .08s ease;
}
.stButton > button p {
    color:var(--dw-cream) !important; font-weight:800 !important;
    font-size:15px; line-height:1.2; margin:0;
}
.stButton > button:hover {
    transform:translate(-1px,-1px);
    box-shadow:5px 5px 0 var(--dw-marigold) !important;
    filter:brightness(1.1);
}
.stButton > button:active {
    transform:translate(3px,3px);
    box-shadow:1px 1px 0 var(--dw-marigold) !important;
}
.stButton > button:focus-visible { outline:3px solid var(--dw-green); outline-offset:2px; }
.stButton > button:disabled {
    opacity:.45; box-shadow:none !important; transform:none; cursor:not-allowed;
}

/* selected / primary */
.stButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    --rivet: var(--dw-ink);
    background-color:var(--dw-green) !important;
    border-color:var(--dw-ink) !important;
}
.stButton > button[kind="primary"] p,
.stButton > button[data-testid="stBaseButton-primary"] p {
    color:var(--dw-ink) !important;
}

/* compact buttons in the playlist draft rows (up / down / remove): no rivets */
div[class*="st-key-playlist_draft_rows"] .stButton > button {
    background-image:none !important;
    min-height:36px; padding:0 !important;
    box-shadow:2px 2px 0 var(--dw-marigold) !important;
}

/* tab rows (container key starts with tabs_): 4 across on desktop, 2x2 on phones */
div[class*="st-key-tabs_"] [data-testid="stHorizontalBlock"] {
    display:grid !important;
    grid-template-columns:repeat(auto-fit, minmax(150px, 1fr));
    gap:0.9rem !important;
}
div[class*="st-key-tabs_"] [data-testid="stColumn"] {
    width:auto !important; min-width:0 !important; flex:none !important;
}
div[class*="st-key-tabs_"] .stButton > button { padding:6px 18px !important; min-height:48px; }
div[class*="st-key-tabs_"] .stButton > button p {
    font-size:15px; line-height:1.15;
    white-space:nowrap;
    overflow-wrap:normal !important; word-break:normal !important; hyphens:none;
}

/* single-line button rows (container key starts with btnrow_): never wrap, text scales */
div[class*="st-key-btnrow_"] .stButton > button {
    padding:6px 22px !important; min-height:44px;
}
div[class*="st-key-btnrow_"] .stButton > button > div {
    width:100%; min-width:0; justify-content:center;
}
div[class*="st-key-btnrow_"] .stButton > button p {
    font-size:clamp(11px, 2.6vw, 14px);
    line-height:1.15; text-align:center;
    white-space:normal;                                 /* wrap at spaces instead of clipping */
    overflow-wrap:normal; word-break:normal; hyphens:none;
    text-wrap:balance;
}

@media (max-width:640px) {
    div[class*="st-key-tabs_"] [data-testid="stColumn"] {
        flex:0 0 calc(50% - 0.375rem) !important;
    }
    div[class*="st-key-tabs_"] .stButton > button p { font-size:14px; }
}

[data-testid="stLinkButton"] a {
    --rivet: var(--dw-cream);
    background-color:var(--dw-panel) !important;
    background-image:
        radial-gradient(circle at 11px 50%, var(--rivet) 2.5px, transparent 3px),
        radial-gradient(circle at calc(100% - 11px) 50%, var(--rivet) 2.5px, transparent 3px) !important;
    border:3px solid rgba(241,234,216,.35) !important;
    border-radius:8px !important;
    box-shadow:4px 4px 0 var(--dw-marigold) !important;
    min-height:44px; padding:6px 28px !important;
    text-decoration:none;
}
[data-testid="stLinkButton"] a p { color:var(--dw-cream) !important; font-weight:800 !important; margin:0; }

/* =========================================================
   TABLES + LISTS
   ========================================================= */
.linked-table, .song-history-table, .perf-history-table, .setlist-table {
    width:100%; border-collapse:collapse; font-size:14px;
}
:is(.linked-table, .song-history-table, .perf-history-table, .setlist-table) :is(th, td) {
    text-align:left; padding:6px 10px;
    border-bottom:1px solid rgba(128,128,128,0.3);
}
:is(.linked-table, .song-history-table, .perf-history-table, .setlist-table) a {
    color:var(--dw-green); text-decoration:none;
}
:is(.linked-table, .song-history-table, .perf-history-table, .setlist-table) a:hover {
    text-decoration:underline;
}

.table-scroll { max-height:520px; overflow:auto;
                border:2px solid rgba(241,234,216,.25); border-radius:8px; }
.table-scroll .linked-table th { position:sticky; top:0; background:var(--dw-panel); color:var(--dw-marigold); }

.song-browse {
    max-height:320px; overflow-y:auto; overscroll-behavior:contain;
    background:var(--dw-panel); border:2px solid rgba(241,234,216,.25);
    border-radius:8px; padding:6px 14px; margin:8px 0;
    scrollbar-width:thin; scrollbar-color:var(--dw-marigold) transparent;
    /* fade-out shadows at the top/bottom edges that disappear when you reach the end */
    background:
        linear-gradient(var(--dw-panel) 30%, transparent) top / 100% 28px no-repeat local,
        linear-gradient(transparent, var(--dw-panel) 70%) bottom / 100% 28px no-repeat local,
        linear-gradient(rgba(255,184,28,.35), transparent) top / 100% 12px no-repeat scroll,
        linear-gradient(transparent, rgba(255,184,28,.35)) bottom / 100% 12px no-repeat scroll,
        var(--dw-panel);
}
.song-browse::-webkit-scrollbar { width:8px; }
.song-browse::-webkit-scrollbar-track { background:transparent; }
.song-browse::-webkit-scrollbar-thumb { background:var(--dw-marigold); border-radius:4px; }
.song-browse a { display:block; padding:8px 2px; color:var(--dw-green); text-decoration:none;
                 border-bottom:1px solid rgba(128,128,128,0.2); }
.song-browse a:hover { text-decoration:underline; }
.song-browse-hint { color:var(--dw-marigold); font-size:12px; font-weight:600;
                    text-transform:uppercase; letter-spacing:.06em; margin:4px 0 0; }

/* =========================================================
   TRACKLIST ROWS (container key starts with trackrow_ / trackon_)
   ========================================================= */
div[class*="st-key-trackrow_"] .stButton > button,
div[class*="st-key-trackon_"] .stButton > button {
    justify-content:flex-start; text-align:left;
    min-height:44px; padding:8px 14px !important;
    border-radius:6px !important; border:2px solid rgba(241,234,216,.25) !important;
    border-left:6px solid rgba(241,234,216,.25) !important;
    background:var(--dw-panel) !important; box-shadow:none !important;
}
div[class*="st-key-trackrow_"] .stButton > button > div,
div[class*="st-key-trackon_"] .stButton > button > div { justify-content:flex-start; width:100%; }
div[class*="st-key-trackrow_"] .stButton > button p,
div[class*="st-key-trackon_"] .stButton > button p {
    text-align:left; margin:0; font-size:15px; line-height:1.25;
    color:var(--dw-cream) !important; font-weight:500 !important;
}
div[class*="st-key-trackrow_"] .stButton > button:hover {
    border-left-color:var(--dw-marigold) !important; background:#2c2926 !important;
}

/* active row */
div[class*="st-key-trackon_"] .stButton > button {
    border-color:var(--dw-green) !important; border-left-color:var(--dw-green) !important;
    background:#2c2926 !important; box-shadow:3px 3px 0 var(--dw-marigold) !important;
}
div[class*="st-key-trackon_"] .stButton > button p {
    color:var(--dw-green) !important; font-weight:800 !important;
}
div[class*="st-key-trackon_"] .stButton > button:disabled { opacity:1; cursor:default; }

/* tighten the gap between rows */
div[class*="st-key-trackrow_"], div[class*="st-key-trackon_"] { margin-bottom:-0.5rem; }

/* setlist randomizer rows */
div[class*="st-key-setlist_rows"] [data-testid="stCheckbox"] {
    background:var(--dw-panel);
    border:2px solid rgba(241,234,216,.25);
    border-left:6px solid rgba(241,234,216,.25);
    border-radius:6px; padding:8px 12px;
}
div[class*="st-key-setlist_rows"] [data-testid="stCheckbox"] p {
    color:var(--dw-cream); font-weight:600; font-size:15px;
}
div[class*="st-key-setlist_rows"] [data-testid="stCheckbox"]:has(input:checked) {
    border-color:var(--dw-green); border-left-color:var(--dw-green);
    background:#2c2926;
}
div[class*="st-key-setlist_rows"] [data-testid="stCheckbox"]:has(input:checked) p {
    color:var(--dw-green); font-weight:800;
}
</style>
""", unsafe_allow_html=True)

def dank_header(subtitle="The Danktuary Archive Explorer", anchor_id="dankapp-top",
                  mascot="skel_walk_dark.png"):
      mascot_html = ""
      try:
          mascot_html = f'<img class="dank-header-mascot" src="data:image/png;base64,{img_b64(mascot)}">'
      except FileNotFoundError:
          pass
      st.markdown(f"""
      <div class="dank-header" id="{anchor_id}">
          <div class="dank-header-title">DankApp</div>
          <div class="dank-header-subtitle">{subtitle}</div>
          {mascot_html}
      </div>
      """, unsafe_allow_html=True)

def dank_callout(text, subtext=None, img="skel_walk_dark.png"):
    def fmt(s):
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _html.escape(s))
        return s.replace("\n", "<br>")

    body = fmt(text)
    if subtext:
        body += f'<br><span class="dank-callout-sub">{fmt(subtext)}</span>'

    try:
        icon = f'<img src="data:image/png;base64,{img_b64(img)}">' if img else ""
    except FileNotFoundError:
        icon = ""

    st.markdown(
        f'<div class="dank-callout">{icon}<div>{body}</div></div>',
        unsafe_allow_html=True,
    )

def dank_sign(text, direction="right", size="md"):
    st.markdown(
        f'<div class="dank-sign dank-sign-{direction} dank-sign-{size}"><div class="dank-sign-edge">'
        f'<div class="dank-sign-rim"><div class="dank-sign-line">'
        f'<div class="dank-sign-inner">{_html.escape(text)}</div>'
        f'</div></div></div></div>',
        unsafe_allow_html=True,
    )

def dank_hex(text, subtext=None):
    def fmt(s):
        s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _html.escape(s))
        return s.replace("\n", "<br>")
    body = fmt(text)
    if subtext:
        body += f'<br><span class="dank-hex-sub">{fmt(subtext)}</span>'
    st.markdown(
        f'<div class="dank-sign dank-hex"><div class="dank-sign-edge">'
        f'<div class="dank-sign-rim"><div class="dank-sign-line">'
        f'<div class="dank-sign-inner">{body}</div>'
        f'</div></div></div></div>',
        unsafe_allow_html=True,
    )

def dank_chart(chart):
    """Applies the Dead Weight look (fonts, colors) to an Altair chart."""
    return (
        chart
        .configure(font="Poppins")
        .configure_axis(
            grid=False, labelColor="#9a9488", tickColor="#9a9488",
            titleColor="#f1ead8", labelFont="Poppins", titleFont="Poppins",
            labelFontSize=12, titleFontSize=12, titleFontWeight=600,
        )
        .configure_title(
            font="Poppins", color="#f1ead8", fontSize=15, fontWeight=800,
        )
        .configure_view(strokeWidth=0)
    )

def dank_footer(text="Danktuary Archive Version: 3.0 | Believe it if you need it"):
    st.markdown(f"""
    <style>
    .dank-footer {{ text-align:center; margin-top:40px; }}
    .dank-footer-line {{
        border-bottom:4px solid #00FF00;
        height:80px;
        overflow:hidden;
        position:relative;
    }}
    .dank-footer-line img {{
        position:absolute; bottom:-2px; left:50%;
        height:80px; margin-left:-40px;
        transform-origin:50% 100%;
        animation:
            dank-walk 35s linear infinite,
            dank-bob .5s ease-in-out infinite alternate;
    }}
    @keyframes dank-walk {{
        from {{translate:55vw 0; }}
        to   {{ translate:-55vw 0; }}
    }}
    @keyframes dank-bob {{
        from {{ transform:translateY(0) rotate(-3deg); }}
        to   {{ transform:translateY(-4px) rotate(3deg); }}
    }}
    @media (prefers-reduced-motion: reduce) {{
        .dank-footer-line img {{ animation:none; }}
    }}
    .dank-footer-text {{ color:#888; font-size:13px; margin-top:10px; }}
    </style>
    <div class="dank-footer">
        <div class="dank-footer-line">
            <img src="data:image/png;base64,{img_b64('skel_walk_dark.png')}">
        </div>
        <div class="dank-footer-text">{text}</div>
    </div>
    """, unsafe_allow_html=True)

def linked_table(df, song_col="Title", show_col=None, show_loc_col=None,
                 show_cols=None, scroll=True):
    """Themed HTML table. song_col values link to /stats?song=...
    show_cols maps a date column to the (hidden) column holding that
    date's location, e.g. {"Last Played": "Last Location"}, and links
    the date to /stats?show=<date — location>."""
    links = dict(show_cols or {})
    if show_col and show_loc_col:
        links[show_col] = show_loc_col
    hidden = set(links.values())

    cols = [c for c in df.columns if c not in hidden]
    head = "".join(f"<th>{_html.escape(str(c))}</th>" for c in cols)

    rows = []
    for _, r in df.iterrows():
        tds = []
        for c in cols:
            v = str(r[c])
            cell = _html.escape(v)
            if c == song_col:
                cell = f'<a href="/stats?song={urllib.parse.quote(v, safe="")}" target="_self">{cell}</a>'
            elif c in links:
                label = f"{v} — {r[links[c]]}"
                cell = f'<a href="/stats?show={urllib.parse.quote(label, safe="")}" target="_self">{cell}</a>'
            tds.append(f"<td>{cell}</td>")
        rows.append(f"<tr>{''.join(tds)}</tr>")

    wrap_open = '<div class="table-scroll">' if scroll else "<div>"
    st.markdown(
        f'{wrap_open}<table class="linked-table"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(rows)}</tbody></table></div>',
        unsafe_allow_html=True,
    )

# -------------------------
# AUDIO PLAYER
# -------------------------

def dank_playlist_player(show_label, tracks):
    """Render a single playlist player with auto-advance.

    tracks: list of dicts, each with keys: label, duration, url
    """
    import streamlit.components.v1 as components
    import json
    import html as _html

    # "</" inside the JSON could close the script tag early
    tracks_json = json.dumps(tracks).replace("</", "<\\/")
    safe_label = _html.escape(show_label)
    js_title = json.dumps(show_label).replace("</", "<\\/")

    try:
        icon_tag = f'<img class="dank-playlist-icon" src="data:image/png;base64,{img_b64("icon.png")}">'
    except FileNotFoundError:
        icon_tag = ""

    components.html(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;800&display=swap');
    body {{
        margin: 0;
        padding: 0 8px 8px 0;
        font-family: 'Poppins', sans-serif;
        background: transparent;
    }}
    .dank-playlist-card {{
        position: relative;
        background: #201e1b;
        border: 3px solid #00FF00;
        border-radius: 8px;
        box-shadow: 5px 5px 0 #ffb81c;
        padding: 18px 18px 12px 18px;
        box-sizing: border-box;
    }}
    .dank-playlist-icon {{
        position: absolute;
        top: 12px;
        right: 12px;
        height: 44px;
        width: 44px;
        object-fit: contain;
    }}
    .dank-playlist-title {{
        color: #00FF00;
        font-size: 17px;
        font-weight: 800;
        letter-spacing: -0.01em;
        margin-bottom: 12px;
        padding-right: 56px;
    }}
    .dank-playlist-card audio {{
        width: 100%;
        border-radius: 8px;
        outline: none;
        margin-bottom: 6px;
        color-scheme: dark;
    }}
    .dank-status {{
        min-height: 18px;
        margin-bottom: 8px;
        font-size: 12px;
        font-weight: 600;
        color: #ffb81c;
    }}
    .dank-status a {{ color: #00FF00; }}
    .dank-status.err {{ color: #ff5a4a; }}
    .dank-track-list {{
        display: flex;
        flex-direction: column;
        gap: 2px;
        max-height: 300px;
        overflow-y: auto;
        padding-right: 4px;
    }}
    .dank-track-list::-webkit-scrollbar {{ width: 6px; }}
    .dank-track-list::-webkit-scrollbar-track {{ background: transparent; }}
    .dank-track-list::-webkit-scrollbar-thumb {{ background-color: #ffb81c; border-radius: 3px; }}
    .dank-track {{
        display: flex;
        align-items: baseline;
        gap: 10px;
        padding: 10px;
        border-radius: 6px;
        cursor: pointer;
        border-left: 4px solid transparent;
        transition: background-color 0.15s ease;
    }}
    .dank-track:hover {{ background-color: #2c2926; }}
    .dank-track.active {{
        border-left: 4px solid #00FF00;
        background-color: #2c2926;
    }}
    .dank-track-num {{
        color: #ffb81c;
        font-size: 12px;
        font-weight: 800;
        min-width: 18px;
    }}
    .dank-track-title {{
        color: #f1ead8;
        font-size: 14px;
        font-weight: 500;
        flex: 1;
    }}
    .dank-track.active .dank-track-title {{
        color: #00FF00;
        font-weight: 600;
    }}
    .dank-track-duration {{
        color: #9a9488;
        font-size: 12px;
    }}
    .dank-transport-row {{
        display: flex;
        justify-content: center;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 10px;
    }}
    .dank-skip-btn {{
        background-color: #f1ead8;
        color: #151412;
        border: 2px solid #151412;
        border-radius: 6px;
        box-shadow: 3px 3px 0 #ffb81c;
        padding: 6px 12px;
        font-family: 'Poppins', sans-serif;
        font-size: 13px;
        font-weight: 600;
        cursor: pointer;
        transition: transform 0.08s ease, box-shadow 0.08s ease;
    }}
    .dank-skip-btn:hover {{ background-color: #fff6df; }}
    .dank-skip-btn:active {{
        transform: translate(2px, 2px);
        box-shadow: 1px 1px 0 #ffb81c;
    }}
    .dank-skip-btn:disabled {{
        opacity: 0.4;
        cursor: not-allowed;
        box-shadow: none;
    }}
    </style>
    <div class="dank-playlist-card">
        {icon_tag}
        <div class="dank-playlist-title">{safe_label}</div>
        <audio id="dank-player" controls preload="metadata" playsinline></audio>
        <div class="dank-status" id="dank-status"></div>
        <div class="dank-transport-row">
            <button id="dank-prev" class="dank-skip-btn">⏮ Prev</button>
            <button id="dank-skip-back" class="dank-skip-btn">⏪ 10s</button>
            <button id="dank-skip-fwd" class="dank-skip-btn">10s ⏩</button>
            <button id="dank-next" class="dank-skip-btn">Next ⏭</button>
        </div>
        <div class="dank-track-list" id="dank-track-list"></div>
    </div>
    <script>
    const tracks = {tracks_json};
    const showTitle = {js_title};
    const player = document.getElementById('dank-player');
    const listEl = document.getElementById('dank-track-list');
    const statusEl = document.getElementById('dank-status');
    const prevBtn = document.getElementById('dank-prev');
    const nextBtn = document.getElementById('dank-next');
    const skipBackBtn = document.getElementById('dank-skip-back');
    const skipFwdBtn = document.getElementById('dank-skip-fwd');
    let currentIndex = 0;
    let retries = 0;
    let lastGoodTime = 0;
    let preloadedFor = -1;   // index of the track already being preloaded

    function esc(s) {{
        const d = document.createElement('div');
        d.textContent = s == null ? '' : s;
        return d.innerHTML;
    }}

    function setStatus(msg, isError) {{
        statusEl.className = 'dank-status' + (isError ? ' err' : '');
        statusEl.innerHTML = msg || '';
    }}

    function updateTransportButtons() {{
        prevBtn.disabled = currentIndex <= 0;
        nextBtn.disabled = currentIndex >= tracks.length - 1;
    }}

    // ---------- transport ----------
    skipBackBtn.addEventListener('click', () => {{
        player.currentTime = Math.max(0, player.currentTime - 10);
    }});
    skipFwdBtn.addEventListener('click', () => {{
        if (!isNaN(player.duration)) {{
            player.currentTime = Math.min(player.duration, player.currentTime + 10);
        }} else {{
            player.currentTime += 10;
        }}
    }});
    prevBtn.addEventListener('click', () => {{
        if (currentIndex > 0) loadTrack(currentIndex - 1, true);
    }});
    nextBtn.addEventListener('click', () => {{
        if (currentIndex + 1 < tracks.length) loadTrack(currentIndex + 1, true);
    }});

    // ---------- lock-screen / media keys ----------
    if ('mediaSession' in navigator) {{
        const ms = navigator.mediaSession;
        ms.setActionHandler('previoustrack', () => prevBtn.click());
        ms.setActionHandler('nexttrack', () => nextBtn.click());
        ms.setActionHandler('seekbackward', () => skipBackBtn.click());
        ms.setActionHandler('seekforward', () => skipFwdBtn.click());
    }}

    // ---------- list ----------
    function renderList() {{
        listEl.innerHTML = '';
        tracks.forEach((track, i) => {{
            const row = document.createElement('div');
            row.className = 'dank-track' + (i === currentIndex ? ' active' : '');
            row.innerHTML = `
                <div class="dank-track-num">${{i + 1}}</div>
                <div class="dank-track-title">${{esc(track.label)}}</div>
                <div class="dank-track-duration">${{esc(track.duration)}}</div>
            `;
            row.addEventListener('click', () => loadTrack(i, true));
            listEl.appendChild(row);
        }});
    }}

    // ---------- preload the next file, but only once the current one is
    // buffered well ahead, so the two downloads never compete ----------
    const preloader = new Audio();
    preloader.preload = 'auto';
    function preloadNext() {{
        const nextIdx = currentIndex + 1;
        const n = tracks[nextIdx];
        if (!n || !n.url || preloadedFor === nextIdx) return;
        const b = player.buffered;
        const ahead = b.length ? b.end(b.length - 1) - player.currentTime : 0;
        if (ahead > 60) {{
            preloadedFor = nextIdx;
            preloader.src = n.url;
            preloader.load();
        }}
    }}
    player.addEventListener('progress', preloadNext);

    // ---------- loading ----------
    function loadTrack(index, autoplay) {{
        if (index < 0 || index >= tracks.length) return;
        currentIndex = index;
        retries = 0;
        lastGoodTime = 0;
        setStatus('');

        const t = tracks[index];
        if (!t.url) {{
            setStatus('No audio link for this track.', true);
        }} else {{
            player.src = t.url;
            if (autoplay) {{
                player.play().catch(() => {{}});
            }}
        }}

        if ('mediaSession' in navigator) {{
            navigator.mediaSession.metadata = new MediaMetadata({{
                title: t.label || '',
                artist: 'Dead Weight',
                album: showTitle,
            }});
        }}
        renderList();
        updateTransportButtons();
    }}

    // ---------- resilience ----------
    player.addEventListener('timeupdate', () => {{
        if (player.currentTime > 0) lastGoodTime = player.currentTime;
    }});
    player.addEventListener('waiting', () => setStatus('Buffering…'));

    // only warn if we genuinely lack data to keep playing
    player.addEventListener('stalled', () => {{
        setTimeout(() => {{
            if (player.readyState < 3 && !player.paused) setStatus('Slow connection…');
        }}, 2500);
    }});

    player.addEventListener('playing', () => {{
        retries = 0;
        setStatus('');
    }});

    player.addEventListener('error', () => {{
        const t = tracks[currentIndex];
        if (!t || !t.url) return;
        if (retries < 3) {{
            retries++;
            const resumeAt = lastGoodTime;
            setStatus('Reconnecting… (' + retries + '/3)');
            setTimeout(() => {{
                player.src = t.url;
                player.load();
                player.addEventListener('loadedmetadata', () => {{
                    if (resumeAt) player.currentTime = resumeAt;
                    player.play().catch(() => {{}});
                }}, {{ once: true }});
            }}, 1000 * retries);
        }} else {{
            setStatus(
                "Couldn't load this track. <a target='_blank' rel='noopener' href='" + t.url + "'>Open the file directly</a>"
            );
        }}
    }});

    player.addEventListener('ended', () => {{
        if (currentIndex + 1 < tracks.length) {{
            loadTrack(currentIndex + 1, true);
        }}
    }});

    loadTrack(0, false);
    </script>
    """, height=90 + min(len(tracks), 6) * 46 + 232)

def format_playlist_track_label(track, index=None):
    """Formats a track for display inside a playlist context, including
    the (date — location) of the show it came from."""
    show = track.get("show", "")
    prefix = f"{index + 1}. " if index is not None else ""
    if show:
        return f"{prefix}{track['label']} ({show})"
    return f"{prefix}{track['label']}"

# -------------------------
# MOBILE KEYBOARD SUPPRESSION FOR SELECTBOX
# -------------------------

def suppress_selectbox_keyboard():
    """Stops the mobile virtual keyboard from popping up when tapping
    a st.selectbox, while keeping tap-to-open-dropdown behavior intact.
    Runs via a real custom component (not components.html), so it has
    genuine same-origin access to the app's real DOM."""
    streamlit_js_eval(
        js_expressions="""
        (function() {
            const doc = window.parent.document;
            function suppressKeyboard() {
                doc.querySelectorAll('div[data-baseweb="select"] input').forEach((input) => {
                    input.setAttribute('inputmode', 'none');
                    input.setAttribute('readonly', 'readonly');
                });
            }
            suppressKeyboard();
            if (!window.parent._dankKeyboardObserverActive) {
                window.parent._dankKeyboardObserverActive = true;
                new MutationObserver(suppressKeyboard).observe(doc.body, {childList: true, subtree: true});
            }
        })();
        """,
        key="suppress_kb",
        want_output=False,
    )

# -------------------------
# PAGE MENU (dropdown)
# -------------------------

def page_menu():
    with st.popover("☰ Menu"):
        if st.button("Dashboard", width="stretch"):
            st.switch_page("pages/landing.py")
        if st.button("Listen", width="stretch"):
            st.switch_page("pages/listen.py")
        if st.button("Playlist Creator", width="stretch"):
            st.switch_page("pages/playlist_creator.py")            
        if st.button("Watch", width="stretch"):
            st.switch_page("pages/watch.py")
        if st.button("Useful Tools", width="stretch"):
            st.switch_page("pages/tools.py")
        if st.button("Heady Stats", width="stretch"):
            st.switch_page("pages/stats.py")

# -------------------------
# FORCE HORIZ ROW/PLAYLIST FORMATTING
# -------------------------

def force_columns_horizontal(gap="0.4rem", min_col_width=None, equal_width=False, key=None):
    """
    Injects CSS so st.columns() rows never stack vertically on mobile.

    gap: space between columns, any CSS length (e.g. "0.4rem", "8px")
    min_col_width: if set, columns won't shrink below this width (e.g. "70px") --
        the row scrolls horizontally instead of squishing text unreadably
    equal_width: if True, columns split space evenly; if False, they size to content
    key: if set, only affects columns inside a matching st.container(key=key)
        block, instead of every st.columns() row on the page
    """
    scope = f".st-key-{key} " if key else ""
    flex_rule = "flex: 1 1 0% !important;" if equal_width else "flex: initial !important;"
    min_width_rule = f"min-width: {min_col_width} !important;" if min_col_width else "min-width: 0 !important;"
    overflow_rule = "overflow-x: auto !important;" if min_col_width else ""

    st.markdown(f"""
    <style>
    {scope}div[data-testid="stHorizontalBlock"] {{
        flex-wrap: nowrap !important;
        gap: {gap} !important;
        {overflow_rule}
    }}
    {scope}div[data-testid="stHorizontalBlock"] > div[data-testid="stColumn"] {{
        width: auto !important;
        {min_width_rule}
        {flex_rule}
    }}
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

def add_segue_labels(d):
    """One vectorized pass: rows in the same show with the same Duration
    are a segue chain, labeled 'A -> B -> C'."""
    d = d.sort_values(["Date", "Track Number"]).copy()
    t = d["Title"]
    same_prev = d["Date"].eq(d["Date"].shift()) & d["Duration"].eq(d["Duration"].shift())
    same_next = d["Date"].eq(d["Date"].shift(-1)) & d["Duration"].eq(d["Duration"].shift(-1))
    d["Segue Label"] = np.select(
        [same_prev & same_next, same_prev, same_next],
        [t.shift() + " -> " + t + " -> " + t.shift(-1),
         t.shift() + " -> " + t,
         t + " -> " + t.shift(-1)],
        default=t,
    )
    return d


def card_html(value, label, accent=False):
    value_class = "dank-card-value dank-card-accent" if accent else "dank-card-value"
    # size by visible text length (ignoring any HTML tags in the value)
    n = len(re.sub(r"<[^>]+>", "", str(value)))
    size = 26 if n <= 10 else 22 if n <= 16 else 18 if n <= 26 else 15
    return (
        f'<div class="dank-card">'
        f'<div class="{value_class}" style="font-size:{size}px">{value}</div>'
        f'<div class="dank-card-label">{label}</div></div>'
    )


def count_bar(data, x_field, title, sort=None):
    """Bar chart of 'Times Played' with a sane whole-number y-axis."""
    max_count = int(data["Times Played"].max())
    chart = alt.Chart(data).mark_bar(
        cornerRadiusTopLeft=4, cornerRadiusTopRight=4, color="#ffb81c"
    ).encode(
        x=alt.X(f"{x_field}:O", sort=sort, axis=alt.Axis(labelAngle=0, title=None)),
        y=alt.Y("Times Played:Q",
                scale=alt.Scale(domain=[0, max_count + 1], nice=False),
                axis=alt.Axis(tickMinStep=1, tickCount=min(max_count + 1, 6),
                              format="d", title="Times Played")),
        tooltip=[x_field, "Times Played"],
    ).properties(height=250, title=alt.TitleParams(title, anchor="middle"))
    return dank_chart(chart)

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


def generate_setlist(num_songs, randomizer_df, jam_titles, today):
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
        song, odds = pick_by_kind(kind, pools, used_songs, prev_song)
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