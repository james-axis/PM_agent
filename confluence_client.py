"""
PM Agent — Confluence Client
Fetches Knowledge Base pages and extracts text from ADF.
"""

import json
import requests
from requests.auth import HTTPBasicAuth
from config import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, CONFLUENCE_BASE,
    CONFLUENCE_SPACE_ID, PRD_PARENT_ID, KB_PAGES, log,
)

auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
headers = {"Accept": "application/json", "Content-Type": "application/json"}


def adf_to_text(node):
    """Recursively extract plain text from an ADF node."""
    if isinstance(node, str):
        return node
    if isinstance(node, list):
        return " ".join(adf_to_text(n) for n in node)
    if isinstance(node, dict):
        parts = []
        if "text" in node:
            parts.append(node["text"])
        for child in node.get("content", []):
            parts.append(adf_to_text(child))
        return " ".join(parts)
    return ""


def fetch_page_content(page_id):
    """Fetch a single Confluence page and return its text content."""
    try:
        r = requests.get(
            f"{CONFLUENCE_BASE}/api/v2/pages/{page_id}",
            auth=auth, headers=headers, timeout=30,
            params={"body-format": "atlas_doc_format"},
        )
        if r.status_code != 200:
            log.warning(f"Failed to fetch page {page_id}: {r.status_code}")
            return None

        data = r.json()
        title = data.get("title", "Unknown")
        adf_str = data.get("body", {}).get("atlas_doc_format", {}).get("value", "")

        if adf_str:
            adf = json.loads(adf_str) if isinstance(adf_str, str) else adf_str
            text = adf_to_text(adf)
        else:
            text = ""

        return {"title": title, "page_id": page_id, "text": text}

    except Exception as e:
        log.error(f"Error fetching page {page_id}: {e}")
        return None


def fetch_knowledge_base():
    """
    Fetch all 6 KB pages and return structured context.
    Returns dict: {kb_key: {title, page_id, text}} for each KB page.
    """
    kb_context = {}
    for kb_key, page_id in KB_PAGES.items():
        content = fetch_page_content(page_id)
        if content:
            kb_context[kb_key] = content
            log.info(f"KB loaded: {content['title']} ({len(content['text'])} chars)")
        else:
            log.warning(f"KB missing: {kb_key} (page {page_id})")

    log.info(f"Knowledge base loaded: {len(kb_context)}/{len(KB_PAGES)} pages")
    return kb_context


def format_kb_for_prompt(kb_context):
    """
    Format KB context into a string block for inclusion in Claude prompts.
    Returns a single string with all KB content, section-delimited.
    """
    sections = []
    for kb_key, content in kb_context.items():
        label = kb_key.replace("_", " ").title()
        sections.append(f"=== {label} ===\n{content['text']}")

    return "\n\n".join(sections)


# ── Confluence write operations ───────────────────────────────────────────────

def create_page(title, markdown_body, parent_id=None):
    """
    Create a Confluence page in the CAD space.
    Returns (page_id, web_url) on success, (None, None) on failure.
    """
    payload = {
        "spaceId": CONFLUENCE_SPACE_ID,
        "status": "current",
        "title": title,
        "body": {
            "representation": "wiki",
            "value": markdown_body,
        },
    }
    if parent_id:
        payload["parentId"] = parent_id

    try:
        r = requests.post(
            f"{CONFLUENCE_BASE}/api/v2/pages",
            auth=auth, headers=headers, timeout=30,
            json=payload,
        )
        if r.status_code in (200, 201):
            data = r.json()
            page_id = data.get("id")
            web_url = data.get("_links", {}).get("webui", "")
            if web_url and not web_url.startswith("http"):
                web_url = f"{JIRA_BASE_URL}/wiki{web_url}"
            log.info(f"Created Confluence page: {title} (id={page_id})")
            return page_id, web_url
        log.error(f"Failed to create page: {r.status_code} {r.text[:500]}")
    except Exception as e:
        log.error(f"Error creating Confluence page: {e}")
    return None, None


def update_page(page_id, title, markdown_body):
    """
    Update an existing Confluence page.
    Returns True on success.
    """
    # Fetch current version number first
    try:
        r = requests.get(
            f"{CONFLUENCE_BASE}/api/v2/pages/{page_id}",
            auth=auth, headers=headers, timeout=30,
        )
        if r.status_code != 200:
            log.error(f"Failed to fetch page {page_id} for update: {r.status_code}")
            return False
        current_version = r.json().get("version", {}).get("number", 1)
    except Exception as e:
        log.error(f"Error fetching page version: {e}")
        return False

    payload = {
        "id": page_id,
        "status": "current",
        "title": title,
        "body": {
            "representation": "wiki",
            "value": markdown_body,
        },
        "version": {
            "number": current_version + 1,
            "message": "Updated by PM Agent",
        },
    }

    try:
        r = requests.put(
            f"{CONFLUENCE_BASE}/api/v2/pages/{page_id}",
            auth=auth, headers=headers, timeout=30,
            json=payload,
        )
        if r.status_code == 200:
            log.info(f"Updated Confluence page {page_id}: {title}")
            return True
        log.error(f"Failed to update page {page_id}: {r.status_code} {r.text[:500]}")
    except Exception as e:
        log.error(f"Error updating Confluence page: {e}")
    return False


def delete_page(page_id):
    """Delete a Confluence page. Returns True on success."""
    try:
        r = requests.delete(
            f"{CONFLUENCE_BASE}/api/v2/pages/{page_id}",
            auth=auth, headers=headers, timeout=30,
        )
        if r.status_code in (200, 204):
            log.info(f"Deleted Confluence page {page_id}")
            return True
        log.error(f"Failed to delete page {page_id}: {r.status_code} {r.text[:300]}")
    except Exception as e:
        log.error(f"Error deleting Confluence page: {e}")
    return False
