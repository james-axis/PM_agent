"""
PM Agent — Jira Client
Thin wrapper around Jira Cloud REST API v3.
"""

import random
import re
import requests
from datetime import datetime, timedelta
from requests.auth import HTTPBasicAuth
from config import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, AR_PROJECT_KEY, AX_PROJECT_KEY,
    JAMES_ACCOUNT_ID, SWIMLANE_FIELD, ROADMAP_FIELD, INITIATIVE_FIELD, PHASE_FIELD,
    ROADMAP_BACKLOG_ID, STORY_POINTS_FIELD, IMPROVES_FIELD, AX_BOARD_ID,
    EXPERIENCE_SWIMLANE_ID, SWIMLANE_OPTIONS, INITIATIVE_OPTIONS,
    PHASE_MVP_ID, PHASE_ITERATION_ID,
    log,
)

auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
headers = {"Accept": "application/json", "Content-Type": "application/json"}

# Epic color field and palette (matches Jira's color picker)
ISSUE_COLOR_FIELD = "customfield_10017"
EPIC_COLORS = [
    "purple", "dark_blue", "teal", "green", "yellow",
    "blue", "dark_teal", "dark_green", "orange", "blue_gray",
    "dark_purple", "dark_orange", "red", "dark_gray",
]


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


def assign_issue(issue_key, account_id):
    """Assign an issue to a user by account ID."""
    ok, resp = jira_put(f"/rest/api/3/issue/{issue_key}", {
        "fields": {"assignee": {"accountId": account_id}}
    })
    if ok:
        log.info(f"Assigned {issue_key} to {account_id}")
    else:
        log.error(f"Failed to assign {issue_key}: {resp.status_code} {resp.text[:200]}")
    return ok


def transition_issue(issue_key, transition_id):
    """Transition an issue to a new status."""
    ok, resp = jira_post(f"/rest/api/3/issue/{issue_key}/transitions", {
        "transition": {"id": transition_id}
    })
    if ok:
        log.info(f"Transitioned {issue_key} via transition {transition_id}")
    else:
        log.error(f"Failed to transition {issue_key}: {resp.status_code} {resp.text[:200]}")
    return ok


def _parse_inline_markdown(text):
    """Parse inline markdown (bold, italic, links) into ADF text nodes with marks."""
    import re as _re
    if not text:
        return [{"type": "text", "text": " "}]

    result = []
    # Tokenise: find **bold**, *italic*, and [text](url) patterns
    # Pattern matches: [text](url) | **text** | *text*
    pattern = _re.compile(
        r'\[([^\]]+)\]\(([^)]+)\)'   # [text](url)
        r'|\*\*(.+?)\*\*'            # **bold**
        r'|\*(.+?)\*'                 # *italic* (render as bold for Jira)
    )

    pos = 0
    for m in pattern.finditer(text):
        # Add any plain text before this match
        if m.start() > pos:
            result.append({"type": "text", "text": text[pos:m.start()]})

        if m.group(1) is not None:
            # Link: [text](url) — check if link text itself is bold **text**
            link_text = m.group(1)
            link_url = m.group(2)
            marks = [{"type": "link", "attrs": {"href": link_url}}]
            bold_match = _re.match(r'^\*\*(.+)\*\*$', link_text)
            if bold_match:
                link_text = bold_match.group(1)
                marks.append({"type": "strong"})
            result.append({"type": "text", "text": link_text, "marks": marks})
        elif m.group(3) is not None:
            # Bold: **text**
            result.append({"type": "text", "text": m.group(3), "marks": [{"type": "strong"}]})
        elif m.group(4) is not None:
            # Italic as bold: *text*
            result.append({"type": "text", "text": m.group(4), "marks": [{"type": "strong"}]})

        pos = m.end()

    # Add trailing plain text
    if pos < len(text):
        result.append({"type": "text", "text": text[pos:]})

    return result if result else [{"type": "text", "text": text}]


