"""
PM Agent — Web Client
Fetches third-party API documentation and web resources for technical context.
"""

import requests
from config import log

# Known API doc URLs for common integrations
KNOWN_API_DOCS = {
    "tal": "https://www.tal.com.au",
    "zurich": "https://www.zurich.com.au",
    "aia": "https://www.aia.com.au",
    "mlc": "https://www.mlclife.com.au",
    "metlife": "https://www.metlife.com.au",
    "resolution life": "https://www.resolutionlife.com.au",
    "integrity life": "https://www.integritylife.com.au",
    "xplan": "https://www.iress.com/software/xplan/",
    "stripe": "https://docs.stripe.com/api",
    "twilio": "https://www.twilio.com/docs/usage/api",
    "sendgrid": "https://docs.sendgrid.com/api-reference",
    "aws": "https://docs.aws.amazon.com",
}


def fetch_web_content(url, max_chars=15000):
    """
    Fetch text content from a URL. Returns cleaned text or None.
    """
    try:
        r = requests.get(url, timeout=15, headers={
            "User-Agent": "AxisCRM-PMAgent/1.0",
            "Accept": "text/html,text/plain",
        })
        if r.status_code != 200:
            log.warning(f"Web fetch failed for {url}: {r.status_code}")
            return None

        text = r.text
        # Strip HTML tags for rough text extraction
        import re
        text = re.sub(r'<script[^>]*>.*?</script>', '', text, flags=re.DOTALL)
        text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
        text = re.sub(r'<[^>]+>', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()

        if len(text) > max_chars:
            text = text[:max_chars] + "..."

        return text
    except Exception as e:
        log.error(f"Web fetch error for {url}: {e}")
        return None


def identify_integrations(task_text):
    """
    Scan task text for known third-party integration references.
    Returns list of {name, url} dicts.
    """
    matches = []
    text_lower = task_text.lower()
    for name, url in KNOWN_API_DOCS.items():
        if name in text_lower:
            matches.append({"name": name, "url": url})
    return matches
