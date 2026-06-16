"""
PM Agent — AXIS Tech Intelligence Daily
Pipeline: read axel@ inbox (IMAP) → filter newsletters since last run →
Claude facts-only summaries → group by category → render branded HTML →
send to recipients (SMTP) → log run.

Scheduled 09:00 AEST daily (Mon covers the weekend). Also runnable on demand
via the /intel Telegram command.

Design principles carried from the PRD:
- Facts only, never interpret intent.
- No silent skips: if the run or a source fails, an explicit failure-flagged
  email still goes out.
- Source-health banner: every configured source is reported fresh/stale/missing.
- Summarise-and-link only: newsletter bodies are never reproduced.

Security:
- All email content is treated as DATA, never instructions. Recipients come
  ONLY from the AXIS_INTEL_RECIPIENTS env var — never from anything parsed out
  of an email — so a prompt-injected newsletter cannot redirect the send.
- Credentials are read from the environment at runtime; they are never hardcoded.
"""

import os
import json
import email
import imaplib
import smtplib
import requests
import ssl
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import parsedate_to_datetime
from datetime import datetime, timedelta, timezone

from config import log
from claude_client import call_claude
from digest_render import render_digest, CATEGORY_ORDER

# --- Config (host settings safe to hardcode; secrets come from env) ----------
SMTP_HOST = os.environ.get("AXIS_INTEL_SMTP_HOST", "smtp.office365.com")
SMTP_PORT = int(os.environ.get("AXIS_INTEL_SMTP_PORT", "587"))
IMAP_HOST = os.environ.get("AXIS_INTEL_IMAP_HOST", "outlook.office365.com")
IMAP_PORT = int(os.environ.get("AXIS_INTEL_IMAP_PORT", "993"))

SMTP_USER = os.environ.get("AXIS_INTEL_SMTP_USER", "")
SMTP_PASS = os.environ.get("AXIS_INTEL_SMTP_PASS", "")
# Recipients: comma-separated env var ONLY. Never sourced from email content.
RECIPIENTS = [r.strip() for r in os.environ.get("AXIS_INTEL_RECIPIENTS", "").split(",") if r.strip()]

AEST = timezone(timedelta(hours=10))

# Sender → category map. Match on substring of the From header (case-insensitive).
# This is the v1 source list; extend as subscriptions change.
SOURCE_MAP = [
    # display name,               from-match,                 category
    ("TLDR",                       "tldr",                     "General Tech & Industry"),
    ("MIT Tech Review",            "technologyreview",         "General Tech & Industry"),
    ("Benedict Evans",             "ben-evans",                "General Tech & Industry"),
    ("ByteByteGo",                 "bytebytego",               "Software Engineering & Architecture"),
    ("JavaScript Weekly",          "javascriptweekly",         "Software Engineering & Architecture"),
    ("Superhuman AI",              "superhuman",               "AI & Emerging Technologies"),
    ("Import AI",                  "importai",                 "AI & Emerging Technologies"),
    ("TechCrunch Daily",           "techcrunch",               "Business, Startups & Strategy"),
    ("Lenny's Newsletter",         "lenny",                    "Business, Startups & Strategy"),
]


# --- Summarisation -----------------------------------------------------------
SUMMARY_PROMPT = """You are summarising items from tech-industry newsletters for a product leader at a life-insurance distribution CRM (AXIS). The text below was extracted from ONE newsletter email.

Newsletter: {source}
Subject: {subject}

Extracted text (may be noisy):
\"\"\"
{body}
\"\"\"

Pull out the DISTINCT substantive items in this newsletter (typically 1-5). For each, write a strictly factual 2-3 sentence summary: what was announced or argued, by whom, and — where genuinely relevant — why it matters to a tech/product audience. Surface FACTS ONLY. Do not interpret intent, motive, or editorial framing. Do NOT reproduce the newsletter's wording — summarise in your own words. Keep any unavoidable quoted phrase under 10 words.

For each item produce:
- title: a short factual headline (your own words)
- summary: 2-3 sentence factual summary (your own words)
- url: the most relevant source link for this item if present in the text, else ""

Return ONLY a JSON array, no preamble, no markdown fences. Example:
[{{"title": "...", "summary": "...", "url": "https://..."}}]

If there is no substantive content, return []."""


