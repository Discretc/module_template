"""Canonical marking-rule validation and approved multilingual wording."""

from __future__ import annotations

import math
import re


class RuleValidationError(ValueError):
    """Raised when a marking-rule value is absent or not canonicalizable."""


class JointRuleConflictError(ValueError):
    """Raised when members of one joint class have different rules."""


RULE_PARAGRAPHS: dict[int, dict[str, tuple[str, ...]]] = {
    1: {"en": (), "zh": (), "pt": ()},
    2: {
        "zh": (
            "若學生期末考試分數為35分以下，即使其總分達50分或以上，學生必須參加補考。",
        ),
        "en": (
            "Students with a score of less than 35 in the final examination must take the "
            "resit examination even if the overall score for the learning module is 50 or above.",
        ),
        "pt": (
            "Qualquer aluno que obtenha menos de 35% no exame final terá de se submeter ao "
            "exame suplementar, independentemente da nota final.",
        ),
    },
    3: {
        "zh": (
            "若學生總體平時分數為35分以下，即使其總分達50分或以上，學生必須參加補考。",
            "若學生期末考試分數為35分以下，即使其總分達50分或以上，學生必須參加補考。",
            "若學生總成績為35分以下，學生不能參加補考。",
        ),
        "en": (
            "Students with an overall score of less than 35 in the coursework must take the "
            "resit examination even if the overall score for the module is 50 or above.",
            "Students with a score of less than 35 in the final examination must take the "
            "resit examination even if the overall score for the module is 50 or above.",
            "Students with an overall final grade of less than 35 are NOT allowed to take the "
            "resit examination.",
        ),
        "pt": (
            "Qualquer aluno que obtenha menos de 35% na avaliação contínua terá de se submeter "
            "ao exame suplementar, independentemente da nota final.",
            "Qualquer aluno que obtenha menos de 35% no exame final terá de se submeter ao "
            "exame suplementar, independentemente da nota final.",
            "Qualquer aluno que obtenha menos de 35% no nota final não pode realizar o exame "
            "suplementar.",
        ),
    },
    4: {
        "zh": (
            "若學生總體平時分數為35分以下，即使其總分達50分或以上，學科單元之成績作不及格處理。",
            "若學生期末考試分數為35分以下，即使其總分達50分或以上，學科單元之成績作不及格處理。",
        ),
        "en": (
            "Students with an overall score of less than 35 in the coursework will fail the "
            "module even if the overall score for the module is 50 or above.",
            "Students with a score of less than 35 in the final examination will fail the "
            "module even if the overall score for the module is 50 or above.",
        ),
        "pt": (
            "Qualquer aluno que obtenha menos de 35% na avaliação contínua vai reprovar ao "
            "módulo, independentemente da nota final.",
            "Qualquer aluno que obtenha menos de 35% no exame final vai reprovar ao módulo, "
            "independentemente da nota final.",
        ),
    },
}


_WORD_CODES = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
}


def normalize_rule_code(value) -> int:
    """Normalize an explicit Rule value to an integer from 1 through 4."""
    if value is None or isinstance(value, bool):
        raise RuleValidationError("Rule is blank")
    if isinstance(value, float):
        if math.isnan(value):
            raise RuleValidationError("Rule is blank")
        if not value.is_integer():
            raise RuleValidationError(f"Rule value {value!r} is fractional")
        value = int(value)
    if isinstance(value, int):
        if value not in RULE_PARAGRAPHS:
            raise RuleValidationError(f"Rule value {value!r} is outside 1–4")
        return value

    text = str(value).replace("\xa0", " ").strip()
    if not text:
        raise RuleValidationError("Rule is blank")
    compact = re.sub(r"[\s_-]+", " ", text.casefold()).strip()
    compact = re.sub(r"^(?:rule|規則|规则)\s*", "", compact).strip()
    if compact in _WORD_CODES:
        return _WORD_CODES[compact]
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", compact):
        number = float(compact)
        if not number.is_integer():
            raise RuleValidationError(f"Rule value {text!r} is fractional")
        integer = int(number)
        if integer not in RULE_PARAGRAPHS:
            raise RuleValidationError(f"Rule value {text!r} is outside 1–4")
        return integer
    raise RuleValidationError(f"Rule value {text!r} is unknown")


def get_rule_paragraphs(rule_code, language: str) -> tuple[str, ...]:
    """Return the approved ordered paragraph list for a canonical rule code."""
    code = normalize_rule_code(rule_code)
    if language not in ("en", "zh", "pt"):
        raise RuleValidationError(f"Unsupported rule language {language!r}")
    return RULE_PARAGRAPHS[code][language]


def require_consistent_joint_rule(members: list[dict]) -> int:
    """Return one rule code or report every conflicting joint-class row."""
    rows = []
    for member in members:
        code = normalize_rule_code(member.get("rule_code"))
        rows.append((str(member.get("class_code") or member.get("id") or "unknown"), code))
    distinct = {code for _, code in rows}
    if len(distinct) != 1:
        detail = ", ".join(f"{class_code}=Rule {code}" for class_code, code in rows)
        raise JointRuleConflictError(f"Joint class has conflicting Rule values: {detail}")
    return rows[0][1]
