"""Generate editable MPU module outlines from the official language templates."""

from __future__ import annotations

import io
import math
import os
import re
import zipfile
from copy import deepcopy
from contextlib import nullcontext
from datetime import datetime
from pathlib import Path

from docxtpl import DocxTemplate
from jinja2 import Environment, StrictUndefined
from lxml import etree

from class_records import instructors, prerequisites
from rules import JointRuleConflictError, get_rule_paragraphs, normalize_rule_code
from template_storage import configured_template_directory, template_lock


TEMPLATE_DIR = configured_template_directory(Path(__file__).resolve().parent / "templates")
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
    """Pair each row's localized name with its own code, retaining stable order."""
    values = []
    for record in prerequisites(cls):
        name_keys = tuple(key.replace("prerequisite_", "name_") for key in keys)
        name = _pick(record, *name_keys)
        code = _safe_text(record.get("prerequisite_code"))
        text = f"{name} ({code})" if name and code else name or code
        if text and text not in values:
            values.append(text)
    return ", ".join(values) or PREREQUISITE_DEFAULTS[lang]


def _teacher_context(cls: dict, lang: str) -> dict:
    records = instructors(cls)
    name_keys = (f"name_{lang}", "name_en", "name_zh", "name_pt")
    names = [_pick(record, *name_keys) for record in records]
    # Unique names in source order. Numbered owners keep contacts unambiguous
    # even when a room/email is shared or some teachers have missing contacts.
    identities = [("name", name) if name else ("contact", index)
                  for index, name in enumerate(names)]
    unique_owners = dict.fromkeys(identities)
    multiple = len(records) > 1
    labels = {owner: str(index + 1) for index, owner in enumerate(unique_owners)}
    instructor_text = "\n".join(
        f"{labels[owner]}. {name}".rstrip() if multiple else name
        for owner, name in dict(zip(identities, names)).items()
    )

    def contacts(*keys):
        owners = {}
        for record, identity in zip(records, identities):
            value = _pick(record, *keys)
            if not value:
                continue
            owner = labels[identity]
            if owner not in owners.setdefault(value, []):
                owners[value].append(owner)
        return "\n".join(
            f"[{', '.join(indices)}] {value}" if multiple else value
            for value, indices in owners.items()
        )

    return {
        "instructor": instructor_text,
        "email": contacts("email"),
        # Room_Chn wins in every language. Non-Chinese legacy values are only
        # used when no authoritative Chinese room value exists for that record.
        "office": contacts("room_zh", "room_en", "room_pt"),
        "office_phone": contacts("telephone"),
    }


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
        },
        "zh": {
            "academic_unit": ("faculty_zh", "faculty_en"),
            "programme_name": ("prog_name_zh", "prog_name_en"),
            "module_name": ("module_name_zh", "module_name_en"),
            "prerequisites": ("prerequisite_zh", "prerequisite_en"),
        },
        "pt": {
            "academic_unit": ("faculty_pt", "faculty_en"),
            "programme_name": ("prog_name_pt", "prog_name_en"),
            "module_name": ("module_name_pt", "module_name_en"),
            "prerequisites": ("prerequisite_pt", "prerequisite_en"),
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
        "medium_of_instruction": {"en": "English", "zh": "中文", "pt": "Português"}[lang],
        "credits": _safe_text(cls.get("credits")),
        "contact_hours": _safe_text(cls.get("duration")),
        "academic_year": _safe_text(cls.get("academic_year")),
        "semester": _safe_text(cls.get("semester")),
        **_teacher_context(cls, lang),
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
        if archive.testzip():
            raise ValueError("Rendered document has corrupt ZIP content")
        for name in archive.namelist():
            if name.endswith((".xml", ".rels")):
                etree.fromstring(archive.read(name), parser=etree.XMLParser(resolve_entities=False, no_network=True))
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


def _render_one(cls: dict, lang: str, template_path: Path | None = None) -> bytes:
    paragraphs = get_marking_rule_paragraphs(_class_rule_code(cls), lang)
    # Explicit paths are private staged validation copies, not the active set.
    with (nullcontext() if template_path is not None else template_lock(TEMPLATE_DIR)):
        template = DocxTemplate(str(template_path or TEMPLATES[lang]))
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
    """Package each output member independently using its shared joint content."""
    # Validate the entire selection before writing any output. A joint conflict
    # must block all members, including when repeated groups were supplied.
    packages = {}
    filenames = {}
    for source in classes:
        _class_rule_code(source)
        codes = source.get("class_codes") or [_safe_text(source.get("class_code"))]
        codes = list(dict.fromkeys(_safe_text(code) for code in codes))
        output_codes = source.get("output_class_codes", codes)
        output_codes = list(dict.fromkeys(_safe_text(code) for code in output_codes))
        if not output_codes or any(code not in codes for code in output_codes):
            raise ValueError("Output members must belong to the joint content group")
        cls = dict(source)
        cls.pop("output_class_codes", None)
        cls["class_code"] = ", ".join(codes)
        if academic_year:
            cls["academic_year"] = academic_year
        if semester:
            cls["semester"] = semester
        for code in output_codes:
            filename = _safe_filename_component(code)
            if filename.casefold() in filenames and filenames[filename.casefold()] != code:
                raise ValueError(f"Class codes produce the same package filename: {code}")
            filenames[filename.casefold()] = code
            if code in packages and packages[code] != cls:
                raise ValueError(f"Conflicting output data for class code: {code}")
            packages[code] = cls

    root = Path(output_dir) if output_dir is not None else OUTPUT_DIR
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    batch_dir = root / f"generated_{timestamp}"
    batch_dir.mkdir(parents=True, exist_ok=False)

    zip_buffer = io.BytesIO()
    with template_lock(TEMPLATE_DIR), zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for code, cls in sorted(packages.items()):
            class_code = _safe_filename_component(code)
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w", zipfile.ZIP_DEFLATED) as package:
                for lang in ("en", "zh", "pt"):
                    filename = f"{class_code}_{LANG_SUFFIXES[lang]}.docx"
                    doc_bytes = _render_one(cls, lang)
                    (batch_dir / filename).write_bytes(doc_bytes)
                    package.writestr(filename, doc_bytes)
            package_name = f"{class_code}.zip"
            (batch_dir / package_name).write_bytes(inner.getvalue())
            archive.writestr(package_name, inner.getvalue())

    zip_buffer.seek(0)
    return zip_buffer


def batch_download_name(academic_year: str = "", semester: str = "") -> str:
    year = _safe_filename_component(academic_year) if academic_year else "unspecified_year"
    term = _safe_filename_component(semester) if semester else "unspecified"
    return f"module_outlines_{year}_sem{term}.zip"
