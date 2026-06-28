"""
PM Agent — JOB A9: Board Refiner
Runs Mon-Fri 7am-7pm every 2hrs AEST.
Scans EVERY ticket in the Backlog ONLY (never touches tickets in any sprint) and
normalises each to a consistent triage state:
1. Summary starts with "⚠️ " followed by a short 3-5 word summary
2. Description = a short paragraph of the issue/request + who requested it (name + email)
3. Priority defaulted to Low
4. Unassigned
5. Story points cleared
6. Backlog ordered oldest (top) → newest (bottom)
"""

import json
import re

from config import STORY_POINTS_FIELD, log
from jira_client import jira_get, jira_put, _extract_adf_text
from claude_client import call_claude
from telegram_bot import send_telegram


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def run_board_refiner():
    """Normalise every backlog ticket and order the backlog oldest→newest.

    Backlog only — never touches tickets in any sprint.
    """
    log.info("JOB A9: Board refiner starting...")

    issues = _get_backlog_issues()
    if not issues:
        log.info("JOB A9: No backlog tickets.")
        return 0

    # Epics are structured differently and aren't triage cards — skip them.
    targets = [i for i in issues
               if (i["fields"].get("issuetype") or {}).get("name") != "Epic"]

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
        "fields": f"summary,status,priority,assignee,description,issuetype,reporter,created,{STORY_POINTS_FIELD}",
        "maxResults": 100,
    })
    if not data:
        return []
    issues = data.get("issues", [])
    # Safety net: only issues not in any sprint (the backlog endpoint already excludes them)
    return [i for i in issues if not i["fields"].get("sprint")]


# ══════════════════════════════════════════════════════════════════════════════
# NORMALISE INDIVIDUAL TICKETS
# ══════════════════════════════════════════════════════════════════════════════

def _normalize_ticket(issue):
    """Bring a single backlog ticket into the standard triage state.

    Idempotent: cheap fields are only changed when they differ; the Claude-backed
    title/description rewrite is skipped once the summary already starts with "⚠️".
    Returns True if the ticket was changed.
    """
    key = issue["key"]
    f = issue["fields"]
    summary = (f.get("summary") or "").strip()

    update = {}

    # ── Cheap, idempotent field normalisations ──
    if (f.get("priority") or {}).get("name") != "Low":
        update["priority"] = {"name": "Low"}
    if f.get("assignee"):
        update["assignee"] = {"accountId": None}  # unassign
    if f.get(STORY_POINTS_FIELD) is not None:
        update[STORY_POINTS_FIELD] = None  # clear story points

    # ── Title + description (only when the title isn't already conforming) ──
    if not summary.startswith("⚠️"):
        gen = _generate_card_content(summary, _desc_text(f))
        if gen:
            short = (gen.get("summary") or "").strip().strip(".")[:120] or summary
            paragraph = (gen.get("paragraph") or "").strip()
            update["summary"] = f"⚠️ {short}"
            update["description"] = _build_description_adf(paragraph, _requester(f))
        else:
            log.warning(f"JOB A9: Claude failed for {key} — leaving title/description")

    if not update:
        return False

    ok, resp = jira_put(f"/rest/api/3/issue/{key}", {"fields": update})
    if not ok:
        log.error(f"JOB A9: Failed to update {key}: {resp.status_code if resp else 'no response'}")
        return False

    log.info(f"JOB A9: Normalised {key} → {update.get('summary', summary)}")
    return True


def _generate_card_content(current_summary, current_desc_text):
    """Ask Claude for a 3-5 word summary + a short plain-language paragraph.

    Returns {"summary": str, "paragraph": str} or None on failure.
    """
    prompt = (
        "You are triaging a backlog ticket for Axis CRM (a life insurance CRM platform).\n\n"
        f"Current title: {current_summary}\n"
        f"Current details: {(current_desc_text or '(none)')[:1500]}\n\n"
        "Return JSON only (no preamble, no markdown fences):\n"
        '{"summary": "...", "paragraph": "..."}\n\n'
        "Rules:\n"
        "- summary: 3-5 words capturing the essence of the request. No leading emoji.\n"
        "- paragraph: 2-3 plain sentences describing the issue or request.\n"
        "- Do NOT invent who requested it; describe only the issue/request itself."
    )
    response = call_claude(prompt, max_tokens=400)
    if not response:
        return None
    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response.strip())
        clean = re.sub(r'\s*```$', '', clean)
        data = json.loads(clean)
        if isinstance(data, dict) and data.get("summary"):
            return data
    except json.JSONDecodeError as e:
        log.warning(f"JOB A9: Claude JSON parse error: {e}")
    return None


def _requester(fields):
    """Reporter as 'Name (email)', or 'Name', or 'Unknown'."""
    rep = fields.get("reporter") or {}
    name = rep.get("displayName") or "Unknown"
    email = rep.get("emailAddress")
    return f"{name} ({email})" if email else name


def _desc_text(fields):
    """Plain text of the current description (ADF → text), or ''."""
    desc = fields.get("description")
    if isinstance(desc, dict):
        return _extract_adf_text(desc)
    return desc or ""


def _build_description_adf(paragraph, requester):
    """ADF doc: a short paragraph + a 'Requested by:' line."""
    content = []
    if paragraph:
        content.append({"type": "paragraph", "content": [{"type": "text", "text": paragraph}]})
    content.append({"type": "paragraph", "content": [
        {"type": "text", "text": "Requested by: ", "marks": [{"type": "strong"}]},
        {"type": "text", "text": requester},
    ]})
    return {"version": 1, "type": "doc", "content": content}


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
