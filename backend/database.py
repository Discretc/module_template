"""SQLite access and joint-class grouping for module-outline generation."""

from __future__ import annotations

import os
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "module_outlines.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
SEED_PATH = BASE_DIR / "seed.sql"


def get_connection(db_path: str | os.PathLike | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Add master-workbook columns to databases created by earlier releases."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(classes)")}
    additions = {
        "rule_value": "TEXT",
        "joint_relationship": "TEXT",
        "academic_year": "TEXT",
        "semester": "TEXT",
        "medium_of_instruction": "TEXT DEFAULT 'English'",
    }
    for column, definition in additions.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE classes ADD COLUMN {column} {definition}")
    conn.commit()


def init_db(db_path: str | os.PathLike | None = None, seed: bool = True) -> None:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(path)
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    _migrate_schema(conn)
    if seed and SEED_PATH.exists():
        class_count = conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
        faculty_count = conn.execute("SELECT COUNT(*) FROM faculties").fetchone()[0]
        if class_count == 0 and faculty_count == 0:
            conn.executescript(SEED_PATH.read_text(encoding="utf-8"))
    conn.close()


def get_faculties() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, code, name_en, name_zh, name_pt FROM faculties ORDER BY code"
    ).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def get_programmes(faculty_id: int | None = None) -> list[dict]:
    conn = get_connection()
    sql = "SELECT id, code, name_en, name_zh, name_pt, degree_level FROM programmes"
    params: tuple = ()
    if faculty_id:
        sql += " WHERE faculty_id = ?"
        params = (faculty_id,)
    rows = conn.execute(sql + " ORDER BY code", params).fetchall()
    conn.close()
    return [dict(row) for row in rows]


def _split_relationships(value) -> list[str]:
    if value is None:
        return []
    return [part.strip() for part in str(value).replace(";", ",").split(",") if part.strip()]


def _full_rows(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT
            c.*, p.code AS prog_code, p.name_en AS prog_name_en,
            p.name_zh AS prog_name_zh, p.name_pt AS prog_name_pt,
            p.degree_level, p.faculty_id,
            f.code AS faculty_code, f.name_en AS faculty_en,
            f.name_zh AS faculty_zh, f.name_pt AS faculty_pt
        FROM classes c
        JOIN programmes p ON c.programme_id = p.id
        JOIN faculties f ON p.faculty_id = f.id
        ORDER BY c.class_code, c.id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def _joint_groups(rows: list[dict]) -> list[list[dict]]:
    """Return undirected connected components from Joint_Relationship values."""
    by_code = {row["class_code"]: row for row in rows}
    graph: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        code = row["class_code"]
        graph[code]
        for related in _split_relationships(row.get("joint_relationship")):
            if related in by_code and related != code:
                graph[code].add(related)
                graph[related].add(code)

    groups: list[list[dict]] = []
    visited: set[str] = set()
    for code in sorted(by_code):
        if code in visited:
            continue
        stack = [code]
        component: list[str] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(current)
            stack.extend(sorted(graph[current] - visited, reverse=True))
        groups.append([by_code[item] for item in sorted(component)])
    return groups


def _unique_text(members: list[dict], field: str, separator: str = " / ") -> str:
    values: list[str] = []
    for member in members:
        value = member.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in values:
            values.append(text)
    return separator.join(values)


def _unique_values(members: list[dict], field: str) -> list:
    values = []
    for member in members:
        value = member.get(field)
        if value is not None and value != "" and value not in values:
            values.append(value)
    return values


def _consolidate_group(members: list[dict]) -> dict:
    members = sorted(members, key=lambda item: item["class_code"])
    first = dict(members[0])
    codes = [member["class_code"] for member in members]
    first.update(
        {
            "id": min(member["id"] for member in members),
            "class_code": ", ".join(codes),
            "class_codes": codes,
            "joint_class": len(members) > 1,
            "joint_member_count": len(members),
            "joint_member_ids": [member["id"] for member in members],
            "joint_relationship": ", ".join(codes[1:]) if len(codes) > 1 else "",
            "marking_rules": _unique_values(members, "marking_rule"),
            "rule_values": _unique_values(members, "rule_value"),
            "degree_levels": _unique_values(members, "degree_level"),
        }
    )

    combined_fields = (
        "module_code", "module_name_en", "module_name_zh", "module_name_pt",
        "prerequisite_en", "prerequisite_zh", "prerequisite_pt",
        "credits", "duration", "medium_of_instruction",
        "instructor_en", "instructor_zh", "instructor_pt", "email",
        "room_en", "room_zh", "room_pt", "telephone",
        "prog_code", "prog_name_en", "prog_name_zh", "prog_name_pt",
        "faculty_code", "faculty_en", "faculty_zh", "faculty_pt",
        "academic_year", "semester",
    )
    for field in combined_fields:
        first[field] = _unique_text(members, field)

    for language in ("en", "zh", "pt"):
        first[f"programme_class_pairs_{language}"] = [
            {
                "class_code": member["class_code"],
                "programme": member.get(f"prog_name_{language}") or member.get("prog_name_en") or "",
            }
            for member in members
        ]
    return first


def _selected_groups(
    rows: list[dict],
    class_ids: list[int] | None = None,
    programme_id: int | None = None,
    faculty_id: int | None = None,
) -> list[list[dict]]:
    selected_ids = {int(value) for value in (class_ids or [])}
    selected: list[list[dict]] = []
    for group in _joint_groups(rows):
        include = not (selected_ids or programme_id or faculty_id)
        if selected_ids:
            include = any(member["id"] in selected_ids for member in group)
        elif programme_id:
            include = any(member["programme_id"] == programme_id for member in group)
        elif faculty_id:
            include = any(member["faculty_id"] == faculty_id for member in group)
        if include:
            selected.append(group)
    return selected


def get_classes(programme_id: int | None = None, faculty_id: int | None = None) -> list[dict]:
    conn = get_connection()
    rows = _full_rows(conn)
    conn.close()
    groups = _selected_groups(rows, programme_id=programme_id, faculty_id=faculty_id)
    summaries = []
    for group in groups:
        item = _consolidate_group(group)
        summaries.append(
            {
                key: item.get(key)
                for key in (
                    "id", "class_code", "class_codes", "module_code",
                    "module_name_en", "module_name_zh", "instructor_en",
                    "prog_name_en", "joint_class", "joint_member_count",
                )
            }
        )
    return sorted(summaries, key=lambda item: item["class_code"])


def get_classes_full(
    class_ids: list[int] | None = None,
    programme_id: int | None = None,
    faculty_id: int | None = None,
) -> list[dict]:
    """Return one consolidated record per standalone class or joint component."""
    conn = get_connection()
    rows = _full_rows(conn)
    conn.close()
    groups = _selected_groups(rows, class_ids, programme_id, faculty_id)
    return [_consolidate_group(group) for group in groups]


def get_academic_years(today: date | None = None) -> dict:
    """Return imported years plus a rolling range suitable for future selection."""
    current = today or date.today()
    start_year = current.year if current.month >= 8 else current.year - 1
    default = f"{start_year}/{start_year + 1}"
    rolling = {f"{year}/{year + 1}" for year in range(start_year - 1, start_year + 4)}

    conn = get_connection()
    imported = {
        str(row[0]).strip()
        for row in conn.execute(
            "SELECT DISTINCT academic_year FROM classes WHERE TRIM(COALESCE(academic_year, '')) <> ''"
        )
    }
    conn.close()
    years = sorted(rolling | imported, key=lambda value: int(value.split("/", 1)[0]), reverse=True)
    return {"years": years, "default": default}
