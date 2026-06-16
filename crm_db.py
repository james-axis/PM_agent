"""
PM Agent — CRM Database Client (PostgreSQL)
Runs read-only queries against the Axis CRM database on RDS.
"""

import psycopg2
from config import DB_HOST, DB_PORT, DB_NAME, DB_USER, DB_PASSWORD, log


def _get_connection():
    """Create a PostgreSQL connection to the CRM database."""
    return psycopg2.connect(
        host=DB_HOST,
        port=int(DB_PORT),
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        connect_timeout=15,
    )


def run_query(sql, params=None):
    """Run a read-only SQL query and return rows as list of dicts."""
    if not all([DB_HOST, DB_NAME, DB_USER, DB_PASSWORD]):
        log.warning(
            f"CRM DB: Connection not configured — "
            f"DB_HOST={'set' if DB_HOST else 'MISSING'}, "
            f"DB_PORT={DB_PORT}, "
            f"DB_NAME={'set' if DB_NAME else 'MISSING'}, "
            f"DB_USER={'set' if DB_USER else 'MISSING'}, "
            f"DB_PASSWORD={'set' if DB_PASSWORD else 'MISSING'}"
        )
        return None

    conn = None
    try:
        log.info(f"CRM DB: Connecting to {DB_HOST}:{DB_PORT}/{DB_NAME} as {DB_USER}...")
        conn = _get_connection()
        log.info("CRM DB: Connected OK, executing query...")
        with conn.cursor() as cur:
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            columns = [desc[0] for desc in cur.description]
            rows = cur.fetchall()
            return [dict(zip(columns, row)) for row in rows]
    except Exception as e:
        log.error(f"CRM DB query error ({type(e).__name__}): {e}")
        return None
    finally:
        if conn:
            conn.close()


LIVES_INSURED_SQL = """
WITH params AS (
  SELECT
    CURRENT_DATE        AS snap_today,
    CURRENT_DATE - 7    AS snap_pcp
),
filtered_policies AS (
  SELECT customer_name, date_ongoing_first, date_ongoing_last, amount_ongoing
  FROM applications_policy
  WHERE customer_name IS NOT NULL
    AND TRIM(customer_name) <> ''
    AND LENGTH(TRIM(customer_name)) >= 4
    AND LOWER(customer_name) NOT LIKE '%test%'
    AND LOWER(customer_name) NOT LIKE '%dummy%'
    AND LOWER(customer_name) NOT LIKE '%demo%'
    AND LOWER(customer_name) NOT LIKE '%sample%'
    AND LOWER(customer_name) NOT LIKE '%example%'
    AND LOWER(customer_name) NOT LIKE '%fake%'
    AND LOWER(customer_name) NOT LIKE 'asdf%'
    AND LOWER(customer_name) NOT LIKE '%do not use%'
    AND LOWER(customer_name) NOT LIKE '%donotuse%'
    AND LOWER(customer_name) NOT LIKE '%qa%account%'
    AND LOWER(customer_name) NOT LIKE '%axis%test%'
),
today_snap AS (
  SELECT COUNT(DISTINCT fp.customer_name) AS lives
  FROM filtered_policies fp, params p
  WHERE fp.date_ongoing_first <= p.snap_today
    AND (fp.amount_ongoing > 0 OR fp.date_ongoing_last >= p.snap_today)
),
pcp_snap AS (
  SELECT COUNT(DISTINCT fp.customer_name) AS lives
  FROM filtered_policies fp, params p
  WHERE fp.date_ongoing_first <= p.snap_pcp
    AND (fp.amount_ongoing > 0 OR fp.date_ongoing_last >= p.snap_pcp)
)
SELECT
  p.snap_today                                            AS snapshot_date,
  p.snap_pcp                                              AS pcp_date,
  t.lives                                                 AS lives_today,
  pp.lives                                                AS lives_pcp,
  (t.lives - pp.lives)                                    AS net_change,
  ROUND(((t.lives - pp.lives)::numeric / pp.lives) * 100, 2) AS pct_change
FROM params p, today_snap t, pcp_snap pp
"""


def get_lives_insured_metrics():
    """Fetch Lives Insured + PCP metrics from the CRM database.

    Returns dict with: lives_today, lives_pcp, pct_change, net_change,
                       snapshot_date, pcp_date
    or None on failure.
    """
    rows = run_query(LIVES_INSURED_SQL)
    if rows and len(rows) > 0:
        row = rows[0]
        log.info(
            f"CRM DB: Lives Insured = {row['lives_today']:,} "
            f"(PCP: {row['lives_pcp']:,}, change: {row['pct_change']}%)"
        )
        return row
    log.warning("CRM DB: No lives insured data returned")
    return None
