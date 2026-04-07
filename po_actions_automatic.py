"""
PM Agent — Automatic Scheduled Actions
Fully automated sprint lifecycle + retrospective generation.
"""

import json
import re
import logging
from datetime import datetime
from uuid import uuid4
import pytz

from config import STORY_POINTS_FIELD, log
from jira_client import (
    get_active_sprints, get_future_sprints, get_sprint_issues,
    get_incomplete_issues, close_sprint, start_sprint,
    move_issue_to_sprint, COMPLETED_STATUSES,
)
from confluence_client import (
    confluence_search, create_page_adf, CHECKINS_PARENT_PAGE_ID,
)
from claude_client import call_claude
from telegram_bot import send_telegram

# ── Config ────────────────────────────────────────────────────────────────────

# Attendee account IDs for retro @mentions
ATTENDEES = [
    {"accountId": "5cf3eb99a6e4d50e24901e17", "name": "Dave Kuhn"},
    {"accountId": "712020:00983fc3-e82b-470b-b141-77804c9be677", "name": "Andrej Kudriavcev"},
    {"accountId": "712020:bc32a9de-a5bf-446a-bd4f-26091c942202", "name": "Dvir"},
    {"accountId": "712020:b28bb054-a469-4a9f-bfde-0b93ad1101ae", "name": "James Nicholls"},
]


# ══════════════════════════════════════════════════════════════════════════════
# JOB A1: SPRINT LIFECYCLE (fully automated, runs Monday 6am AEST)
# ══════════════════════════════════════════════════════════════════════════════

def run_sprint_turnover():
    """Close the active sprint, carry over incomplete tickets, start next sprint.
    Runs every Monday 6am AEST — fully automated, no approval needed."""

    log.info("JOB A1: Sprint turnover starting...")
    sydney_tz = pytz.timezone("Australia/Sydney")

    active_sprints = get_active_sprints()
    if not active_sprints:
        # No active sprint — just start the next one
        future = get_future_sprints()
        if future:
            ns = future[0]
            if start_sprint(ns):
                log.info(f"JOB A1: No active sprint found. Started '{ns['name']}'.")
                send_telegram(f"🏃 *{ns['name']}* started (no active sprint was found).")
            else:
                log.error(f"JOB A1: Failed to start '{ns['name']}'.")
                send_telegram(f"❌ Failed to start sprint '{ns['name']}'.")
        else:
            log.warning("JOB A1: No active or future sprints.")
            send_telegram("⚠️ No sprints available. Create sprints on the board.")
        return

    sprint = active_sprints[0]
    sid = sprint["id"]
    sprint_name = sprint["name"]

    # Gather sprint data
    all_issues = get_sprint_issues(sid)
    completed = [i for i in all_issues
                 if i["fields"]["status"]["name"].lower() in COMPLETED_STATUSES]
    incomplete = [i for i in all_issues
                  if i["fields"]["status"]["name"].lower() not in COMPLETED_STATUSES]

    total_pts = sum((i["fields"].get(STORY_POINTS_FIELD) or 0) for i in all_issues)
    done_pts = sum((i["fields"].get(STORY_POINTS_FIELD) or 0) for i in completed)
    incomplete_pts = sum((i["fields"].get(STORY_POINTS_FIELD) or 0) for i in incomplete)

    # ── Close the sprint ──
    if not close_sprint(sid):
        log.error(f"JOB A1: Failed to close sprint '{sprint_name}'.")
        send_telegram(f"❌ Failed to close sprint *{sprint_name}*. Manual intervention needed.")
        return

    log.info(f"JOB A1: Closed sprint '{sprint_name}'.")

    # ── Start next sprint ──
    future = get_future_sprints()
    next_sprint = future[0] if future else None
    next_name = "None"
    carryover_msg = ""

    if next_sprint:
        if start_sprint(next_sprint):
            next_name = next_sprint["name"]
            log.info(f"JOB A1: Started sprint '{next_name}'.")

            # ── Carry over incomplete tickets ──
            carried = 0
            for issue in incomplete:
                if move_issue_to_sprint(issue["key"], next_sprint["id"]):
                    carried += 1
            if carried:
                carryover_msg = f"\n🔄 {carried} incomplete ticket(s) moved to *{next_name}*"
        else:
            log.error(f"JOB A1: Failed to start '{next_sprint['name']}'.")
            carryover_msg = f"\n❌ Failed to start next sprint."
    else:
        carryover_msg = "\n⚠️ No future sprint to start."

    # ── Build summary ──
    inc_list = ""
    if incomplete:
        inc_items = [f"  • {i['key']} — {i['fields'].get('summary', '?')}"
                     for i in incomplete[:8]]
        if len(incomplete) > 8:
            inc_items.append(f"  ... +{len(incomplete) - 8} more")
        inc_list = "\n" + "\n".join(inc_items)

    msg = (
        f"🔄 *Sprint Turnover Complete*\n\n"
        f"Closed: *{sprint_name}*\n"
        f"✅ Completed: {len(completed)} tickets ({done_pts:.0f} pts)\n"
        f"⚠️ Incomplete: {len(incomplete)} tickets ({incomplete_pts:.0f} pts){inc_list}\n"
        f"📊 Velocity: {done_pts:.0f}/{total_pts:.0f} pts\n"
        f"Started: *{next_name}*{carryover_msg}"
    )
    send_telegram(msg)
    log.info(f"JOB A1: Sprint turnover complete — {sprint_name} → {next_name}.")

    # ── Generate retrospective ──
    try:
        generate_retrospective(sprint, completed, incomplete, total_pts, done_pts)
    except Exception as e:
        log.error(f"JOB A2: Retro generation error: {e}")
        send_telegram("❌ Failed to create retrospective page. Check logs.")


