"""
PM Agent — Sprint Planning Page Generation
Creates a Confluence sprint planning page populated with real sprint data.
Runs after sprint start (Monday 7am AEST).
"""

import json
import requests
from datetime import datetime, timedelta
import pytz

from config import STORY_POINTS_FIELD, SLACK_BOT_TOKEN, SLACK_CHANNEL_ID, log
from jira_client import get_active_sprints, get_sprint_issues
from confluence_client import create_page_adf, confluence_search
from telegram_bot import send_telegram

# ── Config ────────────────────────────────────────────────────────────────────

PLANNING_PARENT_PAGE_ID = "91652097"

ATTENDEES = [
    {"id": "712020:00983fc3-e82b-470b-b141-77804c9be677", "name": "@Andrej Kudriavcev", "role": "Attended"},
    {"id": "712020:b28bb054-a469-4a9f-bfde-0b93ad1101ae", "name": "@James Nicholls", "role": "Attended"},
    {"id": "60cb00f1c90cb20068f5a203", "name": "@Dave Kuhn", "role": "Attended"},
    {"id": "712020:205e7e70-6257-4274-853f-d403e99854a1", "name": "@Marc Schregardus", "role": "Attended"},
    {"id": "712020:db437afd-54db-4eb0-9034-70c3c526e37a", "name": "@Sonny", "role": "For noting"},
]


def generate_planning():
    """Generate a sprint planning page for the active sprint."""

    log.info("Sprint Planning: Generating page...")
    sydney_tz = pytz.timezone("Australia/Sydney")
    now = datetime.now(sydney_tz)

    # Get active sprint
    active = get_active_sprints()
    if not active:
        log.warning("Sprint Planning: No active sprint found.")
        send_telegram("⚠️ Sprint Planning: No active sprint to create planning page for.")
        return None

    sprint = active[0]
    sprint_name = sprint.get("name", "Sprint")

    # Parse sprint dates
    start_str = sprint.get("startDate", "")
    end_str = sprint.get("endDate", "")
    start_date = _parse_date(start_str)
    end_date = _parse_date(end_str)

    if start_date:
        start_aest = start_date.astimezone(sydney_tz)
        title_date = start_aest.strftime("%d%m%y")
        start_display = start_aest.strftime("%d/%m/%Y")
    else:
        title_date = now.strftime("%d%m%y")
        start_display = now.strftime("%d/%m/%Y")

    if end_date:
        end_aest = end_date.astimezone(sydney_tz)
        end_display = end_aest.strftime("%d/%m/%Y")
    else:
        end_display = (now + timedelta(days=4)).strftime("%d/%m/%Y")

    title = f"{title_date} Sprint Planning"

    # Check if already exists
    existing = confluence_search(
        f'ancestor = {PLANNING_PARENT_PAGE_ID} AND type = page AND title = "{title}"',
        limit=1,
    )
    if existing:
        log.info(f"Sprint Planning: Page '{title}' already exists. Skipping.")
        return None

    # Get sprint tickets
    issues = get_sprint_issues(sprint["id"])
    total_points = sum((i["fields"].get(STORY_POINTS_FIELD) or 0) for i in issues)

    # Build backlog list
    backlog_items = []
    for issue in issues:
        key = issue["key"]
        summary = issue["fields"].get("summary", "")
        pts = issue["fields"].get(STORY_POINTS_FIELD) or 0
        status = issue["fields"].get("status", {}).get("name", "")
        priority = (issue["fields"].get("priority") or {}).get("name", "")
        backlog_items.append({
            "key": key,
            "summary": summary,
            "points": pts,
            "status": status,
            "priority": priority,
        })

    # Find 🟣 items for sprint goal
    purple_items = [i for i in backlog_items if "🟣" in i["summary"]]
    if purple_items:
        sprint_goal = "🟣 " + "; ".join(i["summary"].replace("🟣", "").strip() for i in purple_items[:3])
    else:
        sprint_goal = sprint_name

    # Build ADF
    adf = _build_planning_adf(
        start_display=start_display,
        end_display=end_display,
        total_days="5",
        total_points=f"{total_points:.0f} points",
        sprint_goal=sprint_goal,
        backlog_items=backlog_items,
    )

    # Create page
    page_id, web_url = create_page_adf(title, adf, parent_id=PLANNING_PARENT_PAGE_ID)

    if page_id:
        log.info(f"Sprint Planning: Created '{title}' — {web_url}")
        send_telegram(
            f"📋 *Sprint Planning* created:\n"
            f"[{title}]({web_url})\n\n"
            f"📊 {len(backlog_items)} tickets · {total_points:.0f} pts · Goal: {sprint_goal[:60]}"
        )
        return page_id, web_url
    else:
        log.error("Sprint Planning: Failed to create page.")
        send_telegram("❌ Failed to create sprint planning page. Check logs.")
        return None