def markdown_to_adf(md_text):
    """Convert markdown text to ADF content nodes with proper inline formatting."""
    if not md_text:
        return [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}]

    nodes = []
    for line in md_text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue

        # Headings: ### text, ## text, # text
        if stripped.startswith("### "):
            nodes.append({
                "type": "heading", "attrs": {"level": 3},
                "content": _parse_inline_markdown(stripped[4:])
            })
        elif stripped.startswith("## "):
            nodes.append({
                "type": "heading", "attrs": {"level": 2},
                "content": _parse_inline_markdown(stripped[3:])
            })
        elif stripped.startswith("# "):
            nodes.append({
                "type": "heading", "attrs": {"level": 1},
                "content": _parse_inline_markdown(stripped[2:])
            })
        # Bullet items: - text or * text (but not **bold**)
        elif stripped.startswith("- ") or (stripped.startswith("* ") and not stripped.startswith("**")):
            item_text = stripped[2:]
            item_content = _parse_inline_markdown(item_text)
            if nodes and nodes[-1].get("type") == "bulletList":
                nodes[-1]["content"].append({
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": item_content}]
                })
            else:
                nodes.append({
                    "type": "bulletList",
                    "content": [{
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": item_content}]
                    }]
                })
        # Numbered list: 1. text, 2. text
        elif len(stripped) > 2 and stripped[0].isdigit() and '. ' in stripped[:5]:
            dot_pos = stripped.index('. ')
            item_text = stripped[dot_pos+2:]
            item_content = _parse_inline_markdown(item_text)
            if nodes and nodes[-1].get("type") == "orderedList":
                nodes[-1]["content"].append({
                    "type": "listItem",
                    "content": [{"type": "paragraph", "content": item_content}]
                })
            else:
                nodes.append({
                    "type": "orderedList",
                    "content": [{
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": item_content}]
                    }]
                })
        else:
            # Regular paragraph with inline formatting
            nodes.append({
                "type": "paragraph",
                "content": _parse_inline_markdown(stripped)
            })

    return nodes or [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}]


def create_idea(structured_data):
    """
    Create a JPD idea in the AR project from structured data.
    Sets Swimlane, Phase, and Initiative based on Claude's analysis.
    Returns issue key (e.g. 'AR-123') or None on failure.
    """
    summary = structured_data.get("summary", "Untitled idea")
    description_md = structured_data.get("description", "")

    # Resolve swimlane
    swimlane_name = structured_data.get("swimlane", "experience").lower()
    swimlane_id = SWIMLANE_OPTIONS.get(swimlane_name, EXPERIENCE_SWIMLANE_ID)

    # Resolve phase
    phase_name = structured_data.get("phase", "").lower()
    phase_id = PHASE_MVP_ID if phase_name == "mvp" else PHASE_ITERATION_ID if phase_name == "iteration" else None

    fields = {
        "project": {"key": AR_PROJECT_KEY},
        "issuetype": {"name": "Idea"},
        "summary": summary,
        "description": {"version": 1, "type": "doc", "content": markdown_to_adf(description_md)},
        "assignee": {"accountId": JAMES_ACCOUNT_ID},
        SWIMLANE_FIELD: {"id": swimlane_id},
        ROADMAP_FIELD: {"id": ROADMAP_BACKLOG_ID},
    }

    # Phase (separate select field)
    if phase_id:
        fields[PHASE_FIELD] = {"id": phase_id}

    # Initiative tagging (module only)
    init_name = structured_data.get("initiative", "")
    if init_name:
        option_id = INITIATIVE_OPTIONS.get(init_name.lower())
        if option_id:
            fields[INITIATIVE_FIELD] = [{"id": option_id}]

    # Improves field (auto-discovered options)
    improves_label = structured_data.get("improves", "")
    if improves_label:
        improves_id = resolve_improves_id(improves_label)
        if improves_id:
            fields[IMPROVES_FIELD] = {"id": improves_id}

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


def _extract_adf_text(node):
    """Recursively extract plain text from an ADF node."""
    if not node or not isinstance(node, dict):
        return ""
    if node.get("type") == "text":
        return node.get("text", "")
    return "".join(_extract_adf_text(c) for c in node.get("content", []))


def _find_confluence_urls_in_adf(node):
    """Recursively find Confluence wiki URLs in ADF nodes (inlineCard, links, smartlinks)."""
    import re
    urls = []
    if not node or not isinstance(node, dict):
        return urls
    # inlineCard (how PRD links are stored)
    if node.get("type") == "inlineCard":
        url = node.get("attrs", {}).get("url", "")
        if "atlassian.net/wiki" in url:
            urls.append(url)
    # Link marks on text
    for mark in node.get("marks", []):
        if mark.get("type") == "link":
            url = mark.get("attrs", {}).get("href", "")
            if "atlassian.net/wiki" in url:
                urls.append(url)
    # Recurse into children
    for child in node.get("content", []):
        urls.extend(_find_confluence_urls_in_adf(child))
    return urls


