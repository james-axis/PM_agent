"""
PM Agent — PO Actions
Handles /update command actions: sprint moves, backlog, PM5 task breakdown, PM7 scheduling.
"""

import re
import json
import requests
from datetime import datetime
from config import (
    JIRA_BASE_URL, CONFLUENCE_BASE, JIRA_EMAIL, JIRA_API_TOKEN,
    ROADMAP_FIELD, STORY_POINTS_FIELD, ANDREJ_ACCOUNT_ID, READY_TRANSITION_ID, log,
)
from jira_client import jira_get, jira_post, _extract_adf_text, search_issues, assign_issue, transition_issue
from claude_client import call_claude

AX_BOARD_ID = 1

auth = (JIRA_EMAIL, JIRA_API_TOKEN)
headers = {"Accept": "application/json"}

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}


# ── Action Detection ─────────────────────────────────────────────────────────

def detect_action(instruction):
    """Detect if instruction is a PO action (sprint move, backlog, PM trigger).
    Returns (action_type, param) or (None, None)."""
    lower = instruction.lower().strip()

    # Backlog move
    if lower in ("backlog", "move to backlog", "send to backlog"):
        return ("backlog", None)

    # Archive
    if lower in ("archive", "move to archive", "aru"):
        return ("archive", None)

    # PM5: task breakdown
    if lower in ("pm5", "task breakdown", "break down", "breakdown", "break it down"):
        return ("pm5", None)

    # PM7: schedule from roadmap (just "pm7" alone)
    if lower == "pm7":
        return ("pm7", None)

    # Sprint move: "move to sprint April (S1)" or "April (S1)" or "pm7 April (S1)"
    sprint_match = re.search(r'(?:move to sprint|move to|sprint|pm7)\s+(\w+\s*\(S\d+\))', instruction, re.IGNORECASE)
    if not sprint_match:
        sprint_match = re.match(r'^(\w+\s*\(S\d+\))$', instruction.strip(), re.IGNORECASE)
    if sprint_match:
        return ("sprint", sprint_match.group(1).strip())

    return (None, None)


def extract_ticket_key(text):
    """Extract Jira key from text. Returns (key, remaining_text) or (None, text)."""
    m = re.match(r'\s*((?:AX|AR|ARU)-\d+)\s*(.*)', text, re.IGNORECASE | re.DOTALL)
    if m:
        return m.group(1).upper(), m.group(2).strip()
    return None, text


# ── Sprint Helpers ────────────────────────────────────────────────────────────

def find_sprint_by_label(label):
    """Find a sprint matching a label like 'April (S1)'."""
    match = re.match(r'^(\w+)\s*\(S(\d+)\)$', label.strip(), re.IGNORECASE)
    if not match:
        return None
    month_name = match.group(1).lower()
    sprint_idx = int(match.group(2)) - 1
    target_month = MONTH_MAP.get(month_name)
    if target_month is None:
        return None

    now = datetime.now()
    target_year = now.year if target_month >= now.month else now.year + 1

    all_sprints = []
    for st in ("active", "future"):
        data = jira_get(f"/rest/agile/1.0/board/{AX_BOARD_ID}/sprint?state={st}")
        all_sprints.extend(data.get("values", []))

    month_sprints = []
    for s in all_sprints:
        sd = s.get("startDate", "")
        if not sd:
            continue
        try:
            dt = datetime.fromisoformat(sd.replace("Z", "+00:00"))
            if dt.month == target_month and dt.year == target_year:
                month_sprints.append(s)
        except Exception:
            continue

    month_sprints.sort(key=lambda s: s.get("startDate", ""))
    return month_sprints[sprint_idx] if sprint_idx < len(month_sprints) else None


def move_to_sprint(issue_key, sprint_id):
    """Move a single issue into a sprint."""
    ok, _ = jira_post(f"/rest/agile/1.0/sprint/{sprint_id}/issue", {"issues": [issue_key]})
    return ok


