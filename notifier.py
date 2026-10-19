#!/usr/bin/env python3
"""
notifier.py - Tell yourself how an update run went

Pluggable: a "backend" is just a function (settings, subject, body) that sends
a message. Gmail is built in. To add another channel later (a WhatsApp sender
via Twilio, a Discord webhook, ...), write a function with that signature and
register it in BACKENDS -- nothing else in the pipeline needs to change.

Settings live in notify_settings.json next to this file (no secrets in it):
    {"backend": "gmail", "gmail_user": "you@gmail.com", "to": "",
     "on_success": true, "on_failure": true}

The Gmail *app password* is never written to that file. It's read from:
  1. the DANKAPP_GMAIL_APP_PASSWORD environment variable, or
  2. Windows Credential Manager / the OS keychain, if `pip install keyring`
     is available (the GUI's Notifications window can save it there).

Getting an app password: Google Account -> Security -> turn on 2-Step
Verification -> App passwords -> create one. (Your normal password won't work.)
"""

from __future__ import annotations

import json
import os
import smtplib
import ssl
import sys
from email.message import EmailMessage
from pathlib import Path

if getattr(sys, "frozen", False):
    _ROOT = Path(sys.executable).resolve().parent
else:
    _ROOT = Path(__file__).resolve().parent

SETTINGS_FILE = _ROOT / "notify_settings.json"
KEYRING_SERVICE = "DankApp-Gmail"
PASSWORD_ENV = "DANKAPP_GMAIL_APP_PASSWORD"

DEFAULTS = {
    "backend": "off",          # "off" | "gmail"
    "gmail_user": "",
    "to": "",                  # blank = send to the Gmail address itself
    "on_success": True,
    "on_failure": True,
}


class NotifyError(Exception):
    pass


# ----------------------------------------------------------------------
# Settings + credentials
# ----------------------------------------------------------------------

def load_settings(path=None) -> dict:
    settings = dict(DEFAULTS)
    try:
        with open(path or SETTINGS_FILE, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            settings.update({k: v for k, v in loaded.items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict, path=None) -> None:
    clean = {k: settings.get(k, DEFAULTS[k]) for k in DEFAULTS}
    with open(path or SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2)


def keyring_available() -> bool:
    try:
        import keyring  # type: ignore  # noqa: F401
        return True
    except Exception:
        return False


def get_app_password(user: str):
    pw = os.environ.get(PASSWORD_ENV)
    if pw:
        return pw
    try:
        import keyring  # type: ignore
        return keyring.get_password(KEYRING_SERVICE, user)
    except Exception:
        return None


def set_app_password(user: str, password: str) -> bool:
    """Store the app password in the OS keychain. False if keyring isn't installed."""
    try:
        import keyring  # type: ignore
        keyring.set_password(KEYRING_SERVICE, user, password)
        return True
    except Exception:
        return False


# ----------------------------------------------------------------------
# Backends
# ----------------------------------------------------------------------

def _send_gmail(settings: dict, subject: str, body: str) -> None:
    user = (settings.get("gmail_user") or "").strip()
    if not user:
        raise NotifyError("No Gmail address is set.")
    password = get_app_password(user)
    if not password:
        raise NotifyError(
            f"No Gmail app password found. Set the {PASSWORD_ENV} environment variable, "
            f"or save one from the Notifications window (needs `pip install keyring`)."
        )

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = (settings.get("to") or user).strip()
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ssl.create_default_context(), timeout=20) as smtp:
            smtp.login(user, password.replace(" ", ""))      # Google shows app passwords in 4 groups with spaces
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as e:
        raise NotifyError(
            "Gmail rejected the login. Use a 16-character *app password* "
            "(Google Account -> Security -> 2-Step Verification -> App passwords), "
            "not your normal password."
        ) from e


BACKENDS = {"gmail": _send_gmail}


# ----------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------

def send(subject: str, body: str, event: str = "info", settings: dict | None = None):
    """
    Send a notification. `event` is "success", "failure", "test" or "info";
    success/failure respect the on_success / on_failure switches.
    Never raises -- returns (sent: bool, message: str).
    """
    s = dict(DEFAULTS)
    s.update(settings if settings is not None else load_settings())

    backend = s.get("backend", "off")
    if backend == "off":
        return False, "Notifications are turned off."
    if event == "success" and not s.get("on_success"):
        return False, "Success alerts are turned off."
    if event == "failure" and not s.get("on_failure"):
        return False, "Failure alerts are turned off."

    fn = BACKENDS.get(backend)
    if fn is None:
        return False, f"Unknown notification backend '{backend}'."
    try:
        fn(s, f"[DankApp] {subject}", body)
        return True, "Sent."
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"