def discover_prd_from_issue(issue_key):
    """Auto-discover PRD URL and page ID from an issue's description, comments, or linked issues.
    Checks:
    1. Description ADF for inlineCard/link nodes pointing to Confluence wiki
    2. Comments for 'PRD: https://...' patterns
    3. Linked AR issues (for AX epics that link back to ideas)
    Returns (prd_web_url, prd_page_id) or ('', '')."""
    import re

    prd_url = ""
    page_id = ""

    # 1. Check description
    try:
        issue = jira_get(f"/rest/api/3/issue/{issue_key}", params={"fields": "description,issuelinks"})
        if issue and "fields" in issue:
            desc = issue["fields"].get("description")
            if desc and isinstance(desc, dict):
                urls = _find_confluence_urls_in_adf(desc)
                for url in urls:
                    if "/wiki/" in url:
                        prd_url = url
                        break

            # 3. Check linked AR issues (for AX epics)
            if not prd_url:
                for link in issue["fields"].get("issuelinks") or []:
                    for direction in ("inwardIssue", "outwardIssue"):
                        linked = link.get(direction)
                        if linked and linked.get("key", "").startswith("AR-"):
                            ar_key = linked["key"]
                            ar_url, ar_page = discover_prd_from_issue(ar_key)
                            if ar_url:
                                return ar_url, ar_page
    except Exception as e:
        log.warning(f"discover_prd_from_issue: failed reading {issue_key}: {e}")

    # 2. If not found in description, check comments
    if not prd_url:
        try:
            comments = get_issue_comments(issue_key, max_results=50)
            for c in comments:
                text = c.get("text", "")
                m = re.search(r'PRD:\s*(https://\S+)', text)
                if m:
                    prd_url = m.group(1)
                    break
                m = re.search(r'(https://\S+atlassian\.net/wiki/\S+)', text)
                if m:
                    prd_url = m.group(1)
                    break
        except Exception as e:
            log.warning(f"discover_prd_from_issue: failed reading comments for {issue_key}: {e}")

    # Extract page_id from URL
    if prd_url:
        m = re.search(r'/pages/(\d+)', prd_url)
        if m:
            page_id = m.group(1)
        log.info(f"Discovered PRD for {issue_key}: url={prd_url[:80]}... page_id={page_id}")
    else:
        log.info(f"No PRD found for {issue_key}")

    return prd_url, page_id


def get_issue_comments(issue_key, max_results=100):
    """Fetch comments for an issue. Returns list of {id, text}."""
    try:
        data = jira_get(f"/rest/api/3/issue/{issue_key}/comment", params={"maxResults": max_results})
        return [
            {"id": c["id"], "text": _extract_adf_text(c.get("body", {}))}
            for c in data.get("comments", [])
        ]
    except Exception as e:
        log.error(f"Failed to get comments for {issue_key}: {e}")
        return []


def delete_comment(issue_key, comment_id):
    """Delete a comment from an issue."""
    try:
        r = requests.delete(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}/comment/{comment_id}",
            auth=auth, headers=headers, timeout=30,
        )
        if r.status_code == 204:
            log.info(f"Deleted comment {comment_id} on {issue_key}")
            return True
        log.error(f"Failed to delete comment {comment_id} on {issue_key}: {r.status_code}")
        return False
    except Exception as e:
        log.error(f"Failed to delete comment {comment_id} on {issue_key}: {e}")
        return False


def search_issues(jql, fields="summary", max_results=50):
    """Run a JQL search. Returns list of issue dicts."""
    try:
        data = jira_get("/rest/api/3/search", params={
            "jql": jql,
            "fields": fields,
            "maxResults": max_results,
        })
        return data.get("issues", [])
    except Exception as e:
        log.error(f"JQL search failed: {e}")
        return []


def link_delivery_issue(idea_key, epic_key):
    """Create a 'Polaris work item link' between an AR idea and AX Epic.
    This makes the Epic appear in the idea's Delivery tab in JPD.
    AR idea 'is implemented by' AX Epic."""
    payload = {
        "type": {"name": "Polaris work item link"},
        "inwardIssue": {"key": idea_key},
        "outwardIssue": {"key": epic_key},
    }
    ok, resp = jira_post("/rest/api/3/issueLink", payload)
    if ok:
        log.info(f"Linked delivery: {idea_key} ← {epic_key}")
        return True
    else:
        log.error(f"Failed to link {idea_key} ← {epic_key}: {resp.status_code} {resp.text[:300]}")
        return False


def get_roadmap_options():
    """Fetch available Roadmap (Sprint) field options from AR project metadata.
    Returns list of {'id': str, 'value': str} dicts, sprint-only (excludes Shipped/Won't do/Timeline)."""
    try:
        data = jira_get(
            "/rest/api/3/issue/createmeta/AR/issuetypes/10040",
            params={"expand": "projects.issuetypes.fields"}
        )
        # Walk the fields to find customfield_10560
        for field in data.get("fields", []) if isinstance(data, dict) else []:
            if field.get("fieldId") == ROADMAP_FIELD:
                options = field.get("allowedValues", [])
                exclude = {"shipped", "won't do", "timeline"}
                return [
                    {"id": o["id"], "value": o["value"]}
                    for o in options
                    if o.get("value", "").lower() not in exclude
                ]
    except Exception as e:
        log.error(f"Failed to fetch roadmap options: {e}")

    # Fallback: hardcoded known options
    return [
        {"id": "10536", "value": "Backlog"},
        {"id": "10233", "value": "March (S1)"},
        {"id": "10269", "value": "March (S2)"},
        {"id": "10529", "value": "April (S1)"},
        {"id": "10530", "value": "April (S2)"},
        {"id": "10531", "value": "May (S1)"},
        {"id": "10538", "value": "May (S2)"},
        {"id": "10539", "value": "June (S1)"},
        {"id": "10540", "value": "June (S2)"},
        {"id": "10537", "value": "July (S1)"},
        {"id": "10541", "value": "July (S2)"},
    ]