def _parse_date(date_str):
    """Parse an ISO date string from Jira."""
    if not date_str:
        return None
    try:
        return datetime.fromisoformat(date_str.replace("Z", "+00:00"))
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════════════════════
# ADF BUILDER
# ══════════════════════════════════════════════════════════════════════════════

def _build_planning_adf(start_display, end_display, total_days, total_points,
                        sprint_goal, backlog_items):
    """Build the full ADF document for the sprint planning page."""

    # ── Intro paragraph ──
    intro = {
        "type": "paragraph",
        "content": [{
            "text": "Sprint planning template, used to structure the meeting while we set the sprint goal and define the sprint backlog for the upcoming sprint.",
            "type": "text",
        }]
    }

    # ── Team members heading + table ──
    team_heading = {
        "type": "heading", "attrs": {"level": 2},
        "content": [
            {"type": "emoji", "attrs": {"id": "1f465", "text": "👥", "shortName": ":busts_in_silhouette:"}},
            {"text": " Team members", "type": "text"},
        ]
    }

    team_header_row = {
        "type": "tableRow",
        "content": [
            {"type": "tableHeader", "attrs": {"colspan": 1, "background": "#deebff", "rowspan": 1, "colwidth": [399]},
             "content": [{"type": "paragraph", "content": [
                 {"text": "Name", "type": "text", "marks": [{"type": "strong"}]}
             ]}]},
            {"type": "tableHeader", "attrs": {"colspan": 1, "background": "#deebff", "rowspan": 1, "colwidth": [361]},
             "content": [{"type": "paragraph", "content": [
                 {"text": "Attended / for noting", "type": "text", "marks": [{"type": "strong"}]}
             ]}]},
        ]
    }

    team_rows = [team_header_row]
    for att in ATTENDEES:
        team_rows.append({
            "type": "tableRow",
            "content": [
                {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [399]},
                 "content": [{"type": "paragraph", "content": [
                     {"type": "mention", "attrs": {"id": att["id"], "text": att["name"]}},
                     {"text": " ", "type": "text"},
                 ]}]},
                {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [361]},
                 "content": [{"type": "paragraph", "content": [
                     {"text": att["role"], "type": "text"},
                 ]}]},
            ]
        })

    team_table = {"type": "table", "attrs": {"layout": "default", "width": 760}, "content": team_rows}

    # ── Sprint planning heading + table ──
    planning_heading = {
        "type": "heading", "attrs": {"level": 2},
        "content": [
            {"type": "emoji", "attrs": {"id": "270f", "text": "✏", "shortName": ":pencil2:"}},
            {"text": " Sprint planning", "type": "text"},
        ]
    }

    def _planning_row(label, value, is_header=False):
        cell_type = "tableHeader" if is_header else "tableCell"
        return {
            "type": "tableRow",
            "content": [
                {cell_type: None, "type": cell_type, "attrs": {"colspan": 1, "background": "#fffae6", "rowspan": 1, "colwidth": [312]},
                 "content": [{"type": "paragraph", "content": [
                     {"text": label, "type": "text", "marks": [{"type": "strong"}]}
                 ]}]},
                {cell_type: None, "type": cell_type, "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [445],
                 **({"background": "#ffffff"} if is_header else {})},
                 "content": [{"type": "paragraph", "content": [
                     {"text": value, "type": "text"}
                 ]}]},
            ]
        }

    # Build backlog text as a bullet list in the cell
    backlog_bullets = []
    for item in backlog_items:
        pts_str = f" ({item['points']:.0f} sp)" if item["points"] else ""
        backlog_bullets.append({
            "type": "listItem",
            "content": [{"type": "paragraph", "content": [
                {"text": item["key"], "type": "text", "marks": [
                    {"type": "strong"},
                    {"type": "link", "attrs": {"href": f"https://axiscrm.atlassian.net/browse/{item['key']}"}},
                ]},
                {"text": f" — {item['summary']}{pts_str}", "type": "text"},
            ]}]
        })

    backlog_cell_content = [{"type": "bulletList", "content": backlog_bullets}] if backlog_bullets else [{"type": "paragraph"}]

    planning_rows = [
        _planning_row("Start date", start_display, is_header=True),
        _planning_row("End date", end_display),
        _planning_row("Total days", total_days),
        _planning_row("Story points (baseline)", total_points),
        _planning_row("Story points (capacity)", "Engineering: 40 points (5 sp per day each)"),
        _planning_row("Sprint goal", sprint_goal),
        # Sprint backlog row with bullet list
        {
            "type": "tableRow",
            "content": [
                {"type": "tableCell", "attrs": {"colspan": 1, "background": "#fffae6", "rowspan": 1, "colwidth": [312]},
                 "content": [{"type": "paragraph", "content": [
                     {"text": "Sprint backlog (to do)", "type": "text", "marks": [{"type": "strong"}]}
                 ]}]},
                {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [445]},
                 "content": backlog_cell_content},
            ]
        },
    ]

    planning_table = {"type": "table", "attrs": {"layout": "default", "width": 760}, "content": planning_rows}

    # ── Potential risks ──
    risks_heading = {"type": "heading", "attrs": {"level": 3}, "content": [{"text": "Potential risks", "type": "text"}]}
    risks_table = {
        "type": "table", "attrs": {"layout": "default", "width": 760},
        "content": [
            {"type": "tableRow", "content": [
                {"type": "tableHeader", "attrs": {"colspan": 1, "background": "#fffae6", "rowspan": 1, "colwidth": [313]},
                 "content": [{"type": "paragraph", "content": [{"text": "Risk", "type": "text", "marks": [{"type": "strong"}]}]}]},
                {"type": "tableHeader", "attrs": {"colspan": 1, "background": "#fffae6", "rowspan": 1, "colwidth": [446]},
                 "content": [{"type": "paragraph", "content": [{"text": "Mitigation", "type": "text", "marks": [{"type": "strong"}]}]}]},
            ]},
            {"type": "tableRow", "content": [
                {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [313]},
                 "content": [{"type": "paragraph"}]},
                {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [446]},
                 "content": [{"type": "paragraph"}]},
            ]},
        ]
    }

    # ── Sprint boards + links ──
    boards_heading = {"type": "heading", "attrs": {"level": 3}, "content": [{"text": "Sprint boards and retrospectives", "type": "text"}]}
    boards_list = {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"text": "Product Roadmap", "type": "text", "marks": [
                    {"type": "link", "attrs": {"href": "https://productcentral.up.railway.app/"}},
                ]},
            ]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"text": "Sprint Backlog & Product Backlog", "type": "text", "marks": [
                    {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/jira/software/projects/AX/boards/1/backlog"}},
                ]},
            ]}]},
        ]
    }

    # ── Actions ──
    actions_heading = {"type": "paragraph", "content": [{"text": "Actions:", "type": "text", "marks": [{"type": "strong"}]}]}
    actions_list = {
        "type": "bulletList",
        "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [
                {"text": "Technical planning by engineers", "type": "text"},
            ]}]},
        ]
    }

    return {
        "version": 1,
        "type": "doc",
        "content": [
            intro,
            team_heading,
            team_table,
            planning_heading,
            planning_table,
            risks_heading,
            risks_table,
            boards_heading,
            boards_list,
            actions_heading,
            actions_list,
        ]
    }