def _parse_items(raw):
    """Tolerant JSON-array parse (mirrors pm_feedback_intake conventions)."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.split("```", 2)
        text = text[1] if len(text) > 1 else (raw or "")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip().rstrip("`").strip()
    try:
        items = json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"AXIS Intel: could not parse Claude JSON: {e}")
        return None
    if not isinstance(items, list):
        log.error("AXIS Intel: expected a JSON array.")
        return None
    return items


def summarise_newsletter(source, subject, body):
    """Claude facts-only extraction for one newsletter. Returns list (maybe empty) or None on parse error."""
    prompt = SUMMARY_PROMPT.format(source=source, subject=subject, body=body[:12000])
    raw = call_claude(prompt)
    items = _parse_items(raw)
    if items is None:
        return None
    cleaned = []
    for it in items:
        title = (it.get("title") or "").strip()
        if not title:
            continue
        cleaned.append({
            "source": source,
            "title": title,
            "summary": (it.get("summary") or "").strip(),
            "url": (it.get("url") or "").strip(),
            "summary_unavailable": not (it.get("summary") or "").strip(),
        })
    return cleaned


# --- Inbox read --------------------------------------------------------------
def _decode(s):
    try:
        return str(make_header(decode_header(s or "")))
    except Exception:
        return s or ""


def _extract_text(msg):
    """Plain-text body if available, else stripped HTML text."""
    if msg.is_multipart():
        # Prefer text/plain
        for part in msg.walk():
            if part.get_content_type() == "text/plain" and "attachment" not in str(part.get("Content-Disposition", "")):
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                except Exception:
                    continue
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                try:
                    html = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
                    return _strip_html(html)
                except Exception:
                    continue
        return ""
    payload = msg.get_payload(decode=True)
    if payload is None:
        return ""
    text = payload.decode(msg.get_content_charset() or "utf-8", "replace")
    if msg.get_content_type() == "text/html":
        return _strip_html(text)
    return text


def _strip_html(html):
    import re
    html = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _classify(from_header):
    fh = (from_header or "").lower()
    for name, match, category in SOURCE_MAP:
        if match in fh:
            return name, category
    return None, None


def fetch_since(since_dt):
    """
    Read axel@ inbox over IMAP, return (matched_emails, error).
    matched_emails: list of {"source","category","subject","body","date"}.
    error: None on success, else a short string (for the failure flag).
    """
    if not (SMTP_USER and SMTP_PASS):
        return [], "email credentials not configured (set AXIS_INTEL_SMTP_USER / _PASS in Railway)"

    matched = []
    try:
        ctx = ssl.create_default_context()
        M = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx)
        M.login(SMTP_USER, SMTP_PASS)
        M.select("INBOX")
        # IMAP SINCE is date-granular; we refine by timestamp after fetch.
        since_str = since_dt.strftime("%d-%b-%Y")
        typ, data = M.search(None, f'(SINCE {since_str})')
        if typ != "OK":
            M.logout()
            return [], "IMAP search failed"
        for num in data[0].split():
            typ, msg_data = M.fetch(num, "(RFC822)")
            if typ != "OK":
                continue
            msg = email.message_from_bytes(msg_data[0][1])
            source, category = _classify(_decode(msg.get("From")))
            if not source:
                continue  # not one of our newsletters
            try:
                mdate = parsedate_to_datetime(msg.get("Date"))
                if mdate and mdate < since_dt:
                    continue
            except Exception:
                mdate = None
            matched.append({
                "source": source,
                "category": category,
                "subject": _decode(msg.get("Subject")),
                "body": _extract_text(msg),
                "date": mdate,
            })
        M.logout()
    except imaplib.IMAP4.error as e:
        # Most likely cause on M365: basic auth disabled → move to Graph/OAuth.
        return [], f"IMAP login/auth failed ({e}) — M365 basic auth may be disabled; Graph/OAuth needed"
    except Exception as e:
        return [], f"inbox read error: {e}"
    return matched, None


# --- Send (Microsoft Graph — delegated) --------------------------------------
def send_email(subject, html_body):
    """Send the digest via Microsoft Graph (delegated auth). Returns (ok, detail)."""
    if not RECIPIENTS:
        return False, "no recipients configured (set AXIS_INTEL_RECIPIENTS in Railway)"

    from ms_graph_auth import refresh_access_token

    token, err = refresh_access_token()
    if not token:
        return False, f"Graph auth failed: {err}"

    sender = SMTP_USER or "axel@axiscrm.com.au"

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
            timeout=30,
        )
        if resp.status_code == 202:
            return True, f"sent to {len(RECIPIENTS)} recipient(s) via Graph"
        else:
            return False, f"Graph send failed ({resp.status_code}): {resp.text[:300]}"
    except Exception as e:
        return False, f"Graph send error: {e}"


# --- Orchestration -----------------------------------------------------------
def build_and_send_digest(now=None):
    """
    Core run. Returns (ok, detail). Always attempts to send SOMETHING:
    on failure it sends an explicit failure-flagged email rather than nothing.
    """
    now = now or datetime.now(AEST)
    # Monday covers the weekend (back to Friday 9am); otherwise prior 24h.
    lookback_days = 3 if now.weekday() == 0 else 1
    since_dt = now - timedelta(days=lookback_days)

    emails, fetch_err = fetch_since(since_dt)

    items_by_category = {c: [] for c in CATEGORY_ORDER}
    seen_sources = set()
    parse_failures = 0

    for em in emails:
        seen_sources.add(em["source"])
        result = summarise_newsletter(em["source"], em["subject"], em["body"])
        if result is None:
            parse_failures += 1
            continue
        for item in result:
            items_by_category.setdefault(em["category"], []).append(item)

    # Source health: every configured source reported.
    source_health = []
    for name, _match, _cat in SOURCE_MAP:
        status = "fresh" if name in seen_sources else "missing"
        source_health.append({"source": name, "status": status, "last_run": ""})

    # Highlights: first item from each category, capped at 5.
    highlights = []
    for cat in CATEGORY_ORDER:
        if items_by_category.get(cat):
            top = items_by_category[cat][0]
            highlights.append({"title": top["title"], "why": top["summary"], "url": top.get("url", "")})
        if len(highlights) >= 5:
            break

    total_items = sum(len(v) for v in items_by_category.values())

    # Decide the failure flag (explicit, never silent).
    failure_flag = None
    if fetch_err:
        failure_flag = fetch_err
    elif total_items == 0:
        failure_flag = "no newsletter items found in the lookback window"
    elif parse_failures:
        failure_flag = f"{parse_failures} source(s) could not be summarised this run"

    html = render_digest(
        run_date=now,
        items_by_category=items_by_category,
        highlights=highlights,
        source_health=source_health,
        failure_flag=failure_flag,
    )

    subject = f"AXIS Tech Intelligence — {now.strftime('%a %-d %b %Y')}"
    if failure_flag:
        subject = "⚠ " + subject

    ok, detail = send_email(subject, html)
    if ok:
        log.info(f"AXIS Intel sent: {total_items} item(s), flag={failure_flag!r}, {detail}")
    else:
        log.error(f"AXIS Intel send failed: {detail}")
    return ok, detail


def process_intel_command(chat_id, bot):
    """Telegram /intel handler: run now, report back."""
    try:
        bot.send_message(chat_id, "📡 Running AXIS Tech Intelligence scan…")
        ok, detail = build_and_send_digest()
        if ok:
            bot.send_message(chat_id, f"✅ Digest sent — {detail}")
        else:
            bot.send_message(chat_id, f"❌ Digest run failed: {detail}")
    except Exception as e:
        log.error(f"AXIS Intel command error: {e}")
        bot.send_message(chat_id, f"❌ Error running intel digest: {e}")