def set_roadmap(issue_key, option_id):
    """Set the Roadmap field on an AR idea."""
    return jira_put(f"/rest/api/3/issue/{issue_key}", {
        "fields": {ROADMAP_FIELD: {"id": option_id}}
    })


# ── Improves Field (auto-discovered) ────────────────────────────────────────

_improves_cache = None  # [{id, value}, ...]


def get_improves_options():
    """Fetch Improves field options from AR project metadata.
    Returns list of {'id': str, 'value': str} e.g. [{'id': '10719', 'value': '⬆️ Adoption'}, ...].
    Caches after first successful fetch."""
    global _improves_cache
    if _improves_cache is not None:
        return _improves_cache

    try:
        data = jira_get(
            "/rest/api/3/issue/createmeta/AR/issuetypes/10040",
            params={"expand": "projects.issuetypes.fields"},
        )
        for field in data.get("fields", []) if isinstance(data, dict) else []:
            if field.get("fieldId") == IMPROVES_FIELD:
                options = [
                    {"id": o["id"], "value": o["value"]}
                    for o in field.get("allowedValues", [])
                ]
                if options:
                    _improves_cache = options
                    log.info(f"Auto-discovered {len(options)} Improves options: {[o['value'] for o in options]}")
                    return options
    except Exception as e:
        log.warning(f"Failed to auto-discover Improves options: {e}")

    return []


def get_improves_labels():
    """Return plain labels (without emoji) for use in AI prompts.
    e.g. ['Adoption', 'Satisfaction', 'Productivity', 'Retention']"""
    import re
    options = get_improves_options()
    return [re.sub(r'^[^\w]+', '', o["value"]).strip() for o in options]


def resolve_improves_id(label):
    """Match an AI-returned label like 'Adoption' to the full option ID.
    Case-insensitive, strips emoji for matching."""
    import re
    if not label:
        return None
    label_clean = re.sub(r'^[^\w]+', '', label).strip().lower()
    for o in get_improves_options():
        option_clean = re.sub(r'^[^\w]+', '', o["value"]).strip().lower()
        if option_clean == label_clean:
            return o["id"]
    log.warning(f"Improves label '{label}' not matched to any option")
    return None


def get_epic_tasks(epic_key):
    """Fetch all tasks under an Epic. Returns list of {key, summary, story_points, status}."""
    issues = search_issues(
        jql=f'project = AX AND parent = {epic_key} ORDER BY created ASC',
        fields=f"summary,status,{STORY_POINTS_FIELD}",
    )
    tasks = []
    for issue in issues:
        fields = issue.get("fields", {})
        tasks.append({
            "key": issue["key"],
            "summary": fields.get("summary", ""),
            "story_points": fields.get(STORY_POINTS_FIELD, 0) or 0,
            "status": fields.get("status", {}).get("name", ""),
        })
    return tasks


def add_label(issue_key, label):
    """Add a label to an issue."""
    ok, resp = jira_put(f"/rest/api/3/issue/{issue_key}", {
        "update": {"labels": [{"add": label}]}
    })
    if ok:
        log.info(f"Added label '{label}' to {issue_key}")
    else:
        log.error(f"Failed to add label to {issue_key}: {resp.status_code} {resp.text[:300]}")
    return ok


def remove_label(issue_key, label):
    """Remove a label from an issue."""
    ok, resp = jira_put(f"/rest/api/3/issue/{issue_key}", {
        "update": {"labels": [{"remove": label}]}
    })
    if ok:
        log.info(f"Removed label '{label}' from {issue_key}")
    else:
        log.error(f"Failed to remove label from {issue_key}: {resp.status_code} {resp.text[:300]}")
    return ok


def get_issue(issue_key):
    """Fetch an issue by key."""
    try:
        return jira_get(f"/rest/api/3/issue/{issue_key}")
    except Exception as e:
        log.error(f"Failed to fetch {issue_key}: {e}")
        return None


