"""Prepare the official MPU module-outline files for ``docxtpl``.

The English and Chinese sources are DOCX files. The official Portuguese source
is a legacy DOC file and must first be exported to DOCX by Microsoft Word or
Pages; converting it with ``textutil`` flattens the tables and is not suitable.

Run from the repository root::

    python backend/convert_template.py \
      --source-dir "Module Outline Templates" \
      --pt-docx "Module Outline Templates/module-outline-template_pt_202305.docx"

When only the English and Chinese official templates changed, preserve the
existing Portuguese runtime template with ``--skip-pt``.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt


BASE_DIR = Path(__file__).resolve().parent
DEFAULT_SOURCE_DIR = BASE_DIR.parent / "Module Outline Templates"
DEFAULT_OUTPUT_DIR = BASE_DIR / "templates"
ASSESSMENT_URL = "https://www.mpu.edu.mo/en/teaching-and-learning-centre/quality-framework/student_assessment_and_examinations/assessment_strategy"
HANDBOOK_URL = "https://mpusite.mpu.edu.mo/studenthandbook/"


def _preserve_current_assessment_sources(document, language: str) -> None:
    """Carry forward the approved EN/ZH wording and links when preparing sources."""
    if language not in ("en", "zh"):
        return
    prefix = "The assessment will be conducted" if language == "en" else "有關考評標準按大學"
    wording = {
        "en": f"The assessment will be conducted following the University’s Assessment Strategy (see {ASSESSMENT_URL}). Passing this learning module indicates that students will have attained the ILOs of this learning module and thus acquired its credits.",
        "zh": f"有關考評標準按大學的學生考評與評分準則指引進行（詳見{ASSESSMENT_URL})。學生成績合格表示其達到本學科單元/科目的預期學習成效，因而取得相應學分。",
    }
    for paragraph in document.paragraphs:
        _replace_visible_pattern(paragraph, r"(?:https?://)?www\.mpu\.edu\.mo/teaching_learning/(?:en|zh)/assessment_strategy\.php", ASSESSMENT_URL)
        _replace_visible_pattern(paragraph, r"(?:https?://)?www\.mpu\.edu\.mo/student_handbook/", HANDBOOK_URL)
        if paragraph.text.strip().startswith(prefix):
            if language == "zh":
                _replace_visible_pattern(paragraph, "（詳見 +", "（詳見")
            if paragraph.text.strip() != wording[language]:
                raise ValueError("Unrecognized assessment wording; administrator review is required")
    for rel in document.part.rels.values():
        if rel.is_external:
            if "assessment_strategy" in rel.target_ref:
                rel._target = ASSESSMENT_URL
            elif "student_handbook" in rel.target_ref:
                rel._target = HANDBOOK_URL


def _replace_visible_pattern(paragraph, pattern: str, replacement: str) -> None:
    """Replace visible text across runs, preserving hyperlinks and run properties."""
    nodes = paragraph._p.xpath(".//w:t")
    visible = "".join(node.text or "" for node in nodes)
    for match in reversed(list(re.finditer(pattern, visible))):
        cursor = 0
        for node in nodes:
            text = node.text or ""
            end = cursor + len(text)
            if end > match.start() and cursor < match.end():
                before = text[:max(0, match.start() - cursor)]
                after = text[max(0, match.end() - cursor):]
                node.text = before + (replacement if cursor <= match.start() else "") + after
            cursor = end


def _replace_paragraph_text(paragraph, old: str, new: str) -> bool:
    """Replace text spanning runs while retaining the first run's formatting."""
    if old not in paragraph.text:
        return False
    replacement = paragraph.text.replace(old, new)
    if paragraph.runs:
        paragraph.runs[0].text = replacement
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(replacement)
    return True


def _set_paragraph_text(paragraph, text: str) -> None:
    """Replace visible runs without rebuilding the paragraph or its properties."""
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)
    for hyperlink in paragraph._p.findall("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}hyperlink"):
        paragraph._p.remove(hyperlink)


def _set_cell_text(table, row: int, col: int, text: str) -> None:
    """Replace a value cell while preserving cell and first-run formatting."""
    cell = table.cell(row, col)
    _set_paragraph_text(cell.paragraphs[0], text)
    for extra in cell.paragraphs[1:]:
        _set_paragraph_text(extra, "")


