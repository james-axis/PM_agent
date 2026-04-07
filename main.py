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

    # JOB A1: Sprint turnover — Monday 6am AEST (fully automated)
    def run_sprint_lifecycle():
        from po_actions_automatic import run_sprint_turnover
        try:
            run_sprint_turnover()
        except Exception as e:
            log.error(f"Sprint turnover failed: {e}", exc_info=True)

    scheduler.add_job(
        run_sprint_lifecycle,
        trigger=CronTrigger(day_of_week="mon", hour=6, minute=0, timezone=sydney_tz),
        id="sprint_turnover",
        name="Sprint turnover (Monday 6am)",
    )
    log.info("Sprint turnover scheduled — Monday 6am AEST.")

    # JOB A4: Friday sprint reminder — 4:30pm AEST every Friday
    def run_friday_reminders():
        from po_actions_automatic import post_friday_reminders
        try:
            post_friday_reminders()
        except Exception as e:
            log.error(f"Friday reminders failed: {e}", exc_info=True)

    scheduler.add_job(
        run_friday_reminders,
        trigger=CronTrigger(day_of_week="fri", hour=16, minute=30, timezone=sydney_tz),
        id="friday_reminders",
        name="Friday sprint reminder (4:30pm)",
    )
    log.info("Friday sprint reminder scheduled — Friday 4:30pm AEST.")

    # JOB A5: Weekly Product Update — Friday 9am AEST
    def run_weekly_update():
        from weekly_update import generate_weekly_update
        try:
            generate_weekly_update()
        except Exception as e:
            log.error(f"Weekly update failed: {e}", exc_info=True)

    scheduler.add_job(
        run_weekly_update,
        trigger=CronTrigger(day_of_week="fri", hour=9, minute=0, timezone=sydney_tz),
        id="weekly_update",
        name="Product Weekly (Friday 9am)",
    )
    log.info("Product Weekly scheduled — Friday 9am AEST.")

    # Start Telegram bot in a daemon thread
    if TELEGRAM_BOT_TOKEN:
        tg_thread = threading.Thread(target=start_polling, daemon=True)
        tg_thread.start()
        log.info("Telegram bot thread started.")
    else:
        log.warning("Telegram bot skipped — TELEGRAM_BOT_TOKEN not set.")

    scheduler.start()
