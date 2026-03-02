"""
PM Agent — PM2: PRD Generation Pipeline
Orchestrates: approved idea → KB context → AI PRD generation → Confluence page → Telegram preview → approval.
"""

from config import PRD_PARENT_ID, JIRA_BASE_URL, log
from confluence_client import (
    fetch_knowledge_base, format_kb_for_prompt,
    create_page, update_page, delete_page, adf_to_text,
)
from claude_client import generate_prd, update_prd_with_changes
from jira_client import add_comment, get_issue, append_prd_link_to_description


# In-memory store for pending PRDs (keyed by Telegram message_id)
pending_prds = {}


def process_prd(issue_key, summary, chat_id, bot, inspiration=""):
    """
    Full PM2 pipeline: approved idea → KB fetch → Claude PRD → Confluence page → Telegram preview.
    """
    from telegram_bot import send_prd_preview

    # Step 1: Acknowledge
    status_msg = bot.send_message(chat_id, f"📋 Generating PRD for {issue_key}...")

    # Step 2: Fetch idea description from Jira
    issue = get_issue(issue_key)
    if not issue:
        bot.edit_message_text(f"❌ Failed to fetch {issue_key} from Jira.", chat_id, status_msg.message_id)
        return

    description_adf = issue.get("fields", {}).get("description")
    if description_adf:
        idea_description = adf_to_text(description_adf)
    else:
        idea_description = "(No description provided)"

    # Step 3: Fetch KB
    bot.edit_message_text("📋 Loading knowledge base...", chat_id, status_msg.message_id)
    kb_context = fetch_knowledge_base()
    if not kb_context:
        bot.edit_message_text("❌ Failed to load knowledge base.", chat_id, status_msg.message_id)
        return

    kb_text = format_kb_for_prompt(kb_context)

    # Step 3b: Gather codebase context (DB schema + relevant models/views)
    bot.edit_message_text("📋 Investigating codebase...", chat_id, status_msg.message_id)
    try:
        from codebase_context import gather_codebase_context
        codebase = gather_codebase_context(f"{summary}\n{idea_description}", purpose="requirements")
        db_schema_text = codebase.get("db_schema_text", "")
        code_context = codebase.get("code_context", "")
    except Exception as e:
        log.warning(f"Codebase context failed for {issue_key}: {e}")
        db_schema_text = ""
        code_context = ""

    # Step 4: Generate PRD with Claude
    bot.edit_message_text("📋 Writing PRD with AI...", chat_id, status_msg.message_id)
    prd_markdown = generate_prd(summary, idea_description, issue_key, kb_text,
                                inspiration=inspiration, db_schema_text=db_schema_text,
                                code_context=code_context)
    if not prd_markdown:
        bot.edit_message_text("❌ AI failed to generate PRD. Check logs.", chat_id, status_msg.message_id)
        return

    # Step 5: Create Confluence page
    bot.edit_message_text("📋 Creating Confluence page...", chat_id, status_msg.message_id)
    page_title = f"PRD — {issue_key}: {summary}"
    page_id, web_url = create_page(page_title, prd_markdown, parent_id=PRD_PARENT_ID)
    if not page_id:
        bot.edit_message_text("❌ Failed to create Confluence page. Check logs.", chat_id, status_msg.message_id)
        return

    # Step 6: Add comment on Jira idea linking to PRD
    if not web_url:
        web_url = f"{JIRA_BASE_URL}/wiki/spaces/CAD/pages/{page_id}"
    add_comment(issue_key, f"PRD created: {web_url}")

    # Step 6b: Append PRD link to idea description
    append_prd_link_to_description(issue_key, page_title, web_url)

    # Step 7: Delete status message and send preview
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_prd_preview(bot, chat_id, issue_key, summary, page_id, web_url)

    # Step 8: Store in pending for callback handling
    if preview_msg:
        pending_prds[preview_msg.message_id] = {
            "issue_key": issue_key,
            "summary": summary,
            "page_id": page_id,
            "page_title": page_title,
            "web_url": web_url,
            "prd_markdown": prd_markdown,
            "kb_context_text": kb_text,
            "inspiration": inspiration,
            "chat_id": chat_id,
        }
        log.info(f"PM2: Created PRD page {page_id} for {issue_key} — awaiting approval (msg_id={preview_msg.message_id})")


def approve_prd(message_id, bot):
    """Approve a pending PRD: ask if prototype is needed before proceeding."""
    pending = pending_prds.get(message_id)
    if not pending:
        return "❌ This PRD has already been processed or expired."

    issue_key = pending["issue_key"]
    summary = pending["summary"]
    chat_id = pending["chat_id"]

    add_comment(issue_key, "PRD approved")
    log.info(f"PM2: Approved PRD for {issue_key}: {summary}")

    # Ask if prototype is needed (don't pop from pending yet — callback needs it)
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    jira_link = f"https://axiscrm.atlassian.net/browse/{issue_key}"

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Yes — Generate Prototype", callback_data="pm2_proto_yes"),
        InlineKeyboardButton("⏭ No — Skip to Epic", callback_data="pm2_proto_no"),
    )

    bot.send_message(
        chat_id,
        f"✅ [{issue_key}]({jira_link}) — PRD Approved\n\n"
        f"🎨 *Prototype needed?*",
        parse_mode="Markdown",
        reply_markup=markup,
        disable_web_page_preview=True,
    )

    return None  # Already sent message above


