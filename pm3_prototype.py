"""
PM Agent — PM3: Interactive Prototype Pipeline
Orchestrates: approved PRD → context gathering → AI prototype → GitHub Pages → Telegram preview → approval.
"""

from config import JIRA_BASE_URL, log
from confluence_client import (
    fetch_page_content, fetch_knowledge_base, format_kb_for_prompt,
    update_page,
)
from claude_client import (
    extract_db_keywords, generate_prototype, update_prototype_with_changes,
)
from db_client import discover_relevant_schemas
from github_client import push_prototype
from jira_client import add_comment


# In-memory store for pending prototypes (keyed by Telegram message_id)
pending_prototypes = {}


def process_prototype(issue_key, summary, prd_page_id, prd_web_url, chat_id, bot):
    """
    Full PM3 pipeline: approved PRD → gather context → Claude prototype → GitHub → Telegram preview.
    """
    from telegram_bot import send_prototype_preview

    # Step 1: Acknowledge
    status_msg = bot.send_message(chat_id, f"🎨 Generating prototype for {issue_key}...")

    # Step 2: Fetch PRD content from Confluence
    prd_page = fetch_page_content(prd_page_id)
    if not prd_page:
        bot.edit_message_text(f"❌ Failed to fetch PRD page {prd_page_id}.", chat_id, status_msg.message_id)
        return
    prd_content = prd_page["text"]

    # Step 3: Fetch design system from KB
    bot.edit_message_text("🎨 Loading design system...", chat_id, status_msg.message_id)
    kb_context = fetch_knowledge_base()
    design_system_text = ""
    if kb_context and "brand_design_system" in kb_context:
        design_system_text = kb_context["brand_design_system"]["text"]
    if not design_system_text:
        design_system_text = "(Design system unavailable — use Tailwind defaults with orange #D34108 as primary)"

    # Step 4: Discover relevant DB schemas
    bot.edit_message_text("🎨 Discovering database schema...", chat_id, status_msg.message_id)
    db_keywords = extract_db_keywords(prd_content)
    log.info(f"PM3: DB keywords extracted: {db_keywords}")
    db_schema_text = discover_relevant_schemas(db_keywords)

    # Step 5: Generate prototype with Claude
    bot.edit_message_text("🎨 Building interactive prototype...", chat_id, status_msg.message_id)
    html_content = generate_prototype(issue_key, summary, prd_content, design_system_text, db_schema_text)
    if not html_content:
        bot.edit_message_text("❌ AI failed to generate prototype. Check logs.", chat_id, status_msg.message_id)
        return

    # Strip any markdown fences if Claude wrapped the output
    if html_content.startswith("```"):
        lines = html_content.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        html_content = "\n".join(lines)

    # Step 6: Push to GitHub Pages
    bot.edit_message_text("🎨 Publishing prototype...", chat_id, status_msg.message_id)
    filename = f"{issue_key}.html"
    prototype_url = push_prototype(filename, html_content, f"Prototype for {issue_key}: {summary}")
    if not prototype_url:
        bot.edit_message_text("❌ Failed to push prototype to GitHub. Check logs.", chat_id, status_msg.message_id)
        return

    # Step 7: Add prototype URL to Jira idea and PRD page
    add_comment(issue_key, f"Interactive prototype: {prototype_url}")

    # Update PRD page — append prototype link section
    _append_prototype_link_to_prd(prd_page_id, prd_page["title"], prototype_url)

    # Step 8: Delete status message and send preview
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_prototype_preview(bot, chat_id, issue_key, summary, prototype_url)

    # Step 9: Store in pending for callback handling
    if preview_msg:
        pending_prototypes[preview_msg.message_id] = {
            "issue_key": issue_key,
            "summary": summary,
            "prototype_url": prototype_url,
            "html_content": html_content,
            "prd_content": prd_content,
            "prd_page_id": prd_page_id,
            "prd_web_url": prd_web_url,
            "design_system_text": design_system_text,
            "db_schema_text": db_schema_text,
            "chat_id": chat_id,
        }
        log.info(f"PM3: Prototype published at {prototype_url} — awaiting approval (msg_id={preview_msg.message_id})")


