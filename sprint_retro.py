"""
PM Agent — JOB A6: Sprint Retro Page Generation
Every Monday 7am AEST: creates a new sprint retro page in Confluence.
- Reads the previous retro's "This retro" content and moves it to "Last retro"
- Creates empty "This retro" rows for the team to fill
- Includes velocity report link
- @mentions attendees
"""

import json
import re
import logging
from datetime import datetime, timedelta
import pytz
import requests
from requests.auth import HTTPBasicAuth

from config import JIRA_EMAIL, JIRA_API_TOKEN, CONFLUENCE_BASE, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, log
from confluence_client import create_page_adf, confluence_search
from telegram_bot import send_telegram

# ── Config ────────────────────────────────────────────────────────────────────

RETRO_PARENT_PAGE_ID = "92012546"
VELOCITY_REPORT_URL = "https://axiscrm.atlassian.net/jira/software/projects/AX/boards/1/reports/velocity"
BURNDOWN_URL = "https://axiscrm.atlassian.net/jira/software/projects/AX/boards/1/reports/burndown?source=overview"

ATTENDEES = [
    {"id": "60cb00f1c90cb20068f5a203", "name": "@Dave Kuhn"},
    {"id": "712020:00983fc3-e82b-470b-b141-77804c9be677", "name": "@Andrej Kudriavcev"},
    {"id": "712020:b28bb054-a469-4a9f-bfde-0b93ad1101ae", "name": "@James Nicholls"},
    {"id": "712020:205e7e70-6257-4274-853f-d403e99854a1", "name": "@Marc Schregardus"},
]

auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def generate_retro():
    """Generate a sprint retro page for the sprint that just closed."""

    log.info("JOB A6: Generating Sprint Retro...")
    sydney_tz = pytz.timezone("Australia/Sydney")
    now = datetime.now(sydney_tz)

    # Sprint dates: previous week Mon–Fri (AEST)
    # Today is Monday AEST. Last sprint was last Monday to last Friday.
    today = now.date()
    last_monday = today - timedelta(days=7)
    last_friday = today - timedelta(days=3)  # Friday = Monday - 3 days

    title = f"{last_monday.strftime('%d/%m/%y')} - {last_friday.strftime('%d/%m/%y')} sprint retro summary"

    # Check if already exists
    existing = confluence_search(
        f'ancestor = {RETRO_PARENT_PAGE_ID} AND type = page AND title = "{title}"',
        limit=1,
    )
    if existing:
        log.info(f"JOB A6: Retro page '{title}' already exists. Skipping.")
        return None

    # ── Fetch previous retro's "This retro" rows ──
    last_retro_good, last_retro_bad = _get_previous_retro_content()

    # ── Build ADF ──
    adf = _build_retro_adf(last_retro_good, last_retro_bad)

    # ── Create page ──
    page_id, web_url = create_page_adf(title, adf, parent_id=RETRO_PARENT_PAGE_ID)

    if page_id:
        log.info(f"JOB A6: Created retro '{title}' — {web_url}")
        send_telegram(
            f"📝 *Sprint Retro* created:\n"
            f"[{title}]({web_url})\n\n"
            f"📊 [Velocity Report]({VELOCITY_REPORT_URL})"
        )
        return page_id, web_url
    else:
        log.error("JOB A6: Failed to create retro page.")
        send_telegram("❌ Failed to create sprint retro page. Check logs.")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# PREVIOUS RETRO EXTRACTION
# ══════════════════════════════════════════════════════════════════════════════

