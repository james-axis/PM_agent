"""
PM Agent — PM1: Idea Intake Pipeline
Orchestrates: raw idea → KB context → AI enrichment → Telegram preview → approval → Jira creation.
"""

from config import STRATEGIC_INITIATIVES_ID, log
from confluence_client import fetch_knowledge_base, format_kb_for_prompt
from claude_client import enrich_idea, apply_changes
from jira_client import create_idea, add_comment


# In-memory store for pending ideas (keyed by message_id from Telegram)
# Format: {message_id: {"structured": dict, "raw_idea": str, "kb_context_text": str, "chat_id": int}}
pending_ideas = {}


def process_idea(raw_idea, chat_id, bot):
    """
    Full PM1 pipeline: text → KB fetch → Claude enrichment → Telegram preview.
    Sends preview with inline buttons. Actual Jira creation happens on approval.
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

    # Step 4: Delete status message and send preview with inline buttons
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_idea_preview(bot, chat_id, structured)

    # Step 5: Store in pending for callback handling
    if preview_msg:
        pending_ideas[preview_msg.message_id] = {
            "structured": structured,
            "raw_idea": raw_idea,
            "kb_context_text": kb_text,
            "chat_id": chat_id,
        }
        log.info(f"PM1: Idea preview sent, awaiting approval (msg_id={preview_msg.message_id})")


def approve_idea(message_id, bot):
    """
    Approve a pending idea: create in Jira, add PM2 stub comment.
    """
    pending = pending_ideas.pop(message_id, None)
    if not pending:
        return "❌ This idea has already been processed or expired."

    structured = pending["structured"]
    chat_id = pending["chat_id"]

    # Create in Jira
    issue_key = create_idea(structured, swimlane_id=STRATEGIC_INITIATIVES_ID)
    if not issue_key:
        # Put it back so they can retry
        pending_ideas[message_id] = pending
        return "❌ Failed to create idea in Jira. Try again."

    # Add PM2 stub comment
    add_comment(issue_key, "**PM1 Approved** — Idea enriched and created via PM Agent. Ready for PM2 processing.")

    # Build response
    summary = structured.get("summary", "Untitled")
    link = f"https://axiscrm.atlassian.net/jira/polaris/projects/AR/ideas/view/11184018?selectedIssue={issue_key}"

    init_module = structured.get("initiative_module", "?")
    init_stage = structured.get("initiative_stage", "?")
    init_scope = structured.get("initiative_scope", "?")

    log.info(f"PM1: Approved and created {issue_key}: {summary}")

    return (
        f"✅ *{issue_key}* — {summary}\n\n"
        f"🏊 Strategic Initiatives\n"
        f"🏷 {init_module} · {init_stage} · {init_scope}\n\n"
        f"[Open on board]({link})"
    )


def reject_idea(message_id):
    """Reject a pending idea — remove from pending."""
    pending = pending_ideas.pop(message_id, None)
    if not pending:
        return "❌ This idea has already been processed or expired."

    summary = pending["structured"].get("summary", "Untitled")
    log.info(f"PM1: Rejected idea: {summary}")
    return f"⛔ Rejected: _{summary}_"


def start_changes(message_id, chat_id, bot):
    """
    Begin the changes flow — prompt user for change instructions.
    Returns True if successfully entered changes mode.
    """
    pending = pending_ideas.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This idea has already been processed or expired.")
        return False

    bot.send_message(chat_id, "🔄 What would you like to change? Send your instructions.")
    return True


def apply_idea_changes(message_id, change_instructions, bot):
    """
    Apply changes to a pending idea and send updated preview.
    """
    from telegram_bot import send_idea_preview

    pending = pending_ideas.get(message_id)
    if not pending:
        return None

    chat_id = pending["chat_id"]
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

    # Remove old pending entry
    pending_ideas.pop(message_id, None)

    # Send updated preview
    preview_msg = send_idea_preview(bot, chat_id, updated)

    if preview_msg:
        pending_ideas[preview_msg.message_id] = {
            "structured": updated,
            "raw_idea": pending["raw_idea"],
            "kb_context_text": pending["kb_context_text"],
            "chat_id": chat_id,
        }
        log.info(f"PM1: Updated preview sent (msg_id={preview_msg.message_id})")

    return preview_msg