# ══════════════════════════════════════════════════════════════════════════════
# JOB A2: RETROSPECTIVE PAGE GENERATION
# ══════════════════════════════════════════════════════════════════════════════

def generate_retrospective(sprint, completed, incomplete, total_pts, done_pts):
    """Generate sprint retrospective Confluence page.
    Called automatically after sprint turnover."""

    log.info("JOB A2: Generating Retrospective page...")

    start_date = sprint.get("startDate", "")[:10]
    end_date = sprint.get("endDate", "")[:10]
    if not start_date or not end_date:
        log.warning("JOB A2: Sprint missing dates — skipping.")
        return None

    start_dt = datetime.strptime(start_date, "%Y-%m-%d")
    end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    title = f"{start_dt.strftime('%d/%m/%y')} - {end_dt.strftime('%d/%m/%y')} sprint retro summary"

    # Check if already exists
    existing = confluence_search(
        f'ancestor = {CHECKINS_PARENT_PAGE_ID} AND type = page AND title = "{title}"',
        limit=1,
    )
    if existing:
        log.info(f"JOB A2: Retro page '{title}' already exists. Skipping.")
        return None

    # Build sprint summary for Claude
    completed_summary = "\n".join([
        f"  - {i['key']}: {i['fields'].get('summary', '?')} "
        f"({i['fields'].get('issuetype', {}).get('name', '?')}, "
        f"{i['fields'].get(STORY_POINTS_FIELD) or 0} pts)"
        for i in completed[:20]
    ])
    incomplete_summary = "\n".join([
        f"  - {i['key']}: {i['fields'].get('summary', '?')} "
        f"({i['fields'].get('status', {}).get('name', '?')})"
        for i in incomplete[:10]
    ])

    sprint_goal = sprint.get("goal", "No goal set")

    # AI-generate retro content
    retro_content = _generate_retro_ai_content(
        sprint_name=sprint["name"],
        sprint_goal=sprint_goal,
        velocity=f"{done_pts:.0f}/{total_pts:.0f}",
        completed_summary=completed_summary,
        incomplete_summary=incomplete_summary,
        done_count=len(completed),
        incomplete_count=len(incomplete),
    )

    # Build ADF and create page
    adf = _build_retro_adf(retro_content)
    page_id, web_url = create_page_adf(title, adf, parent_id=CHECKINS_PARENT_PAGE_ID)

    if page_id:
        log.info(f"JOB A2: Created retro '{title}' — {web_url}")
        send_telegram(
            f"📝 *Sprint Retrospective* created for {sprint['name']}:\n"
            f"{web_url}\n\n"
            f"📊 Velocity: {done_pts:.0f}/{total_pts:.0f} pts "
            f"({len(completed)} done, {len(incomplete)} incomplete)"
        )
        return page_id, web_url
    else:
        log.error("JOB A2: Failed to create retro page.")
        return None


