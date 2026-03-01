"""
PM Agent — Web Client
Fetches third-party API documentation and web resources for technical context.
"""

import requests
from config import log

# Known API doc URLs for common integrations (matched to apps/leadmanager modules)
KNOWN_API_DOCS = {
    # Insurers
    "tal": "https://www.tal.com.au",
    "zurich": "https://www.zurich.com.au",
    "aia": "https://www.aia.com.au",
    "mlc": "https://www.mlclife.com.au",
    "metlife": "https://www.metlife.com.au",
    "resolution life": "https://www.resolutionlife.com.au",
    "integrity life": "https://www.integritylife.com.au",
    # Platform integrations (modules in codebase)
    "xplan": "https://www.iress.com/software/xplan/",
    "docusign": "https://developers.docusign.com/docs/esign-rest-api/",
    "equifax": "https://www.equifax.com.au",
    "experian": "https://www.experian.com.au",
    "illion": "https://www.illion.com.au",
    "iextend": "https://www.iextend.com.au",
    "neos": "https://www.neos.com.au",
    "omnilife": "https://www.omnilife.com.au",
    "noojee": "https://www.noojee.com.au",
    "justcall": "https://justcall.io/docs",
    "levit8": "https://www.levit8.com.au",
    "minit": "https://www.minit.com.au",
    "rapidid": "https://www.rapidid.com.au",
    "pleasesign": "https://pleasesign.com",
    "castor": "https://www.castor.com.au",
    "credfin": "https://www.credfin.com.au",
    # Communications
    "twilio": "https://www.twilio.com/docs/usage/api",
    "sendgrid": "https://docs.sendgrid.com/api-reference",
    # Infrastructure
    "stripe": "https://docs.stripe.com/api",
    "google api": "https://developers.google.com/apis-explorer",
    "segment": "https://segment.com/docs/connections/sources/",
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
