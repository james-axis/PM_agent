"""
PM Agent — PM5: Task Breakdown
Breaks an approved Epic into small, shippable tasks (0.25–3 SP).
Creates tasks in AX project under the Epic.
"""

from config import log
from jira_client import create_task, add_comment
from claude_client import generate_task_breakdown, update_tasks_with_changes
from confluence_client import fetch_page_content

# Pending task breakdowns awaiting approval: {message_id: {...}}
pending_task_breakdowns = {}


def process_task_breakdown(epic_key, epic_title, source_idea_key, prd_page_id, prd_web_url, prototype_url, chat_id, bot):
    """
    Generate task breakdown from Epic + PRD.
    Called after PM4 Epic is approved.
    """
    from telegram_bot import send_task_breakdown_preview

    # Step 1: Acknowledge
    status_msg = bot.send_message(chat_id, f"📝 Breaking down {epic_key} into tasks...")

    # Step 2: Fetch PRD
    prd_content = ""
    if prd_page_id:
        prd_page = fetch_page_content(prd_page_id)
        if prd_page:
            prd_content = prd_page.get("text", "")

    if not prd_content:
        bot.edit_message_text(f"❌ Could not fetch PRD for {epic_key}.", chat_id, status_msg.message_id)
        return

    # Step 3: Generate task breakdown via Claude
    bot.edit_message_text("📝 Generating task breakdown...", chat_id, status_msg.message_id)
    tasks = generate_task_breakdown(epic_key, epic_title, prd_content, prototype_url)

    if not tasks or not isinstance(tasks, list):
        bot.edit_message_text("❌ AI failed to generate task breakdown. Check logs.", chat_id, status_msg.message_id)
        return

    # Step 4: Delete status and send preview
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    total_sp = sum(t.get("story_points", 0) for t in tasks)

    preview_msg = send_task_breakdown_preview(
        bot, chat_id, epic_key, epic_title, tasks, total_sp, prd_web_url, prototype_url,
    )

    # Step 5: Store pending
    if preview_msg:
        pending_task_breakdowns[preview_msg.message_id] = {
            "issue_key": source_idea_key,
            "summary": epic_title,
            "epic_key": epic_key,
            "epic_title": epic_title,
            "tasks": tasks,
            "total_sp": total_sp,
            "prd_page_id": prd_page_id,
            "prd_web_url": prd_web_url,
            "prd_content": prd_content,
            "prototype_url": prototype_url,
            "chat_id": chat_id,
        }
        log.info(f"PM5: Task breakdown preview for {epic_key} — {len(tasks)} tasks, {total_sp} SP (msg_id={preview_msg.message_id})")


