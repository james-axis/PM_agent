"""
PM Agent — Pending Store
Persists parked pipeline items as Jira comments so they survive redeploys.

Comment format: PM_AGENT_PARKED:<stage>:<json_data>
Example: PM_AGENT_PARKED:pm2:{"page_id":"123","web_url":"https://..."}

Each stage stores only the minimal data that can't be derived from the issue itself.
On resume, the rest is reconstructed by fetching from Jira / Confluence / GitHub.
"""

import json
from config import log
from jira_client import add_comment, get_issue_comments, delete_comment, search_issues, add_label, remove_label

PARK_MARKER = "PM_AGENT_PARKED"
PARK_LABEL = "pm-parked"


def park_item(issue_key, stage, data=None):
    """
    Park an item by adding a label (for discovery) and a structured comment (for data).
    stage: "pm1", "pm2", "pm3", "pm4", etc.
    data: dict of stage-specific fields to persist.
    """
    payload = json.dumps(data or {}, separators=(",", ":"))
    comment_text = f"{PARK_MARKER}:{stage}:{payload}"
    ok_comment = add_comment(issue_key, comment_text)
    ok_label = add_label(issue_key, PARK_LABEL)
    if ok_comment and ok_label:
        log.info(f"Parked {issue_key} at {stage}")
    return ok_comment and ok_label


def list_parked():
    """
    Query Jira for all parked items using label (instant, no indexing delay).
    Returns list of {issue_key, summary, stage, data, comment_id}.
    """
    issues = search_issues(
        jql=f'project = AR AND labels = "{PARK_LABEL}"',
        fields="summary",
        max_results=50,
    )

    parked = []
    for issue in issues:
        issue_key = issue["key"]
        summary = issue["fields"]["summary"]

        comments = get_issue_comments(issue_key)
        for c in comments:
            if not c["text"].startswith(PARK_MARKER):
                continue
            try:
                # Parse: PM_AGENT_PARKED:pm2:{"page_id":"123"}
                _, stage, payload = c["text"].split(":", 2)
                data = json.loads(payload)
                parked.append({
                    "issue_key": issue_key,
                    "summary": summary,
                    "stage": stage,
                    "data": data,
                    "comment_id": c["id"],
                })
            except (ValueError, json.JSONDecodeError) as e:
                log.error(f"Failed to parse parked comment on {issue_key}: {e}")

    return parked


def unpark_item(issue_key):
    """
    Remove the parked comment and label from an issue.
    Returns {stage, data} or None if not found.
    """
    comments = get_issue_comments(issue_key)
    for c in comments:
        if not c["text"].startswith(PARK_MARKER):
            continue
        try:
            _, stage, payload = c["text"].split(":", 2)
            data = json.loads(payload)
            delete_comment(issue_key, c["id"])
            remove_label(issue_key, PARK_LABEL)
            log.info(f"Unparked {issue_key} from {stage}")
            return {"stage": stage, "data": data}
        except (ValueError, json.JSONDecodeError) as e:
            log.error(f"Failed to parse parked comment on {issue_key}: {e}")
    return None


# ── Stage-specific: what to store when parking ───────────────────────────────
# Each function extracts the minimal data from the pending dict that can't be
# recovered from the issue itself. This keeps Jira comments small and makes
# adding new stages trivial — just add a new store/reconstruct pair.

def store_data_for_stage(stage, pending):
    """Extract minimal data to persist for a given stage."""
    extractors = {
        "pm1": lambda p: {},
        "pm2": lambda p: {
            "page_id": p.get("page_id", ""),
            "web_url": p.get("web_url", ""),
            "page_title": p.get("page_title", ""),
        },
        "pm3": lambda p: {
            "prototype_url": p.get("prototype_url", ""),
            "prd_page_id": p.get("prd_page_id", ""),
            "prd_web_url": p.get("prd_web_url", ""),
        },
        "pm4": lambda p: {
            "epic_title": p.get("epic_title", ""),
            "epic_summary": p.get("epic_summary", ""),
            "prd_page_id": p.get("prd_page_id", ""),
            "prd_web_url": p.get("prd_web_url", ""),
            "prototype_url": p.get("prototype_url", ""),
        },
    }
    extractor = extractors.get(stage, lambda p: {})
    return extractor(pending)


def reconstruct_pending(stage, issue_key, summary, stored_data, chat_id):
    """
    Rebuild the full pending dict for a stage from stored data + live sources.
    Heavy fetches (Confluence PRD, GitHub HTML) are done here so the
    approve/changes/reject flows work immediately after resume.
    """
    if stage == "pm1":
        return {
            "issue_key": issue_key,
            "structured": {"summary": summary, "description": ""},
            "raw_idea": "",
            "kb_context_text": "",
            "chat_id": chat_id,
        }

    if stage == "pm2":
        prd_text = ""
        page_id = stored_data.get("page_id", "")
        if page_id:
            try:
                from confluence_client import fetch_page_content
                page = fetch_page_content(page_id)
                if page:
                    prd_text = page.get("text", "")
            except Exception as e:
                log.error(f"Failed to fetch PRD for resume: {e}")
        return {
            "issue_key": issue_key,
            "summary": summary,
            "page_id": page_id,
            "page_title": stored_data.get("page_title", ""),
            "web_url": stored_data.get("web_url", ""),
            "prd_markdown": prd_text,
            "kb_context_text": "",
            "inspiration": "",
            "chat_id": chat_id,
        }

    if stage == "pm3":
        prd_content = ""
        prd_page_id = stored_data.get("prd_page_id", "")
        if prd_page_id:
            try:
                from confluence_client import fetch_page_content
                page = fetch_page_content(prd_page_id)
                if page:
                    prd_content = page.get("text", "")
            except Exception as e:
                log.error(f"Failed to fetch PRD for resume: {e}")

        html_content = ""
        prototype_url = stored_data.get("prototype_url", "")
        if prototype_url:
            try:
                from github_client import fetch_prototype_html
                html_content = fetch_prototype_html(issue_key) or ""
            except Exception as e:
                log.error(f"Failed to fetch prototype HTML for resume: {e}")

        return {
            "issue_key": issue_key,
            "summary": summary,
            "prototype_url": prototype_url,
            "html_content": html_content,
            "prd_content": prd_content,
            "prd_page_id": prd_page_id,
            "prd_web_url": stored_data.get("prd_web_url", ""),
            "design_system_text": "",  # Re-fetched if changes requested
            "db_schema_text": "",       # Re-fetched if changes requested
            "chat_id": chat_id,
        }

    if stage == "pm4":
        prd_content = ""
        prd_page_id = stored_data.get("prd_page_id", "")
        if prd_page_id:
            try:
                from confluence_client import fetch_page_content
                page = fetch_page_content(prd_page_id)
                if page:
                    prd_content = page.get("text", "")
            except Exception as e:
                log.error(f"Failed to fetch PRD for resume: {e}")
        return {
            "issue_key": issue_key,
            "summary": summary,
            "epic_title": stored_data.get("epic_title", summary),
            "epic_summary": stored_data.get("epic_summary", ""),
            "prd_page_id": prd_page_id,
            "prd_web_url": stored_data.get("prd_web_url", ""),
            "prd_content": prd_content,
            "prototype_url": stored_data.get("prototype_url", ""),
            "chat_id": chat_id,
        }

    # Unknown stage — return minimal
    log.warning(f"Unknown stage '{stage}' for reconstruction")
    return {"issue_key": issue_key, "summary": summary, "chat_id": chat_id, **stored_data}
