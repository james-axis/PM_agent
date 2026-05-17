"""
PM Agent — PM1: Opportunity Intake Pipeline
Orchestrates: raw input → KB context → AI enrichment → Roadmap Triage card → Telegram notification.
No Jira ticket creation. No approval flow. Just straight to roadmap Triage.
"""

from config import log
from confluence_client import fetch_knowledge_base, format_kb_for_prompt
from claude_client import enrich_idea
from roadmap_client import add_to_triage


def process_idea(raw_idea, chat_id, bot, column="triage"):
    """
    Full PM1 pipeline: text → KB fetch → Claude enrichment → Roadmap card → Telegram confirmation.
    """

    # Step 1: Acknowledge
    status_msg = bot.send_message(chat_id, "🧠 Loading knowledge base...")

    # Step 2: Fetch KB
    kb_context = fetch_knowledge_base()
    if not kb_context:
        bot.edit_message_text("❌ Failed to load knowledge base. Check Confluence access.", chat_id, status_msg.message_id)
        return

    kb_text = format_kb_for_prompt(kb_context)
    bot.edit_message_text("🧠 Enriching your opportunity with AI...", chat_id, status_msg.message_id)

    # Step 3: AI enrichment
    structured = enrich_idea(raw_idea, kb_text)
    if not structured:
        bot.edit_message_text("❌ AI enrichment failed. Check Claude API key and logs.", chat_id, status_msg.message_id)
        return

    # Step 4: Add to custom roadmap
    summary = structured.get("summary", "Untitled")
    short_desc = structured.get("short_description", "")
    column_label = "Blue Sky" if column == "bluesky" else "Triage"
    bot.edit_message_text(f"📝 Adding to roadmap {column_label}...", chat_id, status_msg.message_id)

    ticket_id, card_id = add_to_triage(label=summary, sub=short_desc, column=column)
    if not ticket_id:
        bot.edit_message_text(f"❌ Failed to add to roadmap {column_label}. Check logs.", chat_id, status_msg.message_id)
        return

    # Step 5: Delete status message and send confirmation
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    roadmap_url = "https://product-roadmap-v10-production.up.railway.app/"
    desc_line = f"\n_{short_desc}_" if short_desc else ""
    bot.send_message(
        chat_id,
        f"🎯 *{ticket_id}* — {summary}{desc_line}\n\n"
        f"Added to [Roadmap {column_label}]({roadmap_url})",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )

    log.info(f"PM1: Created {ticket_id} on roadmap {column_label}: {summary}")
