"""
PM Agent — Sprint Summary Email Generator
Telegram: /sprint_summary <brain-dump text>
Workflow:
  1. Fetch Jira sprint data (current + next)
  2. Fetch DB metrics (Lives Insured / PCP)
  3. Claude structures the brain-dump into template sections
  4. Render Outlook-safe HTML email
  5. Send to james@ via Microsoft Graph
"""

import os
import re
import json
from datetime import datetime
import pytz

from config import log, STORY_POINTS_FIELD
from jira_client import get_active_sprints, get_future_sprints, get_sprint_issues
from crm_db import get_lives_insured_metrics
from claude_client import call_claude

SYDNEY_TZ = pytz.timezone("Australia/Sydney")
RECIPIENTS = ["james@axiscrm.com.au"]
SENDER = "axel@axiscrm.com.au"

# ── Load base64 images from template assets ──
_ASSETS_DIR = os.path.join(os.path.dirname(__file__), "templates")

def _load_b64(filename):
    path = os.path.join(_ASSETS_DIR, filename)
    try:
        with open(path, "r") as f:
            return f.read().strip()
    except Exception as e:
        log.warning(f"Sprint summary: Could not load {filename}: {e}")
        return ""

HEADER_B64 = _load_b64("sprint_summary_img0.b64")
FOOTER_B64 = _load_b64("sprint_summary_img1.b64")


# ══════════════════════════════════════════════════════════════════════════════
# JIRA DATA
# ══════════════════════════════════════════════════════════════════════════════

def _get_sprint_data():
    """Get current sprint info + delivery counts + next sprint info."""
    data = {
        "this_sprint_num": "??",
        "this_sprint_dates": "??",
        "this_sprint_start": "",
        "this_sprint_end": "",
        "next_sprint_num": "??",
        "next_sprint_dates": "??",
        "shipped": 0,
        "in_progress": 0,
        "todo": 0,
        "total_points": 0,
    }

    active = get_active_sprints()
    if not active:
        log.warning("Sprint summary: No active sprint found")
        return data

    sprint = active[0]
    name = sprint.get("name", "Sprint ??")
    # Extract sprint number from name (e.g., "AX Sprint 36" -> "36")
    num_match = re.search(r'(\d+)', name)
    sprint_num = num_match.group(1) if num_match else "??"
    data["this_sprint_num"] = sprint_num

    start_str = sprint.get("startDate", "")
    end_str = sprint.get("endDate", "")
    if start_str and end_str:
        try:
            start_dt = datetime.fromisoformat(start_str.replace("Z", "+00:00")).astimezone(SYDNEY_TZ)
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00")).astimezone(SYDNEY_TZ)
            data["this_sprint_start"] = start_dt.strftime("%-d %B %Y")
            data["this_sprint_end"] = end_dt.strftime("%-d %B %Y")
            # Format as "8 – 12 June 2026"
            if start_dt.month == end_dt.month:
                data["this_sprint_dates"] = f"{start_dt.day} &ndash; {end_dt.day} {end_dt.strftime('%B %Y')}"
            else:
                data["this_sprint_dates"] = f"{start_dt.strftime('%-d %B')} &ndash; {end_dt.strftime('%-d %B %Y')}"
        except Exception:
            pass

    # Count issues by status
    issues = get_sprint_issues(sprint["id"])
    shipped_statuses = {"done", "released", "🚀 shipped"}
    progress_statuses = {"in progress", "in testing", "in review", "code review"}
    todo_statuses = {"to do", "ready", "technical planning", "refinement"}

    for issue in issues:
        status = issue["fields"]["status"]["name"].lower()
        pts = issue["fields"].get(STORY_POINTS_FIELD) or 0
        data["total_points"] += pts
        if status in shipped_statuses:
            data["shipped"] += 1
        elif status in progress_statuses:
            data["in_progress"] += 1
        else:
            data["todo"] += 1

    # Next sprint
    future = get_future_sprints()
    if future:
        next_sprint = future[0]
        next_name = next_sprint.get("name", "Sprint ??")
        next_num = re.search(r'(\d+)', next_name)
        data["next_sprint_num"] = next_num.group(1) if next_num else str(int(sprint_num) + 1)

        next_start = next_sprint.get("startDate", "")
        next_end = next_sprint.get("endDate", "")
        if next_start and next_end:
            try:
                ns = datetime.fromisoformat(next_start.replace("Z", "+00:00")).astimezone(SYDNEY_TZ)
                ne = datetime.fromisoformat(next_end.replace("Z", "+00:00")).astimezone(SYDNEY_TZ)
                if ns.month == ne.month:
                    data["next_sprint_dates"] = f"{ns.day} &ndash; {ne.day} {ne.strftime('%B %Y')}"
                else:
                    data["next_sprint_dates"] = f"{ns.strftime('%-d %B')} &ndash; {ne.strftime('%-d %B %Y')}"
            except Exception:
                pass
    else:
        data["next_sprint_num"] = str(int(sprint_num) + 1)

    return data


