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
STRATEGIC_INITIATIVES_ID = "10574"
USER_FEEDBACK_OPTION_ID = "10575"

# Roadmap
ROADMAP_BACKLOG_ID = "10536"

# Discovery options
DISCOVERY_OPTIONS = {
    "validate": "10027", "validating": "10026", "validated": "10025",
    "won't do": "10028", "delivered": "10072",
}

# Initiative options (modules, stages, scopes)
INITIATIVE_OPTIONS = {
    "crm facelift": "10272", "iextend": "10273", "payments": "10310",
    "insurance": "10311", "extension": "10348", "compliance": "10350",
    "ai assistant": "10351", "notification": "10384", "quoting": "10385",
    "onboarding": "10386", "services": "10387", "application": "10388",
    "dashboard": "10389", "training": "10390", "complaints": "10391",
    "claims": "10392", "dishonours": "10393", "task": "10394",
    "website": "10397", "client portal": "10396", "client profile": "10430",
    "system": "10463", "voa": "10576",
    # Scope tags
    "mvp": "10346", "iteration": "10347", "modules": "10533",
    "workflows": "10534", "features": "10535",
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
CLAUDE_MODEL = "claude-sonnet-4-20250514"
CLAUDE_MAX_TOKENS = 4096

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")  # Auto-captured on first message