def archive_issue(issue_key):
    """Archive an issue using Jira's native archive API. Returns True on success."""
    try:
        r = requests.put(
            f"{JIRA_BASE_URL}/rest/api/3/issue/archive",
            auth=auth, headers=headers, timeout=30,
            json={"issueIdsOrKeys": [issue_key]},
        )
        if r.status_code == 200:
            log.info(f"Archived issue {issue_key}")
            return True
        log.error(f"Failed to archive {issue_key}: {r.status_code} {r.text[:300]}")
        return False
    except Exception as e:
        log.error(f"Failed to archive {issue_key}: {e}")
        return False


def append_prd_link_to_description(issue_key, prd_title, prd_url):
    """Append a 'Product Requirements Document' section with link to an idea's description."""
    issue = get_issue(issue_key)
    if not issue:
        log.error(f"Cannot append PRD link — failed to fetch {issue_key}")
        return False

    desc = issue.get("fields", {}).get("description")
    if not desc or not isinstance(desc, dict):
        desc = {"version": 1, "type": "doc", "content": []}

    # Build the PRD section ADF nodes
    prd_nodes = [
        {
            "type": "paragraph",
            "content": [
                {"type": "text", "text": "Product Requirements Document", "marks": [{"type": "strong"}]}
            ]
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "inlineCard",
                    "attrs": {"url": prd_url}
                }
            ]
        },
    ]

    desc["content"].extend(prd_nodes)

    ok, resp = jira_put(f"/rest/api/3/issue/{issue_key}", {"fields": {"description": desc}})
    if ok:
        log.info(f"Appended PRD link to {issue_key} description")
        return True
    log.error(f"Failed to append PRD link to {issue_key}: {resp.status_code} {resp.text[:300]}")
    return False





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

    # Update swimlane
    swimlane_name = structured_data.get("swimlane", "").lower()
    swimlane_id = SWIMLANE_OPTIONS.get(swimlane_name)
    if swimlane_id:
        fields[SWIMLANE_FIELD] = {"id": swimlane_id}

    # Update phase
    phase_name = structured_data.get("phase", "").lower()
    phase_id = PHASE_MVP_ID if phase_name == "mvp" else PHASE_ITERATION_ID if phase_name == "iteration" else None
    if phase_id:
        fields[PHASE_FIELD] = {"id": phase_id}

    # Update initiative (module only)
    init_name = structured_data.get("initiative", "")
    if init_name:
        option_id = INITIATIVE_OPTIONS.get(init_name.lower())
        if option_id:
            fields[INITIATIVE_FIELD] = [{"id": option_id}]

    # Update improves (auto-discovered)
    improves_label = structured_data.get("improves", "")
    if improves_label:
        improves_id = resolve_improves_id(improves_label)
        if improves_id:
            fields[IMPROVES_FIELD] = {"id": improves_id}

    ok, resp = jira_put(f"/rest/api/3/issue/{issue_key}", {"fields": fields})
    if ok:
        log.info(f"Updated idea {issue_key}: {summary}")
    else:
        log.error(f"Failed to update {issue_key}: {resp.status_code} {resp.text[:300]}")
    return ok


def create_epic(summary, epic_summary_text, source_idea_key, prd_url, prototype_url):
    """
    Create an Epic in the AX project with the standard description template.
    Returns (epic_key, epic_url) or (None, None) on failure.
    """
    # Build ADF description matching existing epic template
    description_adf = {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Product Manager:", "marks": [{"type": "strong"}]}]
            },
            {
                "type": "orderedList",
                "attrs": {"order": 1},
                "content": [
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "Summary: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": epic_summary_text},
                        ]}]
                    },
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "Validated: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": "Yes"},
                        ]}]
                    },
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "PRD: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": "View PRD", "marks": [{"type": "link", "attrs": {"href": prd_url}}]},
                        ]}]
                    },
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "Prototype: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": "View Prototype", "marks": [{"type": "link", "attrs": {"href": prototype_url}}]} if prototype_url and prototype_url != "N/A" else {"type": "text", "text": "N/A"},
                        ]}]
                    },
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "Source idea: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": source_idea_key, "marks": [{"type": "link", "attrs": {"href": f"https://axiscrm.atlassian.net/browse/{source_idea_key}"}}]},
                        ]}]
                    },
                ]
            },
            {"type": "rule"},
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Definition of Ready (DoR) - Epic Level",
                        "marks": [
                            {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/91062273/Delivery+process#Definition-of-Ready-(DoR)"}},
                            {"type": "strong"},
                        ]
                    },
                    {"type": "text", "text": "   |   ", "marks": [{"type": "strong"}]},
                    {
                        "type": "text",
                        "text": "Definition of Done (DoD) - Epic Level",
                        "marks": [
                            {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/91062273/Delivery+process#Definition-of-Done-(DoD)"}},
                            {"type": "strong"},
                        ]
                    },
                ]
            },
        ]
    }

    fields = {
        "project": {"key": AX_PROJECT_KEY},
        "issuetype": {"name": "Epic"},
        "summary": summary,
        "description": description_adf,
        "assignee": {"accountId": JAMES_ACCOUNT_ID},
        ISSUE_COLOR_FIELD: "blue_gray",  # lighter grey
    }

    ok, resp = jira_post("/rest/api/3/issue", {"fields": fields})
    if ok:
        data = resp.json()
        epic_key = data.get("key", "?")
        epic_url = f"https://axiscrm.atlassian.net/browse/{epic_key}"
        log.info(f"Created Epic {epic_key}: {summary}")
        return epic_key, epic_url
    else:
        log.error(f"Failed to create Epic: {resp.status_code} {resp.text[:300]}")
        return None, None


