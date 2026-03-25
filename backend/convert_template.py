"""
convert_template.py
-------------------
Reads the original Word templates (EN, ZH, PT) and inserts docxtpl / Jinja2
placeholder tags into the appropriate cells and paragraphs so that docxtpl
can render them at runtime.

Run once:
    python convert_template.py

Produces:
    backend/templates/template_en.docx
    backend/templates/template_zh.docx
    backend/templates/template_pt.docx
"""

import os
import subprocess
from docx import Document

BASE_DIR = os.path.dirname(__file__)
SRC_DIR = os.path.join(BASE_DIR, "..", "Module Outline Templates")
DST_DIR = os.path.join(BASE_DIR, "templates")


def set_cell_text(table, row, col, text):
    """Replace the text of a table cell while keeping the first run's formatting."""
    cell = table.cell(row, col)
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.text = ""
    p = cell.paragraphs[0]
    if p.runs:
        p.runs[0].text = text
    else:
        p.add_run(text)


def replace_para_text(paragraph, old, new):
    """Replace text across runs in a paragraph (handles split runs)."""
    full = paragraph.text
    if old not in full:
        return
    new_full = full.replace(old, new)
    if paragraph.runs:
        paragraph.runs[0].text = new_full
        for run in paragraph.runs[1:]:
            run.text = ""


def set_para_text(paragraph, text):
    """Replace all text in a paragraph."""
    if paragraph.runs:
        paragraph.runs[0].text = text
        for run in paragraph.runs[1:]:
            run.text = ""
    else:
        paragraph.add_run(text)


# ── EN template ──────────────────────────────────────────────────────────────
def convert_en():
    src = os.path.join(SRC_DIR, "module-outline-template_en_202305.docx")
    dst = os.path.join(DST_DIR, "template_en.docx")
    doc = Document(src)

    for para in doc.paragraphs:
        replace_para_text(para, "[Name of academic unit]", "{{ academic_unit }}")
        replace_para_text(para, "[Programme name]", "{{ programme_name }}")
        replace_para_text(para, "[Doctoral/Master\u2019s/Bachelor\u2019s]", "{{ degree_level }}")
        replace_para_text(para, "[Doctoral/Master's/Bachelor's]", "{{ degree_level }}")

    t0 = doc.tables[0]
    set_cell_text(t0, 0, 1, "{{ academic_year }}")
    set_cell_text(t0, 0, 3, "{{ semester }}")
    set_cell_text(t0, 1, 1, "{{ module_code }}")
    set_cell_text(t0, 2, 1, "{{ module_name }}")
    set_cell_text(t0, 3, 1, "{{ prerequisites }}")
    set_cell_text(t0, 4, 1, "{{ medium_of_instruction }}")
    set_cell_text(t0, 5, 1, "{{ credits }}")
    set_cell_text(t0, 5, 3, "{{ contact_hours }}")
    set_cell_text(t0, 6, 1, "{{ instructor }}")
    set_cell_text(t0, 6, 3, "{{ email }}")
    set_cell_text(t0, 7, 1, "{{ office }}")
    set_cell_text(t0, 7, 3, "{{ office_phone }}")

    doc.save(dst)
    print(f"  EN  -> {dst}")


# ── ZH template ──────────────────────────────────────────────────────────────
def convert_zh():
    src = os.path.join(SRC_DIR, "module-outline-template_zh_202305.docx")
    dst = os.path.join(DST_DIR, "template_zh.docx")
    doc = Document(src)

    for para in doc.paragraphs:
        replace_para_text(para, "[學術單位名稱]", "{{ academic_unit }}")
        replace_para_text(para, "[課程名稱]", "{{ programme_name }}")
        replace_para_text(para, "[博士/碩士/學士]", "{{ degree_level }}")

    t0 = doc.tables[0]
    set_cell_text(t0, 0, 1, "{{ academic_year }}")
    set_cell_text(t0, 0, 3, "{{ semester }}")
    set_cell_text(t0, 1, 1, "{{ module_code }}")
    set_cell_text(t0, 2, 1, "{{ module_name }}")
    set_cell_text(t0, 3, 1, "{{ prerequisites }}")
    set_cell_text(t0, 4, 1, "{{ medium_of_instruction }}")
    set_cell_text(t0, 5, 1, "{{ credits }}")
    set_cell_text(t0, 5, 3, "{{ contact_hours }}")
    set_cell_text(t0, 6, 1, "{{ instructor }}")
    set_cell_text(t0, 6, 3, "{{ email }}")
    set_cell_text(t0, 7, 1, "{{ office }}")
    set_cell_text(t0, 7, 3, "{{ office_phone }}")

    doc.save(dst)
    print(f"  ZH  -> {dst}")


