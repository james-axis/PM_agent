"""
AXIS Intel Daily — email HTML renderer.

Renders the daily tech-intelligence digest in the AXIS brand layout
(charcoal header band, source-health strip, white content body with
category sections), matching the Sprint 33 summary email styling.

Pure rendering: takes structured data, returns an HTML string. No network,
no credentials, no side effects — safe to unit-test and preview.
"""

from datetime import datetime

from digest_assets import HEADER_BANNER_B64, FOOTER_LOGO_B64

# --- Brand tokens (from AXIS guidelines + Sprint 33 email) -------------------
CHARCOAL = "rgb(31, 39, 49)"
SLATE = "rgb(59, 72, 91)"
ORANGE = "rgb(211, 65, 8)"
GREEN = "rgb(22, 163, 74)"
AMBER = "rgb(201, 145, 14)"
RED = "rgb(190, 60, 60)"
LIGHT_RULE = "rgb(190, 198, 208)"
MUTED = "rgb(200, 207, 216)"
BLACK = "rgb(0, 0, 0)"
LIGHT_BG = "rgb(245, 245, 245)"

FONT_HEAD = "Metrophobic,Inter,Arial,sans-serif"
FONT_BODY = "Inter,Arial,sans-serif"

# Source category display order
CATEGORY_ORDER = [
    "General Tech & Industry",
    "Software Engineering & Architecture",
    "AI & Emerging Technologies",
    "Business, Startups & Strategy",
]

# Health → pill colour
HEALTH_COLOUR = {"fresh": GREEN, "stale": AMBER, "failed": RED, "missing": RED}
HEALTH_LABEL = {"fresh": "FRESH", "stale": "STALE", "failed": "FAILED", "missing": "NO DATA"}


def _pill(label, bg):
    return (
        f'<span style="font-family:{FONT_BODY}; font-size:9.5px; font-weight:700; '
        f'letter-spacing:0.5px; text-transform:uppercase; color:rgb(255,255,255); '
        f'background-color:{bg};">&nbsp;{label}&nbsp;</span>'
    )


def _section_label(text):
    return (
        f'<div style="text-transform:uppercase; letter-spacing:1.5px; '
        f'font-family:{FONT_BODY}; font-size:12px; font-weight:800; '
        f'color:{ORANGE}; margin:0 0 6px;">{text}</div>'
    )


def _section_heading(text):
    return (
        f'<div style="line-height:1.15; margin-bottom:14px; '
        f'font-family:{FONT_HEAD}; font-size:30px; color:{CHARCOAL};">{text}</div>'
    )


def _item_row(item):
    """A single newsletter item: ▸ <b>title</b> — summary  [Read ▸]"""
    link = item.get("url", "")
    title = item.get("title", "Untitled")
    summary = item.get("summary", "")
    source = item.get("source", "")
    unavailable = item.get("summary_unavailable", False)

    src_tag = (
        f'<span style="font-family:{FONT_BODY}; font-size:10px; font-weight:700; '
        f'letter-spacing:0.5px; text-transform:uppercase; color:{ORANGE};">{source}</span>'
        if source else ""
    )

    if unavailable:
        body = (
            f'<span style="color:{SLATE}; font-style:italic;"> — summary unavailable; '
            f'open the source for the full item</span>'
        )
    else:
        body = f'<span style="color:{SLATE};"> — {summary}</span>'

    read = (
        f'&nbsp;<a href="{link}" target="_blank" '
        f'style="color:{ORANGE}; text-decoration:none; font-weight:700; '
        f'white-space:nowrap;">Read&nbsp;▸</a>'
        if link else ""
    )

    return (
        f'<tr><td style="padding:6px 0; font-family:{FONT_BODY}; font-size:14px; '
        f'color:{CHARCOAL}; line-height:1.5;">'
        f'<span style="color:{ORANGE};">▸</span> {src_tag} <b>{title}</b>{body}{read}'
        f'</td></tr>'
    )


def _highlight_row(item):
    title = item.get("title", "")
    why = item.get("why", item.get("summary", ""))
    link = item.get("url", "")
    read = (
        f' <a href="{link}" target="_blank" style="color:{ORANGE}; '
        f'text-decoration:none; font-weight:700; white-space:nowrap;">Read&nbsp;▸</a>'
        if link else ""
    )
    return (
        f'<tr><td style="padding:5px 0; font-family:{FONT_BODY}; font-size:14px; '
        f'color:{CHARCOAL}; line-height:1.5;">'
        f'<span style="color:{ORANGE};">▸</span> <b>{title}</b>'
        f'<span style="color:{SLATE};"> — {why}</span>{read}</td></tr>'
    )


