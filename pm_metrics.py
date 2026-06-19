"""
PM Agent — PRD Product Performance Metrics

Extracts the "Product Performance Metrics" table from a PRD (Confluence page)
and pushes the metrics to the Product Central dashboard, where they appear as
rows on the Initiative Metrics / Automation Metrics screens.

Flow: at PRD→Epic time (pm4_epic.approve_epic), call sync_prd_metrics(...).
The PRD's success metrics — tagged Initiative or Automation by the product
owner — land on the matching screen automatically, so they don't have to be
entered by hand.
"""

import requests
from datetime import datetime
import pytz

from config import ROADMAP_API_BASE, ROADMAP_API_KEY, log
from confluence_client import fetch_page_adf, adf_to_text

METRIC_ROWS_URL = f"{ROADMAP_API_BASE}/api/metric-rows"
METRICS_HEADING = "product performance metrics"

# Placeholder cell values that mean "empty"
_BLANK = {"", "—", "-", "–", "n/a", "na", "none", "tbd"}


def _cell_text(cell):
    """Plain text of an ADF table cell, trimmed."""
    return adf_to_text(cell).strip()


def _clean(v):
    """Normalise a cell value; placeholders become ''."""
    s = (v or "").strip()
    return "" if s.lower() in _BLANK else s


def _normalise_screen(v):
    """Map a Screen cell to the dashboard's 'ini' / 'auto', or None if not a metric."""
    s = (v or "").strip().lower()
    if s.startswith("init"):
        return "ini"
    if s.startswith("auto"):
        return "auto"
    return None


def _find_metrics_table(adf):
    """Return the first table node that follows the metrics heading, or None."""
    if not isinstance(adf, dict):
        return None
    blocks = adf.get("content", []) or []
    seen_heading = False
    for node in blocks:
        ntype = node.get("type")
        if ntype == "heading":
            heading_text = adf_to_text(node).strip().lower()
            if METRICS_HEADING in heading_text:
                seen_heading = True
                continue
            # A different heading ends the metrics section
            if seen_heading:
                return None
        elif ntype == "table" and seen_heading:
            return node
    return None


def parse_metrics_from_adf(adf):
    """Parse the Product Performance Metrics table into a list of metric dicts.

    Returns [{screen, name, lever, type, target, note}, ...] (screen is 'ini'/'auto').
    """
    table = _find_metrics_table(adf)
    if not table:
        return []

    rows = [r for r in (table.get("content", []) or []) if r.get("type") == "tableRow"]
    if len(rows) < 2:
        return []

    def cells(row):
        return [c for c in (row.get("content", []) or [])
                if c.get("type") in ("tableHeader", "tableCell")]

    header = [_cell_text(c).lower() for c in cells(rows[0])]

    def col(name):
        for i, h in enumerate(header):
            if name in h:
                return i
        return None

    idx = {k: col(k) for k in ("screen", "metric", "lever", "type", "target", "note")}

    metrics = []
    for row in rows[1:]:
        cs = cells(row)
        get = lambda key: _cell_text(cs[idx[key]]) if idx.get(key) is not None and idx[key] < len(cs) else ""
        screen = _normalise_screen(get("screen"))
        name = _clean(get("metric"))
        if not screen or not name:
            continue
        metrics.append({
            "screen": screen,
            "name": name,
            "lever": _clean(get("lever")),
            "type": _clean(get("type")) or "#",
            "target": _clean(get("target")),
            "note": _clean(get("note")),
        })
    return metrics


def build_groups(metrics, feature_name, owner="", platform="CRM Platform"):
    """Group metrics by screen into the payload the dashboard expects.

    One group per screen, with the feature/epic name as the parent row and each
    metric as a sub-row.
    """
    shipped = datetime.now(pytz.timezone("Australia/Sydney")).strftime("%Y-%m-%d")
    by_screen = {}
    for m in metrics:
        by_screen.setdefault(m["screen"], []).append({
            "name": m["name"],
            "lever": m["lever"],
            "type": m["type"],
            "target": m["target"],
            "note": m["note"],
        })
    groups = []
    for screen in ("ini", "auto"):
        if screen in by_screen:
            groups.append({
                "screen": screen,
                "name": feature_name,
                "owner": owner,
                "platform": platform,
                "shipped": shipped,
                "metrics": by_screen[screen],
            })
    return groups


def push_metric_rows(src, groups):
    """POST grouped metric rows to the dashboard. Returns True on success."""
    try:
        resp = requests.post(
            METRIC_ROWS_URL,
            json={"src": src, "groups": groups},
            headers={"Content-Type": "application/json", "x-api-key": ROADMAP_API_KEY},
            timeout=10,
        )
        if resp.status_code == 200:
            return True
        log.warning(f"Metric rows: POST failed — {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        log.warning(f"Metric rows: POST error — {e}")
    return False


def sync_prd_metrics(prd_page_id, epic_key, feature_name, owner="", platform="CRM Platform"):
    """Extract metrics from a PRD page and push them to the dashboard.

    Keyed by epic_key so a re-run overwrites rather than duplicating. Returns the
    number of metrics pushed (0 if none / on failure). Never raises.
    """
    try:
        adf = fetch_page_adf(prd_page_id)
        if not adf:
            return 0
        metrics = parse_metrics_from_adf(adf)
        if not metrics:
            log.info(f"Metric rows: no dashboard metrics found in PRD {prd_page_id}")
            return 0
        groups = build_groups(metrics, feature_name, owner=owner, platform=platform)
        if push_metric_rows(epic_key, groups):
            ini = sum(len(g["metrics"]) for g in groups if g["screen"] == "ini")
            auto = sum(len(g["metrics"]) for g in groups if g["screen"] == "auto")
            log.info(f"Metric rows: pushed {len(metrics)} metric(s) for {epic_key} "
                     f"({ini} initiative, {auto} automation)")
            return len(metrics)
    except Exception as e:
        log.warning(f"Metric rows: sync error for {epic_key} — {e}")
    return 0
