"""Ordered, row-associated teacher and prerequisite records (including legacy data)."""

import math


MISSING = {"", "none", "nan", "null", "n/a", "na", "not applicable", "-", "--"}
PREREQUISITE_MISSING = MISSING | {
    "nil", "no prerequisite", "no prerequisites", "無", "没有", "沒有",
    "não tem", "nao tem", "sem pré-requisitos", "sem pre-requisitos",
}
INSTRUCTOR_FIELDS = (
    "name_en", "name_zh", "name_pt", "email", "room_zh", "room_en", "room_pt", "telephone",
)
PREREQUISITE_FIELDS = ("prerequisite_code", "name_en", "name_zh", "name_pt")


def clean(value, prerequisite=False):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).replace("\xa0", " ").strip()
    return "" if text.casefold() in (PREREQUISITE_MISSING if prerequisite else MISSING) else text


def unique_records(records, fields):
    """Deduplicate whole records without sorting or breaking field associations."""
    result, seen = [], set()
    for record in records:
        normalized = {field: clean(record.get(field), fields == PREREQUISITE_FIELDS) for field in fields}
        key = tuple(normalized.values())
        if any(key) and key not in seen:
            seen.add(key)
            result.append(normalized)
    return result


def instructors(cls):
    if "instructors" in cls:
        return unique_records(cls["instructors"], INSTRUCTOR_FIELDS)
    return unique_records([{
        **{f"name_{lang}": cls.get(f"instructor_{lang}") for lang in ("en", "zh", "pt")},
        **{field: cls.get(field) for field in INSTRUCTOR_FIELDS if not field.startswith("name_")},
    }], INSTRUCTOR_FIELDS)


def prerequisites(cls):
    if "prerequisites" in cls:
        return unique_records(cls["prerequisites"], PREREQUISITE_FIELDS)
    return unique_records([{
        "prerequisite_code": cls.get("prerequisite_code"),
        **{f"name_{lang}": cls.get(f"prerequisite_{lang}") for lang in ("en", "zh", "pt")},
    }], PREREQUISITE_FIELDS)
