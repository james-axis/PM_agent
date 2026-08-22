"""
PM Agent — Configuration
All environment variables, constants, and knowledge base references.
"""

import os
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("pm_agent")

# ── Jira ──────────────────────────────────────────────────────────────────────
JIRA_BASE_URL = os.getenv("JIRA_BASE_URL", "https://axiscrm.atlassian.net")
JIRA_EMAIL = os.getenv("JIRA_EMAIL")
JIRA_API_TOKEN = os.getenv("JIRA_API_TOKEN")

# AR project (Jira Product Discovery)
AR_PROJECT_KEY = "AR"
JAMES_ACCOUNT_ID = "712020:b28bb054-a469-4a9f-bfde-0b93ad1101ae"

# AX project (Sprints / team-managed)
AX_PROJECT_KEY = "AX"
AX_BOARD_ID = 1
STORY_POINTS_FIELD = "customfield_10016"
ANDREJ_ACCOUNT_ID = "712020:00983fc3-e82b-470b-b141-77804c9be677"
READY_TRANSITION_ID = "7"

# JPD field IDs
SWIMLANE_FIELD = "customfield_10694"
ROADMAP_FIELD = "customfield_10560"
INITIATIVE_FIELD = "customfield_10628"
DISCOVERY_FIELD = "customfield_10049"
PRODUCT_CAT_FIELD = "customfield_10391"
LABELS_FIELD = "labels"

# Swimlane option IDs
EXPERIENCE_SWIMLANE_ID = "10682"
CAPABILITY_SWIMLANE_ID = "10681"
OTHER_SWIMLANE_ID = "10685"

SWIMLANE_OPTIONS = {
    "experience": EXPERIENCE_SWIMLANE_ID,
    "capability": CAPABILITY_SWIMLANE_ID,
    "other": OTHER_SWIMLANE_ID,
}

# Phase field & options (separate from Initiative now)
PHASE_FIELD = "customfield_10867"
PHASE_MVP_ID = "10683"
PHASE_ITERATION_ID = "10684"

# Improves field (auto-discovered options)
IMPROVES_FIELD = "customfield_10900"

# Roadmap
ROADMAP_BACKLOG_ID = "10536"
ENGAGEMENT_PROCESS_FIELD = "customfield_10934"
ENGAGEMENT_INTAKE_DISCOVERY_ID = "10892"

# Discovery options
DISCOVERY_OPTIONS = {
    "validate": "10027", "validating": "10026", "validated": "10025",
    "won't do": "10028", "delivered": "10072",
}

# Initiative options (module tags only — phase & scope moved to separate fields)
INITIATIVE_OPTIONS = {
    "crm facelift": "10272", "iextend": "10273", "payments": "10310",
    "insurance": "10311", "extension": "10348", "compliance": "10350",
    "ai assistant": "10351", "notification": "10384", "quoting": "10385",
    "onboarding": "10386", "services": "10387", "application": "10388",
    "dashboard": "10389", "training": "10390", "complaints": "10391",
    "claims": "10392", "dishonours": "10393", "task": "10394",
    "website": "10397", "client portal": "10396", "client profile": "10430",
    "system": "10463",
}

# Product category options
PRODUCT_CATEGORY_OPTIONS = {
    "analytics": "10190", "ai": "10191", "ux/ui": "10192",
}

# ── Confluence ────────────────────────────────────────────────────────────────
CONFLUENCE_BASE = f"{JIRA_BASE_URL}/wiki"
CONFLUENCE_SPACE_ID = "1933317"       # CAD space (numeric ID)
PRD_PARENT_ID = "13828098"            # Folder for PRD pages in CAD

# Knowledge Base page IDs (PM Agent KB space)
KB_PAGES = {
    "strategic_initiatives": "290619393",
    "platform_modules": "290652164",
    "customer_segments": "290619394",
    "insurer_partners": "290750472",
    "domain_glossary": "290881537",
    "brand_design_system": "290684966",
}

# ── Claude API ────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
CLAUDE_MODEL = "claude-sonnet-4-6"
CLAUDE_MAX_TOKENS = 4096

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Auto-captured on first message

# ── Google Sheets (VoA Monitor) ──────────────────────────────────────────────
GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
VOA_SHEET_ID = os.getenv("VOA_SHEET_ID")  # Google Sheet ID from URL

# ── Atlassian GraphQL (JPD Insights) ─────────────────────────────────────────
ATLASSIAN_CLOUD_ID = "2a0f7b21-7370-4295-b301-e3151afb1325"

# ── Custom Product Roadmap API ───────────────────────────────────────────────
ROADMAP_API_BASE = "https://productcentral.up.railway.app"
ROADMAP_API_KEY = os.getenv("ROADMAP_API_KEY", "ax-rmap-7f3k9w2mXpQ4nLvT8hRbJdYeUcZs")

# ── Insights Hub ─────────────────────────────────────────────────────────────
INSIGHTS_HUB_URL = os.getenv("INSIGHTS_HUB_URL", "https://productcentral.up.railway.app")
INSIGHTS_HUB_TOKEN = os.getenv("INSIGHTS_HUB_TOKEN", "wvf34g35b3b34qb134bqqrev466")

# ── Slack ─────────────────────────────────────────────────────────────────────
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN", "")
SLACK_CHANNEL_ID = os.getenv("SLACK_CHANNEL_ID", "")  # Set to target channel ID

# ── Sprint Guard ─────────────────────────────────────────────────────────────
# Keeps the active sprint honest: flags (and optionally returns) tickets added
# to the open sprint after planning. Default is flag-and-notify (non-destructive).
# Flip SPRINT_GUARD_ENFORCE=true to also auto-return unplanned tickets to backlog.
SPRINT_GUARD_ENFORCE = os.getenv("SPRINT_GUARD_ENFORCE", "false").strip().lower() in ("1", "true", "yes", "on")
UNPLANNED_LABEL = "unplanned"
PLANNED_SWAP_LABEL = "planned-swap"  # PO adds this to permit an intentional mid-sprint swap
# Accounts allowed to add to the open sprint (intentional planning). PO = James.
SPRINT_GUARD_ALLOWLIST = {JAMES_ACCOUNT_ID}

# ── Microsoft Graph (Mail.Send) ──────────────────────────────────────────────
MS_TENANT_ID = os.getenv("MS_TENANT_ID", "")
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID", "")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "")

# ── CRM Database (PostgreSQL on RDS) ─────────────────────────────────────────
DB_HOST = os.getenv("DB_HOST", "")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "")
DB_USER = os.getenv("DB_USER", "")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
