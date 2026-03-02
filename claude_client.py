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
    initiative_modules = ", ".join(
        f'"{k.title()}"' for k in INITIATIVE_OPTIONS
    )

    return f"""You are a PM for Axis CRM (life insurance CRM for AFSL-licensed advisers).

<knowledge_base>
{kb_context_text}
</knowledge_base>

Enrich this raw idea into a JPD idea.

RAW IDEA:
{raw_idea}

JSON only (no markdown, no backticks):

{{
  "summary": "3-6 word title",
  "description": "**Outcome**\\n\\n[1 sentence max]\\n\\n**Problem**\\n\\n[1 sentence max]\\n\\n**Vision alignment**\\n\\n[1 sentence max]\\n\\n**North star impact**\\n\\n[1 sentence max]",
  "swimlane": "[Experience|Capability|Other]",
  "initiative": "[ONE from: {initiative_modules}]",
  "phase": "[MVP|Iteration]"
}}

RULES:
- Each description section: ONE sentence. Max 15 words per sentence.
- No filler phrases ("This will enable...", "This ensures...", "By implementing...").
- swimlane: Experience = user-facing UI/UX. Capability = backend/infra. Other = neither.
- phase: MVP = net new. Iteration = improving existing."""


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

def build_prd_prompt(idea_summary, idea_description, issue_key, kb_context_text, inspiration="",
                     db_schema_text="", code_context=""):
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

* 2-3 bullet points: reference products, features, or patterns that inform UX/UI design."""

    if inspiration:
        inspiration_section = """## Inspiration

* Reference the provided inspiration and note what to replicate vs adapt."""

    if not inspiration:
        inspiration_section = """## Inspiration

* Suggest 2-3 relevant industry examples or design patterns for this feature."""

    codebase_block = ""
    if db_schema_text or code_context:
        codebase_block = f"""
<database_schema>
{db_schema_text if db_schema_text else "(Not available)"}
</database_schema>

<codebase_context>
{code_context if code_context else "(Not available)"}
</codebase_context>

Reference existing models/tables/fields where relevant.
"""

    return f"""PM for Axis CRM (life insurance CRM for AFSL-licensed advisers).

<knowledge_base>
{kb_context_text}
</knowledge_base>
{codebase_block}
PRD for: {issue_key} — {idea_summary}

DESCRIPTION:
{idea_description}
{inspiration_block}
MARKDOWN. 6 sections. No preamble. Start with first heading.

## Context

* **Idea:** {idea_url}
* 3 bullets max. One sentence each. Problem, what we're building, success metric.

{inspiration_section}

## Business requirements

* Max 8 bullets. One sentence each. No sub-bullets.
* Group by area if needed. Include acceptance criteria inline.

## Risks

* Markdown table: Risk | Mitigation
* 3 rows max. One sentence per cell.

## Technical requirements (for developer)

* Max 5 bullets. One sentence each.

## Proposed tickets (for developer)

* **Ticket title** (X SP) — One sentence scope.
* Max 8 tickets.

CRITICAL RULES:
- EVERY bullet = ONE sentence. No multi-sentence bullets.
- No filler ("This ensures...", "This will enable...", "It is important to...").
- No prose paragraphs anywhere. Bullets only.
- If you can say it in 8 words, don't use 15.
- Output ONLY markdown. No JSON, no backticks fence."""


def build_prd_changes_prompt(current_prd_markdown, change_instructions, kb_context_text):
    """Build a PRD re-generation prompt incorporating change requests."""
    return f"""PM for Axis CRM.

Current PRD:

<current_prd>
{current_prd_markdown}
</current_prd>

Changes requested:

<changes>
{change_instructions}
</changes>

<knowledge_base>
{kb_context_text}
</knowledge_base>

