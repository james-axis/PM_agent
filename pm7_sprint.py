"""
PM Agent — PM7: Sprint Scheduler
Reads the AR idea's Roadmap field (e.g. "March (S1)") and moves
all tasks + Epic into the matching AX sprint.

Roadmap field: customfield_10560
  Values: "January (S1)", "February (S2)", "March (S1)", "Shipped", "Backlog", etc.
  S1 = first 2-week sprint starting in that month
  S2 = second 2-week sprint starting in that month

Sprint naming convention: "DD/MM/YYYY - DD/MM/YYYY" (2-week sprints starting Tuesdays)
"""

import re
from datetime import datetime
from config import JIRA_BASE_URL, ROADMAP_FIELD, ANDREJ_ACCOUNT_ID, READY_TRANSITION_ID, log
from jira_client import jira_get, jira_post, get_issue, add_comment, assign_issue, transition_issue

# AX board ID (sprint board)
AX_BOARD_ID = 1

# Month name → number mapping
MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


def get_future_sprints():
    """Get all future + active sprints from the AX board."""
    sprints = []
    for state in ("active", "future"):
        try:
            data = jira_get(f"/rest/agile/1.0/board/{AX_BOARD_ID}/sprint?state={state}")
            sprints.extend(data.get("values", []))
        except Exception as e:
            log.error(f"PM7: Failed to fetch {state} sprints: {e}")
    # Sort by start date
    sprints.sort(key=lambda s: s.get("startDate", ""))
    return sprints


def move_to_sprint(issue_key, sprint_id):
    """Move a single issue into a sprint."""
    try:
        ok, r = jira_post(
            f"/rest/agile/1.0/sprint/{sprint_id}/issue",
            {"issues": [issue_key]},
        )
        if ok:
            log.info(f"PM7: Moved {issue_key} to sprint {sprint_id}")
            return True
        else:
            log.error(f"PM7: Failed to move {issue_key}: {r.status_code} {r.text[:200]}")
            return False
    except Exception as e:
        log.error(f"PM7: Exception moving {issue_key}: {e}")
        return False


def parse_roadmap_value(roadmap_str):
    """
    Parse roadmap field value like "March (S1)" into (month_number, sprint_index).
    Returns (month_number, sprint_index) or (None, None) if unparseable.
    sprint_index: 0 for S1, 1 for S2.
    """
    if not roadmap_str:
        return None, None

    # Handle non-month values
    lower = roadmap_str.lower().strip()
    if lower in ("backlog", "shipped", "delivered", ""):
        return None, None

    # Parse "Month (SN)"
    match = re.match(r'^(\w+)\s*\(S(\d+)\)$', roadmap_str.strip(), re.IGNORECASE)
    if not match:
        log.warning(f"PM7: Could not parse roadmap value: '{roadmap_str}'")
        return None, None

    month_name = match.group(1).lower()
    sprint_num = int(match.group(2))

    month_number = MONTH_MAP.get(month_name)
    if not month_number:
        log.warning(f"PM7: Unknown month: '{month_name}'")
        return None, None

    return month_number, sprint_num - 1  # 0-indexed


def find_matching_sprint(target_month, sprint_index, sprints):
    """
    Find the Nth sprint (0-indexed) whose start date falls in target_month.
    Sprint names are "DD/MM/YYYY - DD/MM/YYYY".
    """
    # Determine target year — use current year, but if the month is in the past
    # and there are sprints next year, use next year
    now = datetime.now()
    target_year = now.year

    # If target month is behind current month, assume next year
    if target_month < now.month:
        target_year = now.year + 1

    month_sprints = []
    for sprint in sprints:
        start_str = sprint.get("startDate", "")
        if not start_str:
            continue
        try:
            # Parse ISO date from sprint
            start_date = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
            if start_date.month == target_month and start_date.year == target_year:
                month_sprints.append(sprint)
        except Exception:
            continue

    # Sort by start date
    month_sprints.sort(key=lambda s: s.get("startDate", ""))

    if sprint_index < len(month_sprints):
        return month_sprints[sprint_index]

    # Fallback: if no exact match, try any year
    if not month_sprints:
        for sprint in sprints:
            start_str = sprint.get("startDate", "")
            try:
                start_date = datetime.fromisoformat(start_str.replace("Z", "+00:00"))
                if start_date.month == target_month:
                    month_sprints.append(sprint)
            except Exception:
                continue
        month_sprints.sort(key=lambda s: s.get("startDate", ""))
        if sprint_index < len(month_sprints):
            return month_sprints[sprint_index]

    log.warning(f"PM7: No sprint found for month={target_month}, index={sprint_index}")
    return None


