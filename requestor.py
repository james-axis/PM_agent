"""
PM Agent — requestor first-name extraction

The person who raised a ticket is named in its description, e.g.
"… — Submitted via the in-app feedback form by Rebel Servante (Rebel@slifegroup.com.au)".
This pulls their first name so it can be added as a Jira label (Rebel, Nathaniel …)
to filter tickets by who raised them.
"""

import re

_NAME = r"([A-Z][A-Za-z’'\-]+)"
_PATTERNS = [
    rf"feedback form by\s+{_NAME}",          # "…in-app feedback form by Rebel …"
    rf"\b(?:submitted|reported|raised|requested)\s+by\s+{_NAME}",
    rf"\bby\s+{_NAME}\s*\(",                  # "by Rebel Servante (email)"
]


def extract_first_name(description_text):
    """Return the requestor's first name, or None."""
    if not description_text:
        return None
    for pat in _PATTERNS:
        m = re.search(pat, description_text)
        if m:
            return m.group(1)
    # Fallback: local part of the first email address → first name
    m = re.search(r"([A-Za-z0-9._%+\-]+)@", description_text)
    if m:
        local = re.split(r"[._\-]", m.group(1))[0]
        if local:
            return local[:1].upper() + local[1:]
    return None
