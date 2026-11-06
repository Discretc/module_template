# October 2026 master workbook validation

Validated on 2026-11-06 using `Master File to Elvis 20261030.xlsx` in the current
working tree. The source workbook was read only; its SHA-256 was checked before
and after import/generation. Testing used an isolated database under `output/`.
Source SHA-256: `849d426e56f83b10f8da14b14dd02656f1f47bcb13ebd04b586e8e54b7747513`.

## Workbook inspection and import

One sheet, `工作表1`, contains **54 data rows**, **28 columns**, and **11 unique
full Class_Code values**. The new `Prerequsite_Code` header is column **13**,
immediately before the three prerequisite name columns. Compared with the
previous canonical mapping, this is the added column. Exact current order:

```text
Faculty_Code | Faculty _Chn | Faculty _Eng | Faculty _Prt
Prog_Code | Prog_Chn | Prog_Eng | Prog_Prt | Class_Code
Module_Chn | Module_Eng | Module_Prt
Prerequsite_Code | Prerequsite_Chn | Prerequsite_Eng | Prerequsite_Por
Credits | Durations | Instructor_Chn | Instructor_Eng | Instructor_Prt
Email | Room_Chn | Room_Eng | Room_Prt | Telephone | Rule | Joint_Relationship
```

Both `Room_Eng` and `Room_Prt` are entirely empty. They are optional for import;
`Room_Chn` drives all three document versions. There is no medium-of-instruction
column; generated versions supply `English`, `中文`, and `Português`.

| Repeated Class_Code | Source rows |
| --- | ---: |
| COMP1121-111 | 2 |
| COMP1121-114 | 2 |
| COMP111-111 | 2 |
| JAPN1102-313 | 2 |
| JAPN1102-215 | 2 |
| JAPN1102-211 | 2 |
| PPOL8101-111 | 3 |
| COMP4299-431 | 36 |

`PPOL8101-111` has three instructors with different emails and rooms.
`COMP4299-431` has 18 teacher/contact records and two prerequisite pairs:
`Software Engineering (COMP2116)` and `Information System Project (COMP3114)`.
`JAPN1102-313` has `Japanese I (JAPN1101)` and different joint relationships on
its two rows. The COMP1121/COMP111 rows similarly supply multiple joint edges.

| Database/import result | Count |
| --- | ---: |
| Excel rows processed | 54 |
| Faculties | 3 |
| Programmes | 9 |
| Unique classes | 11 |
| Logical groups, including standalone classes | 6 |
| Joint groups | 3 |
| Teacher/contact child records, across classes | 30 |
| Prerequisite child records, across classes | 5 |
| Skipped source rows | 0 |
| Nested packages | 11 |
| DOCX files in packages | 33 |

The three joint groups are:

- COMP111-111, COMP1121-111, COMP1121-114
- JAPN1102-211, JAPN1102-215, JAPN1102-313
- PADM1103-111, PADM1103-112

Every unique member receives its own ZIP containing EN/ZH/PT. Documents contain
the full joint class list and combined programme names. Teacher/prerequisite
records shared by joint members appear once in the combined content.

## Data model and validation

The previous importer retained the first class row and skipped all later rows
with the same Class_Code. The new importer groups the full class identity and
keeps ordered records in `class_instructors` and `class_prerequisites`. Records
are deduplicated as whole tuples, retaining name/email/room/telephone and
code/EN/ZH/PT-name associations. Source occurrence sets the order. Contacts in
multi-teacher documents carry numeric owner labels; shared values carry all
owners without repeating the contact value. Missing fields do not shift other
teachers' contacts.

Scalar metadata conflicts within the same class reject the entire import, with
class code, field, source values and Excel row numbers. Numeric and Rule values
are validated and normalized first. Joint-group Rule validation remains active
at selection/generation as before. Staging plus atomic database replacement
keeps existing data untouched on an invalid import.