Apply changes. Return COMPLETE updated PRD in same markdown format.
Same brevity rules: every bullet = one sentence. No filler. No prose paragraphs.
Output ONLY markdown — no JSON, no backticks, no explanation."""


def generate_prd(idea_summary, idea_description, issue_key, kb_context_text, inspiration="",
                  db_schema_text="", code_context=""):
    """
    Generate a full PRD from an approved idea.
    Returns markdown string or None on failure.
    """
    prompt = build_prd_prompt(idea_summary, idea_description, issue_key, kb_context_text,
                              inspiration=inspiration, db_schema_text=db_schema_text,
                              code_context=code_context)
    return call_claude(prompt, max_tokens=6000)


def update_prd_with_changes(current_prd_markdown, change_instructions, kb_context_text):
    """
    Re-generate a PRD with change instructions.
    Returns updated markdown string or None on failure.
    """
    prompt = build_prd_changes_prompt(current_prd_markdown, change_instructions, kb_context_text)
    return call_claude(prompt, max_tokens=6000)


# ── PM3: Prototype Generation ────────────────────────────────────────────────

def build_prototype_prompt(issue_key, summary, prd_content, design_system_text, db_schema_text,
                           ui_patterns_text="", model_context=""):
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

{f'''<existing_ui_patterns>
These are actual templates/HTML from the existing codebase. Match these patterns for consistency:
{ui_patterns_text}
</existing_ui_patterns>''' if ui_patterns_text else ''}

{f'''<existing_models>
These are the existing Django models. Use real field names and data types in the prototype:
{model_context}
</existing_models>''' if model_context else ''}

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
- You MUST include the following sidebar HTML EXACTLY as provided. Copy it verbatim into the prototype. Only change which nav item gets the active highlight based on the feature being prototyped.

SIDEBAR HTML (copy this exactly):
```
<aside id="sidebar" class="fixed inset-y-0 left-0 w-60 bg-[#2B3544] text-white flex flex-col z-40 transform transition-transform duration-200 -translate-x-full lg:translate-x-0">
  <div class="p-5 pb-3">
    <div class="flex items-center gap-2 mb-5">
      <svg class="w-10 h-10" viewBox="0 0 32 32"><path fill="#ff4405" d="M0,12.8C0,8.32,0,6.08.87,4.37c.77-1.51,1.99-2.73,3.5-3.5C6.08,0,8.32,0,12.8,0h6.4C23.68,0,25.92,0,27.63.87c1.51.77,2.73,1.99,3.5,3.5.87,1.71.87,3.95.87,8.43v6.4c0,4.48,0,6.72-.87,8.43-.77,1.51-1.99,2.73-3.5,3.5-1.71.87-3.95.87-8.43.87h-6.4c-4.48,0-6.72,0-8.43-.87-1.51-.77-2.73-1.99-3.5-3.5C0,25.92,0,23.68,0,19.2v-6.4Z"/><path fill="#fff" d="M13.43,15.89l-9.43,10.27h4.86L28,5.35h-4.99l-7.08,7.63-7.08-7.63h-4.86l9.43,10.54Z"/><path fill="#fff" d="M23.01,26.16h4.99l-9.16-9.85c-1.44,2.37-.88,4.23-.42,4.86l4.58,4.99Z"/></svg>
      <span class="text-2xl font-bold italic text-[#D34108]">AXIS</span>
    </div>
    <input type="text" placeholder="Search..." class="w-full bg-[#3B485B] text-white placeholder-gray-400 rounded-lg px-3 py-2 text-sm border-0 outline-none focus:ring-1 focus:ring-[#D34108]">
  </div>
  <nav class="flex-1 overflow-y-auto px-3 space-y-0.5 text-[14px]">
    <div>
      <button onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.chev').classList.toggle('rotate-180')" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B] transition-colors">
        <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25H12"/></svg>
        <span class="flex-1 text-left">Tasks</span>
        <svg class="chev w-4 h-4 opacity-50 rotate-180 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7"/></svg>
      </button>
      <div class="pl-11 space-y-0.5">
        <a href="#" class="block px-3 py-1.5 rounded-lg hover:bg-[#3B485B] text-gray-300 text-sm">All Tasks</a>
        <a href="#" class="block px-3 py-1.5 rounded-lg hover:bg-[#3B485B] text-gray-300 text-sm">Scheduled Tasks</a>
      </div>
    </div>
    <a href="#" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M15.75 6a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.501 20.118a7.5 7.5 0 0 1 14.998 0"/><path d="M18 8.25V12m0 0v3.75m0-3.75h3.75M18 12h-3.75"/></svg>
      <span class="flex-1">Leads</span>
      <span class="bg-[#D34108] text-white text-xs font-semibold px-2 py-0.5 rounded-full">607</span>
    </a>
    <button onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.chev').classList.toggle('rotate-180')" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M15 19.128a9.38 9.38 0 0 0 2.625.372 9.337 9.337 0 0 0 4.121-.952 4.125 4.125 0 0 0-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128H5.228A2 2 0 0 1 3.213 17.1a4.123 4.123 0 0 1 3.569-4.452M15.75 6.75a3.75 3.75 0 1 1-7.5 0 3.75 3.75 0 0 1 7.5 0ZM4.5 15.75a3 3 0 1 1 6 0 3 3 0 0 1-6 0Z"/></svg>
      <span class="flex-1 text-left">Clients</span>
      <svg class="chev w-4 h-4 opacity-50 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7"/></svg>
    </button>
    <div class="hidden"></div>
    <button onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.chev').classList.toggle('rotate-180')" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"/></svg>
      <span class="flex-1 text-left">Applications</span>
      <svg class="chev w-4 h-4 opacity-50 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7"/></svg>
    </button>
    <div class="hidden"></div>
    <button onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.chev').classList.toggle('rotate-180')" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126Z"/><path d="M12 15.75h.007v.008H12v-.008Z"/></svg>
      <span class="flex-1 text-left">Dishonours</span>
      <svg class="chev w-4 h-4 opacity-50 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7"/></svg>
    </button>
    <div class="hidden"></div>
    <button onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.chev').classList.toggle('rotate-180')" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M9 12h3.75M9 15h3.75M9 18h3.75m3 .75H18a2.25 2.25 0 0 0 2.25-2.25V6.108c0-1.135-.845-2.098-1.976-2.192a48.424 48.424 0 0 0-1.123-.08m-5.801 0c-.065.21-.1.433-.1.664 0 .414.336.75.75.75h4.5a.75.75 0 0 0 .75-.75 2.25 2.25 0 0 0-.1-.664m-5.8 0A2.251 2.251 0 0 1 13.5 2.25H15a2.25 2.25 0 0 1 2.15 1.586m-5.8 0c-.376.023-.75.05-1.124.08C9.095 4.01 8.25 4.973 8.25 6.108V8.25m0 0H4.875c-.621 0-1.125.504-1.125 1.125v11.25c0 .621.504 1.125 1.125 1.125h9.75c.621 0 1.125-.504 1.125-1.125V9.375c0-.621-.504-1.125-1.125-1.125H8.25Z"/></svg>
      <span class="flex-1 text-left">Claims</span>
      <svg class="chev w-4 h-4 opacity-50 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7"/></svg>
    </button>
    <div class="hidden"></div>
    <button onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.chev').classList.toggle('rotate-180')" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M8.625 12a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H8.25m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0H12m4.125 0a.375.375 0 1 1-.75 0 .375.375 0 0 1 .75 0Zm0 0h-.375M21 12c0 4.556-4.03 8.25-9 8.25a9.764 9.764 0 0 1-2.555-.337A5.972 5.972 0 0 1 5.41 20.97a5.969 5.969 0 0 1-.474-.065 4.48 4.48 0 0 0 .978-2.025c.09-.457-.133-.901-.467-1.226C3.93 16.178 3 14.189 3 12c0-4.556 4.03-8.25 9-8.25s9 3.694 9 8.25Z"/></svg>
      <span class="flex-1 text-left">Complaints</span>
      <svg class="chev w-4 h-4 opacity-50 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7"/></svg>
    </button>
    <div class="hidden"></div>
    <button onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.chev').classList.toggle('rotate-180')" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M9 12.75 11.25 15 15 9.75m-3-7.036A11.959 11.959 0 0 1 3.598 6 11.99 11.99 0 0 0 3 9.749c0 5.592 3.824 10.29 9 11.623 5.176-1.332 9-6.03 9-11.622 0-1.31-.21-2.571-.598-3.751h-.152c-3.196 0-6.1-1.248-8.25-3.285Z"/></svg>
      <span class="flex-1 text-left">Insurance</span>
      <svg class="chev w-4 h-4 opacity-50 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7"/></svg>
    </button>
    <div class="hidden"></div>
    <a href="#" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m0 12.75h7.5m-7.5 3H12M10.5 2.25H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z"/></svg>
      <span>Policies</span>
    </a>
    <button onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.chev').classList.toggle('rotate-180')" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M2.25 18.75a60.07 60.07 0 0 1 15.797 2.101c.727.198 1.453-.342 1.453-1.096V18.75M3.75 4.5v.75A.75.75 0 0 1 3 6h-.75m0 0v-.375c0-.621.504-1.125 1.125-1.125H20.25M2.25 6v9m18-10.5v.75c0 .414.336.75.75.75h.75m-1.5-1.5h.375c.621 0 1.125.504 1.125 1.125v9.75c0 .621-.504 1.125-1.125 1.125h-.375m1.5-1.5H21a.75.75 0 0 0-.75.75v.75m0 0H3.75m0 0h-.375a1.125 1.125 0 0 1-1.125-1.125V15m1.5 1.5v-.75A.75.75 0 0 0 3 15h-.75M15 10.5a3 3 0 1 1-6 0 3 3 0 0 1 6 0Zm3 0h.008v.008H18V10.5Zm-12 0h.008v.008H6V10.5Z"/></svg>
      <span class="flex-1 text-left">Commissions</span>
      <svg class="chev w-4 h-4 opacity-50 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7"/></svg>
    </button>
    <div class="hidden"></div>
    <button onclick="this.nextElementSibling.classList.toggle('hidden');this.querySelector('.chev').classList.toggle('rotate-180')" class="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M2.25 8.25h19.5M2.25 9h19.5m-16.5 5.25h6m-6 2.25h3m-3.75 3h15a2.25 2.25 0 0 0 2.25-2.25V6.75A2.25 2.25 0 0 0 19.5 4.5h-15a2.25 2.25 0 0 0-2.25 2.25v10.5A2.25 2.25 0 0 0 4.5 19.5Z"/></svg>
      <span class="flex-1 text-left">Payments</span>
      <svg class="chev w-4 h-4 opacity-50 transition-transform" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M19 9l-7 7-7-7"/></svg>
    </button>
    <div class="hidden"></div>
    <a href="#" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M10.34 15.84c-.688-.06-1.386-.09-2.09-.09H7.5a4.5 4.5 0 1 1 0-9h.75c.704 0 1.402-.03 2.09-.09m0 9.18c.253.962.584 1.892.985 2.783.247.55.06 1.21-.463 1.511l-.657.38c-.551.318-1.26.117-1.527-.461a20.845 20.845 0 0 1-1.44-4.282m3.102.069a18.03 18.03 0 0 1-.59-4.59c0-1.586.205-3.124.59-4.59m0 9.18a23.848 23.848 0 0 1 8.835 2.535M10.34 6.66a23.847 23.847 0 0 0 8.835-2.535m0 0A23.74 23.74 0 0 0 18.795 3m.38 1.125a23.91 23.91 0 0 1 1.014 5.395m-1.014 8.855c-.118.38-.245.754-.38 1.125m.38-1.125a23.91 23.91 0 0 0 1.014-5.395m0-3.46c.495.413.811 1.035.811 1.73 0 .695-.316 1.317-.811 1.73m0-3.46a24.347 24.347 0 0 1 0 3.46"/></svg>
      <span>Campaigns</span>
    </a>
    <a href="#" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z"/></svg>
      <span>Reports</span>
    </a>
    <a href="#" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5M16.5 12 12 16.5m0 0L7.5 12m4.5 4.5V3"/></svg>
      <span>Exports</span>
    </a>
    <a href="#" class="flex items-center gap-3 px-3 py-2.5 rounded-lg hover:bg-[#3B485B]">
      <svg class="w-5 h-5 opacity-70" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M9.594 3.94c.09-.542.56-.94 1.11-.94h2.593c.55 0 1.02.398 1.11.94l.213 1.281c.063.374.313.686.645.87.074.04.147.083.22.127.325.196.72.257 1.075.124l1.217-.456a1.125 1.125 0 0 1 1.37.49l1.296 2.247a1.125 1.125 0 0 1-.26 1.431l-1.003.827c-.293.241-.438.613-.431.992a6.759 6.759 0 0 1 0 .255c-.007.378.138.75.43.99l1.005.828c.424.35.534.954.26 1.43l-1.298 2.247a1.125 1.125 0 0 1-1.369.491l-1.217-.456c-.355-.133-.75-.072-1.076.124a6.57 6.57 0 0 1-.22.128c-.331.183-.581.495-.644.869l-.213 1.28c-.09.543-.56.941-1.11.941h-2.594c-.55 0-1.02-.398-1.11-.94l-.213-1.281c-.062-.374-.312-.686-.644-.87a6.52 6.52 0 0 1-.22-.127c-.325-.196-.72-.257-1.076-.124l-1.217.456a1.125 1.125 0 0 1-1.369-.49l-1.297-2.247a1.125 1.125 0 0 1 .26-1.431l1.004-.827c.292-.24.437-.613.43-.991a6.932 6.932 0 0 1 0-.255c.007-.38-.138-.751-.43-.992l-1.004-.827a1.125 1.125 0 0 1-.26-1.43l1.297-2.247a1.125 1.125 0 0 1 1.37-.491l1.216.456c.356.133.751.072 1.076-.124.072-.044.146-.087.22-.128.332-.183.582-.495.644-.869l.214-1.281Z"/><path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z"/></svg>
      <span>Settings</span>
    </a>
  </nav>
  <div class="p-3 mt-auto">
    <button class="w-full bg-[#D34108] hover:bg-[#EA6921] text-white font-medium py-2.5 px-4 rounded-lg flex items-center justify-center gap-2 transition-colors">
      <svg class="w-5 h-5" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M12 4.5v15m7.5-7.5h-15"/></svg>
      Create New Lead
    </button>
  </div>
  <div class="p-3 pt-0 border-t border-[#3B485B]">
    <div class="flex items-center gap-3 px-2 py-2">
      <div class="w-9 h-9 rounded-full bg-[#3B485B] flex items-center justify-center text-sm font-semibold border-2 border-[#D34108]">JN</div>
      <div class="flex-1 min-w-0">
        <p class="text-sm font-medium truncate">James Nicholls</p>
        <p class="text-xs text-gray-400 truncate">james@axiscrm.co...</p>
      </div>
      <svg class="w-4 h-4 opacity-50" fill="none" stroke="currentColor" stroke-width="2" viewBox="0 0 24 24"><path d="M4.5 15.75l7.5-7.5 7.5 7.5"/></svg>
    </div>
  </div>
</aside>
<div id="sidebar-backdrop" class="fixed inset-0 bg-black/50 z-30 hidden lg:hidden" onclick="document.getElementById('sidebar').classList.add('-translate-x-full');this.classList.add('hidden')"></div>
```

Also include this mobile top bar (shown only on mobile, hidden on lg:):
```
<header class="sticky top-0 z-20 bg-white border-b border-gray-200 px-4 py-3 flex items-center gap-3 lg:hidden">
  <button onclick="document.getElementById('sidebar').classList.remove('-translate-x-full');document.getElementById('sidebar-backdrop').classList.remove('hidden')" class="p-1">
    <svg class="w-6 h-6 text-gray-700" fill="none" stroke="currentColor" stroke-width="1.5" viewBox="0 0 24 24"><path d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5"/></svg>
  </button>
  <h1 class="text-base font-semibold text-gray-900 flex-1">[Page Title]</h1>
  <div class="w-8 h-8 rounded-full bg-gray-200 flex items-center justify-center text-xs font-semibold">JN</div>
</header>
```

The main content area must use: class="lg:ml-60" to offset for the sidebar on desktop.
Highlight the nav item most relevant to this feature by adding bg-[#3B485B] to that item.

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
- MODALS: use fixed inset-0 overlay with flex items-center justify-center on ALL screen sizes. On mobile, modal should be nearly full-width (mx-4) with max-h-[90vh] overflow-y-auto. On desktop, max-w-lg or max-w-2xl centered. Always use a semi-transparent backdrop (bg-black/50).
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
- Modal dialogs for confirmations (centered on all screen sizes)
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


def generate_prototype(issue_key, summary, prd_content, design_system_text, db_schema_text,
                        ui_patterns_text="", model_context=""):
    """
    Generate a full HTML prototype from PRD and context.
    Returns HTML string or None on failure.
    """
    prompt = build_prototype_prompt(issue_key, summary, prd_content, design_system_text, db_schema_text,
                                    ui_patterns_text=ui_patterns_text, model_context=model_context)
    return call_claude(prompt, max_tokens=16000)


def update_prototype_with_changes(current_html, change_instructions, prd_content, design_system_text, db_schema_text):
    """
    Re-generate a prototype with change instructions.
    Returns updated HTML string or None on failure.
    """
    prompt = build_prototype_changes_prompt(current_html, change_instructions, prd_content, design_system_text, db_schema_text)
    return call_claude(prompt, max_tokens=16000)


# ── PM4: Epic Generation ────────────────────────────────────────────────────

def build_epic_prompt(issue_key, summary, prd_content):
    """Build a prompt to generate Epic summary and title from the PRD."""
    return f"""Generate Epic content from this idea and PRD.

