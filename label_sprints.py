"""
PM Agent — JOB A13: Label bucket-sprints

Jira allows only one Backlog (home for Support tasks). To give each board custom
filter its own "backlog", we maintain one future sprint per custom filter
(excl. Support), named after the filter. They are DATE-LESS so Jira lists them at
the bottom of the backlog (below the dated "Sprint N" runway sprints). Users drag
tickets in themselves.

Each run it:
  1. reads the board's custom quick filters (excl. Support),
  2. ensures a date-less sprint named after each filter exists,
  3. clears dates off any bucket that has them (keeping them at the bottom).

Bucket sprints are named after the filter (NOT "Sprint N"), so is_runway_sprint()
keeps them out of the runway count, date resequencing, and close/start selection.
"""

from config import log
from jira_client import (
    get_future_sprints, is_runway_sprint, get_board_quickfilters,
    create_sprint_no_dates, clear_sprint_dates,
)
from telegram_bot import send_telegram


def sync_label_sprints():
    """Ensure a date-less bucket-sprint per board custom filter (excl. Support).
    Creates missing ones and strips dates off any that have them. Returns count touched."""
    log.info("JOB A13: Syncing label bucket-sprints...")

    filters = get_board_quickfilters(exclude=("support",))
    if not filters:
        log.info("JOB A13: No custom filters found.")
        return 0

    # Existing bucket sprints (non-runway future sprints), keyed by lowercase name
    existing = {s["name"].strip().lower(): s
                for s in get_future_sprints() if not is_runway_sprint(s)}

    created, cleared = 0, 0
    for name in filters:
        s = existing.get(name.strip().lower())
        if s:
            if s.get("startDate") or s.get("endDate"):
                if clear_sprint_dates(s["id"]):
                    cleared += 1
        else:
            if create_sprint_no_dates(name):
                created += 1

    log.info(f"JOB A13: Label sprints — {created} created, {cleared} date-cleared.")
    if created or cleared:
        send_telegram(
            f"🏷 *Label sprints* — {created} created, {cleared} date-cleared\n"
            f"({len(filters)} filter bucket(s), kept date-less at the bottom)"
        )
    return created + cleared