def get_all_sprints_sorted():
    """Get all active + future sprints sorted chronologically by start date."""
    all_sprints = []
    for st in ("active", "future"):
        data = jira_get(f"/rest/agile/1.0/board/{AX_BOARD_ID}/sprint?state={st}")
        all_sprints.extend(data.get("values", []))
    all_sprints.sort(key=lambda s: s.get("startDate", ""))
    return all_sprints


def find_sprint_with_offset(target_label, offset=-2):
    """Find a sprint N positions before the target sprint.
    offset=-2 means 2 sprints before target. Falls back to -1, then 0 (target itself).
    Returns (sprint_dict, actual_offset) or (None, 0)."""
    target = find_sprint_by_label(target_label)
    if not target:
        return None, 0

    all_sprints = get_all_sprints_sorted()
    target_id = target["id"]

    # Find target index in sorted list
    target_idx = None
    for i, s in enumerate(all_sprints):
        if s["id"] == target_id:
            target_idx = i
            break

    if target_idx is None:
        return target, 0

    # Try offset -2, then -1, then 0
    for off in (offset, offset + 1, 0):
        idx = target_idx + off
        if 0 <= idx < len(all_sprints):
            return all_sprints[idx], off

    return target, 0


def get_epic_children(epic_key):
    """Get all non-Done child issues under an Epic."""
    data = jira_get("/rest/api/3/search/jql", params={
        "jql": f'"Epic Link" = {epic_key} AND status not in (Done, Released)',
        "fields": "summary,status,issuetype",
        "maxResults": 100,
    })
    return data.get("issues", []) if data else []


# ── Action Handlers ───────────────────────────────────────────────────────────

def handle_sprint_move(ticket_key, sprint_label, chat_id, bot):
    """Move a ticket (+ children if Epic) to a named sprint."""
    sprint = find_sprint_by_label(sprint_label)
    if not sprint:
        bot.send_message(chat_id, f"❌ No sprint found matching '{sprint_label}'.")
        return

    sprint_id = sprint["id"]
    sprint_name = sprint.get("name", str(sprint_id))

    issue = jira_get(f"/rest/api/3/issue/{ticket_key}", params={"fields": "issuetype"})
    is_epic = issue and issue.get("fields", {}).get("issuetype", {}).get("name") == "Epic"

    keys_to_move = [ticket_key]
    if is_epic:
        children = get_epic_children(ticket_key)
        keys_to_move.extend(c["key"] for c in children)

    moved = sum(1 for key in keys_to_move if move_to_sprint(key, sprint_id))

    # Assign to Andrej and transition to Ready
    assigned = sum(1 for key in keys_to_move if assign_issue(key, ANDREJ_ACCOUNT_ID))
    transitioned = sum(1 for key in keys_to_move if transition_issue(key, READY_TRANSITION_ID))

    link = f"https://axiscrm.atlassian.net/browse/{ticket_key}"
    suffix = f" (epic + {len(keys_to_move)-1} children)" if is_epic and len(keys_to_move) > 1 else ""
    bot.send_message(chat_id,
        f"📅 [{ticket_key}]({link}) → *{sprint_name}*\n"
        f"Moved {moved}/{len(keys_to_move)} · Assigned: {assigned} · Ready: {transitioned}{suffix}\n\n"
        f"Send another ticket ID, or /done to exit.",
        parse_mode="Markdown", disable_web_page_preview=True)
    log.info(f"PO: Moved {ticket_key}{suffix} to '{sprint_name}' (assigned={assigned}, ready={transitioned})")


