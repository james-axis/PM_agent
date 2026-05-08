"""
PM Agent — PM5: Spike Plan
Generates a single Spike ticket under an Epic with:
summary, acceptance criteria, t-shirt size, architectural thoughts, and supporting artefacts.
"""

from config import ROADMAP_FIELD, ANDREJ_ACCOUNT_ID, READY_TRANSITION_ID, STORY_POINTS_FIELD, log
from jira_client import create_spike, add_comment, jira_get, jira_put, assign_issue, transition_issue
from claude_client import generate_spike_plan, update_spike_with_changes
from confluence_client import fetch_page_content

# Pending spike plans awaiting approval: {message_id: {...}}
pending_spike_plans = {}


def _resolve_target_sprint(source_idea_key, epic_key=None):
    """Read the AR idea's Roadmap field to get target sprint label (e.g. 'April (S1)').
    If source_idea_key is missing/non-AR, tries to find AR idea from epic's issue links."""

    # If no AR key, try to find one from epic's issue links
    if (not source_idea_key or not source_idea_key.startswith("AR-")) and epic_key:
        try:
            epic = jira_get(f"/rest/api/3/issue/{epic_key}", params={"fields": "issuelinks"})
            if epic:
                for link in epic.get("fields", {}).get("issuelinks") or []:
                    for direction in ("outwardIssue", "inwardIssue"):
                        linked = link.get(direction)
                        if linked and linked.get("key", "").startswith("AR-"):
                            source_idea_key = linked["key"]
                            log.info(f"PM5: Found AR idea {source_idea_key} via {epic_key} issue links")
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


def process_task_breakdown(epic_key, epic_title, source_idea_key, prd_page_id, prd_web_url, prototype_url, chat_id, bot):
    """
    Generate a spike plan from Epic + PRD.
    Called after PM4 Epic is approved.
    """
    from telegram_bot import send_spike_preview

    status_msg = bot.send_message(chat_id, f"📝 Generating spike plan for {epic_key}...")

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

    # Resolve target sprint from AR roadmap
    target_sprint = _resolve_target_sprint(source_idea_key, epic_key=epic_key)
    log.info(f"PM5: Target sprint for {epic_key}: '{target_sprint}'")

    # Generate spike plan via Claude
    bot.edit_message_text("📝 Generating spike plan...", chat_id, status_msg.message_id)
    log.info(f"PM5: Calling Claude for spike plan on {epic_key}...")
    spike = generate_spike_plan(
        epic_key, epic_title, prd_content,
        prototype_url=prototype_url,
        prd_url=prd_web_url,
        target_sprint=target_sprint,
    )
    log.info(f"PM5: Spike plan result for {epic_key}: {type(spike)} — {bool(spike)}")

    if not spike or not isinstance(spike, dict):
        bot.edit_message_text(f"❌ AI failed to generate spike plan for {epic_key}. Check logs.", chat_id, status_msg.message_id)
        return

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_spike_preview(
        bot, chat_id, epic_key, epic_title, spike, prd_web_url, prototype_url, target_sprint,
    )

    if preview_msg:
        pending_spike_plans[preview_msg.message_id] = {
            "issue_key": source_idea_key,
            "summary": epic_title,
            "epic_key": epic_key,
            "epic_title": epic_title,
            "spike": spike,
            "prd_page_id": prd_page_id,
            "prd_web_url": prd_web_url,
            "prd_content": prd_content,
            "prototype_url": prototype_url,
            "target_sprint": target_sprint,
            "chat_id": chat_id,
        }
        log.info(f"PM5: Spike plan preview for {epic_key} — {spike.get('tshirt_size', '?')} (msg_id={preview_msg.message_id})")


