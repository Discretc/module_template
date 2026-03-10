"""
convert_template.py
-------------------
Reads the original Word template and inserts docxtpl / Jinja2 placeholder tags
into the appropriate cells and paragraphs so that docxtpl can render them at
runtime.

Run once:
    python convert_template.py

Produces:  backend/templates/module_outline_template.docx
"""

import copy, os, sys
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT

SRC = os.path.join(
    os.path.dirname(__file__),
    "..",
    "Module Outline Templates",
    "module-outline-template_en_202305.docx",
)
DST = os.path.join(os.path.dirname(__file__), "templates", "module_outline_template.docx")


def set_cell_text(table, row, col, text):
    """Replace the text of a table cell while keeping the first run's formatting."""
    cell = table.cell(row, col)
    # Clear existing paragraphs
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.text = ""
    # Set text in first paragraph / first run (create run if needed)
    p = cell.paragraphs[0]
    if p.runs:
        p.runs[0].text = text
    else:
        run = p.add_run(text)


def replace_para_text(paragraph, old, new):
    """Replace text across runs in a paragraph (handles split runs)."""
    full = paragraph.text
    if old not in full:
        return
    new_full = full.replace(old, new)
    # Rebuild: put all text in first run, clear others
    if paragraph.runs:
        paragraph.runs[0].text = new_full
        for run in paragraph.runs[1:]:
            run.text = ""


def main():
    os.makedirs(os.path.dirname(DST), exist_ok=True)
    doc = Document(SRC)

    # --- Paragraph-level replacements ---
    for para in doc.paragraphs:
        # Header area
        replace_para_text(para, "[Name of academic unit]", "{{ academic_unit }}")
        replace_para_text(para, "[Programme name]", "{{ programme_name }}")

        # Attendance paragraph – replace the bracketed degree options
        replace_para_text(
            para,
            "[Doctoral/Master\u2019s/Bachelor\u2019s]",
            "{{ degree_level }}",
        )
        # Also handle straight-quote variant just in case
        replace_para_text(
            para,
            "[Doctoral/Master's/Bachelor's]",
            "{{ degree_level }}",
        )

    # --- Table 0: Module info header table ---
    t0 = doc.tables[0]
    # Row 0: Academic Year | [value] | Semester | [value]
    set_cell_text(t0, 0, 1, "{{ academic_year }}")
    set_cell_text(t0, 0, 3, "{{ semester }}")
    # Row 1: Module Code | [value]  (merged across cols 1-3)
    set_cell_text(t0, 1, 1, "{{ module_code }}")
    # Row 2: Learning Module
    set_cell_text(t0, 2, 1, "{{ module_name }}")
    # Row 3: Pre-requisite(s)
    set_cell_text(t0, 3, 1, "{{ prerequisites }}")
    # Row 4: Medium of Instruction
    set_cell_text(t0, 4, 1, "{{ medium_of_instruction }}")
    # Row 5: Credits | [value] | Contact Hours | [value]
    set_cell_text(t0, 5, 1, "{{ credits }}")
    set_cell_text(t0, 5, 3, "{{ contact_hours }}")
    # Row 6: Instructor | [value] | Email | [value]
    set_cell_text(t0, 6, 1, "{{ instructor }}")
    set_cell_text(t0, 6, 3, "{{ email }}")
    # Row 7: Office | [value] | Office Phone | [value]
    set_cell_text(t0, 7, 1, "{{ office }}")
    set_cell_text(t0, 7, 3, "{{ office_phone }}")

    doc.save(DST)
    print(f"✔  Template saved to {DST}")


if __name__ == "__main__":
    main()
