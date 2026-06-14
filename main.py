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

    # JOB A1: Sprint close — Sunday 10pm AEST (close sprint, carry over)
    def run_sprint_close_job():
        from po_actions_automatic import run_sprint_close
        try:
            run_sprint_close()
        except Exception as e:
            log.error(f"Sprint close failed: {e}", exc_info=True)

    scheduler.add_job(
        run_sprint_close_job,
        trigger=CronTrigger(day_of_week="sun", hour=22, minute=0, timezone=sydney_tz),
        id="sprint_close",
        name="Sprint close (Sunday 10pm)",
    )
    log.info("Sprint close scheduled — Sunday 10pm AEST.")

    # JOB A8: Sprint start — Monday 7am AEST (start next sprint)
    def run_sprint_start_job():
        from po_actions_automatic import run_sprint_start
        try:
            run_sprint_start()
        except Exception as e:
            log.error(f"Sprint start failed: {e}", exc_info=True)

    scheduler.add_job(
        run_sprint_start_job,
        trigger=CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=sydney_tz),
        id="sprint_start",
        name="Sprint start (Monday 7am)",
    )
    log.info("Sprint start scheduled — Monday 7am AEST.")

    log.info("Sprint turnover also available manually via /sprint_turnover.")

    # JOB A7: Sprint runway — ensure 8 future sprints exist (daily 5am AEST)
    def run_sprint_runway():
        from jira_client import ensure_sprint_runway
        try:
            ensure_sprint_runway(required=8)
        except Exception as e:
            log.error(f"Sprint runway failed: {e}", exc_info=True)

    scheduler.add_job(
        run_sprint_runway,
        trigger=CronTrigger(day_of_week="mon-fri", hour=5, minute=0, timezone=sydney_tz),
        id="sprint_runway",
        name="Sprint runway (daily 5am)",
    )
    log.info("Sprint runway scheduled — daily 5am AEST (ensures 8 future sprints).")

    # JOB A6: Sprint Retro — Sunday 10:30am AEST
    def run_sprint_retro():
        from sprint_retro import generate_retro
        try:
            generate_retro()
        except Exception as e:
            log.error(f"Sprint retro failed: {e}", exc_info=True)

    scheduler.add_job(
        run_sprint_retro,
        trigger=CronTrigger(day_of_week="sun", hour=10, minute=30, timezone=sydney_tz),
        id="sprint_retro",
        name="Sprint retro (Sunday 10:30am)",
    )
    log.info("Sprint retro scheduled — Sunday 10:30am AEST.")

    # Start Telegram bot in a daemon thread
    if TELEGRAM_BOT_TOKEN:
        tg_thread = threading.Thread(target=start_polling, daemon=True)
        tg_thread.start()
        log.info("Telegram bot thread started.")
    else:
        log.warning("Telegram bot skipped — TELEGRAM_BOT_TOKEN not set.")

    # Run sprint runway once at startup
    run_sprint_runway()

    scheduler.start()