def handle_backlog_move(ticket_key, chat_id, bot):
    """Move a ticket (+ children if Epic) to backlog."""
    issue = jira_get(f"/rest/api/3/issue/{ticket_key}", params={"fields": "issuetype"})
    is_epic = issue and issue.get("fields", {}).get("issuetype", {}).get("name") == "Epic"

    keys_to_move = [ticket_key]
    if is_epic:
        children = get_epic_children(ticket_key)
        keys_to_move.extend(c["key"] for c in children)

    ok, _ = jira_post("/rest/agile/1.0/backlog/issue", {"issues": keys_to_move})

    link = f"https://axiscrm.atlassian.net/browse/{ticket_key}"
    suffix = f" ({len(keys_to_move)} issues)" if len(keys_to_move) > 1 else ""
    if ok:
        bot.send_message(chat_id,
            f"📋 [{ticket_key}]({link}) → *Backlog*{suffix}\n\n"
            f"Send another ticket ID, or /done to exit.",
            parse_mode="Markdown", disable_web_page_preview=True)
    else:
        bot.send_message(chat_id, f"❌ Failed to move {ticket_key} to backlog.")
    log.info(f"PO: Moved {ticket_key} to backlog (ok={ok})")


# ARU type mapping (ARU only has Task, Bug, Story, Epic, Subtask)
ARCHIVE_TYPE_MAP = {
    "Task": "Task", "Bug": "Bug", "Epic": "Epic", "Subtask": "Subtask",
    "Spike": "Task", "Support": "Task", "Maintenance": "Task", "Story": "Story",
    "Idea": "Task",
}


def handle_archive(ticket_key, chat_id, bot):
    """Archive a ticket: AX/AR → move to ARU project. Epics include children."""
    issue = jira_get(f"/rest/api/3/issue/{ticket_key}", params={"fields": "issuetype,project"})
    if not issue:
        bot.send_message(chat_id, f"❌ Couldn't find {ticket_key}.")
        return

    project_key = issue.get("fields", {}).get("project", {}).get("key", "")
    itype = issue.get("fields", {}).get("issuetype", {}).get("name", "")
    is_epic = itype == "Epic"

    # Collect keys to archive
    keys_to_archive = [(ticket_key, itype)]
    if is_epic and project_key == "AX":
        children = get_epic_children(ticket_key)
        for c in children:
            child_type = c.get("fields", {}).get("issuetype", {}).get("name", "Task")
            keys_to_archive.append((c["key"], child_type))

    archived = 0
    for key, it in keys_to_archive:
        target_type = ARCHIVE_TYPE_MAP.get(it, "Task")
        try:
            r = requests.put(
                f"{JIRA_BASE_URL}/rest/api/3/issue/{key}",
                json={"fields": {"project": {"key": "ARU"}, "issuetype": {"name": target_type}}},
                auth=auth,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                timeout=15,
            )
            if r.status_code in (200, 204):
                archived += 1
            else:
                log.warning(f"Archive {key}: {r.status_code} {r.text[:200]}")
        except Exception as e:
            log.warning(f"Archive {key}: {e}")

    link = f"https://axiscrm.atlassian.net/browse/{ticket_key}"
    suffix = f" (epic + {len(keys_to_archive)-1} children)" if is_epic and len(keys_to_archive) > 1 else ""
    bot.send_message(chat_id,
        f"🗄️ [{ticket_key}]({link}) → *ARU*\n"
        f"Archived {archived}/{len(keys_to_archive)} issues{suffix}\n\n"
        f"Send another ticket ID, or /done to exit.",
        parse_mode="Markdown", disable_web_page_preview=True)
    log.info(f"PO: Archived {ticket_key}{suffix} to ARU ({archived}/{len(keys_to_archive)})")


