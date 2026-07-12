import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import streamlit.components.v1 as components
import random
from zoneinfo import ZoneInfo
today_md = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).strftime("%m/%d")
from shared import load_data, parse_duration, page_menu, dank_header, force_columns_horizontal #type: ignore

df, song_stats, metadata, jam_metadata = load_data()
df = df[df["Take"] == 1]

page_menu()
st.markdown("""
<style>
div[data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important;
    gap: 8px !important;
}
div[data-testid="stHorizontalBlock"] > div {
    min-width: 60px !important;
    flex: 1 1 0 !important;
}
div[data-testid="stHorizontalBlock"] button {
    font-size: 13px !important;
    padding: 4px 6px !important;
    white-space: normal !important;
    word-break: break-word !important;
}
</style>
""", unsafe_allow_html=True)

dank_header(subtitle="The Dankest App In Town")

force_columns_horizontal(min_col_width="28px", key="login_mod")
with st.container(key="login_mod"):
    if st.user.is_logged_in:
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.success("✅ You're logged in.")
        with col2:
            if st.button("🎧 Click to Listen"):
                    st.switch_page("pages/listen.py")
        st.divider()

# -------------------------
# MOST RECENT SETLIST
# -------------------------

last_show_row = df[df["Date"] == df["Date"].max()]
last_show_date_str = df["Date"].max().strftime("%m/%d/%Y")
last_show_location = last_show_row["Location"].iloc[0]
last_show_label = f"{last_show_date_str} — {last_show_location}"

st.markdown("<div style='text-align: center;'><strong>Most Recent Setlist</strong></div>", unsafe_allow_html=True)
if st.button(last_show_label, key="most_recent_setlist_btn", width="stretch"):
    st.session_state["listen_show_select"] = last_show_label
    st.session_state["listen_playlist_select"] = None
    st.session_state["player_mode"] = "setlist"
    st.switch_page("pages/listen.py")
    
# -------------------------
# ON THIS DAY
# -------------------------

day_name = pd.Timestamp.now(tz=ZoneInfo("America/New_York")).strftime("%A")
on_this_day_df = df[df["Date"].dt.strftime("%m/%d") == today_md].copy()
on_this_day_dates = sorted(on_this_day_df["Date"].unique())

if on_this_day_dates:
    st.markdown("<div style='text-align: center;'><strong>On This Day</strong></div>", unsafe_allow_html=True)
    st.write(
        f"**{today_md}: We have {len(on_this_day_dates)} {'recording' if len(on_this_day_dates) == 1 else 'recordings'} in the archive**"
    )

    cols = st.columns(len(on_this_day_dates))
    for i, date in enumerate(on_this_day_dates):
        date_str = pd.Timestamp(date).strftime("%m/%d/%Y")
        location = on_this_day_df[on_this_day_df["Date"] == date]["Location"].iloc[0]
        label = f"{date_str} — {location}"

        with cols[i]:
            if st.button(label, key=f"otd_{date_str}", width="stretch"):
                st.session_state.selected_show = label
                if "selected_show_widget" in st.session_state:
                    del st.session_state["selected_show_widget"]
                st.session_state.active_tab = "Setlist Lookup"
                st.query_params["scroll"] = "1"
                st.switch_page("pages/explore.py")
else:
    st.markdown("<div style='text-align: center;'><strong>On This Day</strong></div>", unsafe_allow_html=True)
    st.write(f"**{today_md}: No recordings found**")

st.write("")

# -------------------------
# FUN FACT
# -------------------------
 
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
fun_facts.append(f"At **{jam_secs // 60}:{jam_secs % 60:02d}**, **\"{jam_title}\"** (**{jam_date}**) is the **#{jam_idx + 1}** longest jam in the archive.")
 
busiest_year = df["Year"].value_counts().idxmax()
fun_facts.append(f"**{busiest_year}** was the most active year, with **{df['Year'].value_counts().max()}** songs played.")
 
oldest_song_date = df["Date"].min().strftime("%m/%d/%Y")
oldest_song_title = df[df["Date"] == df["Date"].min()]["Title"].iloc[0]
fun_facts.append(f"The earliest recording in the archive is **\"{oldest_song_title}\"** from **{oldest_song_date}**.")

st.markdown("<div style='text-align: center;'><strong>Random Fact</strong></div>", unsafe_allow_html=True)
st.write(f"{random.choice(fun_facts)}")
 
st.divider()

# -------------------------
# STATS DASHBOARD
# -------------------------

st.markdown("#### **Stats Dashboard**")

total_shows = df["Date"].nunique()
total_songs_played = len(df)
total_unique_songs = df["Title"].nunique()
days_since_last_show = (pd.Timestamp.now() - df["Date"].max()).days
last_show_date = df["Date"].max().strftime("%m/%d/%y")

total_secs_all = df["Duration"].apply(parse_duration).sum()
total_days = total_secs_all // 86400
total_hours_remainder = (total_secs_all % 86400) // 3600
total_mins_remainder = (total_secs_all % 3600) // 60

most_played_song = df["Title"].value_counts().idxmax()
most_played_count = df["Title"].value_counts().max()

longest_jam_secs = df["Duration"].apply(parse_duration).max()
longest_mins = longest_jam_secs // 60
longest_secs = longest_jam_secs % 60

gig_count = df[df["Type"] == "live"]["Date"].nunique()

st.markdown("""
<style>
.dank-card {
    background-color: #1c1b1a;
    border-radius: 10px;
    border-bottom: 3px solid #d4a24c;
    padding: 18px 16px 14px 16px;
    margin-bottom: 14px;
}
.dank-card-value {
    color: #ece7de;
    font-size: 26px;
    font-weight: 700;
    letter-spacing: -0.02em;
    line-height: 1.15;
    margin-bottom: 4px;
}
.dank-card-label {
    color: #8a857c;
    font-size: 12px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}
.dank-card-accent {
    color: #7a8b6f;
}
.dank-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 12px;
}
</style>
""", unsafe_allow_html=True)

def card_html(value, label, accent=False):
    value_class = "dank-card-value dank-card-accent" if accent else "dank-card-value"
    return f'<div class="dank-card"><div class="{value_class}">{value}</div><div class="dank-card-label">{label}</div></div>'

cards = [
    card_html(total_shows, "Total Setlists"),
    card_html(total_unique_songs, "Unique Songs"),
    card_html(total_songs_played, "Songs Played", accent=True),
    card_html(gig_count, "Total Gigs"),
    card_html(f"{total_days}d {total_hours_remainder}h {total_mins_remainder}m", "Total Time Played"),
    card_html(f"{longest_mins}:{longest_secs:02d}", "Longest Jam", accent=True),
    card_html(last_show_date, "Last Setlist"),
    card_html(days_since_last_show, "Days Since Last"),
    card_html(most_played_song, "Most Played Song"),
    card_html(most_played_count, f"Times Played \"{most_played_song}\"", accent=True),
]

st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

# -------------------------
# FOOTER 
# -------------------------
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

st.divider()

st.markdown(
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 2.0 | Believe it if you need it</div>",
    unsafe_allow_html=True
)
st.markdown("")