**Source Idea:** {issue_key} — {summary}

<prd>
{prd_content}
</prd>

JSON only (no fences):
{{"epic_title": "...", "epic_summary": "..."}}

RULES:
- epic_title: Shortened version of idea title, max 50 chars. Keep original wording, just trim.
- epic_summary: ONE sentence. What's being built + key outcome. Max 20 words."""


def generate_epic_content(issue_key, summary, prd_content):
    """
    Generate Epic title and summary from PRD content.
    Returns dict with epic_title and epic_summary, or None on failure.
    """
    prompt = build_epic_prompt(issue_key, summary, prd_content)
    response = call_claude(prompt, max_tokens=500)
    return parse_json_response(response)


def build_epic_changes_prompt(current_title, current_summary, change_instructions, prd_content):
    """Build a prompt to re-generate Epic content with changes."""
    return f"""You are a senior Product Manager for Axis CRM.

You previously generated this Epic:
- Title: {current_title}
- Summary: {current_summary}

The Product Owner has requested these changes:
{change_instructions}

<prd>
{prd_content}
</prd>

Apply the requested changes and return updated JSON:
{{"epic_title": "...", "epic_summary": "..."}}

Respond with ONLY valid JSON, no markdown fences."""


def update_epic_with_changes(current_title, current_summary, change_instructions, prd_content):
    """
    Re-generate Epic content with change instructions.
    Returns dict with epic_title and epic_summary, or None on failure.
    """
    prompt = build_epic_changes_prompt(current_title, current_summary, change_instructions, prd_content)
    response = call_claude(prompt, max_tokens=500)
    return parse_json_response(response)