def approve_task_breakdown(message_id, bot):
    """Approve a pending task breakdown: create all tasks in AX under the Epic."""
    pending = pending_task_breakdowns.pop(message_id, None)
    if not pending:
        return "❌ This task breakdown has already been processed or expired."

    epic_key = pending["epic_key"]
    tasks = pending["tasks"]
    chat_id = pending["chat_id"]
    source_idea_key = pending["issue_key"]

    # Send progress — we create tasks one by one
    status_msg = bot.send_message(chat_id, f"📝 Creating {len(tasks)} tasks under {epic_key}...")

    created = []
    failed = 0
    for i, task in enumerate(tasks, 1):
        try:
            bot.edit_message_text(
                f"📝 Creating task {i}/{len(tasks)}...",
                chat_id, status_msg.message_id,
            )
        except Exception:
            pass

        task_key, task_url = create_task(
            epic_key=epic_key,
            summary=task.get("summary", f"Task {i}"),
            task_summary=task.get("task_summary", ""),
            user_story=task.get("user_story", ""),
            acceptance_criteria=task.get("acceptance_criteria", []),
            test_plan=task.get("test_plan", ""),
            story_points=task.get("story_points", 1.0),
        )
        if task_key:
            created.append({"key": task_key, "summary": task["summary"], "sp": task.get("story_points", 0)})
        else:
            failed += 1

    # Delete status
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    # Comment on source idea
    total_sp = sum(t["sp"] for t in created)
    task_list = "\n".join(f"- {t['key']}: {t['summary']} ({t['sp']} SP)" for t in created)
    add_comment(source_idea_key, f"Tasks created under {epic_key}: {len(created)} tasks, {total_sp} SP\n{task_list}")

    # Comment on Epic
    add_comment(epic_key, f"Task breakdown complete: {len(created)} tasks, {total_sp} SP")

    result = f"✅ [{epic_key}](https://axiscrm.atlassian.net/browse/{epic_key}) — {len(created)} tasks created ({total_sp} SP)"
    if failed:
        result += f"\n⚠️ {failed} task(s) failed to create."

    log.info(f"PM5: Created {len(created)} tasks under {epic_key} ({total_sp} SP)")

    # Send confirmation then trigger PM6
    bot.send_message(
        chat_id,
        result + "\n\n🔧 Starting engineering review...",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )

    # Trigger PM6: Engineer Review
    try:
        from pm6_engineer import process_engineer_review
        process_engineer_review(
            epic_key=epic_key,
            epic_title=pending["epic_title"],
            source_idea_key=source_idea_key,
            tasks_created=created,
            prd_page_id=pending.get("prd_page_id", ""),
            prd_web_url=pending.get("prd_web_url", ""),
            prototype_url=pending.get("prototype_url", ""),
            chat_id=chat_id,
            bot=bot,
        )
    except Exception as e:
        log.error(f"PM6 engineer review failed for {epic_key}: {e}")
        bot.send_message(chat_id, f"❌ Engineer review failed for {epic_key}: {e}")

    return None  # Already sent confirmation


def reject_task_breakdown(message_id):
    """Reject a pending task breakdown."""
    pending = pending_task_breakdowns.pop(message_id, None)
    if not pending:
        return "❌ This task breakdown has already been processed or expired."

    epic_key = pending["epic_key"]
    log.info(f"PM5: Rejected task breakdown for {epic_key}")
    return f"⛔ {epic_key} — Task breakdown rejected"


def start_task_changes(message_id, chat_id, bot):
    """Begin the task changes flow."""
    pending = pending_task_breakdowns.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This task breakdown has already been processed or expired.")
        return False

    bot.send_message(chat_id, "🔄 What would you like to change? (e.g. 'split task 3', 'add a migration task', 'reduce story points')")
    return True


def apply_task_changes(message_id, change_text, chat_id, bot):
    """Apply changes to a pending task breakdown using Claude."""
    pending = pending_task_breakdowns.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This task breakdown has already been processed or expired.")
        return

    from telegram_bot import send_task_breakdown_preview

    status_msg = bot.send_message(chat_id, "🔄 Regenerating task breakdown...")

    updated = update_tasks_with_changes(
        current_tasks=pending["tasks"],
        change_instructions=change_text,
        prd_content=pending["prd_content"],
    )

    if not updated or not isinstance(updated, list):
        bot.edit_message_text("❌ Failed to regenerate tasks. Try again.", chat_id, status_msg.message_id)
        return

    # Update pending
    pending["tasks"] = updated
    total_sp = sum(t.get("story_points", 0) for t in updated)
    pending["total_sp"] = total_sp

    # Remove old pending
    pending_task_breakdowns.pop(message_id, None)

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_task_breakdown_preview(
        bot, chat_id,
        pending["epic_key"],
        pending["epic_title"],
        updated,
        total_sp,
        pending["prd_web_url"],
        pending["prototype_url"],
    )

    if preview_msg:
        pending_task_breakdowns[preview_msg.message_id] = pending
        pending["chat_id"] = chat_id
        log.info(f"PM5: Tasks re-generated for {pending['epic_key']} — {len(updated)} tasks, {total_sp} SP")
