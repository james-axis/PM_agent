"""
PM Agent — PM5: Task Breakdown
Decomposes an Epic into Task tickets with PM template:
Summary, User story, Acceptance criteria, Test plan.
"""

import json
import re
import logging

from config import ROADMAP_FIELD, STORY_POINTS_FIELD, log
from jira_client import add_comment, jira_get, jira_post, jira_put, move_issue_to_sprint
from claude_client import call_claude
from confluence_client import fetch_page_content

# Pending task breakdowns awaiting approval: {message_id: {...}}
pending_task_breakdowns = {}


def _resolve_target_sprint(source_idea_key, epic_key=None):
    """Read the AR idea's Roadmap field to get target sprint label."""
    if (not source_idea_key or not source_idea_key.startswith("AR-")) and epic_key:
        try:
            epic = jira_get(f"/rest/api/3/issue/{epic_key}", params={"fields": "issuelinks"})
            if epic:
                for link in epic.get("fields", {}).get("issuelinks") or []:
                    for direction in ("outwardIssue", "inwardIssue"):
                        linked = link.get(direction)
                        if linked and linked.get("key", "").startswith("AR-"):
                            source_idea_key = linked["key"]
                            break
                    if source_idea_key and source_idea_key.startswith("AR-"):
                        break
        except Exception as e:
            log.warning(f"PM5: Could not check issue links on {epic_key}: {e}")

    if not source_idea_key or not source_idea_key.startswith("AR-"):
        return ""

    try:
        issue = jira_get(f"/rest/api/3/issue/{source_idea_key}", params={"fields": ROADMAP_FIELD})
        if not issue:
            return ""
        roadmap_field = issue.get("fields", {}).get(ROADMAP_FIELD)
        if not roadmap_field:
            return ""
        value = roadmap_field.get("value", "") if isinstance(roadmap_field, dict) else str(roadmap_field)
        if value.lower() in ("backlog", "shipped", "delivered", ""):
            return ""
        return value
    except Exception as e:
        log.warning(f"PM5: Could not read roadmap for {source_idea_key}: {e}")
        return ""


def _generate_task_breakdown(epic_key, epic_title, prd_content):
    """Use Claude to decompose an Epic into tasks with PM template fields."""

    prompt = (
        "You are a product manager decomposing a Jira Epic into individual Task tickets "
        "for a CRM platform team. Each task should be small enough to be 1, 2, or 3 story points "
        "(1=small/one layer, 2=medium/one external dependency, 3=large/multi-step data work); "
        "split anything that would be larger than 3.\n\n"
        f"Epic: {epic_key} — {epic_title}\n\n"
        f"<prd>\n{prd_content[:8000]}\n</prd>\n\n"
        "Break this Epic into 3-8 tasks. For each task, return:\n"
        '- "title": concise task title (max 10 words)\n'
        '- "summary": 1-2 sentence description of what this task delivers\n'
        '- "user_story": "As a [role], I want [goal], so that [benefit]"\n'
        '- "acceptance_criteria": list of 3-5 testable conditions\n'
        '- "test_plan": list of 2-4 test scenarios\n\n'
        "Return a JSON array of task objects. Be concise — quality over length.\n"
        "Return ONLY valid JSON, no preamble or markdown."
    )

    response = call_claude(prompt, max_tokens=4000)
    if not response:
        return None

    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response.strip())
        clean = re.sub(r'\s*```$', '', clean)
        result = json.loads(clean)
        if isinstance(result, list):
            return result
        if isinstance(result, dict) and "tasks" in result:
            return result["tasks"]
        return None
    except json.JSONDecodeError as e:
        log.error(f"PM5: Claude JSON parse error: {e}")
        return None