def create_task(epic_key, summary, task_summary, user_story, acceptance_criteria, test_plan, story_points):
    """
    Create a Task in AX project under an Epic, matching the default template.
    Returns (task_key, task_url) or (None, None) on failure.
    """
    # Build ADF description matching AX Task default template
    description_adf = {
        "version": 1,
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Product Manager:", "marks": [{"type": "strong"}]}]
            },
            {
                "type": "orderedList",
                "attrs": {"order": 1},
                "content": [
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "Summary: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": task_summary},
                        ]}]
                    },
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "User story: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": user_story},
                        ]}]
                    },
                    {
                        "type": "listItem",
                        "content": [
                            {"type": "paragraph", "content": [
                                {"type": "text", "text": "Acceptance criteria:", "marks": [{"type": "strong"}]},
                            ]},
                            {"type": "bulletList", "content": [
                                {"type": "listItem", "content": [
                                    {"type": "paragraph", "content": [{"type": "text", "text": ac}]}
                                ]}
                                for ac in acceptance_criteria
                            ]} if acceptance_criteria else
                            {"type": "paragraph", "content": [{"type": "text", "text": "—"}]},
                        ]
                    },
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "Test plan: ", "marks": [{"type": "strong"}]},
                            {"type": "text", "text": test_plan},
                        ]}]
                    },
                ]
            },
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": "Engineer:", "marks": [{"type": "strong"}]}]
            },
            {
                "type": "orderedList",
                "attrs": {"order": 1},
                "content": [
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Technical plan:"}]}]
                    },
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "Story points estimated", "marks": [
                                {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/91062273/Delivery+process#Story-points-framework"}},
                                {"type": "underline"},
                            ]},
                            {"type": "text", "text": ":", "marks": [{"type": "underline"}]},
                        ]}]
                    },
                    {
                        "type": "listItem",
                        "content": [{"type": "paragraph", "content": [
                            {"type": "text", "text": "Task broken down (<=3 story points or split into parts): Yes/No"},
                        ]}]
                    },
                ]
            },
            {"type": "rule"},
            {
                "type": "paragraph",
                "content": [
                    {
                        "type": "text",
                        "text": "Definition of Ready (DoR) - Task Level",
                        "marks": [
                            {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/91062273/Delivery+process#Definition-of-Ready-(DoR)"}},
                            {"type": "strong"},
                        ]
                    },
                    {"type": "text", "text": " | ", "marks": [{"type": "strong"}]},
                    {
                        "type": "text",
                        "text": "Definition of Done (DoD) - Task Level",
                        "marks": [
                            {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/91062273/Delivery+process#Definition-of-Done-(DoD)"}},
                            {"type": "strong"},
                        ]
                    },
                ]
            },
        ]
    }

    fields = {
        "project": {"key": AX_PROJECT_KEY},
        "issuetype": {"name": "Task"},
        "parent": {"key": epic_key},
        "summary": summary,
        "description": description_adf,
        "assignee": {"accountId": JAMES_ACCOUNT_ID},
        STORY_POINTS_FIELD: story_points,
    }

    ok, resp = jira_post("/rest/api/3/issue", {"fields": fields})
    if ok:
        data = resp.json()
        task_key = data.get("key", "?")
        task_url = f"https://axiscrm.atlassian.net/browse/{task_key}"
        log.info(f"Created Task {task_key} under {epic_key}: {summary} ({story_points} SP)")
        return task_key, task_url
    else:
        log.error(f"Failed to create Task under {epic_key}: {resp.status_code} {resp.text[:300]}")
        return None, None


