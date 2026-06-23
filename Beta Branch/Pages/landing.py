import streamlit as st  # type: ignore
import pandas as pd  # type: ignore
import streamlit.components.v1 as components  # type: ignore
from shared import load_data, parse_duration, page_menu # type: ignore

df, song_stats, metadata, jam_metadata = load_data()

st.divider()
page_menu()

st.markdown("""
<style>
.dank-header {
    background-color: #1c1b1a;
    border-radius: 10px;
    border-bottom: 3px solid #d4a24c;
    padding: 18px 20px 16px 20px;
    margin-bottom: 20px;
}
.dank-header-title {
    color: #ece7de;
    font-size: 32px;
    font-weight: 700;
    letter-spacing: -0.01em;
    line-height: 1.1;
    margin-bottom: 4px;
}
.dank-header-subtitle {
    color: #7a8b6f;
    font-size: 14px;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}
</style>
<div class="dank-header" id="dankapp-top">
    <div class="dank-header-title">DankApp</div>
    <div class="dank-header-subtitle">The Danktuary Archive Explorer</div>
</div>
""", unsafe_allow_html=True)

# -------------------------
# ON THIS DAY
# -------------------------

today_md = pd.Timestamp.today().strftime("%m/%d")
day_name = pd.Timestamp.today().strftime("%A")
on_this_day_df = df[df["Date"].dt.strftime("%m/%d") == today_md].copy()
on_this_day_dates = sorted(on_this_day_df["Date"].unique())

if on_this_day_dates:
    st.write(
        f"On this day, {today_md} ({day_name}), we have {len(on_this_day_dates)} "
        f"{'recording' if len(on_this_day_dates) == 1 else 'recordings'} in the archive:"
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
                st.switch_page("pages/explore.py")
else:
    st.write(f"**Today is {day_name}, {today_md}. On this day, no recordings found.**")
st.divider()
    
# -------------------------
# STATS DASHBOARD
# -------------------------

st.subheader("Archive Dashboard")
total_shows = df["Date"].nunique()
total_songs_played = len(df)
total_unique_songs = df["Title"].nunique()
days_since_last_show = (pd.Timestamp.today() - df["Date"].max()).days
last_show_date = df["Date"].max().strftime("%m/%d/%Y")

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
    card_html(total_shows, "Total Sets"),
    card_html(total_unique_songs, "Unique Songs"),
    card_html(total_songs_played, "Total Songs Played"),
    card_html(gig_count, "Total Gigs", accent=True),
    card_html(f"{total_days}d {total_hours_remainder}h {total_mins_remainder}m", "Total Time Played"),
    card_html(f"{longest_mins}:{longest_secs:02d}", "Longest Recorded Jam", accent=True),
    card_html(last_show_date, "Last Time Played"),
    card_html(days_since_last_show, "Days Since Last Played"),
    card_html(most_played_song, "Most Played Song"),
    card_html(most_played_count, f"Times Played \"{most_played_song}\"", accent=True),
]

st.markdown(f'<div class="dank-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

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

st.markdown("")
st.markdown(
    "<div style='text-align: center; color: grey; font-size: 13px;'>Danktuary Archive Version: 1.5.0 | Believe it if you need it</div>",
    unsafe_allow_html=True
)
st.markdown("")

col_f1, col_f2, col_f3 = st.columns(3)