def _build_task_description_adf(task):
    """Build ADF description for a task using the PM template."""
    ac_items = task.get("acceptance_criteria", ["TBD"])
    tp_items = task.get("test_plan", ["TBD"])

    ac_list = {"type": "bulletList", "content": [
        {"type": "listItem", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": ac}]}
        ]} for ac in ac_items
    ]}
    tp_list = {"type": "bulletList", "content": [
        {"type": "listItem", "content": [
            {"type": "paragraph", "content": [{"type": "text", "text": tp}]}
        ]} for tp in tp_items
    ]}

    return {
        "version": 1,
        "type": "doc",
        "content": [
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Product Manager:", "marks": [{"type": "strong"}]}
            ]},
            {"type": "orderedList", "attrs": {"order": 1}, "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "Summary: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": task.get("summary", "TBD")},
                ]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "User story: ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": task.get("user_story", "TBD")},
                ]}]},
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [
                        {"type": "text", "text": "Acceptance criteria:", "marks": [{"type": "strong"}]},
                    ]},
                    ac_list,
                ]},
                {"type": "listItem", "content": [
                    {"type": "paragraph", "content": [
                        {"type": "text", "text": "Test plan:", "marks": [{"type": "strong"}]},
                    ]},
                    tp_list,
                ]},
            ]},
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Engineer:", "marks": [{"type": "strong"}]}
            ]},
            {"type": "orderedList", "attrs": {"order": 1}, "content": [
                {"type": "listItem", "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "Technical plan: ", "marks": [{"type": "strong"}]},
                ]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "Story points estimated", "marks": [
                        {"type": "strong"},
                        {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/91062273/Delivery+process#Story-points-framework"}},
                    ]},
                    {"type": "text", "text": ":", "marks": [{"type": "strong"}]},
                ]}]},
                {"type": "listItem", "content": [{"type": "paragraph", "content": [
                    {"type": "text", "text": "Task broken down (<=3 story points or split into parts): ", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": "Yes/No"},
                ]}]},
            ]},
            {"type": "paragraph", "content": [
                {"type": "text", "text": "Definition of Ready (DoR) - Task Level", "marks": [
                    {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/91062273/Delivery+process#Definition-of-Ready-(DoR)"}},
                ]},
                {"type": "text", "text": "   |   "},
                {"type": "text", "text": "Definition of Done (DoD) - Task Level", "marks": [
                    {"type": "link", "attrs": {"href": "https://axiscrm.atlassian.net/wiki/spaces/CAD/pages/91062273/Delivery+process#Definition-of-Done-(DoD)"}},
                ]},
            ]},
        ]
    }


def _create_task_under_epic(epic_key, task):
    """Create a single Task ticket under an Epic with the PM template."""
    title = task.get("title", "Untitled task")[:250]
    description_adf = _build_task_description_adf(task)

    payload = {
        "fields": {
            "project": {"key": "AX"},
            "summary": title,
            "issuetype": {"name": "Task"},
            "parent": {"key": epic_key},
            "description": description_adf,
        }
    }

    ok, resp = jira_post("/rest/api/3/issue", payload)
    if ok:
        data = resp.json()
        key = data["key"]
        url = f"https://axiscrm.atlassian.net/browse/{key}"
        log.info(f"PM5: Created task {key}: {title} under {epic_key}")
        return key, url
    else:
        log.error(f"PM5: Failed to create task: {resp.status_code} {resp.text[:300]}")
        return None, None


# ══════════════════════════════════════════════════════════════════════════════
# MAIN FLOW
# ══════════════════════════════════════════════════════════════════════════════

def process_task_breakdown(epic_key, epic_title, source_idea_key, prd_page_id, prd_web_url, prototype_url, chat_id, bot):
    """Generate task breakdown from Epic + PRD. Called after PM4 Epic is approved."""
    from telegram_bot import send_task_breakdown_preview

    status_msg = bot.send_message(chat_id, f"📝 Generating task breakdown for {epic_key}...")

    # Fetch PRD
    prd_content = ""
    if prd_page_id:
        log.info(f"PM5: Fetching PRD page {prd_page_id} for {epic_key}...")
        try:
            prd_page = fetch_page_content(prd_page_id)
            if prd_page:
                prd_content = prd_page.get("text", "")
                log.info(f"PM5: PRD fetched — {len(prd_content)} chars")
            else:
                log.warning(f"PM5: fetch_page_content returned None for {prd_page_id}")
        except Exception as e:
            log.error(f"PM5: PRD fetch error for {prd_page_id}: {e}", exc_info=True)

    if not prd_content:
        bot.edit_message_text(f"❌ Could not fetch PRD for {epic_key} (page {prd_page_id}).", chat_id, status_msg.message_id)
        return

    # Resolve target sprint
    target_sprint = _resolve_target_sprint(source_idea_key, epic_key=epic_key)
    log.info(f"PM5: Target sprint for {epic_key}: '{target_sprint}'")

    # Generate tasks via Claude
    bot.edit_message_text("📝 Decomposing into tasks...", chat_id, status_msg.message_id)
    log.info(f"PM5: Calling Claude for task breakdown on {epic_key}...")

    tasks = _generate_task_breakdown(epic_key, epic_title, prd_content)
    log.info(f"PM5: Task breakdown result for {epic_key}: {len(tasks) if tasks else 0} tasks")

    if not tasks:
        bot.edit_message_text(f"❌ AI failed to generate task breakdown for {epic_key}. Check logs.", chat_id, status_msg.message_id)
        return

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_task_breakdown_preview(bot, chat_id, epic_key, epic_title, tasks)

    if preview_msg:
        pending_task_breakdowns[preview_msg.message_id] = {
            "issue_key": source_idea_key,
            "epic_key": epic_key,
            "epic_title": epic_title,
            "tasks": tasks,
            "prd_page_id": prd_page_id,
            "prd_web_url": prd_web_url,
            "prd_content": prd_content,
            "prototype_url": prototype_url,
            "target_sprint": target_sprint,
            "chat_id": chat_id,
        }
        log.info(f"PM5: Task breakdown preview for {epic_key} — {len(tasks)} tasks (msg_id={preview_msg.message_id})")


