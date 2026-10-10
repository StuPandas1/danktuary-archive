import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import random
import html
import urllib.parse
import streamlit.components.v1 as components  # type: ignore
from zoneinfo import ZoneInfo

today = pd.Timestamp.now(tz=ZoneInfo("America/New_York"))
today_md = today.strftime("%m/%d")
today_naive = today.tz_localize(None)

from shared import ( #type: ignore
    load_data, build_filtered, weighted_pick, find_closers, dank_theme, dank_footer, dank_sign, dank_hex, dank_callout, force_columns_horizontal, linked_table,
    times_played_mult, page_menu, dank_header, build_randomizer_pools, apply_segue_boost, pick_by_kind, generate_setlist, ranked_table,
    dead_weight_artists, dead_weight_year,
    clean_title, manual_fixes
)

st.set_page_config(page_title="DankApp | Useful Tools", page_icon="static/icon.png", layout="wide")
dank_theme()


df, song_stats, metadata, jam_metadata = load_data()
df = df[df["Take"] == 1]

page_menu()

min_year = int(df["Year"].min())
max_year = int(df["Year"].max())

if "random_setlist" not in st.session_state:
    st.session_state.random_setlist = None

if "active_tab" not in st.session_state:
    st.session_state.active_tab = "Recent Stats"

dank_header(subtitle="Useful Tools for the Dank")

tab_names = ["Recently Played", "Bustout Tracker", "Setlist Randomizer", "Unplayed Songs"]
with st.container(key="tabs_main"):
    tab_cols = st.columns(len(tab_names))
    for i, name in enumerate(tab_names):
        with tab_cols[i]:
            button_type = "primary" if st.session_state.active_tab == name else "secondary"
            if st.button(name, key=f"tabbtn_{name}", width="stretch", type=button_type):
                st.session_state.active_tab = name
                st.rerun()

st.divider()

active_tab = st.session_state.active_tab

# -------------------------
# TAB: RECENT SETLIST STATS
# -------------------------

if active_tab in ("Recently Played", "Bustout Tracker", "Song Streak"):
    full_df, full_stats = build_filtered(df, metadata, [], (min_year, max_year))

