"""Import the authoritative master workbook into the application database."""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd

from rules import RuleValidationError, normalize_rule_code


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "module_outlines.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
SHEET = 0

# Exact headings in ``Master File to Elvis 20260902.xlsx``. The spelling and
# embedded spaces are intentional and are validated before the database changes.
COLUMN_MAP = {
    "faculty_code": "Faculty_Code",
    "faculty_zh": "Faculty _Chn",
    "faculty_en": "Faculty _Eng",
    "faculty_pt": "Faculty _Prt",
    "prog_code": "Prog_Code",
    "prog_zh": "Prog_Chn",
    "prog_en": "Prog_Eng",
    "prog_pt": "Prog_Prt",
    "class_code": "Class_Code",
    "module_name_zh": "Module_Chn",
    "module_name_en": "Module_Eng",
    "module_name_pt": "Module_Prt",
    "prerequisite_zh": "Prerequsite_Chn",
    "prerequisite_en": "Prerequsite_Eng",
    "prerequisite_pt": "Prerequsite_Por",
    "credits": "Credits",
    "duration": "Durations",
    "instructor_zh": "Instructor_Chn",
    "instructor_en": "Instructor_Eng",
    "instructor_pt": "Instructor_Prt",
    "email": "Email",
    "room_zh": "Room_Chn",
    "room_en": "Room_Eng",
    "room_pt": "Room_Prt",
    "telephone": "Telephone",
    "rule_code": "Rule",
    "joint_relationship": "Joint_Relationship",
}

# Legacy aliases keep older uploads working without weakening validation of the
# authoritative headings when the corresponding master heading is present.
COLUMN_ALIASES = {
    "faculty_zh": ("Faculty_Chn",),
    "faculty_en": ("Faculty_Eng",),
    "faculty_pt": ("Faculty_Prt",),
    "prerequisite_zh": ("Prerequisite_Chn",),
    "prerequisite_en": ("Prerequisite_Eng",),
    "prerequisite_pt": ("Prerequisite_Por",),
    "rule_code": ("Marking_Rule",),
}

OPTIONAL_COLUMNS = {
    "academic_year": ("Academic_Year", "Academic Year"),
    "semester": ("Semester",),
    "medium_of_instruction": ("Teaching_Language", "Medium_of_Instruction"),
}

MISSING_TEXT = {"", "none", "nan", "null", "n/a", "na", "not applicable", "-", "--"}


def _clean(value, default=""):
    if value is None or pd.isna(value):
        return default
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    text = str(value).replace("\xa0", " ").strip()
    return default if text.casefold() in MISSING_TEXT else text


def _header_for(row, field: str) -> str | None:
    candidates = (COLUMN_MAP.get(field),) + COLUMN_ALIASES.get(field, ()) + OPTIONAL_COLUMNS.get(field, ())
    return next((header for header in candidates if header and header in row.index), None)


def col(row, field: str, default=""):
    header = _header_for(row, field)
    return default if header is None else _clean(row[header], default)


def derive_degree_level(prog_name_en: str) -> str:
    name = (prog_name_en or "").upper()
    if "DOCTOR" in name or "PHILOSOPHY" in name:
        return "doctoral"
    if "MASTER" in name:
        return "master"
    return "bachelor"


def normalize_rule(value) -> int:
    """Compatibility wrapper around the canonical strict normalizer."""
    return normalize_rule_code(value)


def normalize_relationship(value, class_code: str = "") -> str:
    raw = _clean(value)
    if not raw:
        return ""
    values: list[str] = []
    for part in re.split(r"[,;\n]+", raw):
        code = part.strip()
        if code and code != class_code and code not in values:
            values.append(code)
    return ", ".join(values)


def _validate_headers(df: pd.DataFrame) -> None:
    available = set(df.columns)
    missing = []
    for field, authoritative in COLUMN_MAP.items():
        candidates = (authoritative,) + COLUMN_ALIASES.get(field, ())
        if not any(candidate in available for candidate in candidates):
            missing.append(authoritative)
    if missing:
        raise ValueError("Missing required master-workbook columns: " + ", ".join(missing))


