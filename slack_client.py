"""
PM Agent — Slack Client
Posts to the configured Slack channel via chat.postMessage.

Posts with the custom "Axel" name/icon when possible; if the app lacks the
chat:write.customize scope (Slack returns missing_scope), it retries as the
app's default identity so the message still lands.
"""

import requests
from config import SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, log

AXEL_ICON = "https://raw.githubusercontent.com/james-axis/PM_agent/main/static/axel-icon.png"


def post_slack_message(blocks=None, text=None):
    """Post to the configured Slack channel. Returns (ok: bool, error: str|None).

    Tries with the Axel name/icon override (needs chat:write.customize); on
    missing_scope it retries without the override so the message still sends.
    """
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        return False, "not_configured"

    base = {"channel": SLACK_CHANNEL_ID}
    if blocks:
        base["blocks"] = blocks
    if text:
        base["text"] = text

    headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}

    for customize in (True, False):
        payload = dict(base)
        if customize:
            payload["username"] = "Axel"
            payload["icon_url"] = AXEL_ICON
        try:
            resp = requests.post(
                "https://slack.com/api/chat.postMessage",
                json=payload, headers=headers, timeout=10,
            )
            data = resp.json()
        except Exception as e:
            return False, str(e)

        if data.get("ok"):
            return True, None

        err = data.get("error", "unknown")
        # The custom name/icon needs chat:write.customize — drop it and retry once.
        if err == "missing_scope" and customize:
            log.warning("Slack: missing chat:write.customize — retrying without custom name/icon")
            continue
        if err == "missing_scope":
            needed = data.get("needed", "?")
            provided = data.get("provided", "?")
            err = f"missing_scope (needed: {needed}; have: {provided})"
        return False, err

    return False, "missing_scope"
