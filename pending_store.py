"""
PM Agent — Pending Store
Persists parked pipeline items so they survive redeploys.

Discovery: parked.json in the prototypes GitHub repo (instant, no JQL issues)
Data: Jira comment on the issue (PM_AGENT_PARKED:<stage>:<json>)

On park:  write comment + add key to parked.json
On list:  read parked.json → fetch each issue's comments for stage/data
On resume: delete comment + remove key from parked.json
"""

import json
import base64
import os
import requests
from config import log
from jira_client import add_comment, get_issue_comments, delete_comment

PARK_MARKER = "PM_AGENT_PARKED"

# GitHub config (same repo as prototypes)
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = "james-axis/prototypes"
GITHUB_API = "https://api.github.com"
PARKED_FILE = "parked.json"

_gh_headers = {
    "Authorization": f"Bearer {GITHUB_TOKEN}" if GITHUB_TOKEN else "",
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
}


# ── GitHub parked.json helpers ───────────────────────────────────────────────

def _read_parked_json():
    """Read parked.json from GitHub. Returns (dict, sha) or ({}, None)."""
    if not GITHUB_TOKEN:
        return {}, None
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{PARKED_FILE}"
    try:
        r = requests.get(url, headers=_gh_headers, timeout=15)
        if r.status_code == 200:
            data = r.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return json.loads(content), data["sha"]
        if r.status_code == 404:
            return {}, None  # File doesn't exist yet
        log.error(f"Failed to read {PARKED_FILE}: {r.status_code}")
    except Exception as e:
        log.error(f"Failed to read {PARKED_FILE}: {e}")
    return {}, None


def _write_parked_json(parked_dict, sha=None):
    """Write parked.json to GitHub. Returns True on success."""
    if not GITHUB_TOKEN:
        return False
    url = f"{GITHUB_API}/repos/{GITHUB_REPO}/contents/{PARKED_FILE}"
    payload = {
        "message": "Update parked items",
        "content": base64.b64encode(json.dumps(parked_dict, indent=2).encode()).decode(),
    }
    if sha:
        payload["sha"] = sha
    try:
        r = requests.put(url, headers=_gh_headers, json=payload, timeout=15)
        if r.status_code in (200, 201):
            return True
        log.error(f"Failed to write {PARKED_FILE}: {r.status_code} {r.text[:300]}")
    except Exception as e:
        log.error(f"Failed to write {PARKED_FILE}: {e}")
    return False


# ── Public API ───────────────────────────────────────────────────────────────

def park_item(issue_key, stage, data=None):
    """
    Park an item: add Jira comment (data) + register in parked.json (discovery).
    """
    # 1. Write comment with data
    payload = json.dumps(data or {}, separators=(",", ":"))
    comment_text = f"{PARK_MARKER}:{stage}:{payload}"
    ok = add_comment(issue_key, comment_text)
    if not ok:
        return False

    # 2. Add to parked.json
    parked, sha = _read_parked_json()
    parked[issue_key] = stage
    _write_parked_json(parked, sha)

    log.info(f"Parked {issue_key} at {stage}")
    return True


def list_parked():
    """
    List all parked items by reading parked.json, then fetching stage/data
    from each issue's comments.
    Returns list of {issue_key, summary, stage, data, comment_id}.
    """
    parked, _ = _read_parked_json()
    if not parked:
        return []

    from jira_client import get_issue

    items = []
    stale_keys = []

    for issue_key, stage_hint in parked.items():
        # Fetch issue for summary
        issue = get_issue(issue_key)
        if not issue:
            stale_keys.append(issue_key)
            continue

        summary = issue.get("fields", {}).get("summary", issue_key)

        # Find the parked comment for data
        comments = get_issue_comments(issue_key)
        found = False
        for c in comments:
            if not c["text"].startswith(PARK_MARKER):
                continue
            try:
                _, stage, payload = c["text"].split(":", 2)
                data = json.loads(payload)
                items.append({
                    "issue_key": issue_key,
                    "summary": summary,
                    "stage": stage,
                    "data": data,
                    "comment_id": c["id"],
                })
                found = True
                break
            except (ValueError, json.JSONDecodeError) as e:
                log.error(f"Failed to parse parked comment on {issue_key}: {e}")

        if not found:
            # Comment was deleted but key still in parked.json — mark stale
            stale_keys.append(issue_key)

    # Clean up stale entries
    if stale_keys:
        parked_clean, sha = _read_parked_json()
        for k in stale_keys:
            parked_clean.pop(k, None)
        _write_parked_json(parked_clean, sha)

    return items


