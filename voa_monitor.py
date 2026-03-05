"""
PM Agent — VoA (Voice of Adviser) Monitor
Reads adviser verbatim from a Google Sheet, AI-matches to AR roadmap ideas,
creates JPD Insights on matched ideas, and marks rows as reviewed.

JOB A3: Runs daily at 6:30am AEST. Initial run processes all unreviewed rows.
"""

import json
import re
import logging
from datetime import datetime
import pytz

from config import (
    JIRA_BASE_URL, JIRA_EMAIL, JIRA_API_TOKEN, AR_PROJECT_KEY,
    GOOGLE_SERVICE_ACCOUNT_JSON, VOA_SHEET_ID, ATLASSIAN_CLOUD_ID,
    log,
)
from jira_client import jira_get
from claude_client import call_claude
from telegram_bot import send_telegram

# ── Constants ─────────────────────────────────────────────────────────────────

SHEET_TAB_NAME = "Categorised Verbatim"
BATCH_SIZE = 15  # Verbatim per Claude call (keeps prompt manageable)

# Expected columns in the sheet (0-indexed)
COL_ROW_NUM = 0         # #
COL_THEME = 1           # Strategic Theme
COL_VERBATIM_THEME = 2  # Verbatim Theme
COL_ADVISERS = 3        # Advisers/Users
COL_TITLE = 4           # Title
COL_VERBATIM = 5        # Verbatim (grouped by adviser)
COL_AR_MATCH = 6        # AR Match (written by agent)
COL_REVIEWED = 7        # Reviewed (written by agent)

HEADER_ROW = 1  # 1-indexed, the first row


# ══════════════════════════════════════════════════════════════════════════════
# GOOGLE SHEETS CLIENT
# ══════════════════════════════════════════════════════════════════════════════

_gspread_client = None


def _get_gspread_client():
    """Lazy-init gspread client from service account JSON."""
    global _gspread_client
    if _gspread_client:
        return _gspread_client

    if not GOOGLE_SERVICE_ACCOUNT_JSON:
        raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON env var not set.")

    import gspread
    from google.oauth2.service_account import Credentials

    creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    _gspread_client = gspread.authorize(creds)
    return _gspread_client


def _get_worksheet():
    """Open the VoA sheet and return the worksheet."""
    if not VOA_SHEET_ID:
        raise RuntimeError("VOA_SHEET_ID env var not set.")

    gc = _get_gspread_client()
    spreadsheet = gc.open_by_key(VOA_SHEET_ID)

    try:
        return spreadsheet.worksheet(SHEET_TAB_NAME)
    except Exception:
        # Fallback to first sheet
        log.warning(f"JOB A3: Sheet tab '{SHEET_TAB_NAME}' not found, using first sheet.")
        return spreadsheet.sheet1


def _ensure_headers(ws):
    """Ensure AR Match and Reviewed columns exist in the header row."""
    headers = ws.row_values(HEADER_ROW)

    # Pad headers if needed
    while len(headers) < COL_REVIEWED + 1:
        headers.append("")

    changed = False
    if headers[COL_AR_MATCH] != "AR Match":
        headers[COL_AR_MATCH] = "AR Match"
        changed = True
    if headers[COL_REVIEWED] != "Reviewed":
        headers[COL_REVIEWED] = "Reviewed"
        changed = True

    if changed:
        # Update header row (columns G and H)
        ws.update_cell(HEADER_ROW, COL_AR_MATCH + 1, "AR Match")
        ws.update_cell(HEADER_ROW, COL_REVIEWED + 1, "Reviewed")
        log.info("JOB A3: Added AR Match and Reviewed column headers.")


