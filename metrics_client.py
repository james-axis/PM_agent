"""
PM Agent — Metrics Client
POSTs automation run data to Product Central's /api/metrics endpoint.
Job keys are assigned by the dashboard (A### format).
"""

import requests
from datetime import datetime
import pytz

from config import ROADMAP_API_KEY, log

METRICS_URL = "https://productcentral.up.railway.app/api/metrics"

# ── Job key mapping (assigned by Product Central dashboard) ───────────────────
JOB_KEYS = {
    "sprint_start":     "A102",
    "sprint_close":     "A103",
    "sprint_retro":     "A104",
    "sprint_planning":  "A105",
    "sprint_runway":    "A106",
    "board_refiner":    "A107",
    "prd_to_epic":      "A108",
    "epic_to_tasks":    "A109",
    "retro_slack":      "A110",
    "sprint_summary":   "A111",
    "planning_slack":   "A112",
}


def post_metric(job, items_processed=1, success=True, **_kwargs):
    """POST a metric record after an automation run.

    Args:
        job: descriptive name (looked up in JOB_KEYS) or direct A### key
        items_processed: count of items handled (1 for single-item jobs)
        success: False for failed runs
        **_kwargs: absorbs any extra args (e.g. legacy run_duration_secs) silently
    """
    # Resolve to A### key
    key = JOB_KEYS.get(job, job)

    sydney_tz = pytz.timezone("Australia/Sydney")
    now = datetime.now(sydney_tz)

    payload = {
        "job": key,
        "timestamp": now.isoformat(),
    }

    if success:
        payload["items_processed"] = items_processed
    else:
        payload["success"] = False

    try:
        resp = requests.post(
            METRICS_URL,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "x-api-key": ROADMAP_API_KEY,
            },
            timeout=10,
        )
        if resp.status_code == 200:
            log.info(f"Metrics: Posted {key} ({items_processed} items)")
        else:
            log.warning(f"Metrics: POST failed — {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Metrics: POST error — {e}")