# ── PT template ──────────────────────────────────────────────────────────────
def convert_pt():
    """Build the PT template by cloning the EN template's table structure and
    replacing English labels with Portuguese ones.  The original .doc template
    lost its table when converted to .docx via textutil, so we use the EN
    template as the structural base."""
    src_en = os.path.join(DST_DIR, "template_en.docx")
    dst = os.path.join(DST_DIR, "template_pt.docx")
    doc = Document(src_en)

    # ── Header paragraphs (centred, bold) ────────────────────────────
    for para in doc.paragraphs:
        replace_para_text(para, "learning MOdule Outline", "PROGRAMA DE UNIDADE CURRICULAR")
        replace_para_text(para, "MOdule Description", "Descrição da Unidade Curricular")

    # ── Table 0: field labels (PT) ───────────────────────────────────
    t0 = doc.tables[0]
    pt_labels = {
        (0, 0): "Ano lectivo",
        (0, 2): "Semestre",
        (1, 0): "Código da unidade curricular",
        (2, 0): "Nome da unidade curricular",
        (3, 0): "Pré-requisitos",
        (4, 0): "Língua veicular",
        (5, 0): "Créditos",
        (5, 2): "Horas lectivas presenciais",
        (6, 0): "Nome de docente",
        (6, 2): "E-mail",
        (7, 0): "Gabinete",
        (7, 2): "N.º de contacto",
    }
    for (row, col), label in pt_labels.items():
        set_cell_text(t0, row, col, label)

    # ── Remaining section headings & body text ────────────────────────
    pt_replacements = {
        "[insert text]": "[Caracterização]",
        "module Intended Learning outcomes (ILOS)": "RESULTADOS DE ESTUDO PREVISTOS DA UNIDADE CURRICULAR / DISCIPLINA",
        "On completion of this learning module, students will be able to:":
            "Concluída esta unidade curricular / disciplina, os alunos vão atingir os seguintes resultados de estudo previstos:",
        "These ILOs aims to enable students to attain the following Programme Intended Learning Outcomes (PILOs):":
            "Os resultados de estudo previstos contribuem para os alunos obterem os seguintes objetivos previstos para o Curso do estudo:",
        "Module SCHEDULE, Coverage and study load": "Calendário, Conteúdo e Carga de Estudo",
        "Teaching and learning activities": "Actividades de Ensino e Aprendizagem",
        "In this learning module, students will work towards attaining the ILOs through the following teaching and learning activities:":
            "Nesta unidade curricular, os alunos trabalharão para atingir os resultados de estudo através das seguintes actividades de ensino e aprendizagem:",
        "Attendance": "Assiduidade",
        "Assessment": "Avaliação",
        "In this learning module, students are required to complete the following assessment activities:":
            "Nesta unidade curricular, os alunos devem completar as seguintes actividades de avaliação:",
        "Marking scheme": "Grelha de Avaliação",
        "[Insert marking scheme]": "[Inserir grelha de avaliação]",
        "Required readings": "Leitura Obrigatória",
        "References": "Referências",
        "Student Feedback": "Feedback dos Alunos",
        "Academic Integrity": "Integridade Académica",
    }
    for para in doc.paragraphs:
        for en_text, pt_text in pt_replacements.items():
            if para.text.strip() == en_text:
                set_para_text(para, pt_text)
                break

    # ── Longer body paragraphs (replace entire text by start phrase) ──
    pt_long = {
        "Attendance requirements are governed":
            "Os requisitos de assiduidade são regidos pelo Regulamento Académico dos Programas de Grau de {{ degree_level }} da Universidade Politécnica de Macau. Os alunos que não cumpram os requisitos de assiduidade da unidade curricular receberão a classificação 'F'.",
        "The assessment will be conducted":
            "A avaliação será conduzida de acordo com a Estratégia de Avaliação da Universidade (consultar www.mpu.edu.mo/teaching_learning/en/assessment_strategy.php). A aprovação nesta unidade curricular indica que os alunos atingiram os resultados de estudo previstos e, assim, obtiveram os respetivos créditos.",
        "At the end of every semester":
            "No final de cada semestre, os alunos são convidados a dar feedback sobre a unidade curricular e a organização do ensino através de questionários. O seu feedback é importante para os docentes melhorarem a unidade curricular e a sua lecionação para futuros alunos. O docente e os coordenadores do curso irão considerar todo o feedback e responder com ações formalmente na revisão anual do curso.",
        "The Macao Polytechnic University requires":
            "A Universidade Politécnica de Macau exige que os alunos tenham pleno compromisso com a integridade académica na realização de actividades de investigação e académicas. Violações da integridade académica, que incluem, mas não se limitam a plágio, conluio, fabricação ou falsificação, reutilização de trabalhos e fraude em exames, são consideradas infrações académicas graves e podem levar a ações disciplinares. Os alunos devem ler os regulamentos e orientações relevantes no Manual do Estudante, que é distribuído aquando da admissão na Universidade, e cuja cópia também pode ser encontrada em www.mpu.edu.mo/student_handbook/.",
    }
    for para in doc.paragraphs:
        for start_phrase, pt_text in pt_long.items():
            if para.text.strip().startswith(start_phrase):
                set_para_text(para, pt_text)
                break

    doc.save(dst)
    print(f"  PT  -> {dst}")


def main():
    os.makedirs(DST_DIR, exist_ok=True)
    convert_en()
    convert_zh()
    convert_pt()
    print("Done.")


if __name__ == "__main__":
    main()
