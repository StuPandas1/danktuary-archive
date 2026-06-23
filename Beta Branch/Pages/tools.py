import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import random
import subprocess
import time
import streamlit.components.v1 as components  # type: ignore
from shared import ( #type: ignore
    load_data, build_filtered, weighted_pick, find_closers,
    times_played_mult, page_menu
)

df, song_stats, metadata, jam_metadata = load_data()

page_menu()

min_year = int(df["Year"].min())
max_year = int(df["Year"].max())

if "random_setlist" not in st.session_state:
    st.session_state.random_setlist = None

if "active_stat" not in st.session_state:
    st.session_state.active_stat = None

st.subheader("Useful Tools")

tool_tab1, tool_tab2 = st.tabs(["Recent Setlist Stats", "Dead Weight Setlist Randomizer"])

# -------------------------
# TAB: RECENT SETLIST STATS
# -------------------------

with tool_tab1:
    st.markdown("#### Recent Setlist Stats")

    # full unfiltered stats, used by "Most Recently Played" and "Active Streaks"
    full_df, full_stats = build_filtered(df, metadata, [], (min_year, max_year))

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Most Overdue"):
            st.session_state.active_stat = "bustouts"
    with col2:
        if st.button("Most Recently Played"):
            st.session_state.active_stat = "recent"
    with col3:
        if st.button("Active Streaks"):
            st.session_state.active_stat = "consecutive"

    active = st.session_state.get("active_stat")

    if active == "bustouts":

        dead_weight_artists_list = ["Grateful Dead", "Jerry Garcia Band", "The Band", "Little Feat"]
        dead_weight_only = st.checkbox("Dead Weight Only", key="bustout_dead_weight")

        if dead_weight_only:
            bustout_df, bustout_stats = build_filtered(df, metadata, dead_weight_artists_list, (2022, max_year))
        else:
            bustout_df, bustout_stats = full_df, full_stats

        today = pd.Timestamp.today()
        bustouts = bustout_stats.copy()
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
            hide_index=True
        )

    elif active == "recent":

        recent = full_stats.sort_values("Last_Played", ascending=False)
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
            hide_index=True,
            column_config={
                "Rank": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
            }
        )

    elif active == "consecutive":

        all_dates = sorted(df["Date"].dt.normalize().unique())
        records = []
        for title in full_df["Title"].unique():
            song_dates = set(full_df[full_df["Title"] == title]["Date"].dt.normalize().unique())
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

            st.subheader("Active Setlist Streaks")
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
        else:
            st.subheader("Active Setlist Streaks")
            st.write("No active streaks.")

# -------------------------
# TAB: DEAD WEIGHT SETLIST RANDOMIZER
# -------------------------

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
    closers = find_closers(df, allowed_titles)

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


SEGUE_BOOST = 8.0  # multiplier for songs with historical segue from previous song


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


