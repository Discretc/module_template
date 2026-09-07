-- Module Outline Template Generator – Database Schema (v2, trilingual)
-- SQLite

CREATE TABLE IF NOT EXISTS faculties (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    code     TEXT NOT NULL UNIQUE,
    name_en  TEXT,
    name_zh  TEXT,
    name_pt  TEXT
);

CREATE TABLE IF NOT EXISTS programmes (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    code         TEXT NOT NULL UNIQUE,
    name_en      TEXT,
    name_zh      TEXT,
    name_pt      TEXT,
    degree_level TEXT NOT NULL,   -- "bachelor", "master", "doctoral"
    faculty_id   INTEGER NOT NULL REFERENCES faculties(id)
);

CREATE TABLE IF NOT EXISTS classes (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    class_code       TEXT NOT NULL UNIQUE,   -- e.g. "COMP1123-121"
    module_code      TEXT NOT NULL,          -- e.g. "COMP1123" (derived)
    module_name_en   TEXT,
    module_name_zh   TEXT,
    module_name_pt   TEXT,
    prerequisite_en  TEXT DEFAULT 'Nil',
    prerequisite_zh  TEXT,
    prerequisite_pt  TEXT DEFAULT 'Nil',
    credits          INTEGER,
    duration         INTEGER,               -- contact hours number (e.g. 45)
    medium_of_instruction TEXT DEFAULT 'English',
    instructor_en    TEXT,
    instructor_zh    TEXT,
    instructor_pt    TEXT,
    email            TEXT,
    room_en          TEXT,
    room_zh          TEXT,
    room_pt          TEXT,
    telephone        TEXT,
    rule_code        INTEGER NOT NULL CHECK (rule_code IN (1, 2, 3, 4)),
    joint_relationship TEXT,              -- comma-separated related full class codes
    programme_id     INTEGER NOT NULL REFERENCES programmes(id),
    academic_year    TEXT,
    semester         TEXT
);

CREATE TABLE IF NOT EXISTS rule_migration_review (
    class_id     INTEGER,
    class_code   TEXT,
    legacy_value TEXT,
    reason       TEXT NOT NULL,
    flagged_at   TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
