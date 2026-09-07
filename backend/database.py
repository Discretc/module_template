"""SQLite access and joint-class grouping for module-outline generation."""

from __future__ import annotations

import os
import re
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

from rules import (
    JointRuleConflictError,
    RuleValidationError,
    normalize_rule_code,
    require_consistent_joint_rule,
)


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "module_outlines.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
SEED_PATH = BASE_DIR / "seed.sql"


def get_connection(db_path: str | os.PathLike | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path or DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


class RuleMigrationRequiredError(RuntimeError):
    """Raised when legacy rows do not contain an explicit valid rule."""


CLASS_COLUMNS = (
    "id", "class_code", "module_code", "module_name_en", "module_name_zh",
    "module_name_pt", "prerequisite_en", "prerequisite_zh", "prerequisite_pt",
    "credits", "duration", "medium_of_instruction", "instructor_en",
    "instructor_zh", "instructor_pt", "email", "room_en", "room_zh", "room_pt",
    "telephone", "rule_code", "joint_relationship", "programme_id",
    "academic_year", "semester",
)


def _record_rule_review(conn: sqlite3.Connection, issues: list[dict]) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS rule_migration_review (
               class_id INTEGER, class_code TEXT, legacy_value TEXT,
               reason TEXT NOT NULL, flagged_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
           )"""
    )
    conn.execute("DELETE FROM rule_migration_review")
    conn.executemany(
        """INSERT INTO rule_migration_review
           (class_id, class_code, legacy_value, reason) VALUES (?, ?, ?, ?)""",
        [
            (issue["id"], issue["class_code"], issue["legacy_value"], issue["reason"])
            for issue in issues
        ],
    )
    conn.commit()


def _create_classes_table(conn: sqlite3.Connection, name: str = "classes") -> None:
    conn.execute(
        f"""CREATE TABLE {name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            class_code TEXT NOT NULL UNIQUE,
            module_code TEXT NOT NULL,
            module_name_en TEXT, module_name_zh TEXT, module_name_pt TEXT,
            prerequisite_en TEXT DEFAULT 'Nil', prerequisite_zh TEXT,
            prerequisite_pt TEXT DEFAULT 'Nil', credits INTEGER, duration INTEGER,
            medium_of_instruction TEXT DEFAULT 'English', instructor_en TEXT,
            instructor_zh TEXT, instructor_pt TEXT, email TEXT, room_en TEXT,
            room_zh TEXT, room_pt TEXT, telephone TEXT,
            rule_code INTEGER NOT NULL CHECK (rule_code IN (1, 2, 3, 4)),
            joint_relationship TEXT,
            programme_id INTEGER NOT NULL REFERENCES programmes(id),
            academic_year TEXT, semester TEXT
        )"""
    )


def _rebuild_classes(conn: sqlite3.Connection, rows: list[dict], rules: dict[int, int]) -> None:
    existing = set(rows[0]) if rows else {
        row[1] for row in conn.execute("PRAGMA table_info(classes)")
    }
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.execute("BEGIN")
        conn.execute("DROP TABLE IF EXISTS classes_rule_migration")
        _create_classes_table(conn, "classes_rule_migration")
        placeholders = ",".join("?" for _ in CLASS_COLUMNS)
        for row in rows:
            values = []
            for column in CLASS_COLUMNS:
                if column == "rule_code":
                    value = rules[row["id"]]
                elif column in existing:
                    value = row.get(column)
                elif column == "module_code":
                    class_code = str(row.get("class_code") or "")
                    value = class_code.rsplit("-", 1)[0] if "-" in class_code else class_code
                else:
                    value = None
                values.append(value)
            conn.execute(
                f"INSERT INTO classes_rule_migration ({','.join(CLASS_COLUMNS)}) VALUES ({placeholders})",
                values,
            )
        conn.execute("DROP TABLE classes")
        conn.execute("ALTER TABLE classes_rule_migration RENAME TO classes")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Migrate legacy class rules without inventing values for missing records."""
    info = list(conn.execute("PRAGMA table_info(classes)"))
    if not info:
        return
    existing = {row[1] for row in info}
    sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='classes'"
    ).fetchone()[0]
    constraint_present = bool(
        re.search(r"rule_code\s+INTEGER\s+NOT\s+NULL", sql or "", re.IGNORECASE)
        and re.search(r"rule_code\s+IN\s*\(\s*1\s*,\s*2\s*,\s*3\s*,\s*4\s*\)", sql or "", re.IGNORECASE)
    )
    legacy_columns = {"marking_rule", "rule_value"} & existing
    if "rule_code" in existing and constraint_present and not legacy_columns:
        return

    source_column = next(
        (column for column in ("rule_code", "marking_rule", "rule_value") if column in existing),
        None,
    )
    rows = [dict(row) for row in conn.execute("SELECT * FROM classes ORDER BY id")]
    rules: dict[int, int] = {}
    issues: list[dict] = []
    for row in rows:
        value = row.get(source_column) if source_column else None
        try:
            rules[row["id"]] = normalize_rule_code(value)
        except RuleValidationError as exc:
            issues.append(
                {
                    "id": row.get("id"),
                    "class_code": row.get("class_code"),
                    "legacy_value": None if value is None else str(value),
                    "reason": str(exc),
                }
            )
    if issues:
        _record_rule_review(conn, issues)
        detail = "; ".join(
            f"{item['class_code'] or item['id']}: {item['reason']}" for item in issues
        )
        raise RuleMigrationRequiredError(
            "Rule migration requires review; see rule_migration_review. " + detail
        )
    _rebuild_classes(conn, rows, rules)


def init_db(db_path: str | os.PathLike | None = None, seed: bool = True) -> None:
    path = Path(db_path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = get_connection(path)
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        _migrate_schema(conn)
        if seed and SEED_PATH.exists():
            class_count = conn.execute("SELECT COUNT(*) FROM classes").fetchone()[0]
            faculty_count = conn.execute("SELECT COUNT(*) FROM faculties").fetchone()[0]
            if class_count == 0 and faculty_count == 0:
                conn.executescript(SEED_PATH.read_text(encoding="utf-8"))
    finally:
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


def _consolidate_group(members: list[dict], strict_rule: bool = True) -> dict:
    members = sorted(members, key=lambda item: item["class_code"])
    first = dict(members[0])
    codes = [member["class_code"] for member in members]
    try:
        rule_code = require_consistent_joint_rule(members)
        rule_conflict = False
        rule_conflicts = []
    except JointRuleConflictError:
        if strict_rule:
            raise
        rule_code = None
        rule_conflict = True
        rule_conflicts = [
            {"class_code": member["class_code"], "rule_code": member.get("rule_code")}
            for member in members
        ]
    first.update(
        {
            "id": min(member["id"] for member in members),
            "class_code": ", ".join(codes),
            "class_codes": codes,
            "joint_class": len(members) > 1,
            "joint_member_count": len(members),
            "joint_member_ids": [member["id"] for member in members],
            "joint_relationship": ", ".join(codes[1:]) if len(codes) > 1 else "",
            "rule_code": rule_code,
            "rule_conflict": rule_conflict,
            "rule_conflicts": rule_conflicts,
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
        item = _consolidate_group(group, strict_rule=False)
        summaries.append(
            {
                key: item.get(key)
                for key in (
                    "id", "class_code", "class_codes", "module_code",
                    "module_name_en", "module_name_zh", "instructor_en",
                    "prog_name_en", "joint_class", "joint_member_count",
                    "rule_conflict", "rule_conflicts",
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
