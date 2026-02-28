"""
PM Agent — Claude Client
AI-powered idea enrichment using Anthropic's Claude API.
"""

import re
import json
import requests
from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS,
    INITIATIVE_OPTIONS, log,
)


def call_claude(prompt, max_tokens=None):
    """Send a prompt to Claude and return the text response."""
    if not ANTHROPIC_API_KEY:
        log.error("ANTHROPIC_API_KEY not set")
        return None
    tokens = max_tokens or CLAUDE_MAX_TOKENS
    # Scale timeout: ~90s for small requests, up to 300s for large prototype generation
    timeout = min(300, max(90, tokens // 50))
    try:
        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={
                "model": CLAUDE_MODEL,
                "max_tokens": tokens,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=timeout,
        )
        if r.status_code == 200:
            return r.json()["content"][0]["text"].strip()
        log.error(f"Claude API error: {r.status_code} {r.text[:300]}")
    except Exception as e:
        log.error(f"Claude API exception: {e}")
    return None


def parse_json_response(response):
    """Parse Claude's response, stripping markdown fences if present."""
    if not response:
        return None
    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response)
        clean = re.sub(r'\s*```$', '', clean)
        return json.loads(clean)
    except json.JSONDecodeError as e:
        log.error(f"JSON parse error: {e}\nRaw: {response[:500]}")
        return None


def build_enrichment_prompt(raw_idea, kb_context_text):
    """
    Build the PM1 enrichment prompt.
    Takes raw idea text and formatted KB context string.
    Returns structured prompt for Claude.
    """
    # Build initiative module options (exclude scope/stage tags)
    scope_tags = {"mvp", "iteration", "modules", "workflows", "features", "voa"}
    initiative_modules = ", ".join(
        f'"{k.title()}"' for k in INITIATIVE_OPTIONS if k not in scope_tags
    )

    return f"""You are a senior Product Manager for Axis CRM, a life insurance distribution CRM platform.
The platform is used by AFSL-licensed insurance advisers to manage clients, policies, applications, quotes, payments and commissions.
Partner insurers include TAL, Zurich, AIA, MLC Life, MetLife, Resolution Life, Integrity Life and others.

You have access to the following knowledge base about the product:

<knowledge_base>
{kb_context_text}
</knowledge_base>

A product idea has been submitted (possibly informal/conversational from a voice note).
Your job is to enrich it into a fully-formed, strategically-aligned JPD idea using the knowledge base.

RAW IDEA:
{raw_idea}

Respond with ONLY a JSON object (no markdown, no backticks, no explanation):

{{
  "summary": "Concise idea title (3-8 words)",
  "description": "**Outcome we want to achieve**\\n\\n[Clear, specific outcome with measurable targets where possible.]\\n\\n**Why it's a problem**\\n\\n[Current pain point, inefficiency, or gap. Reference knowledge base context where relevant.]\\n\\n**How it gets us closer to our vision: The Adviser CRM that enables workflow and pipeline visibility, client engagement and compliance through intelligent automation.**\\n\\n[Connect to vision — workflow/pipeline visibility, client engagement, compliance, or intelligent automation. Reference strategic initiatives if aligned.]\\n\\n**How it improves our north star: Total submissions**\\n\\n[Specific causal chain explaining how this increases total submissions.]",
  "initiative_module": "[Primary module/feature — select ONE from: {initiative_modules}]",
  "initiative_stage": "[MVP or Iteration — MVP if new capability, Iteration if improving existing]",
  "initiative_scope": "[Modules, Features, or Workflows — Modules if full module/screen, Features if feature within a module, Workflows if it's a workflow/process]"
}}

RULES:
- Use the knowledge base to inform your analysis — reference specific modules, segments, and initiatives.
- Write the description as a thoughtful PM would — substantive, not just parroting the input.
- All four description sections are MANDATORY.
- initiative_module must be ONE value from the list. Pick the closest match.
- initiative_scope MUST be one of: "Modules", "Features", or "Workflows"."""


def build_changes_prompt(original_data, change_instructions, kb_context_text):
    """
    Build a re-enrichment prompt incorporating change requests.
    Takes the original structured data, user's change instructions, and KB context.
    """
    return f"""You are a senior Product Manager for Axis CRM.

You previously structured this product idea:

<original>
{json.dumps(original_data, indent=2)}
</original>

The Product Owner has requested changes:

<changes>
{change_instructions}
</changes>

Knowledge base for reference:

<knowledge_base>
{kb_context_text}
</knowledge_base>

Apply the requested changes and return the COMPLETE updated JSON object in the same format.
Respond with ONLY the JSON object (no markdown, no backticks, no explanation).
Preserve all fields — only modify what the change request asks for."""


def enrich_idea(raw_idea, kb_context_text):
    """
    Full enrichment pipeline: raw idea + KB context → structured data.
    Returns parsed dict or None on failure.
    """
    prompt = build_enrichment_prompt(raw_idea, kb_context_text)
    response = call_claude(prompt)
    return parse_json_response(response)


def apply_changes(original_data, change_instructions, kb_context_text):
    """
    Re-enrich an idea with change instructions.
    Returns updated parsed dict or None on failure.
    """
    prompt = build_changes_prompt(original_data, change_instructions, kb_context_text)
    response = call_claude(prompt)
    return parse_json_response(response)


# ── PM2: PRD Generation ──────────────────────────────────────────────────────

def build_prd_prompt(idea_summary, idea_description, issue_key, kb_context_text, inspiration=""):
    """
    Build the PM2 PRD generation prompt.
    Returns a prompt that generates all PRD sections in markdown.
    """
    idea_url = f"https://axiscrm.atlassian.net/browse/{issue_key}"

    inspiration_block = ""
    if inspiration:
        inspiration_block = f"""
PRODUCT OWNER'S INSPIRATION / REFERENCES:
{inspiration}
"""

    inspiration_section = """## Inspiration

* Reference any existing products, features, competitor implementations, or design patterns that inspired this feature.
* Include links or names of specific tools/products where the Product Owner drew inspiration.
* Note what aspects to replicate and what to adapt for the Axis CRM context.
* This section informs the UX/UI prototype that will be built next."""

    if not inspiration:
        inspiration_section = """## Inspiration

* (No specific inspiration provided — research and suggest relevant industry examples, competitor features, or design patterns that could inform this feature's UX/UI design.)"""

    return f"""You are a senior Product Manager for Axis CRM, a life insurance distribution CRM platform.
The platform is used by AFSL-licensed insurance advisers to manage clients, policies, applications, quotes, payments and commissions.
Partner insurers include TAL, Zurich, AIA, MLC Life, MetLife, Resolution Life, Integrity Life and others.

You have access to the following knowledge base about the product:

<knowledge_base>
{kb_context_text}
</knowledge_base>

An idea has been approved and you need to write a Product Requirements Document (PRD) for it.

IDEA: {issue_key} — {idea_summary}

IDEA DESCRIPTION:
{idea_description}
{inspiration_block}
Write the PRD in MARKDOWN format with exactly these 6 sections. Do NOT include a table of contents or any preamble — start directly with the first heading.

## Context

* **Idea:** {idea_url}
* Write 3-5 bullet points covering: what the problem is, why we're prioritising it now, what we're building, what's in/out of scope, and how we'll measure success. Reference knowledge base context where relevant.

{inspiration_section}

## Business requirements

* List the core functional requirements as bullet points.
* Group by logical area if there are multiple concerns.
* Be specific and actionable — avoid vague statements.
* Include acceptance criteria where possible.

## Risks

* List risks as a markdown table with columns: Risk | Mitigation
* Include at least 3-5 risks covering: data integrity, user adoption, technical complexity, dependencies, and timeline.

## Technical requirements (for developer)

* List technical considerations: APIs, data models, integrations, performance requirements.
* Note any dependencies on other modules or external services.
* Specify any constraints (browser support, data migration, etc.).

## Proposed tickets (for developer)

* Break the work into logical development tickets.
* Each ticket should have: a short title, estimated story points (1, 2, 3, 5, 8, 13), and a brief scope description.
* Order them by dependency/priority.
* Format: "**Ticket title** (X SP) — Description"

RULES:
- Write as a thoughtful PM — substantive, specific, and grounded in the knowledge base.
- Every section must have real content — no "TBD" or empty placeholders.
- Use the knowledge base to reference specific modules, segments, integrations, and terminology.
- The Inspiration section is critical — it informs the interactive prototype that will be built in PM3.
- Keep it concise but complete — this document will be handed to a developer.
- Output ONLY the markdown content. No JSON wrapping, no backticks fence, no preamble."""


def build_prd_changes_prompt(current_prd_markdown, change_instructions, kb_context_text):
    """Build a PRD re-generation prompt incorporating change requests."""
    return f"""You are a senior Product Manager for Axis CRM.

You previously wrote this PRD:

<current_prd>
{current_prd_markdown}
</current_prd>

The Product Owner has requested changes:

<changes>
{change_instructions}
</changes>

Knowledge base for reference:

<knowledge_base>
{kb_context_text}
</knowledge_base>

Apply the requested changes and return the COMPLETE updated PRD in the same markdown format.
Output ONLY the markdown content — no JSON, no backticks fence, no explanation.
Preserve all sections — only modify what the change request asks for."""


def generate_prd(idea_summary, idea_description, issue_key, kb_context_text, inspiration=""):
    """
    Generate a full PRD from an approved idea.
    Returns markdown string or None on failure.
    """
    prompt = build_prd_prompt(idea_summary, idea_description, issue_key, kb_context_text, inspiration=inspiration)
    return call_claude(prompt, max_tokens=6000)


def update_prd_with_changes(current_prd_markdown, change_instructions, kb_context_text):
    """
    Re-generate a PRD with change instructions.
    Returns updated markdown string or None on failure.
    """
    prompt = build_prd_changes_prompt(current_prd_markdown, change_instructions, kb_context_text)
    return call_claude(prompt, max_tokens=6000)


# ── PM3: Prototype Generation ────────────────────────────────────────────────

def build_prototype_prompt(issue_key, summary, prd_content, design_system_text, db_schema_text):
    """
    Build the PM3 prototype generation prompt.
    Returns a prompt that generates a single-file HTML prototype.
    """
    return f"""You are a senior UX/UI designer and frontend developer for Axis CRM, a life insurance distribution platform.

You need to create a HIGH-FIDELITY interactive prototype for this feature:

**{issue_key} — {summary}**

<prd>
{prd_content}
</prd>

<design_system>
{design_system_text}
</design_system>

<database_schema>
{db_schema_text}
</database_schema>

Create a SINGLE self-contained HTML file that is a high-fidelity interactive prototype of this feature.

TECHNICAL REQUIREMENTS:
- Single HTML file with all CSS and JS inline
- Use Tailwind CSS via CDN: <script src="https://cdn.tailwindcss.com"></script>
- Configure Tailwind with the Axis brand colours in a <script> block:
  tailwind.config = {{
    theme: {{
      extend: {{
        colors: {{
          'axis-orange': '#D34108',
          'axis-orange-light': '#EA6921',
          'axis-slate': '#3B485B',
          'axis-charcoal': '#2B3544',
          'axis-gray': '#F5F5F5',
        }}
      }}
    }}
  }}
- Use Untitled UI patterns throughout: clean card layouts, subtle shadows (shadow-sm), 8px border radius (rounded-lg), consistent 16/24px spacing, 14px body text, muted secondary text (#667085), dividers (#EAECF0)
- Use Inter font via Google Fonts (Untitled UI's default)
- Use Lucide icons via CDN for any icons needed

DESIGN REQUIREMENTS:
- Match the existing Axis CRM look and feel — dark sidebar navigation, white content area
- Include the EXACT Axis CRM left sidebar (dark bg: axis-charcoal #2B3544) with this structure:
  * Top: Axis logo (orange X icon + "AXIS" text in white, use an SVG or styled div)
  * Search bar (dark input with "Search..." placeholder, rounded)
  * Navigation items (white text, icons on left, chevron on right for expandable):
    - Tasks (expandable: All Tasks, Scheduled Tasks)
    - Leads (with orange count badge showing a number like "607")
    - Clients (expandable)
    - Applications (expandable)
    - Dishonours (expandable)
    - Claims (expandable)
    - Complaints (expandable)
    - Insurance (expandable)
    - Policies
    - Commissions (expandable)
    - Payments (expandable)
    - Campaigns
    - Reports
    - Exports
    - Settings
  * Bottom: Orange "+ Create New Lead" button (full width, rounded)
  * Footer: User avatar + "James Nicholls" + "james@axiscrm.co..." in smaller text
  * Highlight the nav item most relevant to this feature with a slightly lighter background
  * Sidebar width: 240px on desktop, hidden by default on mobile with hamburger toggle
- Use real field names from the database schema (not lorem ipsum)
- Make forms interactive (show/hide sections, tab switching, basic validation states)
- Include realistic sample data appropriate to life insurance (Australian names, realistic policy numbers, etc.)
- Show all key user flows described in the PRD — use tabs or multi-step flows if needed
- Include status indicators, badges, and progress elements where appropriate

MOBILE-FIRST RESPONSIVE DESIGN (CRITICAL — follow Untitled UI responsive patterns):
- Build MOBILE-FIRST: start with mobile layout, enhance for larger screens using sm:, md:, lg: prefixes
- Breakpoints: mobile (<640px), tablet (640-1023px), desktop (1024px+)
- SIDEBAR: hidden off-screen on mobile (translate-x, transition), toggled via hamburger icon in a sticky top bar. Overlay with backdrop on mobile. Visible always on lg: screens.
- TOP BAR on mobile: sticky top-0, white bg, hamburger button (left), page title (center), user avatar (right)
- TABLES: on mobile, convert data tables to stacked card layouts — each row becomes a card with label:value pairs. Use Untitled UI's mobile table pattern (no horizontal scrolling).
- FORMS: single column on mobile, two columns on md: screens. Full-width inputs, proper touch targets (min 44px height). Labels above inputs (not inline).
- CARDS: full-width on mobile (no side margins except px-4), grid with gap-4/gap-6 on larger screens
- BUTTONS: full-width on mobile (w-full), auto-width on sm: and above. Min height 44px for touch.
- MODALS: on mobile, use bottom sheet pattern (fixed bottom-0, rounded-t-xl, slide up). Centered modal on desktop.
- TABS: horizontally scrollable on mobile (overflow-x-auto, no wrapping). Sticky if needed.
- SPACING: use px-4 on mobile, px-6 on md:, px-8 on lg: for page padding
- TYPOGRAPHY: scale down headings on mobile (text-xl instead of text-2xl, text-lg instead of text-xl)
- STAT CARDS / KPI TILES: single column stack on mobile, 2-col on md:, 3-4 col on lg:
- FILTERS / SEARCH: collapsible filter panel on mobile (toggle show/hide), inline on desktop
- Touch-friendly: all interactive elements min 44px tap target, adequate spacing between clickable items

INTERACTIVITY:
- Clickable navigation and tabs
- Form inputs with placeholder text matching real field names
- Expandable/collapsible sections
- Modal dialogs for confirmations (bottom sheets on mobile)
- Toast notifications for actions (bottom-center on mobile, top-right on desktop)
- Hover states on interactive elements (desktop), active/pressed states (mobile)
- Table sorting/filtering where relevant
- Mobile sidebar: hamburger opens sidebar with slide-in + backdrop overlay, tap backdrop to close
- Smooth CSS transitions on all show/hide interactions (transition-all duration-200)

Output ONLY the complete HTML file content. No explanation, no markdown fences — just the raw HTML starting with <!DOCTYPE html>."""


def build_prototype_changes_prompt(current_html, change_instructions, prd_content, design_system_text, db_schema_text):
    """Build a prototype re-generation prompt with change requests."""
    return f"""You are a senior UX/UI designer and frontend developer for Axis CRM.

You previously created this prototype:

<current_prototype>
{current_html}
</current_prototype>

The Product Owner has requested changes:

<changes>
{change_instructions}
</changes>

For reference:
<prd>
{prd_content}
</prd>
<design_system>
{design_system_text}
</design_system>
<database_schema>
{db_schema_text}
</database_schema>

Apply the requested changes and return the COMPLETE updated HTML file.
Output ONLY the raw HTML starting with <!DOCTYPE html>. No explanation, no markdown fences."""


def extract_db_keywords(prd_content):
    """
    Use Claude to extract relevant database table keywords from PRD content.
    Returns a list of keyword strings for DB schema lookup.
    """
    prompt = f"""Given this PRD for a CRM feature, extract 5-10 keywords that would match relevant database table names.
The database uses Django-style naming: app_modelname (e.g., leads_lead, applications_application, companies_company).

PRD:
{prd_content[:3000]}

Return ONLY a JSON array of lowercase keywords, e.g.: ["lead", "application", "policy", "company"]
No explanation, no markdown fences — just the JSON array."""

    response = call_claude(prompt, max_tokens=200)
    parsed = parse_json_response(response)
    if isinstance(parsed, list):
        return parsed
    return ["lead", "application", "policy", "company"]  # sensible defaults


def generate_prototype(issue_key, summary, prd_content, design_system_text, db_schema_text):
    """
    Generate a full HTML prototype from PRD and context.
    Returns HTML string or None on failure.
    """
    prompt = build_prototype_prompt(issue_key, summary, prd_content, design_system_text, db_schema_text)
    return call_claude(prompt, max_tokens=16000)


def update_prototype_with_changes(current_html, change_instructions, prd_content, design_system_text, db_schema_text):
    """
    Re-generate a prototype with change instructions.
    Returns updated HTML string or None on failure.
    """
    prompt = build_prototype_changes_prompt(current_html, change_instructions, prd_content, design_system_text, db_schema_text)
    return call_claude(prompt, max_tokens=16000)