def _get_previous_retro_content():
    """Find the most recent retro page and extract its 'This retro' rows."""
    good_items = []
    bad_items = []

    try:
        results = confluence_search(
            f'ancestor = {RETRO_PARENT_PAGE_ID} AND type = page AND title ~ "sprint retro summary" ORDER BY created DESC',
            limit=1,
        )
        if not results:
            log.info("JOB A6: No previous retro found.")
            return good_items, bad_items

        prev_page_id = results[0].get("id") or results[0].get("content", {}).get("id")
        if not prev_page_id:
            return good_items, bad_items

        log.info(f"JOB A6: Reading previous retro page {prev_page_id}...")

        # Fetch ADF body via v2 API
        resp = requests.get(
            f"{CONFLUENCE_BASE}/api/v2/pages/{prev_page_id}",
            params={"body-format": "atlas_doc_format"},
            auth=auth,
            headers={"Accept": "application/json"},
            timeout=15,
        )
        if resp.status_code != 200:
            log.warning(f"JOB A6: Could not fetch prev retro ADF: {resp.status_code}")
            return good_items, bad_items

        body_raw = resp.json().get("body", {}).get("atlas_doc_format", {}).get("value", "")
        if isinstance(body_raw, str):
            body = json.loads(body_raw)
        else:
            body = body_raw

        good_items, bad_items = _extract_this_retro_rows(body)
        log.info(f"JOB A6: Extracted {len(good_items)} good, {len(bad_items)} bad from previous retro")

    except Exception as e:
        log.error(f"JOB A6: Error reading previous retro: {e}", exc_info=True)

    return good_items, bad_items


def _extract_this_retro_rows(adf_doc):
    """Parse ADF table to find rows between 'This retro' and 'Last retro' headers."""
    good = []
    bad = []

    for node in adf_doc.get("content", []):
        if node.get("type") != "table":
            continue

        in_this_retro = False
        for row in node.get("content", []):
            if row.get("type") != "tableRow":
                continue

            cells = row.get("content", [])
            if not cells:
                continue

            first_cell = cells[0]

            # Check for section headers (colspan=2 blue background cells)
            if first_cell.get("attrs", {}).get("colspan") == 2:
                cell_text = _extract_cell_text(first_cell)
                if "this retro" in cell_text.lower():
                    in_this_retro = True
                    continue
                elif "last retro" in cell_text.lower():
                    in_this_retro = False
                    continue

            # Skip header row
            if first_cell.get("type") == "tableHeader":
                continue

            if in_this_retro and len(cells) >= 2:
                good_text = _extract_cell_text(cells[0]).strip()
                bad_text = _extract_cell_text(cells[1]).strip()
                if good_text or bad_text:
                    good.append(good_text)
                    bad.append(bad_text)

    return good, bad


def _extract_cell_text(cell):
    """Recursively extract plain text from an ADF cell node."""
    text = ""
    for para in cell.get("content", []):
        for node in para.get("content", []):
            if node.get("type") == "text":
                text += node.get("text", "")
            elif node.get("type") == "mention":
                text += node.get("attrs", {}).get("text", "")
    return text


# ══════════════════════════════════════════════════════════════════════════════
# ADF BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_retro_adf(last_retro_good, last_retro_bad):
    """Build the full ADF document for the retro page."""

    # ── Attendees ──
    attendee_nodes = [{"text": "Attendees: ", "type": "text", "marks": [{"type": "strong"}]}]
    for i, att in enumerate(ATTENDEES):
        attendee_nodes.append({"type": "mention", "attrs": {"id": att["id"], "text": att["name"]}})
        if i < len(ATTENDEES) - 1:
            attendee_nodes.append({"type": "text", "text": " "})

    # ── Actions ──
    actions = [
        {"type": "heading", "attrs": {"level": 1}, "content": [{"text": "Actions", "type": "text"}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph"}]},
        ]},
    ]

    # ── Sprint Velocity ──
    velocity = [
        {"type": "heading", "attrs": {"level": 1}, "content": [{"text": "Sprint Velocity", "type": "text"}]},
        {"type": "paragraph", "content": [
            {"text": "📊 ", "type": "text"},
            {"text": "View Velocity Report", "type": "text", "marks": [
                {"type": "link", "attrs": {"href": VELOCITY_REPORT_URL}},
            ]},
            {"text": " — add screenshot here", "type": "text", "marks": [{"type": "em"}]},
        ]},
    ]

    # ── Review table ──
    header_row = {
        "type": "tableRow",
        "content": [
            {"type": "tableHeader", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [364]},
             "content": [{"type": "paragraph", "content": [
                 {"text": "What went well (Good)", "type": "text", "marks": [{"type": "strong"}]}
             ]}]},
            {"type": "tableHeader", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [395]},
             "content": [{"type": "paragraph", "content": [
                 {"text": "What could be improved (Bad / Could be better)", "type": "text", "marks": [{"type": "strong"}]}
             ]}]},
        ]
    }

    this_retro_rows = [_empty_row() for _ in range(5)]

    last_retro_rows = []
    max_rows = max(len(last_retro_good), len(last_retro_bad), 1)
    for i in range(max_rows):
        g = last_retro_good[i] if i < len(last_retro_good) else ""
        b = last_retro_bad[i] if i < len(last_retro_bad) else ""
        last_retro_rows.append(_data_row(g, b))

    if not last_retro_rows:
        last_retro_rows = [_empty_row()]

    table = {
        "type": "table",
        "attrs": {"layout": "default", "width": 760},
        "content": [
            header_row,
            _section_header("This retro"),
            *this_retro_rows,
            _section_header("Last retro"),
            *last_retro_rows,
        ]
    }

    return {
        "version": 1,
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": attendee_nodes},
            *actions,
            *velocity,
            {"type": "heading", "attrs": {"level": 1}, "content": [{"text": "Review", "type": "text"}]},
            table,
        ]
    }


