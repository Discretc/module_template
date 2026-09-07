"""Regenerate the committed visual-QA samples for all degrees and languages."""

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from generator import LANG_SUFFIXES, _render_one  # noqa: E402


OUTPUT_DIR = ROOT / "outputs" / "representative"

SAMPLES = {
    "bachelor": {
        "class_code": "COMP1123-121",
        "module_code": "COMP1123",
        "faculty_en": "Faculty of Applied Sciences",
        "faculty_zh": "應用科學學院",
        "faculty_pt": "Faculdade de Ciências Aplicadas",
        "prog_name_en": "Bachelor of Science in Computing",
        "prog_name_zh": "電腦學理學士學位課程",
        "prog_name_pt": "Licenciatura em Ciências da Computação",
        "module_name_en": "Computer Organization",
        "module_name_zh": "計算機組織",
        "module_name_pt": "Organização de Computadores",
        "prerequisite_en": "Nil",
        "prerequisite_zh": "無",
        "prerequisite_pt": "Nil",
        "instructor_en": "CHAN Tai Man",
        "instructor_zh": "陳大文",
        "instructor_pt": "CHAN Tai Man",
        "marking_rule": 2,
    },
    "master": {
        "class_code": "MSBD5001-131",
        "module_code": "MSBD5001",
        "faculty_en": "Faculty of Applied Sciences",
        "faculty_zh": "應用科學學院",
        "faculty_pt": "Faculdade de Ciências Aplicadas",
        "prog_name_en": "Master of Science in Data Engineering",
        "prog_name_zh": "數據工程理學碩士學位課程",
        "prog_name_pt": "Mestrado em Engenharia de Dados",
        "module_name_en": "Advanced Machine Learning",
        "module_name_zh": "高級機器學習",
        "module_name_pt": "Aprendizagem Automática Avançada",
        "prerequisite_en": "Nil",
        "prerequisite_zh": "無",
        "prerequisite_pt": "Nil",
        "instructor_en": "LEONG Hou U",
        "instructor_zh": "梁浩宇",
        "instructor_pt": "LEONG Hou U",
        "marking_rule": 3,
    },
    "doctoral": {
        "class_code": "PHD7001-001",
        "module_code": "PHD7001",
        "faculty_en": "Faculty of Applied Sciences",
        "faculty_zh": "應用科學學院",
        "faculty_pt": "Faculdade de Ciências Aplicadas",
        "prog_name_en": "Doctor of Philosophy in Applied Sciences",
        "prog_name_zh": "應用科學哲學博士學位課程",
        "prog_name_pt": "Doutoramento em Ciências Aplicadas",
        "module_name_en": "Research Methods",
        "module_name_zh": "研究方法",
        "module_name_pt": "Métodos de Investigação",
        "prerequisite_en": "Nil",
        "prerequisite_zh": "無",
        "prerequisite_pt": "Nil",
        "instructor_en": "Example Lecturer",
        "instructor_zh": "示例教師",
        "instructor_pt": "Docente de Exemplo",
        "marking_rule": 4,
    },
    "joint": {
        "class_code": "COMP111-111, COMP1121-111, COMP1121-114",
        "class_codes": ["COMP111-111", "COMP1121-111", "COMP1121-114"],
        "module_code": "COMP111 / COMP1121",
        "faculty_en": "Faculty of Applied Sciences",
        "faculty_zh": "應用科學學院",
        "faculty_pt": "Faculdade de Ciências Aplicadas",
        "prog_name_en": "Bachelor of Science in Computing / Bachelor of Science in Artificial Intelligence",
        "prog_name_zh": "電腦學學士學位課程 / 電腦學理學士學位課程 / 人工智能理學士學位課程",
        "prog_name_pt": "Curso de Licenciatura em Informática / Curso de Licenciatura em Inteligência Artificial",
        "module_name_en": "Introduction to Computing / Introduction to Computer Science and Its Application",
        "module_name_zh": "電腦學概論 / 計算機科學導論及其應用",
        "module_name_pt": "Introdução à Informática / Introdução à Informática e suas Aplicações",
        "prerequisite_en": None,
        "prerequisite_zh": " ",
        "prerequisite_pt": None,
        "instructor_en": "NG POU IOK",
        "instructor_zh": "吳寶玉",
        "instructor_pt": "NG POU IOK",
        "marking_rules": [1],
    },
}


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    common = {
        "degree_level": "",
        "medium_of_instruction": "English",
        "credits": 3,
        "duration": 45,
        "academic_year": "2026/2027",
        "semester": "1",
        "email": "lecturer@mpu.edu.mo",
        "room_en": "M505",
        "room_zh": "M505",
        "room_pt": "M505",
        "telephone": "8599-0000",
    }
    for degree, specific in SAMPLES.items():
        module = {**common, **specific, "degree_level": degree}
        for language in ("en", "zh", "pt"):
            filename = f"{degree}_{LANG_SUFFIXES[language]}.docx"
            (OUTPUT_DIR / filename).write_bytes(_render_one(module, language))
    print(f"Wrote {len(SAMPLES) * 3} samples to {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