def unpark_item(issue_key):
    """
    Remove parked comment + entry from parked.json.
    Returns {stage, data} or None if not found.
    """
    # 1. Find and delete comment
    comments = get_issue_comments(issue_key)
    result = None
    for c in comments:
        if not c["text"].startswith(PARK_MARKER):
            continue
        try:
            _, stage, payload = c["text"].split(":", 2)
            data = json.loads(payload)
            delete_comment(issue_key, c["id"])
            result = {"stage": stage, "data": data}
            break
        except (ValueError, json.JSONDecodeError) as e:
            log.error(f"Failed to parse parked comment on {issue_key}: {e}")

    # 2. Remove from parked.json
    parked, sha = _read_parked_json()
    if issue_key in parked:
        del parked[issue_key]
        _write_parked_json(parked, sha)

    if result:
        log.info(f"Unparked {issue_key} from {result['stage']}")
    return result


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
        "pm5": lambda p: {
            "epic_key": p.get("epic_key", ""),
            "epic_title": p.get("epic_title", ""),
            "tasks": p.get("tasks", []),
            "total_sp": p.get("total_sp", 0),
            "prd_page_id": p.get("prd_page_id", ""),
            "prd_web_url": p.get("prd_web_url", ""),
            "prototype_url": p.get("prototype_url", ""),
        },
        "pm6": lambda p: {
            "epic_key": p.get("epic_key", ""),
            "epic_title": p.get("epic_title", ""),
            "tasks": p.get("tasks", []),
            "total_sp": p.get("total_sp", 0),
            "prd_page_id": p.get("prd_page_id", ""),
            "prd_web_url": p.get("prd_web_url", ""),
            "prototype_url": p.get("prototype_url", ""),
            "context_summary": p.get("context_summary", ""),
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

    if stage == "pm5":
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
            "epic_key": stored_data.get("epic_key", ""),
            "epic_title": stored_data.get("epic_title", summary),
            "tasks": stored_data.get("tasks", []),
            "total_sp": stored_data.get("total_sp", 0),
            "prd_page_id": prd_page_id,
            "prd_web_url": stored_data.get("prd_web_url", ""),
            "prd_content": prd_content,
            "prototype_url": stored_data.get("prototype_url", ""),
            "chat_id": chat_id,
        }

    if stage == "pm6":
        return {
            "issue_key": issue_key,
            "summary": summary,
            "epic_key": stored_data.get("epic_key", ""),
            "epic_title": stored_data.get("epic_title", summary),
            "tasks": stored_data.get("tasks", []),
            "total_sp": stored_data.get("total_sp", 0),
            "prd_page_id": stored_data.get("prd_page_id", ""),
            "prd_web_url": stored_data.get("prd_web_url", ""),
            "prd_content": "",  # Not needed for PM6 resume — plans already generated
            "prototype_url": stored_data.get("prototype_url", ""),
            "context_summary": stored_data.get("context_summary", ""),
            "chat_id": chat_id,
        }

    # Unknown stage — return minimal
    log.warning(f"Unknown stage '{stage}' for reconstruction")
    return {"issue_key": issue_key, "summary": summary, "chat_id": chat_id, **stored_data}