The migration creates child tables and backfills legacy scalar records
idempotently. Legacy fields and explicit stored teaching-language values remain
preserved, although document version now determines Medium of Instruction.
Nullable per-class `programme_name_en/zh/pt` snapshots preserve source wording;
older databases fall back to the existing programme lookup.

## Source warnings

Two warnings remain visible after a successful import:

- `COMP4299-431` references `COMP490-431`, which is absent. The reference is
  retained; no missing class/package is invented.
- Programme `4LCSDI` has Portuguese wording `Curso de Licenciatura em Informática`
  on Excel rows 2–3 and `Curso de Licenciatura em Ciências de Informática` on rows
  20–55. These belong to different classes, whose own values are retained for
  generation. The programme selector displays the first source label. Repeated
  rows within any one class agree; there are no same-class metadata conflicts.

## Verification results

- `.venv/bin/python -m unittest discover -s tests -q`: **110 tests passed**, no
  failures or skips, **59.802 seconds**. This includes 18 new repeated-record,
  real-workbook, API, migration and environment-token tests plus the existing
  template conversion, safety, rollback, Rule and ZIP regressions.
- `.venv/bin/python -m compileall -q backend tests scripts`: passed.
- `git diff --check`: passed.
- Real workbook import, SQLite integrity check and foreign-key check: passed.
- All **33 package DOCX files** passed content/XML checks, including contact
  values, prerequisite pairings, language-derived medium, full class codes,
  programme names, Rule paragraphs, no Jinja, no None/NaN or empty parentheses.
- Frontend/API smoke: `/`, `/api/faculties`, `/api/programmes`, `/api/classes`,
  `/api/academic-years`, `/api/column-format`, `/api/rules` all returned 200.
  The class API returned 11 unique class choices. Import/filter/generation flows
  are also exercised together by the regression suite.
- Administrator token: absent server configuration returns 503; missing or wrong
  credentials return 401; a token loaded from a fresh process environment
  authorizes the endpoint. Successful actual conversion, rollback and secret
  non-disclosure are covered by the existing suite. No secret is committed.

## Representative visual review

Generated and rendered all five requested scenarios in EN/ZH/PT (**15 DOCX,
54 rendered pages**):

| Scenario | Representative class | EN pages | ZH pages | PT pages |
| --- | --- | ---: | ---: | ---: |
| Single teacher | COMP6131-111 | 3 | 3 | 4 |
| Multiple teachers | PPOL8101-111 | 4 | 3 | 4 |
| Multiple prerequisites / 18 teachers | COMP4299-431 | 4 | 4 | 5 |
| Joint class | JAPN1102-211 group | 3 | 3 | 4 |
| No prerequisite | COMP1121-111 group | 3 | 3 | 4 |

All pages were visually inspected using the bundled headless LibreOffice and
packaged DOCX renderer. A temporary fontconfig configuration made the available
system Chinese fonts visible to the QA renderer; no runtime template font or
layout was changed. Chinese rooms display in EN/ZH/PT. No clipping, overlaps,
missing glyphs or broken metadata cells were observed. Portuguese vertical
alignment, table grid, header/footer and official paragraph formatting remain
intact. Longer contact lists grow naturally: the 18-teacher office cell spans
two pages, with no data truncation. Pagination varies by language and font
availability; native Word was not used for this review.

Reproduce the import/content/ZIP/API checks with:

```bash
.venv/bin/python scripts/validate_authoritative_workbook.py \
  '/Users/eve/Downloads/Master File to Elvis 20261030.xlsx'
```

Local validation artifacts are under `output/master-validation/` (ignored by
Git), including `validation.json`, `validation.db`, `authoritative_packages.zip`
and the representative DOCX files. Final verification was repeated under
`output/master-validation-final/`; all 15 final representative documents have
identical Word XML to the rendered and visually inspected samples. Rendering
remains a separate visual QA step.
