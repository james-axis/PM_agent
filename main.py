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

    # JOB A1: Sprint close — Sunday 10pm AEST (close sprint, carry over, then ensure runway)
    def run_sprint_close_job():
        import time
        from po_actions_automatic import run_sprint_close
        from jira_client import ensure_sprint_runway
        from metrics_client import post_metric
        t0 = time.time()
        try:
            run_sprint_close()
            post_metric("sprint_close", items_processed=1, run_duration_secs=time.time() - t0)
            # Ensure 8 future sprints exist after closing
            ensure_sprint_runway(required=8)
            post_metric("sprint_runway", items_processed=1)
        except Exception as e:
            log.error(f"Sprint close failed: {e}", exc_info=True)
            post_metric("sprint_close", success=False)

    scheduler.add_job(
        run_sprint_close_job,
        trigger=CronTrigger(day_of_week="sun", hour=22, minute=0, timezone=sydney_tz),
        id="sprint_close",
        name="Sprint close (Sunday 10pm)",
    )
    log.info("Sprint close scheduled — Sunday 10pm AEST (includes sprint runway).")

    # JOB A8: Sprint start — Monday 7am AEST (start next sprint + create planning page)
    def run_sprint_start_job():
        import time
        from po_actions_automatic import run_sprint_start
        from sprint_planning import generate_planning
        from metrics_client import post_metric
        t0 = time.time()
        try:
            run_sprint_start()
            post_metric("sprint_start", items_processed=1, run_duration_secs=time.time() - t0)
            # Create planning page after sprint starts
            generate_planning()
        except Exception as e:
            log.error(f"Sprint start failed: {e}", exc_info=True)
            post_metric("sprint_start", success=False)

    scheduler.add_job(
        run_sprint_start_job,
        trigger=CronTrigger(day_of_week="mon", hour=7, minute=0, timezone=sydney_tz),
        id="sprint_start",
        name="Sprint start (Monday 7am)",
    )
    log.info("Sprint start scheduled — Monday 7am AEST.")

    log.info("Sprint turnover also available manually via /sprint_turnover.")

    # JOB A9: Board Refiner — Mon-Fri 7am-7pm every 2hrs AEST
    def run_board_refiner_job():
        import time
        from board_refiner import run_board_refiner as _run_refiner
        from metrics_client import post_metric
        t0 = time.time()
        try:
            refined = _run_refiner()
            items = refined if isinstance(refined, int) else 0
            post_metric("board_refiner", items_processed=max(items, 1), run_duration_secs=time.time() - t0)
        except Exception as e:
            log.error(f"Board refiner failed: {e}", exc_info=True)
            post_metric("board_refiner", success=False)

    scheduler.add_job(
        run_board_refiner_job,
        trigger=CronTrigger(day_of_week="mon-fri", hour="7,9,11,13,15,17,19", minute=0, timezone=sydney_tz),
        id="board_refiner",
        name="Board refiner (2-hourly)",
    )
    log.info("Board refiner scheduled — Mon-Fri 7am-7pm every 2hrs AEST.")

    # JOB A6: Sprint Retro — Sunday 10:30pm AEST
    def run_sprint_retro():
        import time
        from sprint_retro import generate_retro
        from metrics_client import post_metric
        t0 = time.time()
        try:
            generate_retro()
            post_metric("sprint_retro", items_processed=1, run_duration_secs=time.time() - t0)
        except Exception as e:
            log.error(f"Sprint retro failed: {e}", exc_info=True)
            post_metric("sprint_retro", success=False)

    scheduler.add_job(
        run_sprint_retro,
        trigger=CronTrigger(day_of_week="sun", hour=22, minute=30, timezone=sydney_tz),
        id="sprint_retro",
        name="Sprint retro (Sunday 10:30pm)",
    )
    log.info("Sprint retro scheduled — Sunday 10:30pm AEST.")

    # JOB A10: Send retro to Slack — Monday 9am AEST
    def run_retro_slack():
        import time
        from sprint_retro import send_retro_to_slack
        from metrics_client import post_metric
        t0 = time.time()
        try:
            send_retro_to_slack()
            post_metric("retro_slack", items_processed=1, run_duration_secs=time.time() - t0)
        except Exception as e:
            log.error(f"Retro Slack notification failed: {e}", exc_info=True)
            post_metric("retro_slack", success=False)

    scheduler.add_job(
        run_retro_slack,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=0, timezone=sydney_tz),
        id="retro_slack",
        name="Retro to Slack (Monday 9am)",
    )
    log.info("Retro Slack notification scheduled — Monday 9am AEST.")

    # JOB A12: Send planning to Slack — Monday 9:15am AEST
    def run_planning_slack():
        import time
        from sprint_planning import send_planning_to_slack
        from metrics_client import post_metric
        t0 = time.time()
        try:
            send_planning_to_slack()
            post_metric("planning_slack", items_processed=1, run_duration_secs=time.time() - t0)
        except Exception as e:
            log.error(f"Planning Slack notification failed: {e}", exc_info=True)
            post_metric("planning_slack", success=False)

    scheduler.add_job(
        run_planning_slack,
        trigger=CronTrigger(day_of_week="mon", hour=9, minute=15, timezone=sydney_tz),
        id="planning_slack",
        name="Planning to Slack (Monday 9:15am)",
    )
    log.info("Planning Slack notification scheduled — Monday 9:15am AEST.")

    # JOB A11: AXIS Intel Digest — daily 9am AEST
    def run_intel_digest():
        import time
        from pm_axis_intel_digest import build_and_send_digest
        from metrics_client import post_metric
        t0 = time.time()
        try:
            build_and_send_digest()
            post_metric("intel_digest", items_processed=1)
        except Exception as e:
            log.error(f"Intel digest failed: {e}", exc_info=True)
            post_metric("intel_digest", success=False)

    scheduler.add_job(
        run_intel_digest,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=sydney_tz),
        id="intel_digest",
        name="AXIS Intel Digest (daily 9am)",
    )
    log.info("AXIS Intel Digest scheduled — Mon-Fri 9am AEST.")

    # Start OAuth auth server for Microsoft Graph
    from ms_graph_auth import start_auth_server
    start_auth_server(port=8080)

    # Start Telegram bot in a daemon thread
    if TELEGRAM_BOT_TOKEN:
        tg_thread = threading.Thread(target=start_polling, daemon=True)
        tg_thread.start()
        log.info("Telegram bot thread started.")
    else:
        log.warning("Telegram bot skipped — TELEGRAM_BOT_TOKEN not set.")

    scheduler.start()
