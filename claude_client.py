"""
PM Agent — Claude Client
AI-powered idea enrichment using Anthropic's Claude API.
"""

import re
import json
import requests
from config import (
    ANTHROPIC_API_KEY, CLAUDE_MODEL, CLAUDE_MAX_TOKENS,
    INITIATIVE_OPTIONS, PRODUCT_CATEGORY_OPTIONS, log,
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
    product_cats = ", ".join(f'"{k.title()}"' for k in PRODUCT_CATEGORY_OPTIONS)

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
  "initiative_scope": "[Modules or Features — Modules if full module/screen, Features if feature within a module]",
  "labels": "[Modules or Features — match initiative_scope]",
  "product_category": "[One of: {product_cats}, or null]",
  "discovery": "Validate",
  "customer_segment": "[Primary customer segment this serves, from the knowledge base]",
  "strategic_alignment": "[Which strategic initiative(s) this aligns with, if any]",
  "affected_modules": ["[List of platform modules affected, from the knowledge base]"],
  "flags": ["[Any risks, dependencies, or considerations]"]
}}

RULES:
- Use the knowledge base to inform your analysis — reference specific modules, segments, and initiatives.
- Write the description as a thoughtful PM would — substantive, not just parroting the input.
- All four description sections are MANDATORY.
- initiative_module must be ONE value from the list. Pick the closest match.
- customer_segment, strategic_alignment, affected_modules, and flags are for the Telegram preview only (not stored in Jira fields).
- discovery should default to "Validate" unless the user says otherwise."""


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