def handle_pm5_trigger(ticket_key, chat_id, bot, state, user_state):
    """Generate spike plan for an Epic and show preview."""
    issue = jira_get(f"/rest/api/3/issue/{ticket_key}", params={
        "fields": "summary,issuetype,description,issuelinks"
    })
    if not issue:
        bot.send_message(chat_id, f"❌ Couldn't find {ticket_key}.")
        return
    itype = issue.get("fields", {}).get("issuetype", {}).get("name", "")
    if itype != "Epic":
        bot.send_message(chat_id, f"❌ PM5 only works on Epics. {ticket_key} is a {itype}.")
        return

    epic_title = issue["fields"].get("summary", "")
    desc_adf = issue["fields"].get("description") or {}
    desc_text = _extract_adf_text(desc_adf) if isinstance(desc_adf, dict) else str(desc_adf)

    # Find PRD link + prototype link in description
    status_msg = bot.send_message(chat_id, f"📝 Finding PRD for {ticket_key}...")
    prd_content = ""
    prd_url = ""
    prototype_url = "N/A"

    prd_urls = re.findall(r'https?://axiscrm\.atlassian\.net/wiki/\S+', desc_text)
    for url in prd_urls:
        m = re.search(r'/pages/(\d+)', url)
        if m and m.group(1) != "91062273":  # Skip DoR/DoD page
            prd_url = url
            try:
                r = requests.get(
                    f"{CONFLUENCE_BASE}/api/v2/pages/{m.group(1)}?body-format=atlas_doc_format",
                    auth=auth, headers=headers, timeout=10,
                )
                if r.status_code == 200:
                    page = r.json()
                    body_val = page.get("body", {}).get("atlas_doc_format", {}).get("value", "")
                    if body_val:
                        parsed = json.loads(body_val) if isinstance(body_val, str) else body_val
                        prd_content = _extract_adf_text(parsed)
                        break
            except Exception as e:
                log.warning(f"PM5: Failed to fetch Confluence page: {e}")

    # Find prototype URL
    proto_match = re.search(r'https?://james-axis\.github\.io/\S+', desc_text)
    if proto_match:
        prototype_url = proto_match.group(0)

    if not prd_content:
        try:
            bot.delete_message(chat_id, status_msg.message_id)
        except Exception:
            pass
        bot.send_message(chat_id, f"❌ No PRD found in {ticket_key}'s description. Add a Confluence PRD link first.")
        return

    # Resolve target sprint from AR idea roadmap
    source_idea_key = ""
    ar_match = re.search(r'(AR-\d+)', desc_text)
    if ar_match:
        source_idea_key = ar_match.group(1)
    else:
        for link in issue["fields"].get("issuelinks") or []:
            for direction in ("outwardIssue", "inwardIssue"):
                linked = link.get(direction)
                if linked and linked.get("key", "").startswith("AR-"):
                    source_idea_key = linked["key"]
                    break
            if source_idea_key:
                break

    target_sprint = ""
    if source_idea_key:
        ar_issue = jira_get(f"/rest/api/3/issue/{source_idea_key}", params={"fields": ROADMAP_FIELD})
        if ar_issue:
            rf = ar_issue.get("fields", {}).get(ROADMAP_FIELD)
            if rf:
                val = rf.get("value", "") if isinstance(rf, dict) else str(rf)
                if val.lower() not in ("backlog", "shipped", "delivered", ""):
                    target_sprint = val

    # Generate spike plan
    bot.edit_message_text("📝 Generating spike plan...", chat_id, status_msg.message_id)

    from claude_client import generate_spike_plan
    spike = generate_spike_plan(
        ticket_key, epic_title, prd_content,
        prototype_url=prototype_url,
        prd_url=prd_url,
        target_sprint=target_sprint,
    )

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if not spike or not isinstance(spike, dict):
        bot.send_message(chat_id, "❌ AI failed to generate spike plan.")
        return

    tshirt = spike.get("tshirt_size", "?")

    # Build preview
    ac_lines = "\n".join(f"  • {ac}" for ac in spike.get("acceptance_criteria", []))
    at_lines = "\n".join(f"  • {at}" for at in spike.get("architectural_thoughts", []))

    lines = [
        f"📝 *{ticket_key} — Spike Plan* ({tshirt})\n",
        f"*{spike.get('summary', epic_title)}*\n",
        f"*Acceptance criteria:*\n{ac_lines}\n",
        f"*Architectural thoughts:*\n{at_lines}",
        f"\n✅ *approve* | 🔄 describe changes | ⛔ *cancel*",
    ]

    bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")

    state["pm5_pending"] = {
        "spike": spike,
        "epic_key": ticket_key,
        "epic_title": epic_title,
        "prd_content": prd_content,
        "prd_url": prd_url,
        "prototype_url": prototype_url,
        "target_sprint": target_sprint,
    }
    user_state[chat_id] = state
    log.info(f"PO PM5: Generated spike plan for {ticket_key} ({tshirt})")


