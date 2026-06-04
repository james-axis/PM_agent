"""
PM Agent — Feedback Intake
Pipeline: transcript (text or voice) → Claude extraction → Insights Hub POST.

Claude extracts an array of distinct feedback items from a single conversation/
recording. Each item carries customer_name, verbatim, summary, sentiment, themes.
The items are POSTed as an array in a single call to the Insights Hub
(/api/feedback). If Claude-derived fields are present, the Hub uses them as-is;
if omitted it runs its own analysis as fallback.
"""

import json
import requests

from config import INSIGHTS_HUB_URL, INSIGHTS_HUB_TOKEN, log
from claude_client import call_claude


EXTRACTION_PROMPT = """You are extracting structured customer feedback from a transcript of a conversation or voice note. The speaker is a product manager at a life insurance distribution CRM, relaying feedback from advisers/customers.

Transcript:
\"\"\"
{transcript}
\"\"\"

Extract every DISTINCT piece of feedback as a separate item. A single transcript may contain multiple unrelated points (e.g. a complaint about compliance UX AND praise for automation) — split these into separate items. If the transcript is a single coherent point, return one item.

For each item produce:
- customer_name: the person the feedback is attributed to, inferred from the speech. If no name is mentioned, use "Unknown".
- verbatim: the feedback as close to the speaker's own words as possible, cleaned of filler.
- summary: one concise sentence summarising the point.
- sentiment: one of "positive", "negative", "neutral", "mixed".
- themes: an array of 1-4 short tags, max 2 words each (e.g. "compliance", "UX", "automation", "quoting", "mobile", "PDF", "onboarding", "notes"). Keep them short and specific — these are filter labels, not descriptions.
- tags: an array of applicable labels from ["CRM", "AI"]. Use "CRM" if the feedback relates to the CRM platform (UI, data, workflows, modules). Use "AI" if it relates to AI/automation features. Use both if applicable. Never leave empty — pick at least one.

Return ONLY a JSON array of objects, no preamble, no markdown fences, no commentary. Example shape:
[{{"customer_name": "Emma Williams", "verbatim": "...", "summary": "...", "sentiment": "negative", "themes": ["compliance", "UX"], "tags": ["CRM"]}}]

If the transcript contains no actionable feedback, return an empty array: []"""


def _parse_items(raw):
    """Parse Claude's response into a list of feedback dicts. Tolerant of fences."""
    text = (raw or "").strip()
    if text.startswith("```"):
        # Strip a leading ```json / ``` fence and trailing ```
        text = text.split("```", 2)
        text = text[1] if len(text) > 1 else (raw or "")
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
        text = text.strip().rstrip("`").strip()
    try:
        items = json.loads(text)
    except json.JSONDecodeError as e:
        log.error(f"Feedback extraction: could not parse Claude JSON: {e}")
        return None
    if not isinstance(items, list):
        log.error("Feedback extraction: expected a JSON array.")
        return None
    return items


def _normalise(item):
    """Ensure each item has the fields the Hub expects, with source set."""
    return {
        "customer_name": item.get("customer_name") or "Unknown",
        "verbatim": item.get("verbatim", "").strip(),
        "summary": item.get("summary", "").strip(),
        "sentiment": item.get("sentiment", "neutral"),
        "themes": item.get("themes", []) if isinstance(item.get("themes"), list) else [],
        "source": "voice_note",
        "tags": item.get("tags", []) if isinstance(item.get("tags"), list) else [],
    }


def extract_feedback(transcript):
    """Run Claude extraction. Returns a list of normalised feedback items, or None on error."""
    prompt = EXTRACTION_PROMPT.format(transcript=transcript)
    raw = call_claude(prompt)
    items = _parse_items(raw)
    if items is None:
        return None
    cleaned = [_normalise(i) for i in items if i.get("verbatim", "").strip()]
    return cleaned


def post_to_hub(items):
    """POST each feedback item to the Insights Hub Telegram webhook.
    Returns (success, detail)."""
    url = f"{INSIGHTS_HUB_URL.rstrip('/')}/api/telegram"
    posted = 0
    errors = []

    for item in items:
        # Build structured message
        lines = []
        if item.get("customer_name") and item["customer_name"] != "Unknown":
            lines.append(f"Customer: {item['customer_name']}")
        lines.append(f"Feedback: {item.get('verbatim', '')}")
        if item.get("tags"):
            platform = ", ".join(item["tags"])
            lines.append(f"Platform: {platform}")
        if item.get("sentiment"):
            lines.append(f"Sentiment: {item['sentiment']}")
        if item.get("themes"):
            lines.append(f"Tags: {', '.join(item['themes'])}")

        message = "\n".join(lines)

        try:
            r = requests.post(
                url,
                headers={
                    "Content-Type": "application/json",
                    "x-insights-token": INSIGHTS_HUB_TOKEN,
                },
                json={"message": message},
                timeout=30,
            )
            if r.status_code in (200, 201):
                posted += 1
            else:
                errors.append(f"HTTP {r.status_code}")
                log.error(f"Insights Hub returned {r.status_code}: {r.text[:300]}")
        except requests.RequestException as e:
            errors.append(str(e))
            log.error(f"Insights Hub POST failed: {e}")

    if posted == len(items):
        log.info(f"Posted {posted} feedback item(s) to Insights Hub.")
        return True, f"{posted} posted"
    elif posted > 0:
        log.warning(f"Posted {posted}/{len(items)} items. Errors: {errors}")
        return True, f"{posted}/{len(items)} posted"
    else:
        return False, "; ".join(errors) if errors else "Unknown error"


def process_feedback(transcript, chat_id, bot, sender_name="Unknown"):
    """Full pipeline: extract → post → confirm back to Telegram."""
    try:
        items = extract_feedback(transcript)
        if items is None:
            bot.send_message(chat_id, "❌ Couldn't parse the feedback. Try rephrasing.")
            return
        if not items:
            bot.send_message(chat_id, "🤔 No actionable feedback found in that. Try again with a clearer point.")
            return

        # Replace "Unknown" customer names with Telegram sender name
        for item in items:
            if item.get("customer_name", "Unknown") == "Unknown":
                item["customer_name"] = sender_name

        ok, detail = post_to_hub(items)
        if not ok:
            bot.send_message(chat_id, f"❌ Extracted {len(items)} item(s) but the Insights Hub rejected them: {detail}")
            return

        # Build confirmation summary
        sentiment_emoji = {"positive": "🟢", "negative": "🔴", "neutral": "⚪", "mixed": "🟡"}
        lines = [f"✅ *{len(items)} feedback item(s) added to the Insights Hub*\n"]
        for i, item in enumerate(items, 1):
            emoji = sentiment_emoji.get(item["sentiment"], "⚪")
            themes = ", ".join(item["themes"]) if item["themes"] else "—"
            platform = ", ".join(item["tags"]) if item.get("tags") else ""
            tag_line = f"{themes} ({platform})" if platform else themes
            lines.append(
                f"{i}. {emoji} *{item['customer_name']}*\n"
                f"   _{item['summary']}_\n"
                f"   Tags: {tag_line}"
            )
        bot.send_message(chat_id, "\n".join(lines), parse_mode="Markdown")

    except Exception as e:
        log.error(f"Feedback processing error: {e}")
        bot.send_message(chat_id, f"❌ Error processing feedback: {e}")