def read_unreviewed_rows(ws):
    """Read all rows where the Reviewed column is empty. Returns list of dicts."""
    all_rows = ws.get_all_values()
    if len(all_rows) <= 1:
        return []

    unreviewed = []
    for row_idx, row in enumerate(all_rows[1:], start=2):  # 1-indexed, skip header
        # Pad row if shorter than expected
        while len(row) < COL_REVIEWED + 1:
            row.append("")

        reviewed = row[COL_REVIEWED].strip()
        if reviewed:
            continue

        verbatim = row[COL_VERBATIM].strip() if len(row) > COL_VERBATIM else ""
        if not verbatim:
            continue

        unreviewed.append({
            "sheet_row": row_idx,  # 1-indexed row number in sheet
            "row_num": row[COL_ROW_NUM].strip(),
            "theme": row[COL_THEME].strip() if len(row) > COL_THEME else "",
            "verbatim_theme": row[COL_VERBATIM_THEME].strip() if len(row) > COL_VERBATIM_THEME else "",
            "advisers": row[COL_ADVISERS].strip() if len(row) > COL_ADVISERS else "",
            "title": row[COL_TITLE].strip() if len(row) > COL_TITLE else "",
            "verbatim": verbatim,
        })

    return unreviewed


def mark_reviewed(ws, sheet_row, ar_keys):
    """Mark a row as reviewed with timestamp and AR match keys."""
    sydney_tz = pytz.timezone("Australia/Sydney")
    now = datetime.now(sydney_tz).strftime("%Y-%m-%d %H:%M")
    ar_text = ", ".join(ar_keys) if ar_keys else "No match"

    ws.update_cell(sheet_row, COL_AR_MATCH + 1, ar_text)
    ws.update_cell(sheet_row, COL_REVIEWED + 1, now)


def mark_reviewed_batch(ws, updates):
    """Batch update reviewed rows. updates: list of (sheet_row, ar_keys)."""
    sydney_tz = pytz.timezone("Australia/Sydney")
    now = datetime.now(sydney_tz).strftime("%Y-%m-%d %H:%M")

    if not updates:
        return

    # Use batch_update for efficiency
    cells = []
    import gspread
    for sheet_row, ar_keys in updates:
        ar_text = ", ".join(ar_keys) if ar_keys else "No match"
        cells.append(gspread.Cell(sheet_row, COL_AR_MATCH + 1, ar_text))
        cells.append(gspread.Cell(sheet_row, COL_REVIEWED + 1, now))

    ws.update_cells(cells)
    log.info(f"JOB A3: Batch-marked {len(updates)} rows as reviewed.")


# ══════════════════════════════════════════════════════════════════════════════
# AR IDEAS FETCHER
# ══════════════════════════════════════════════════════════════════════════════

def fetch_ar_ideas():
    """Fetch all AR ideas with summary and description excerpt for matching."""
    ideas = []
    start_at = 0
    max_results = 100

    while True:
        data = jira_get("/rest/api/3/search/jql", params={
            "jql": f"project = {AR_PROJECT_KEY} ORDER BY key ASC",
            "fields": "summary,description,status",
            "maxResults": max_results,
            "startAt": start_at,
        })
        if not data:
            break

        for issue in data.get("issues", []):
            summary = issue["fields"].get("summary", "")
            # Extract first ~200 chars of description text
            desc_adf = issue["fields"].get("description")
            desc_text = _extract_adf_text(desc_adf)[:200] if desc_adf else ""
            status = (issue["fields"].get("status") or {}).get("name", "")

            ideas.append({
                "key": issue["key"],
                "summary": summary,
                "description_excerpt": desc_text,
                "status": status,
            })

        total = data.get("total", 0)
        start_at += max_results
        if start_at >= total:
            break

    log.info(f"JOB A3: Fetched {len(ideas)} AR ideas for matching.")
    return ideas


def _extract_adf_text(node):
    """Recursively extract plain text from ADF node."""
    if not node:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if node.get("type") == "text":
            return node.get("text", "")
        children = node.get("content", [])
        return " ".join(_extract_adf_text(c) for c in children)
    if isinstance(node, list):
        return " ".join(_extract_adf_text(c) for c in node)
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# AI MATCHING
# ══════════════════════════════════════════════════════════════════════════════

