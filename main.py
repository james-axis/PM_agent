"""
PM Agent — Entry Point
Phase 1: PM1 Idea Intake via Telegram bot (command-driven, no scheduled jobs).
"""

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

    # Phase 1: Telegram bot only (no scheduler)
    # Future phases will add scheduled jobs here
    start_polling()
