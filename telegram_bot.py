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


def send_telegram(msg, parse_mode="Markdown"):
    """Send a proactive message to the configured chat (for scheduled jobs)."""
    import config
    chat_id = config.TELEGRAM_CHAT_ID
    if not bot or not chat_id:
        log.warning("send_telegram: bot or chat_id not available.")
        return None
    try:
        return bot.send_message(int(chat_id), msg, parse_mode=parse_mode, disable_web_page_preview=True)
    except Exception as e:
        log.error(f"send_telegram failed: {e}")
        return None


def save_chat_id(chat_id):
    """Auto-capture chat ID for proactive messaging."""
    import config
    if not config.TELEGRAM_CHAT_ID:
        config.TELEGRAM_CHAT_ID = str(chat_id)
        log.info(f"Telegram chat ID captured: {config.TELEGRAM_CHAT_ID}")


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
    proto_line = f" · 🎨 [Prototype]({prototype_url})" if prototype_url and prototype_url != "N/A" else ""
    msg = (
        f"📦 *Epic Preview* — [{issue_key}]({jira_link})\n\n"
        f"*Title:* {epic_title}\n\n"
        f"*Summary:* {epic_summary}\n\n"
        f"📄 [PRD]({prd_url}){proto_line}"
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


def send_task_breakdown_preview(bot_instance, chat_id, epic_key, epic_title, tasks):
    """
    Send a task breakdown preview with approval buttons.
    Returns the sent message (for tracking message_id).
    """
    epic_link = f"https://axiscrm.atlassian.net/browse/{epic_key}"

    task_lines = []
    for i, t in enumerate(tasks, 1):
        title = t.get("title", "Untitled")
        summary = t.get("summary", "")
        task_lines.append(f"*{i}. {title}*\n  {summary}")

    tasks_text = "\n\n".join(task_lines)

    msg = (
        f"📋 *Task Breakdown* — [{epic_key}]({epic_link})\n"
        f"*{epic_title}*\n\n"
        f"{tasks_text}\n\n"
        f"_{len(tasks)} tasks total_"
    )

    # Truncate if needed
    if len(msg) > 4000:
        short_lines = []
        for i, t in enumerate(tasks, 1):
            short_lines.append(f"{i}. {t.get('title', 'Untitled')}")
        msg = (
            f"📋 *Task Breakdown* — [{epic_key}]({epic_link})\n"
            f"*{epic_title}*\n\n"
            + "\n".join(short_lines) +
            f"\n\n_{len(tasks)} tasks — approve to create_"
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

    from pm1_idea_intake import process_idea
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
            "*Commands:*\n"
            "💡 /opportunity — Submit a product opportunity\n"
            "⚡ /actions — Parked items, ticket actions, pipeline inject\n"
            "📝 /update — Edit an existing ticket\n"
            "⏳ /pending — Show pending approvals\n\n"
            "*Scheduled jobs (also manual):*\n"
            "🔄 /sprint\\_turnover — Close sprint, carry over, start next\n"
            "🔍 /voa — Run Voice of Adviser monitor\n\n"
            "*Automated schedule:*\n"
            "• Mon 6am — Sprint turnover",
            parse_mode="Markdown",
        )

    @bot.message_handler(commands=["opportunity"])
    def handle_opportunity(message):
        save_chat_id(message.chat.id)
        raw_text = message.text.strip()
        if raw_text.lower() == "/opportunity":
            user_state[message.chat.id] = {"mode": "awaiting_idea"}
            bot.reply_to(message, "💡 Send me your opportunity — type it out or send a voice note.")
            return

        idea_text = raw_text[len("/opportunity"):].strip()
        if not idea_text:
            user_state[message.chat.id] = {"mode": "awaiting_idea"}
            bot.reply_to(message, "💡 Send me your opportunity — type it out or send a voice note.")
            return

        # Ask which column
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📋 Triage", callback_data="col_triage"),
            InlineKeyboardButton("🌤 Blue Sky", callback_data="col_bluesky"),
        )
        col_msg = bot.send_message(
            message.chat.id,
            "Where should this land?",
            reply_markup=markup,
        )
        user_state[message.chat.id] = {
            "mode": "awaiting_column",
            "idea_text": idea_text,
            "col_message_id": col_msg.message_id,
        }

    @bot.callback_query_handler(func=lambda call: call.data.startswith("col_"))
    def handle_column_callback(call):
        save_chat_id(call.message.chat.id)
        chat_id = call.message.chat.id
        message_id = call.message.message_id

        bot.answer_callback_query(call.id)
        try:
            bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
        except Exception:
            pass

        state = user_state.get(chat_id, {})
        idea_text = state.get("idea_text", "")
        if not idea_text:
            bot.send_message(chat_id, "❌ Lost the opportunity text. Try /opportunity again.")
            return

        column = "bluesky" if call.data == "col_bluesky" else "triage"
        column_label = "Blue Sky" if column == "bluesky" else "Triage"
        log.info(f"PM1: Column selected — {column_label} (callback: {call.data})")

        try:
            bot.delete_message(chat_id, message_id)
        except Exception:
            pass

        user_state[chat_id] = {"mode": "idle"}
        process_idea(idea_text, chat_id, bot, column=column)

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
            else:
                # Track that this chat is awaiting prototype decision
                from pm2_prd import set_proto_decision_pending
                set_proto_decision_pending(chat_id, message_id)

        elif action == "pm2_proto_yes":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            from pm2_prd import proceed_with_prototype
            proceed_with_prototype(chat_id, bot)

        elif action == "pm2_proto_no":
            try:
                bot.edit_message_reply_markup(chat_id, message_id, reply_markup=None)
            except Exception:
                pass
            from pm2_prd import skip_prototype
            skip_prototype(chat_id, bot)

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
                bot.send_message(chat_id, f"⏸ {key} — PRD parked. Use /actions → Parked to resume.")

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
                bot.send_message(chat_id, f"⏸ {key} — Prototype parked. Use /actions → Parked to resume.")

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
                bot.send_message(chat_id, f"⏸ {key} — Epic parked. Use /actions → Parked to resume.")

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
                bot.send_message(chat_id, f"⏸ {key} — Spike plan parked. Use /actions → Parked to resume.")

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
                bot.send_message(chat_id, f"⏸ {key} — Engineer review parked. Use /actions → Parked to resume.")

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

        stage_labels = {"pm1": "💡 Idea", "pm2": "📋 PRD", "pm3": "🎨 Prototype", "pm4": "📦 Epic", "pm5": "📝 Spike", "pm6": "🔧 Engineer"}
        bot.send_message(chat_id, f"▶️ Resuming {stage_labels.get(stage, stage)} for {issue_key}...")

        # Fetch issue summary from Jira
        from jira_client import get_issue
        issue = get_issue(issue_key)
        summary = issue["fields"]["summary"] if issue else stored_data.get("summary", issue_key)

        # Reconstruct full pending dict from stored data + live sources
        pending = reconstruct_pending(stage, issue_key, summary, stored_data, chat_id)

        # Re-send preview and store in the stage's pending dict
        if stage == "pm2":
            web_url = stored_data.get("web_url", "")
            page_id = stored_data.get("page_id", "")
            if not web_url:
                # Injected — trigger PRD generation from scratch
                bot.send_message(chat_id, f"💡 No existing PRD found — generating from scratch...")
                from pm2_prd import process_prd
                process_prd(issue_key, summary, chat_id, bot)
            else:
                preview_msg = send_prd_preview(bot, chat_id, issue_key, summary, page_id, web_url)
                if preview_msg:
                    from pm2_prd import pending_prds
                    pending_prds[preview_msg.message_id] = pending

        elif stage == "pm3":
            prototype_url = stored_data.get("prototype_url", "")
            if not prototype_url:
                # Injected — trigger prototype generation
                prd_page_id = stored_data.get("prd_page_id", "")
                prd_web_url = stored_data.get("prd_web_url", "")
                from pm3_prototype import process_prototype
                process_prototype(issue_key, summary, prd_page_id, prd_web_url, chat_id, bot)
            else:
                preview_msg = send_prototype_preview(bot, chat_id, issue_key, summary, prototype_url)
                if preview_msg:
                    from pm3_prototype import pending_prototypes
                    pending_prototypes[preview_msg.message_id] = pending

        elif stage == "pm4":
            epic_summary = stored_data.get("epic_summary", "")
            if not epic_summary:
                # Injected — trigger Epic generation
                prd_page_id = stored_data.get("prd_page_id", "")
                prd_web_url = stored_data.get("prd_web_url", "")
                prototype_url = stored_data.get("prototype_url", "") or "N/A"
                from pm4_epic import process_epic
                process_epic(issue_key, summary, prd_page_id, prd_web_url, prototype_url, chat_id, bot)
            else:
                epic_title = stored_data.get("epic_title", summary)
                prd_web_url = stored_data.get("prd_web_url", "")
                prototype_url = stored_data.get("prototype_url", "")
                preview_msg = send_epic_preview(bot, chat_id, issue_key, epic_title, epic_summary, prd_web_url, prototype_url)
                if preview_msg:
                    from pm4_epic import pending_epics
                    pending_epics[preview_msg.message_id] = pending

        elif stage == "pm5":
            spike = stored_data.get("spike", {})
            epic_key = stored_data.get("epic_key", "")
            if not spike or not epic_key:
                # Injected — trigger task breakdown generation
                # issue_key IS the epic for PM5 inject
                epic_key = epic_key or issue_key
                prd_page_id = stored_data.get("prd_page_id", "")
                prd_web_url = stored_data.get("prd_web_url", "")
                prototype_url = stored_data.get("prototype_url", "") or "N/A"
                from pm5_tasks import process_task_breakdown
                process_task_breakdown(epic_key, summary, issue_key, prd_page_id, prd_web_url, prototype_url, chat_id, bot)
            else:
                # Restoring a parked task breakdown
                epic_title = stored_data.get("epic_title", summary)
                tasks = stored_data.get("tasks", [])
                if tasks:
                    preview_msg = send_task_breakdown_preview(bot, chat_id, epic_key, epic_title, tasks)
                    if preview_msg:
                        from pm5_tasks import pending_task_breakdowns
                        pending_task_breakdowns[preview_msg.message_id] = pending
                else:
                    # Legacy spike data — trigger fresh task breakdown
                    prd_page_id = stored_data.get("prd_page_id", "")
                    prd_web_url = stored_data.get("prd_web_url", "")
                    prototype_url = stored_data.get("prototype_url", "") or "N/A"
                    from pm5_tasks import process_task_breakdown
                    process_task_breakdown(epic_key, summary, issue_key, prd_page_id, prd_web_url, prototype_url, chat_id, bot)

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
        """Alias: redirect to /actions parked flow."""
        save_chat_id(message.chat.id)
        _show_parked_items(message.chat.id)

    @bot.message_handler(commands=["update"])
    def handle_update(message):
        """Alias: redirect to /actions ticket flow."""
        save_chat_id(message.chat.id)
        _start_ticket_flow(message.chat.id)

    @bot.message_handler(commands=["actions"])
    def handle_actions(message):
        save_chat_id(message.chat.id)
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📋 Parked", callback_data="act_parked"),
            InlineKeyboardButton("🎫 Ticket", callback_data="act_ticket"),
        )
        bot.send_message(message.chat.id,
            "⚡ *Actions*\n\n"
            "📋 *Parked* — View & resume parked items\n"
            "🎫 *Ticket* — Take action on a ticket",
            parse_mode="Markdown", reply_markup=markup)

    def _show_parked_items(chat_id):
        """Show parked items list."""
        from pending_store import list_parked
        items = list_parked()

        if not items:
            bot.send_message(chat_id, "✨ No pending items. Everything is clear!")
            return

        stage_labels = {"pm1": "💡 Idea", "pm2": "📋 PRD", "pm3": "🎨 Prototype", "pm4": "📦 Epic", "pm5": "📝 Spike", "pm6": "🔧 Engineer"}

        lines = ["*Parked Items:*\n"]
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

    def _start_ticket_flow(chat_id):
        """Ask for a ticket ID, then show action menu."""
        user_state[chat_id] = {"mode": "actions_awaiting_ticket"}
        bot.send_message(chat_id,
            "🎫 Send a ticket ID (e.g. `AX-426` or `AR-350`)",
            parse_mode="Markdown")

    def _show_ticket_actions(chat_id, ticket_key, issue):
        """Show action menu for a ticket."""
        f = issue.get("fields", {})
        summary = f.get("summary", "")
        itype = f.get("issuetype", {}).get("name", "?")
        status = f.get("status", {}).get("name", "?")

        sprint_info = ""
        sprints = f.get("customfield_10020") or []
        if isinstance(sprints, list) and sprints:
            sprint_info = f" · {sprints[-1].get('name', '?')}"

        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("🏃 Sprint", callback_data="act_sprint"),
            InlineKeyboardButton("📋 Backlog", callback_data="act_backlog"),
        )
        markup.add(
            InlineKeyboardButton("📌 Inject", callback_data="act_inject"),
            InlineKeyboardButton("✏️ Edit", callback_data="act_edit"),
        )
        markup.add(
            InlineKeyboardButton("🗃 Archive", callback_data="act_archive"),
        )

        link = f"https://axiscrm.atlassian.net/browse/{ticket_key}"
        bot.send_message(chat_id,
            f"🎫 *[{ticket_key}]({link})* ({itype} · {status}{sprint_info})\n"
            f"_{summary}_\n\n"
            f"Pick an action:",
            parse_mode="Markdown", reply_markup=markup, disable_web_page_preview=True)

    @bot.callback_query_handler(func=lambda call: call.data.startswith("act_"))
    def handle_actions_callback(call):
        save_chat_id(call.message.chat.id)
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id
        action = call.data
        state = user_state.get(chat_id, {"mode": "idle"})

        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass

        if action == "act_parked":
            _show_parked_items(chat_id)
            return

        if action == "act_ticket":
            _start_ticket_flow(chat_id)
            return

        # All remaining actions need a ticket key in state
        ticket_key = state.get("ticket_key")
        if not ticket_key:
            bot.send_message(chat_id, "❓ No ticket selected. Use /actions to start.")
            return

        if action == "act_sprint":
            user_state[chat_id] = {**state, "mode": "actions_awaiting_sprint"}
            bot.send_message(chat_id,
                f"🏃 Which sprint for *{ticket_key}*? e.g. `April (S1)`",
                parse_mode="Markdown")
            return

        if action == "act_backlog":
            from po_actions import handle_backlog_move
            handle_backlog_move(ticket_key, chat_id, bot)
            user_state[chat_id] = {"mode": "idle"}
            return

        if action == "act_archive":
            from po_actions import handle_archive
            handle_archive(ticket_key, chat_id, bot)
            user_state[chat_id] = {"mode": "idle"}
            return

        if action == "act_edit":
            user_state[chat_id] = {**state, "mode": "actions_awaiting_edit"}
            bot.send_message(chat_id,
                f"✏️ What do you want to change on *{ticket_key}*?\n"
                f"e.g. `change AC to include admin validation` or `set SP to 2`",
                parse_mode="Markdown")
            return

        if action == "act_inject":
            stage_labels = {"pm1": "💡 Idea", "pm2": "📋 PRD", "pm3": "🎨 Prototype", "pm4": "📦 Epic", "pm5": "📝 Spike", "pm6": "🔧 Engineer"}
            markup = InlineKeyboardMarkup(row_width=2)
            for stage, label in stage_labels.items():
                markup.add(InlineKeyboardButton(
                    f"{label}", callback_data=f"actinj_{stage}",
                ))
            bot.send_message(chat_id,
                f"📌 Inject *{ticket_key}* at which stage?",
                parse_mode="Markdown", reply_markup=markup)
            return

    @bot.callback_query_handler(func=lambda call: call.data.startswith("actinj_"))
    def handle_inject_callback(call):
        save_chat_id(call.message.chat.id)
        bot.answer_callback_query(call.id)
        chat_id = call.message.chat.id

        try:
            bot.edit_message_reply_markup(chat_id, call.message.message_id, reply_markup=None)
        except Exception:
            pass

        state = user_state.get(chat_id, {})
        ticket_key = state.get("ticket_key")
        if not ticket_key:
            bot.send_message(chat_id, "❓ No ticket selected.")
            return

        stage = call.data.replace("actinj_", "")
        stage_labels = {"pm1": "💡 Idea", "pm2": "📋 PRD", "pm3": "🎨 Prototype", "pm4": "📦 Epic", "pm5": "📝 Spike", "pm6": "🔧 Engineer"}

        # Auto-discover context for later stages so resume works
        park_data = {}
        if stage in ("pm3", "pm4", "pm5", "pm6"):
            from jira_client import discover_prd_from_issue
            prd_url, page_id = discover_prd_from_issue(ticket_key)
            if prd_url:
                park_data["prd_web_url"] = prd_url
            if page_id:
                park_data["prd_page_id"] = page_id

        from pending_store import park_item
        ok = park_item(ticket_key, stage, park_data)
        if ok:
            label = stage_labels.get(stage, stage)
            bot.send_message(chat_id,
                f"📌 [{ticket_key}](https://axiscrm.atlassian.net/browse/{ticket_key}) injected at {label}\n"
                f"Use /actions → Parked to resume.",
                parse_mode="Markdown", disable_web_page_preview=True)
        else:
            bot.send_message(chat_id, f"❌ Failed to park {ticket_key}.")
        user_state[chat_id] = {"mode": "idle"}

    @bot.message_handler(commands=["voa"])
    def handle_voa(message):
        save_chat_id(message.chat.id)
        import threading
        def _run():
            try:
                from voa_monitor import run_voa_monitor
                run_voa_monitor()
            except Exception as e:
                log.error(f"/voa failed: {e}", exc_info=True)
        bot.reply_to(message, "🔄 VoA Monitor starting...")
        threading.Thread(target=_run, daemon=True).start()

    @bot.message_handler(commands=["sprint_turnover"])
    def handle_sprint_turnover(message):
        save_chat_id(message.chat.id)
        import threading
        def _run():
            try:
                from po_actions_automatic import run_sprint_turnover
                run_sprint_turnover()
            except Exception as e:
                log.error(f"/sprint_turnover failed: {e}", exc_info=True)
        bot.reply_to(message, "🔄 Sprint turnover starting...")
        threading.Thread(target=_run, daemon=True).start()

    @bot.message_handler(content_types=["text"])
    def handle_text(message):
        save_chat_id(message.chat.id)
        chat_id = message.chat.id
        state = user_state.get(chat_id, {"mode": "idle"})
        text = message.text.strip()

        # Unknown command
        if text.startswith("/"):
            if text.split()[0].lower() in ("/done",):
                user_state[chat_id] = {"mode": "idle"}
                bot.send_message(chat_id, "👍 Back to default mode.")
                return
            bot.reply_to(message, "Unknown command. Try /opportunity, /actions, or /help")
            return

        # Awaiting opportunity text (user sent /opportunity with no text)
        if state.get("mode") == "awaiting_idea":
            markup = InlineKeyboardMarkup(row_width=2)
            markup.add(
                InlineKeyboardButton("📋 Triage", callback_data="col_triage"),
                InlineKeyboardButton("🌤 Blue Sky", callback_data="col_bluesky"),
            )
            col_msg = bot.send_message(chat_id, "Where should this land?", reply_markup=markup)
            user_state[chat_id] = {
                "mode": "awaiting_column",
                "idea_text": text,
                "col_message_id": col_msg.message_id,
            }
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

        # ── /actions: awaiting ticket ID ──
        if state.get("mode") == "actions_awaiting_ticket":
            from po_actions import extract_ticket_key
            ticket_key, _ = extract_ticket_key(text)
            if not ticket_key:
                bot.send_message(chat_id, "❓ Send a valid ticket ID (e.g. `AX-426`).", parse_mode="Markdown")
                return
            from jira_client import jira_get
            from config import STORY_POINTS_FIELD
            issue = jira_get(f"/rest/api/3/issue/{ticket_key}", params={
                "fields": f"summary,issuetype,status,{STORY_POINTS_FIELD},customfield_10020"
            })
            if not issue or "fields" not in issue:
                bot.send_message(chat_id, f"❌ Couldn't find {ticket_key}.")
                return
            user_state[chat_id] = {"mode": "actions_ticket_selected", "ticket_key": ticket_key}
            _show_ticket_actions(chat_id, ticket_key, issue)
            return

        # ── /actions: awaiting sprint label ──
        if state.get("mode") == "actions_awaiting_sprint":
            ticket_key = state.get("ticket_key")
            if ticket_key:
                from po_actions import handle_sprint_move
                handle_sprint_move(ticket_key, text.strip(), chat_id, bot)
            user_state[chat_id] = {"mode": "idle"}
            return

        # ── /actions: awaiting edit instruction ──
        if state.get("mode") == "actions_awaiting_edit":
            ticket_key = state.get("ticket_key")
            if ticket_key:
                # Reuse the AI update flow from process_update
                user_state[chat_id] = {"mode": "update", "ticket_key": ticket_key}
                from po_actions import process_update
                process_update(text, chat_id, bot, user_state[chat_id], user_state)
            return

        # Awaiting /update actions (PO mode — used by PM5 approval flow)
        if state.get("mode") == "update":
            if text.lower() == "done":
                user_state[chat_id] = {"mode": "idle"}
                bot.send_message(chat_id, "👍 Back to default mode.")
                return
            from po_actions import process_update
            process_update(text, chat_id, bot, state, user_state)
            return

        # Default: treat as an opportunity — show column picker
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("📋 Triage", callback_data="col_triage"),
            InlineKeyboardButton("🌤 Blue Sky", callback_data="col_bluesky"),
        )
        col_msg = bot.send_message(chat_id, "Where should this land?", reply_markup=markup)
        user_state[chat_id] = {
            "mode": "awaiting_column",
            "idea_text": text,
            "col_message_id": col_msg.message_id,
        }

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
                # Awaiting idea or idle — show column picker
                markup = InlineKeyboardMarkup(row_width=2)
                markup.add(
                    InlineKeyboardButton("📋 Triage", callback_data="col_triage"),
                    InlineKeyboardButton("🌤 Blue Sky", callback_data="col_bluesky"),
                )
                col_msg = bot.send_message(chat_id, "Where should this land?", reply_markup=markup)
                user_state[chat_id] = {
                    "mode": "awaiting_column",
                    "idea_text": text,
                    "col_message_id": col_msg.message_id,
                }

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

    import time as _time

    # Retry loop to handle 409 conflicts during Railway deploys
    max_retries = 5
    for attempt in range(max_retries):
        try:
            bot.remove_webhook()
            _time.sleep(2)  # Give old instance time to release
            bot.get_updates(offset=-1, timeout=1)
            log.info("Cleared stale Telegram connections.")
            break
        except Exception as e:
            if "409" in str(e) and attempt < max_retries - 1:
                wait = (attempt + 1) * 5  # 5s, 10s, 15s, 20s
                log.warning(f"Telegram 409 conflict (attempt {attempt+1}/{max_retries}). Waiting {wait}s...")
                _time.sleep(wait)
            else:
                log.error(f"Failed to clear Telegram connections after {max_retries} attempts: {e}")
                raise

    try:

        # Register commands in Telegram's "/" menu
        from telebot.types import BotCommand
        bot.set_my_commands([
            BotCommand("help", "Show all commands"),
            BotCommand("opportunity", "Submit a product opportunity"),
            BotCommand("actions", "Ticket actions, pipeline inject"),
            BotCommand("update", "Edit an existing ticket"),
            BotCommand("pending", "Show pending approvals"),
            BotCommand("sprint_turnover", "Close sprint, carry over, start next"),
            BotCommand("voa", "Run Voice of Adviser monitor"),
        ])
        log.info("Registered Telegram bot commands menu.")

        bot.infinity_polling(timeout=20, long_polling_timeout=20)
    except Exception as e:
        if "409" in str(e):
            log.warning(f"Telegram 409 during polling — retrying in 10s: {e}")
            _time.sleep(10)
            try:
                bot.remove_webhook()
                bot.get_updates(offset=-1, timeout=1)
                bot.infinity_polling(timeout=20, long_polling_timeout=20)
            except Exception as e2:
                log.error(f"Telegram bot crashed on retry: {e2}", exc_info=True)
        else:
            log.error(f"Telegram bot crashed: {e}", exc_info=True)
