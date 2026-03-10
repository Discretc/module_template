"""
import_excel.py
---------------
Imports real-world module and programme data from an Excel file into the
SQLite database, replacing any existing data.

USAGE
-----
    python backend/import_excel.py path/to/your_data.xlsx

The script expects one sheet where each row represents a module.
Programme information (name, degree level, academic unit) can either be
repeated on every row or live on a separate sheet — both layouts are handled.

HOW TO ADAPT WHEN YOU RECEIVE THE REAL EXCEL FILE
---------------------------------------------------
1. Open the Excel file and note the exact column header names.
2. Update the COLUMN MAP section below to match.
3. If programmes are on a separate sheet, set PROGRAMME_SHEET to that sheet name
   and update PROGRAMME_COLUMN_MAP.  Otherwise leave PROGRAMME_SHEET as None and
   keep programme columns inside the main MODULE_COLUMN_MAP.
4. Run the script — it will wipe the existing data and import everything fresh.
"""

import sys
import os
import sqlite3
import pandas as pd

# ---------------------------------------------------------------------------
# COLUMN MAP
# ---------------------------------------------------------------------------
# Change the VALUES on the right to match your actual Excel column headers.
# The KEYS on the left are the internal field names used by the app — do not
# change those.

MODULE_COLUMN_MAP = {
    # Internal field      : Excel column header (exact, case-insensitive)
    "module_code"         : "Module Code",
    "module_name"         : "Module Name",
    "prerequisites"       : "Pre-requisite(s)",
    "medium_of_instruction": "Medium of Instruction",
    "credits"             : "Credits",
    "contact_hours"       : "Contact Hours",

    # Programme fields — include these only when programme data is on the
    # same sheet as modules (i.e. PROGRAMME_SHEET = None below).
    "programme_name"      : "Programme Name",
    "degree_level"        : "Degree Level",      # "Bachelor's", "Master's", "Doctoral"
    "academic_unit"       : "Academic Unit",
}

# Name of the sheet containing module rows.
MODULE_SHEET = 0   # 0 means the first sheet; use the sheet name string if needed

# If your programmes are on a separate sheet, set this to the sheet name and
# fill PROGRAMME_COLUMN_MAP.  Otherwise leave as None.
PROGRAMME_SHEET = None

PROGRAMME_COLUMN_MAP = {
    "programme_name" : "Programme Name",
    "degree_level"   : "Degree Level",
    "academic_unit"  : "Academic Unit",
}

# ---------------------------------------------------------------------------
# DEFAULTS — used when a cell is blank
# ---------------------------------------------------------------------------
DEFAULTS = {
    "prerequisites"         : "Nil",
    "medium_of_instruction" : "English",
    "contact_hours"         : "45 hrs",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

DB_PATH = os.path.join(os.path.dirname(__file__), "module_outlines.db")


def get_col(row, mapping, field):
    """Return the value for *field* from *row* using the column map."""
    header = mapping.get(field)
    if header is None or header not in row.index:
        return DEFAULTS.get(field, "")
    val = row[header]
    if pd.isna(val) or str(val).strip() == "":
        return DEFAULTS.get(field, "")
    return str(val).strip()


def normalise_headers(df):
    """Strip whitespace from column headers so minor formatting differences
    in the Excel file don't cause key-not-found errors."""
    df.columns = [str(c).strip() for c in df.columns]
    return df


def import_data(excel_path: str):
    print(f"Reading: {excel_path}")

    # --- Load sheets ---
    df_modules = normalise_headers(pd.read_excel(excel_path, sheet_name=MODULE_SHEET))
    print(f"  {len(df_modules)} rows found in the module sheet")

    df_programmes = None
    if PROGRAMME_SHEET is not None:
        df_programmes = normalise_headers(
            pd.read_excel(excel_path, sheet_name=PROGRAMME_SHEET)
        )
        print(f"  {len(df_programmes)} rows found in the programme sheet")

    # --- Connect and wipe existing data ---
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("DELETE FROM modules")
    conn.execute("DELETE FROM programmes")
    conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('modules','programmes')")
    conn.commit()
    print("  Existing data cleared")

    # --- Insert programmes ---
    programme_id_map = {}   # programme_name -> id

    if df_programmes is not None:
        # Programmes come from a separate sheet
        for _, row in df_programmes.iterrows():
            name  = get_col(row, PROGRAMME_COLUMN_MAP, "programme_name")
            level = get_col(row, PROGRAMME_COLUMN_MAP, "degree_level")
            unit  = get_col(row, PROGRAMME_COLUMN_MAP, "academic_unit")
            if not name:
                continue
            if name not in programme_id_map:
                cur = conn.execute(
                    "INSERT INTO programmes (programme_name, degree_level, academic_unit) VALUES (?,?,?)",
                    (name, level, unit),
                )
                programme_id_map[name] = cur.lastrowid
    else:
        # Derive unique programmes from the module sheet
        for _, row in df_modules.iterrows():
            name  = get_col(row, MODULE_COLUMN_MAP, "programme_name")
            level = get_col(row, MODULE_COLUMN_MAP, "degree_level")
            unit  = get_col(row, MODULE_COLUMN_MAP, "academic_unit")
            if not name or name in programme_id_map:
                continue
            cur = conn.execute(
                "INSERT INTO programmes (programme_name, degree_level, academic_unit) VALUES (?,?,?)",
                (name, level, unit),
            )
            programme_id_map[name] = cur.lastrowid

    conn.commit()
    print(f"  {len(programme_id_map)} programme(s) imported")

    # --- Insert modules ---
    imported = 0
    skipped  = 0

    for _, row in df_modules.iterrows():
        code  = get_col(row, MODULE_COLUMN_MAP, "module_code")
        name  = get_col(row, MODULE_COLUMN_MAP, "module_name")
        pname = get_col(row, MODULE_COLUMN_MAP, "programme_name")

        if not code or not name:
            skipped += 1
            continue

        prog_id = programme_id_map.get(pname)
        if prog_id is None:
            print(f"  WARNING: programme '{pname}' not found for module {code} — skipping")
            skipped += 1
            continue

        prereqs = get_col(row, MODULE_COLUMN_MAP, "prerequisites")
        medium  = get_col(row, MODULE_COLUMN_MAP, "medium_of_instruction")
        credits = get_col(row, MODULE_COLUMN_MAP, "credits")
        hours   = get_col(row, MODULE_COLUMN_MAP, "contact_hours")

        try:
            conn.execute(
                """INSERT INTO modules
                   (module_code, module_name, programme_id, prerequisites,
                    medium_of_instruction, credits, contact_hours)
                   VALUES (?,?,?,?,?,?,?)""",
                (code, name, prog_id, prereqs, medium, int(float(credits)), hours),
            )
            imported += 1
        except sqlite3.IntegrityError:
            print(f"  WARNING: duplicate module code '{code}' — skipping")
            skipped += 1

    conn.commit()
    conn.close()

    print(f"  {imported} module(s) imported, {skipped} skipped")
    print("Done. Restart the Flask app to use the new data.")


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python backend/import_excel.py path/to/data.xlsx")
        sys.exit(1)
    excel_path = sys.argv[1]
    if not os.path.exists(excel_path):
        print(f"File not found: {excel_path}")
        sys.exit(1)
    import_data(excel_path)