def match_verbatim_to_ideas(verbatim_batch, ar_ideas):
    """Use Claude to match a batch of verbatim to the most relevant AR ideas.

    Returns list of {verbatim_index, ar_keys: [str], impact: str}
    """
    # Build compact idea list for prompt
    ideas_text = "\n".join([
        f"- {idea['key']}: {idea['summary']}"
        for idea in ar_ideas
    ])

    verbatim_text = "\n".join([
        f"[{i}] ({v['theme']} / {v['verbatim_theme']}) \"{v['verbatim']}\""
        for i, v in enumerate(verbatim_batch)
    ])

    prompt = (
        "You are matching customer verbatim feedback to product roadmap ideas.\n\n"
        "ROADMAP IDEAS:\n"
        f"{ideas_text}\n\n"
        "VERBATIM TO MATCH:\n"
        f"{verbatim_text}\n\n"
        "For each verbatim [index], identify the 1-3 most relevant AR ideas and an impact rating.\n"
        "Impact ratings: 3 = directly describes this idea, 2 = strongly related, 1 = loosely related.\n"
        "If no idea matches well (confidence < 60%), set ar_keys to empty array.\n\n"
        "Return ONLY valid JSON array:\n"
        '[{"idx": 0, "ar_keys": ["AR-123", "AR-45"], "impact": 2}, ...]\n'
        "No preamble, no markdown fences."
    )

    response = call_claude(prompt, max_tokens=2000)
    if not response:
        log.warning("JOB A3: Claude returned empty response for matching.")
        return [{"idx": i, "ar_keys": [], "impact": 0} for i in range(len(verbatim_batch))]

    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response.strip())
        clean = re.sub(r'\s*```$', '', clean)
        results = json.loads(clean)
        return results
    except json.JSONDecodeError as e:
        log.warning(f"JOB A3: Claude JSON parse error: {e}")
        return [{"idx": i, "ar_keys": [], "impact": 0} for i in range(len(verbatim_batch))]


# ══════════════════════════════════════════════════════════════════════════════
# JPD INSIGHTS (GRAPHQL)
# ══════════════════════════════════════════════════════════════════════════════

_ar_project_id = None


def _get_ar_project_id():
    """Discover AR project's numeric ID (cached)."""
    global _ar_project_id
    if _ar_project_id:
        return _ar_project_id

    data = jira_get(f"/rest/api/3/project/{AR_PROJECT_KEY}")
    if data:
        _ar_project_id = data["id"]
        log.info(f"JOB A3: AR project numeric ID: {_ar_project_id}")
    return _ar_project_id


def _get_issue_id(issue_key):
    """Get the numeric issue ID for an AR ticket."""
    data = jira_get(f"/rest/api/3/issue/{issue_key}", params={"fields": "summary"})
    if data:
        return data["id"]
    return None


