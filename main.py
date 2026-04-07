"""
PM Agent — Entry Point
Telegram bot + scheduled automatic jobs.
"""

import threading
import pytz
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from config import log, TELEGRAM_BOT_TOKEN, JIRA_EMAIL, JIRA_API_TOKEN, ANTHROPIC_API_KEY
from telegram_bot import start_polling


def preflight_check():
    """Verify required environment variables are set."""
    missing = []
    if not JIRA_EMAIL:
        missing.append("JIRA_EMAIL")
    if not JIRA_API_TOKEN:
        missing.append("JIRA_API_TOKEN")
    if not ANTHROPIC_API_KEY:
        missing.append("ANTHROPIC_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")

    if missing:
        log.error(f"Missing required env vars: {', '.join(missing)}")
        return False

    log.info("Preflight check passed — all required env vars set.")
    return True


if __name__ == "__main__":
    log.info("=== PM Agent starting ===")

    if not preflight_check():
        log.error("Aborting — fix environment variables and restart.")
        exit(1)

    sydney_tz = pytz.timezone("Australia/Sydney")
    scheduler = BlockingScheduler(timezone=sydney_tz)

    # JOB A1: Sprint lifecycle check — every 30 min during business hours
    def run_sprint_lifecycle():
        from po_actions_automatic import check_sprint_lifecycle
        try:
            check_sprint_lifecycle()
        except Exception as e:
            log.error(f"Sprint lifecycle failed: {e}", exc_info=True)

    scheduler.add_job(
        run_sprint_lifecycle,
        trigger=CronTrigger(day_of_week="mon-fri", hour="6-22", minute="0,30", timezone=sydney_tz),
        id="sprint_lifecycle",
        name="Sprint lifecycle check (30min)",
    )
    log.info("Sprint lifecycle scheduled — every 30min (6am-10:30pm Mon-Fri AEST).")

    # Start Telegram bot in a daemon thread
    if TELEGRAM_BOT_TOKEN:
        tg_thread = threading.Thread(target=start_polling, daemon=True)
        tg_thread.start()
        log.info("Telegram bot thread started.")
    else:
        log.warning("Telegram bot skipped — TELEGRAM_BOT_TOKEN not set.")

    # Run sprint lifecycle once at startup
    run_sprint_lifecycle()

    scheduler.start()
