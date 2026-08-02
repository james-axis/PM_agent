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
    get_incomplete_issues, close_sprint, start_sprint, is_runway_sprint, sprint_number,
    move_issue_to_sprint, is_completed_status,
)
from telegram_bot import send_telegram


# ══════════════════════════════════════════════════════════════════════════════
# JOB A1: SPRINT LIFECYCLE (fully automated, runs Monday 6am AEST)
# ══════════════════════════════════════════════════════════════════════════════

def run_sprint_close():
    """Close the active sprint and move incomplete tickets to the next future sprint.
    Does NOT start the next sprint — that's a separate job.
    Runs Sunday 10pm AEST."""

    log.info("JOB A1: Sprint close starting...")

    active_sprints = get_active_sprints()
    if not active_sprints:
        log.info("JOB A1: No active sprint to close.")
        send_telegram("ℹ️ No active sprint to close.")
        return

    sprint = active_sprints[0]
    sid = sprint["id"]
    sprint_name = sprint["name"]

    # Gather sprint data
    all_issues = get_sprint_issues(sid)
    completed = [i for i in all_issues
                 if is_completed_status(i["fields"]["status"]["name"])]
    incomplete = [i for i in all_issues
                  if not is_completed_status(i["fields"]["status"]["name"])]

    total_pts = sum((i["fields"].get(STORY_POINTS_FIELD) or 0) for i in all_issues)
    done_pts = sum((i["fields"].get(STORY_POINTS_FIELD) or 0) for i in completed)
    incomplete_pts = sum((i["fields"].get(STORY_POINTS_FIELD) or 0) for i in incomplete)

    # ── Close the sprint ──
    if not close_sprint(sid):
        log.error(f"JOB A1: Failed to close sprint '{sprint_name}'.")
        send_telegram(f"❌ Failed to close sprint *{sprint_name}*. Manual intervention needed.")
        return

    log.info(f"JOB A1: Closed sprint '{sprint_name}'.")

    # ── Move incomplete tickets to next future sprint (lowest-numbered runway
    # sprint; never a label bucket, and immune to date-less sprints) ──
    future = sorted([s for s in get_future_sprints() if is_runway_sprint(s)], key=sprint_number)
    next_sprint = future[0] if future else None
    carryover_msg = ""

    if next_sprint and incomplete:
        carried = 0
        for issue in incomplete:
            if move_issue_to_sprint(issue["key"], next_sprint["id"]):
                carried += 1
        if carried:
            carryover_msg = f"\n🔄 {carried} incomplete ticket(s) moved to *{next_sprint['name']}*"
    elif not next_sprint and incomplete:
        carryover_msg = "\n⚠️ No future sprint to move incomplete tickets to."

    # ── Build summary ──
    inc_list = ""
    if incomplete:
        inc_items = [f"  • {i['key']} — {i['fields'].get('summary', '?')}"
                     for i in incomplete[:8]]
        if len(incomplete) > 8:
            inc_items.append(f"  ... +{len(incomplete) - 8} more")
        inc_list = "\n" + "\n".join(inc_items)

    msg = (
        f"🔒 *Sprint Closed*\n\n"
        f"Closed: *{sprint_name}*\n"
        f"✅ Completed: {len(completed)} tickets ({done_pts:.0f} pts)\n"
        f"⚠️ Incomplete: {len(incomplete)} tickets ({incomplete_pts:.0f} pts){inc_list}\n"
        f"📊 Velocity: {done_pts:.0f}/{total_pts:.0f} pts{carryover_msg}\n\n"
        f"_Next sprint starts Monday 7am._"
    )
    send_telegram(msg)
    log.info(f"JOB A1: Sprint close complete — {sprint_name}.")


def run_sprint_start():
    """Start the next future sprint. Runs Monday 7am AEST."""

    log.info("JOB A8: Sprint start starting...")

    active_sprints = get_active_sprints()
    if active_sprints:
        name = active_sprints[0]["name"]
        log.info(f"JOB A8: Sprint '{name}' already active. Skipping.")
        return

    future = sorted([s for s in get_future_sprints() if is_runway_sprint(s)], key=sprint_number)
    if not future:
        log.warning("JOB A8: No future sprints to start.")
        send_telegram("⚠️ No future sprints available to start. Check sprint runway.")
        return

    ns = future[0]
    if start_sprint(ns):
        log.info(f"JOB A8: Started sprint '{ns['name']}'.")
        send_telegram(f"🏃 *{ns['name']}* started. Let's go!")
    else:
        log.error(f"JOB A8: Failed to start '{ns['name']}'.")
        send_telegram(f"❌ Failed to start sprint *{ns['name']}*.")


def run_sprint_turnover():
    """Legacy: close + start in one step. Used by /sprint_turnover command."""
    run_sprint_close()
    run_sprint_start()

# ══════════════════════════════════════════════════════════════════════════════
# JOB A4: FRIDAY SPRINT REMINDER (4:30pm AEST every Friday)
# ══════════════════════════════════════════════════════════════════════════════

def post_friday_reminders():
    """Add a comment to every incomplete ticket in the active sprint
    warning that it will be moved to the next sprint on Monday 6am."""
    from jira_client import get_active_sprints, get_sprint_issues, add_comment_adf, is_completed_status

    log.info("JOB A4: Posting Friday sprint reminders...")

    active = get_active_sprints()
    if not active:
        log.info("JOB A4: No active sprint — skipping.")
        return

    sprint = active[0]
    all_issues = get_sprint_issues(sprint["id"])
    incomplete = [i for i in all_issues
                  if not is_completed_status(i["fields"]["status"]["name"])]

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
