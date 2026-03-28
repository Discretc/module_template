"""
generator.py
------------
Generates module-outline Word documents in all three languages (EN, ZH, PT)
using docxtpl.  Supports batch generation for multiple classes, outputting
all files into a folder and optionally returning a zip archive.
"""

import io
import os
import zipfile
from datetime import datetime
from docxtpl import DocxTemplate

TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "output")

TEMPLATES = {
    "en": os.path.join(TEMPLATE_DIR, "template_en.docx"),
    "zh": os.path.join(TEMPLATE_DIR, "template_zh.docx"),
    "pt": os.path.join(TEMPLATE_DIR, "template_pt.docx"),
}

DEGREE_LABELS = {
    "doctoral": {"en": "Doctoral",  "zh": "博士", "pt": "Doutor"},
    "master":   {"en": "Master's",  "zh": "碩士", "pt": "Mestre"},
    "bachelor": {"en": "Bachelor's", "zh": "學士", "pt": "Licenciado"},
}

LANG_SUFFIXES = {"en": "EN", "zh": "ZH", "pt": "PT"}

# ── Marking-scheme rule text per language ────────────────────────────────────
# Rule 1 = no text; Rule 2 = final<35 resit; Rule 3 = cw+final<35 resit; Rule 4 = cw+final<35 fail
MARKING_RULES = {
    2: {
        "en": (
            "Students with a score of less than 35 in the final examination must take the "
            "resit examination even if the overall score for the learning module is 50 or above."
        ),
        "zh": "若學生期末考試分數為35分以下，即使其總分達50分或以上，學生必須參加補考。",
        "pt": (
            "Qualquer aluno que obtenha menos de 35% no exame final terá de se submeter ao "
            "exame suplementar, independentemente da nota final."
        ),
    },
    3: {
        "en": (
            "Students with an overall score of less than 35 in the coursework must take the "
            "resit examination even if the overall score for the module is 50 or above.\n\n"
            "Students with a score of less than 35 in the final examination must take the "
            "resit examination even if the overall score for the module is 50 or above.\n\n"
            "Students with an overall final grade of less than 35 are NOT allowed to take the resit examination."
        ),
        "zh": (
            "若學生總體平時分數為35分以下，即使其總分達50分或以上，學生必須參加補考。\n\n"
            "若學生期末考試分數為35分以下，即使其總分達50分或以上，學生必須參加補考。\n\n"
            "若學生總成績為35分以下，學生不能參加補考。"
        ),
        "pt": (
            "Qualquer aluno que obtenha menos de 35% na avaliação contínua terá de se submeter ao "
            "exame suplementar, independentemente da nota final.\n\n"
            "Qualquer aluno que obtenha menos de 35% no exame final terá de se submeter ao "
            "exame suplementar, independentemente da nota final.\n\n"
            "Qualquer aluno que obtenha menos de 35% no nota final não pode realizar o exame suplementar."
        ),
    },
    4: {
        "en": (
            "Students with an overall score of less than 35 in the coursework will fail the module "
            "even if the overall score for the module is 50 or above.\n\n"
            "Students with a score of less than 35 in the final examination will fail the module "
            "even if the overall score for the module is 50 or above."
        ),
        "zh": (
            "若學生總體平時分數為35分以下，即使其總分達50分或以上，學科單元之成績作不及格處理。\n\n"
            "若學生期末考試分數為35分以下，即使其總分達50分或以上，學科單元之成績作不及格處理。"
        ),
        "pt": (
            "Qualquer aluno que obtenha menos de 35% na avaliação contínua vai reprovar ao módulo, "
            "independentemente da nota final.\n\n"
            "Qualquer aluno que obtenha menos de 35% no exame final vai reprovar ao módulo, "
            "independentemente da nota final."
        ),
    },
}