# ── PM5: Task Breakdown ─────────────────────────────────────────────────────

def build_task_breakdown_prompt(epic_key, epic_title, prd_content, prototype_url=""):
    """Build a prompt to break an Epic into shippable tasks."""
    proto_line = f"\n**Prototype:** {prototype_url}" if prototype_url else ""
    sp_scale = "SP Scale: 0.25 (30min), 0.5 (1hr), 1 (2hr), 2 (4hr), 3 (6hr max)"
    return (
        f"Break this Epic into small, shippable tasks.\n\n"
        f"**Epic:** {epic_key} - {epic_title}{proto_line}\n\n"
        f"<prd>\n{prd_content}\n</prd>\n\n"
        f"{sp_scale}\n\n"
        "JSON only:\n"
        "[\n"
        "  {\n"
        '    "summary": "Short title (max 8 words)",\n'
        '    "task_summary": "One sentence: what this delivers",\n'
        '    "user_story": "As a [role], I want [action] so that [benefit]",\n'
        '    "acceptance_criteria": ["Short AC (max 10 words each)"],\n'
        '    "test_plan": "One sentence",\n'
        '    "story_points": 1.0\n'
        "  }\n"
        "]\n\n"
        "RULES:\n"
        "- 8-15 tasks. Vertical slices. Order by dependency.\n"
        "- task_summary: ONE sentence, max 15 words.\n"
        "- acceptance_criteria: 2-3 items, max 10 words each.\n"
        "- test_plan: ONE sentence.\n"
        "- No filler words. Just state the requirement."
    )


