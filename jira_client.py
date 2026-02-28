"""
PM Agent — Jira Client
Thin wrapper around Jira Cloud REST API v3.
"""

import requests
from requests.auth import HTTPBasicAuth
from config import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, AR_PROJECT_KEY,
    JAMES_ACCOUNT_ID, SWIMLANE_FIELD, ROADMAP_FIELD, INITIATIVE_FIELD,
    DISCOVERY_FIELD, PRODUCT_CAT_FIELD, LABELS_FIELD, ROADMAP_BACKLOG_ID,
    STRATEGIC_INITIATIVES_ID, USER_FEEDBACK_OPTION_ID, INITIATIVE_OPTIONS,
    DISCOVERY_OPTIONS, PRODUCT_CATEGORY_OPTIONS, log,
)

auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
headers = {"Accept": "application/json", "Content-Type": "application/json"}


def jira_get(path, params=None):
    """GET request to Jira REST API."""
    r = requests.get(f"{JIRA_BASE_URL}{path}", auth=auth, headers=headers, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def jira_post(path, payload):
    """POST request to Jira REST API. Returns (success, response)."""
    r = requests.post(f"{JIRA_BASE_URL}{path}", auth=auth, headers=headers, json=payload, timeout=30)
    return r.status_code in (200, 201, 204), r


def jira_put(path, payload):
    """PUT request to Jira REST API. Returns (success, response)."""
    r = requests.put(f"{JIRA_BASE_URL}{path}", auth=auth, headers=headers, json=payload, timeout=30)
    return r.status_code in (200, 204), r


def markdown_to_adf(md_text):
    """Convert simple markdown text to ADF content nodes."""
    if not md_text:
        return [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}]

    nodes = []
    for line in md_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("**") and stripped.endswith("**"):
            # Bold heading-style line
            nodes.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": stripped.strip("*"), "marks": [{"type": "strong"}]}]
            })
        elif stripped.startswith("- ") or stripped.startswith("* "):
            # Bullet item — collect consecutive bullets
            if nodes and nodes[-1].get("type") == "bulletList":
                nodes[-1]["content"].append({
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": [{"type": "text", "text": stripped[2:]}]}]
                })
            else:
                nodes.append({
                    "type": "bulletList",
                    "content": [{
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": stripped[2:]}]}]
                    }]
                })
        else:
            nodes.append({
                "type": "paragraph",
                "content": [{"type": "text", "text": stripped}]
            })

    return nodes or [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}]


def create_idea(structured_data, swimlane_id=None):
    """
    Create a JPD idea in the AR project from structured data.
    Returns issue key (e.g. 'AR-123') or None on failure.
    """
    if swimlane_id is None:
        swimlane_id = STRATEGIC_INITIATIVES_ID

    summary = structured_data.get("summary", "Untitled idea")
    description_md = structured_data.get("description", "")

    fields = {
        "project": {"key": AR_PROJECT_KEY},
        "issuetype": {"name": "Idea"},
        "summary": summary,
        "description": {"version": 1, "type": "doc", "content": markdown_to_adf(description_md)},
        "assignee": {"accountId": JAMES_ACCOUNT_ID},
        SWIMLANE_FIELD: {"id": swimlane_id},
        ROADMAP_FIELD: {"id": ROADMAP_BACKLOG_ID},
    }

    # Initiative tagging
    if swimlane_id == USER_FEEDBACK_OPTION_ID:
        voa_id = INITIATIVE_OPTIONS.get("voa")
        if voa_id:
            fields[INITIATIVE_FIELD] = [{"id": voa_id}]
    else:
        init_ids = []
        for key in ("initiative_module", "initiative_stage", "initiative_scope"):
            name = structured_data.get(key, "")
            if name:
                option_id = INITIATIVE_OPTIONS.get(name.lower())
                if option_id:
                    init_ids.append({"id": option_id})
        if init_ids:
            fields[INITIATIVE_FIELD] = init_ids

    # Labels
    label = structured_data.get("labels", "Features")
    if isinstance(label, list):
        label = label[0] if label else "Features"
    if label not in ("Modules", "Features"):
        label = "Features"
    fields[LABELS_FIELD] = [label]

    # Product category
    prod_cat = structured_data.get("product_category")
    if prod_cat and prod_cat.lower() in PRODUCT_CATEGORY_OPTIONS:
        fields[PRODUCT_CAT_FIELD] = [{"id": PRODUCT_CATEGORY_OPTIONS[prod_cat.lower()]}]

    # Discovery status
    discovery = structured_data.get("discovery", "Validate")
    if discovery and discovery.lower() in DISCOVERY_OPTIONS:
        fields[DISCOVERY_FIELD] = {"id": DISCOVERY_OPTIONS[discovery.lower()]}

    ok, resp = jira_post("/rest/api/3/issue", {"fields": fields})
    if ok:
        issue_key = resp.json().get("key", "?")
        log.info(f"Created JPD idea {issue_key}: {summary}")
        return issue_key
    else:
        log.error(f"Failed to create idea: {resp.status_code} {resp.text[:300]}")
        return None


def add_comment(issue_key, comment_md):
    """Add a comment to an issue using markdown-style text."""
    payload = {
        "body": {
            "version": 1,
            "type": "doc",
            "content": markdown_to_adf(comment_md),
        }
    }
    ok, resp = jira_post(f"/rest/api/3/issue/{issue_key}/comment", payload)
    if ok:
        log.info(f"Added comment to {issue_key}")
    else:
        log.error(f"Failed to add comment to {issue_key}: {resp.status_code}")
    return ok


def get_issue(issue_key):
    """Fetch an issue by key."""
    try:
        return jira_get(f"/rest/api/3/issue/{issue_key}")
    except Exception as e:
        log.error(f"Failed to fetch {issue_key}: {e}")
        return None


def update_idea(issue_key, structured_data):
    """
    Update an existing JPD idea with re-enriched data.
    Returns True on success, False on failure.
    """
    summary = structured_data.get("summary", "Untitled idea")
    description_md = structured_data.get("description", "")

    fields = {
        "summary": summary,
        "description": {"version": 1, "type": "doc", "content": markdown_to_adf(description_md)},
    }

    # Update initiative tags
    init_ids = []
    for key in ("initiative_module", "initiative_stage", "initiative_scope"):
        name = structured_data.get(key, "")
        if name:
            option_id = INITIATIVE_OPTIONS.get(name.lower())
            if option_id:
                init_ids.append({"id": option_id})
    if init_ids:
        fields[INITIATIVE_FIELD] = init_ids

    # Labels
    label = structured_data.get("labels", "Features")
    if isinstance(label, list):
        label = label[0] if label else "Features"
    if label not in ("Modules", "Features"):
        label = "Features"
    fields[LABELS_FIELD] = [label]

    # Product category
    prod_cat = structured_data.get("product_category")
    if prod_cat and prod_cat.lower() in PRODUCT_CATEGORY_OPTIONS:
        fields[PRODUCT_CAT_FIELD] = [{"id": PRODUCT_CATEGORY_OPTIONS[prod_cat.lower()]}]

    ok, resp = jira_put(f"/rest/api/3/issue/{issue_key}", {"fields": fields})
    if ok:
        log.info(f"Updated idea {issue_key}: {summary}")
    else:
        log.error(f"Failed to update {issue_key}: {resp.status_code} {resp.text[:300]}")
    return ok
