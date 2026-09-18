# Module Outline Generator

An internal web tool for Macao Polytechnic University that generates pre-filled
Module Outline Word documents in three languages (English, Chinese, Portuguese).

Users select a faculty, programme, or individual class from cascading dropdown
menus. The system retrieves all data from a database and produces a downloadable
.zip archive containing one inner ZIP per class code, each with editable
EN, ZH and PT .docx files. Generated files are also saved on the server in the `output/` folder.


## Project Structure

    module_template_app/
    |
    |-- backend/
    |   |-- app.py                  Flask application and API routes
    |   |-- database.py             SQLite connection and query helpers
    |   |-- generator.py            Trilingual Word document rendering (docxtpl)
    |   |-- convert_template.py     Shared official-template conversion and CLI
    |   |-- import_excel.py         Import real data from an Excel file
    |   |-- schema.sql              Database schema (faculties, programmes, classes)
    |   |-- seed.sql                Sample data for development
    |   |-- templates/
    |       |-- template_en.docx    English Jinja2-tagged template
    |       |-- template_zh.docx    Chinese Jinja2-tagged template
    |       |-- template_pt.docx    Portuguese Jinja2-tagged template
    |
    |-- frontend/
    |   |-- index.html              Single-page web interface
    |
    |-- output/                     Generated documents (created at runtime)
    |-- requirements.txt


## Prerequisites

- Python 3.10 or higher
- The original Module Outline Templates from the university (EN, ZH, PT)
  placed in a `Module Outline Templates/` folder at the project root


## Setup Steps

1. Clone the repository

        git clone https://github.com/Discretc/module_template.git
        cd module_template

2. Create and activate a virtual environment

        python3 -m venv .venv
        source .venv/bin/activate

   On Windows use:

        .venv\Scripts\activate

3. Install dependencies

        pip install -r requirements.txt

4. Run the application

        python3 backend/app.py

   The database is created and seeded with sample data automatically on first
   run. The app starts on port **5001**.

5. Open the application in your browser

        http://127.0.0.1:5001


## Preparing New Official Word Templates

The repository already includes prepared runtime templates in:

- `backend/templates/template_en.docx`
- `backend/templates/template_zh.docx`
- `backend/templates/template_pt.docx`

You do not need to run the conversion script during normal setup.

Use the **Convert / Update Official Templates — Administrator** section when MPU
issues a new official template. Set `TEMPLATE_ADMIN_TOKEN` to a long random
secret in the server environment and configure `TEMPLATE_STORAGE_DIR` as described
below. Restart the app and give the token only to authorized administrators. Use
HTTPS for a hosted installation. With no configured token, updates return HTTP
503; missing/invalid credentials return 401. With valid credentials but no storage
configuration, updates return 503 before parsing uploads. There is no default
administrator token. The server never returns the token, and the frontend clears
its password field after every attempt without saving it in browser storage.
Keep Authorization headers out of any custom proxy/access logging.

Upload English, Chinese and Portuguese official `.docx` files together and click
**Convert & Validate**. Each file is limited to 10 MB (32 MB total request). The
server checks ZIP/XML integrity, structure anchors, required placeholders and
representative generation for every Rule and degree in every language. Uploaded
Jinja, macros, embedded objects, unsafe paths and external linked content (other
than web/email hyperlinks) are rejected. `.docm` is rejected; legacy Portuguese
`.doc` must first be exported to DOCX using Word or Apple Pages.

All files are staged before activation. Updates and generation share thread and
OS file locks across cooperating Flask/Gunicorn workers. The complete update,
including staging and validation, is serialized; generation waits during it.
Previous templates are retained under
`$TEMPLATE_STORAGE_DIR/.template-backups/<backup_id>/`. The journal at
`$TEMPLATE_STORAGE_DIR/.template-transaction.json` rolls an interrupted activation
back before another reader/update proceeds. Linux file and directory `fsync`
preserves backup/journal/activation ordering. Recovery is retryable even if it is
interrupted; an unreadable/incomplete recovery backup blocks readers rather than
serving mixed templates. Ordinary failures clean staging immediately; abrupt
process termination leaves temporary files that are cleaned on the next locked
startup/read/update. Backups remain until an administrator removes them. Never
delete a backup referenced by an existing journal. Direct external file
readers/writers and the conversion CLI do not participate in this transaction.

### Required persistent storage for hosted template updates

Previously, web updates overwrote tracked `backend/templates` files on the local
application disk. A process restart on the same disk retained updates, but a new
container/deployment restored the repository copies. **Do not enable web updates
on ephemeral container storage.** This app now uses the following configuration:

| Configuration | Runtime templates | Restart / redeploy behavior |
| --- | --- | --- |
| No `TEMPLATE_STORAGE_DIR` | Bundled `backend/templates` | Generation works; web updates are disabled. |
| `TEMPLATE_STORAGE_DIR` on a persistent mount | `<directory>/templates` | Updates and recovery state survive while the same mount is retained. |
| `TEMPLATE_STORAGE_DIR` on ephemeral disk | `<directory>/templates` | Changes can be lost on container replacement; unsupported for hosted updates. |