def approve_task_breakdown(message_id, bot):
    """Approve a pending spike plan: create 1 Spike ticket in AX under the Epic."""
    pending = pending_spike_plans.pop(message_id, None)
    if not pending:
        return "❌ This spike plan has already been processed or expired."

    epic_key = pending["epic_key"]
    spike = pending["spike"]
    chat_id = pending["chat_id"]
    source_idea_key = pending["issue_key"]
    prd_web_url = pending["prd_web_url"]
    prototype_url = pending["prototype_url"]
    target_sprint = pending["target_sprint"]

    status_msg = bot.send_message(chat_id, f"📝 Creating spike under {epic_key}...")

    spike_key, spike_url = create_spike(
        epic_key=epic_key,
        spike_data=spike,
        prd_url=prd_web_url,
        prototype_url=prototype_url,
        target_sprint=target_sprint,
    )

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if not spike_key:
        bot.send_message(chat_id, f"❌ Failed to create spike under {epic_key}.")
        return None

    # Set 3 SP on the spike
    jira_put(f"/rest/api/3/issue/{spike_key}", {"fields": {STORY_POINTS_FIELD: 3.0}})

    # Move spike to S-2 (2 sprints before target), epic to target sprint
    sprint_status = ""
    if target_sprint:
        from po_actions import find_sprint_by_label, find_sprint_with_offset, move_to_sprint, get_all_sprints_sorted

        # Spike goes to S-2 for early investigation
        spike_sprint, offset = find_sprint_with_offset(target_sprint, offset=-2)
        if spike_sprint:
            move_to_sprint(spike_key, spike_sprint["id"])
            offset_label = f"S{offset}" if offset < 0 else "target"
            sprint_status = f" · Spike → {spike_sprint.get('name', '?')} ({offset_label})"
        else:
            # Target sprint doesn't exist yet (too far out) — use last future sprint
            all_sprints = get_all_sprints_sorted()
            if all_sprints:
                last_sprint = all_sprints[-1]
                move_to_sprint(spike_key, last_sprint["id"])
                sprint_status = f" · Spike → {last_sprint.get('name', '?')} (latest, target {target_sprint})"
                log.info(f"PM5: Target {target_sprint} not found, placed spike in {last_sprint.get('name')}")

        # Epic goes to target sprint
        target = find_sprint_by_label(target_sprint)
        if target:
            move_to_sprint(epic_key, target["id"])
            sprint_status += f" · Epic → {target.get('name', target_sprint)}"
        else:
            # Target sprint doesn't exist — put epic in last available sprint too
            all_sprints = get_all_sprints_sorted()
            if all_sprints:
                last_sprint = all_sprints[-1]
                move_to_sprint(epic_key, last_sprint["id"])
                sprint_status += f" · Epic → {last_sprint.get('name', '?')} (latest, target {target_sprint})"

    assign_issue(spike_key, ANDREJ_ACCOUNT_ID)
    assign_issue(epic_key, ANDREJ_ACCOUNT_ID)
    transition_issue(spike_key, READY_TRANSITION_ID)
    transition_issue(epic_key, READY_TRANSITION_ID)

    tshirt = spike.get("tshirt_size", "?")
    add_comment(source_idea_key, f"Spike created: {spike_key} under {epic_key} ({tshirt})")
    add_comment(epic_key, f"Spike plan: {spike_key} ({tshirt})")

    epic_link = f"https://axiscrm.atlassian.net/browse/{epic_key}"
    spike_link = f"https://axiscrm.atlassian.net/browse/{spike_key}"

    bot.send_message(
        chat_id,
        f"✅ [{spike_key}]({spike_link}) created under [{epic_key}]({epic_link})\n"
        f"3 SP · {tshirt} · Assigned: Andrej · Ready\n{sprint_status}\n\n"
        f"🏁 Pipeline complete for {epic_key}.",
        parse_mode="Markdown",
        disable_web_page_preview=True,
    )

    log.info(f"PM5: Created Spike {spike_key} under {epic_key} ({tshirt})")
    return None


def reject_task_breakdown(message_id):
    """Reject a pending spike plan."""
    pending = pending_spike_plans.pop(message_id, None)
    if not pending:
        return "❌ This spike plan has already been processed or expired."

    epic_key = pending["epic_key"]
    log.info(f"PM5: Rejected spike plan for {epic_key}")
    return f"⛔ {epic_key} — Spike plan rejected"


def start_task_changes(message_id, chat_id, bot):
    """Begin the spike changes flow."""
    pending = pending_spike_plans.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This spike plan has already been processed or expired.")
        return False

    bot.send_message(chat_id, "🔄 What would you like to change? (e.g. 'add more test cases', 'increase SP estimate', 'change technical approach')")
    return True


def apply_task_changes(message_id, change_text, chat_id, bot):
    """Apply changes to a pending spike plan using Claude."""
    pending = pending_spike_plans.get(message_id)
    if not pending:
        bot.send_message(chat_id, "❌ This spike plan has already been processed or expired.")
        return

    from telegram_bot import send_spike_preview

    status_msg = bot.send_message(chat_id, "🔄 Regenerating spike plan...")

    updated = update_spike_with_changes(
        current_spike=pending["spike"],
        change_instructions=change_text,
        prd_content=pending["prd_content"],
    )

    if not updated or not isinstance(updated, dict):
        bot.edit_message_text("❌ Failed to regenerate spike. Try again.", chat_id, status_msg.message_id)
        return

    pending["spike"] = updated
    pending_spike_plans.pop(message_id, None)

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    preview_msg = send_spike_preview(
        bot, chat_id,
        pending["epic_key"],
        pending["epic_title"],
        updated,
        pending["prd_web_url"],
        pending["prototype_url"],
        pending["target_sprint"],
    )

    if preview_msg:
        pending_spike_plans[preview_msg.message_id] = pending
        pending["chat_id"] = chat_id
        log.info(f"PM5: Spike re-generated for {pending['epic_key']} — {updated.get('tshirt_size', '?')}")