def handle_pm5_approval(chat_id, bot, state, user_state):
    """Create spike from an approved PM5 plan."""
    from jira_client import create_spike, jira_put
    pm5 = state.get("pm5_pending")
    if not pm5:
        return

    epic_key = pm5["epic_key"]
    spike = pm5["spike"]
    target_sprint = pm5.get("target_sprint", "")

    status_msg = bot.send_message(chat_id, f"📝 Creating spike under {epic_key}...")

    spike_key, spike_url = create_spike(
        epic_key=epic_key,
        spike_data=spike,
        prd_url=pm5.get("prd_url", ""),
        prototype_url=pm5.get("prototype_url", "N/A"),
        target_sprint=target_sprint,
    )

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if not spike_key:
        bot.send_message(chat_id, f"❌ Failed to create spike under {epic_key}.")
        state.pop("pm5_pending", None)
        user_state[chat_id] = state
        return

    # Set 3 SP
    jira_put(f"/rest/api/3/issue/{spike_key}", {"fields": {STORY_POINTS_FIELD: 3.0}})

    # Move spike to S-2 (2 sprints before target), epic to target sprint
    sprint_status = ""
    if target_sprint:
        # Spike goes to S-2 for early investigation
        spike_sprint, offset = find_sprint_with_offset(target_sprint, offset=-2)
        if spike_sprint:
            move_to_sprint(spike_key, spike_sprint["id"])
            offset_label = f"S{offset}" if offset < 0 else "target"
            sprint_status = f" · Spike → {spike_sprint.get('name', '?')} ({offset_label})"

        # Epic goes to target sprint
        target = find_sprint_by_label(target_sprint)
        if target:
            move_to_sprint(epic_key, target["id"])
            sprint_status += f" · Epic → {target.get('name', target_sprint)}"

    assign_issue(spike_key, ANDREJ_ACCOUNT_ID)
    assign_issue(epic_key, ANDREJ_ACCOUNT_ID)
    transition_issue(spike_key, READY_TRANSITION_ID)
    transition_issue(epic_key, READY_TRANSITION_ID)

    tshirt = spike.get("tshirt_size", "?")
    link = f"https://axiscrm.atlassian.net/browse/{spike_key}"
    epic_link = f"https://axiscrm.atlassian.net/browse/{epic_key}"
    bot.send_message(chat_id,
        f"✅ [{spike_key}]({link}) created under [{epic_key}]({epic_link})\n"
        f"3 SP · {tshirt} · Assigned: Andrej · Ready\n{sprint_status}\n\n"
        f"Send another ticket ID, or /done to exit.",
        parse_mode="Markdown", disable_web_page_preview=True)

    state.pop("pm5_pending", None)
    state.pop("ticket_key", None)
    user_state[chat_id] = state
    log.info(f"PO PM5: Created Spike {spike_key} under {epic_key} (3 SP){sprint_status}")