def _fill_metadata_table(table, value_columns: tuple[int, int]) -> None:
    left_value, right_value = value_columns
    mapping = {
        (0, left_value): "{{ academic_year }}",
        (0, right_value): "{{ semester }}",
        (1, left_value): "{{ module_code }}",
        (2, left_value): "{{ module_name }}",
        (3, left_value): "{{ prerequisites }}",
        (4, left_value): "{{ medium_of_instruction }}",
        (5, left_value): "{{ credits }}",
        (5, right_value): "{{ contact_hours }}",
        (6, left_value): "{{ instructor }}",
        (6, right_value): "{{ email }}",
        (7, left_value): "{{ office }}",
        (7, right_value): "{{ office_phone }}",
    }
    for (row, col), placeholder in mapping.items():
        _set_cell_text(table, row, col, placeholder)


def _format_portuguese_metadata_table(table) -> None:
    """Make the compact PT metadata rows render consistently in Word.

    The Portuguese source is a legacy Word document. Its label paragraphs and
    the value paragraphs created for Jinja placeholders use different styles,
    so relying on inherited spacing can make otherwise centered text appear
    top-heavy in Microsoft Word. Limit the normalization to the first metadata
    table: the larger lecturer-editable tables retain their official layout.
    """
    seen_cells = set()
    for row in table.rows:
        for cell in row.cells:
            if cell._tc in seen_cells:
                continue
            seen_cells.add(cell._tc)
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            for paragraph in cell.paragraphs:
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.0


def _convert_common(
    src: Path,
    dst: Path,
    header_placeholders: tuple[tuple[str, str], ...],
    required_headers: tuple[str, ...],
    attendance_prefix: str,
    marking_placeholder: str,
    lecturer_placeholders: tuple[str, ...],
    value_columns: tuple[int, int],
    language: str,
) -> None:
    document = Document(src)
    if len(document.tables) != 6:
        raise ValueError(f"{src.name}: expected 6 tables, found {len(document.tables)}")
    metadata = document.tables[0]
    allowed_columns = (4, 5) if language == "pt" else (4,)
    if len(metadata.rows) != 8 or len(metadata.columns) not in allowed_columns:
        raise ValueError(f"{src.name}: expected an 8-row metadata table with 4 or 5 columns")
    anchors = {
        "Attendance requirements are governed": ("Academic Year", "Module Code", "Learning Module", "Pre-requisite(s)", "Medium of Instruction", "Credits", "Instructor", "Office"),
        "考勤要求按澳門理工大學": ("學年", "學科單元/科目編號", "學科單元/科目名稱", "先修要求", "授課語言", "學分", "教師姓名", "辦公室"),
        "Os requisitos de assiduidade são cumpridos": ("Ano lectivo", "Código da unidade curricular", "Nome da unidade curricular", "Pré-requisitos", "Língua veicular", "Créditos", "Nome de docente", "Gabinete"),
    }
    for row, label in enumerate(anchors[attendance_prefix]):
        if metadata.cell(row, 0).text.strip().casefold() != label.casefold():
            raise ValueError(f"{src.name}: metadata row {row + 1} must be '{label}'")
    right_labels = {
        "en": ((0, "Semester"), (5, "Contact Hours"), (6, "Email"), (7, "Office Phone")),
        "zh": ((0, "學期"), (5, "面授學時"), (6, "電郵"), (7, "辦公室電話")),
        "pt": ((0, "Semestre"), (5, "Horas lectivas presenciais"), (6, "E-mail"), (7, "N.º de contacto")),
    }
    for row, label in right_labels[language]:
        if metadata.cell(row, value_columns[1] - 1).text.strip().casefold() != label.casefold():
            raise ValueError(f"{src.name}: metadata row {row + 1} must contain '{label}'")

    replacements_found = {target: False for target in required_headers}
    attendance_found = False
    marking_found = False

    for paragraph in document.paragraphs:
        for source, target in header_placeholders:
            if _replace_paragraph_text(paragraph, source, target):
                replacements_found[target] = True

        stripped = paragraph.text.strip()
        if stripped.startswith(attendance_prefix):
            _set_paragraph_text(paragraph, "{{ attendance_text }}")
            attendance_found = True
        elif marking_placeholder in stripped:
            _set_paragraph_text(paragraph, "__MARKING_RULE_BLOCK__")
            paragraph.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.LEFT
            marking_found = True
        elif stripped in lecturer_placeholders:
            # Retain the official paragraph/style as an editable Word slot, but
            # do not ship instructional placeholder text as lecturer content.
            _set_paragraph_text(paragraph, "")

    missing = [key for key, found in replacements_found.items() if not found]
    if missing or not attendance_found or not marking_found:
        raise ValueError(
            f"{src.name}: required template slots not found "
            f"(headers={missing}, attendance={attendance_found}, marking={marking_found})"
        )

    _fill_metadata_table(document.tables[0], value_columns)
    if language == "pt":
        _format_portuguese_metadata_table(document.tables[0])
    _preserve_current_assessment_sources(document, language)
    dst.parent.mkdir(parents=True, exist_ok=True)
    document.save(dst)


