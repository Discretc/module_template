"""
import_excel.py
---------------
Imports real-world module/class data from an Excel file into the SQLite
database, replacing any existing data.

USAGE
-----
    python backend/import_excel.py path/to/your_data.xlsx

The script expects one sheet where each row represents a class assignment.
Programme and faculty information is derived from columns on the same sheet.

HOW TO ADAPT WHEN COLUMN HEADERS CHANGE
-----------------------------------------
Update the COLUMN_MAP section below.  Keys on the left are internal names
used by the app — do not change them.  Values on the right must match the
exact Excel column headers.
"""

import sys
import os
import sqlite3
import pandas as pd

# ---------------------------------------------------------------------------
# COLUMN MAP — change the VALUES to match your Excel headers
# ---------------------------------------------------------------------------
COLUMN_MAP = {
    # Faculty
    "faculty_code": "Faculty_Code",
    "faculty_en":   "Faculty_Eng",
    "faculty_zh":   "Faculty_Chn",
    "faculty_pt":   "Faculty_Prt",

    # Programme
    "prog_code":    "Prog_Code",
    "prog_en":      "Prog_Eng",
    "prog_zh":      "Prog_Chn",
    "prog_pt":      "Prog_Prt",

    # Class / Module
    "class_code":      "Class_Code",
    "module_name_en":  "Module_Eng",
    "module_name_zh":  "Module_Chn",
    "module_name_pt":  "Module_Prt",
    "prerequisite_en": "Prerequisite_Eng",
    "prerequisite_zh": "Prerequisite_Chn",
    "prerequisite_pt": "Prerequisite_Por",
    "credits":         "Credits",
    "duration":        "Durations",

    # Instructor
    "instructor_en":   "Instructor_Eng",
    "instructor_zh":   "Instructor_Chn",
    "instructor_pt":   "Instructor_Prt",
    "email":           "Email",
    "room_en":         "Room_Eng",
    "room_zh":         "Room_Chn",
    "room_pt":         "Room_Prt",
    "telephone":       "Telephone",
    "marking_rule":    "Marking_Rule",
}

# Which sheet to read (0 = first sheet, or use a sheet name string)
SHEET = 0

# ---------------------------------------------------------------------------
DB_PATH = os.path.join(os.path.dirname(__file__), "module_outlines.db")
SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "schema.sql")


def col(row, field, default=""):
    """Get a value from a DataFrame row using the column map."""
    header = COLUMN_MAP.get(field)
    if header is None or header not in row.index:
        return default
    val = row[header]
    if pd.isna(val) or str(val).strip() == "":
        return default
    return str(val).strip()


def derive_degree_level(prog_name_en):
    """Infer degree level from the English programme name."""
    name = (prog_name_en or "").upper()
    if "DOCTOR" in name or "PHILOSOPHY" in name:
        return "doctoral"
    elif "MASTER" in name:
        return "master"
    return "bachelor"


def import_data(excel_path: str) -> dict:
    """Import data from an Excel file into the database.
    Returns a dict with counts and status."""
    result = {"faculties": 0, "programmes": 0, "classes": 0, "skipped": 0, "warnings": []}

    df = pd.read_excel(excel_path, sheet_name=SHEET)
    df.columns = [str(c).strip() for c in df.columns]
    result["total_rows"] = len(df)

    # --- Recreate database ---
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    with open(SCHEMA_PATH) as f:
        conn.executescript(f.read())

    # --- Pass 1: faculties ---
    faculty_map = {}  # code -> id
    for _, row in df.iterrows():
        code = col(row, "faculty_code")
        if not code or code in faculty_map:
            continue
        cur = conn.execute(
            "INSERT INTO faculties (code, name_en, name_zh, name_pt) VALUES (?,?,?,?)",
            (code, col(row, "faculty_en"), col(row, "faculty_zh"), col(row, "faculty_pt")),
        )
        faculty_map[code] = cur.lastrowid
    conn.commit()
    result["faculties"] = len(faculty_map)

    # --- Pass 2: programmes ---
    prog_map = {}  # code -> id
    for _, row in df.iterrows():
        pcode = col(row, "prog_code")
        if not pcode or pcode in prog_map:
            continue
        fac_code = col(row, "faculty_code")
        fac_id = faculty_map.get(fac_code)
        if fac_id is None:
            continue
        prog_en = col(row, "prog_en")
        degree = derive_degree_level(prog_en)
        cur = conn.execute(
            "INSERT INTO programmes (code, name_en, name_zh, name_pt, degree_level, faculty_id) VALUES (?,?,?,?,?,?)",
            (pcode, prog_en, col(row, "prog_zh"), col(row, "prog_pt"), degree, fac_id),
        )
        prog_map[pcode] = cur.lastrowid
    conn.commit()
    result["programmes"] = len(prog_map)

    # --- Pass 3: classes ---
    imported = 0
    skipped = 0
    for _, row in df.iterrows():
        class_code = col(row, "class_code")
        pcode = col(row, "prog_code")
        if not class_code or not pcode:
            skipped += 1
            continue
        prog_id = prog_map.get(pcode)
        if prog_id is None:
            skipped += 1
            continue

        # Derive module_code from class_code (e.g. "COMP1123-121" -> "COMP1123")
        module_code = class_code.rsplit("-", 1)[0] if "-" in class_code else class_code

        credits_val = col(row, "credits")
        duration_val = col(row, "duration")

        try:
            marking_rule_val = col(row, "marking_rule", "1")
            try:
                marking_rule_int = int(float(marking_rule_val))
            except (ValueError, TypeError):
                marking_rule_int = 1

            conn.execute(
                """INSERT INTO classes
                   (class_code, module_code, module_name_en, module_name_zh, module_name_pt,
                    prerequisite_en, prerequisite_zh, prerequisite_pt,
                    credits, duration, instructor_en, instructor_zh, instructor_pt,
                    email, room_en, room_zh, room_pt, telephone, marking_rule, programme_id)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    class_code, module_code,
                    col(row, "module_name_en"), col(row, "module_name_zh"), col(row, "module_name_pt"),
                    col(row, "prerequisite_en", "Nil"), col(row, "prerequisite_zh"), col(row, "prerequisite_pt", "Nil"),
                    int(float(credits_val)) if credits_val else None,
                    int(float(duration_val)) if duration_val else None,
                    col(row, "instructor_en"), col(row, "instructor_zh"), col(row, "instructor_pt"),
                    col(row, "email"),
                    col(row, "room_en"), col(row, "room_zh"), col(row, "room_pt"),
                    col(row, "telephone"),
                    marking_rule_int,
                    prog_id,
                ),
            )
            imported += 1
        except sqlite3.IntegrityError:
            result["warnings"].append(f"duplicate class_code '{class_code}' — skipped")
            skipped += 1

    conn.commit()
    conn.close()
    result["classes"] = imported
    result["skipped"] = skipped
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backend/import_excel.py path/to/data.xlsx")
        sys.exit(1)
    path = sys.argv[1]
    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)
    import_result = import_data(path)
    print(f"  {import_result['total_rows']} rows found")
    print(f"  {import_result['faculties']} faculty/ies imported")
    print(f"  {import_result['programmes']} programme(s) imported")
    print(f"  {import_result['classes']} class(es) imported, {import_result['skipped']} skipped")
    for w in import_result.get("warnings", []):
        print(f"  WARNING: {w}")
    print("Done.")
