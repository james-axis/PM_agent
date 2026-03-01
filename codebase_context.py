"""
PM Agent — Codebase Context
Shared helper to gather relevant DB schema and codebase context for any PM stage.
Lightweight version of PM6's two-pass investigation — single Claude call to identify
what to look at, then gathers and returns formatted context.
"""

from config import log
from claude_client import call_claude, parse_json_response
from db_client import discover_relevant_schemas
from github_client import read_file_content, search_code


def gather_codebase_context(feature_description, purpose="requirements"):
    """
    Given a feature description, discover relevant DB tables and code files.
    
    Args:
        feature_description: PRD content, idea description, or feature summary
        purpose: "requirements" (PM2), "prototype" (PM3), or "engineering" (PM6)
    
    Returns:
        dict with keys: db_schema_text, code_context, relevant_models, relevant_views
    """
    # Step 1: Ask Claude what to investigate (lightweight — small prompt)
    investigation = _identify_relevant_areas(feature_description, purpose)
    
    if not investigation:
        log.warning("Codebase context: investigation returned nothing")
        return {
            "db_schema_text": "(Database schema unavailable)",
            "code_context": "(Codebase context unavailable)",
            "relevant_models": "",
            "relevant_views": "",
            "relevant_templates": "",
        }
    
    db_keywords = investigation.get("db_keywords", [])
    models = investigation.get("models", [])
    views = investigation.get("views", [])
    templates = investigation.get("templates", [])
    
    # Step 2: Gather DB schema
    db_schema_text = "(No matching tables)"
    if db_keywords:
        schema = discover_relevant_schemas(db_keywords)
        if schema:
            db_schema_text = schema
    
    # Step 3: Read relevant code files
    relevant_models = _read_files(models, label="models")
    relevant_views = _read_files(views, label="views")
    relevant_templates = _read_files(templates, label="templates")
    
    # Combine into a single code context string
    parts = []
    if relevant_models:
        parts.append(f"=== MODELS ===\n{relevant_models}")
    if relevant_views:
        parts.append(f"=== VIEWS ===\n{relevant_views}")
    if relevant_templates:
        parts.append(f"=== TEMPLATES ===\n{relevant_templates}")
    
    code_context = "\n\n".join(parts) if parts else "(No relevant code found)"
    
    log.info(f"Codebase context: DB keywords={db_keywords}, models={len(models)}, views={len(views)}, templates={len(templates)}")
    
    return {
        "db_schema_text": db_schema_text,
        "code_context": code_context,
        "relevant_models": relevant_models,
        "relevant_views": relevant_views,
        "relevant_templates": relevant_templates,
    }


def _identify_relevant_areas(feature_description, purpose):
    """Ask Claude to identify which DB tables, models, views, and templates are relevant."""
    
    purpose_hints = {
        "requirements": "Focus on models (data structure) and views (business logic) to write accurate requirements.",
        "prototype": "Focus on templates (HTML/Vue patterns, Tailwind classes) and models (field names, data types) to build a realistic UI.",
        "engineering": "Focus on models, views, and templates for comprehensive technical planning.",
    }
    
    prompt = f"""You are analysing the Axis CRM (LeadManager) codebase to find relevant code for a feature.

Stack: Django/Python, MySQL, Vue.js frontend with Tailwind CSS.
Code lives in apps/leadmanager/ with ~50 Django modules including:
account, actions, administration, api, applications, apply, attachments, campaigns, 
castor, claims, clientportal, commissions, companies, complaints, credfin, dishonours, 
docs, docusign, emailimport, emails, equifax, experian, exports, forms, googleapi, 
iextend, illion, insurance, justcall, leadimport, leadmarket, leads, levit8, 
marketinglists, minit, neos, noojee, notes, omnilife, payments, pdf, pleasesign, 
pluggablefunctions, policies, rapidid, reports, schedule, settings, sms, sysmedia, 
tags, tasks, trials, twilioclient, unified_sms, userprofile, utils, webhooks, xplan.

Each module typically has: models.py, views.py, urls.py, forms.py, templates/ directory.

Purpose: {purpose_hints.get(purpose, purpose_hints["requirements"])}

Feature description:
{feature_description[:3000]}

Identify the most relevant areas to investigate. Respond with ONLY valid JSON:
{{
  "db_keywords": ["table_name_keyword1", "keyword2"],
  "models": ["apps/leadmanager/module1/models.py", "apps/leadmanager/module2/models.py"],
  "views": ["apps/leadmanager/module1/views.py"],
  "templates": ["apps/leadmanager/module1/templates/"]
}}

Rules:
- db_keywords: 3-8 table name keywords to search MySQL schema
- models: Max 5 most relevant model files
- views: Max 3 most relevant view files (skip for prototype purpose)
- templates: Max 3 template directories (only for prototype purpose)
- Only include files you're confident exist based on the module list"""

    response = call_claude(prompt, max_tokens=1000)
    return parse_json_response(response)


def _read_files(file_paths, label="files", max_chars_per_file=3000):
    """Read a list of files from the codebase, return combined text."""
    if not file_paths:
        return ""
    
    sections = []
    for filepath in file_paths[:5]:  # Cap at 5
        content = read_file_content(filepath)
        if content:
            if len(content) > max_chars_per_file:
                content = content[:max_chars_per_file] + "\n... (truncated)"
            sections.append(f"--- {filepath} ---\n{content}")
        else:
            log.debug(f"Could not read {filepath}")
    
    return "\n\n".join(sections)
