"""
PM Agent — Weekly Product Update (JOB A5)
Every Friday 9am AEST: duplicates the Product Weekly Confluence template,
fills it with current sprint data, and creates a new page.
"""

import json
import copy
import logging
from datetime import datetime, timedelta
from uuid import uuid4
import pytz

from config import STORY_POINTS_FIELD, log
from jira_client import (
    get_active_sprints, get_future_sprints, get_sprint_issues,
    jira_get, COMPLETED_STATUSES,
)
from confluence_client import create_page_adf, CHECKINS_PARENT_PAGE_ID, confluence_search
from claude_client import call_claude
from telegram_bot import send_telegram

# ── Config ────────────────────────────────────────────────────────────────────

TEMPLATE_PAGE_ID = "330465281"  # 2026-03-27 Product Weekly
WEEKLY_PARENT_PAGE_ID = CHECKINS_PARENT_PAGE_ID  # "Checkins" parent
WEEKLY_SPACE_ID = "1933317"  # CAD space


def generate_weekly_update():
    """JOB A5: Generate the weekly Product Weekly Confluence page."""

    log.info("JOB A5: Generating Product Weekly...")
    sydney_tz = pytz.timezone("Australia/Sydney")
    now = datetime.now(sydney_tz)

    # Friday's date (if run on Friday, use today; otherwise use next Friday)
    if now.weekday() == 4:  # Friday
        friday = now.date()
    else:
        days_until_friday = (4 - now.weekday()) % 7
        friday = (now + timedelta(days=days_until_friday)).date()

    page_title = f"{friday.strftime('%Y-%m-%d')} Product Weekly"

    # Check if page already exists
    existing = confluence_search(
        f'ancestor = {WEEKLY_PARENT_PAGE_ID} AND type = page AND title = "{page_title}"',
        limit=1,
    )
    if existing:
        log.info(f"JOB A5: Page '{page_title}' already exists. Skipping.")
        return None

    # ── Gather sprint data ──
    active = get_active_sprints()
    future = get_future_sprints()

    current_sprint = active[0] if active else None
    next_sprint = future[0] if future else None

    current_issues = get_sprint_issues(current_sprint["id"]) if current_sprint else []
    next_issues = get_sprint_issues(next_sprint["id"]) if next_sprint else []

    completed = [i for i in current_issues
                 if i["fields"]["status"]["name"].lower() in COMPLETED_STATUSES]
    in_progress = [i for i in current_issues
                   if i["fields"]["status"]["name"].lower() not in COMPLETED_STATUSES]

    sprint_name = current_sprint["name"] if current_sprint else "No active sprint"
    sprint_goal = current_sprint.get("goal", "") if current_sprint else ""
    next_sprint_name = next_sprint["name"] if next_sprint else "TBD"

    # ── Use Claude to generate insights ──
    sprint_summary = _build_sprint_summary(completed, in_progress, next_issues,
                                            sprint_name, next_sprint_name)
    insights = _generate_insights_with_claude(sprint_summary, sprint_goal)

    # ── Build ADF from template ──
    adf = _build_weekly_adf(friday, sprint_goal or insights.get("sprint_goal", ""),
                            insights, completed, in_progress, next_issues,
                            next_sprint_name)

    # ── Create page ──
    page_id, web_url = create_page_adf(page_title, adf, parent_id=WEEKLY_PARENT_PAGE_ID)

    if page_id:
        log.info(f"JOB A5: Created '{page_title}' — {web_url}")
        send_telegram(
            f"📋 *Product Weekly* created for {friday.strftime('%d %b %Y')}:\n"
            f"{web_url}"
        )
        return page_id, web_url
    else:
        log.error("JOB A5: Failed to create Product Weekly page.")
        send_telegram("❌ Failed to create Product Weekly page. Check logs.")
        return None


def _build_sprint_summary(completed, in_progress, next_issues, sprint_name, next_sprint_name):
    """Build a text summary of sprint data for Claude."""
    comp_text = "\n".join([
        f"  - {i['key']}: {i['fields'].get('summary', '?')} "
        f"[{(i['fields'].get('parent') or {}).get('fields', {}).get('summary', 'No epic')}]"
        for i in completed[:15]
    ]) or "  None"

    ip_text = "\n".join([
        f"  - {i['key']}: {i['fields'].get('summary', '?')} ({i['fields']['status']['name']}) "
        f"[{(i['fields'].get('parent') or {}).get('fields', {}).get('summary', 'No epic')}]"
        for i in in_progress[:15]
    ]) or "  None"

    next_text = "\n".join([
        f"  - {i['key']}: {i['fields'].get('summary', '?')} "
        f"[{(i['fields'].get('parent') or {}).get('fields', {}).get('summary', 'No epic')}]"
        for i in next_issues[:15]
    ]) or "  None"

    return (
        f"Current Sprint: {sprint_name}\n"
        f"Completed this week:\n{comp_text}\n\n"
        f"Still in progress:\n{ip_text}\n\n"
        f"Next Sprint ({next_sprint_name}):\n{next_text}"
    )