def approve_task_breakdown(message_id, bot):
    """Approve: create Task tickets under the Epic."""
    pending = pending_task_breakdowns.pop(message_id, None)
    if not pending:
        return "❌ This task breakdown has already been processed or expired."

    epic_key = pending["epic_key"]
    tasks = pending["tasks"]
    chat_id = pending["chat_id"]
    source_idea_key = pending["issue_key"]

    status_msg = bot.send_message(chat_id, f"📝 Creating {len(tasks)} tasks under {epic_key}...")

    created = []
    for task in tasks:
        key, url = _create_task_under_epic(epic_key, task)
        if key:
            created.append((key, url, task.get("title", "?")))

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if not created:
        bot.send_message(chat_id, f"❌ Failed to create any tasks under {epic_key}.")
        return None

    # Comment on source idea
    task_list = ", ".join(k for k, _, _ in created)
    add_comment(source_idea_key, f"Tasks created under {epic_key}: {task_list}")

    # Build summary message
    epic_link = f"https://axiscrm.atlassian.net/browse/{epic_key}"
    task_lines = "\n".join(
        f"  • [{k}]({u}) — {t}" for k, u, t in created
    )

    bot.send_message(
        chat_id,
        f"✅ *{len(created)} tasks* created under [{epic_key}]({epic_link}):\n\n"
        f"{task_lines}\n\n"
        f"🏁 Pipeline complete for {epic_key}.",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )

    log.info(f"PM5: Created {len(created)} tasks under {epic_key}")

    # Track metric
    try:
        from metrics_client import post_metric
        post_metric("epic_to_tasks", items_processed=len(created))
    except Exception:
        pass

    return None


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

    bot.send_message(chat_id, "🔄 What would you like to change? (e.g. 'split task 3 into two', 'add a task for error handling', 'remove the last task')")
    return True


def apply_task_changes(message_id, change_text, chat_id, bot):
    """Apply changes to a pending task breakdown using Claude."""
    pending = pending_task_breakdowns.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This task breakdown has already been processed or expired.")
        return

    from telegram_bot import send_task_breakdown_preview

    status_msg = bot.send_message(chat_id, "🔄 Regenerating task breakdown...")

    current_tasks = json.dumps(pending["tasks"], indent=2)
    prompt = (
        f"You previously generated this task breakdown:\n{current_tasks}\n\n"
        f"Changes requested: {change_text}\n\n"
        f"<prd>\n{pending['prd_content'][:6000]}\n</prd>\n\n"
        "Apply the changes. Return the updated JSON array of tasks (same format). "
        "No preamble, no markdown fences."
    )

    response = call_claude(prompt, max_tokens=4000)
    updated = None
    if response:
        try:
            clean = re.sub(r'^```(?:json)?\s*', '', response.strip())
            clean = re.sub(r'\s*```$', '', clean)
            result = json.loads(clean)
            if isinstance(result, list):
                updated = result
            elif isinstance(result, dict) and "tasks" in result:
                updated = result["tasks"]
        except json.JSONDecodeError as e:
            log.error(f"PM5: Claude JSON parse error on changes: {e}")

    if not updated:
        bot.edit_message_text("❌ Failed to regenerate tasks. Try again.", chat_id, status_msg.message_id)
        return

    pending["tasks"] = updated
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
    )

    if preview_msg:
        pending_task_breakdowns[preview_msg.message_id] = pending
        pending["chat_id"] = chat_id
        log.info(f"PM5: Tasks re-generated for {pending['epic_key']} — {len(updated)} tasks")
