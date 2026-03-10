"""
generator.py
------------
Uses docxtpl to render the module-outline Word template
with data pulled from the database.
"""

import io
import os
from docxtpl import DocxTemplate

TEMPLATE_PATH = os.path.join(
    os.path.dirname(__file__), "templates", "module_outline_template.docx"
)


def generate_module_outline(module_data: dict) -> io.BytesIO:
    """
    Accept a dict of module fields, render the docxtpl template,
    and return the result as an in-memory BytesIO object (ready and
    suitable for streaming as a file download).

    *module_data* should contain at minimum:
        module_code, module_name, programme_name, degree_level,
        academic_unit, prerequisites, medium_of_instruction,
        credits, contact_hours

    Fields the lecturer will fill in later are left with safe defaults.
    """
    tpl = DocxTemplate(TEMPLATE_PATH)

    # Build the context – database fields + sensible defaults for
    # things the lecturer fills in manually after download.
    context = {
        # From the database
        "academic_unit": module_data.get("academic_unit", ""),
        "programme_name": module_data.get("programme_name", ""),
        "degree_level": module_data.get("degree_level", ""),
        "module_code": module_data.get("module_code", ""),
        "module_name": module_data.get("module_name", ""),
        "prerequisites": module_data.get("prerequisites", "Nil"),
        "medium_of_instruction": module_data.get("medium_of_instruction", "English"),
        "credits": str(module_data.get("credits", "")),
        "contact_hours": module_data.get("contact_hours", ""),
        # Defaults – lecturer fills these in
        "academic_year": module_data.get("academic_year", "2025/2026"),
        "semester": module_data.get("semester", ""),
        "instructor": module_data.get("instructor", ""),
        "email": module_data.get("email", ""),
        "office": module_data.get("office", ""),
        "office_phone": module_data.get("office_phone", ""),
    }

    tpl.render(context)

    buf = io.BytesIO()
    tpl.save(buf)
    buf.seek(0)
    return buf
