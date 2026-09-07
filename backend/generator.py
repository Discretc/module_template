"""Generate editable MPU module outlines from the official language templates."""

from __future__ import annotations

import io
import math
import os
import re
import zipfile
from copy import deepcopy
from datetime import datetime
from pathlib import Path

from docxtpl import DocxTemplate
from jinja2 import Environment, StrictUndefined
from lxml import etree

from rules import JointRuleConflictError, get_rule_paragraphs, normalize_rule_code


TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"

TEMPLATES = {
    "en": TEMPLATE_DIR / "template_en.docx",
    "zh": TEMPLATE_DIR / "template_zh.docx",
    "pt": TEMPLATE_DIR / "template_pt.docx",
}

DEGREE_LABELS = {
    "doctoral": {"en": "Doctoral", "zh": "博士", "pt": "Doutor"},
    "master": {"en": "Master’s", "zh": "碩士", "pt": "Mestre"},
    "bachelor": {"en": "Bachelor’s", "zh": "學士", "pt": "Licenciado"},
}

LANG_SUFFIXES = {"en": "EN", "zh": "ZH", "pt": "PT"}
LANGUAGE_LABELS = {"en": "English", "zh": "中文", "pt": "Português"}
STRICT_JINJA = Environment(undefined=StrictUndefined, autoescape=True)

GENERIC_MISSING = {"", "none", "nan", "null", "n/a", "na", "not applicable", "-", "--"}
PREREQUISITE_MISSING = GENERIC_MISSING | {
    "nil", "no prerequisite", "no prerequisites", "無", "没有", "沒有",
    "não tem", "nao tem", "sem pré-requisitos", "sem pre-requisitos",
}
PREREQUISITE_DEFAULTS = {"en": "Nil", "zh": "無", "pt": "Não tem"}
MARKING_RULE_MARKER = "__MARKING_RULE_BLOCK__"


def _safe_text(value) -> str:
    """Return display text without leaking ``None`` or floating-point NaN."""
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    text = str(value).replace("\xa0", " ").strip()
    return "" if text.casefold() in GENERIC_MISSING else text


def _pick(cls: dict, *keys: str) -> str:
    """Return the first non-empty known value, enabling language fallbacks."""
    for key in keys:
        value = _safe_text(cls.get(key))
        if value:
            return value
    return ""


def _attendance_text(degree_key: str, lang: str) -> str:
    degree = DEGREE_LABELS.get(degree_key, {}).get(lang)
    if lang == "en":
        regulation = (
            f"the Academic Regulations Governing {degree} Degree Programmes"
            if degree
            else "the applicable Academic Regulations"
        )
        return (
            f"Attendance requirements are governed by {regulation} of the Macao Polytechnic "
            "University. Students who do not meet the attendance requirements for the learning "
            "module shall be awarded an ‘F’ grade."
        )
    if lang == "zh":
        regulation = f"《{degree}學位課程教務規章》" if degree else "適用的教務規章"
        return (
            f"考勤要求按澳門理工大學{regulation}規定執行，未能達至要求者，"
            "本學科單元/科目成績將被評為不合格（“F”）。"
        )
    regulation = (
        f"«Regulamento Pedagógico dos Cursos Conferentes do Grau de {degree}»"
        if degree
        else "o regulamento pedagógico aplicável"
    )
    return (
        f"Os requisitos de assiduidade são cumpridos de acordo com {regulation}; para os alunos "
        "que não preenchem os requisitos, a classificação da respectiva unidade curricular será "
        "considerada com a menção de “f” (não aproveitamento)."
    )


def _prerequisite_text(cls: dict, lang: str, keys: tuple[str, ...]) -> str:
    """Localize missing prerequisites while retaining meaningful source values."""
    for key in keys:
        value = cls.get(key)
        if value is None or (isinstance(value, float) and math.isnan(value)):
            continue
        text = str(value).replace("\xa0", " ").strip()
        if text and text.casefold() not in PREREQUISITE_MISSING:
            return text
    return PREREQUISITE_DEFAULTS[lang]


