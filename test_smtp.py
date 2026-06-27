import os
import smtplib
from email.mime.text import MIMEText

GMAIL_ADDRESS = os.environ.get("DANKAPP_GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.environ.get("DANKAPP_GMAIL_APP_PASSWORD")

print(f"Using address: {GMAIL_ADDRESS}")
print(f"Password present: {bool(GMAIL_APP_PASSWORD)}")

if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
    print("Missing credentials, stopping.")
    exit(1)

msg = MIMEText("This is a test email from notify_band.py debugging.")
msg["Subject"] = "DankApp SMTP Test"
msg["From"] = GMAIL_ADDRESS
msg["To"] = GMAIL_ADDRESS

try:
    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_ADDRESS, [GMAIL_ADDRESS], msg.as_string())
    print("SUCCESS: test email sent.")
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