`TEMPLATE_STORAGE_DIR` must be an absolute path to a dedicated, writable directory
outside `frontend` and bundled templates. It must point **inside an attached
persistent mount**, or to an external persistent directory on a managed server.
Setting an environment variable does not provision persistent storage; the app
cannot verify the provider's durability guarantee. On first runtime startup it
seeds all three templates from the bundled copies. Subsequent startups use the
existing complete set, even when a release changes its bundled templates. A
partial existing set fails startup and needs explicit repair. The mount must
include the entire storage directory: active templates, lock, backups, journal
and staging all live there. Files are private application state and are not
served by Flask static routes. Generated document downloads still use them as
intended. Do not configure a proxy/static server to expose the storage directory.

Manual deployment settings (no deployment changes are made automatically):

- **Railway:** attach a persistent volume at `/data`, then set
  `TEMPLATE_STORAGE_DIR=/data/template-storage` and `TEMPLATE_ADMIN_TOKEN` in the
  service's secret variables. Volume initialization runs during application
  startup, not build/pre-deploy. See [Railway volumes](https://docs.railway.com/volumes).
- **Render:** attach a persistent disk at `/var/data` to a supported paid service,
  then set `TEMPLATE_STORAGE_DIR=/var/data/template-storage` and
  `TEMPLATE_ADMIN_TOKEN` in the service environment. Default service filesystems
  are ephemeral; only paths under the disk mount persist. See
  [Render persistent disks](https://render.com/docs/disks).
- Use one service instance with that mount; multiple Gunicorn workers on the
  instance are supported. Separate containers with separate disks cannot share
  this lock/state. External filesystems must support reliable OS file locking,
  atomic rename and `fsync`. Retain the mount when deploying or rolling back code.
- For local development only, an absolute path to this checkout's
  `template-storage/` directory is Git-ignored. It is not a cloud persistence
  solution. Keep other custom storage paths outside the checkout. Backup,
  journal, lock, staging and temporary filenames are ignored anywhere in Git.

For migration, stop the old app and copy its current three runtime DOCX files to
`<persistent-directory>/templates/` before starting the configured app. Also copy
any `.template-backups/` and `.template-transaction.json` from the old templates'
parent directory so interrupted recovery remains possible. Export existing
updates before destroying/redeploying the old container. Keep the old files
until the configured service generates documents successfully.

For an administrator rollback, stop the service, retain a copy of the whole
storage directory, and run this on the mounted runtime host with its configured
environment and the backup reference shown after an upload:

```sh
export TEMPLATE_BACKUP_ID='<32-character backup reference>'
PYTHONPATH=backend python - <<'PYCODE'
import os
from pathlib import Path
from template_storage import activate_templates, configured_template_directory
backup_id = os.environ["TEMPLATE_BACKUP_ID"]
assert len(backup_id) == 32 and all(c in "0123456789abcdef" for c in backup_id)
assert os.environ.get("TEMPLATE_STORAGE_DIR"), "Persistent storage must be configured"
active = configured_template_directory(Path("backend/templates").resolve())
activate_templates(active.parent / ".template-backups" / backup_id, active)
PYCODE
```

This first completes any pending journal recovery, then activates the selected
backup through the same transaction and backs up the current set. Restart and
verify a representative generated package. If recovery is blocked by missing or
corrupt files, restore the whole storage directory from a known-good offline
backup; do not remove the journal just to bypass the error. Keep a periodic
backup outside the volume and monitor retained-backup disk usage. Store token,
hosting and storage access in a faculty-controlled account/password manager so
staff can rotate the token and manage templates after the original developer
leaves. No developer checkout is required for normal web updates.

The CLI remains available and uses the same conversion function. Only run
`backend/convert_template.py` when the university provides a new
official Module Outline template and the runtime templates need to be
regenerated.

    python3 backend/convert_template.py \
      --source-dir "Module Outline Templates" \
      --pt-docx "Module Outline Templates/module-outline-template_pt_202305.docx"

This script copies/prepares the official Word templates and inserts the
placeholders used by the document generator.

When only the English and Chinese templates changed, preserve the existing
Portuguese runtime template with `--skip-pt`.

    python3 backend/convert_template.py \
      --source-dir "Module Outline Templates" \
      --skip-pt

For Portuguese, if the university supplies only a legacy `.doc` file, first
open it in Microsoft Word or Apple Pages and export it as `.docx`. Do not use
macOS `textutil`, because it may damage the document's table structure.


## Tests

Run the focused generator and API regression tests with:

    PYTHONPATH=backend .venv/bin/python -m unittest discover -s tests -v

The tests cover existing import/migration/render behavior, nested ZIP filenames
and contents, joint packages and programme names, canonical rule reference and
frontend rendering/count helpers, administrator authorization, upload validation,
all-language activation/backups, rollback and interrupted-update recovery.
Frontend helper tests require Node.js. For additional checks:

    git diff --check
    .venv/bin/python -m compileall -q backend tests scripts


## How to Use

1. Select the **Academic Year** and **Semester**
2. Choose a **Faculty** from the dropdown
3. Optionally narrow down to a specific **Programme** or **Class**
4. Click **"Download Module Outlines (.zip)"**
5. The browser downloads an outer .zip containing one class-code ZIP per class;
   open an inner ZIP to find that class code’s EN, ZH and PT Word documents
6. Open the .docx files in Word and complete the remaining sections

**Batch generation:** leave the Programme and Class dropdowns at their default
("all") to generate documents for every class in the selected faculty at once.


## API Endpoints

    GET  /api/faculties                          List all faculties
    GET  /api/programmes?faculty_id=             Programmes filtered by faculty
    GET  /api/classes?programme_id=&faculty_id=  Classes filtered by programme or faculty
    POST /api/generate                           Generate and download nested class ZIPs
    GET  /api/rules                              Read-only canonical Rules 1–4
    POST /api/templates/convert                  Convert/validate/activate EN/ZH/PT uploads

The generate endpoint accepts a JSON body:

    {
      "faculty_id": 1,
      "programme_id": 1,        // optional – omit for entire faculty
      "class_ids": [1, 2],      // optional – omit for entire programme/faculty
      "academic_year": "2025/2026",
      "semester": "1"
    }


## Importing Real Data from Excel

When you have the real university data in an Excel file, use the import script
instead of the sample seed data.

    python backend/import_excel.py path/to/your_data.xlsx

The script will wipe the existing data and replace it with everything in the
Excel file. Restart the Flask app afterwards.

The master workbook has one sheet where each row is a class association, with
these authoritative columns (including the source spelling and spaces):

    Faculty_Code | Faculty _Chn | Faculty _Eng | Faculty _Prt
    Prog_Code | Prog_Chn | Prog_Eng | Prog_Prt
    Class_Code | Module_Chn | Module_Eng | Module_Prt
    Prerequsite_Chn | Prerequsite_Eng | Prerequsite_Por
    Credits | Durations
    Instructor_Chn | Instructor_Eng | Instructor_Prt
    Email | Room_Chn | Room_Eng | Room_Prt | Telephone | Rule | Joint_Relationship

The importer validates the headings and every `Rule` value before replacing the
database. `Rule` is stored as `rule_code INTEGER NOT NULL` with a database check
constraint limiting it to 1–4. Whole-number Excel values such as `2` and `2.0`
and clear legacy labels such as `Rule TWO` are normalized. Blank, fractional,
unknown, and out-of-range values reject the complete import with row-specific
errors; they are never treated as Rule 1.

Rule 1 inserts no marking-rule paragraph. Rules 2–4 insert the approved fixed
English, Chinese, or Portuguese statements as separate Word paragraphs. Joint
class members must have the same rule code; a conflict reports each class code
and stops generation for the complete selection.

Legacy databases with a valid `marking_rule` are migrated to `rule_code`.
Records without a valid legacy value are recorded in `rule_migration_review`
and block normal database use until reviewed, rather than receiving a default.

`Medium of Instruction` / `授課語言` / `Língua veicular` is the module's actual
teaching language, not the generated document language. The authoritative
master workbook does not supply it, so new imports store it as unknown and the
corresponding editable Word cell remains blank. Optional legacy
`Teaching_Language` or `Medium_of_Instruction` columns are preserved when they
are explicitly supplied.

`Joint_Relationship` contains related full class codes separated by commas. The
application treats reciprocal or one-way references as an undirected group and
combines document content per connected group. Every member class code receives
its own package and three language documents; each document still shows all
joint class codes (comma + space) and combined programme names in stable order.
Selecting one member generates only that member's package. Programme and faculty
generation package only members in the selected scope. Documents and Rule
validation always include the complete joint group, including members outside
that scope. The class dropdown lists individual members, and the preview counts
the selected output codes and documents.

For example:

```text
module_outlines_2026_2027_sem1.zip
├── COMP1121-111.zip
│   ├── COMP1121-111_EN.docx
│   ├── COMP1121-111_ZH.docx
│   └── COMP1121-111_PT.docx
└── COMP1121-114.zip
    ├── COMP1121-114_EN.docx
    ├── COMP1121-114_ZH.docx
    └── COMP1121-114_PT.docx
```

Single-class downloads use the same outer/inner structure. Duplicate class codes
are removed; ambiguous filename collisions fail clearly rather than overwrite.
The **Rule Reference** below Excel import fetches approved wording directly from
`backend/rules.py`; it provides no editing controls.

The current master workbook has no academic-year, semester, or teaching-language
column. The interface therefore supplies a rolling academic-year range and the
selected semester. Unknown medium-of-instruction cells remain blank in all languages. Missing prerequisites display `Nil`, `無`, and
`Não tem`.


## Reseeding the Database (development)

To reset the database and reload the sample data:

    rm backend/module_outlines.db
    python backend/app.py

The template-update endpoint accepts multipart fields `en`, `zh`, `pt` and
`Authorization: Bearer <TEMPLATE_ADMIN_TOKEN>`. Conversion supports the existing
official six-table format and language anchors. A future structurally different
template is rejected safely and needs an update to the shared converter.
