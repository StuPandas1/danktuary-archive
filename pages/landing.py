import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import streamlit.components.v1 as components
import random
from zoneinfo import ZoneInfo
today_md = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).strftime("%m/%d")
from shared import load_data, parse_duration, page_menu, dank_header, force_columns_horizontal, dank_theme, dank_footer, dank_sign, dank_hex, dank_callout, card_html #type: ignore

st.set_page_config(page_title="DankApp | The Dead Weight Hub", page_icon="static/icon.png", layout="wide")
dank_theme()

df, song_stats, metadata, jam_metadata = load_data()
df2 = df.copy()
df_durationfiltered = df[df["Duration"] != df["Duration"].shift()].reset_index(drop=True)
df = df[df["Take"] == 1]
force_columns_horizontal(min_col_width="28px", key="login_mod")

force_columns_horizontal(gap="0.75rem", equal_width=True, key="top_row")
with st.container(key="top_row"):
    col1, col2 = st.columns(2, vertical_alignment="center")
    with col1:
        page_menu()
    with col2:
        if st.user.is_logged_in:
            if st.button("Logout", key="landing_logout", width="stretch"):
                st.logout()
        else:
            st.button("Log in with Google", key="landing_login", on_click=st.login, width="stretch")

dank_header(subtitle="The Dankest App In Town")
st.divider()

dank_sign("listen to the latest")

# -------------------------
# MOST RECENT SETLIST
# -------------------------
last_show_row = df[df["Date"] == df["Date"].max()]
last_show_date_str = df["Date"].max().strftime("%m/%d/%Y")
last_show_location = last_show_row["Location"].iloc[0]
last_show_label = f"{last_show_date_str} — {last_show_location}"

with st.container(key="hex_recent"):
    if st.button(f"{last_show_label}", key="most_recent_setlist_btn", width="stretch"):
        st.session_state["listen_show_select"] = last_show_label
        st.session_state["listen_playlist_select"] = None
        st.session_state["player_mode"] = "setlist"
        st.switch_page("pages/listen.py")

# -------------------------
# ON THIS DAY
# ------------------------
day_name = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).strftime("%A")
on_this_day_df = df[df["Date"].dt.strftime("%m/%d") == today_md].copy()
on_this_day_dates = sorted(on_this_day_df["Date"].unique())

if on_this_day_dates:
    n = len(on_this_day_dates)
    dank_sign(f"Explore {n} {'recording' if n == 1 else 'recordings'} on this day ({today_md})", direction="left")
    with st.container(key="hex_otd"):
        cols = st.columns(len(on_this_day_dates))
        for i, date in enumerate(on_this_day_dates):
            date_str = pd.Timestamp(date).strftime("%m/%d/%Y")
            location = on_this_day_df[on_this_day_df["Date"] == date]["Location"].iloc[0]
            label = f"{date_str} — {location}"

            with cols[i]:
                if st.button(label, key=f"otd_{date_str}", width="stretch"):
                    st.session_state.pending_show_selection = label
                    st.session_state.active_tab = "Setlist Lookup"
                    st.query_params["scroll"] = "1"
                    st.switch_page("pages/stats.py")
else:
    dank_hex(f"No recordings found on this day ({today_md})")

st.write("")

# -------------------------
# FUN FACT
# -------------------------
st.divider()

fun_facts = []
 
# most played: top 10, pick one at random, show its rank
most_played_counts = df["Title"].value_counts().head(10)
mp_idx = random.randrange(len(most_played_counts))
mp_title = most_played_counts.index[mp_idx]
mp_n = most_played_counts.iloc[mp_idx]
fun_facts.append(f"**\"{mp_title}\"** is the **#{mp_idx + 1}** most played song in the archive (**{mp_n}** plays).")
 
rare_songs = df["Title"].value_counts()
one_timers = rare_songs[rare_songs == 1]
if not one_timers.empty:
    rare_pick = random.choice(one_timers.index.tolist())
    rare_date = df[df["Title"] == rare_pick]["Date"].iloc[0].strftime("%m/%d/%Y")
    fun_facts.append(f"**\"{rare_pick}\"** has only been played once, on **{rare_date}**.")
 
