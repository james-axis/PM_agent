"""
PM Agent — Metrics Client
POSTs automation run data to Product Central's /api/metrics endpoint.
"""

import requests
from datetime import datetime
import pytz

from config import ROADMAP_API_KEY, log

METRICS_URL = "https://productcentral.up.railway.app/api/metrics"


def post_metric(job, items_processed=1, success=True, run_duration_secs=None):
    """POST a metric record after an automation run.
    
    Args:
        job: one of sprint_start, sprint_close, sprint_retro, sprint_runway,
             board_refiner, prd_to_epic, epic_to_tasks, retro_slack
        items_processed: count of items handled (1 for single-item jobs)
        success: False for failed runs
        run_duration_secs: optional, logged but not used in calculations
    """
    sydney_tz = pytz.timezone("Australia/Sydney")
    now = datetime.now(sydney_tz)

    payload = {
        "job": job,
        "timestamp": now.isoformat(),
    }

    if success:
        payload["items_processed"] = items_processed
    else:
        payload["success"] = False

    if run_duration_secs is not None:
        payload["run_duration_secs"] = round(run_duration_secs, 2)

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
            data = resp.json()
            initiative = data.get("initiative", job)
            log.info(f"Metrics: Posted {job} ({items_processed} items) → {initiative}")
        else:
            log.warning(f"Metrics: POST failed — {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Metrics: POST error — {e}")