def generate_task_breakdown(epic_key, epic_title, prd_content, prototype_url=""):
    """
    Generate task breakdown from Epic and PRD content.
    Returns list of task dicts or None on failure.
    """
    prompt = build_task_breakdown_prompt(epic_key, epic_title, prd_content, prototype_url)
    response = call_claude(prompt, max_tokens=8000)
    return parse_json_response(response)


def build_task_changes_prompt(current_tasks, change_instructions, prd_content):
    """Build a prompt to re-generate task breakdown with changes."""
    import json
    tasks_json = json.dumps(current_tasks, indent=2)
    return f"""You are a senior Product Manager for Axis CRM.

You previously generated this task breakdown:
{tasks_json}

The Product Owner has requested these changes:
{change_instructions}

<prd>
{prd_content}
</prd>

Apply the requested changes. Remember:
- Story points: 0.25, 0.5, 1.0, 2.0, 3.0 only (max 3.0)
- Each task independently deployable
- 8-20 tasks total

Respond with ONLY the updated valid JSON array, no markdown fences."""


def update_tasks_with_changes(current_tasks, change_instructions, prd_content):
    """
    Re-generate task breakdown with change instructions.
    Returns list of task dicts or None on failure.
    """
    prompt = build_task_changes_prompt(current_tasks, change_instructions, prd_content)
    response = call_claude(prompt, max_tokens=8000)
    return parse_json_response(response)