def _class_rule_code(cls: dict) -> int:
    values = cls.get("rule_codes")
    if values is not None:
        if not isinstance(values, (list, tuple, set)):
            values = [values]
        normalized = [normalize_rule_code(value) for value in values]
        if len(set(normalized)) != 1:
            codes = list(cls.get("class_codes") or [])
            detail = ", ".join(
                f"{codes[index] if index < len(codes) else index + 1}=Rule {code}"
                for index, code in enumerate(normalized)
            )
            raise JointRuleConflictError(f"Joint class has conflicting Rule values: {detail}")
        return normalized[0]
    return normalize_rule_code(cls.get("rule_code"))


def get_marking_rule_paragraphs(rule_code, lang: str) -> tuple[str, ...]:
    """Return approved ordered rule statements for the selected document language."""
    return get_rule_paragraphs(rule_code, lang)


def _build_context(cls: dict, lang: str) -> dict:
    """Build a complete, null-safe context for one class and language."""
    if lang not in TEMPLATES:
        raise ValueError(f"Unsupported language: {lang}")

    degree_key = _safe_text(cls.get("degree_level")).lower()
    degree_label = DEGREE_LABELS.get(degree_key, {}).get(lang, "")

    language_fields = {
        "en": {
            "academic_unit": ("faculty_en",),
            "programme_name": ("prog_name_en",),
            "module_name": ("module_name_en",),
            "prerequisites": ("prerequisite_en",),
            "instructor": ("instructor_en",),
            "office": ("room_en",),
        },
        "zh": {
            "academic_unit": ("faculty_zh", "faculty_en"),
            "programme_name": ("prog_name_zh", "prog_name_en"),
            "module_name": ("module_name_zh", "module_name_en"),
            "prerequisites": ("prerequisite_zh", "prerequisite_en"),
            "instructor": ("instructor_zh", "instructor_en"),
            "office": ("room_zh", "room_en"),
        },
        "pt": {
            "academic_unit": ("faculty_pt", "faculty_en"),
            "programme_name": ("prog_name_pt", "prog_name_en"),
            "module_name": ("module_name_pt", "module_name_en"),
            "prerequisites": ("prerequisite_pt", "prerequisite_en"),
            "instructor": ("instructor_pt", "instructor_en"),
            "office": ("room_pt", "room_en"),
        },
    }[lang]

    return {
        "academic_unit": _pick(cls, *language_fields["academic_unit"]),
        "programme_name": _pick(cls, *language_fields["programme_name"]),
        "degree_level": degree_label,
        "attendance_text": _attendance_text(degree_key, lang),
        # The master workbook identifies offerings by the full Class_Code. For
        # joint classes this is the stable, ordered list produced by database.py.
        "module_code": _safe_text(cls.get("class_code")) or _safe_text(cls.get("module_code")),
        "module_name": _pick(cls, *language_fields["module_name"]),
        "prerequisites": _prerequisite_text(cls, lang, language_fields["prerequisites"]),
        # The authoritative workbook has no teaching-language column. The
        # confirmed display rule is therefore based on the generated version.
        "medium_of_instruction": LANGUAGE_LABELS[lang],
        "credits": _safe_text(cls.get("credits")),
        "contact_hours": _safe_text(cls.get("duration")),
        "academic_year": _safe_text(cls.get("academic_year")),
        "semester": _safe_text(cls.get("semester")),
        "instructor": _pick(cls, *language_fields["instructor"]),
        "email": _safe_text(cls.get("email")),
        "office": _pick(cls, *language_fields["office"]),
        "office_phone": _safe_text(cls.get("telephone")),
    }


