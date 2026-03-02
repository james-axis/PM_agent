"""
PM Agent — Jira Client
Thin wrapper around Jira Cloud REST API v3.
"""

import random
import requests
from requests.auth import HTTPBasicAuth
from config import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, AR_PROJECT_KEY, AX_PROJECT_KEY,
    JAMES_ACCOUNT_ID, SWIMLANE_FIELD, ROADMAP_FIELD, INITIATIVE_FIELD, PHASE_FIELD,
    ROADMAP_BACKLOG_ID, STORY_POINTS_FIELD,
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
    """Parse inline markdown (bold, italic) into ADF text nodes with marks."""
    if not text:
        return [{"type": "text", "text": " "}]

    nodes = []
    i = 0
    while i < len(text):
        # Bold: **text** or __text__
        if text[i:i+2] == '**':
            end = text.find('**', i + 2)
            if end != -1:
                if nodes == [] and i > 0:
                    nodes.append({"type": "text", "text": text[:i]})
                inner = text[i+2:end]
                if inner.strip():
                    nodes.append({"type": "text", "text": inner, "marks": [{"type": "strong"}]})
                i = end + 2
                continue
        # Bold/italic with single *: *text* (treat as bold for Jira display)
        if text[i] == '*' and (i == 0 or text[i-1] in ' \t(') and text[i:i+2] != '**':
            end = text.find('*', i + 1)
            if end != -1 and end > i + 1:
                inner = text[i+1:end]
                if ' ' not in inner or len(inner) < 80:  # Likely intentional formatting
                    if nodes == [] and i > 0:
                        nodes.append({"type": "text", "text": text[:i]})
                    nodes.append({"type": "text", "text": inner, "marks": [{"type": "strong"}]})
                    i = end + 1
                    continue
        i += 1

    if not nodes:
        # No inline markdown found — return plain text
        return [{"type": "text", "text": text}]

    # Capture any remaining text after the last markdown token
    # Rebuild by finding gaps between nodes
    result = []
    pos = 0
    for node in nodes:
        node_text = node["text"]
        marks = node.get("marks")
        if marks:
            # Find where the original markdown was
            if marks[0]["type"] == "strong":
                # Look for **text** or *text*
                bold_double = text.find(f'**{node_text}**', pos)
                bold_single = text.find(f'*{node_text}*', pos)
                if bold_double != -1 and (bold_single == -1 or bold_double <= bold_single):
                    if bold_double > pos:
                        result.append({"type": "text", "text": text[pos:bold_double]})
                    result.append(node)
                    pos = bold_double + len(node_text) + 4
                elif bold_single != -1:
                    if bold_single > pos:
                        result.append({"type": "text", "text": text[pos:bold_single]})
                    result.append(node)
                    pos = bold_single + len(node_text) + 2
                else:
                    result.append(node)
        else:
            result.append(node)

    if pos < len(text):
        remaining = text[pos:]
        if remaining.strip():
            result.append({"type": "text", "text": remaining})

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
                            {"type": "text", "text": "View Prototype", "marks": [{"type": "link", "attrs": {"href": prototype_url}}]},
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
        ISSUE_COLOR_FIELD: random.choice(EPIC_COLORS),
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
