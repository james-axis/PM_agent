"""
PM Agent — Database Client
Connects to MySQL to discover schema for prototype generation.
"""

import os
import pymysql
from config import log

DB_HOST = os.getenv("DB_HOST")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME", "lifeinsurancepartners")


def get_connection():
    """Get a MySQL connection."""
    if not all([DB_HOST, DB_USER, DB_PASSWORD]):
        log.warning("DB credentials not set — schema discovery disabled")
        return None
    try:
        return pymysql.connect(
            host=DB_HOST, port=DB_PORT, user=DB_USER,
            password=DB_PASSWORD, database=DB_NAME,
            connect_timeout=5, read_timeout=5,
        )
    except Exception as e:
        log.error(f"DB connection failed: {e}")
        return None


def get_all_table_names():
    """Get all table names in the database."""
    conn = get_connection()
    if not conn:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute("SHOW TABLES")
            return [row[0] for row in cur.fetchall()]
    except Exception as e:
        log.error(f"Failed to list tables: {e}")
        return []
    finally:
        conn.close()


def get_table_schema(table_name):
    """Get column definitions for a single table."""
    conn = get_connection()
    if not conn:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(f"DESCRIBE `{table_name}`")
            columns = []
            for row in cur.fetchall():
                columns.append({
                    "name": row[0],
                    "type": row[1],
                    "null": row[2],
                    "key": row[3],
                    "default": row[4],
                })
            return {"table": table_name, "columns": columns}
    except Exception as e:
        log.error(f"Failed to describe {table_name}: {e}")
        return None
    finally:
        conn.close()


def discover_relevant_schemas(keywords):
    """
    Given a list of keywords (from PRD analysis), find and return
    schemas for tables whose names contain any of the keywords.
    Returns formatted string for prompt inclusion.
    """
    all_tables = get_all_table_names()
    if not all_tables:
        return "(Database schema unavailable)"

    # Match tables by keyword prefix/contains
    matched_tables = set()
    for kw in keywords:
        kw_lower = kw.lower().strip()
        for table in all_tables:
            if kw_lower in table.lower():
                matched_tables.add(table)

    if not matched_tables:
        return "(No matching tables found)"

    # Limit to 15 most relevant tables to keep context manageable
    matched_list = sorted(matched_tables)[:15]

    sections = []
    for table_name in matched_list:
        schema = get_table_schema(table_name)
        if schema:
            cols = ", ".join(
                f"{c['name']} ({c['type']}{'  PK' if c['key'] == 'PRI' else ''})"
                for c in schema["columns"]
            )
            sections.append(f"  {table_name}: {cols}")

    log.info(f"DB schema: matched {len(sections)} tables from keywords {keywords}")
    return "\n".join(sections) if sections else "(No schema details retrieved)"