if active_tab == "Recently Played":
    col_sign, col_right = st.columns([4, 2], vertical_alignment="center")
    with col_sign:
        dank_sign("Most Recently Played")
    with col_right:
        recent_sort = st.radio(
            "Sort by:",
            ["Date", "Title"],
            index=0,
            horizontal=True,
            key="recent_sort_by",
        )

    # get track number from each song's most recent appearance
    most_recent_rows = (
        full_df.sort_values(["Date", "Track Number"])
        .groupby("Title")
        .last()
        .reset_index()[["Title", "Date", "Track Number", "Location"]]
    )

    recent_display = full_stats.merge(most_recent_rows, on="Title", how="left")
    recent_display = (
        recent_display
        .sort_values(
            ["Last_Played", "Title", "Track Number"],
            ascending=[False, True, True]
        )
        .assign(Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y"))
        .rename(columns={"Last_Played": "Last Played", "Times_Played": "Total Plays"})
        [["Title", "Last Played", "Total Plays", "Location"]]
        .reset_index(drop=True)
    )
    # rank always reflects recency, even when the table is sorted by title
    recent_display.insert(0, "Rank", range(1, len(recent_display) + 1))

    if recent_sort == "Title":
        recent_display = (
            recent_display
            .assign(_t=lambda x: x["Title"].str.lower())
            .sort_values("_t")
            .drop(columns="_t")
        )

    rows_html = []
    for _, row in recent_display.iterrows():
        encoded_title = urllib.parse.quote(row["Title"], safe="")
        safe_title = html.escape(row["Title"])

        show_label = f'{row["Last Played"]} — {row["Location"]}'
        encoded_show = urllib.parse.quote(show_label, safe="")
        safe_last_played = html.escape(row["Last Played"])

        rows_html.append(
            "<tr>"
            f'<td>{row["Rank"]}</td>'
            f'<td><a href="/stats?song={encoded_title}" target="_self">{safe_title}</a></td>'
            f'<td><a href="/stats?show={encoded_show}" target="_self">{safe_last_played}</a></td>'
            f'<td>{html.escape(str(row["Total Plays"]))}</td>'
            "</tr>"
        )

    table_html = f"""
    <table class="linked-table">
        <thead>
            <tr>
                <th>Rank</th>
                <th>Title</th>
                <th>Last Played</th>
                <th>Total Plays</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows_html)}
        </tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)

# -------------------------
# TAB: BUSTOUT INFO
# -------------------------

elif active_tab == "Bustout Tracker":
    dank_sign("Most Overdue Songs")
    dead_weight_only = st.checkbox("Dead Weight Only", value=True, key="bustout_dead_weight")

    col_label, col_radio = st.columns([1, 6], vertical_alignment="center")
    with col_label:
        st.markdown("**Sort by:**")
    with col_radio:
        sort_by = st.radio(
            "Sort by",
            ["Score", "Days Since"],
            index=0,
            horizontal=True,
            label_visibility="collapsed",
            key="bustout_sort_by",
        )

    if dead_weight_only:
        bustout_df, bustout_stats = build_filtered(df, metadata, dead_weight_artists, (dead_weight_year, max_year))
    else:
        bustout_df, bustout_stats = full_df, full_stats

    bustouts = bustout_stats.copy()
    bustouts["Days_Since_Played"] = (today_naive - bustouts["Last_Played"]).dt.days
    bustouts["Overdue_Score"] = bustouts["Days_Since_Played"] * (bustouts["Times_Played"] ** times_played_mult)
    max_score = bustouts["Overdue_Score"].max()
    bustouts["Overdue_Score_Normalized"] = ((bustouts["Overdue_Score"] / max_score) * 100).round(1)
    bustouts["Last_Played_Short"] = bustouts["Last_Played"].dt.strftime("%m/%d/%y")

    # pull the location of each song's most recent appearance so we can
    # build a link back to that show
    last_played_locations = (
        bustout_df.sort_values(["Date"])
        .groupby("Title")
        .last()
        .reset_index()[["Title", "Location"]]
    )

    sort_col = "Overdue Score" if sort_by == "Score" else "Days Since Played"

    bustout_display = (
        bustouts.merge(last_played_locations, on="Title", how="left")
        .assign(Last_Played=lambda x: x["Last_Played"].dt.strftime("%m/%d/%Y"))
        .rename(columns={
            "Days_Since_Played": "Days Since Played",
            "Times_Played": "Times Played",
            "Overdue_Score_Normalized": "Overdue Score",
            "Last_Played": "Last Played",
            "Last_Played_Short": "Last Played Short"
        })
        .sort_values(sort_col, ascending=False)[[
            "Title", "Days Since Played", "Last Played Short", "Times Played", "Overdue Score",
            "Last Played", "Location"
        ]]
        .reset_index(drop=True)
    )
    bustout_display.insert(0, "Rank", range(1, len(bustout_display) + 1))

    rows_html = []
    for _, row in bustout_display.iterrows():
        encoded_title = urllib.parse.quote(row["Title"], safe="")
        safe_title = html.escape(row["Title"])

        show_label = f'{row["Last Played"]} — {row["Location"]}'
        encoded_show = urllib.parse.quote(show_label, safe="")
        safe_days = html.escape(f'{row["Days Since Played"]} ({row["Last Played Short"]})')

        rows_html.append(
            "<tr>"
            f'<td>{row["Rank"]}</td>'
            f'<td><a href="/stats?song={encoded_title}" target="_self">{safe_title}</a></td>'
            f'<td><a href="/stats?show={encoded_show}" target="_self">{safe_days}</a></td>'
            f'<td>{html.escape(str(row["Times Played"]))}</td>'
            f'<td>{html.escape(str(row["Overdue Score"]))}</td>'
            "</tr>"
        )

    table_html = f"""
    <table class="linked-table">
        <thead>
            <tr>
                <th></th>
                <th>Title</th>
                <th>Days Since Played</th>
                <th>Times Played</th>
                <th>Overdue Score</th>
            </tr>
        </thead>
        <tbody>
            {''.join(rows_html)}
        </tbody>
    </table>
    """
    st.markdown(table_html, unsafe_allow_html=True)

# -------------------------
# TAB: DEAD WEIGHT SL RANDOMIZER
# -------------------------

elif active_tab == "Setlist Randomizer":

    dank_sign("Setlist Randomizer")

    jam_titles = set(jam_metadata["Title"])

    randomizer_df = df.merge(metadata[["Title", "Artist"]], on="Title", how="left")
    randomizer_df = randomizer_df[
        (randomizer_df["Artist"].isin(dead_weight_artists)) &
        (randomizer_df["Year"] >= dead_weight_year)
    ]

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

    # copy checkbox states into the dataframe BEFORE any button logic runs,
    # so a re-roll always sees the latest locks
    setlist = st.session_state.get("random_setlist")
    version = st.session_state.get("setlist_version", 0)
    if setlist is not None:
        locked_col = setlist.columns.get_loc("Locked")
        for i in range(len(setlist)):
            key = f"lock_{version}_{i}"
            if key in st.session_state:
                setlist.iloc[i, locked_col] = bool(st.session_state[key])

    col1, col2 = st.columns(2, vertical_alignment="bottom")
    with col1:
        num_songs = st.slider("Number of Songs:", 4, 15, 10)
    with col2:
        if st.button("Create New Setlist", width="stretch"):
            st.session_state.random_setlist = generate_setlist(
                num_songs, randomizer_df, jam_titles, today_naive
            )
            st.session_state.setlist_version = version + 1
            st.session_state.random_message = random.choice(random_messages)
            st.rerun()

    if st.session_state.get("random_setlist") is not None:
        current = st.session_state.random_setlist

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Re-Roll Those Laughing Bones", width="stretch"):
                locked_songs = set(current[current["Locked"] == True]["Title"].tolist())
                new = generate_setlist(num_songs, randomizer_df, jam_titles, today_naive)

                merged = []
                locked_rows = current[current["Locked"] == True].set_index("#")
                new_unlocked = new[~new["Title"].isin(locked_songs)].reset_index(drop=True)
                new_idx = 0

                for i in range(1, num_songs + 1):
                    if i in locked_rows.index:
                        row = locked_rows.loc[i].to_dict()
                        row["#"] = i
                        merged.append(row)
                    elif new_idx < len(new_unlocked):
                        row = new_unlocked.iloc[new_idx].to_dict()
                        row["#"] = i
                        merged.append(row)
                        new_idx += 1

                st.session_state.random_setlist = pd.DataFrame(merged)
                st.session_state.setlist_version = version + 1
                st.session_state.random_message = random.choice(random_messages)
                st.rerun()
        with col2:
            if st.button("Clear Setlist", width="stretch", key="clear_setlists2"):
                st.session_state.random_setlist = None
                st.rerun()

        # ---- the setlist ----
        st.caption("Check a song to retain it for the next re-roll.")
        with st.container(key="setlist_rows"):
            for i, row in enumerate(current.itertuples()):
                st.checkbox(
                    f"{row[current.columns.get_loc('#') + 1]}. {row.Title}",
                    value=bool(row.Locked),
                    key=f"lock_{version}_{i}",
                )

        if st.session_state.get("random_message"):
            st.divider()
            dank_callout(st.session_state.random_message)
# -------------------------
# TAB: UNPLAYED SONGS
# -------------------------

elif active_tab == "Unplayed Songs":
    dank_sign("Songs We Haven't Played")

    try:
        total_songs = pd.read_csv("total_songs.csv").dropna(subset=["Title"])
        total_songs["Title"] = total_songs["Title"].apply(clean_title)
    except FileNotFoundError:
        dank_hex("total_songs.csv not found")
        st.stop()

    played_titles = set(df["Title"].unique())
    unplayed = (
        total_songs[~total_songs["Title"].isin(played_titles)]
        .sort_values(["Title", "Artist"])
        .reset_index(drop=True)
    )

    n = len(unplayed)
    dank_hex(f"**{n}** {'song' if n == 1 else 'songs'} to learn...")

    if n:
        linked_table(
            unplayed[["Title", "Artist"]].rename(columns={"Title": "Song Title"}),
            song_col=None,
        )

else: dank_hex("Select a tab to view its content.")

# -------------------------
# FOOTER
# -------------------------
st.divider()

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

dank_footer()


#LEGACY TOOLS (commented out for now)
# col_f1, col_f2, col_f3 = st.columns(3)

# with col_f1:
#     if st.button("Master List Clearer"):
#         st.session_state.random_setlist = None
#         st.session_state.selected_show = None
#         if "selected_show_widget" in st.session_state:
#             del st.session_state["selected_show_widget"]
#         st.rerun()


# if st.button("Refresh Database"):
#     with st.spinner("Updating archive..."):
#         subprocess.run(["python", "scanner.py"])
#         subprocess.run(["python", "analyze.py"])
#         subprocess.run(["python", "build_metadata.py"])
#         subprocess.run(["python", "generate_onedrive_urls.py"])
#     st.cache_data.clear()
#     success_message = st.empty()
#     success_message.success("Database updated!")
#     time.sleep(2)
#     success_message.empty()
#     st.rerun()