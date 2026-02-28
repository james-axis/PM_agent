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
                "max_tokens": max_tokens or CLAUDE_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=90,
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

def build_prd_prompt(idea_summary, idea_description, issue_key, kb_context_text):
    """
    Build the PM2 PRD generation prompt.
    Returns a prompt that generates all 6 PRD sections in markdown.
    """
    idea_url = f"https://axiscrm.atlassian.net/jira/polaris/projects/AR/ideas/view/11184018?selectedIssue={issue_key}"

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

Write the PRD in MARKDOWN format with exactly these 6 sections. Do NOT include a table of contents or any preamble — start directly with the first heading.

## Context

* **Idea:** {idea_url}
* Write 3-5 bullet points covering: what the problem is, why we're prioritising it now, what we're building, what's in/out of scope, and how we'll measure success. Reference knowledge base context where relevant.

## Business requirements

* List the core functional requirements as bullet points.
* Group by logical area if there are multiple concerns.
* Be specific and actionable — avoid vague statements.
* Include acceptance criteria where possible.

## UX/UI Design

* Describe the user flow step by step (numbered list or bullets).
* Specify which screens/modules are affected.
* Note any key UI decisions or patterns from the Brand & Design System.
* If there are multiple user roles, describe each role's experience.

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


def generate_prd(idea_summary, idea_description, issue_key, kb_context_text):
    """
    Generate a full PRD from an approved idea.
    Returns markdown string or None on failure.
    """
    prompt = build_prd_prompt(idea_summary, idea_description, issue_key, kb_context_text)
    return call_claude(prompt, max_tokens=6000)


def update_prd_with_changes(current_prd_markdown, change_instructions, kb_context_text):
    """
    Re-generate a PRD with change instructions.
    Returns updated markdown string or None on failure.
    """
    prompt = build_prd_changes_prompt(current_prd_markdown, change_instructions, kb_context_text)
    return call_claude(prompt, max_tokens=6000)