def render_digest(*, run_date, items_by_category, highlights, source_health,
                  failure_flag=None):
    """
    run_date: datetime
    items_by_category: {category_name: [item, ...]}
    highlights: [item, ...]  (top cross-category)
    source_health: [{"source": str, "status": "fresh|stale|failed|missing",
                     "last_run": str}]
    failure_flag: optional str — if set, a red banner is shown.
    """
    date_str = run_date.strftime("%A %-d %B %Y")
    weekday = run_date.strftime("%A")
    coverage_note = "covering the weekend" if weekday == "Monday" else "since yesterday"

    fresh = sum(1 for s in source_health if s["status"] == "fresh")
    total = len(source_health)

    # --- Failure banner (explicit, never silent) ---
    failure_html = ""
    if failure_flag:
        failure_html = (
            f'<tr><td style="padding:14px 32px; background-color:{RED};">'
            f'<div style="font-family:{FONT_BODY}; font-size:13px; font-weight:700; '
            f'color:rgb(255,255,255); line-height:1.4;">⚠ RUN FLAG — {failure_flag}</div>'
            f'</td></tr>'
        )

    # --- Source-health strip ---
    chips = []
    for s in source_health:
        c = HEALTH_COLOUR.get(s["status"], RED)
        chips.append(
            f'<span style="display:inline-block; font-family:{FONT_BODY}; '
            f'font-size:10px; color:{MUTED}; margin:0 10px 4px 0; white-space:nowrap;">'
            f'<span style="color:{c};">●</span>&nbsp;{s["source"]}</span>'
        )
    health_strip = (
        f'<tr><td style="padding:10px 32px 12px; background-color:{BLACK};">'
        f'<div style="font-family:{FONT_BODY}; font-size:9.5px; letter-spacing:1px; '
        f'text-transform:uppercase; color:{MUTED}; margin-bottom:6px;">'
        f'Source health &nbsp;·&nbsp; {fresh}/{total} fresh</div>'
        f'<div>{"".join(chips)}</div></td></tr>'
    )

    # --- Highlights block (light card with orange left border) ---
    highlight_rows = "".join(_highlight_row(h) for h in highlights) if highlights else (
        f'<tr><td style="font-family:{FONT_BODY}; font-size:13px; color:{SLATE}; '
        f'font-style:italic;">No standout items today.</td></tr>'
    )
    highlights_html = (
        f'<tr><td style="padding:24px 32px 4px;">'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'border="0" style="background-color:{LIGHT_BG}; '
        f'border-left:4px solid {ORANGE};"><tr><td style="padding:18px 22px;">'
        f'<div style="text-transform:uppercase; letter-spacing:1.5px; '
        f'font-family:{FONT_BODY}; font-size:12px; font-weight:800; color:{ORANGE}; '
        f'margin:0 0 10px;">Top of the brief</div>'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'border="0">{highlight_rows}</table>'
        f'</td></tr></table></td></tr>'
    )

    # --- Category sections ---
    section_html = ""
    for cat in CATEGORY_ORDER:
        rows = items_by_category.get(cat, [])
        if not rows:
            continue
        item_rows = "".join(_item_row(i) for i in rows)
        section_html += (
            f'<tr><td style="padding-top:28px; padding-right:32px; padding-left:32px;">'
            f'{_section_heading(cat)}'
            f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
            f'border="0">{item_rows}</table></td></tr>'
        )

    # --- Header band (real AXIS banner image, as per Sprint 33 email) ---
    header_html = (
        f'<tr><td style="padding:0; font-size:0; line-height:0; '
        f'background-color:{CHARCOAL};">'
        f'<img src="data:image/png;base64,{HEADER_BANNER_B64}" '
        f'alt="AXIS Product &amp; Engineering" width="640" '
        f'style="width:100%; max-width:640px; height:auto; display:block; '
        f'border:0; outline:none;"></td></tr>'
    )

    # --- Intro line ---
    intro_html = (
        f'<tr><td style="padding:24px 32px 0;">'
        f'<div style="font-family:{FONT_HEAD}; font-size:30px; color:{CHARCOAL}; '
        f'line-height:1.15; margin-bottom:6px;">Today\'s Brief</div>'
        f'<div style="font-family:{FONT_BODY}; font-size:13px; color:{SLATE};">'
        f'{date_str} &nbsp;·&nbsp; {coverage_note} &nbsp;·&nbsp; '
        f'<span style="color:{ORANGE}; font-weight:700; text-transform:uppercase; '
        f'letter-spacing:1px;">Facts only — links to every source</span></div></td></tr>'
    )

    # --- Footer (matches Sprint 33: disclaimer, then light-gray logo strip) ---
    footer_html = (
        f'<tr><td style="padding:22px 32px 4px; background-color:rgb(255,255,255);">'
        f'<div style="font-family:{FONT_BODY}; font-size:10.5px; color:{SLATE}; '
        f'line-height:1.5;">Generated automatically by PM_agent at 9:00 AM AEST. '
        f'Summaries are AI-generated from subscribed newsletters and link to the '
        f'original source &mdash; facts only, no interpretation. '
        f'Source content remains &copy; its publishers.</div></td></tr>'
        f'<tr><td style="border-top:1px solid rgb(232,232,232); '
        f'background-color:rgb(245,245,245); padding:16px 32px;">'
        f'<img src="data:image/png;base64,{FOOTER_LOGO_B64}" alt="AXIS" height="16" '
        f'style="height:16px; width:auto; vertical-align:middle; border:0; '
        f'display:inline-block;">'
        f'<span style="font-family:{FONT_BODY}; font-size:10px; letter-spacing:2px; '
        f'color:{SLATE}; text-transform:uppercase; vertical-align:middle;">'
        f'&nbsp;&nbsp;Product &amp; Engineering &nbsp;·&nbsp; Tech Intelligence Daily'
        f'</span></td></tr>'
    )

    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1"></head>'
        f'<body style="margin:0; padding:0; background-color:rgb(245,245,245);">'
        f'<table role="presentation" width="100%" cellspacing="0" cellpadding="0" '
        f'border="0" style="background-color:rgb(245,245,245);"><tr><td align="center" '
        f'style="padding:24px 12px;">'
        f'<table role="presentation" width="640" cellspacing="0" cellpadding="0" '
        f'border="0" style="width:640px; max-width:640px; background-color:rgb(255,255,255);">'
        f'{header_html}{failure_html}{health_strip}{highlights_html}'
        f'{intro_html}{section_html}{footer_html}'
        f'</table></td></tr></table></body></html>'
    )