def _append_prototype_link_to_prd(page_id, page_title, prototype_url):
    """Append a UX/UI Design section with prototype link to the PRD page."""
    try:
        prd_page = fetch_page_content(page_id)
        if not prd_page:
            return

        # Get current markdown content via the API
        import requests
        from requests.auth import HTTPBasicAuth
        from config import JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, CONFLUENCE_BASE

        r = requests.get(
            f"{CONFLUENCE_BASE}/api/v2/pages/{page_id}",
            auth=HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN),
            headers={"Accept": "application/json"},
            params={"body-format": "storage"},
            timeout=30,
        )
        if r.status_code != 200:
            log.warning(f"Could not fetch PRD storage format: {r.status_code}")
            return

        data = r.json()
        current_body = data.get("body", {}).get("storage", {}).get("value", "")
        current_version = data.get("version", {}).get("number", 1)

        # Append UX/UI section with prototype link
        prototype_section = (
            f'<h2>UX/UI Design</h2>'
            f'<p><strong>Interactive prototype:</strong> '
            f'<a href="{prototype_url}">{prototype_url}</a></p>'
        )

        updated_body = current_body + prototype_section

        # Update via storage format
        payload = {
            "id": page_id,
            "status": "current",
            "title": page_title,
            "body": {
                "representation": "storage",
                "value": updated_body,
            },
            "version": {
                "number": current_version + 1,
                "message": "Added UX/UI prototype link (PM3)",
            },
        }

        r = requests.put(
            f"{CONFLUENCE_BASE}/api/v2/pages/{page_id}",
            auth=HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN),
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if r.status_code == 200:
            log.info(f"PRD updated with prototype link: {page_id}")
        else:
            log.warning(f"Failed to update PRD with prototype link: {r.status_code} {r.text[:300]}")

    except Exception as e:
        log.error(f"Error appending prototype link to PRD: {e}")


def approve_prototype(message_id, bot):
    """Approve a pending prototype."""
    pending = pending_prototypes.pop(message_id, None)
    if not pending:
        return "❌ This prototype has already been processed or expired."

    issue_key = pending["issue_key"]
    prototype_url = pending["prototype_url"]

    add_comment(issue_key, "Prototype approved by James. Ready for development.")
    log.info(f"PM3: Approved prototype for {issue_key}")

    return f"✅ [{issue_key}]({prototype_url}) — Prototype Approved"


def reject_prototype(message_id):
    """Reject a pending prototype — remove from GitHub."""
    pending = pending_prototypes.pop(message_id, None)
    if not pending:
        return "❌ This prototype has already been processed or expired."

    issue_key = pending["issue_key"]
    # Note: we don't delete from GitHub — the file can be overwritten later
    log.info(f"PM3: Rejected prototype for {issue_key}")
    return f"⛔ {issue_key} — Prototype rejected"


def start_prototype_changes(message_id, chat_id, bot):
    """Begin the prototype changes flow."""
    pending = pending_prototypes.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This prototype has already been processed or expired.")
        return False

    bot.send_message(chat_id, "🔄 What would you like to change in the prototype? Send your instructions.")
    return True


def apply_prototype_changes(message_id, change_instructions, bot):
    """Apply changes to a prototype: re-generate, update GitHub, send new preview."""
    from telegram_bot import send_prototype_preview

    pending = pending_prototypes.get(message_id)
    if not pending:
        return None

    chat_id = pending["chat_id"]
    issue_key = pending["issue_key"]
    status_msg = bot.send_message(chat_id, "🎨 Applying prototype changes...")

    # Re-generate with changes
    updated_html = update_prototype_with_changes(
        pending["html_content"],
        change_instructions,
        pending["prd_content"],
        pending["design_system_text"],
        pending["db_schema_text"],
    )

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if not updated_html:
        bot.send_message(chat_id, "❌ Failed to apply prototype changes. Try again.")
        return None

    # Strip markdown fences
    if updated_html.startswith("```"):
        lines = updated_html.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        updated_html = "\n".join(lines)

    # Push updated file to GitHub
    filename = f"{issue_key}.html"
    prototype_url = push_prototype(filename, updated_html, f"Update prototype: {issue_key}")
    if not prototype_url:
        bot.send_message(chat_id, "❌ Failed to push updated prototype to GitHub.")
        return None

    # Remove old pending entry
    pending_prototypes.pop(message_id, None)

    # Send updated preview
    preview_msg = send_prototype_preview(bot, chat_id, issue_key, pending["summary"], prototype_url)

    if preview_msg:
        pending_prototypes[preview_msg.message_id] = {
            **pending,
            "html_content": updated_html,
            "prototype_url": prototype_url,
        }
        log.info(f"PM3: Updated prototype for {issue_key} — awaiting approval (msg_id={preview_msg.message_id})")

    return preview_msg
