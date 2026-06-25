"""
PM Agent — JOB A9: Board Refiner
Runs Mon-Fri 7am-7pm every 2hrs AEST.
Refines tickets in the Backlog ONLY — never touches tickets in any sprint:
1. Rewrites summary as user story ("I want...")
2. Fills description with user story + Given/When/Then acceptance criteria
3. Randomly assigns to Marc or Andrej
4. Transitions to Technical Planning status
5. Ranks tickets by priority (🟣 > Highest > High > Medium > Low > Lowest)
"""

import json
import re
import random
import logging
from datetime import datetime

from config import STORY_POINTS_FIELD, log
from jira_client import jira_get, jira_put
from claude_client import call_claude
from telegram_bot import send_telegram

# ── Config ────────────────────────────────────────────────────────────────────

MARC_ID = "712020:205e7e70-6257-4274-853f-d403e99854a1"
ANDREJ_ID = "712020:00983fc3-e82b-470b-b141-77804c9be677"
GARETH_ID = "712020:11bea6ad-d0cb-4b1c-9821-cf389926868f"
ENGINEERS = [MARC_ID, ANDREJ_ID]
KNOWN_ASSIGNEES = {MARC_ID, ANDREJ_ID, GARETH_ID}

# Priority sort order (lower = higher priority)
PRIORITY_ORDER = {
    "highest": 1,
    "high": 2,
    "medium": 3,
    "low": 4,
    "lowest": 5,
}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run_board_refiner():
    """Refine tickets in the Backlog only. Never touches tickets in any sprint."""

    log.info("JOB A9: Board refiner starting...")

    # Backlog tickets only (excludes every sprint — active and future)
    all_targets = _get_backlog_issues()
    for issue in all_targets:
        issue["_sprint_id"] = None
        issue["_sprint_name"] = "Backlog"

    if not all_targets:
        log.info("JOB A9: No backlog tickets to refine.")
        return

    # ── Step 1-4: Refine tickets in Technical Planning or Refinement ──
    ready_tickets = [i for i in all_targets
                     if i["fields"]["status"]["name"] in ("Technical Planning", "Refinement")]

    refined = 0
    for issue in ready_tickets:
        try:
            if _refine_ticket(issue):
                refined += 1
        except Exception as e:
            log.error(f"JOB A9: Error refining {issue['key']}: {e}")

    # ── Step 5: Rank the backlog by priority ──
    ranked = False
    try:
        ranked = _rank_by_priority(all_targets)
    except Exception as e:
        log.error(f"JOB A9: Error ranking backlog: {e}")

    if refined > 0 or ranked:
        log.info(f"JOB A9: Refined {refined} backlog tickets, ranked={ranked}.")
        send_telegram(
            f"🔧 *Board Refiner*\n"
            f"Refined: {refined} backlog ticket(s)\n"
            f"Ranked: {'backlog' if ranked else 'none'}"
        )
    else:
        log.info("JOB A9: Nothing to refine or rank.")

    return refined


def _get_backlog_issues():
    """Get issues in the backlog (not in any sprint)."""
    data = jira_get("/rest/agile/1.0/board/1/backlog", params={
        "fields": f"summary,status,priority,assignee,description,issuetype,parent,{STORY_POINTS_FIELD}",
        "maxResults": 100,
    })
    if not data:
        return []
    issues = data.get("issues", [])
    # Filter to only issues not in any sprint
    return [i for i in issues if not i["fields"].get("sprint")]


# ══════════════════════════════════════════════════════════════════════════════
# STEP 1-4: REFINE INDIVIDUAL TICKETS
# ══════════════════════════════════════════════════════════════════════════════