# ── PM6: Engineer Technical Plans ────────────────────────────────────────────

def build_investigation_prompt(tasks, prd_content, repo_structure):
    """Build prompt for Pass 1: identify what to investigate for each task."""
    import json
    task_summaries = json.dumps([
        {"index": i, "summary": t.get("summary", ""), "user_story": t.get("user_story", "")}
        for i, t in enumerate(tasks)
    ], indent=2)

    return f"""Senior engineer at Axis CRM (LeadManager). Django/Python, MySQL, Vue.js, REST APIs.
Repo: apps/leadmanager/ with ~50 Django modules (models.py, views.py, urls.py each).

Identify what to investigate for these tasks:

<tasks>
{task_summaries}
</tasks>

<prd>
{prd_content}
</prd>

<repo_structure>
{repo_structure}
</repo_structure>

JSON only (no fences):
{{
  "db_keywords": ["keyword1", "keyword2"],
  "code_files": ["apps/leadmanager/module/file.py"],
  "api_integrations": ["docusign", "xplan"]
}}

Max 10 code_files total. Combine and deduplicate across all tasks."""


def generate_investigation_plan(tasks, prd_content, repo_structure):
    """
    Pass 1: Analyze tasks and identify what DB tables, code files, and APIs to investigate.
    Returns dict with db_keywords, code_files, api_integrations or None.
    """
    prompt = build_investigation_prompt(tasks, prd_content, repo_structure)
    response = call_claude(prompt, max_tokens=2000)
    return parse_json_response(response)


