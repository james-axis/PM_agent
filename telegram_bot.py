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


def send_task_breakdown_preview(bot_instance, chat_id, epic_key, epic_title, tasks, total_sp, prd_url, prototype_url):
    """
    Send a task breakdown preview with task list and approval buttons.
    Returns the sent message (for tracking message_id).
    """
    epic_link = f"https://axiscrm.atlassian.net/browse/{epic_key}"

    # Build compact task list
    task_lines = []
    for i, t in enumerate(tasks, 1):
        sp = t.get("story_points", "?")
        task_lines.append(f"  {i}. {t.get('summary', '?')} — *{sp} SP*")

    task_list = "\n".join(task_lines)
    msg = (
        f"📝 *Task Breakdown* — [{epic_key}]({epic_link})\n"
        f"*{epic_title}*\n\n"
        f"{task_list}\n\n"
        f"*Total: {len(tasks)} tasks, {total_sp} SP*\n"
        f"📄 [PRD]({prd_url}) · 🎨 [Prototype]({prototype_url})"
    )

    # Telegram has a 4096 char limit — truncate if needed
    if len(msg) > 4000:
        msg = (
            f"📝 *Task Breakdown* — [{epic_key}]({epic_link})\n"
            f"*{epic_title}*\n\n"
            f"*{len(tasks)} tasks, {total_sp} SP total*\n"
            f"(Task list too long for preview — approve to create all)\n\n"
            f"📄 [PRD]({prd_url}) · 🎨 [Prototype]({prototype_url})"
        )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data="pm5_approve"),
        InlineKeyboardButton("🔄 Changes", callback_data="pm5_changes"),
        InlineKeyboardButton("⏸ Pending", callback_data="pm5_park"),
        InlineKeyboardButton("⛔ Reject", callback_data="pm5_reject"),
    )

    try:
        return bot_instance.send_message(
            chat_id, msg, parse_mode="Markdown",
            reply_markup=markup, disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Failed to send task breakdown preview: {e}")
        return None


def send_engineer_preview(bot_instance, chat_id, epic_key, epic_title, tasks, total_sp):
    """
    Send an engineer review preview with technical plans for each task.
    Returns the sent message (for tracking message_id).
    """
    epic_link = f"https://axiscrm.atlassian.net/browse/{epic_key}"

    # Build compact task list with technical plans
    task_lines = []
    for i, t in enumerate(tasks, 1):
        sp = t.get("confirmed_sp", t.get("story_points", "?"))
        plan_points = t.get("technical_plan", ["TBD"])
        plan_str = " → ".join(plan_points[:3])
        # Truncate long plans
        if len(plan_str) > 120:
            plan_str = plan_str[:117] + "..."
        task_lines.append(f"  {i}. *{t.get('key', '?')}* — {t.get('summary', '?')} (*{sp} SP*)\n       _{plan_str}_")

    task_list = "\n".join(task_lines)
    msg = (
        f"🔧 *Engineer Review* — [{epic_key}]({epic_link})\n"
        f"*{epic_title}*\n\n"
        f"{task_list}\n\n"
        f"*Total: {len(tasks)} tasks, {total_sp} SP*"
    )

    # Telegram 4096 char limit
    if len(msg) > 4000:
        msg = (
            f"🔧 *Engineer Review* — [{epic_key}]({epic_link})\n"
            f"*{epic_title}*\n\n"
            f"*{len(tasks)} tasks, {total_sp} SP total*\n"
            f"(Full plans too long for preview — approve to update all tasks)\n"
        )

    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data="pm6_approve"),
        InlineKeyboardButton("🔄 Changes", callback_data="pm6_changes"),
        InlineKeyboardButton("⏸ Pending", callback_data="pm6_park"),
        InlineKeyboardButton("⛔ Reject", callback_data="pm6_reject"),
    )

    try:
        return bot_instance.send_message(
            chat_id, msg, parse_mode="Markdown",
            reply_markup=markup, disable_web_page_preview=True,
        )
    except Exception as e:
        log.error(f"Failed to send engineer preview: {e}")
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
            "📦 *Epic* — Auto-created in AX on prototype approval\n"
            "📝 *Tasks* — Auto-broken down on Epic approval\n"
            "🔧 *Engineer* — Auto-fills technical plans on task approval\n\n"
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
            from pending_store import park_item, store_data_for_stage
            pending = pending_ideas.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                key = pending.get("issue_key", "?")
                park_item(key, "pm1", store_data_for_stage("pm1", pending))
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
            from pending_store import park_item, store_data_for_stage
            pending = pending_prds.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                key = pending.get("issue_key", "?")
                park_item(key, "pm2", store_data_for_stage("pm2", pending))
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
            from pending_store import park_item, store_data_for_stage
            pending = pending_prototypes.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                key = pending.get("issue_key", "?")
                park_item(key, "pm3", store_data_for_stage("pm3", pending))
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
            from pending_store import park_item, store_data_for_stage
            pending = pending_epics.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                key = pending.get("issue_key", "?")
                park_item(key, "pm4", store_data_for_stage("pm4", pending))
                bot.send_message(chat_id, f"⏸ {key} — Epic parked. Use /pending to resume.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("pm5_"))
    def handle_pm5_callback(call):
        save_chat_id(call.message.chat.id)
        action = call.data
        message_id = call.message.message_id
        chat_id = call.message.chat.id

        # Answer callback immediately to prevent timeout
        bot.answer_callback_query(call.id)

        from pm5_tasks import approve_task_breakdown, reject_task_breakdown, start_task_changes

        if action == "pm5_approve":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = approve_task_breakdown(message_id, bot)
            if result:
                bot.send_message(chat_id, result, parse_mode="Markdown", disable_web_page_preview=True)

        elif action == "pm5_changes":
            success = start_task_changes(message_id, chat_id, bot)
            if success:
                user_state[chat_id] = {"mode": "awaiting_task_changes", "preview_message_id": message_id}
                try:
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
                except Exception:
                    pass

        elif action == "pm5_reject":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = reject_task_breakdown(message_id)
            bot.send_message(chat_id, result, parse_mode="Markdown")

        elif action == "pm5_park":
            from pm5_tasks import pending_task_breakdowns
            from pending_store import park_item, store_data_for_stage
            pending = pending_task_breakdowns.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                key = pending.get("issue_key", "?")
                park_item(key, "pm5", store_data_for_stage("pm5", pending))
                bot.send_message(chat_id, f"⏸ {key} — Task breakdown parked. Use /pending to resume.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("pm6_"))
    def handle_pm6_callback(call):
        save_chat_id(call.message.chat.id)
        action = call.data
        message_id = call.message.message_id
        chat_id = call.message.chat.id

        bot.answer_callback_query(call.id)

        from pm6_engineer import approve_engineer_review, reject_engineer_review, start_engineer_changes

        if action == "pm6_approve":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = approve_engineer_review(message_id, bot)
            if result:
                bot.send_message(chat_id, result, parse_mode="Markdown", disable_web_page_preview=True)

        elif action == "pm6_changes":
            success = start_engineer_changes(message_id, chat_id, bot)
            if success:
                user_state[chat_id] = {"mode": "awaiting_engineer_changes", "preview_message_id": message_id}
                try:
                    bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
                except Exception:
                    pass

        elif action == "pm6_reject":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            result = reject_engineer_review(message_id)
            bot.send_message(chat_id, result, parse_mode="Markdown")

        elif action == "pm6_park":
            from pm6_engineer import pending_engineer_reviews
            from pending_store import park_item, store_data_for_stage
            pending = pending_engineer_reviews.pop(message_id, None)
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            if pending:
                key = pending.get("issue_key", "?")
                park_item(key, "pm6", store_data_for_stage("pm6", pending))
                bot.send_message(chat_id, f"⏸ {key} — Engineer review parked. Use /pending to resume.")

    @bot.callback_query_handler(func=lambda call: call.data.startswith("resume_"))
    def handle_resume_callback(call):
        save_chat_id(call.message.chat.id)
        bot.answer_callback_query(call.id)

        issue_key = call.data.replace("resume_", "")
        chat_id = call.message.chat.id

        # Remove the /pending list message buttons
        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass

        from pending_store import unpark_item, reconstruct_pending
        unparked = unpark_item(issue_key)
        if not unparked:
            bot.send_message(chat_id, f"❌ {issue_key} not found in pending list.")
            return

        stage = unparked["stage"]
        stored_data = unparked["data"]

        stage_labels = {"pm1": "💡 Idea", "pm2": "📋 PRD", "pm3": "🎨 Prototype", "pm4": "📦 Epic", "pm5": "📝 Tasks", "pm6": "🔧 Engineer"}
        bot.send_message(chat_id, f"▶️ Resuming {stage_labels.get(stage, stage)} for {issue_key}...")

        # Fetch issue summary from Jira
        from jira_client import get_issue
        issue = get_issue(issue_key)
        summary = issue["fields"]["summary"] if issue else stored_data.get("summary", issue_key)

        # Reconstruct full pending dict from stored data + live sources
        pending = reconstruct_pending(stage, issue_key, summary, stored_data, chat_id)

        # Re-send preview and store in the stage's pending dict
        if stage == "pm1":
            preview_msg = send_idea_preview(bot, chat_id, issue_key, summary)
            if preview_msg:
                from pm1_idea_intake import pending_ideas
                pending_ideas[preview_msg.message_id] = pending

        elif stage == "pm2":
            web_url = stored_data.get("web_url", "")
            page_id = stored_data.get("page_id", "")
            preview_msg = send_prd_preview(bot, chat_id, issue_key, summary, page_id, web_url)
            if preview_msg:
                from pm2_prd import pending_prds
                pending_prds[preview_msg.message_id] = pending

        elif stage == "pm3":
            prototype_url = stored_data.get("prototype_url", "")
            preview_msg = send_prototype_preview(bot, chat_id, issue_key, summary, prototype_url)
            if preview_msg:
                from pm3_prototype import pending_prototypes
                pending_prototypes[preview_msg.message_id] = pending

        elif stage == "pm4":
            epic_title = stored_data.get("epic_title", summary)
            epic_summary = stored_data.get("epic_summary", "")
            prd_web_url = stored_data.get("prd_web_url", "")
            prototype_url = stored_data.get("prototype_url", "")
            preview_msg = send_epic_preview(bot, chat_id, issue_key, epic_title, epic_summary, prd_web_url, prototype_url)
            if preview_msg:
                from pm4_epic import pending_epics
                pending_epics[preview_msg.message_id] = pending

        elif stage == "pm5":
            epic_key = stored_data.get("epic_key", "")
            epic_title = stored_data.get("epic_title", summary)
            tasks = pending.get("tasks", [])
            total_sp = sum(t.get("story_points", 0) for t in tasks)
            prd_web_url = stored_data.get("prd_web_url", "")
            prototype_url = stored_data.get("prototype_url", "")
            preview_msg = send_task_breakdown_preview(bot, chat_id, epic_key, epic_title, tasks, total_sp, prd_web_url, prototype_url)
            if preview_msg:
                from pm5_tasks import pending_task_breakdowns
                pending_task_breakdowns[preview_msg.message_id] = pending

        elif stage == "pm6":
            epic_key = stored_data.get("epic_key", "")
            epic_title = stored_data.get("epic_title", summary)
            tasks = pending.get("tasks", [])
            total_sp = sum(t.get("confirmed_sp", t.get("story_points", 0)) for t in tasks)
            preview_msg = send_engineer_preview(bot, chat_id, epic_key, epic_title, tasks, total_sp)
            if preview_msg:
                from pm6_engineer import pending_engineer_reviews
                pending_engineer_reviews[preview_msg.message_id] = pending

        else:
            bot.send_message(chat_id, f"❌ Unknown stage '{stage}' for {issue_key}.")

    @bot.message_handler(commands=["pending"])
    def handle_pending(message):
        save_chat_id(message.chat.id)
        chat_id = message.chat.id

        bot.send_message(chat_id, "🔍 Checking for parked items...")

        from pending_store import list_parked
        items = list_parked()

        if not items:
            bot.send_message(chat_id, "✨ No pending items. Everything is clear!")
            return

        stage_labels = {"pm1": "💡 Idea", "pm2": "📋 PRD", "pm3": "🎨 Prototype", "pm4": "📦 Epic", "pm5": "📝 Tasks", "pm6": "🔧 Engineer"}

        lines = ["*Pending Items:*\n"]
        markup = InlineKeyboardMarkup(row_width=1)

        for item in items:
            issue_key = item["issue_key"]
            stage = item["stage"]
            summary = item["summary"]
            label = stage_labels.get(stage, f"⏸ {stage}")
            jira_link = f"https://axiscrm.atlassian.net/browse/{issue_key}"
            lines.append(f"{label} — [{issue_key}]({jira_link}): {summary}")
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

        if state.get("mode") == "awaiting_task_changes":
            preview_msg_id = state.get("preview_message_id")
            user_state[chat_id] = {"mode": "idle"}

            if preview_msg_id:
                try:
                    bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                except Exception:
                    pass
                from pm5_tasks import apply_task_changes
                apply_task_changes(preview_msg_id, text, chat_id, bot)
            else:
                bot.send_message(chat_id, "❌ Lost track of which task breakdown to update.")
            return

        if state.get("mode") == "awaiting_engineer_changes":
            preview_msg_id = state.get("preview_message_id")
            user_state[chat_id] = {"mode": "idle"}

            if preview_msg_id:
                try:
                    bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                except Exception:
                    pass
                from pm6_engineer import apply_engineer_changes
                apply_engineer_changes(preview_msg_id, text, chat_id, bot)
            else:
                bot.send_message(chat_id, "❌ Lost track of which engineer review to update.")
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
            elif state.get("mode") == "awaiting_task_changes":
                preview_msg_id = state.get("preview_message_id")
                user_state[chat_id] = {"mode": "idle"}
                if preview_msg_id:
                    try:
                        bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                    except Exception:
                        pass
                    from pm5_tasks import apply_task_changes
                    apply_task_changes(preview_msg_id, text, chat_id, bot)
                else:
                    bot.send_message(chat_id, "❌ Lost track of which task breakdown to update.")
            elif state.get("mode") == "awaiting_engineer_changes":
                preview_msg_id = state.get("preview_message_id")
                user_state[chat_id] = {"mode": "idle"}
                if preview_msg_id:
                    try:
                        bot.edit_message_reply_markup(chat_id, preview_msg_id, reply_markup=None)
                    except Exception:
                        pass
                    from pm6_engineer import apply_engineer_changes
                    apply_engineer_changes(preview_msg_id, text, chat_id, bot)
                else:
                    bot.send_message(chat_id, "❌ Lost track of which engineer review to update.")
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