def handle_pm5_changes(change_text, chat_id, bot, state, user_state):
    """Regenerate PM5 spike plan with change instructions."""
    pm5 = state.get("pm5_pending")
    if not pm5:
        return

    status_msg = bot.send_message(chat_id, "🔄 Regenerating spike plan...")

    prompt = f"""You previously generated this spike plan:
{json.dumps(pm5['spike'], indent=2)}

Changes requested: {change_text}

<prd>
{pm5['prd_content'][:6000]}
</prd>

Apply changes. Same JSON format, no fences."""

    response = call_claude(prompt, max_tokens=4000)

    try:
        bot.delete_message(chat_id, status_msg.message_id)
    except Exception:
        pass

    if not response:
        bot.send_message(chat_id, "❌ Failed to regenerate. Try again.")
        return

    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response)
        clean = re.sub(r'\s*```$', '', clean)
        spike = json.loads(clean)
    except json.JSONDecodeError:
        bot.send_message(chat_id, "❌ Failed to parse. Try again.")
        return

    if isinstance(spike, list) and spike:
        spike = spike[0]

    pm5["spike"] = spike
    tshirt = spike.get("tshirt_size", "?")

    ac_lines = "\n".join(f"  • {ac}" for ac in spike.get("acceptance_criteria", []))
    at_lines = "\n".join(f"  • {at}" for at in spike.get("architectural_thoughts", []))

    lines = [
        f"📝 *{pm5['epic_key']} — Spike Plan* ({tshirt})\n",
        f"*{spike.get('summary', pm5['epic_title'])}*\n",
        f"*Acceptance criteria:*\n{ac_lines}\n",
        f"*Architectural thoughts:*\n{at_lines}",
        f"\n✅ *approve* | 🔄 describe more changes | ⛔ *cancel*",
    ]

    bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")
    user_state[chat_id] = state


def handle_pm7_trigger(ticket_key, chat_id, bot, state, user_state):
    """Read source AR idea's Roadmap field and move Epic to matching sprint."""
    issue = jira_get(f"/rest/api/3/issue/{ticket_key}", params={
        "fields": "summary,issuetype,description,issuelinks"
    })
    if not issue:
        bot.send_message(chat_id, f"❌ Couldn't find {ticket_key}.")
        return
    itype = issue.get("fields", {}).get("issuetype", {}).get("name", "")
    if itype != "Epic":
        bot.send_message(chat_id, f"❌ PM7 only works on Epics. {ticket_key} is a {itype}.")
        return

    # Try to find AR idea: first in description, then in issue links
    source_idea_key = None

    # 1. Check description text
    desc_adf = issue["fields"].get("description") or {}
    desc_text = _extract_adf_text(desc_adf) if isinstance(desc_adf, dict) else str(desc_adf)
    ar_match = re.search(r'(AR-\d+)', desc_text)
    if ar_match:
        source_idea_key = ar_match.group(1)

    # 2. Fallback: check issue links for AR ideas
    if not source_idea_key:
        for link in issue["fields"].get("issuelinks") or []:
            for direction in ("outwardIssue", "inwardIssue"):
                linked = link.get(direction)
                if linked and linked.get("key", "").startswith("AR-"):
                    source_idea_key = linked["key"]
                    break
            if source_idea_key:
                break

    if not source_idea_key:
        bot.send_message(chat_id, f"❌ No AR idea linked to {ticket_key}. Add an AR link or use a sprint name directly (e.g. `April (S1)`).")
        return
    status_msg = bot.send_message(chat_id, f"📅 Reading roadmap from {source_idea_key}...")

    ar_issue = jira_get(f"/rest/api/3/issue/{source_idea_key}", params={"fields": ROADMAP_FIELD})
    if not ar_issue:
        try: bot.delete_message(chat_id, status_msg.message_id)
        except Exception: pass
        bot.send_message(chat_id, f"❌ Couldn't fetch {source_idea_key}.")
        return

    roadmap_field = ar_issue.get("fields", {}).get(ROADMAP_FIELD)
    if not roadmap_field:
        try: bot.delete_message(chat_id, status_msg.message_id)
        except Exception: pass
        bot.send_message(chat_id, f"⚠️ No Roadmap field set on {source_idea_key}.")
        return

    roadmap_value = roadmap_field.get("value", "") if isinstance(roadmap_field, dict) else str(roadmap_field)
    if roadmap_value.lower() in ("backlog", "shipped", "delivered", ""):
        try: bot.delete_message(chat_id, status_msg.message_id)
        except Exception: pass
        bot.send_message(chat_id, f"⚠️ {source_idea_key} Roadmap = '{roadmap_value}' — not a sprint target.")
        return

    try: bot.delete_message(chat_id, status_msg.message_id)
    except Exception: pass

    handle_sprint_move(ticket_key, roadmap_value, chat_id, bot)
    state.pop("ticket_key", None)
    user_state[chat_id] = state
    log.info(f"PO PM7: {ticket_key} via {source_idea_key} Roadmap='{roadmap_value}'")


