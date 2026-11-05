import streamlit as st  # type: ignore
import streamlit.components.v1 as components  # type: ignore
import pandas as pd  # type: ignore
import random
from zoneinfo import ZoneInfo
from shared import (  # type: ignore
    load_data, generate_setlist, dank_theme, dank_footer, dank_sign, dank_hex, dank_header,
    page_menu, force_columns_horizontal, dead_weight_artists, dead_weight_year,
)

st.set_page_config(page_title="DankApp | Setlist Randomizer", page_icon="static/icon.png", layout="wide")
dank_theme()

df, song_stats, metadata, jam_metadata = load_data()
df = df[df["Take"] == 1]
today_naive = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).tz_localize(None)

# -------------------------
# TOP ROW + HEADER
# -------------------------

force_columns_horizontal(gap="0.75rem", equal_width=True, key="top_row")
with st.container(key="top_row"):
    c1, c2 = st.columns(2, vertical_alignment="center")
    with c1:
        page_menu()
    with c2:
        if st.user.is_logged_in:
            if st.button("Logout", width="stretch"):
                st.logout()
        else:
            st.button("Log in with Google", on_click=st.login)

dank_header(subtitle="Let the bones decide")

# -------------------------
# DATA
# -------------------------

jam_titles = set(jam_metadata["Title"])
randomizer_df = df.merge(metadata[["Title", "Artist"]], on="Title", how="left")
randomizer_df = randomizer_df[
    (randomizer_df["Artist"].isin(dead_weight_artists)) &
    (randomizer_df["Year"] >= dead_weight_year)
]

RANDOM_MESSAGES = [
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
    "The one thing we need is a left handed monkey wrench.",
]

st.session_state.setdefault("random_setlist", None)
st.session_state.setdefault("setlist_version", 0)

# copy checkbox states into the dataframe BEFORE any button logic runs,
# so a re-roll always sees the latest locks
setlist = st.session_state["random_setlist"]
version = st.session_state["setlist_version"]
if setlist is not None:
    locked_col = setlist.columns.get_loc("Locked")
    for i in range(len(setlist)):
        key = f"lock_{version}_{i}"
        if key in st.session_state:
            setlist.iloc[i, locked_col] = bool(st.session_state[key])

# -------------------------
# CALLBACKS
# -------------------------

def create_setlist(n):
    st.session_state["random_setlist"] = generate_setlist(n, randomizer_df, jam_titles, today_naive)
    st.session_state["setlist_version"] += 1
    st.session_state["random_message"] = random.choice(RANDOM_MESSAGES)

def reroll(n):
    current = st.session_state["random_setlist"]
    locked = current[current["Locked"] == True]
    locked_titles = set(locked["Title"])
    new = generate_setlist(n, randomizer_df, jam_titles, today_naive)
    fresh = new[~new["Title"].isin(locked_titles)].reset_index(drop=True)
    locked_rows = locked.set_index("#")

    merged, k = [], 0
    for i in range(1, n + 1):
        if i in locked_rows.index:
            r = locked_rows.loc[i].to_dict()
            r["#"] = i
            merged.append(r)
        elif k < len(fresh):
            r = fresh.iloc[k].to_dict()
            r["#"] = i
            merged.append(r)
            k += 1
    st.session_state["random_setlist"] = pd.DataFrame(merged)
    st.session_state["setlist_version"] += 1
    st.session_state["random_message"] = random.choice(RANDOM_MESSAGES)

def clear_setlist():
    st.session_state["random_setlist"] = None

# -------------------------
# CONTROLS
# -------------------------

dank_sign("Setlist Randomizer")
num_songs = st.slider("Number of Songs:", 4, 15, 10, key="rand_num")

has_list = st.session_state["random_setlist"] is not None
force_columns_horizontal(equal_width=True, gap="0.5rem", key="btnrow_rand")
with st.container(key="btnrow_rand"):
    b1, b2, b3 = st.columns(3)
    with b1:
        st.button("Create" if not has_list else "New Setlist", key="rand_create", width="stretch",
                  type="primary" if not has_list else "secondary",
                  on_click=create_setlist, args=(num_songs,))
    with b2:
        st.button("Re-Roll", key="rand_reroll", width="stretch", disabled=not has_list,
                  on_click=reroll, args=(num_songs,))
    with b3:
        st.button("Clear", key="rand_clear", width="stretch", disabled=not has_list,
                  on_click=clear_setlist)

# -------------------------
# THE SETLIST
# -------------------------

current = st.session_state["random_setlist"]
if current is None:
    dank_hex("Pick a length and hit Create")
else:
    st.caption("Tick a song to lock it in place for the next re-roll.")
    version = st.session_state["setlist_version"]
    with st.container(key="setlist_rows"):
        for i, r in enumerate(current.to_dict("records")):
            st.checkbox(f"{r['#']}. {r['Title']}", value=bool(r["Locked"]), key=f"lock_{version}_{i}")
    if st.session_state.get("random_message"):
        dank_hex(st.session_state["random_message"])

# -------------------------
# FOOTER
# -------------------------
st.divider()

if st.button("⬆ Back to top"):
    components.html("""
        <script>
        var doc = window.parent.document;
        var selectors = ['section.main', '.main', '[data-testid="stAppViewContainer"]',
            '[data-testid="stMain"]', '.stApp', 'div[data-testid="stAppViewBlockContainer"]'];
        selectors.forEach(function(sel) {
            var el = doc.querySelector(sel);
            if (el) { el.scrollTo(0, 0); el.scrollTop = 0; }
        });
        doc.documentElement.scrollTop = 0;
        doc.body.scrollTop = 0;
        window.parent.scrollTo(0, 0);
        </script>
    """, height=0)

dank_footer()