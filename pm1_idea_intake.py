"""
PM Agent — PM1: Idea Intake Pipeline
Orchestrates: raw idea → KB context → AI enrichment → Jira creation → Telegram preview → approval.
"""

from config import log
from confluence_client import fetch_knowledge_base, format_kb_for_prompt
from claude_client import enrich_idea, apply_changes
from jira_client import create_idea, add_comment, update_idea


# In-memory store for pending ideas (keyed by message_id from Telegram)
pending_ideas = {}

# In-memory store for pending roadmap selections (keyed by message_id)
pending_roadmap = {}


def process_idea(raw_idea, chat_id, bot):
    """
    Full PM1 pipeline: text → KB fetch → Claude enrichment → Jira creation → Telegram preview.
    Creates the idea in Jira immediately. Approval adds PM2 comment.
    """
    from telegram_bot import send_idea_preview

    # Step 1: Acknowledge
    status_msg = bot.send_message(chat_id, "🧠 Loading knowledge base...")

    # Step 2: Fetch KB
    kb_context = fetch_knowledge_base()
    if not kb_context:
        bot.edit_message_text("❌ Failed to load knowledge base. Check Confluence access.", chat_id, status_msg.message_id)
        return

    kb_text = format_kb_for_prompt(kb_context)
    bot.edit_message_text("🧠 Enriching your idea with AI...", chat_id, status_msg.message_id)

    # Step 3: AI enrichment
    structured = enrich_idea(raw_idea, kb_text)
    if not structured:
        bot.edit_message_text("❌ AI enrichment failed. Check Claude API key and logs.", chat_id, status_msg.message_id)
        return

    # Step 4: Create in Jira immediately
    bot.edit_message_text("📝 Creating idea in Jira...", chat_id, status_msg.message_id)
    issue_key = create_idea(structured)
    if not issue_key:
        bot.edit_message_text("❌ Failed to create idea in Jira. Check logs.", chat_id, status_msg.message_id)
        return

    # Step 5: Delete status message and send preview
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    summary = structured.get("summary", "Untitled")
    preview_msg = send_idea_preview(bot, chat_id, issue_key, summary)

    # Step 6: Store in pending for callback handling
    if preview_msg:
        pending_ideas[preview_msg.message_id] = {
            "issue_key": issue_key,
            "structured": structured,
            "raw_idea": raw_idea,
            "kb_context_text": kb_text,
            "chat_id": chat_id,
        }
        log.info(f"PM1: Created {issue_key} — awaiting approval (msg_id={preview_msg.message_id})")


def approve_idea(message_id, bot):
    """Approve a pending idea: show roadmap picker before triggering PM2 PRD generation."""
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

    pending = pending_ideas.pop(message_id, None)
    if not pending:
        return "❌ This idea has already been processed or expired."

    issue_key = pending["issue_key"]
    summary = pending["structured"].get("summary", "Untitled")
    chat_id = pending["chat_id"]

    add_comment(issue_key, "Approved, next step: PRD (PM2)")

    link = f"https://axiscrm.atlassian.net/browse/{issue_key}"
    log.info(f"PM1: Approved {issue_key}: {summary}")

    # Fetch roadmap options and show picker
    from jira_client import get_roadmap_options
    options = get_roadmap_options()

    markup = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for opt in options:
        # Skip Backlog — idea starts there already
        if opt["value"].lower() == "backlog":
            continue
        buttons.append(
            InlineKeyboardButton(opt["value"], callback_data=f"roadmap_{opt['id']}")
        )
    # Add a "Stay in Backlog" option
    buttons.append(InlineKeyboardButton("📋 Stay in Backlog", callback_data="roadmap_skip"))

    # Add buttons in rows of 2
    for i in range(0, len(buttons), 2):
        row = buttons[i:i+2]
        markup.row(*row)

    roadmap_msg = bot.send_message(
        chat_id,
        f"✅ [{issue_key}]({link}) — Approved\n\n"
        "📅 Which sprint should this go on the roadmap?",
        parse_mode="Markdown",
        disable_web_page_preview=True,
        reply_markup=markup,
    )

    # Store context for roadmap callback
    pending_roadmap[roadmap_msg.message_id] = {
        "issue_key": issue_key,
        "summary": summary,
        "chat_id": chat_id,
    }

    return None  # Don't send another message — we already sent one