# ══════════════════════════════════════════════════════════════════════════════
# SLACK NOTIFICATION
# ══════════════════════════════════════════════════════════════════════════════

def send_planning_to_slack():
    """Find the latest planning page and send it to Slack. Runs Monday 9:15am AEST."""
    log.info("JOB A12: Sending planning to Slack...")

    try:
        results = confluence_search(
            f'ancestor = {PLANNING_PARENT_PAGE_ID} AND type = page AND title ~ "sprint planning" ORDER BY created DESC',
            limit=1,
        )
        if not results:
            log.warning("JOB A12: No planning page found to send.")
            return

        page = results[0]
        page_id = page.get("id") or page.get("content", {}).get("id")
        title = page.get("title") or page.get("content", {}).get("title", "Sprint Planning")
        web_url = f"https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/{page_id}"

        _send_planning_slack(title, web_url)
    except Exception as e:
        log.error(f"JOB A12: Error sending planning to Slack: {e}", exc_info=True)


def _send_planning_slack(title, page_url):
    """Send planning page notification to Slack via Bot API. Returns True on success.

    Failures are surfaced via Telegram (not just logs) so they don't fail silently.
    """
    if not SLACK_BOT_TOKEN or not SLACK_CHANNEL_ID:
        msg = "⚠️ Planning→Slack skipped: SLACK_BOT_TOKEN / SLACK_CHANNEL_ID not set."
        log.warning(f"JOB A12: {msg}")
        send_telegram(msg)
        return False

    blocks = [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"📋 *Sprint Planning* — <!here> New sprint kicked off\n\n"
                    f"<{page_url}|{title}>"
                ),
            },
        },
    ]
    from slack_client import post_slack_message
    ok, err = post_slack_message(blocks)
    if ok:
        log.info("JOB A12: Sent planning to Slack.")
        return True
    log.warning(f"JOB A12: Slack API error: {err}")
    send_telegram(f"❌ Planning→Slack failed — Slack API error: `{err}` (channel {SLACK_CHANNEL_ID})")
    return False