def build_technical_plans_prompt(tasks, prd_content, db_schema_text, code_context, api_docs_text):
    """Build prompt for Pass 2: generate technical plans for all tasks with full context."""
    import json
    tasks_json = json.dumps([
        {
            "index": i,
            "summary": t.get("summary", ""),
            "task_summary": t.get("task_summary", ""),
            "user_story": t.get("user_story", ""),
            "acceptance_criteria": t.get("acceptance_criteria", []),
            "story_points": t.get("story_points", 1.0),
        }
        for i, t in enumerate(tasks)
    ], indent=2)

    return f"""Senior engineer at Axis CRM (LeadManager). Django/Python, MySQL, Vue.js, REST APIs.

Technical plan for each task. One sentence per bullet point.

<tasks>
{tasks_json}
</tasks>

<prd>
{prd_content}
</prd>

<database_schema>
{db_schema_text}
</database_schema>

<codebase>
{code_context}
</codebase>

{f'<api_documentation>{api_docs_text}</api_documentation>' if api_docs_text else ''}

JSON only (no fences):
[
  {{
    "index": 0,
    "technical_plan": ["One sentence each", "Max 3 bullets", "Reference specific models/tables"],
    "story_points": 1.0
  }}
]

RULES:
- technical_plan: 2-3 bullets. ONE sentence each, max 15 words.
- Reference specific tables/models/files. No generic advice.
- SP: 0.25, 0.5, 1.0, 2.0, or 3.0."""


