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

    # VoA Monitor — daily at 7:25am Mon-Fri
    def run_voa():
        from voa_monitor import run_voa_monitor
        try:
            run_voa_monitor()
        except Exception as e:
            log.error(f"VoA Monitor failed: {e}", exc_info=True)

    scheduler.add_job(
        run_voa,
        trigger=CronTrigger(day_of_week="mon-fri", hour=7, minute=56, timezone=sydney_tz),
        id="voa_monitor",
        name="VoA Monitor (daily 7:56am)",
    )
    log.info("VoA Monitor scheduled — daily 7:56am Mon-Fri.")

    # Start Telegram bot in a daemon thread
    if TELEGRAM_BOT_TOKEN:
        tg_thread = threading.Thread(target=start_polling, daemon=True)
        tg_thread.start()
        log.info("Telegram bot thread started.")
    else:
        log.warning("Telegram bot skipped — TELEGRAM_BOT_TOKEN not set.")

    scheduler.start()