def _generate_insights_with_claude(sprint_summary, sprint_goal):
    """Use Claude to generate the shipped/upcoming/sprint goal content."""
    import re

    prompt = (
        "You are writing the weekly product update for a CRM platform team. "
        "Based on the sprint data below, generate content for the meeting page.\n\n"
        f"Sprint Goal (if set): {sprint_goal or 'Not set'}\n\n"
        f"{sprint_summary}\n\n"
        "Return a JSON object with:\n"
        '- "sprint_goal": a concise 1-line sprint goal if none was set (use emoji prefix like 🟣)\n'
        '- "shipped": list of strings describing what was completed/shipped this week\n'
        '- "upcoming": list of strings describing key items coming next week\n'
        '- "blocked": list of strings for any blocked items (or ["N/A"] if none)\n\n'
        "Keep items concise (1 line each). Group by epic/theme where possible.\n"
        "Return ONLY valid JSON, no preamble or markdown."
    )

    response = call_claude(prompt, max_tokens=1000)
    if not response:
        return {"sprint_goal": sprint_goal, "shipped": [], "upcoming": [], "blocked": ["N/A"]}

    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response.strip())
        clean = re.sub(r'\s*```$', '', clean)
        return json.loads(clean)
    except json.JSONDecodeError as e:
        log.warning(f"JOB A5: Claude JSON parse error: {e}")
        return {"sprint_goal": sprint_goal, "shipped": [], "upcoming": [], "blocked": ["N/A"]}


