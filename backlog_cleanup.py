"""
PM Agent — one-time Backlog cleanup

Brings every ticket in the board Backlog section into the triage state the new
refiner enforces, WITHOUT losing the requestor's original wording:
  - priority → Low, unassigned, story points cleared
  - if the old refiner rewrote the summary (starts with "⚠️"), restore the
    original summary from the ticket history
  - descriptions are left as-is (they hold the original request + requestor);
    only restored if they actually carry the old refiner's "Requested by:" marker

Run once via the /cleanupbacklog Telegram command. Idempotent: once summaries are
restored and fields normalised, re-running is a no-op.
"""

from config import STORY_POINTS_FIELD, log
from jira_client import jira_get, jira_put, _extract_adf_text

REFINER_DESC_MARKER = "Requested by: "


def _fetch_backlog():
    """The board Backlog section (issues not in any sprint)."""
    data = jira_get("/rest/agile/1.0/board/1/backlog", params={
        "fields": f"summary,description,priority,assignee,issuetype,{STORY_POINTS_FIELD}",
        "maxResults": 200,
    })
    issues = data.get("issues", []) if data else []
    return [i for i in issues if not i["fields"].get("sprint")]


def _changelog_originals(key):
    """From the ticket history, return (orig_summary, orig_desc_text) that the old
    refiner overwrote — each None if not found / not overwritten."""
    data = jira_get(f"/rest/api/3/issue/{key}", params={"expand": "changelog", "fields": "summary"})
    if not data:
        return None, None
    histories = data.get("changelog", {}).get("histories", []) or []
    histories.sort(key=lambda h: h.get("created", ""))  # oldest first
    orig_summary = orig_desc = None
    for h in histories:
        for it in h.get("items", []):
            fld = it.get("field")
            frm = it.get("fromString")
            to = it.get("toString") or ""
            # First edit that turned the summary into a "⚠️ …" value → fromString is the original
            if fld == "summary" and orig_summary is None:
                if not (frm or "").startswith("⚠️") and to.startswith("⚠️"):
                    orig_summary = frm
            # First edit that turned the description into the refiner's format
            elif fld == "description" and orig_desc is None:
                if REFINER_DESC_MARKER in to:
                    orig_desc = frm  # original text (may be "")
    return orig_summary, orig_desc


def _text_to_adf(text):
    lines = (text or "").split("\n")
    content = [{"type": "paragraph", "content": [{"type": "text", "text": ln}]}
               for ln in lines if ln.strip()]
    if not content:
        content = [{"type": "paragraph"}]
    return {"version": 1, "type": "doc", "content": content}


def _desc_has_marker(desc):
    text = _extract_adf_text(desc) if isinstance(desc, dict) else (desc or "")
    return REFINER_DESC_MARKER in text


def cleanup_backlog():
    """One-time normalise of the Backlog section. Returns (changed, summaries_restored,
    descriptions_restored, total)."""
    log.info("Cleanup: fetching Backlog section...")
    issues = _fetch_backlog()
    total = len(issues)

    changed = summaries_restored = descriptions_restored = 0
    for issue in issues:
        f = issue["fields"]
        if (f.get("issuetype") or {}).get("name") == "Epic":
            continue
        key = issue["key"]
        summary = f.get("summary") or ""

        update = {}
        if (f.get("priority") or {}).get("name") != "Low":
            update["priority"] = {"name": "Low"}
        if f.get("assignee"):
            update["assignee"] = {"accountId": None}
        if f.get(STORY_POINTS_FIELD) is not None:
            update[STORY_POINTS_FIELD] = None

        need_summary = summary.startswith("⚠️")
        need_desc = _desc_has_marker(f.get("description"))
        if need_summary or need_desc:
            orig_summary, orig_desc = _changelog_originals(key)
            if need_summary and orig_summary:
                update["summary"] = orig_summary
                summaries_restored += 1
            if need_desc and orig_desc is not None:
                update["description"] = _text_to_adf(orig_desc)
                descriptions_restored += 1

        if not update:
            continue

        ok, resp = jira_put(f"/rest/api/3/issue/{key}", {"fields": update})
        if ok:
            changed += 1
            log.info(f"Cleanup: {key} — {', '.join(update.keys())}")
        else:
            log.error(f"Cleanup: failed {key}: {resp.status_code if resp else 'no response'}")

    log.info(f"Cleanup done: {changed}/{total} changed, "
             f"{summaries_restored} summaries + {descriptions_restored} descriptions restored.")
    return changed, summaries_restored, descriptions_restored, total