def convert_template(src: Path, dst: Path, language: str) -> None:
    """Prepare one official DOCX using the same logic for CLI and web uploads."""
    if language == "en":
        _convert_common(
            src,
            dst,
            (("[Name of academic unit]", "{{ academic_unit }}"),
             ("[Programme name]", "{{ programme_name }}")),
            ("{{ academic_unit }}", "{{ programme_name }}"),
            "Attendance requirements are governed",
            "[Insert marking scheme]",
            ("[insert text]",),
            (1, 3),
            "en",
        )
    elif language == "zh":
        _convert_common(
            src,
            dst,
            (("[學術單位名稱]", "{{ academic_unit }}"),
             ("[課程名稱]", "{{ programme_name }}")),
            ("{{ academic_unit }}", "{{ programme_name }}"),
            "考勤要求按澳門理工大學",
            "[插入評分準則]",
            ("[插入概述]", "[插入書單]", "[插入參考文獻]"),
            (1, 3),
            "zh",
        )
    elif language == "pt":

        pt_document = Document(src)
        pt_columns = len(pt_document.tables[0].columns) if pt_document.tables else 0
        if pt_columns == 5:
            pt_value_columns = (1, 4)
        elif pt_columns == 4:
            pt_value_columns = (1, 3)
        else:
            raise ValueError(
                f"{src.name}: expected 4 or 5 metadata columns, found {pt_columns}"
            )

        _convert_common(
            src,
            dst,
            (("[nome da unidade académica]", "{{ academic_unit }}"),
             ("[NOME DA UNIDADE ACADÉMICA]", "{{ academic_unit }}"),
             ("[designação do curso]", "{{ programme_name }}"),
             ("[DESIGNAÇÃO DO CURSO]", "{{ programme_name }}")),
            ("{{ academic_unit }}", "{{ programme_name }}"),
            "Os requisitos de assiduidade são cumpridos",
            "[Inserir o critério de classificação]",
            ("[Caracterização]", "[Inserir a bibliografia]", "[Inserir as referências]"),
            pt_value_columns,
            "pt",
        )
    else:
        raise ValueError(f"Unsupported template language: {language}")


def convert_templates(source_dir: Path, output_dir: Path, pt_docx: Path | None) -> None:
    sources = {
        "en": source_dir / "module-outline-template_en_202305.docx",
        "zh": source_dir / "module-outline-template_zh_202305.docx",
    }
    if pt_docx is not None:
        sources["pt"] = pt_docx
    for source in sources.values():
        if not source.is_file():
            raise FileNotFoundError(source)
    for language, source in sources.items():
        convert_template(source, output_dir / f"template_{language}.docx", language)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--pt-docx",
        type=Path,
        default=DEFAULT_SOURCE_DIR / "module-outline-template_pt_202305.docx",
        help="Faithful DOCX export of the official Portuguese .doc file",
    )
    parser.add_argument(
        "--skip-pt",
        action="store_true",
        help="Regenerate only English and Chinese; leave template_pt.docx untouched",
    )
    args = parser.parse_args()
    pt_docx = None if args.skip_pt else args.pt_docx.resolve()
    convert_templates(args.source_dir.resolve(), args.output_dir.resolve(), pt_docx)
    print(f"Templates written to {args.output_dir.resolve()}")


if __name__ == "__main__":
    main()