# ══════════════════════════════════════════════════════════════════════════════
# CLAUDE STRUCTURING
# ══════════════════════════════════════════════════════════════════════════════

STRUCTURE_PROMPT = """You are a senior product manager at Axis, a life insurance distribution CRM company. Structure the following brain-dump into a weekly sprint summary email.

Sprint context:
- Current sprint: Sprint {this_sprint_num} ({this_sprint_dates})
- Next sprint: Sprint {next_sprint_num} ({next_sprint_dates})
- Delivery: {shipped} shipped, {in_progress} in progress, {todo} to do

Brain-dump:
\"\"\"
{braindump}
\"\"\"

Return ONLY valid JSON (no preamble, no markdown fences) with this exact structure:
{{
  "goal_status": "MET" or "IN PROGRESS" or "NOT MET",
  "goal_text": "short goal description (lowercase)",
  "this_week_summary": "1-2 paragraph summary of what happened this week",
  "features": [
    {{"title": "Feature name", "description": "what it does/why it matters"}},
  ],
  "bugs_fixed": "bug1 (raised by · status); bug2 (raised by · status)" or null,
  "next_week_goal": "short goal description",
  "next_week_headlining_title": "Main feature name",
  "next_week_headlining_description": "detailed description of the headline feature",
  "next_week_deliverables": [
    {{"title": "Feature name", "description": "what it does"}},
  ],
  "roadmap_phases": [
    {{"name": "PHASE NAME IN CAPS", "description": "short description", "status": "complete" or "current" or "future", "features": [{{"name": "Feature", "status": "done" or "in_progress" or "todo"}}]}}
  ],
  "signoff_text": "custom closing line or null for default",
  "signoff_name": "James"
}}

Rules:
- Write in professional, concise language
- Features should have bold-worthy titles and clear descriptions
- Roadmap phases: mark exactly one as "current" (the "WE ARE HERE" phase)
- If info is missing from the brain-dump, use reasonable defaults based on context
- Do NOT include markdown formatting in the values — plain text only"""


def _structure_braindump(braindump, sprint_data):
    """Use Claude to structure the brain-dump into template sections."""
    prompt = STRUCTURE_PROMPT.format(
        this_sprint_num=sprint_data["this_sprint_num"],
        this_sprint_dates=sprint_data["this_sprint_dates"].replace("&ndash;", "–"),
        next_sprint_num=sprint_data["next_sprint_num"],
        next_sprint_dates=sprint_data["next_sprint_dates"].replace("&ndash;", "–"),
        shipped=sprint_data["shipped"],
        in_progress=sprint_data["in_progress"],
        todo=sprint_data["todo"],
        braindump=braindump,
    )

    response = call_claude(prompt, max_tokens=3000)
    if not response:
        return None

    try:
        clean = re.sub(r'^```(?:json)?\s*', '', response.strip())
        clean = re.sub(r'\s*```$', '', clean)
        return json.loads(clean)
    except json.JSONDecodeError as e:
        log.error(f"Sprint summary: Claude JSON parse error: {e}")
        log.debug(f"Claude response: {response[:500]}")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# HTML RENDERING
# ══════════════════════════════════════════════════════════════════════════════

def _format_metric_dates(date_obj):
    """Format date for the metric strip (e.g., '5 – 11 JUN')."""
    if not date_obj:
        return "N/A"
    try:
        return date_obj.strftime("%-d %b").upper()
    except Exception:
        return str(date_obj)


def _render_features_html(features):
    """Render features list as table rows."""
    if not features:
        return ""
    rows = []
    for f in features:
        title = f.get("title", "")
        desc = f.get("description", "")
        rows.append(
            f'    <tr><td style="padding:4px 0;"><span style="color:#e8501e;">&#9656;</span> '
            f'<b>{title}</b> &mdash; {desc}</td></tr>'
        )
    return "\n".join(rows)


