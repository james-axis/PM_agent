"""
PM Agent — JOB A9: Board Refiner
Runs Mon-Fri 7am-7pm every 2hrs AEST.
Scans Backlog tickets ONLY (never touches tickets in any sprint), and only those
whose status is "Technical Planning" or "Refinement" — all other statuses are left
untouched.

It does NOT rewrite the summary or description (the requestor's original wording
and name are kept intact). For each matching ticket it only:
1. Unassigned (assignee cleared; reporter left as-is)
2. Story points cleared
3. Adds a label with the requestor's first name (parsed from the description),
   so tickets can be filtered by who raised them
4. Ordered by Priority (Highest → Lowest), then created date (oldest → newest).
   Priority itself is left untouched so it drives the order.
"""

from config import STORY_POINTS_FIELD, log
from jira_client import jira_get, jira_put, _extract_adf_text
from requestor import extract_first_name

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

    # Order by Priority (Highest→Lowest), then created date (oldest→newest)
    ordered = False
    try:
        ordered = _order_backlog_by_priority(targets)
    except Exception as e:
        log.error(f"JOB A9: Error ordering backlog: {e}")

    # Runs every 5 min — log only (no Telegram) to avoid spam.
    if normalized > 0 or ordered:
        log.info(f"JOB A9: Normalised {normalized} backlog ticket(s), reordered={ordered}.")
    else:
        log.info("JOB A9: Backlog already conforms — nothing to do.")

    return normalized


def _get_backlog_issues():
    """Get issues in the backlog (not in any sprint)."""
    data = jira_get("/rest/agile/1.0/board/1/backlog", params={
        "fields": f"summary,status,priority,assignee,issuetype,created,description,labels,{STORY_POINTS_FIELD}",
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
    """Unassign, clear story points, and add a label with the requestor's first name
    (from the description). Priority is left as-is so it can be used for ordering.
    Idempotent — only PUTs when something differs. Summary/description never touched.
    Returns True if the ticket was changed."""
    key = issue["key"]
    f = issue["fields"]

    update = {}
    if f.get("assignee"):
        update["assignee"] = {"accountId": None}  # unassign
    if f.get(STORY_POINTS_FIELD) is not None:
        update[STORY_POINTS_FIELD] = None  # clear story points

    # Label the ticket with the requestor's first name (from the description)
    label = _requestor_label(f)

    if not update and not label:
        return False

    payload = {}
    if update:
        payload["fields"] = update
    if label:
        payload["update"] = {"labels": [{"add": label}]}

    ok, resp = jira_put(f"/rest/api/3/issue/{key}", payload)
    if not ok:
        log.error(f"JOB A9: Failed to update {key}: {resp.status_code if resp else 'no response'}")
        return False

    touched = list(update.keys()) + ([f"label:{label}"] if label else [])
    log.info(f"JOB A9: Normalised {key} ({', '.join(touched)})")
    return True


def _requestor_label(fields):
    """First name of the requestor (from the description) if not already a label."""
    desc = fields.get("description")
    desc_text = _extract_adf_text(desc) if isinstance(desc, dict) else (desc or "")
    name = extract_first_name(desc_text)
    if not name:
        return None
    existing = {l.lower() for l in (fields.get("labels") or [])}
    return None if name.lower() in existing else name


# ══════════════════════════════════════════════════════════════════════════════
# ORDER BACKLOG BY PRIORITY, THEN CREATED DATE
# ══════════════════════════════════════════════════════════════════════════════

# Lower rank = higher on the board (Highest at top → Lowest at bottom).
PRIORITY_RANK = {"highest": 1, "high": 2, "medium": 3, "low": 4, "lowest": 5}


def _order_backlog_by_priority(issues):
    """Rank the backlog by Priority (Highest → Lowest), then created date
    (oldest → newest) as the tiebreaker.

    Skips the rank API entirely when the backlog is already in order. Returns True
    if a reorder was applied.
    """
    if len(issues) < 2:
        return False

    def _key(i):
        pr = ((i["fields"].get("priority") or {}).get("name") or "Medium").lower()
        return (PRIORITY_RANK.get(pr, 3), i["fields"].get("created", "") or "")

    current_order = [i["key"] for i in issues]
    sorted_issues = sorted(issues, key=_key)
    desired_order = [i["key"] for i in sorted_issues]
    if current_order == desired_order:
        return False  # already ordered

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
