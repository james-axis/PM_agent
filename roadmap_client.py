"""
PM Agent — Custom Product Roadmap API Client
Connects to the Axis Product Roadmap (Railway-hosted) for Triage management.
"""

import requests
from config import ROADMAP_API_BASE, ROADMAP_API_KEY, log


def _headers():
    return {
        "Content-Type": "application/json",
        "x-api-key": ROADMAP_API_KEY,
    }


def add_to_triage(label, sub="", swimlane="", column="triage"):
    """Add a new card to the roadmap.
    column: 'triage' (default) or 'bluesky'.
    Returns (ticket_id, card_id) or (None, None) on failure."""
    try:
        payload = {"label": label[:100], "column": column}
        if swimlane:
            payload["swimlane"] = swimlane
        if sub:
            payload["sub"] = sub[:500]

        resp = requests.post(
            f"{ROADMAP_API_BASE}/api/triage",
            json=payload,
            headers=_headers(),
            timeout=15,
        )
        log.info(f"Roadmap: POST payload={payload}, status={resp.status_code}")

        if resp.status_code == 200:
            data = resp.json()
            ticket_id = data.get("ticketId", "")
            card_id = data.get("id", "")
            log.info(f"Roadmap: Added to {column} — {ticket_id}: {label}")
            return ticket_id, card_id
        else:
            log.error(f"Roadmap: Triage POST failed — {resp.status_code}: {resp.text[:300]}")
            return None, None
    except Exception as e:
        log.error(f"Roadmap: Triage POST error — {e}")
        return None, None


def get_triage_cards():
    """List all current cards in the Triage column.
    Returns list of card dicts or empty list on failure."""
    try:
        resp = requests.get(
            f"{ROADMAP_API_BASE}/api/triage",
            headers=_headers(),
            timeout=15,
        )
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list):
                return data
            return data.get("cards", data.get("items", []))
        else:
            log.error(f"Roadmap: Triage GET failed — {resp.status_code}: {resp.text[:300]}")
            return []
    except Exception as e:
        log.error(f"Roadmap: Triage GET error — {e}")
        return []