def _render_deliverables_html(deliverables):
    """Render next week deliverables as table rows."""
    return _render_features_html(deliverables)


def _render_roadmap_html(phases):
    """Render the roadmap timeline section."""
    if not phases:
        return ""

    rows = []
    for phase in phases:
        name = phase.get("name", "PHASE")
        desc = phase.get("description", "")
        status = phase.get("status", "future")
        features = phase.get("features", [])

        if status == "complete":
            marker = '<td width="90" valign="top" style="font-size:9px; letter-spacing:1px; color:#2da44e; font-weight:700; padding-top:3px;">COMPLETE &#9656;</td>'
        elif status == "current":
            marker = '<td width="90" valign="top" style="font-size:9px; letter-spacing:1px; color:#e8501e; font-weight:700; padding-top:3px;">WE ARE HERE &#9656;</td>'
        else:
            marker = '<td></td>'

        feature_html = ""
        if features:
            left_features = features[:len(features)//2 + len(features)%2]
            right_features = features[len(features)//2 + len(features)%2:]

            def _feature_line(feat):
                s = feat.get("status", "todo")
                n = feat.get("name", "")
                if s == "done":
                    return f'<span style="color:#2da44e;">&#10004;</span> <b>{n}</b><br>'
                elif s == "in_progress":
                    return f'<span style="color:#e8501e;">&#9680;</span> <b>{n}</b><br>'
                else:
                    return f'<span style="color:#e8501e;">&#9656;</span> <b>{n}</b><br>'

            left_html = "\n".join(_feature_line(f) for f in left_features)
            right_html = "\n".join(_feature_line(f) for f in right_features)

            feature_html = f'''
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:12px; line-height:1.7; margin-top:8px;">
          <tr>
            <td width="50%" valign="top">{left_html}</td>
            <td width="50%" valign="top">{right_html}</td>
          </tr>
        </table>'''

        rows.append(f'''    <tr>
      {marker}
      <td valign="top" style="padding-bottom:16px; border-left:2px solid #d8dbe0; padding-left:16px;">
        <div style="font-size:11px; letter-spacing:2px; font-weight:700; color:#1d2630;">{name}</div>
        <div style="color:#4a5158; padding-top:4px; line-height:1.5;">{desc}</div>{feature_html}
      </td>
    </tr>''')

    return "\n".join(rows)


def _render_html(structured, sprint_data, db_metrics):
    """Build the complete Outlook-safe HTML email."""

    # Metrics
    lives_today = f"{db_metrics['lives_today']:,}" if db_metrics else "N/A"
    pct_change = db_metrics.get("pct_change", 0) if db_metrics else 0
    lives_pcp = f"{db_metrics['lives_pcp']:,}" if db_metrics else "N/A"

    if pct_change and float(pct_change) > 0:
        change_html = f'<span style="font-size:8px; color:#3fb950;">&#9650; {pct_change}%</span>'
    elif pct_change and float(pct_change) < 0:
        change_html = f'<span style="font-size:8px; color:#f85149;">&#9660; {abs(float(pct_change))}%</span>'
    else:
        change_html = '<span style="font-size:8px; color:#8a929b;">0%</span>'

    snap_date = db_metrics.get("snapshot_date", "") if db_metrics else ""
    pcp_date = db_metrics.get("pcp_date", "") if db_metrics else ""

    now = datetime.now(SYDNEY_TZ)

    # Sprint data
    sn = sprint_data["this_sprint_num"]
    sd = sprint_data["this_sprint_dates"]
    nsn = sprint_data["next_sprint_num"]
    nsd = sprint_data["next_sprint_dates"]
    shipped = sprint_data["shipped"]
    in_prog = sprint_data["in_progress"]
    todo = sprint_data["todo"]

    # Structured content
    goal_status = structured.get("goal_status", "IN PROGRESS")
    goal_text = structured.get("goal_text", "")
    summary = structured.get("this_week_summary", "")
    features_html = _render_features_html(structured.get("features", []))
    bugs = structured.get("bugs_fixed")
    bugs_html = f'<tr><td style="padding:8px 0 0 0; font-size:12px; font-style:italic; color:#6a7280;">Bugs fixed: {bugs}</td></tr>' if bugs else ""

    nw_goal = structured.get("next_week_goal", "")
    nw_head_title = structured.get("next_week_headlining_title", "")
    nw_head_desc = structured.get("next_week_headlining_description", "")
    nw_deliverables_html = _render_deliverables_html(structured.get("next_week_deliverables", []))

    roadmap_html = _render_roadmap_html(structured.get("roadmap_phases", []))

    signoff_text = structured.get("signoff_text") or f"Happy to walk through any of the above &mdash; otherwise, on to Sprint {nsn}. Thanks to Marc, Andrej and Dave for the work this sprint."
    signoff_name = structured.get("signoff_name", "James")

    # Date formatting for metric strip
    try:
        from datetime import timedelta
        snap_end = snap_date
        snap_start = pcp_date
        if hasattr(snap_date, 'strftime'):
            snap_range = f"{(snap_date).strftime('%-d')} &ndash; {snap_end.strftime('%-d %b').upper()}"
            pcp_range = f"{(pcp_date - timedelta(days=6)).strftime('%-d %b').upper()} &ndash; {pcp_date.strftime('%-d %b').upper()}"
        else:
            snap_range = str(snap_date)
            pcp_range = str(pcp_date)
    except Exception:
        snap_range = "N/A"
        pcp_range = "N/A"

    # Delivery metrics date
    delivery_date = now.strftime("%a %-d %b").upper()

    html = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AXIS Product &amp; Engineering &mdash; Sprint {sn}</title>
<style type="text/css">
  @media only screen and (max-width: 480px) {{
    .metrics-strip-table td.vision-cell,
    .metrics-strip-table td.metric-cell {{
      display: block !important;
      width: 100% !important;
      text-align: left !important;
      padding: 4px 0 !important;
    }}
    .metrics-strip-table td.metric-cell {{
      display: inline-block !important;
      width: 48% !important;
    }}
  }}
</style>
</head>
<body style="margin:0; padding:0; background:#f2f3f5; font-family:Segoe UI, Helvetica, Arial, sans-serif; color:#2b2f36;">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f2f3f5;">
<tr><td align="center" style="padding:24px 12px;">
<table role="presentation" width="680" cellpadding="0" cellspacing="0" style="max-width:680px; width:100%; background:#ffffff; border:1px solid #e1e4e8;">

<!-- HEADER -->
<tr><td style="padding:16px 0 0 0; line-height:0; background:#222b36;">
  <img src="data:image/png;base64,{HEADER_B64}" alt="AXIS &mdash; Product &amp; Engineering" width="680" style="width:100%; max-width:680px; height:auto; display:block;">
</td></tr>

<!-- VISION + METRICS STRIP -->
<tr><td style="background:#10161d; padding:7px 32px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" class="metrics-strip-table">
    <tr>
      <td valign="middle" class="vision-cell" style="padding-right:16px; padding-bottom:2px;">
        <div style="font-size:10px; font-style:italic; color:#ffffff; line-height:1.4; white-space:nowrap;"><span style="color:#e8501e;">Lower the barriers,</span> to operate a successful general advice business</div>
      </td>
      <td width="110" align="right" valign="middle" class="metric-cell" style="padding-right:16px; white-space:nowrap;">
        <div style="font-size:7px; letter-spacing:1px; color:#8a929b; white-space:nowrap;">LIVES INSURED</div>
        <div style="font-size:13px; font-weight:700; color:#ffffff; white-space:nowrap;">{lives_today} {change_html}</div>
        <div style="font-size:7px; letter-spacing:1px; color:#8a929b; white-space:nowrap;">{snap_range}</div>
      </td>
      <td width="90" align="right" valign="middle" class="metric-cell" style="white-space:nowrap;">
        <div style="font-size:7px; letter-spacing:1px; color:#8a929b; white-space:nowrap;">PCP</div>
        <div style="font-size:13px; font-weight:700; color:#ffffff; white-space:nowrap;">{lives_pcp}</div>
        <div style="font-size:7px; letter-spacing:1px; color:#8a929b; white-space:nowrap;">{pcp_range}</div>
      </td>
    </tr>
  </table>
</td></tr>

<!-- THIS WEEK -->
<tr><td style="padding:30px 32px 8px 32px;">
  <div style="font-size:24px; font-weight:600; color:#1d2630;">This Week</div>
  <div style="font-size:12px; color:#6a7280; padding-top:4px;">Sprint {sn} &nbsp;&middot;&nbsp; {sd} &nbsp;&middot;&nbsp; <span style="color:#e8501e; font-weight:700; letter-spacing:1px;">GOAL: {goal_status}</span> &nbsp;&middot;&nbsp; {goal_text}</div>
  <p style="font-size:13px; line-height:1.55; color:#2b2f36; margin:14px 0 0 0;">{summary}</p>
</td></tr>

<tr><td style="padding:18px 32px 0 32px;">
  <div style="font-size:10px; letter-spacing:2px; color:#e8501e; font-weight:700; padding-bottom:8px;">FEATURES &amp; ENHANCEMENTS</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:13px; line-height:1.5;">
{features_html}
{bugs_html}
  </table>
</td></tr>

<!-- SPRINT DELIVERY METRICS -->
<tr><td style="padding:22px 32px 0 32px;">
  <div style="font-size:10px; letter-spacing:2px; color:#e8501e; font-weight:700; padding-bottom:8px;">SPRINT {sn} DELIVERY &mdash; AS AT {delivery_date}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td width="33%" style="background:#f6f7f9; border-top:3px solid #e8501e; padding:12px 14px;">
        <div style="font-size:24px; font-weight:700; color:#e8501e;">{shipped}</div>
        <div style="font-size:9px; letter-spacing:1px; color:#6a7280;">SHIPPED</div>
      </td>
      <td width="8">&nbsp;</td>
      <td width="33%" style="background:#f6f7f9; border-top:3px solid #1d2630; padding:12px 14px;">
        <div style="font-size:24px; font-weight:700; color:#1d2630;">{in_prog}</div>
        <div style="font-size:9px; letter-spacing:1px; color:#6a7280;">IN TESTING / IN PROGRESS</div>
      </td>
      <td width="8">&nbsp;</td>
      <td width="33%" style="background:#f6f7f9; border-top:3px solid #1d2630; padding:12px 14px;">
        <div style="font-size:24px; font-weight:700; color:#1d2630;">{todo}</div>
        <div style="font-size:9px; letter-spacing:1px; color:#6a7280;">TO DO</div>
      </td>
    </tr>
  </table>
</td></tr>

<!-- NEXT WEEK -->
<tr><td style="padding:32px 32px 0 32px;">
  <div style="font-size:24px; font-weight:600; color:#1d2630;">Next Week</div>
  <div style="font-size:12px; color:#6a7280; padding-top:4px;">Sprint {nsn} &nbsp;&middot;&nbsp; {nsd}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px;">
    <tr><td style="border-left:3px solid #e8501e; padding:6px 14px;">
      <div style="font-size:10px; letter-spacing:2px; color:#e8501e; font-weight:700;">SPRINT GOAL</div>
      <div style="font-size:13px; padding-top:3px;">{nw_goal}</div>
    </td></tr>
  </table>
  <div style="font-size:10px; letter-spacing:2px; color:#e8501e; font-weight:700; padding:16px 0 6px 0;">HEADLINING</div>
  <p style="font-size:13px; line-height:1.55; margin:0;"><b>{nw_head_title}</b> &mdash; {nw_head_desc}</p>
  <div style="font-size:10px; letter-spacing:2px; color:#e8501e; font-weight:700; padding:16px 0 6px 0;">OTHER KEY DELIVERABLES</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="font-size:13px; line-height:1.5;">
{nw_deliverables_html}
  </table>
</td></tr>

<!-- ROADMAP -->
<tr><td style="padding:32px 32px 0 32px;">
  <div style="font-size:24px; font-weight:600; color:#1d2630;">Roadmap</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:14px; font-size:13px;">
{roadmap_html}
  </table>
</td></tr>

<!-- SIGN-OFF -->
<tr><td style="padding:28px 32px 48px 32px;">
  <p style="font-size:13px; line-height:1.55; margin:0;">{signoff_text}</p>
  <p style="font-size:13px; margin:14px 0 0 0;">{signoff_name}</p>
</td></tr>

<!-- FOOTER -->
<tr><td style="border-top:1px solid #e1e4e8; padding:16px 32px; background:#f6f7f9;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
    <tr>
      <td><img src="data:image/png;base64,{FOOTER_B64}" alt="AXIS" width="266" style="width:266px; height:auto; display:block;"></td>
      <td align="right" style="font-size:9px; letter-spacing:2px; color:#6a7280;">SPRINT {sn}</td>
    </tr>
  </table>
</td></tr>

</table>
</td></tr>
</table>
</body>
</html>'''

    return html


# ══════════════════════════════════════════════════════════════════════════════
# EMAIL SENDING (via Graph)
# ══════════════════════════════════════════════════════════════════════════════

def _send_email(subject, html_body):
    """Send the sprint summary via Microsoft Graph."""
    import requests
    from ms_graph_auth import refresh_access_token

    token, err = refresh_access_token()
    if not token:
        return False, f"Graph auth failed: {err}"

    payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": html_body,
            },
            "toRecipients": [
                {"emailAddress": {"address": r}} for r in RECIPIENTS
            ],
        },
        "saveToSentItems": "true",
    }

    try:
        resp = requests.post(
            "https://graph.microsoft.com/v1.0/me/sendMail",
            json=payload,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            timeout=60,
        )
        if resp.status_code == 202:
            return True, f"sent to {len(RECIPIENTS)} recipient(s)"
        else:
            return False, f"Graph send failed ({resp.status_code}): {resp.text[:300]}"
    except Exception as e:
        return False, f"Graph send error: {e}"


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINTS
# ══════════════════════════════════════════════════════════════════════════════

def build_and_send_summary(braindump_text):
    """Full pipeline: Jira + DB + Claude + render + send. Returns (ok, detail)."""

    log.info("Sprint summary: Starting pipeline...")

    # 1. Fetch Jira data
    log.info("Sprint summary: Fetching Jira sprint data...")
    sprint_data = _get_sprint_data()
    log.info(f"Sprint summary: Sprint {sprint_data['this_sprint_num']} — "
             f"{sprint_data['shipped']} shipped, {sprint_data['in_progress']} in progress, {sprint_data['todo']} to do")

    # 2. Fetch DB metrics
    log.info("Sprint summary: Fetching DB metrics...")
    db_metrics = get_lives_insured_metrics()
    if db_metrics:
        log.info(f"Sprint summary: Lives Insured = {db_metrics['lives_today']:,}")
    else:
        log.warning("Sprint summary: DB metrics unavailable — using placeholders")

    # 3. Claude structures the brain-dump
    log.info("Sprint summary: Structuring brain-dump with Claude...")
    structured = _structure_braindump(braindump_text, sprint_data)
    if not structured:
        return False, "Claude failed to structure the brain-dump"
    log.info(f"Sprint summary: Structured — {len(structured.get('features', []))} features, "
             f"{len(structured.get('next_week_deliverables', []))} deliverables")

    # 4. Render HTML
    log.info("Sprint summary: Rendering HTML...")
    html = _render_html(structured, sprint_data, db_metrics)
    log.info(f"Sprint summary: HTML rendered ({len(html):,} bytes)")

    # 5. Send email
    sn = sprint_data["this_sprint_num"]
    now = datetime.now(SYDNEY_TZ)
    subject = f"\U0001f680 AXIS CRM Sprint {sn} — Weekly Report — {now.strftime('%-d %b %Y')}"

    log.info(f"Sprint summary: Sending email...")
    ok, detail = _send_email(subject, html)
    if ok:
        log.info(f"Sprint summary: {detail}")
        try:
            from metrics_client import post_metric
            post_metric("sprint_summary", items_processed=1)
        except Exception as e:
            log.warning(f"Sprint summary: Metric post failed: {e}")
    else:
        log.error(f"Sprint summary: Send failed — {detail}")
        try:
            from metrics_client import post_metric
            post_metric("sprint_summary", success=False)
        except Exception as e:
            log.warning(f"Sprint summary: Metric post failed: {e}")

    return ok, detail


def process_sprint_summary_command(chat_id, bot, braindump_text):
    """Telegram /sprint_summary handler."""
    try:
        if not braindump_text or len(braindump_text.strip()) < 20:
            bot.send_message(
                chat_id,
                "📝 Please include your brain-dump after the command.\n\n"
                "Example:\n`/sprint_summary Browser extension broadened to Zurich, TAL. "
                "First data integration with NEOS complete. Security hardening done. "
                "Next week: one-click portal access, broader extension coverage...`",
                parse_mode="Markdown",
            )
            return

        bot.send_message(chat_id, "🚀 Building sprint summary...\n\n"
                                   "Fetching Jira + DB data, structuring with Claude, rendering HTML...")

        ok, detail = build_and_send_summary(braindump_text)

        if ok:
            bot.send_message(chat_id, f"✅ Sprint summary sent to james@axiscrm.com.au\n{detail}")
        else:
            bot.send_message(chat_id, f"❌ Sprint summary failed: {detail}")

    except Exception as e:
        log.error(f"/sprint_summary error: {e}", exc_info=True)
        bot.send_message(chat_id, f"❌ Error: {e}")
