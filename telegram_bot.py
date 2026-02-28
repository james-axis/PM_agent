"""
PM Agent — Telegram Bot
Handles /idea command, inline approval buttons, and conversation state.
"""

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, log

bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN) if TELEGRAM_BOT_TOKEN else None

# Conversation state per chat_id
# Modes: "idle", "awaiting_changes"
user_state = {}


def save_chat_id(chat_id):
    """Auto-capture chat ID for proactive messaging."""
    import config
    if not config.TELEGRAM_CHAT_ID:
        config.TELEGRAM_CHAT_ID = str(chat_id)
        log.info(f"Telegram chat ID captured: {config.TELEGRAM_CHAT_ID}")


def send_idea_preview(bot_instance, chat_id, structured):
    """
    Send a formatted idea preview with inline approval buttons.
    Returns the sent message (for tracking message_id).
    """
    summary = structured.get("summary", "Untitled")
    description = structured.get("description", "No description")

    # Truncate description for Telegram (keep it readable)
    if len(description) > 800:
        description = description[:800] + "..."

    init_module = structured.get("initiative_module", "—")
    init_stage = structured.get("initiative_stage", "—")
    init_scope = structured.get("initiative_scope", "—")
    customer = structured.get("customer_segment", "—")
    alignment = structured.get("strategic_alignment", "—")
    modules = structured.get("affected_modules", [])
    flags = structured.get("flags", [])

    modules_str = ", ".join(modules) if modules else "—"
    flags_str = "\n".join(f"  ⚠️ {f}" for f in flags) if flags else "  None"

    msg = (
        f"💡 *{summary}*\n\n"
        f"{description}\n\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"🏷 *Initiative:* {init_module} · {init_stage} · {init_scope}\n"
        f"👥 *Segment:* {customer}\n"
        f"🎯 *Alignment:* {alignment}\n"
        f"📦 *Modules:* {modules_str}\n"
        f"🚩 *Flags:*\n{flags_str}"
    )

    # Inline keyboard
    markup = InlineKeyboardMarkup(row_width=3)
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data="pm1_approve"),
        InlineKeyboardButton("🔄 Changes", callback_data="pm1_changes"),
        InlineKeyboardButton("⛔ Reject", callback_data="pm1_reject"),
    )

    try:
        return bot_instance.send_message(
            chat_id, msg, parse_mode="Markdown",
            reply_markup=markup, disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Failed to send preview: {e}")
        # Retry without markdown in case of formatting issues
        try:
            return bot_instance.send_message(
                chat_id, msg.replace("*", ""),
                reply_markup=markup, disable_web_page_preview=True,
            )
        except Exception as e2:
            log.error(f"Failed to send preview (retry): {e2}")
            return None


def register_handlers():
    """Register all bot command and callback handlers."""
    if not bot:
        return

    from pm1_idea_intake import (
        process_idea, approve_idea, reject_idea,
        start_changes, apply_idea_changes,
    )
    from voice import transcribe_voice

    @bot.message_handler(commands=["start", "help"])
    def handle_help(message):
        save_chat_id(message.chat.id)
        bot.reply_to(message,
            "👋 *PM Agent*\n\n"
            "💡 */idea* — Submit a product idea\n"
            "   Send text or a voice note. AI enriches it with KB context, you approve before it hits Jira.\n\n"
            "Send `/idea` then describe your idea via text or voice.",
            parse_mode="Markdown",
        )

    @bot.message_handler(commands=["idea"])
    def handle_idea(message):
        save_chat_id(message.chat.id)
        # Extract idea text after /idea command
        raw_text = message.text.strip()
        if raw_text.lower() == "/idea":
            user_state[message.chat.id] = {"mode": "awaiting_idea"}
            bot.reply_to(message, "💡 Send me your idea — type it out or send a voice note.")
            return

        # Strip the /idea prefix
        idea_text = raw_text[5:].strip()  # Remove "/idea"
        if not idea_text:
            user_state[message.chat.id] = {"mode": "awaiting_idea"}
            bot.reply_to(message, "💡 Send me your idea — type it out or send a voice note.")
            return

        user_state[message.chat.id] = {"mode": "idle"}
        process_idea(idea_text, message.chat.id, bot)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("pm1_"))
    def handle_callback(call):
        save_chat_id(call.message.chat.id)
        action = call.data
        message_id = call.message.message_id
        chat_id = call.message.chat.id

        if action == "pm1_approve":
            result = approve_idea(message_id, bot)
            # Remove inline buttons from preview
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(chat_id, result, parse_mode="Markdown", disable_web_page_preview=True)

        elif action == "pm1_changes":
            success = start_changes(message_id, chat_id, bot)
            if success:
                user_state[chat_id] = {"mode": "awaiting_changes", "preview_message_id": message_id}
            bot.answer_callback_query(call.id)

        elif action == "pm1_reject":
            result = reject_idea(message_id)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            bot.send_message(chat_id, result, parse_mode="Markdown")

    @bot.message_handler(content_types=["text"])
    def handle_text(message):
        save_chat_id(message.chat.id)
        chat_id = message.chat.id
        state = user_state.get(chat_id, {"mode": "idle"})
        text = message.text.strip()

        # Unknown command
        if text.startswith("/"):
            bot.reply_to(message, "Unknown command. Try /idea or /help")
            return

        # Awaiting idea text (user sent /idea with no text)
        if state.get("mode") == "awaiting_idea":
            user_state[chat_id] = {"mode": "idle"}
            process_idea(text, chat_id, bot)
            return

        # Awaiting change instructions
        if state.get("mode") == "awaiting_changes":
            preview_msg_id = state.get("preview_message_id")
            user_state[chat_id] = {"mode": "idle"}

            if preview_msg_id:
                # Remove buttons from old preview
                try:
                    bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                except Exception:
                    pass
                apply_idea_changes(preview_msg_id, text, bot)
            else:
                bot.send_message(chat_id, "❌ Lost track of which idea to update. Try /idea again.")
            return

        # Default: treat as an idea
        process_idea(text, chat_id, bot)

    @bot.message_handler(content_types=["voice"])
    def handle_voice(message):
        save_chat_id(message.chat.id)
        chat_id = message.chat.id
        state = user_state.get(chat_id, {"mode": "idle"})

        try:
            bot.send_message(chat_id, "🎙 Transcribing your voice note...")
            file_info = bot.get_file(message.voice.file_id)
            downloaded = bot.download_file(file_info.file_path)
            tmp_path = f"/tmp/voice_{message.message_id}.ogg"
            with open(tmp_path, "wb") as f:
                f.write(downloaded)

            text = transcribe_voice(tmp_path)
            if not text:
                bot.send_message(chat_id, "❌ Couldn't transcribe the voice note. Try sending it as text.")
                return

            bot.send_message(chat_id, f"📝 Heard: _{text}_", parse_mode="Markdown")

            # Process based on current state
            if state.get("mode") == "awaiting_changes":
                preview_msg_id = state.get("preview_message_id")
                user_state[chat_id] = {"mode": "idle"}
                if preview_msg_id:
                    try:
                        bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                    except Exception:
                        pass
                    apply_idea_changes(preview_msg_id, text, bot)
                else:
                    bot.send_message(chat_id, "❌ Lost track of which idea to update. Try /idea again.")
            else:
                # Awaiting idea or idle — treat as new idea
                user_state[chat_id] = {"mode": "idle"}
                process_idea(text, chat_id, bot)

        except Exception as e:
            log.error(f"Voice handling error: {e}")
            bot.send_message(chat_id, f"❌ Error processing voice note: {e}")


def start_polling():
    """Start the Telegram bot with long polling."""
    if not bot:
        log.warning("Telegram bot not started — TELEGRAM_BOT_TOKEN not set.")
        return

    register_handlers()
    log.info("Telegram bot starting (polling)...")

    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=20)
    except Exception as e:
        log.error(f"Telegram bot crashed: {e}", exc_info=True)