def process_sprint_scheduling(source_idea_key, epic_key, tasks, chat_id, bot):
    """
    Full PM7 pipeline: read roadmap → find sprint → move issues → confirm.

    Args:
        source_idea_key: AR idea key (e.g. "AR-123")
        epic_key: AX epic key (e.g. "AX-100")
        tasks: list of dicts with at least "key" field
        chat_id: Telegram chat ID
        bot: Telegram bot instance
    """
    status_msg = bot.send_message(chat_id, f"📅 Scheduling sprint for {epic_key}...")

    # Step 1: Read AR idea's Roadmap field
    issue = get_issue(source_idea_key)
    if not issue:
        bot.edit_message_text(f"⚠️ Could not fetch {source_idea_key} to read Roadmap field.", chat_id, status_msg.message_id)
        return

    roadmap_field = issue.get("fields", {}).get(ROADMAP_FIELD)
    if not roadmap_field:
        _cleanup_and_notify(bot, chat_id, status_msg.message_id, epic_key,
                            "⚠️ No Roadmap field set on idea — skipping sprint assignment.")
        return

    roadmap_value = roadmap_field.get("value", "") if isinstance(roadmap_field, dict) else str(roadmap_field)
    log.info(f"PM7: {source_idea_key} Roadmap = '{roadmap_value}'")

    # Step 2: Parse roadmap value
    target_month, sprint_index = parse_roadmap_value(roadmap_value)
    if target_month is None:
        _cleanup_and_notify(bot, chat_id, status_msg.message_id, epic_key,
                            f"⚠️ Roadmap value '{roadmap_value}' — not a sprint target, skipping.")
        return

    # Step 3: Get future sprints
    bot.edit_message_text("📅 Finding matching sprint...", chat_id, status_msg.message_id)
    sprints = get_future_sprints()
    if not sprints:
        _cleanup_and_notify(bot, chat_id, status_msg.message_id, epic_key,
                            "⚠️ No future sprints found in AX board.")
        return

    target_sprint = find_matching_sprint(target_month, sprint_index, sprints)
    if not target_sprint:
        _cleanup_and_notify(bot, chat_id, status_msg.message_id, epic_key,
                            f"⚠️ No AX sprint found matching '{roadmap_value}'.")
        return

    sprint_id = target_sprint["id"]
    sprint_name = target_sprint.get("name", str(sprint_id))
    log.info(f"PM7: Matched '{roadmap_value}' → sprint '{sprint_name}' (ID {sprint_id})")

    # Step 4: Move Epic + all tasks into the sprint
    bot.edit_message_text(f"📅 Moving {len(tasks) + 1} issues to '{sprint_name}'...",
                          chat_id, status_msg.message_id)

    all_keys = [epic_key] + [t["key"] for t in tasks]
    moved = 0
    failed_keys = []

    for key in all_keys:
        if move_to_sprint(key, sprint_id):
            moved += 1
        else:
            failed_keys.append(key)

    # Step 5: Assign all issues to Andrej and transition to Ready
    bot.edit_message_text(f"📅 Assigning & setting Ready for {len(all_keys)} issues...",
                          chat_id, status_msg.message_id)

    assigned = 0
    transitioned = 0
    for key in all_keys:
        if assign_issue(key, ANDREJ_ACCOUNT_ID):
            assigned += 1
        if transition_issue(key, READY_TRANSITION_ID):
            transitioned += 1

    # Step 6: Clean up status and send confirmation
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    # Comment on epic
    add_comment(epic_key, f"Sprint scheduled: {moved}/{len(all_keys)} issues moved to '{sprint_name}', assigned to Andrej, status → Ready (from {source_idea_key} Roadmap: {roadmap_value})")

    # Telegram confirmation
    epic_link = f"https://axiscrm.atlassian.net/browse/{epic_key}"
    idea_link = f"https://axiscrm.atlassian.net/browse/{source_idea_key}"
    msg = (
        f"📅 *Sprint Scheduled* — [{epic_key}]({epic_link})\n"
        f"Roadmap: [{source_idea_key}]({idea_link}) → _{roadmap_value}_\n"
        f"Sprint: *{sprint_name}*\n"
        f"Moved: {moved}/{len(all_keys)} · Assigned: {assigned} · Ready: {transitioned}"
    )
    if failed_keys:
        msg += f"\n⚠️ Failed: {', '.join(failed_keys)}"

    bot.send_message(chat_id, msg, parse_mode="Markdown", disable_web_page_preview=True)
    log.info(f"PM7: Scheduled {moved}/{len(all_keys)} issues for {epic_key} → '{sprint_name}'")


def _cleanup_and_notify(bot, chat_id, status_msg_id, epic_key, message):
    """Delete status message and send a notification."""
    try:
        bot.delete_message(chat_id, status_msg_id)
    except Exception:
        pass
    epic_link = f"https://axiscrm.atlassian.net/browse/{epic_key}"
    bot.send_message(
        chat_id,
        f"[{epic_key}]({epic_link}): {message}",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )
    log.info(f"PM7: {epic_key} — {message}")
