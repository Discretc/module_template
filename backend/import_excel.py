"""Import the authoritative master workbook into the application database."""

from __future__ import annotations

import os
import re
import sqlite3
import sys
import tempfile
from pathlib import Path

import pandas as pd

from class_records import INSTRUCTOR_FIELDS, PREREQUISITE_FIELDS, unique_records
from rules import RuleValidationError, normalize_rule_code


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "module_outlines.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
SHEET = 0

# Exact headings in ``Master File to Elvis 20261030.xlsx``. The spelling and
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
    "prerequisite_code": "Prerequsite_Code",
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

OPTIONAL_MASTER_FIELDS = {"room_en", "room_pt"}

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
        if field in OPTIONAL_MASTER_FIELDS:
            continue
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


# These are scalar identities; contacts, prerequisites and joint edges may vary.
CLASS_METADATA = (
    "faculty_code", "faculty_zh", "faculty_en", "faculty_pt",
    "prog_code", "prog_zh", "prog_en", "prog_pt",
    "module_name_zh", "module_name_en", "module_name_pt",
    "credits", "duration", "rule_code", "academic_year", "semester",
)


def _aggregate_rows(df, validated_rules):
    groups = {}
    errors = []
    for number, (index, source) in enumerate(df.iterrows(), start=2):
        row = {field: col(source, field) for field in (*COLUMN_MAP, *OPTIONAL_COLUMNS)}
        code = row["class_code"]
        if not code:
            errors.append(f"row {number}: Class_Code is missing")
            continue
        for field in ("faculty_code", "prog_code"):
            if not row[field]:
                errors.append(f"row {number} ({code}): {COLUMN_MAP[field]} is missing")
        row["rule_code"] = validated_rules[index]
        for field in ("credits", "duration"):
            try:
                value = float(row[field]) if row[field] else None
                if value is not None and (not value.is_integer() or value < 0):
                    raise ValueError
                row[field] = int(value) if value is not None else None
            except (ValueError, OverflowError):
                errors.append(f"row {number} ({code}): invalid {COLUMN_MAP[field]} {row[field]!r}; expected a non-negative whole number")
        groups.setdefault(code, []).append((number, row))

    def consistent(rows, fields, label):
        for field in fields:
            values = {}
            for number, row in rows:
                values.setdefault(row[field], []).append(number)
            if len(values) > 1:
                detail = "; ".join(f"{value!r} at rows {numbers}" for value, numbers in values.items())
                errors.append(f"{label}: conflicting {COLUMN_MAP.get(field, field)}: {detail}")

    for code, rows in groups.items():
        consistent(rows, CLASS_METADATA, f"Class_Code {code}")
    # Shared lookups must agree on faculty identity. Programme wording is
    # snapshotted per class, with cross-class variants reported as warnings.
    all_rows = [item for rows in groups.values() for item in rows]
    for identity, fields in (
        ("faculty_code", ("faculty_zh", "faculty_en", "faculty_pt")),
        ("prog_code", ("faculty_code",)),
    ):
        identities = {}
        for item in all_rows:
            identities.setdefault(item[1][identity], []).append(item)
        for code, rows in identities.items():
            affected = ", ".join(dict.fromkeys(row["class_code"] for _, row in rows))
            consistent(rows, fields, f"{COLUMN_MAP[identity]} {code} (Class_Code {affected})")
    if errors:
        raise ValueError("Conflicting or invalid master-workbook data; import was not applied:\n" + "\n".join(errors))

    aggregated = []
    for code, rows in groups.items():
        first = dict(rows[0][1])
        first["instructors"] = unique_records([
            {**{f"name_{lang}": row[f"instructor_{lang}"] for lang in ("en", "zh", "pt")},
             **{field: row[field] for field in INSTRUCTOR_FIELDS if not field.startswith("name_")}}
            for _, row in rows
        ], INSTRUCTOR_FIELDS)
        first["prerequisites"] = unique_records([
            {"prerequisite_code": row["prerequisite_code"],
             **{f"name_{lang}": row[f"prerequisite_{lang}"] for lang in ("en", "zh", "pt")}}
            for _, row in rows
        ], PREREQUISITE_FIELDS)
        edges = []
        for _, row in rows:
            for edge in normalize_relationship(row["joint_relationship"], code).split(", "):
                if edge and edge not in edges:
                    edges.append(edge)
        first["joint_relationship"] = ", ".join(edges)
        aggregated.append(first)
    return aggregated


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
    records = _aggregate_rows(df, validated_rules)
    result["total_rows"] = len(df)
    result["repeated_classes"] = {code: int(count) for code, count in df[COLUMN_MAP["class_code"]].map(_clean).value_counts(sort=False).items() if count > 1}

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

        for code, rows in df.groupby(COLUMN_MAP["prog_code"], sort=False):
            for field in ("prog_en", "prog_zh", "prog_pt"):
                variants = list(dict.fromkeys(col(row, field) for _, row in rows.iterrows()))
                if len(variants) > 1:
                    result["warnings"].append(
                        f"programme '{code}' has class-specific {COLUMN_MAP[field]} variants: {variants!r}; "
                        "all values are preserved per class; programme selector uses the first source value"
                    )

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

        imported_codes: list[str] = []
        relationships: dict[str, list[str]] = {}
        for row in records:
            class_code = row["class_code"]
            programme_id = programme_map[row["prog_code"]]
            rule_code = row["rule_code"]
            relationship = row["joint_relationship"]
            relationships[class_code] = [part.strip() for part in relationship.split(",") if part.strip()]

            credits = row["credits"]
            duration = row["duration"]
            cursor = conn.execute(
                """INSERT INTO classes
                   (class_code, module_code, module_name_en, module_name_zh, module_name_pt,
                    prerequisite_en, prerequisite_zh, prerequisite_pt, credits, duration,
                    medium_of_instruction, instructor_en, instructor_zh, instructor_pt,
                    email, room_en, room_zh, room_pt, telephone, rule_code,
                    joint_relationship, programme_id, academic_year, semester,
                    programme_name_en, programme_name_zh, programme_name_pt)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    class_code,
                    class_code.rsplit("-", 1)[0] if "-" in class_code else class_code,
                    row["module_name_en"], row["module_name_zh"], row["module_name_pt"],
                    row["prerequisite_en"], row["prerequisite_zh"], row["prerequisite_pt"],
                    credits, duration,
                    row["medium_of_instruction"] or None,
                    row["instructor_en"], row["instructor_zh"], row["instructor_pt"],
                    row["email"], row["room_en"], row["room_zh"], row["room_pt"],
                    row["telephone"], rule_code, relationship, programme_id,
                    row["academic_year"], row["semester"],
                    row["prog_en"], row["prog_zh"], row["prog_pt"],
                ),
            )
            for table, fields, key in (
                ("class_instructors", INSTRUCTOR_FIELDS, "instructors"),
                ("class_prerequisites", PREREQUISITE_FIELDS, "prerequisites"),
            ):
                for position, record in enumerate(row[key]):
                    columns = ("class_id", "position") + fields
                    conn.execute(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
                        (cursor.lastrowid, position, *(record[field] for field in fields)),
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

        result["instructors"] = sum(len(row["instructors"]) for row in records)
        result["prerequisites"] = sum(len(row["prerequisites"]) for row in records)
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