def _refine_ticket(issue):
    """Refine a single Ready ticket: user story, description, assign, transition."""
    key = issue["key"]
    current_summary = issue["fields"].get("summary", "")
    current_desc = issue["fields"].get("description")
    issue_type = issue["fields"].get("issuetype", {}).get("name", "Task")
    parent_summary = (issue["fields"].get("parent") or {}).get("fields", {}).get("summary", "")

    # Skip if already has a user story title
    if current_summary.lower().startswith("i want") or current_summary.lower().startswith("as a"):
        log.info(f"JOB A9: {key} already has user story title. Skipping.")
        return False

    # Skip Epics — only refine Tasks
    if issue_type == "Epic":
        log.info(f"JOB A9: {key} is an Epic. Skipping.")
        return False

    log.info(f"JOB A9: Refining {key}: {current_summary}")

    # ── Generate user story + acceptance criteria via Claude ──
    prompt = (
        "You are a product manager writing a Jira task for a life insurance CRM platform.\n\n"
        f"Task: {current_summary}\n"
        f"Epic: {parent_summary}\n"
        f"Issue type: {issue_type}\n\n"
        "Generate:\n"
        '1. "title": A user story title starting with "I want..." (max 15 words)\n'
        '2. "user_story": Full user story "As a [role], I want [goal], so that [benefit]"\n'
        '3. "acceptance_criteria": Array of 3-5 items in Given/When/Then format:\n'
        '   "Given [context], When [action], Then [expected result]"\n\n'
        "Return ONLY valid JSON, no preamble or markdown.\n"
        "Be specific to Axis CRM context: advisers, insurers, applications, commissions, compliance."
    )

    response = call_claude(prompt, max_tokens=800)
    if not response:
        log.warning(f"JOB A9: Claude failed for {key}")
        return False

    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response.strip())
        clean = re.sub(r'\s*```$', '', clean)
        data = json.loads(clean)
    except json.JSONDecodeError as e:
        log.warning(f"JOB A9: Claude JSON parse error for {key}: {e}")
        return False

    new_title = data.get("title", current_summary)[:250]
    user_story = data.get("user_story", "")
    ac_items = data.get("acceptance_criteria", [])

    # ── Build ADF description ──
    # Format: bold section headings — User story / Acceptance criteria (numbered)
    # / Engineer notes.
    content = [
        {"type": "paragraph", "content": [
            {"type": "text", "text": "User story: ", "marks": [{"type": "strong"}]},
            {"type": "text", "text": user_story or current_summary},
        ]},
        {"type": "paragraph", "content": [
            {"type": "text", "text": "Acceptance criteria:", "marks": [{"type": "strong"}]},
        ]},
    ]

    clean_ac = [ac for ac in ac_items if isinstance(ac, str) and ac.strip()]
    if clean_ac:
        content.append({"type": "orderedList", "attrs": {"order": 1}, "content": [
            {"type": "listItem", "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": ac}]}
            ]} for ac in clean_ac
        ]})

    content.append({"type": "paragraph", "content": [
        {"type": "text", "text": "Engineer notes:", "marks": [{"type": "strong"}]},
    ]})

    description_adf = {
        "version": 1,
        "type": "doc",
        "content": content,
    }

    # ── Update ticket: summary, description, assignee (if not already assigned) ──
    current_assignee = (issue["fields"].get("assignee") or {}).get("accountId")
    update_fields = {
        "summary": new_title,
        "description": description_adf,
    }

    # Only assign if not already assigned to Marc, Andrej, or Gareth
    assigned_to = ""
    if current_assignee not in KNOWN_ASSIGNEES:
        assignee_id = random.choice(ENGINEERS)
        update_fields["assignee"] = {"accountId": assignee_id}
        assigned_to = f" (assigned: {'Marc' if assignee_id == MARC_ID else 'Andrej'})"
    else:
        assigned_to = " (assignee unchanged)"

    ok, resp = jira_put(f"/rest/api/3/issue/{key}", {"fields": update_fields})
    if not ok:
        log.error(f"JOB A9: Failed to update {key}: {resp.status_code if resp else 'no response'}")
        return False

    log.info(f"JOB A9: Refined {key} → '{new_title}'{assigned_to}")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# STEP 5: RANK BY PRIORITY
# ══════════════════════════════════════════════════════════════════════════════

def _rank_by_priority(issues):
    """Sort issues by priority: 🟣 emoji > Highest > High > Medium > Low > Lowest."""
    if len(issues) < 2:
        return False

    def _sort_key(issue):
        summary = issue["fields"].get("summary", "")
        priority_name = (issue["fields"].get("priority") or {}).get("name", "Medium").lower()
        priority_rank = PRIORITY_ORDER.get(priority_name, 3)

        # 🟣 in summary = rank 0 (above Highest)
        if "🟣" in summary:
            priority_rank = 0

        return priority_rank

    sorted_issues = sorted(issues, key=_sort_key)

    # Use Jira rank API to reorder
    for i in range(1, len(sorted_issues)):
        current = sorted_issues[i]
        previous = sorted_issues[i - 1]

        try:
            jira_put("/rest/agile/1.0/issue/rank", {
                "issues": [current["key"]],
                "rankAfterIssue": previous["key"],
            })
        except Exception as e:
            log.warning(f"JOB A9: Failed to rank {current['key']} after {previous['key']}: {e}")

    return True
