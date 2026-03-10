-- Module Outline Template Generator – Database Schema
-- SQLite

-- Programmes (degree programmes offered by the university)
CREATE TABLE IF NOT EXISTS programmes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    programme_name  TEXT    NOT NULL,               -- e.g. "Bachelor of Science in Computing"
    degree_level    TEXT    NOT NULL,               -- "Doctoral" | "Master's" | "Bachelor's"
    academic_unit   TEXT    NOT NULL,               -- e.g. "Faculty of Applied Sciences"
    created_at      TEXT    DEFAULT (datetime('now'))
);

-- Modules (individual learning modules / courses)
CREATE TABLE IF NOT EXISTS modules (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    module_code             TEXT    NOT NULL UNIQUE, -- e.g. "MSEL3101"
    module_name             TEXT    NOT NULL,        -- e.g. "Introduction to Psychology"
    programme_id            INTEGER NOT NULL REFERENCES programmes(id),
    prerequisites           TEXT    DEFAULT 'Nil',   -- free text; "Nil" when none
    medium_of_instruction   TEXT    DEFAULT 'English',
    credits                 INTEGER NOT NULL,
    contact_hours           TEXT    NOT NULL,        -- e.g. "45 hrs"
    created_at              TEXT    DEFAULT (datetime('now'))
);