def create_spike(epic_key, spike_data, prd_url, prototype_url, target_sprint):
    """
    Create a Spike in AX project under an Epic.
    spike_data: dict with summary, acceptance_criteria, tshirt_size, architectural_thoughts.
    Returns (spike_key, spike_url) or (None, None) on failure.
    """
    summary = spike_data.get("summary", f"Spike: {epic_key}")
    acceptance_criteria = spike_data.get("acceptance_criteria", [])
    tshirt_size = spike_data.get("tshirt_size", "M (5-8 SP)")
    architectural_thoughts = spike_data.get("architectural_thoughts", [])

    proto_display = prototype_url if prototype_url and prototype_url != "N/A" else None

    # Build markdown description
    md_lines = [
        "**Acceptance criteria:**",
    ]
    for ac in acceptance_criteria:
        md_lines.append(f"- {ac}")

    md_lines.append("")
    md_lines.append(f"**T-shirt size:** {tshirt_size}")

    sprint_display = target_sprint if target_sprint else "TBD"
    md_lines.append("")
    md_lines.append(f"**Target sprint:** {sprint_display}")

    md_lines.append("")
    md_lines.append("**Architectural thoughts:**")
    for at in architectural_thoughts:
        md_lines.append(f"- {at}")

    md_lines.append("")
    md_lines.append("**Supporting artefacts:**")
    if prd_url:
        md_lines.append(f"- [PRD]({prd_url})")
    else:
        md_lines.append("- PRD: N/A")
    if proto_display:
        md_lines.append(f"- [Design/Prototype]({prototype_url})")

    description_adf = {"version": 1, "type": "doc", "content": markdown_to_adf("\n".join(md_lines))}

    fields = {
        "project": {"key": AX_PROJECT_KEY},
        "issuetype": {"name": "Spike"},
        "parent": {"key": epic_key},
        "summary": summary,
        "description": description_adf,
        "assignee": {"accountId": JAMES_ACCOUNT_ID},
    }

    ok, resp = jira_post("/rest/api/3/issue", {"fields": fields})
    if ok:
        data = resp.json()
        spike_key = data.get("key", "?")
        spike_url = f"https://axiscrm.atlassian.net/browse/{spike_key}"
        log.info(f"Created Spike {spike_key} under {epic_key}: {summary}")
        return spike_key, spike_url
    else:
        log.error(f"Failed to create Spike under {epic_key}: {resp.status_code} {resp.text[:300]}")
        return None, None


def update_task_engineer_section(task_key, technical_plan_points, story_points):
    """
    Update a Task's description to fill in the Engineer section.
    Fetches existing description, replaces Engineer ordered list, and updates.
    
    technical_plan_points: list of 2-3 strings
    story_points: float
    """
    # Fetch existing issue to get current description
    issue = get_issue(task_key)
    if not issue:
        log.error(f"Cannot fetch {task_key} to update Engineer section")
        return False

    description = issue.get("fields", {}).get("description")
    if not description or not isinstance(description, dict):
        log.error(f"{task_key} has no ADF description")
        return False

    # Build the replacement Engineer ordered list content
    engineer_items = [
        {
            "type": "listItem",
            "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "Technical plan:", "marks": [{"type": "strong"}]},
            ]},
            {"type": "bulletList", "content": [
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": point}]}
                ]}
                for point in technical_plan_points
            ]}]
        },
        {
            "type": "listItem",
            "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "Story points estimated", "marks": [
                    {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/91062273/Delivery+process#Story-points-framework"}},
                    {"type": "underline"},
                ]},
                {"type": "text", "text": f": {story_points}", "marks": [{"type": "underline"}]},
            ]}]
        },
        {
            "type": "listItem",
            "content": [{"type": "paragraph", "content": [
                {"type": "text", "text": "Task broken down (<=3 story points or split into parts): "},
                {"type": "text", "text": "Yes", "marks": [{"type": "strong"}]},
            ]}]
        },
    ]

    # Walk the ADF and replace the Engineer ordered list
    # It's the second orderedList in the document
    content = description.get("content", [])
    ordered_list_count = 0
    for i, node in enumerate(content):
        if node.get("type") == "orderedList":
            ordered_list_count += 1
            if ordered_list_count == 2:
                # This is the Engineer ordered list — replace it
                content[i] = {
                    "type": "orderedList",
                    "attrs": {"order": 1},
                    "content": engineer_items,
                }
                break

    if ordered_list_count < 2:
        log.error(f"{task_key} description doesn't have expected Engineer ordered list")
        return False

    # Also update story points field
    update_payload = {
        "fields": {
            "description": description,
            STORY_POINTS_FIELD: story_points,
        }
    }

    try:
        r = requests.put(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{task_key}",
            auth=auth, headers=headers, json=update_payload, timeout=30,
        )
        if r.status_code == 204:
            log.info(f"Updated Engineer section for {task_key} ({story_points} SP)")
            return True
        log.error(f"Failed to update {task_key}: {r.status_code} {r.text[:300]}")
        return False
    except Exception as e:
        log.error(f"Failed to update {task_key}: {e}")
        return False


# ── Sprint Lifecycle ──────────────────────────────────────────────────────────