with tool_tab2:

    st.markdown("#### Dead Weight Setlist Randomizer v1.0")

    improv_titles = set(metadata[metadata["Type"] == "Improv"]["Title"])
    allowed_artists = ["The Band", "Grateful Dead", "Jerry Garcia Band", "Little Feat"]
    jam_titles = set(jam_metadata["Title"])
    today = pd.Timestamp.today()

    randomizer_df = df.merge(metadata[["Title", "Artist"]], on="Title", how="left")
    randomizer_df = randomizer_df[
        (randomizer_df["Artist"].isin(allowed_artists)) &
        (randomizer_df["Year"] >= 2022)
    ]
    randomizer_df = randomizer_df[~randomizer_df["Title"].isin(improv_titles)]

    random_messages = [
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
        "The one thing we need is a left handed monkey wrench."
    ]

    col1, col2 = st.columns([1, 1])

    with col1:
        num_songs = st.slider("Number of Songs:", 4, 15, 10)

    with col2:
        st.markdown("&nbsp;", unsafe_allow_html=True)
        if st.button("Create Setlist", width='stretch'):
            st.session_state.random_setlist = generate_setlist(
                num_songs, randomizer_df, jam_titles, improv_titles, today
            )
            st.session_state.setlist_version = st.session_state.get("setlist_version", 0) + 1
            st.session_state.random_message = random.choice(random_messages)

    if st.session_state.get("random_setlist") is not None:

        col1, col2 = st.columns(2)

        with col1:
            if st.button("Re-Roll Those Laughing Bones", width='stretch'):
                current = st.session_state.random_setlist.copy()
                locked_songs = set(current[current["Locked"] == True]["Title"].tolist())
                new = generate_setlist(num_songs, randomizer_df, jam_titles, improv_titles, today)

                merged = []
                locked_rows = current[current["Locked"] == True].set_index("#")
                new_unlocked = new[~new["Title"].isin(locked_songs)].reset_index(drop=True)
                new_idx = 0

                for i in range(1, num_songs + 1):
                    if i in locked_rows.index:
                        row = locked_rows.loc[i].to_dict()
                        row["#"] = i
                        merged.append(row)
                    else:
                        if new_idx < len(new_unlocked):
                            row = new_unlocked.iloc[new_idx].to_dict()
                            row["#"] = i
                            merged.append(row)
                            new_idx += 1

                st.session_state.random_setlist = pd.DataFrame(merged)
                st.session_state.setlist_version = st.session_state.get("setlist_version", 0) + 1
                st.session_state.random_message = random.choice(random_messages)

        with col2:
            if st.button("Clear Setlist", width='stretch', key="clear_setlists2"):
                st.session_state.random_setlist = None
                st.session_state.setlist_version = 0
                st.rerun()

        if st.session_state.get("random_message"):
            st.write(st.session_state.random_message)

        editor_key = f"setlist_editor_{st.session_state.get('setlist_version', 0)}"

        if editor_key in st.session_state:
            edited_state = st.session_state[editor_key].get("edited_rows", {})
            for row_idx, changes in edited_state.items():
                if "Locked" in changes:
                    st.session_state.random_setlist.at[
                        st.session_state.random_setlist.index[row_idx], "Locked"
                    ] = changes["Locked"]

        st.data_editor(
            st.session_state.random_setlist[["#", "Title", "Locked"]],
            hide_index=True,
            width="stretch",
            column_config={
                "#": st.column_config.NumberColumn(width="small"),
                "Title": st.column_config.TextColumn(width="large"),
                "Locked": st.column_config.CheckboxColumn("🔒", width="small")
            },
            disabled=["#", "Title"],
            key=editor_key
        )

# -------------------------
# FOOTER UTILITIES
# -------------------------

st.markdown("")
st.divider()
st.markdown(
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 1.5.0 | Believe it if you need it</div>",
    unsafe_allow_html=True
)
st.markdown("")

if st.button("⬆ Back to top"):
    components.html("""
        <script>
        var doc = window.parent.document;
        var selectors = [
            'section.main',
            '.main',
            '[data-testid="stAppViewContainer"]',
            '[data-testid="stMain"]',
            '.stApp',
            'div[data-testid="stAppViewBlockContainer"]'
        ];
        selectors.forEach(function(sel) {
            var el = doc.querySelector(sel);
            if (el) { el.scrollTo(0, 0); el.scrollTop = 0; }
        });
        doc.documentElement.scrollTop = 0;
        doc.body.scrollTop = 0;
        window.parent.scrollTo(0, 0);
        </script>
    """, height=0)


col_f1, col_f2, col_f3 = st.columns(3)

with col_f1:
    if st.button("Master List Clearer"):
        st.session_state.active_stat = None
        st.session_state.random_setlist = None
        if "selected_show" in st.session_state:
            del st.session_state["selected_show"]
        st.session_state.selected_show = None
        if "selected_show_widget" in st.session_state:
            del st.session_state["selected_show_widget"]
        st.rerun()

with col_f2:
    if st.button("Refresh Database"):
        with st.spinner("Updating archive..."):
            subprocess.run(["python", "scanner.py"])
            subprocess.run(["python", "analyze.py"])
            subprocess.run(["python", "build_metadata.py"])
        st.cache_data.clear()
        success_message = st.empty()
        success_message.success("Database updated!")
        time.sleep(2)
        success_message.empty()
        st.rerun()