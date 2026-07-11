"""
PM Agent — JOB A9: Board Refiner
Runs Mon-Fri 7am-7pm every 2hrs AEST.
Scans Backlog tickets ONLY (never touches tickets in any sprint), and only those
whose status is "Technical Planning" or "Refinement" — all other statuses are left
untouched.

It does NOT rewrite the summary or description (the requestor's original wording
and name are kept intact). For each matching ticket it only:
1. Priority defaulted to Low
2. Unassigned (assignee cleared; reporter left as-is)
3. Story points cleared
4. Backlog ordered oldest (top) → newest (bottom)
"""

from config import STORY_POINTS_FIELD, log
from jira_client import jira_get, jira_put
from telegram_bot import send_telegram

# Only normalise/reorder backlog tickets in these statuses — never touch others.
REFINE_STATUSES = {"Technical Planning", "Refinement"}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run_board_refiner():
    """Normalise backlog tickets (priority/assignee/SP) and order oldest→newest.

    Backlog only — never touches tickets in any sprint. Never edits summary/description.
    """
    log.info("JOB A9: Board refiner starting...")

    issues = _get_backlog_issues()
    if not issues:
        log.info("JOB A9: No backlog tickets.")
        return 0

    # Only act on Technical Planning / Refinement tickets (skip Epics and all other
    # statuses — they are left completely untouched, including their backlog order).
    targets = [i for i in issues
               if (i["fields"].get("issuetype") or {}).get("name") != "Epic"
               and (i["fields"].get("status") or {}).get("name") in REFINE_STATUSES]

    if not targets:
        log.info("JOB A9: No backlog tickets in Technical Planning / Refinement.")
        return 0

    normalized = 0
    for issue in targets:
        try:
            if _normalize_ticket(issue):
                normalized += 1
        except Exception as e:
            log.error(f"JOB A9: Error normalising {issue['key']}: {e}")

    # Order the backlog oldest → newest
    ordered = False
    try:
        ordered = _order_backlog_by_created(targets)
    except Exception as e:
        log.error(f"JOB A9: Error ordering backlog: {e}")

    if normalized > 0 or ordered:
        log.info(f"JOB A9: Normalised {normalized} backlog ticket(s), reordered={ordered}.")
        send_telegram(
            f"🔧 *Board Refiner*\n"
            f"Normalised: {normalized} backlog ticket(s)\n"
            f"Reordered: {'oldest→newest' if ordered else 'already in order'}"
        )
    else:
        log.info("JOB A9: Backlog already conforms — nothing to do.")

    return normalized


def _get_backlog_issues():
    """Get issues in the backlog (not in any sprint)."""
    data = jira_get("/rest/agile/1.0/board/1/backlog", params={
        "fields": f"summary,status,priority,assignee,issuetype,created,{STORY_POINTS_FIELD}",
        "maxResults": 100,
    })
    if not data:
        return []
    issues = data.get("issues", [])
    # Safety net: only issues not in any sprint (the backlog endpoint already excludes them)
    return [i for i in issues if not i["fields"].get("sprint")]


# ══════════════════════════════════════════════════════════════════════════════
# NORMALISE INDIVIDUAL TICKETS (fields only — never summary/description)
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_ticket(issue):
    """Set priority=Low, unassign, and clear story points. Idempotent — only PUTs
    when something differs. Summary and description are never touched.
    Returns True if the ticket was changed."""
    key = issue["key"]
    f = issue["fields"]

    update = {}
    if (f.get("priority") or {}).get("name") != "Low":
        update["priority"] = {"name": "Low"}
    if f.get("assignee"):
        update["assignee"] = {"accountId": None}  # unassign
    if f.get(STORY_POINTS_FIELD) is not None:
        update[STORY_POINTS_FIELD] = None  # clear story points

    if not update:
        return False

    ok, resp = jira_put(f"/rest/api/3/issue/{key}", {"fields": update})
    if not ok:
        log.error(f"JOB A9: Failed to update {key}: {resp.status_code if resp else 'no response'}")
        return False

    log.info(f"JOB A9: Normalised {key} ({', '.join(update.keys())})")
    return True


# ══════════════════════════════════════════════════════════════════════════════
# ORDER BACKLOG OLDEST → NEWEST
# ══════════════════════════════════════════════════════════════════════════════

def _order_backlog_by_created(issues):
    """Rank the backlog so the oldest ticket is at the top, newest at the bottom.

    Skips the rank API entirely when the backlog is already in order. Returns True
    if a reorder was applied.
    """
    if len(issues) < 2:
        return False

    current_order = [i["key"] for i in issues]
    sorted_issues = sorted(issues, key=lambda i: i["fields"].get("created", "") or "")
    desired_order = [i["key"] for i in sorted_issues]
    if current_order == desired_order:
        return False  # already oldest → newest

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