COMPLETED_STATUSES = {"done", "released"}


def get_active_sprints():
    """Get all active sprints on the AX board."""
    data = jira_get(f"/rest/agile/1.0/board/{AX_BOARD_ID}/sprint?state=active")
    return data.get("values", []) if data else []


def get_future_sprints():
    """Get all future sprints on the AX board, sorted by start date."""
    data = jira_get(f"/rest/agile/1.0/board/{AX_BOARD_ID}/sprint?state=future")
    sprints = data.get("values", []) if data else []
    sprints.sort(key=lambda s: s.get("startDate", ""))
    return sprints


def get_sprint_issues(sprint_id):
    """Get all issues in a sprint."""
    data = jira_get(f"/rest/agile/1.0/sprint/{sprint_id}/issue", params={
        "fields": f"summary,status,issuetype,priority,parent,{STORY_POINTS_FIELD}",
        "maxResults": 200,
    })
    return data.get("issues", []) if data else []


def get_incomplete_issues(sprint_id):
    """Get incomplete issues in a sprint."""
    return [i for i in get_sprint_issues(sprint_id)
            if i["fields"]["status"]["name"].lower() not in COMPLETED_STATUSES]


def close_sprint(sprint_id):
    """Close a sprint."""
    ok, _ = jira_post(f"/rest/agile/1.0/sprint/{sprint_id}", {"state": "closed"})
    return ok


def start_sprint(sprint):
    """Start a sprint."""
    ok, _ = jira_post(f"/rest/agile/1.0/sprint/{sprint['id']}",
                      {"state": "active", "startDate": sprint["startDate"], "endDate": sprint["endDate"]})
    return ok


def move_issue_to_sprint(issue_key, sprint_id):
    """Move a single issue into a sprint."""
    ok, _ = jira_post(f"/rest/agile/1.0/sprint/{sprint_id}/issue", {"issues": [issue_key]})
    return ok


def create_sprint(name, start_date, end_date):
    """Create a new sprint on the AX board.
    start_date/end_date: datetime objects (timezone-aware preferred)."""
    def _fmt(dt):
        if dt.tzinfo:
            return dt.isoformat(timespec='milliseconds')
        return dt.strftime("%Y-%m-%dT00:00:00.000Z")

    ok, r = jira_post("/rest/agile/1.0/sprint", {
        "name": name,
        "startDate": _fmt(start_date),
        "endDate": _fmt(end_date),
        "originBoardId": int(AX_BOARD_ID),
    })
    if ok:
        s = r.json()
        log.info(f"Created sprint '{name}' (id: {s['id']})")
        return s
    log.error(f"Failed to create sprint: {r.status_code} {r.text[:300]}")
    return None


def _next_monday(after_date):
    """Return the next Monday on or after the given date."""
    days_ahead = (0 - after_date.weekday()) % 7  # Monday = 0
    if days_ahead == 0:
        days_ahead = 7
    return after_date + timedelta(days=days_ahead)


def ensure_sprint_runway(required=12):
    """Ensure at least `required` future sprints exist. Creates missing ones.
    Weekly cadence: Monday 6am AEST to Friday 10pm AEST.
    Returns the (refreshed) list of future sprints."""
    import pytz
    aest = pytz.timezone("Australia/Sydney")

    future = get_future_sprints()
    if len(future) >= required:
        log.info(f"Sprint runway OK — {len(future)} future sprints.")
        return future

    log.info(f"Only {len(future)} future sprints. Creating up to {required}...")
    all_s = future + get_active_sprints()
    all_s.sort(key=lambda s: s.get("endDate", ""))

    if all_s:
        last_end = datetime.strptime(all_s[-1]["endDate"][:10], "%Y-%m-%d")
    else:
        last_end = datetime.now()

    # Determine next sprint number from existing sprint names
    existing_nums = []
    for s in all_s:
        import re as _re
        m = _re.search(r'Sprint (\d+)', s.get("name", ""))
        if m:
            existing_nums.append(int(m.group(1)))
    next_num = max(existing_nums) + 1 if existing_nums else 1

    for _ in range(required - len(future)):
        mon = _next_monday(last_end + timedelta(days=1))
        fri = mon + timedelta(days=4)  # Friday = Monday + 4

        # Monday 6:00am AEST, Friday 10:00pm AEST
        start_dt = aest.localize(datetime(mon.year, mon.month, mon.day, 6, 0))
        end_dt = aest.localize(datetime(fri.year, fri.month, fri.day, 22, 0))

        name = f"Sprint {next_num}"
        new = create_sprint(name, start_dt, end_dt)
        if new:
            future.append(new)
        last_end = fri
        next_num += 1

    future.sort(key=lambda s: s["startDate"])
    return future