# ── Main Update Processor ────────────────────────────────────────────────────

def process_update(text, chat_id, bot, state, user_state):
    """Process an /update instruction. Handles PO actions + AI field updates."""
    ticket_key = state.get("ticket_key")
    instruction = text

    # ── PM5 approval flow ──
    if state.get("pm5_pending"):
        lower = text.strip().lower()
        if lower in ("approve", "yes", "go", "create", "ok"):
            handle_pm5_approval(chat_id, bot, state, user_state)
            return
        elif lower in ("cancel", "abort", "no", "stop"):
            epic_key = state["pm5_pending"]["epic_key"]
            state.pop("pm5_pending", None)
            state.pop("ticket_key", None)
            user_state[chat_id] = state
            bot.send_message(chat_id, f"⛔ {epic_key} task breakdown cancelled.\n\nSend another ticket ID, or /done to exit.")
            return
        else:
            handle_pm5_changes(text, chat_id, bot, state, user_state)
            return

    # ── Extract ticket key ──
    if not ticket_key:
        ticket_key, instruction = extract_ticket_key(text)
        if not ticket_key:
            bot.send_message(chat_id, "❓ Send a ticket ID (e.g. `AX-426`).", parse_mode="Markdown")
            return
        state["ticket_key"] = ticket_key
        user_state[chat_id] = state

    # ── No instruction: show ticket and wait ──
    if not instruction:
        bot.send_message(chat_id, f"🔍 Loading {ticket_key}...")
        issue = jira_get(f"/rest/api/3/issue/{ticket_key}", params={
            "fields": f"summary,issuetype,status,{STORY_POINTS_FIELD},customfield_10020"
        })
        if not issue or "fields" not in issue:
            bot.send_message(chat_id, f"❌ Couldn't find {ticket_key}.")
            state.pop("ticket_key", None)
            return

        f = issue["fields"]
        summary = f.get("summary", "")
        itype = f.get("issuetype", {}).get("name", "?")
        status = f.get("status", {}).get("name", "?")

        sprint_info = ""
        sprints = f.get("customfield_10020") or []
        if isinstance(sprints, list) and sprints:
            sprint_info = f" · {sprints[-1].get('name', '?')}"

        bot.send_message(chat_id,
            f"✏️ *{ticket_key}* ({itype} · {status}{sprint_info})\n"
            f"_{summary}_\n\n"
            f"What do you want to do?",
            parse_mode="Markdown")
        return

    # ── Detect PO actions ──
    action, param = detect_action(instruction)

    if action == "sprint":
        handle_sprint_move(ticket_key, param, chat_id, bot)
        state.pop("ticket_key", None)
        user_state[chat_id] = state
        return

    if action == "backlog":
        handle_backlog_move(ticket_key, chat_id, bot)
        state.pop("ticket_key", None)
        user_state[chat_id] = state
        return

    if action == "archive":
        handle_archive(ticket_key, chat_id, bot)
        state.pop("ticket_key", None)
        user_state[chat_id] = state
        return

    if action == "pm5":
        handle_pm5_trigger(ticket_key, chat_id, bot, state, user_state)
        return

    if action == "pm7":
        handle_pm7_trigger(ticket_key, chat_id, bot, state, user_state)
        return

    # ── Fall through: AI-powered field update ──
    bot.send_message(chat_id, f"✏️ Updating {ticket_key}...")

    issue = jira_get(f"/rest/api/3/issue/{ticket_key}", params={
        "fields": f"summary,issuetype,status,{STORY_POINTS_FIELD},description"
    })
    if not issue or "fields" not in issue:
        bot.send_message(chat_id, f"❌ Couldn't find {ticket_key}.")
        return

    f = issue["fields"]
    current_summary = f.get("summary", "")
    itype = f.get("issuetype", {}).get("name", "Task")
    current_sp = f.get(STORY_POINTS_FIELD)
    desc_adf = f.get("description") or {}
    current_desc_text = _extract_adf_text(desc_adf) if isinstance(desc_adf, dict) else ""

    prompt = f"""Apply an update to this Jira ticket based on the instruction.

TICKET: {ticket_key} ({itype})
Summary: {current_summary} | SP: {current_sp}
Description:
{current_desc_text}

INSTRUCTION: {instruction}

JSON only (no fences):

{{
  "summary": "Updated summary or null",
  "story_points": null,
  "description_changes": "What changed, or null",
  "updated_description": "FULL updated description in markdown preserving template structure, or null"
}}

RULES:
- Only change what's asked. Preserve everything else.
- SP must be 0.25, 0.5, 1, 2, or 3. Set null if unchanged.
- Preserve PM/Engineer sections and DoR/DoD links.
- Be concise in all content."""

    response = call_claude(prompt, max_tokens=4096)
    if not response:
        bot.send_message(chat_id, "❌ AI processing failed.")
        return

    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response)
        clean = re.sub(r'\s*```$', '', clean)
        updates = json.loads(clean)
    except json.JSONDecodeError as e:
        log.error(f"Update parse error: {e}\nRaw: {response[:500]}")
        bot.send_message(chat_id, "❌ Failed to parse AI response. Try rephrasing.")
        return

    new_summary = updates.get("summary")
    new_sp = updates.get("story_points")
    new_desc = updates.get("updated_description")

    changes = []
    if new_summary and new_summary != current_summary:
        changes.append(f"📝 Summary → _{new_summary}_")
    if new_sp is not None and new_sp != current_sp:
        changes.append(f"🎯 Story Points → {new_sp}")
    if new_desc:
        desc_change = updates.get("description_changes", "Description updated")
        changes.append(f"📄 {desc_change}")

    if not changes:
        bot.send_message(chat_id, f"🤷 No changes needed for {ticket_key}.")
        return

    # Apply via API
    update_fields = {}
    if new_summary and new_summary != current_summary:
        update_fields["summary"] = new_summary
    if new_sp is not None:
        update_fields[STORY_POINTS_FIELD] = float(new_sp)
    if new_desc:
        from jira_client import markdown_to_adf
        update_fields["description"] = markdown_to_adf(new_desc)

    if update_fields:
        ok, resp = jira_put_fields(ticket_key, update_fields)
    else:
        ok = True

    if ok:
        link = f"https://axiscrm.atlassian.net/browse/{ticket_key}"
        change_list = "\n".join(changes)
        bot.send_message(chat_id,
            f"✅ *{ticket_key} updated:*\n{change_list}\n\n"
            f"[Open ticket]({link})\n\n"
            f"Send another ticket ID, or /done to exit.",
            parse_mode="Markdown", disable_web_page_preview=True)
    else:
        bot.send_message(chat_id, f"❌ Failed to update {ticket_key}.")

    state.pop("ticket_key", None)
    user_state[chat_id] = state


def jira_put_fields(issue_key, fields):
    """Update issue fields via PUT."""
    try:
        r = requests.put(
            f"{JIRA_BASE_URL}/rest/api/3/issue/{issue_key}",
            json={"fields": fields},
            auth=auth,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
            timeout=15,
        )
        return r.status_code == 204, r
    except Exception as e:
        log.error(f"jira_put_fields {issue_key}: {e}")
        return False, None