def _new_database(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    return conn


def _validated_rule_codes(df: pd.DataFrame) -> dict[int, int]:
    header = next(
        candidate
        for candidate in (COLUMN_MAP["rule_code"],) + COLUMN_ALIASES["rule_code"]
        if candidate in df.columns
    )
    values: dict[int, int] = {}
    errors: list[str] = []
    for row_number, (index, row) in enumerate(df.iterrows(), start=2):
        class_code = _clean(row.get(COLUMN_MAP["class_code"])) or "unknown class"
        try:
            values[index] = normalize_rule_code(row.get(header))
        except RuleValidationError as exc:
            errors.append(f"row {row_number} ({class_code}): {exc}")
    if errors:
        raise ValueError("Invalid Rule values; import was not applied:\n" + "\n".join(errors))
    return values


def import_data(excel_path: str, db_path: str | os.PathLike | None = None) -> dict:
    """Validate and atomically replace the database from the master workbook."""
    result = {
        "faculties": 0,
        "programmes": 0,
        "classes": 0,
        "outlines": 0,
        "joint_groups": 0,
        "skipped": 0,
        "warnings": [],
    }
    df = pd.read_excel(excel_path, sheet_name=SHEET, dtype=object)
    df.columns = [str(column).strip() for column in df.columns]
    _validate_headers(df)
    validated_rules = _validated_rule_codes(df)
    result["total_rows"] = len(df)

    destination = Path(db_path or DB_PATH)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, staging_name = tempfile.mkstemp(prefix=f".{destination.stem}-", suffix=".db", dir=destination.parent)
    os.close(fd)
    staging = Path(staging_name)

    conn = None
    try:
        conn = _new_database(staging)
        faculty_map: dict[str, int] = {}
        programme_map: dict[str, int] = {}

        for _, row in df.iterrows():
            code = col(row, "faculty_code")
            if not code or code in faculty_map:
                continue
            cursor = conn.execute(
                "INSERT INTO faculties (code, name_en, name_zh, name_pt) VALUES (?,?,?,?)",
                (code, col(row, "faculty_en"), col(row, "faculty_zh"), col(row, "faculty_pt")),
            )
            faculty_map[code] = cursor.lastrowid

        for _, row in df.iterrows():
            code = col(row, "prog_code")
            if not code or code in programme_map:
                continue
            faculty_id = faculty_map.get(col(row, "faculty_code"))
            if faculty_id is None:
                result["warnings"].append(f"programme '{code}' has no valid faculty and was skipped")
                continue
            english_name = col(row, "prog_en")
            cursor = conn.execute(
                """INSERT INTO programmes
                   (code, name_en, name_zh, name_pt, degree_level, faculty_id)
                   VALUES (?,?,?,?,?,?)""",
                (
                    code, english_name, col(row, "prog_zh"), col(row, "prog_pt"),
                    derive_degree_level(english_name), faculty_id,
                ),
            )
            programme_map[code] = cursor.lastrowid

        seen_codes: set[str] = set()
        imported_codes: list[str] = []
        relationships: dict[str, list[str]] = {}
        for row_number, (_, row) in enumerate(df.iterrows(), start=2):
            class_code = col(row, "class_code")
            programme_id = programme_map.get(col(row, "prog_code"))
            if not class_code or programme_id is None:
                result["warnings"].append(f"row {row_number} has no valid class/programme and was skipped")
                result["skipped"] += 1
                continue
            if class_code in seen_codes:
                result["warnings"].append(f"duplicate class_code '{class_code}' was skipped")
                result["skipped"] += 1
                continue
            seen_codes.add(class_code)

            rule_code = validated_rules[row.name]
            relationship = normalize_relationship(col(row, "joint_relationship"), class_code)
            relationships[class_code] = [part.strip() for part in relationship.split(",") if part.strip()]

            credits = col(row, "credits")
            duration = col(row, "duration")
            conn.execute(
                """INSERT INTO classes
                   (class_code, module_code, module_name_en, module_name_zh, module_name_pt,
                    prerequisite_en, prerequisite_zh, prerequisite_pt, credits, duration,
                    medium_of_instruction, instructor_en, instructor_zh, instructor_pt,
                    email, room_en, room_zh, room_pt, telephone, rule_code,
                    joint_relationship, programme_id, academic_year, semester)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    class_code,
                    class_code.rsplit("-", 1)[0] if "-" in class_code else class_code,
                    col(row, "module_name_en"), col(row, "module_name_zh"), col(row, "module_name_pt"),
                    col(row, "prerequisite_en"), col(row, "prerequisite_zh"), col(row, "prerequisite_pt"),
                    int(float(credits)) if credits else None,
                    int(float(duration)) if duration else None,
                    col(row, "medium_of_instruction"),
                    col(row, "instructor_en"), col(row, "instructor_zh"), col(row, "instructor_pt"),
                    col(row, "email"), col(row, "room_en"), col(row, "room_zh"), col(row, "room_pt"),
                    col(row, "telephone"), rule_code, relationship, programme_id,
                    col(row, "academic_year"), col(row, "semester"),
                ),
            )
            imported_codes.append(class_code)

        imported_set = set(imported_codes)
        for class_code, related_codes in relationships.items():
            for related in related_codes:
                if related not in imported_set:
                    result["warnings"].append(
                        f"class '{class_code}' references missing joint class '{related}'"
                    )

        conn.commit()
        conn.close()
        conn = None
        os.replace(staging, destination)

        # Use the same connected-component behavior as the application without
        # importing database.py (which may point at a different configured DB).
        graph = {code: set() for code in imported_codes}
        for code, related_codes in relationships.items():
            for related in related_codes:
                if related in graph:
                    graph[code].add(related)
                    graph[related].add(code)
        visited: set[str] = set()
        components = []
        for code in sorted(graph):
            if code in visited:
                continue
            stack = [code]
            component = []
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.append(current)
                stack.extend(graph[current] - visited)
            components.append(component)

        result["faculties"] = len(faculty_map)
        result["programmes"] = len(programme_map)
        result["classes"] = len(imported_codes)
        result["outlines"] = len(components)
        result["joint_groups"] = sum(len(component) > 1 for component in components)
        return result
    except Exception:
        if conn is not None:
            conn.close()
        staging.unlink(missing_ok=True)
        raise


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backend/import_excel.py path/to/data.xlsx")
        raise SystemExit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}")
        raise SystemExit(1)
    imported = import_data(str(path))
    print(f"  {imported['total_rows']} rows found")
    print(f"  {imported['faculties']} faculties imported")
    print(f"  {imported['programmes']} programmes imported")
    print(f"  {imported['classes']} classes grouped into {imported['outlines']} outlines")
    for warning in imported["warnings"]:
        print(f"  WARNING: {warning}")