def _build_context(cls: dict, lang: str) -> dict:
    """Build the Jinja2 context dict for a single class + language."""
    degree_key = cls.get("degree_level", "bachelor")
    degree_label = DEGREE_LABELS.get(degree_key, DEGREE_LABELS["bachelor"])[lang]

    duration = cls.get("duration")
    contact_hours = f"{duration} hrs" if duration else ""

    marking_rule = cls.get("marking_rule", 1) or 1
    marking_text = ""
    if marking_rule in MARKING_RULES:
        marking_text = MARKING_RULES[marking_rule].get(lang, "")

    if lang == "en":
        return {
            "academic_unit": cls.get("faculty_en", ""),
            "programme_name": cls.get("prog_name_en", ""),
            "degree_level": degree_label,
            "module_code": cls.get("module_code", ""),
            "module_name": cls.get("module_name_en", ""),
            "prerequisites": cls.get("prerequisite_en", "") or "Nil",
            "medium_of_instruction": cls.get("medium_of_instruction", "English"),
            "credits": str(cls.get("credits", "")),
            "contact_hours": contact_hours,
            "academic_year": cls.get("academic_year", ""),
            "semester": cls.get("semester", ""),
            "instructor": cls.get("instructor_en", ""),
            "email": cls.get("email", ""),
            "office": cls.get("room_en", ""),
            "office_phone": cls.get("telephone", ""),
            "marking_scheme_text": marking_text,
        }
    elif lang == "zh":
        return {
            "academic_unit": cls.get("faculty_zh", "") or cls.get("faculty_en", ""),
            "programme_name": cls.get("prog_name_zh", "") or cls.get("prog_name_en", ""),
            "degree_level": degree_label,
            "module_code": cls.get("module_code", ""),
            "module_name": cls.get("module_name_zh", "") or cls.get("module_name_en", ""),
            "prerequisites": cls.get("prerequisite_zh", "") or cls.get("prerequisite_en", "") or "Nil",
            "medium_of_instruction": cls.get("medium_of_instruction", "English"),
            "credits": str(cls.get("credits", "")),
            "contact_hours": contact_hours,
            "academic_year": cls.get("academic_year", ""),
            "semester": cls.get("semester", ""),
            "instructor": cls.get("instructor_zh", "") or cls.get("instructor_en", ""),
            "email": cls.get("email", ""),
            "office": cls.get("room_zh", "") or cls.get("room_en", ""),
            "office_phone": cls.get("telephone", ""),
            "marking_scheme_text": marking_text,
        }
    else:  # pt
        return {
            "academic_unit": cls.get("faculty_pt", "") or cls.get("faculty_en", ""),
            "programme_name": cls.get("prog_name_pt", "") or cls.get("prog_name_en", ""),
            "degree_level": degree_label,
            "module_code": cls.get("module_code", ""),
            "module_name": cls.get("module_name_pt", "") or cls.get("module_name_en", ""),
            "prerequisites": cls.get("prerequisite_pt", "") or cls.get("prerequisite_en", "") or "Nil",
            "medium_of_instruction": cls.get("medium_of_instruction", "English"),
            "credits": str(cls.get("credits", "")),
            "contact_hours": contact_hours,
            "academic_year": cls.get("academic_year", ""),
            "semester": cls.get("semester", ""),
            "instructor": cls.get("instructor_pt", "") or cls.get("instructor_en", ""),
            "email": cls.get("email", ""),
            "office": cls.get("room_pt", "") or cls.get("room_en", ""),
            "office_phone": cls.get("telephone", ""),
            "marking_scheme_text": marking_text,
        }


def _render_one(cls: dict, lang: str) -> bytes:
    """Render a single template and return the raw bytes."""
    tpl = DocxTemplate(TEMPLATES[lang])
    ctx = _build_context(cls, lang)
    tpl.render(ctx)
    buf = io.BytesIO()
    tpl.save(buf)
    return buf.getvalue()


def generate_batch(classes: list[dict], academic_year: str = "", semester: str = "") -> io.BytesIO:
    """
    Generate EN/ZH/PT templates for every class in the list.
    Saves files to output/ folder and returns a zip archive as BytesIO.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    batch_dir = os.path.join(OUTPUT_DIR, f"generated_{timestamp}")
    os.makedirs(batch_dir, exist_ok=True)

    zip_buf = io.BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for cls in classes:
            # Inject academic_year/semester if provided
            if academic_year:
                cls["academic_year"] = academic_year
            if semester:
                cls["semester"] = semester

            class_code = cls.get("class_code", "UNKNOWN")
            for lang in ("en", "zh", "pt"):
                filename = f"{class_code}_Module_Outline_{LANG_SUFFIXES[lang]}.docx"
                doc_bytes = _render_one(cls, lang)

                # Save to disk
                filepath = os.path.join(batch_dir, filename)
                with open(filepath, "wb") as f:
                    f.write(doc_bytes)

                # Add to zip
                zf.writestr(filename, doc_bytes)

    zip_buf.seek(0)
    file_count = len(classes) * 3
    print(f"  Generated {file_count} file(s) -> {batch_dir}")
    return zip_buf
