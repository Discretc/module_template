"""
database.py
-----------
SQLite helper functions for the trilingual module-outline system.
Provides cascading-dropdown queries and batch class retrieval.
"""

import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(__file__), "module_outlines.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")
SEED_PATH = os.path.join(os.path.dirname(__file__), "seed.sql")


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())
    # Seed only if no real data has been imported yet
    if os.path.exists(SEED_PATH):
        cur = conn.execute("SELECT COUNT(*) FROM classes")
        if cur.fetchone()[0] == 0:
            cur2 = conn.execute("SELECT COUNT(*) FROM faculties")
            if cur2.fetchone()[0] == 0:
                with open(SEED_PATH) as f:
                    conn.executescript(f.read())
                print("  Database seeded with sample data")
    conn.close()


# ── Dropdown queries (cascading) ─────────────────────────────────────────────

def get_faculties() -> list[dict]:
    conn = get_connection()
    rows = conn.execute("SELECT id, code, name_en, name_zh FROM faculties ORDER BY code").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_programmes(faculty_id: int | None = None) -> list[dict]:
    conn = get_connection()
    if faculty_id:
        rows = conn.execute(
            "SELECT id, code, name_en, name_zh, degree_level FROM programmes WHERE faculty_id = ? ORDER BY code",
            (faculty_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, code, name_en, name_zh, degree_level FROM programmes ORDER BY code"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_classes(programme_id: int | None = None, faculty_id: int | None = None) -> list[dict]:
    conn = get_connection()
    if programme_id:
        rows = conn.execute(
            "SELECT id, class_code, module_code, module_name_en, module_name_zh, instructor_en FROM classes WHERE programme_id = ? ORDER BY class_code",
            (programme_id,),
        ).fetchall()
    elif faculty_id:
        rows = conn.execute(
            """SELECT c.id, c.class_code, c.module_code, c.module_name_en, c.module_name_zh, c.instructor_en
               FROM classes c JOIN programmes p ON c.programme_id = p.id
               WHERE p.faculty_id = ? ORDER BY c.class_code""",
            (faculty_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT id, class_code, module_code, module_name_en, module_name_zh, instructor_en FROM classes ORDER BY class_code"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_classes_full(class_ids: list[int] | None = None,
                     programme_id: int | None = None,
                     faculty_id: int | None = None) -> list[dict]:
    """Return full class + programme + faculty data for template generation."""
    conn = get_connection()

    base = """
        SELECT
            c.*, p.code AS prog_code, p.name_en AS prog_name_en,
            p.name_zh AS prog_name_zh, p.name_pt AS prog_name_pt,
            p.degree_level,
            f.name_en AS faculty_en, f.name_zh AS faculty_zh, f.name_pt AS faculty_pt
        FROM classes c
        JOIN programmes p ON c.programme_id = p.id
        JOIN faculties f ON p.faculty_id = f.id
    """

    if class_ids:
        placeholders = ",".join("?" * len(class_ids))
        rows = conn.execute(f"{base} WHERE c.id IN ({placeholders}) ORDER BY c.class_code", class_ids).fetchall()
    elif programme_id:
        rows = conn.execute(f"{base} WHERE c.programme_id = ? ORDER BY c.class_code", (programme_id,)).fetchall()
    elif faculty_id:
        rows = conn.execute(f"{base} WHERE p.faculty_id = ? ORDER BY c.class_code", (faculty_id,)).fetchall()
    else:
        rows = conn.execute(f"{base} ORDER BY c.class_code").fetchall()

    conn.close()
    return [dict(r) for r in rows]