# Track which PRD message_id is awaiting prototype decision per chat
_proto_decision_pending = {}  # {chat_id: prd_message_id}


def set_proto_decision_pending(chat_id, prd_message_id):
    """Track that a prototype yes/no decision is pending for a PRD."""
    _proto_decision_pending[chat_id] = prd_message_id


def proceed_with_prototype(chat_id, bot):
    """User chose Yes — generate prototype (PM3)."""
    prd_msg_id = _proto_decision_pending.pop(chat_id, None)
    if not prd_msg_id:
        bot.send_message(chat_id, "❌ No pending PRD decision found.")
        return

    pending = pending_prds.pop(prd_msg_id, None)
    if not pending:
        bot.send_message(chat_id, "❌ PRD data expired.")
        return

    issue_key = pending["issue_key"]
    summary = pending["summary"]
    page_id = pending["page_id"]
    web_url = pending["web_url"]

    add_comment(issue_key, "Prototype needed — generating (PM3)")
    bot.send_message(chat_id, f"🎨 Generating prototype for {issue_key}...")

    try:
        from pm3_prototype import process_prototype
        process_prototype(issue_key, summary, page_id, web_url, chat_id, bot)
    except Exception as e:
        log.error(f"PM3 prototype generation failed for {issue_key}: {e}")
        bot.send_message(chat_id, f"❌ Prototype generation failed for {issue_key}: {e}")


def skip_prototype(chat_id, bot):
    """User chose No — skip PM3, go straight to PM4 with prototype N/A."""
    prd_msg_id = _proto_decision_pending.pop(chat_id, None)
    if not prd_msg_id:
        bot.send_message(chat_id, "❌ No pending PRD decision found.")
        return

    pending = pending_prds.pop(prd_msg_id, None)
    if not pending:
        bot.send_message(chat_id, "❌ PRD data expired.")
        return

    issue_key = pending["issue_key"]
    summary = pending["summary"]
    prd_page_id = pending["page_id"]
    prd_web_url = pending["web_url"]

    add_comment(issue_key, "Prototype skipped — proceeding to Epic (PM4)")
    log.info(f"PM2→PM4: Skipping prototype for {issue_key}")

    jira_link = f"https://axiscrm.atlassian.net/browse/{issue_key}"
    bot.send_message(
        chat_id,
        f"⏭ [{issue_key}]({jira_link}) — Prototype skipped, generating Epic...",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )

    try:
        from pm4_epic import process_epic
        process_epic(issue_key, summary, prd_page_id, prd_web_url, "N/A", chat_id, bot)
    except Exception as e:
        log.error(f"PM4 Epic generation failed for {issue_key}: {e}")
        bot.send_message(chat_id, f"❌ Epic generation failed for {issue_key}: {e}")


def reject_prd(message_id):
    """Reject a pending PRD: delete the Confluence page."""
    pending = pending_prds.pop(message_id, None)
    if not pending:
        return "❌ This PRD has already been processed or expired."

    issue_key = pending["issue_key"]
    page_id = pending["page_id"]
    summary = pending["summary"]

    deleted = delete_page(page_id)

    log.info(f"PM2: Rejected PRD for {issue_key}: {summary} (deleted={deleted})")
    if deleted:
        return f"⛔ {issue_key} — PRD deleted"
    else:
        return f"⛔ {issue_key} — Failed to delete PRD, remove manually"


def start_prd_changes(message_id, chat_id, bot):
    """Begin the PRD changes flow — prompt user for change instructions."""
    pending = pending_prds.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This PRD has already been processed or expired.")
        return False

    bot.send_message(chat_id, "🔄 What would you like to change in the PRD? Send your instructions.")
    return True


def apply_prd_changes(message_id, change_instructions, bot):
    """Apply changes to a pending PRD: re-generate, update Confluence page, send new preview."""
    from telegram_bot import send_prd_preview

    pending = pending_prds.get(message_id)
    if not pending:
        return None

    chat_id = pending["chat_id"]
    issue_key = pending["issue_key"]
    status_msg = bot.send_message(chat_id, "📋 Applying PRD changes...")

    # Re-generate with changes
    updated_markdown = update_prd_with_changes(
        pending["prd_markdown"],
        change_instructions,
        pending["kb_context_text"],
    )

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if not updated_markdown:
        bot.send_message(chat_id, "❌ Failed to apply PRD changes. Try again.")
        return None

    # Update the Confluence page
    ok = update_page(pending["page_id"], pending["page_title"], updated_markdown)
    if not ok:
        bot.send_message(chat_id, "❌ Failed to update Confluence page.")
        return None

    # Remove old pending entry
    pending_prds.pop(message_id, None)

    # Send updated preview
    preview_msg = send_prd_preview(
        bot, chat_id, issue_key, pending["summary"],
        pending["page_id"], pending["web_url"],
    )

    if preview_msg:
        pending_prds[preview_msg.message_id] = {
            **pending,
            "prd_markdown": updated_markdown,
        }
        log.info(f"PM2: Updated PRD for {issue_key} — awaiting approval (msg_id={preview_msg.message_id})")

    return preview_msg
