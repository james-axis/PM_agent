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

# Parked items awaiting later review: {issue_key: {stage, data, chat_id, parked_at}}
parked_items = {}


def save_chat_id(chat_id):
    """Auto-capture chat ID for proactive messaging."""
    import config
    if not config.TELEGRAM_CHAT_ID:
        config.TELEGRAM_CHAT_ID = str(chat_id)
        log.info(f"Telegram chat ID captured: {config.TELEGRAM_CHAT_ID}")


def send_idea_preview(bot_instance, chat_id, issue_key, summary):
    """
    Send a hyperlinked ticket ID + summary with inline approval buttons.
    Returns the sent message (for tracking message_id).
    """
    link = f"https://axiscrm.atlassian.net/browse/{issue_key}"

    msg = f"💡 [{issue_key}]({link}) — {summary}"

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data="pm1_approve"),
        InlineKeyboardButton("🔄 Changes", callback_data="pm1_changes"),
        InlineKeyboardButton("⏸ Pending", callback_data="pm1_park"),
        InlineKeyboardButton("⛔ Reject", callback_data="pm1_reject"),
    )

    try:
        return bot_instance.send_message(
            chat_id, msg, parse_mode="Markdown",
            reply_markup=markup, disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Failed to send preview: {e}")
        return None


def send_prd_preview(bot_instance, chat_id, issue_key, summary, page_id, web_url):
    """
    Send a PRD preview with link to Confluence page and inline approval buttons.
    Returns the sent message (for tracking message_id).
    """
    msg = (
        f"📋 [{issue_key}](https://axiscrm.atlassian.net/browse/{issue_key}) — PRD: {summary}\n"
        f"📄 [Open PRD in Confluence]({web_url})"
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data="pm2_approve"),
        InlineKeyboardButton("🔄 Changes", callback_data="pm2_changes"),
        InlineKeyboardButton("⏸ Pending", callback_data="pm2_park"),
        InlineKeyboardButton("⛔ Reject", callback_data="pm2_reject"),
    )

    try:
        return bot_instance.send_message(
            chat_id, msg, parse_mode="Markdown",
            reply_markup=markup, disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Failed to send PRD preview: {e}")
        return None


def send_prototype_preview(bot_instance, chat_id, issue_key, summary, prototype_url):
    """
    Send a prototype preview with link to GitHub Pages and inline approval buttons.
    Returns the sent message (for tracking message_id).
    """
    msg = f"🎨 [{issue_key}]({prototype_url}) — Prototype: {summary}"

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data="pm3_approve"),
        InlineKeyboardButton("🔄 Changes", callback_data="pm3_changes"),
        InlineKeyboardButton("⏸ Pending", callback_data="pm3_park"),
        InlineKeyboardButton("⛔ Reject", callback_data="pm3_reject"),
    )

    try:
        return bot_instance.send_message(
            chat_id, msg, parse_mode="Markdown",
            reply_markup=markup, disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Failed to send prototype preview: {e}")
        return None


def send_epic_preview(bot_instance, chat_id, issue_key, epic_title, epic_summary, prd_url, prototype_url):
    """
    Send an Epic preview with title, summary, and links for approval.
    Returns the sent message (for tracking message_id).
    """
    jira_link = f"https://axiscrm.atlassian.net/browse/{issue_key}"
    msg = (
        f"📦 *Epic Preview* — [{issue_key}]({jira_link})\n\n"
        f"*Title:* {epic_title}\n\n"
        f"*Summary:* {epic_summary}\n\n"
        f"📄 [PRD]({prd_url}) · 🎨 [Prototype]({prototype_url})"
    )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data="pm4_approve"),
        InlineKeyboardButton("🔄 Changes", callback_data="pm4_changes"),
        InlineKeyboardButton("⏸ Pending", callback_data="pm4_park"),
        InlineKeyboardButton("⛔ Reject", callback_data="pm4_reject"),
    )

    try:
        return bot_instance.send_message(
            chat_id, msg, parse_mode="Markdown",
            reply_markup=markup, disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Failed to send epic preview: {e}")
        return None


def register_handlers():
    """Register all bot command and callback handlers."""
    if not bot:
        return

    from pm1_idea_intake import (
        process_idea, approve_idea, reject_idea,
        start_changes, apply_idea_changes,
    )
    from pm2_prd import (
        approve_prd, reject_prd,
        start_prd_changes, apply_prd_changes,
    )
    from pm3_prototype import (
        approve_prototype, reject_prototype,
        start_prototype_changes, apply_prototype_changes,
    )
    from voice import transcribe_voice

    @bot.message_handler(commands=["start", "help"])
    def handle_help(message):
        save_chat_id(message.chat.id)
        bot.reply_to(message,
            "👋 *PM Agent*\n\n"
            "💡 */idea* — Submit a product idea\n"
            "📋 *PRD* — Auto-generated on idea approval\n"
            "🎨 *Prototype* — Auto-generated on PRD approval\n"
            "📦 *Epic* — Auto-created in AX on prototype approval\n\n"
            "⏸ */pending* — View & resume parked items\n\n"
            "At each step: ✅ Approve, 🔄 Changes, ⏸ Pending, or ⛔ Reject.\n"
            "Send text or voice notes at any stage.",
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
    def handle_pm1_callback(call):
        save_chat_id(call.message.chat.id)
        action = call.data
        message_id = call.message.message_id
        chat_id = call.message.chat.id

        # Answer callback immediately to prevent timeout
        bot.answer_callback_query(call.id)

        if action == "pm1_approve":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = approve_idea(message_id, bot)
            if result:
                bot.send_message(chat_id, result, parse_mode="Markdown", disable_web_page_preview=True)

        elif action == "pm1_changes":
            success = start_changes(message_id, chat_id, bot)
            if success:
                user_state[chat_id] = {"mode": "awaiting_changes", "preview_message_id": message_id}
                try:
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
                except Exception:
                    pass

        elif action == "pm1_reject":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = reject_idea(message_id)
            bot.send_message(chat_id, result, parse_mode="Markdown")

        elif action == "pm1_park":
            from pm1_idea_intake import pending_ideas
            pending = pending_ideas.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                import datetime
                key = pending.get("issue_key", "?")
                parked_items[key] = {"stage": "pm1", "data": pending, "chat_id": chat_id, "parked_at": datetime.datetime.now().isoformat()}
                bot.send_message(chat_id, f"⏸ {key} — Idea parked. Use /pending to resume.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("pm2_"))
    def handle_pm2_callback(call):
        save_chat_id(call.message.chat.id)
        action = call.data
        message_id = call.message.message_id
        chat_id = call.message.chat.id

        # Answer callback immediately to prevent timeout
        bot.answer_callback_query(call.id)

        if action == "pm2_approve":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = approve_prd(message_id, bot)
            if result:
                bot.send_message(chat_id, result, parse_mode="Markdown", disable_web_page_preview=True)

        elif action == "pm2_changes":
            success = start_prd_changes(message_id, chat_id, bot)
            if success:
                user_state[chat_id] = {"mode": "awaiting_prd_changes", "preview_message_id": message_id}
                try:
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
                except Exception:
                    pass

        elif action == "pm2_reject":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = reject_prd(message_id)
            bot.send_message(chat_id, result, parse_mode="Markdown")

        elif action == "pm2_park":
            from pm2_prd import pending_prds
            pending = pending_prds.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                import datetime
                key = pending.get("issue_key", "?")
                parked_items[key] = {"stage": "pm2", "data": pending, "chat_id": chat_id, "parked_at": datetime.datetime.now().isoformat()}
                bot.send_message(chat_id, f"⏸ {key} — PRD parked. Use /pending to resume.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("pm3_"))
    def handle_pm3_callback(call):
        save_chat_id(call.message.chat.id)
        action = call.data
        message_id = call.message.message_id
        chat_id = call.message.chat.id

        # Answer callback immediately to prevent timeout
        bot.answer_callback_query(call.id)

        if action == "pm3_approve":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = approve_prototype(message_id, bot)
            if result:
                bot.send_message(chat_id, result, parse_mode="Markdown", disable_web_page_preview=True)

        elif action == "pm3_changes":
            success = start_prototype_changes(message_id, chat_id, bot)
            if success:
                user_state[chat_id] = {"mode": "awaiting_prototype_changes", "preview_message_id": message_id}
                try:
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
                except Exception:
                    pass

        elif action == "pm3_reject":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = reject_prototype(message_id)
            bot.send_message(chat_id, result, parse_mode="Markdown")

        elif action == "pm3_park":
            from pm3_prototype import pending_prototypes
            pending = pending_prototypes.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                import datetime
                key = pending.get("issue_key", "?")
                parked_items[key] = {"stage": "pm3", "data": pending, "chat_id": chat_id, "parked_at": datetime.datetime.now().isoformat()}
                bot.send_message(chat_id, f"⏸ {key} — Prototype parked. Use /pending to resume.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("pm4_"))
    def handle_pm4_callback(call):
        save_chat_id(call.message.chat.id)
        action = call.data
        message_id = call.message.message_id
        chat_id = call.message.chat.id

        # Answer callback immediately to prevent timeout
        bot.answer_callback_query(call.id)

        from pm4_epic import approve_epic, reject_epic, start_epic_changes

        if action == "pm4_approve":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = approve_epic(message_id, bot)
            if result:
                bot.send_message(chat_id, result, parse_mode="Markdown", disable_web_page_preview=True)

        elif action == "pm4_changes":
            success = start_epic_changes(message_id, chat_id, bot)
            if success:
                user_state[chat_id] = {"mode": "awaiting_epic_changes", "preview_message_id": message_id}
                try:
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
                except Exception:
                    pass

        elif action == "pm4_reject":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = reject_epic(message_id)
            bot.send_message(chat_id, result, parse_mode="Markdown")

        elif action == "pm4_park":
            from pm4_epic import pending_epics
            pending = pending_epics.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                import datetime
                key = pending.get("issue_key", "?")
                parked_items[key] = {"stage": "pm4", "data": pending, "chat_id": chat_id, "parked_at": datetime.datetime.now().isoformat()}
                bot.send_message(chat_id, f"⏸ {key} — Epic parked. Use /pending to resume.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("resume_"))
    def handle_resume_callback(call):
        save_chat_id(call.message.chat.id)
        bot.answer_callback_query(call.id)

        issue_key = call.data.replace("resume_", "")
        chat_id = call.message.chat.id

        parked = parked_items.pop(issue_key, None)
        if not parked:
            bot.send_message(chat_id, f"❌ {issue_key} not found in pending list.")
            return

        # Remove the /pending list message buttons
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass

        stage = parked["stage"]
        data = parked["data"]
        summary = data.get("summary", "")

        stage_labels = {"pm1": "Idea", "pm2": "PRD", "pm3": "Prototype", "pm4": "Epic"}
        bot.send_message(chat_id, f"▶️ Resuming {stage_labels.get(stage, stage)} for {issue_key}...")

        if stage == "pm1":
            preview_msg = send_idea_preview(bot, chat_id, issue_key, summary)
            if preview_msg:
                from pm1_idea_intake import pending_ideas
                pending_ideas[preview_msg.message_id] = data

        elif stage == "pm2":
            web_url = data.get("web_url", "")
            page_id = data.get("page_id", "")
            preview_msg = send_prd_preview(bot, chat_id, issue_key, summary, page_id, web_url)
            if preview_msg:
                from pm2_prd import pending_prds
                pending_prds[preview_msg.message_id] = data

        elif stage == "pm3":
            prototype_url = data.get("prototype_url", "")
            preview_msg = send_prototype_preview(bot, chat_id, issue_key, summary, prototype_url)
            if preview_msg:
                from pm3_prototype import pending_prototypes
                pending_prototypes[preview_msg.message_id] = data

        elif stage == "pm4":
            epic_title = data.get("epic_title", summary)
            epic_summary = data.get("epic_summary", "")
            prd_web_url = data.get("prd_web_url", "")
            prototype_url = data.get("prototype_url", "")
            preview_msg = send_epic_preview(bot, chat_id, issue_key, epic_title, epic_summary, prd_web_url, prototype_url)
            if preview_msg:
                from pm4_epic import pending_epics
                pending_epics[preview_msg.message_id] = data

    @bot.message_handler(commands=["pending"])
    def handle_pending(message):
        save_chat_id(message.chat.id)
        chat_id = message.chat.id

        if not parked_items:
            bot.send_message(chat_id, "✨ No pending items. Everything is clear!")
            return

        stage_labels = {"pm1": "💡 Idea", "pm2": "📋 PRD", "pm3": "🎨 Prototype", "pm4": "📦 Epic"}

        lines = ["*Pending Items:*\n"]
        markup = InlineKeyboardMarkup(row_width=1)

        for issue_key, item in parked_items.items():
            stage = item["stage"]
            summary = item["data"].get("summary", "")
            label = stage_labels.get(stage, stage)
            lines.append(f"{label} — *{issue_key}*: {summary}")
            markup.add(InlineKeyboardButton(
                f"▶️ Resume {issue_key} ({label})",
                callback_data=f"resume_{issue_key}",
            ))

        bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)

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

        # Awaiting inspiration for PRD (PM2)
        if state.get("mode") == "awaiting_inspiration":
            user_state[chat_id] = {"mode": "idle"}
            issue_key = state.get("issue_key")
            summary = state.get("summary")
            inspiration = "" if text.strip().lower() == "skip" else text
            from pm2_prd import process_prd
            process_prd(issue_key, summary, chat_id, bot, inspiration=inspiration)
            return

        # Awaiting change instructions (PM1)
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

        # Awaiting PRD change instructions (PM2)
        if state.get("mode") == "awaiting_prd_changes":
            preview_msg_id = state.get("preview_message_id")
            user_state[chat_id] = {"mode": "idle"}

            if preview_msg_id:
                try:
                    bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                except Exception:
                    pass
                apply_prd_changes(preview_msg_id, text, bot)
            else:
                bot.send_message(chat_id, "❌ Lost track of which PRD to update.")
            return

        # Awaiting prototype change instructions (PM3)
        if state.get("mode") == "awaiting_prototype_changes":
            preview_msg_id = state.get("preview_message_id")
            user_state[chat_id] = {"mode": "idle"}

            if preview_msg_id:
                try:
                    bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                except Exception:
                    pass
                apply_prototype_changes(preview_msg_id, text, bot)
            else:
                bot.send_message(chat_id, "❌ Lost track of which prototype to update.")
            return

        # Awaiting epic change instructions (PM4)
        if state.get("mode") == "awaiting_epic_changes":
            preview_msg_id = state.get("preview_message_id")
            user_state[chat_id] = {"mode": "idle"}

            if preview_msg_id:
                try:
                    bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                except Exception:
                    pass
                from pm4_epic import apply_epic_changes
                apply_epic_changes(preview_msg_id, text, chat_id, bot)
            else:
                bot.send_message(chat_id, "❌ Lost track of which Epic to update.")
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
            elif state.get("mode") == "awaiting_prd_changes":
                preview_msg_id = state.get("preview_message_id")
                user_state[chat_id] = {"mode": "idle"}
                if preview_msg_id:
                    try:
                        bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                    except Exception:
                        pass
                    apply_prd_changes(preview_msg_id, text, bot)
                else:
                    bot.send_message(chat_id, "❌ Lost track of which PRD to update.")
            elif state.get("mode") == "awaiting_prototype_changes":
                preview_msg_id = state.get("preview_message_id")
                user_state[chat_id] = {"mode": "idle"}
                if preview_msg_id:
                    try:
                        bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                    except Exception:
                        pass
                    apply_prototype_changes(preview_msg_id, text, bot)
                else:
                    bot.send_message(chat_id, "❌ Lost track of which prototype to update.")
            elif state.get("mode") == "awaiting_epic_changes":
                preview_msg_id = state.get("preview_message_id")
                user_state[chat_id] = {"mode": "idle"}
                if preview_msg_id:
                    try:
                        bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                    except Exception:
                        pass
                    from pm4_epic import apply_epic_changes
                    apply_epic_changes(preview_msg_id, text, chat_id, bot)
                else:
                    bot.send_message(chat_id, "❌ Lost track of which Epic to update.")
            elif state.get("mode") == "awaiting_inspiration":
                user_state[chat_id] = {"mode": "idle"}
                issue_key = state.get("issue_key")
                summary = state.get("summary")
                inspiration = "" if text.strip().lower() == "skip" else text
                from pm2_prd import process_prd
                process_prd(issue_key, summary, chat_id, bot, inspiration=inspiration)
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