def _insert_marking_rule_paragraphs(doc_bytes: bytes, paragraphs: tuple[str, ...]) -> bytes:
    """Replace the template marker with zero or more separate styled Word paragraphs."""
    source = io.BytesIO(doc_bytes)
    destination = io.BytesIO()
    with zipfile.ZipFile(source, "r") as archive, zipfile.ZipFile(destination, "w") as output:
        found = 0
        for info in archive.infolist():
            data = archive.read(info.filename)
            if info.filename == "word/document.xml":
                root = etree.fromstring(data)
                namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
                for text_node in root.xpath("//w:t[contains(., $marker)]", namespaces=namespace, marker=MARKING_RULE_MARKER):
                    paragraph = text_node.xpath("ancestor::w:p[1]", namespaces=namespace)[0]
                    parent = paragraph.getparent()
                    position = parent.index(paragraph)
                    for offset, statement in enumerate(paragraphs):
                        clone = deepcopy(paragraph)
                        clone_text_nodes = clone.xpath(".//w:t", namespaces=namespace)
                        marker_node = next(
                            node for node in clone_text_nodes if MARKING_RULE_MARKER in (node.text or "")
                        )
                        marker_node.text = (marker_node.text or "").replace(MARKING_RULE_MARKER, statement)
                        parent.insert(position + offset, clone)
                    parent.remove(paragraph)
                    found += 1
                data = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
            output.writestr(info, data)
    if found != 1:
        raise ValueError(f"Expected one marking-rule template marker, found {found}")
    return destination.getvalue()


def _validate_rendered_docx(doc_bytes: bytes) -> None:
    """Reject visible unresolved/template-error text before it reaches a download."""
    forbidden = (
        "{{", "}}", "{%", "%}", MARKING_RULE_MARKER,
        "[Doctoral/Master", "[博士/碩士/學士]", "[Doutor / Mestre",
    )
    with zipfile.ZipFile(io.BytesIO(doc_bytes)) as archive:
        visible_xml = b"\n".join(
            archive.read(name)
            for name in archive.namelist()
            if name.startswith("word/") and name.endswith(".xml")
        ).decode("utf-8", errors="ignore")
    matches = [token for token in forbidden if token in visible_xml]
    for bad_value in ("None", "NaN"):
        if re.search(rf">\s*{bad_value}\s*<", visible_xml, flags=re.IGNORECASE):
            matches.append(bad_value)
    if matches:
        raise ValueError(f"Rendered document contains unresolved text: {', '.join(matches)}")


def _render_one(cls: dict, lang: str) -> bytes:
    paragraphs = get_marking_rule_paragraphs(_class_rule_code(cls), lang)
    template = DocxTemplate(str(TEMPLATES[lang]))
    template.render(_build_context(cls, lang), jinja_env=STRICT_JINJA)
    buffer = io.BytesIO()
    template.save(buffer)
    doc_bytes = _insert_marking_rule_paragraphs(buffer.getvalue(), paragraphs)
    _validate_rendered_docx(doc_bytes)
    return doc_bytes


def _safe_filename_component(value) -> str:
    text = _safe_text(value) or "UNKNOWN"
    text = re.sub(r"\s*[,;]+\s*", "+", text)
    text = re.sub(r"[\\/:*?\"<>|\x00-\x1f]+", "_", text)
    text = re.sub(r"\s+", "_", text).strip("._")
    return text or "UNKNOWN"


def generate_batch(
    classes: list[dict],
    academic_year: str = "",
    semester: str = "",
    output_dir: str | os.PathLike | None = None,
) -> io.BytesIO:
    """Generate EN/ZH/PT documents and return them in a downloadable ZIP."""
    root = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    batch_dir = root / f"generated_{timestamp}"
    batch_dir.mkdir(parents=True, exist_ok=False)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for source_class in classes:
            cls = dict(source_class)
            if academic_year:
                cls["academic_year"] = academic_year
            if semester:
                cls["semester"] = semester

            class_code = _safe_filename_component(cls.get("class_code"))
            for lang in ("en", "zh", "pt"):
                filename = f"{class_code}_Module_Outline_{LANG_SUFFIXES[lang]}.docx"
                doc_bytes = _render_one(cls, lang)
                (batch_dir / filename).write_bytes(doc_bytes)
                archive.writestr(filename, doc_bytes)

    zip_buffer.seek(0)
    return zip_buffer
