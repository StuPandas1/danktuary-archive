import os
import sys
import smtplib
import pandas as pd  # type: ignore
from email.mime.text import MIMEText

# -------------------------
# CONFIG
# -------------------------

GMAIL_ADDRESS = os.environ.get("DANKAPP_GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("DANKAPP_GMAIL_APP_PASSWORD")

BAND_EMAILS = [
    "davidericmelamed@gmail.com",
    "mmargolis52@gmail.com",
    "abrizel07@gmail.com",
    "mr.chrisciao@gmail.com",
    "camoser19@gmail.com"
]

SNAPSHOT_PATH = "last_known_shows.csv"

# -------------------------
# DETECT NEW SHOWS
# -------------------------

def get_current_shows(df):
    shows = df.drop_duplicates(subset="Date")[["Date", "Location"]].copy()
    shows["Date"] = pd.to_datetime(shows["Date"]).dt.strftime("%Y-%m-%d")
    return shows


def main():
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        print("ERROR: DANKAPP_GMAIL_ADDRESS and DANKAPP_GMAIL_APP_PASSWORD environment variables must be set.")
        sys.exit(1)

    df = pd.read_csv("band_archive.csv")
    df["Date"] = pd.to_datetime(df["Date"])

    current_shows = get_current_shows(df)

    if not os.path.exists(SNAPSHOT_PATH):
        # first run ever: seed the snapshot with everything that already
        # exists so we don't email about the entire back-catalog at once
        print("No snapshot found. Seeding baseline with existing shows (no emails sent this run).")
        current_shows.to_csv(SNAPSHOT_PATH, index=False)
        return

    previous_shows = pd.read_csv(SNAPSHOT_PATH)

    new_shows = current_shows[
        ~current_shows["Date"].isin(previous_shows["Date"])
    ]

    if new_shows.empty:
        print("No new shows detected. No email sent.")
        current_shows.to_csv(SNAPSHOT_PATH, index=False)
        return

    for _, show in new_shows.iterrows():
        send_show_email(df, show["Date"], show["Location"])

    # update snapshot so these shows aren't re-flagged next time
    current_shows.to_csv(SNAPSHOT_PATH, index=False)
    print(f"Sent {len(new_shows)} new show notification(s).")


def send_show_email(df, date_str, location):
    show_date = pd.Timestamp(date_str)
    setlist = df[
        (df["Date"] == show_date) & (df["Location"] == location)
    ].sort_values("Track Number")

    date_display = show_date.strftime("%m/%d/%Y")
    subject = f"New Recording Added: {date_display} — {location}"

    lines = [f"A new recording has been added to the Danktuary Archive:\n",
             f"{location} — {date_display}\n",
             "Setlist:"]

    for _, row in setlist.iterrows():
        lines.append(f"  {int(row['Track Number'])}. {row['Title']}")

    lines.append("\nYou can access the recording and related files here:")
    lines.append("https://drive.google.com/drive/folders/1sUzVbzE8lQ8SV9vzGtCHztzlLa-fDaz6?usp=drive_link")

    body = "\n".join(lines)

    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = GMAIL_ADDRESS
    msg["To"] = ", ".join(BAND_EMAILS)

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, BAND_EMAILS, msg.as_string())

    print(f"Emailed: {subject}")


if __name__ == "__main__":
    main()