def _build_weekly_adf(friday, sprint_goal, insights, completed, in_progress,
                       next_issues, next_sprint_name):
    """Build the full ADF document for the weekly page."""

    # Friday timestamp in milliseconds (for Confluence date node)
    friday_ts = str(int(datetime(friday.year, friday.month, friday.day).timestamp() * 1000))

    shipped = insights.get("shipped", [])
    upcoming = insights.get("upcoming", [])
    blocked = insights.get("blocked", ["N/A"])

    # ── Helper: build bullet list ADF ──
    def _bullet_list(items):
        return {
            "type": "bulletList",
            "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": item}]}
                ]}
                for item in items
            ]
        } if items else {"type": "paragraph", "content": [{"type": "text", "text": "N/A"}]}

    # ── Date paragraph ──
    date_para = {
        "type": "paragraph",
        "content": [
            {"text": "Date: ", "type": "text", "marks": [{"type": "strong"}]},
            {"type": "date", "attrs": {"timestamp": friday_ts}},
        ]
    }

    # ── Header table (attendees, sprint goal, etc) ──
    header_table = {
        "type": "table",
        "attrs": {"layout": "default", "width": 760},
        "content": [
            _table_row("Attendees", [
                {"type": "mention", "attrs": {"id": "712020:db437afd-54db-4eb0-9034-70c3c526e37a", "text": "@Sonny"}},
                {"type": "text", "text": " "},
                {"type": "mention", "attrs": {"id": "712020:85218206-16f5-49a3-b40a-6f7c137ea1e8", "text": "@Joanne Raffel"}},
                {"type": "text", "text": " "},
                {"type": "mention", "attrs": {"id": "712020:447c348c-ae4f-4bba-87b6-99edddbc89e6", "text": "@Stephen Lai"}},
                {"type": "text", "text": " "},
                {"type": "mention", "attrs": {"id": "712020:b28bb054-a469-4a9f-bfde-0b93ad1101ae", "text": "@James Nicholls"}},
            ]),
            _table_row("For noting", [
                {"type": "mention", "attrs": {"id": "60cb00f1c90cb20068f5a203", "text": "@Dave Kuhn"}},
            ]),
            _table_row("Actions", [{"type": "text", "text": "N/A"}]),
            _table_row("Roadmap", [
                {"type": "text", "text": "Product roadmap",
                 "marks": [{"type": "link", "attrs": {"href": "https://product-roadmap-v10-production.up.railway.app/"}}]},
            ]),
            _table_row("Current sprint", [
                {"type": "text", "text": "Engineering backlog",
                 "marks": [{"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/jira/software/projects/AX/boards/1/backlog"}}]},
            ]),
            _table_row("Current sprint goal", [
                {"type": "text", "text": sprint_goal or "TBD"},
            ]),
        ]
    }

    # ── Insights table ──
    shipped_content = [
        {"type": "paragraph", "content": [
            {"text": "Shipped ", "type": "text", "marks": [{"type": "strong"}, {"type": "textColor", "attrs": {"color": "#4c9aff"}}]},
            {"type": "emoji", "attrs": {"shortName": ":rocket:", "text": "🚀"}},
        ]},
        _bullet_list(shipped) if shipped else {"type": "paragraph", "content": [{"type": "text", "text": "N/A"}]},
        {"type": "paragraph", "content": [{"type": "text", "text": "--"}]},
        {"type": "paragraph", "content": [
            {"text": "Upcoming", "type": "text", "marks": [{"type": "strong"}, {"type": "textColor", "attrs": {"color": "#4c9aff"}}]},
        ]},
        _bullet_list(upcoming) if upcoming else {"type": "paragraph", "content": [{"type": "text", "text": "TBD"}]},
    ]

    insights_table = {
        "type": "table",
        "attrs": {"layout": "center", "width": 760},
        "content": [
            {
                "type": "tableRow",
                "content": [
                    {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [220]},
                     "content": [{"type": "paragraph", "content": [
                         {"text": "Insights / callouts", "type": "text", "marks": [{"type": "strong"}]}
                     ]}]},
                    {"type": "tableCell", "attrs": {"colspan": 2, "rowspan": 1, "colwidth": [261, 279]},
                     "content": shipped_content},
                ]
            },
            {
                "type": "tableRow",
                "content": [
                    {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [220]},
                     "content": [{"type": "paragraph", "content": [
                         {"text": "Blocked", "type": "text", "marks": [{"type": "strong"}]}
                     ]}]},
                    {"type": "tableCell", "attrs": {"colspan": 2, "rowspan": 1, "colwidth": [261, 279]},
                     "content": [_bullet_list(blocked)]},
                ]
            },
            {
                "type": "tableRow",
                "content": [
                    {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [220]},
                     "content": [{"type": "paragraph", "content": [
                         {"text": "Discussion", "type": "text", "marks": [{"type": "strong"}]}
                     ]}]},
                    {"type": "tableCell", "attrs": {"colspan": 2, "rowspan": 1, "colwidth": [261, 279]},
                     "content": [{"type": "paragraph"}]},
                ]
            },
            # Prior decisions header
            {
                "type": "tableRow",
                "content": [
                    {"type": "tableCell", "attrs": {"colspan": 2, "rowspan": 1, "colwidth": [220, 261], "background": "#f4f5f7"},
                     "content": [{"type": "paragraph", "content": [
                         {"text": "Prior decisions", "type": "text", "marks": [{"type": "strong"}]}
                     ]}]},
                    {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [279], "background": "#f4f5f7"},
                     "content": [{"type": "paragraph"}]},
                ]
            },
            # Prior decisions column headers
            _three_col_row("Date", "Topic", "Decision", bold=True, bg="#ffffff"),
            # Carried-forward decisions
            _three_col_row("21/11/25", "Data", "Sonny, Dave and James are fully aligned on the proposed approach to policy data (new 'insurance' module)."),
            _three_col_row("21/11/25", "APIs", "Sonny, Dave and James agreed to position our API in a way that encourages insurer alignment, with the broader ambition of defining an industry-wide data standard for distribution."),
            _three_col_row("26/11/25", "Hiring", "Sonny has approved hiring a new mid–senior engineer, with a planned start date in January or February."),
            _three_col_row("01/12/25", "Design", "All agreed on Tailwind and Untitled React components."),
            _three_col_row("12/12/25", "Unified inbox", "All agreed on Front, after due diligence / vetting process was completed."),
            _three_col_row("27/01/26", "CRM UI facelift", "Approved to move forward. Final review by Jo when polish complete."),
            _three_col_row("05/03/26", "Refactor CRM", "Migrate from MySQL to PostgreSQL and React Frontend."),
        ]
    }

    return {
        "version": 1,
        "type": "doc",
        "content": [date_para, header_table, insights_table],
    }


def _table_row(label, value_nodes):
    """Build a 2-column table row with bold label and value nodes."""
    return {
        "type": "tableRow",
        "content": [
            {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [217]},
             "content": [{"type": "paragraph", "content": [
                 {"text": label, "type": "text", "marks": [{"type": "strong"}]}
             ]}]},
            {"type": "tableCell", "attrs": {"colspan": 1, "rowspan": 1, "colwidth": [541]},
             "content": [{"type": "paragraph", "content": value_nodes}]},
        ]
    }


def _three_col_row(col1, col2, col3, bold=False, bg=None):
    """Build a 3-column table row."""
    marks = [{"type": "strong"}] if bold else None
    cell_attrs_base = lambda w: {"colspan": 1, "rowspan": 1, "colwidth": [w]}

    def _cell(width, text):
        attrs = cell_attrs_base(width)
        if bg:
            attrs["background"] = bg
        content = [{"type": "text", "text": text}]
        if marks:
            content[0]["marks"] = marks
        return {"type": "tableCell", "attrs": attrs,
                "content": [{"type": "paragraph", "content": content}]}

    return {"type": "tableRow", "content": [_cell(220, col1), _cell(261, col2), _cell(279, col3)]}
