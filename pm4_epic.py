"""
PM Agent — PM4: Epic Creation
Generates an Epic ticket in AX project from approved PRD + prototype.
"""

from config import log
from jira_client import create_epic, add_comment
from claude_client import generate_epic_content, update_epic_with_changes
from confluence_client import fetch_page_content

# Pending epics awaiting approval: {message_id: {...}}
pending_epics = {}


def process_epic(issue_key, summary, prd_page_id, prd_web_url, prototype_url, chat_id, bot):
    """
    Generate Epic content from PRD and create in AX project.
    Called after PM3 prototype is approved.
    """
    from telegram_bot import send_epic_preview

    # Step 1: Acknowledge
    status_msg = bot.send_message(chat_id, f"📦 Generating Epic for {issue_key}...")

    # Step 2: Fetch PRD content
    prd_page = fetch_page_content(prd_page_id)
    if not prd_page:
        bot.edit_message_text(f"❌ Failed to fetch PRD page {prd_page_id}.", chat_id, status_msg.message_id)
        return
    prd_content = prd_page["text"]

    # Step 3: Generate Epic content via Claude
    bot.edit_message_text("📦 Generating Epic title and summary...", chat_id, status_msg.message_id)
    epic_data = generate_epic_content(issue_key, summary, prd_content)
    if not epic_data:
        bot.edit_message_text("❌ AI failed to generate Epic content. Check logs.", chat_id, status_msg.message_id)
        return

    epic_title = epic_data.get("epic_title", summary)
    epic_summary = epic_data.get("epic_summary", "")

    # Step 4: Delete status and send preview
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_epic_preview(bot, chat_id, issue_key, epic_title, epic_summary, prd_web_url, prototype_url)

    # Step 5: Store pending for callback
    if preview_msg:
        pending_epics[preview_msg.message_id] = {
            "issue_key": issue_key,
            "summary": summary,
            "epic_title": epic_title,
            "epic_summary": epic_summary,
            "prd_page_id": prd_page_id,
            "prd_web_url": prd_web_url,
            "prd_content": prd_content,
            "prototype_url": prototype_url,
            "chat_id": chat_id,
        }
        log.info(f"PM4: Epic preview sent for {issue_key} — awaiting approval (msg_id={preview_msg.message_id})")


def approve_epic(message_id, bot):
    """Approve a pending Epic: create in AX project, then trigger PM5 task breakdown."""
    pending = pending_epics.pop(message_id, None)
    if not pending:
        return "❌ This Epic has already been processed or expired."

    issue_key = pending["issue_key"]
    epic_title = pending["epic_title"]
    epic_summary = pending["epic_summary"]
    prd_web_url = pending["prd_web_url"]
    prd_page_id = pending["prd_page_id"]
    prototype_url = pending["prototype_url"]
    chat_id = pending["chat_id"]

    # Create Epic in AX project
    epic_key, epic_url = create_epic(
        summary=epic_title,
        epic_summary_text=epic_summary,
        source_idea_key=issue_key,
        prd_url=prd_web_url,
        prototype_url=prototype_url,
    )

    if not epic_key:
        return f"❌ Failed to create Epic in AX project for {issue_key}."

    # Comment on source idea with Epic link
    add_comment(issue_key, f"Epic created: {epic_key} — {epic_url}")

    # Comment on Epic linking back
    add_comment(epic_key, f"Source idea: {issue_key}\nPRD: {prd_web_url}\nPrototype: {prototype_url}")

    log.info(f"PM4: Epic {epic_key} created for {issue_key}")

    # Send approval confirmation
    bot.send_message(
        chat_id,
        f"✅ Epic [{epic_key}]({epic_url}) created — generating task breakdown...",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )

    # Trigger PM5: Task Breakdown
    try:
        from pm5_tasks import process_task_breakdown
        process_task_breakdown(epic_key, epic_title, issue_key, prd_page_id, prd_web_url, prototype_url, chat_id, bot)
    except Exception as e:
        log.error(f"PM5 task breakdown failed for {epic_key}: {e}")
        bot.send_message(chat_id, f"❌ Task breakdown failed for {epic_key}: {e}")

    return None  # Already sent confirmation


def reject_epic(message_id):
    """Reject a pending Epic."""
    pending = pending_epics.pop(message_id, None)
    if not pending:
        return "❌ This Epic has already been processed or expired."

    issue_key = pending["issue_key"]
    log.info(f"PM4: Rejected Epic for {issue_key}")
    return f"⛔ {issue_key} — Epic rejected"


def start_epic_changes(message_id, chat_id, bot):
    """Begin the epic changes flow."""
    pending = pending_epics.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This Epic has already been processed or expired.")
        return False

    bot.send_message(chat_id, "🔄 What would you like to change in the Epic? Send your instructions.")
    return True


def apply_epic_changes(message_id, change_text, chat_id, bot):
    """Apply changes to a pending Epic using Claude."""
    pending = pending_epics.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This Epic has already been processed or expired.")
        return

    from telegram_bot import send_epic_preview

    status_msg = bot.send_message(chat_id, "🔄 Regenerating Epic with your changes...")

    updated = update_epic_with_changes(
        current_title=pending["epic_title"],
        current_summary=pending["epic_summary"],
        change_instructions=change_text,
        prd_content=pending["prd_content"],
    )

    if not updated:
        bot.edit_message_text("❌ Failed to regenerate Epic. Try again.", chat_id, status_msg.message_id)
        return

    # Update pending data
    pending["epic_title"] = updated.get("epic_title", pending["epic_title"])
    pending["epic_summary"] = updated.get("epic_summary", pending["epic_summary"])

    # Remove old pending entry (keyed by old message_id)
    pending_epics.pop(message_id, None)

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_epic_preview(
        bot, chat_id,
        pending["issue_key"],
        pending["epic_title"],
        pending["epic_summary"],
        pending["prd_web_url"],
        pending["prototype_url"],
    )

    if preview_msg:
        pending_epics[preview_msg.message_id] = pending
        pending["chat_id"] = chat_id
        log.info(f"PM4: Epic re-generated for {pending['issue_key']} (msg_id={preview_msg.message_id})")
