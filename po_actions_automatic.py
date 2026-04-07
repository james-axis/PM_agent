"""
PM Agent — Automatic Scheduled Actions
Fully automated sprint lifecycle + Friday reminders.
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
from telegram_bot import send_telegram


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