def create_insight(issue_key, description, impact_rating=2):
    """Create a JPD insight on an AR idea via the experimental GraphQL API.

    impact_rating: 1-3 (1=low, 2=medium, 3=high)
    Returns True on success, False on failure.
    """
    import requests
    from requests.auth import HTTPBasicAuth

    project_id = _get_ar_project_id()
    issue_id = _get_issue_id(issue_key)
    if not project_id or not issue_id:
        log.error(f"JOB A3: Could not resolve IDs for {issue_key}")
        return False

    project_ari = f"ari:cloud:jira:{ATLASSIAN_CLOUD_ID}:project/{project_id}"
    issue_ari = f"ari:cloud:jira:{ATLASSIAN_CLOUD_ID}:issue/{issue_id}"

    # ADF description for the insight
    adf_desc = json.dumps({
        "version": 1,
        "type": "doc",
        "content": [{
            "type": "paragraph",
            "content": [{"type": "text", "text": description}]
        }]
    })

    # Map impact: 1→-1 (low), 2→0 (neutral/medium), 3→1 (high) — JPD rating scale
    # JPD uses: -2, -1, 0, 1, 2 (very negative to very positive)
    impact_map = {1: 0, 2: 1, 3: 2}
    jpd_impact = impact_map.get(impact_rating, 1)

    mutation = """
    mutation CreateInsight($projectAri: ID!, $issueAri: ID!, $description: String!, $impact: Int!) {
        createPolarisInsight(
            project: $projectAri,
            container: $issueAri,
            description: $description,
            impact: $impact
        ) {
            id
        }
    }
    """

    gql_url = f"{JIRA_BASE_URL}/gateway/api/graphql"
    auth = HTTPBasicAuth(JIRA_EMAIL, JIRA_API_TOKEN)
    headers = {
        "Content-Type": "application/json",
        "X-ExperimentalApi": "polaris-v0",
    }

    try:
        r = requests.post(gql_url, auth=auth, headers=headers, timeout=30, json={
            "query": mutation,
            "variables": {
                "projectAri": project_ari,
                "issueAri": issue_ari,
                "description": adf_desc,
                "impact": jpd_impact,
            }
        })

        if r.ok:
            data = r.json()
            if "errors" in data:
                log.warning(f"JOB A3: GraphQL errors for {issue_key}: {data['errors']}")
                # Try alternative mutation format
                return _create_insight_alternative(issue_key, issue_ari, project_ari,
                                                   description, jpd_impact, auth, headers, gql_url)
            log.info(f"JOB A3: Created insight on {issue_key}")
            return True
        else:
            log.warning(f"JOB A3: GraphQL request failed ({r.status_code}): {r.text[:300]}")
            return _create_insight_alternative(issue_key, issue_ari, project_ari,
                                               description, jpd_impact, auth, headers, gql_url)
    except Exception as e:
        log.error(f"JOB A3: Insight creation error for {issue_key}: {e}")
        return False


def _create_insight_alternative(issue_key, issue_ari, project_ari, description, impact,
                                 auth, headers, gql_url):
    """Try alternative GraphQL mutation formats for insight creation."""
    import requests

    # Alternative 1: Different mutation name / structure
    alt_mutations = [
        # Format from Forge push-example pattern
        """
        mutation {
            polarisCreateInsight(
                project: "%s",
                container: "%s",
                description: "%s",
                impact: %d
            ) {
                id
            }
        }
        """ % (project_ari, issue_ari, description.replace('"', '\\"'), impact),

        # Format with input object
        """
        mutation {
            jira_createPolarisInsight(input: {
                project: "%s",
                container: "%s",
                description: "%s",
                impact: %d
            }) {
                id
            }
        }
        """ % (project_ari, issue_ari, description.replace('"', '\\"'), impact),
    ]

    for i, mutation in enumerate(alt_mutations):
        try:
            r = requests.post(gql_url, auth=auth, headers=headers, timeout=30,
                              json={"query": mutation})
            if r.ok:
                data = r.json()
                if "errors" not in data or not data["errors"]:
                    log.info(f"JOB A3: Created insight on {issue_key} (alt format {i+1})")
                    return True
                log.debug(f"JOB A3: Alt {i+1} errors: {data.get('errors', [])}")
        except Exception as e:
            log.debug(f"JOB A3: Alt {i+1} error: {e}")

    # All GraphQL attempts failed — log for debugging
    log.warning(f"JOB A3: All GraphQL insight formats failed for {issue_key}. "
                f"Insight text: {description[:100]}...")
    return False


# ══════════════════════════════════════════════════════════════════════════════
# MAIN JOB
# ══════════════════════════════════════════════════════════════════════════════