def generate_technical_plans(tasks, prd_content, db_schema_text, code_context, api_docs_text=""):
    """
    Pass 2: Generate technical plans for all tasks with full context.
    Returns list of {index, technical_plan, story_points} dicts or None.
    """
    prompt = build_technical_plans_prompt(tasks, prd_content, db_schema_text, code_context, api_docs_text)
    response = call_claude(prompt, max_tokens=8000)
    return parse_json_response(response)


def build_engineer_changes_prompt(tasks_with_plans, change_instructions, context_summary):
    """Build a prompt to re-generate technical plans with changes."""
    import json
    tasks_json = json.dumps(tasks_with_plans, indent=2)
    return f"""You are a senior software engineer at Axis CRM (LeadManager), a Django/Python platform.

You previously generated these technical plans:
{tasks_json}

The tech lead has requested these changes:
{change_instructions}

Context summary:
{context_summary}

Apply the requested changes. Each task must have:
- technical_plan: 2-3 high-level bullet points
- story_points: 0.25, 0.5, 1.0, 2.0, or 3.0

Respond with ONLY the updated valid JSON array, no markdown fences:
[{{"index": 0, "technical_plan": ["..."], "story_points": 1.0}}]"""


def update_engineer_plans_with_changes(tasks_with_plans, change_instructions, context_summary):
    """Re-generate technical plans with change instructions."""
    prompt = build_engineer_changes_prompt(tasks_with_plans, change_instructions, context_summary)
    response = call_claude(prompt, max_tokens=8000)
    return parse_json_response(response)
