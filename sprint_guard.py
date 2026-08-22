"""
Sprint Guard — keeps the active sprint honest.

Detects tickets added to the OPEN sprint after planning (i.e. not in the
committed baseline) and, for each one:
  • adds the `unplanned` label
  • posts a Slack alert naming who added it and what

If SPRINT_GUARD_ENFORCE is on, it ALSO returns the ticket to the backlog.
Default is flag-and-notify (non-destructive) so nothing is yanked silently —
visibility alone tends to change behaviour. Flip the env flag to escalate.

Baseline (the committed set of issue keys) is stored as a Jira sprint entity
property, so it survives redeploys and is tied to the sprint. It is captured
automatically the first time the guard sees a new active sprint, and can be
re-captured after planning via the /snapshotsprint Telegram command.

Exemptions: tickets added by an allow-listed account (the PO) or carrying the
`planned-swap` label are treated as intentional and left alone.
"""

from config import (log, SPRINT_GUARD_ENFORCE, SPRINT_GUARD_ALLOWLIST,
                    UNPLANNED_LABEL, PLANNED_SWAP_LABEL)
from jira_client import (get_active_sprints, get_sprint_issues, add_label,
                         move_issue_to_backlog, get_sprint_property,
                         set_sprint_property, get_issue_labels, get_sprint_add_actor)
from slack_client import post_slack_message

BASELINE_PROP = "pmagent_sprint_baseline"
JIRA_BROWSE = "https://axiscrm.atlassian.net/browse/"


def _capture_baseline(sprint):
    """Snapshot the sprint's current issues as the committed baseline."""
    keys = [i["key"] for i in get_sprint_issues(sprint["id"])]
    set_sprint_property(sprint["id"], BASELINE_PROP, {
        "sprint_id": sprint["id"],
        "sprint_name": sprint["name"],
        "keys": keys,
    })
    log.info(f"Sprint guard: baseline captured for {sprint['name']} ({len(keys)} issues).")
    return set(keys)


def snapshot_active_sprint():
    """Manually (re)capture the committed baseline for the active sprint.
    Run this right after planning so the fresh commitment becomes the baseline.
    Returns (sprint_name, issue_count) or (None, 0)."""
    sprints = get_active_sprints()
    if not sprints:
        return None, 0
    s = sprints[0]
    keys = _capture_baseline(s)
    return s["name"], len(keys)


def _alert(sprint_name, key, summary, who, action_note):
    """Post the unplanned-ticket alert to Slack (Telegram fallback)."""
    who_txt = who or "someone"
    url = f"{JIRA_BROWSE}{key}"
    lines = [
        f"🚧 *Unplanned ticket added to {sprint_name}*",
        f"<{url}|{key}> — {summary}",
        f"Added by *{who_txt}* — not part of the committed sprint.",
    ]
    if action_note:
        lines.append(action_note)
    text = "\n".join(lines)
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": text}}]
    ok, err = post_slack_message(blocks=blocks, text=f"Unplanned ticket in {sprint_name}: {key}")
    if not ok:
        try:
            from telegram_bot import send_telegram
            send_telegram(f"🚧 Unplanned ticket in {sprint_name}: {key} — {summary} "
                          f"(added by {who_txt}). [Slack failed: {err}]")
        except Exception:
            log.error(f"Sprint guard: alert failed for {key} (Slack err: {err})")


def run_sprint_guard():
    """One pass of the guard. Returns the number of unplanned tickets handled."""
    sprints = get_active_sprints()
    if not sprints:
        log.info("Sprint guard: no active sprint.")
        return 0
    sprint = sprints[0]
    sid = sprint["id"]

    stored = get_sprint_property(sid, BASELINE_PROP)
    current = {i["key"]: i for i in get_sprint_issues(sid)}

    # First time we see this sprint → baseline it now, flag nothing this pass.
    if not stored or stored.get("sprint_id") != sid:
        _capture_baseline(sprint)
        return 0

    baseline = set(stored.get("keys", []))
    new_keys = [k for k in current if k not in baseline]
    if not new_keys:
        return 0

    handled = 0
    for key in new_keys:
        labels = get_issue_labels(key)
        # Intentional additions are exempt.
        if PLANNED_SWAP_LABEL in labels:
            continue
        who, acct, _when = get_sprint_add_actor(key, sid)
        if acct and acct in SPRINT_GUARD_ALLOWLIST:
            continue

        already_flagged = UNPLANNED_LABEL in labels
        # In flag-only mode, don't re-ping a ticket we've already flagged.
        if already_flagged and not SPRINT_GUARD_ENFORCE:
            continue

        if not already_flagged:
            add_label(key, UNPLANNED_LABEL)

        action_note = ""
        if SPRINT_GUARD_ENFORCE:
            if move_issue_to_backlog(key):
                action_note = "↩️ *Returned to the backlog.*"
            else:
                action_note = "⚠️ _Could not auto-return — please move it back manually._"

        summary = current[key]["fields"].get("summary", "")
        _alert(sprint["name"], key, summary, who, action_note)
        handled += 1

    mode = "enforce" if SPRINT_GUARD_ENFORCE else "flag"
    log.info(f"Sprint guard ({mode}): handled {handled} unplanned ticket(s) in {sprint['name']}.")
    return handled