def run_voa_monitor():
    """JOB A3: Read VoA sheet, match verbatim to AR ideas, create insights, mark reviewed."""
    log.info("JOB A3: Starting VoA Monitor...")

    if not GOOGLE_SERVICE_ACCOUNT_JSON or not VOA_SHEET_ID:
        log.info("JOB A3: Skipped — GOOGLE_SERVICE_ACCOUNT_JSON or VOA_SHEET_ID not set.")
        return

    try:
        ws = _get_worksheet()
        _ensure_headers(ws)
    except Exception as e:
        log.error(f"JOB A3: Failed to open sheet: {e}")
        send_telegram(f"❌ VoA Monitor: Failed to open Google Sheet: {e}")
        return

    # Read unreviewed rows
    unreviewed = read_unreviewed_rows(ws)
    if not unreviewed:
        log.info("JOB A3: No unreviewed verbatim found.")
        return

    log.info(f"JOB A3: Found {len(unreviewed)} unreviewed verbatim.")

    # Fetch all AR ideas for matching
    ar_ideas = fetch_ar_ideas()
    if not ar_ideas:
        log.error("JOB A3: No AR ideas found — cannot match.")
        send_telegram("❌ VoA Monitor: No AR ideas found for matching.")
        return

    # Process in batches
    total_matched = 0
    total_insights = 0
    total_no_match = 0
    insight_failures = 0
    review_updates = []  # (sheet_row, ar_keys)
    ideas_touched = set()

    for batch_start in range(0, len(unreviewed), BATCH_SIZE):
        batch = unreviewed[batch_start:batch_start + BATCH_SIZE]
        log.info(f"JOB A3: Processing batch {batch_start // BATCH_SIZE + 1} "
                 f"({len(batch)} verbatim)...")

        # AI matching
        matches = match_verbatim_to_ideas(batch, ar_ideas)

        for match in matches:
            idx = match.get("idx", 0)
            ar_keys = match.get("ar_keys", [])
            impact = match.get("impact", 0)

            if idx >= len(batch):
                continue

            verbatim_row = batch[idx]
            sheet_row = verbatim_row["sheet_row"]

            if not ar_keys:
                total_no_match += 1
                review_updates.append((sheet_row, []))
                continue

            total_matched += 1

            # Create insight on each matched AR idea
            adviser_text = verbatim_row["advisers"] or "Unknown adviser"
            insight_desc = (
                f"[VoA] {adviser_text}: \"{verbatim_row['verbatim']}\""
            )

            created_keys = []
            for ar_key in ar_keys:
                success = create_insight(ar_key, insight_desc, impact_rating=impact)
                if success:
                    total_insights += 1
                    created_keys.append(ar_key)
                    ideas_touched.add(ar_key)
                else:
                    insight_failures += 1
                    created_keys.append(f"{ar_key}?")  # Mark uncertain

            review_updates.append((sheet_row, created_keys))

    # Batch update the sheet
    if review_updates:
        try:
            mark_reviewed_batch(ws, review_updates)
        except Exception as e:
            log.error(f"JOB A3: Failed to batch-update sheet: {e}")
            # Fall back to individual updates
            for sheet_row, ar_keys in review_updates:
                try:
                    mark_reviewed(ws, sheet_row, ar_keys)
                except Exception as e2:
                    log.error(f"JOB A3: Failed to mark row {sheet_row}: {e2}")

    # Summary
    summary = (
        f"📊 *VoA Monitor Complete*\n\n"
        f"Processed: {len(unreviewed)} verbatim\n"
        f"Matched: {total_matched} → {total_insights} insights across {len(ideas_touched)} ideas\n"
        f"No match: {total_no_match}"
    )
    if insight_failures:
        summary += f"\n⚠️ {insight_failures} insight creation failures (GraphQL)"

    send_telegram(summary)
    log.info(f"JOB A3: Done — {total_matched} matched, {total_insights} insights, "
             f"{total_no_match} unmatched, {insight_failures} failures.")