# most common opener: top 10, pick one at random, show its rank
opener_counts = df[df["Track Number"] == 1]["Title"].value_counts().head(10)
if not opener_counts.empty:
    op_idx = random.randrange(len(opener_counts))
    op_title = opener_counts.index[op_idx]
    op_n = opener_counts.iloc[op_idx]
    fun_facts.append(f"**\"{op_title}\"** is the **#{op_idx + 1}** most common opener (**{op_n}** times).")
 
# longest jams: group segued tracks (same date + consecutive same duration = one jam), then top 10, pick one at random, show its rank
jam_records = []
for date in df["Date"].unique():
    session = df[df["Date"] == date].sort_values("Track Number").reset_index(drop=True)
    i = 0
    while i < len(session):
        current = session.iloc[i]
        duration = current["Duration"]
        group_titles = [current["Title"]]
 
        j = i + 1
        while j < len(session) and session.iloc[j]["Duration"] == duration:
            group_titles.append(session.iloc[j]["Title"])
            j += 1
 
        jam_records.append({
            "Date": pd.Timestamp(date),
            "Song(s)": " -> ".join(group_titles),
            "Duration_Secs": parse_duration(duration)
        })
        i = j
 
jam_groups_df = pd.DataFrame(jam_records)
top_jams = jam_groups_df.sort_values("Duration_Secs", ascending=False).head(10).reset_index(drop=True)
jam_idx = random.randrange(len(top_jams))
jam_row = top_jams.iloc[jam_idx]
jam_title = jam_row["Song(s)"]
jam_date = jam_row["Date"].strftime("%m/%d/%Y")
jam_secs = jam_row["Duration_Secs"]
fun_facts.append(f"At **{jam_secs // 60}:{jam_secs % 60:02d}**, **\"{jam_title}\"** (**{jam_date}**) is the **#{jam_idx + 1}** longest track in the archive.")
 
busiest_year = df["Year"].value_counts().idxmax()
fun_facts.append(f"**{busiest_year}** was the most active year, with **{df['Year'].value_counts().max()}** songs played.")
 
oldest_song_date = df["Date"].min().strftime("%m/%d/%Y") 
oldest_song_title = df[df["Date"] == df["Date"].min()]["Title"].iloc[0]
fun_facts.append(f"The earliest recording in the archive is **\"{oldest_song_title}\"** from **{oldest_song_date}**.")

dank_callout("How 'bout a random fact, man?", random.choice(fun_facts))
 
st.divider()
 
# -------------------------
# STATS DASHBOARD
# -------------------------

dank_sign("Heady Stats Dashboard")
total_shows = df["Date"].nunique()
total_songs_played = len(df2)
total_unique_songs = df["Title"].nunique()
days_since_last_show = (pd.Timestamp.now() - df["Date"].max()).days
last_show_date = df["Date"].max().strftime("%m/%d/%y")

total_secs_all = df_durationfiltered["Duration"].apply(parse_duration).sum()
total_days = total_secs_all // 86400
total_hours_remainder = (total_secs_all % 86400) // 3600
total_mins_remainder = (total_secs_all % 3600) // 60

most_played_song = df["Title"].value_counts().idxmax()
most_played_count = df["Title"].value_counts().max()

longest_jam_secs = df["Duration"].apply(parse_duration).max()
longest_mins = longest_jam_secs // 60
longest_secs = longest_jam_secs % 60

gig_count = df[df["Type"] == "live"]["Date"].nunique()

cards = [
    card_html(total_shows, "Total Recordings", accent=True),
    card_html(gig_count, "Gig Recordings"),
    card_html(last_show_date, "Last Recording"),
    card_html(f"{total_days}d {total_hours_remainder}h {total_mins_remainder}m", "Total Time Played"),
    card_html(total_songs_played, "Songs Played", accent=True),
    card_html(total_unique_songs, "Unique Songs"),
    card_html(f"{longest_mins}:{longest_secs:02d}", "Longest Track", accent=True),
    card_html(f"{most_played_song} ({most_played_count})", "Most Played Song", accent=True),
]

st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

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