def _generate_retro_ai_content(sprint_name, sprint_goal, velocity, completed_summary,
                                incomplete_summary, done_count, incomplete_count):
    """Use Claude to generate retro good/bad/actions from sprint data."""

    prompt = (
        "You are analysing a sprint retrospective for a small product development team "
        "(Product Owner, Engineer, QA). Generate retrospective content based on the sprint data below.\n\n"
        f"Sprint: {sprint_name}\n"
        f"Sprint Goal: {sprint_goal}\n"
        f"Velocity: {velocity} story points\n"
        f"Completed ({done_count} tickets):\n{completed_summary}\n\n"
        f"Incomplete ({incomplete_count} tickets):\n{incomplete_summary}\n\n"
        "Return a JSON object with:\n"
        '- "good": list of 3-5 strings (what went well — based on tickets completed, themes, velocity)\n'
        '- "improve": list of 3-5 strings (what could be improved — based on incomplete work, patterns)\n'
        '- "actions": list of 1-3 strings (specific action items for next sprint)\n\n'
        "Be specific and reference actual ticket themes. Keep each item to 1 sentence.\n"
        "Return ONLY valid JSON, no preamble or markdown."
    )

    response = call_claude(prompt, max_tokens=800)
    if not response:
        return {"good": [], "improve": [], "actions": []}

    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response.strip())
        clean = re.sub(r'\s*```$', '', clean)
        return json.loads(clean)
    except json.JSONDecodeError as e:
        log.warning(f"JOB A2: Claude JSON parse error: {e}")
        return {"good": [], "improve": [], "actions": []}


def _build_retro_adf(retro_content):
    """Build ADF document for the retro page matching existing template."""
    good_items = retro_content.get("good", [])
    improve_items = retro_content.get("improve", [])
    actions = retro_content.get("actions", [])

    attendee_nodes = [{"type": "text", "text": "Attendees: ", "marks": [{"type": "strong"}]}]
    for i, att in enumerate(ATTENDEES):
        attendee_nodes.append({
            "type": "mention",
            "attrs": {"id": att["accountId"], "text": f"@{att['name']}",
                      "accessLevel": "", "userType": "DEFAULT"},
        })
        if i < len(ATTENDEES) - 1:
            attendee_nodes.append({"type": "text", "text": " "})

    header_row = {
        "type": "tableRow",
        "content": [
            {"type": "tableHeader", "content": [
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "What went well (Good)", "marks": [{"type": "strong"}]}
                ]}
            ]},
            {"type": "tableHeader", "content": [
                {"type": "paragraph", "content": [
                    {"type": "text", "text": "What could be improved (Bad / Could be better)",
                     "marks": [{"type": "strong"}]}
                ]}
            ]},
        ]
    }

    max_rows = max(len(good_items), len(improve_items), 5)
    data_rows = []
    for idx in range(max_rows):
        good_text = good_items[idx] if idx < len(good_items) else ""
        improve_text = improve_items[idx] if idx < len(improve_items) else ""
        data_rows.append({
            "type": "tableRow",
            "content": [
                {"type": "tableCell", "content": [
                    {"type": "paragraph",
                     "content": [{"type": "text", "text": good_text}] if good_text else []}
                ]},
                {"type": "tableCell", "content": [
                    {"type": "paragraph",
                     "content": [{"type": "text", "text": improve_text}] if improve_text else []}
                ]},
            ]
        })

    table = {"type": "table", "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
             "content": [header_row] + data_rows}

    actions_content = []
    for action in actions:
        actions_content.append({
            "type": "taskList",
            "attrs": {"localId": str(uuid4())[:8]},
            "content": [{
                "type": "taskItem",
                "attrs": {"localId": str(uuid4())[:8], "state": "TODO"},
                "content": [{"type": "text", "text": action}],
            }]
        })
    if not actions_content:
        actions_content = [{"type": "paragraph", "content": []}]

    other_content = [{"type": "bulletList", "content": [
        {"type": "listItem", "content": [{"type": "paragraph", "content": []}]}
    ]}]

    return {
        "version": 1,
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": attendee_nodes},
            {"type": "rule"},
            table,
            {"type": "heading", "attrs": {"level": 1},
             "content": [{"type": "text", "text": "Actions"}]},
            *actions_content,
            {"type": "heading", "attrs": {"level": 1},
             "content": [{"type": "text", "text": "Other discussion"}]},
            *other_content,
        ]
    }


