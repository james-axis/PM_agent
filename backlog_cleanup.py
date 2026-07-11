"""
PM Agent — one-time Backlog cleanup

Brings every ticket in the board Backlog section into the triage state the new
refiner enforces, WITHOUT losing the requestor's original wording:
  - priority → Low, unassigned, story points cleared (all tickets)
  - if the old refiner rewrote the summary (starts with the ⚠️ warning sign),
    restore the ORIGINAL summary and description from the ticket history
    (the value before the first recorded edit of each field)

Run once via the /cleanupbacklog Telegram command. Idempotent: once summaries
are restored (no longer start with ⚠️) and fields normalised, re-running is a no-op.
"""

from config import STORY_POINTS_FIELD, log
from jira_client import jira_get, jira_put, _extract_adf_text

WARNING_SIGN = "⚠"  # ⚠ — match ignoring the optional U+FE0F variation selector


def _is_mangled_summary(text):
    return (text or "").lstrip().startswith(WARNING_SIGN)


def _fetch_backlog():
    """The board Backlog section (issues not in any sprint), paginated."""
    issues, start = [], 0
    while True:
        data = jira_get("/rest/agile/1.0/board/1/backlog", params={
            "fields": f"summary,description,priority,assignee,issuetype,{STORY_POINTS_FIELD}",
            "startAt": start, "maxResults": 50,
        })
        if not data:
            break
        batch = data.get("issues", []) or []
        issues.extend(batch)
        if data.get("isLast") or not batch or len(issues) >= (data.get("total") or 0):
            break
        start += len(batch)
    return [i for i in issues if not i["fields"].get("sprint")]


def _originals_from_changelog(key):
    """Return (orig_summary, orig_desc): the value each field held BEFORE its first
    recorded edit (i.e. the original the old refiner later overwrote). None if the
    field was never edited."""
    histories, start = [], 0
    while True:
        data = jira_get(f"/rest/api/3/issue/{key}/changelog",
                        params={"startAt": start, "maxResults": 100})
        if not data:
            break
        vals = data.get("values", []) or []
        histories.extend(vals)
        if data.get("isLast") or not vals or len(histories) >= (data.get("total") or 0):
            break
        start += len(vals)

    histories.sort(key=lambda h: h.get("created", ""))  # oldest first
    orig_summary = orig_desc = None
    for h in histories:
        for it in h.get("items", []):
            fld = it.get("field")
            if fld == "summary" and orig_summary is None:
                orig_summary = it.get("fromString")
            elif fld == "description" and orig_desc is None:
                orig_desc = it.get("fromString")
        if orig_summary is not None and orig_desc is not None:
            break
    return orig_summary, orig_desc


def _text_to_adf(text):
    lines = (text or "").split("\n")
    content = [{"type": "paragraph", "content": [{"type": "text", "text": ln}]}
               for ln in lines if ln.strip()]
    if not content:
        content = [{"type": "paragraph"}]
    return {"version": 1, "type": "doc", "content": content}


def cleanup_backlog():
    """One-time normalise of the Backlog section. Returns dict of counts."""
    log.info("Cleanup: fetching Backlog section...")
    issues = _fetch_backlog()
    total = len(issues)
    changed = summaries_restored = descriptions_restored = unresolved = 0

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

        # Restore original summary + description on tickets the old refiner mangled.
        if _is_mangled_summary(summary):
            orig_summary, orig_desc = _originals_from_changelog(key)
            restored_any = False
            if orig_summary and not _is_mangled_summary(orig_summary):
                update["summary"] = orig_summary
                summaries_restored += 1
                restored_any = True
            cur_desc = _extract_adf_text(f.get("description")) if isinstance(f.get("description"), dict) else (f.get("description") or "")
            if orig_desc and orig_desc.strip() and orig_desc.strip() != cur_desc.strip():
                update["description"] = _text_to_adf(orig_desc)
                descriptions_restored += 1
                restored_any = True
            if not restored_any:
                unresolved += 1
                log.warning(f"Cleanup: {key} still ⚠️ — no original found in history")

        if not update:
            continue

        ok, resp = jira_put(f"/rest/api/3/issue/{key}", {"fields": update})
        if ok:
            changed += 1
            log.info(f"Cleanup: {key} — {', '.join(update.keys())}")
        else:
            log.error(f"Cleanup: failed {key}: {resp.status_code if resp else 'no response'}")

    result = {"total": total, "changed": changed,
              "summaries_restored": summaries_restored,
              "descriptions_restored": descriptions_restored,
              "unresolved": unresolved}
    log.info(f"Cleanup done: {result}")
    return result
