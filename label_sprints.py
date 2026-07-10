"""
PM Agent — JOB A13: Label bucket-sprints

Jira allows only one Backlog (home for Support tasks). To give each board custom
filter its own "backlog", we maintain one future sprint per custom filter
(excl. Support), named after the filter, dated just BEYOND the 8 reviewed runway
sprints so it sits directly above the Backlog on the board. Users drag tickets
in themselves.

Each run (weekly) it:
  1. reads the board's custom quick filters (excl. Support),
  2. ensures a sprint named after each filter exists,
  3. pushes every bucket's dates to stay past the current 8th runway sprint.

Bucket sprints are named after the filter (NOT "Sprint N"), so is_runway_sprint()
keeps them out of the runway count and the weekly close/start selection.
"""

from datetime import datetime, timedelta
import pytz

from config import log
from jira_client import (
    get_future_sprints, get_active_sprints, is_runway_sprint,
    get_board_quickfilters, create_sprint, update_sprint_dates,
)
from telegram_bot import send_telegram

AEST = pytz.timezone("Australia/Sydney")


def _parse_dt(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _bucket_window():
    """(start, end) for the buckets — a week-long window just past the last
    runway sprint, so buckets always sit beyond the reviewed 8 and get pushed
    forward as the runway advances."""
    runway = [s for s in (get_future_sprints() + get_active_sprints()) if is_runway_sprint(s)]
    ends = [d for d in (_parse_dt(s.get("endDate")) for s in runway) if d]
    anchor = max(ends) if ends else datetime.now(AEST) + timedelta(weeks=8)
    anchor = anchor.astimezone(AEST)
    start = anchor + timedelta(days=7)
    end = start + timedelta(days=5)
    return start, end


def sync_label_sprints():
    """Ensure a bucket-sprint per board custom filter (excl. Support), dated beyond
    the runway. Creates missing ones and pushes existing ones out. Returns count touched."""
    log.info("JOB A13: Syncing label bucket-sprints...")

    filters = get_board_quickfilters(exclude=("support",))
    if not filters:
        log.info("JOB A13: No custom filters found.")
        return 0

    start, end = _bucket_window()

    # Existing bucket sprints, keyed by lowercase name
    existing = {s["name"].strip().lower(): s
                for s in get_future_sprints() if not is_runway_sprint(s)}

    created, pushed = 0, 0
    for name in filters:
        s = existing.get(name.strip().lower())
        if s:
            if update_sprint_dates(s["id"], start, end):
                pushed += 1
        else:
            if create_sprint(name, start, end):
                created += 1

    log.info(f"JOB A13: Label sprints — {created} created, {pushed} pushed "
             f"(window {start.date()}–{end.date()}).")
    if created or pushed:
        send_telegram(
            f"🏷 *Label sprints* — {created} created, {pushed} pushed out\n"
            f"({len(filters)} filter bucket(s), dated to {start.strftime('%d/%m')})"
        )
    return created + pushed
