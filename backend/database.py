"""
database.py
-----------
SQLite helper functions: initialise the database, seed sample data,
and provide a query helper used by the Flask app.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "module_outlines.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
SEED_PATH = os.path.join(os.path.dirname(__file__), "seed.sql")


def get_connection() -> sqlite3.Connection:
    """Return a new connection with Row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(force: bool = False) -> None:
    """Create tables and seed data.  Set *force=True* to recreate from scratch."""
    if force and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    conn = get_connection()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    # Only seed if the modules table is empty
    cur = conn.execute("SELECT COUNT(*) FROM modules")
    if cur.fetchone()[0] == 0:
        with open(SEED_PATH) as f:
            conn.executescript(f.read())
        print("  ✔  Database seeded with sample data")

    conn.close()


def get_module(module_code: str) -> dict | None:
    """
    Look up a module by its code and return a flat dict with all fields
    needed to populate the template, or None if not found.
    """
    conn = get_connection()
    row = conn.execute(
        """
        SELECT
            m.module_code,
            m.module_name,
            m.prerequisites,
            m.medium_of_instruction,
            m.credits,
            m.contact_hours,
            p.programme_name,
            p.degree_level,
            p.academic_unit
        FROM modules m
        JOIN programmes p ON m.programme_id = p.id
        WHERE UPPER(m.module_code) = UPPER(?)
        """,
        (module_code,),
    ).fetchone()
    conn.close()

    if row is None:
        return None
    return dict(row)


def search_modules(query: str) -> list[dict]:
    """Return modules whose code or name matches a search query (for autocomplete)."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT m.module_code, m.module_name
        FROM modules m
        WHERE m.module_code LIKE ? OR m.module_name LIKE ?
        ORDER BY m.module_code
        LIMIT 20
        """,
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
