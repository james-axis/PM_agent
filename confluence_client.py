"""
PM Agent — Confluence Client
Fetches Knowledge Base pages and extracts text from ADF.
"""

import json
import re
import requests
from requests.auth import HTTPBasicAuth
from config import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, CONFLUENCE_BASE,
    CONFLUENCE_SPACE_ID, PRD_PARENT_ID, KB_PAGES, log,
)

auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
headers = {"Accept": "application/json", "Content-Type": "application/json"}


def markdown_to_wiki(md_text):
    """Convert markdown to Confluence wiki markup.

    Handles: headings, bold, italic, bullet lists, numbered lists, tables, links, code blocks.
    """
    if not md_text:
        return ""

    lines = md_text.split("\n")
    wiki_lines = []
    in_code_block = False
    in_table = False

    for line in lines:
        # Code blocks
        if line.strip().startswith("```"):
            if in_code_block:
                wiki_lines.append("{code}")
                in_code_block = False
            else:
                lang = line.strip()[3:].strip()
                wiki_lines.append("{code" + (f":language={lang}" if lang else "") + "}")
                in_code_block = True
            continue

        if in_code_block:
            wiki_lines.append(line)
            continue

        stripped = line.strip()

        # Empty lines
        if not stripped:
            if in_table:
                in_table = False
            wiki_lines.append("")
            continue

        # Headings: ## text → h2. text
        if stripped.startswith("######"):
            wiki_lines.append(f"h6. {_inline_md_to_wiki(stripped[6:].strip())}")
            continue
        if stripped.startswith("#####"):
            wiki_lines.append(f"h5. {_inline_md_to_wiki(stripped[5:].strip())}")
            continue
        if stripped.startswith("####"):
            wiki_lines.append(f"h4. {_inline_md_to_wiki(stripped[4:].strip())}")
            continue
        if stripped.startswith("###"):
            wiki_lines.append(f"h3. {_inline_md_to_wiki(stripped[3:].strip())}")
            continue
        if stripped.startswith("##"):
            wiki_lines.append(f"h2. {_inline_md_to_wiki(stripped[2:].strip())}")
            continue
        if stripped.startswith("# "):
            wiki_lines.append(f"h1. {_inline_md_to_wiki(stripped[2:].strip())}")
            continue

        # Tables: | col1 | col2 |
        if stripped.startswith("|") and stripped.endswith("|"):
            # Skip separator rows like |---|---|
            if all(c in "|-: " for c in stripped):
                continue
            # Convert: | col | col | → || col || col || (header) or | col | col | (data)
            cells = [c.strip() for c in stripped.split("|")[1:-1]]
            if not in_table:
                # First row = header
                wiki_lines.append("|| " + " || ".join(_inline_md_to_wiki(c) for c in cells) + " ||")
                in_table = True
            else:
                wiki_lines.append("| " + " | ".join(_inline_md_to_wiki(c) for c in cells) + " |")
            continue

        in_table = False

        # Bullet lists: - text or * text (not **bold**)
        if stripped.startswith("- ") or (stripped.startswith("* ") and not stripped.startswith("**")):
            wiki_lines.append(f"* {_inline_md_to_wiki(stripped[2:])}")
            continue

        # Numbered lists: 1. text
        if len(stripped) > 2 and stripped[0].isdigit() and '. ' in stripped[:5]:
            dot_pos = stripped.index('. ')
            wiki_lines.append(f"# {_inline_md_to_wiki(stripped[dot_pos+2:])}")
            continue

        # Horizontal rule
        if stripped in ("---", "***", "___"):
            wiki_lines.append("----")
            continue

        # Regular paragraph
        wiki_lines.append(_inline_md_to_wiki(stripped))

    return "\n".join(wiki_lines)


def _inline_md_to_wiki(text):
    """Convert inline markdown to Confluence wiki markup.
    **bold** → *bold*, *italic* → _italic_, [text](url) → [text|url], `code` → {{code}}
    """
    if not text:
        return ""

    # Inline code: `code` → {{code}}
    text = re.sub(r'`([^`]+)`', r'{{\1}}', text)

    # Bold: **text** → *text*
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text)

    # Links: [text](url) → [text|url]
    text = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'[\1|\2]', text)

    return text


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
    Converts markdown to Confluence wiki markup before sending.
    Returns (page_id, web_url) on success, (None, None) on failure.
    """
    wiki_body = markdown_to_wiki(markdown_body)

    payload = {
        "spaceId": CONFLUENCE_SPACE_ID,
        "status": "current",
        "title": title,
        "body": {
            "representation": "wiki",
            "value": wiki_body,
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
    Converts markdown to Confluence wiki markup before sending.
    Returns True on success.
    """
    wiki_body = markdown_to_wiki(markdown_body)

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
            "value": wiki_body,
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
