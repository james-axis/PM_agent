"""
PM Agent — PM6: Engineer
Investigates DB schema, codebase, and third-party APIs,
then fills in the Engineer section of each task (technical plan, story points, breakdown confirmation).

Two-pass approach:
  Pass 1 — Claude analyses tasks and identifies what to investigate
  Pass 2 — Claude generates technical plans with full gathered context
"""

from config import log
from jira_client import (
    get_epic_tasks, get_issue, update_task_engineer_section, add_comment,
)
from claude_client import (
    generate_investigation_plan, generate_technical_plans,
    update_engineer_plans_with_changes,
)
from confluence_client import fetch_page_content
from db_client import discover_relevant_schemas
from github_client import get_repo_structure, read_file_content, search_code
from web_client import identify_integrations, fetch_web_content

# Pending engineer reviews: {message_id: {...}}
pending_engineer_reviews = {}


def process_engineer_review(epic_key, epic_title, source_idea_key, tasks_created,
                            prd_page_id, prd_web_url, prototype_url, chat_id, bot):
    """
    Run the Engineer agent on all tasks under an Epic.
    tasks_created: list of {key, summary, sp} from PM5 approval.
    """
    from telegram_bot import send_engineer_preview

    status_msg = bot.send_message(chat_id, f"🔧 Engineering review for {epic_key}...")

    # ── Step 1: Fetch PRD ────────────────────────────────────────────────────
    prd_content = ""
    if prd_page_id:
        page = fetch_page_content(prd_page_id)
        if page:
            prd_content = page.get("text", "")

    if not prd_content:
        bot.edit_message_text(f"❌ Could not fetch PRD for {epic_key}.", chat_id, status_msg.message_id)
        return

    # Fetch full task details from Jira (includes user stories, ACs)
    tasks = []
    for tc in tasks_created:
        issue = get_issue(tc["key"])
        if issue:
            fields = issue.get("fields", {})
            # Extract PM section text from description
            desc = fields.get("description", {})
            pm_text = _extract_pm_section_text(desc) if desc else ""
            tasks.append({
                "key": tc["key"],
                "summary": tc["summary"],
                "story_points": tc.get("sp", 1.0),
                "pm_text": pm_text,
                # Carry forward from PM5 output
                "task_summary": pm_text[:200] if pm_text else tc["summary"],
                "user_story": "",
                "acceptance_criteria": [],
            })
        else:
            tasks.append({
                "key": tc["key"],
                "summary": tc["summary"],
                "story_points": tc.get("sp", 1.0),
                "pm_text": "",
                "task_summary": tc["summary"],
                "user_story": "",
                "acceptance_criteria": [],
            })

    # ── Step 2: Pass 1 — Investigation Plan ──────────────────────────────────
    bot.edit_message_text("🔍 Analysing tasks and codebase structure...", chat_id, status_msg.message_id)

    repo_structure = get_repo_structure()

    investigation = generate_investigation_plan(tasks, prd_content, repo_structure)

    db_keywords = investigation.get("db_keywords", []) if investigation else []
    code_files = investigation.get("code_files", []) if investigation else []
    api_integrations = investigation.get("api_integrations", []) if investigation else []

    log.info(f"PM6: Investigation plan — DB: {db_keywords}, Code: {len(code_files)} files, APIs: {api_integrations}")

    # ── Step 3: Gather Context ───────────────────────────────────────────────
    bot.edit_message_text("🗄️ Querying database schema...", chat_id, status_msg.message_id)

    # DB schema
    db_schema_text = "(No DB access)"
    if db_keywords:
        schema = discover_relevant_schemas(db_keywords)
        if schema:
            db_schema_text = schema

    # Code files
    bot.edit_message_text("📂 Reading codebase...", chat_id, status_msg.message_id)
    code_sections = []
    for filepath in code_files[:10]:  # Cap at 10 files
        content = read_file_content(filepath)
        if content:
            # Truncate large files
            if len(content) > 3000:
                content = content[:3000] + "\n... (truncated)"
            code_sections.append(f"--- {filepath} ---\n{content}")

    code_context = "\n\n".join(code_sections) if code_sections else "(No code files loaded)"

    # API docs
    api_docs_text = ""
    if api_integrations:
        bot.edit_message_text("🌐 Fetching API documentation...", chat_id, status_msg.message_id)
        api_sections = []
        for api_name in api_integrations[:3]:  # Cap at 3
            matches = identify_integrations(api_name)
            for match in matches:
                doc = fetch_web_content(match["url"], max_chars=5000)
                if doc:
                    api_sections.append(f"--- {match['name']} ({match['url']}) ---\n{doc[:3000]}")
        api_docs_text = "\n\n".join(api_sections) if api_sections else ""

    # ── Step 4: Pass 2 — Generate Technical Plans ────────────────────────────
    bot.edit_message_text("🧠 Generating technical plans...", chat_id, status_msg.message_id)

    plans = generate_technical_plans(tasks, prd_content, db_schema_text, code_context, api_docs_text)

    if not plans or not isinstance(plans, list):
        bot.edit_message_text("❌ AI failed to generate technical plans. Check logs.", chat_id, status_msg.message_id)
        return

    # Merge plans into tasks
    plans_by_index = {p["index"]: p for p in plans}
    for i, task in enumerate(tasks):
        plan = plans_by_index.get(i, {})
        task["technical_plan"] = plan.get("technical_plan", ["TBD"])
        task["confirmed_sp"] = plan.get("story_points", task["story_points"])

    total_sp = sum(t["confirmed_sp"] for t in tasks)

    # ── Step 5: Send Preview ─────────────────────────────────────────────────
    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_engineer_preview(bot, chat_id, epic_key, epic_title, tasks, total_sp)

    if preview_msg:
        # Build context summary for potential change requests
        context_summary = f"DB tables: {', '.join(db_keywords)}\nCode files: {', '.join(code_files[:5])}\nAPIs: {', '.join(api_integrations)}"

        pending_engineer_reviews[preview_msg.message_id] = {
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
            "context_summary": context_summary,
            "chat_id": chat_id,
        }
        log.info(f"PM6: Engineer preview for {epic_key} — {len(tasks)} tasks, {total_sp} SP")