def handle_roadmap_selection(message_id, option_id, bot):
    """Handle roadmap selection callback: update field, then ask for inspiration."""
    pending = pending_roadmap.pop(message_id, None)
    if not pending:
        return "❌ This selection has already been processed or expired."

    issue_key = pending["issue_key"]
    summary = pending["summary"]
    chat_id = pending["chat_id"]
    link = f"https://axiscrm.atlassian.net/browse/{issue_key}"

    if option_id != "skip":
        from jira_client import set_roadmap
        ok, _ = set_roadmap(issue_key, option_id)
        if ok:
            log.info(f"PM1: Set roadmap on {issue_key} to option {option_id}")
        else:
            log.warning(f"PM1: Failed to set roadmap on {issue_key}")

    # Continue to inspiration prompt
    bot.send_message(
        chat_id,
        "🎯 What's the inspiration for this? Any existing products, features, or designs "
        "we should reference? Anything off the shelf we can replicate?\n\n"
        "_Send your inspiration or 'skip' to proceed without._",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )

    from telegram_bot import user_state
    user_state[chat_id] = {
        "mode": "awaiting_inspiration",
        "issue_key": issue_key,
        "summary": summary,
    }

    return None


def reject_idea(message_id):
    """Reject a pending idea: archive it in Jira."""
    pending = pending_ideas.pop(message_id, None)
    if not pending:
        return "❌ This idea has already been processed or expired."

    issue_key = pending["issue_key"]
    summary = pending["structured"].get("summary", "Untitled")

    from jira_client import archive_issue
    archived = archive_issue(issue_key)

    log.info(f"PM1: Rejected {issue_key}: {summary} (archived={archived})")
    if archived:
        return f"⛔ {issue_key} — Archived"
    else:
        return f"⛔ {issue_key} — Failed to archive, do it manually"


def start_changes(message_id, chat_id, bot):
    """Begin the changes flow — prompt user for change instructions."""
    pending = pending_ideas.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This idea has already been processed or expired.")
        return False

    bot.send_message(chat_id, "🔄 What would you like to change? Send your instructions.")
    return True


def apply_idea_changes(message_id, change_instructions, bot):
    """Apply changes to a pending idea: re-enrich, update Jira issue, send new preview."""
    from telegram_bot import send_idea_preview

    pending = pending_ideas.get(message_id)
    if not pending:
        return None

    chat_id = pending["chat_id"]
    issue_key = pending["issue_key"]
    status_msg = bot.send_message(chat_id, "🧠 Applying changes...")

    updated = apply_changes(
        pending["structured"],
        change_instructions,
        pending["kb_context_text"],
    )

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if not updated:
        bot.send_message(chat_id, "❌ Failed to apply changes. Try again.")
        return None

    # Update the Jira issue
    ok = update_idea(issue_key, updated)
    if not ok:
        bot.send_message(chat_id, f"❌ Failed to update {issue_key} in Jira.")
        return None

    # Remove old pending entry
    pending_ideas.pop(message_id, None)

    # Send updated preview
    summary = updated.get("summary", "Untitled")
    preview_msg = send_idea_preview(bot, chat_id, issue_key, summary)

    if preview_msg:
        pending_ideas[preview_msg.message_id] = {
            "issue_key": issue_key,
            "structured": updated,
            "raw_idea": pending["raw_idea"],
            "kb_context_text": pending["kb_context_text"],
            "chat_id": chat_id,
        }
        log.info(f"PM1: Updated {issue_key} — awaiting approval (msg_id={preview_msg.message_id})")

    return preview_msg