# ══════════════════════════════════════════════════════════════════════════════
# JOB A4: FRIDAY SPRINT REMINDER (4:30pm AEST every Friday)
# ══════════════════════════════════════════════════════════════════════════════

def post_friday_reminders():
    """Add a comment to every incomplete ticket in the active sprint
    warning that it will be moved to the next sprint on Monday 6am."""
    from jira_client import get_active_sprints, get_sprint_issues, add_comment_adf, COMPLETED_STATUSES

    log.info("JOB A4: Posting Friday sprint reminders...")

    active = get_active_sprints()
    if not active:
        log.info("JOB A4: No active sprint — skipping.")
        return

    sprint = active[0]
    all_issues = get_sprint_issues(sprint["id"])
    incomplete = [i for i in all_issues
                  if i["fields"]["status"]["name"].lower() not in COMPLETED_STATUSES]

    if not incomplete:
        log.info(f"JOB A4: All tickets in '{sprint['name']}' are done. No reminders needed.")
        send_telegram(f"✅ All tickets in *{sprint['name']}* are released — no Friday reminders needed.")
        return

    commented = 0
    for issue in incomplete:
        key = issue["key"]
        assignee = issue["fields"].get("assignee")

        # Build ADF with @mention
        content_nodes = []
        if assignee and assignee.get("accountId"):
            content_nodes.append({
                "type": "mention",
                "attrs": {
                    "id": assignee["accountId"],
                    "text": f"@{assignee.get('displayName', 'assignee')}",
                    "accessLevel": "",
                    "userType": "DEFAULT",
                },
            })
            content_nodes.append({"type": "text", "text": " "})

        content_nodes.append({
            "type": "text",
            "text": "This task will be automatically moved to the next sprint at 6am on Monday "
                    "if it hasn't been marked as released before then — from Alfred.",
        })

        adf = {
            "version": 1,
            "type": "doc",
            "content": [{
                "type": "paragraph",
                "content": content_nodes,
            }]
        }

        if add_comment_adf(key, adf):
            commented += 1

    log.info(f"JOB A4: Posted reminders on {commented}/{len(incomplete)} tickets in '{sprint['name']}'.")
    send_telegram(
        f"⏰ *Friday Sprint Reminder*\n\n"
        f"Posted comments on {commented} incomplete ticket(s) in *{sprint['name']}*."
    )


# ══════════════════════════════════════════════════════════════════════════════
# TELEGRAM: /sprint_turnover command is registered in telegram_bot.py
# ══════════════════════════════════════════════════════════════════════════════