def _section_header(label):
    return {
        "type": "tableRow",
        "content": [{
            "type": "tableCell",
            "attrs": {"colspan": 2, "background": "#deebff", "rowspan": 1, "colwidth": [364, 395]},
            "content": [{"type": "paragraph", "content": [
                {"text": label, "type": "text", "marks": [{"type": "strong"}]}
            ]}],
        }]
    }


def _data_row(good_text, bad_text):
    good_content = [{"type": "text", "text": good_text}] if good_text else []
    bad_content = [{"type": "text", "text": bad_text}] if bad_text else []
    return {
        "type": "tableRow",
        "content": [
            {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [364]},
             "content": [{"type": "paragraph", "content": good_content}]},
            {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [395]},
             "content": [{"type": "paragraph", "content": bad_content}]},
        ]
    }


def _empty_row():
    return _data_row("", "")


# ══════════════════════════════════════════════════════════════════════════════
# SLACK NOTIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def send_retro_to_slack():
    """Find the latest retro page and send it to Slack. Runs Monday 9am AEST."""
    log.info("JOB A10: Sending retro to Slack...")

    try:
        results = confluence_search(
            f'ancestor = {RETRO_PARENT_PAGE_ID} AND type = page AND title ~ "sprint retro summary" ORDER BY created DESC',
            limit=1,
        )
        if not results:
            log.warning("JOB A10: No retro page found to send.")
            return

        page = results[0]
        page_id = page.get("id") or page.get("content", {}).get("id")
        title = page.get("title") or page.get("content", {}).get("title", "Sprint Retro")
        web_url = f"https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/{page_id}"

        _send_to_slack(title, web_url)
    except Exception as e:
        log.error(f"JOB A10: Error sending retro to Slack: {e}", exc_info=True)


def _send_to_slack(title, page_url):
    """Send retro page notification to Slack via Bot API."""
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        log.info("JOB A6: Slack not configured (missing token or channel ID) — skipping.")
        return

    try:
        payload = {
            "channel": SLACK_CHANNEL_ID,
            "icon_url": "https://raw.githubusercontent.com/james-axis/PM_agent/main/static/axel-icon.png",
            "username": "Axel",
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f"✦ *Sprint Retrospective* — Please add your thoughts\n\n"
                            f"<{page_url}|{title}>"
                        ),
                    },
                },
            ],
        }
        resp = requests.post(
            "https://slack.com/api/chat.postMessage",
            json=payload,
            headers={"Authorization": f"Bearer {SLACK_BOT_TOKEN}"},
            timeout=10,
        )
        data = resp.json()
        if data.get("ok"):
            log.info("JOB A6: Sent retro to Slack.")
        else:
            log.warning(f"JOB A6: Slack API error: {data.get('error', 'unknown')}")
    except Exception as e:
        log.warning(f"JOB A6: Slack notification failed: {e}")