def approve_engineer_review(message_id, bot):
    """Approve: update all tasks in Jira with the Engineer section."""
    pending = pending_engineer_reviews.pop(message_id, None)
    if not pending:
        return "❌ This engineer review has already been processed or expired."

    epic_key = pending["epic_key"]
    tasks = pending["tasks"]
    chat_id = pending["chat_id"]

    status_msg = bot.send_message(chat_id, f"🔧 Updating {len(tasks)} tasks with technical plans...")

    updated = 0
    failed = 0
    for i, task in enumerate(tasks, 1):
        try:
            bot.edit_message_text(
                f"🔧 Updating task {i}/{len(tasks)}...",
                chat_id, status_msg.message_id,
            )
        except Exception:
            pass

        ok = update_task_engineer_section(
            task_key=task["key"],
            technical_plan_points=task.get("technical_plan", ["TBD"]),
            story_points=task.get("confirmed_sp", task.get("story_points", 1.0)),
        )
        if ok:
            updated += 1
        else:
            failed += 1

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    # Comment on Epic
    total_sp = sum(t.get("confirmed_sp", 0) for t in tasks)
    add_comment(epic_key, f"Engineer review complete: {updated} tasks updated with technical plans, {total_sp} SP total")

    result = f"✅ [{epic_key}](https://axiscrm.atlassian.net/browse/{epic_key}) — {updated} tasks updated with technical plans ({total_sp} SP)"
    if failed:
        result += f"\n⚠️ {failed} task(s) failed to update."

    log.info(f"PM6: Updated {updated} tasks under {epic_key}")
    return result


def reject_engineer_review(message_id):
    """Reject a pending engineer review."""
    pending = pending_engineer_reviews.pop(message_id, None)
    if not pending:
        return "❌ This engineer review has already been processed or expired."

    epic_key = pending["epic_key"]
    log.info(f"PM6: Rejected engineer review for {epic_key}")
    return f"⛔ {epic_key} — Engineer review rejected"


def start_engineer_changes(message_id, chat_id, bot):
    """Begin the engineer changes flow."""
    pending = pending_engineer_reviews.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This engineer review has already been processed or expired.")
        return False

    bot.send_message(chat_id, "🔄 What would you like to change? (e.g. 'task 3 should use the existing API', 'reduce SP for migrations')")
    return True


def apply_engineer_changes(message_id, change_text, chat_id, bot):
    """Apply changes to pending engineer review."""
    pending = pending_engineer_reviews.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This engineer review has already been processed or expired.")
        return

    from telegram_bot import send_engineer_preview

    status_msg = bot.send_message(chat_id, "🔄 Regenerating technical plans...")

    # Build current plans for Claude
    current_plans = [
        {
            "index": i,
            "summary": t.get("summary", ""),
            "technical_plan": t.get("technical_plan", []),
            "story_points": t.get("confirmed_sp", t.get("story_points", 1.0)),
        }
        for i, t in enumerate(pending["tasks"])
    ]

    updated = update_engineer_plans_with_changes(
        current_plans, change_text, pending.get("context_summary", ""),
    )

    if not updated or not isinstance(updated, list):
        bot.edit_message_text("❌ Failed to regenerate plans. Try again.", chat_id, status_msg.message_id)
        return

    # Merge updated plans into tasks
    plans_by_index = {p["index"]: p for p in updated}
    for i, task in enumerate(pending["tasks"]):
        plan = plans_by_index.get(i, {})
        if plan:
            task["technical_plan"] = plan.get("technical_plan", task.get("technical_plan", ["TBD"]))
            task["confirmed_sp"] = plan.get("story_points", task.get("confirmed_sp", 1.0))

    total_sp = sum(t.get("confirmed_sp", 0) for t in pending["tasks"])
    pending["total_sp"] = total_sp

    pending_engineer_reviews.pop(message_id, None)

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_engineer_preview(bot, chat_id, pending["epic_key"], pending["epic_title"], pending["tasks"], total_sp)

    if preview_msg:
        pending_engineer_reviews[preview_msg.message_id] = pending
        pending["chat_id"] = chat_id
        log.info(f"PM6: Plans re-generated for {pending['epic_key']}")


def _extract_pm_section_text(adf_node, depth=0):
    """Recursively extract text from ADF, stopping at the Engineer heading."""
    if not adf_node or not isinstance(adf_node, dict):
        return ""

    if adf_node.get("type") == "text":
        text = adf_node.get("text", "")
        if text.strip() == "Engineer:":
            return ""  # Stop before Engineer section
        return text

    parts = []
    for child in adf_node.get("content", []):
        extracted = _extract_pm_section_text(child, depth + 1)
        if extracted is None:
            break
        parts.append(extracted)

    return " ".join(parts).strip()
