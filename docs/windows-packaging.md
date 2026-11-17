# Windows packaging and verification

The faculty guide is [README-Windows.md](../README-Windows.md). This document is for maintainers.

## Build

Run `./build_windows.ps1` in PowerShell on 64-bit Windows with Python 3.11 or 3.12
(including Tcl/Tk), Git and Node.js available. Node is used by the existing frontend regression test,
not by the packaged application. The script creates `.build-venv`, installs requirements and PyInstaller,
runs the full unittest suite and compilation checks, and builds `ModuleOutlineGenerator.spec`.
It then runs the HTTP smoke harness against the **compiled EXE**, before creating:

```
dist/ModuleOutlineGenerator-Windows/
    ModuleOutlineGenerator.exe
    _internal/
    README-Windows.txt
    README-Windows.md
    Reset Administrator.cmd
    build-dependencies.txt
release/ModuleOutlineGenerator-Windows.zip
```

The ZIP includes the enclosing folder. Do not distribute just the EXE. Build outputs are ignored by Git.
`build-dependencies.txt` records the resolved build environment. Requirements remain compatible with
the existing web environment; Gunicorn is excluded on Windows and from the frozen application.

Alternatively, push these source changes to GitHub and run **Actions → Windows application → Run workflow**.
The workflow uses `windows-latest`, also runs for `v*` tags, and uploads the release ZIP as an artifact.
It does not publish releases or embed GitHub/environment secrets. It has read-only repository permissions.
The workflow uses the maintainers' supported Node 24 action versions
([checkout](https://github.com/actions/checkout), [setup-python](https://github.com/actions/setup-python),
[upload-artifact](https://github.com/actions/upload-artifact)).
Download and extract the artifact wrapper to obtain the distribution ZIP; publish that ZIP through
your university's approved release channel after completing the interactive guide checklist.

Windows executables must be built on Windows; PyInstaller does not cross-compile this package on macOS.
An unsigned build may need review by university IT. Code signing is not configured by this project.

## Resource inventory

`ModuleOutlineGenerator.spec` explicitly includes:

- `frontend/index.html`: the existing interface, with no network-hosted frontend dependencies.
- `backend/schema.sql` and `backend/seed.sql`: schema/migrations and first-launch demonstration data.
- All three tracked `backend/templates/template_{en,zh,pt}.docx`: prepared official runtime templates.
- The imported backend modules, Flask, Waitress, pandas/openpyxl/xlrd, DOCX/Jinja/XML dependencies,
  standard-library Tk and the Python runtime (through PyInstaller analysis and hooks).
- python-docx/docxtpl package data needed for document operations.

No developer database, real faculty workbook, source template directory, local outputs,
credential verifier, administrator token, backups, or environment file is bundled.
The converted runtime templates, not the ignored `Module Outline Templates` source directory,
are the release source of truth. Validate changes to those tracked templates before building.

Read-only paths come from the bundle root (`sys._MEIPASS` when frozen), independent of CWD.
This follows [PyInstaller's resource discovery](https://pyinstaller.org/en/stable/runtime-information.html)
and [spec data-file configuration](https://pyinstaller.org/en/stable/spec-files.html).
Every mutable desktop path is under `%LOCALAPPDATA%\ModuleOutlineGenerator`.

## Runtime and authentication

`desktop_launcher.py` is the entry point. A small **standard-library Tk** window is used only
for masked first-run password setup, explicit recovery, status, and reliable Windows close events.
The full application interface stays in the default browser. There is no new third-party GUI dependency.
Cancel setup to exit. Users close the status window or click Stop to drain active file operations
before shutting down the Waitress workers and sockets. Browser-tab closure alone does not stop the app.
Forced process termination/power loss cannot guarantee graceful completion; existing template recovery
is retained, and SQLite imports still stage their replacement database before activation.

The launcher owns an OS file lock for its lifetime. Later launches verify the stored instance
address using a fresh instance nonce before reopening the same browser page. Stale metadata is
discarded only by the next lock owner. Instances for separate Windows accounts have separate stores.
The socket is bound to `127.0.0.1` before handing it to Waitress; a busy or reserved default port
falls back to a kernel-selected port without a check-then-bind race.
Readiness is probed over HTTP before browser launch.
Waitress is the [Windows-compatible WSGI server](https://docs.pylonsproject.org/projects/waitress/en/stable/usage.html).

Desktop request middleware rejects foreign Host/Origin values and cross-site state-changing requests.
It serializes file operations, so Excel import can replace SQLite files without another desktop request
holding a SQLite connection open on Windows. Shutdown waits for in-progress requests before closing workers.
The instance nonce is only a lifecycle identifier in private local state, never an administrator password.

An administrator chooses a 12–256-character password, stored as a salted Werkzeug scrypt verifier
(`32768:8:1`) through atomic replacement of `data/administrator.json`.
The browser transports the explicitly entered password only with the template-update request using the
`Desktop` authorization scheme and percent encoding for Unicode. It is cleared after the attempt.
The public `/api/runtime` endpoint discloses only the mode, never secrets, hashes, or local paths.
Five failed password checks cause a 30-second cooldown. Missing or corrupt verifiers fail closed.
If a database already exists without a verifier, ordinary launch requires explicit reset.

`Reset Administrator.cmd` runs `--reset-admin`, which requires an explicit confirmation and new
password; cancelling leaves the verifier unchanged. The existing application must first be stopped.
Recovery trusts access to the Windows account and its local files; it is not a boundary against
someone who can modify those files. No credential deletion or universal recovery password is used.

The web deployment retains its existing paths, `TEMPLATE_ADMIN_TOKEN` Bearer authentication,
`TEMPLATE_STORAGE_DIR`, Gunicorn Procfile and Railway behavior. Desktop mode overrides those settings
before importing Flask, clears any inherited web token in the app configuration, and authenticates
with the verifier instead. Desktop database/output path overrides use `MODULE_OUTLINE_DATA_DIR`.
Neither desktop setting is required for web deployment.

Template activation uses the existing template lock, journal, rollback and `.template-backups`
layout under the writable root. Initial templates are copied only into an empty template directory.
Partial sets require explicit recovery; existing templates and databases are never overwritten by startup.
The bundled seed is applied only when a desktop database is first created.
Back up and restore the whole data directory while stopped, including the recovery journal if present.

## Automated and manual checks

From a development checkout:

```
PYTHONPATH=backend .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/smoke_windows.py --source
git diff --check
```

The portable unittest cases cover source/frozen resource paths, damaged/missing resources,
first-run storage and seeding, deliberately empty database persistence, hash authentication/reset,
rate limiting, private API behavior, loopback port conflicts/failure, browser readiness/failure,
single-instance coordination, cross-origin rejection and draining active file operations.
The existing regression suite covers authoritative master import, repeated rows, Rule 1–4,
multiple teachers/prerequisites, joint grouping, DOCX structure/hyperlinks and transactional updates.
Tests requiring the supplied real master workbook skip if that private workbook is unavailable.
The existing POSIX-specific process-lock test skips on Windows; desktop lock and HTTP restart
coverage run on Windows instead. Symlink coverage skips if Windows denies symlink creation.

`scripts/smoke_windows.py --executable <path-to-exe>` copies the full distribution into a path
with spaces, Chinese and Portuguese characters. It starts that EXE from a different working directory
with isolated writable state and a pre-provisioned, randomly salted test verifier. It imports a
synthetic authoritative-format workbook through multipart HTTP, tests repeated/joint data, downloads
and opens nested ZIPs and EN/ZH/PT DOCX files, rejects incorrect/web authentication, converts all
three official-slot fixture templates, verifies backups, prevents duplicate servers, stops cleanly,
restarts, and checks database/template/password persistence and generation again.
It also reserves the default port when available to verify fallback and uploads Unicode template filenames.
It never runs on a staff data directory and embeds no test credential in the release.

The harness uses `--headless --no-browser --data-dir <temporary-path>` solely for automation.
Headless mode requires an existing verifier and does not implement an unauthenticated setup API.
Its `.stop-request` file triggers the same clean server shutdown used by the launcher.
Headless mode does not open dialogs. Source mode is not evidence of a Windows build.
Build logs explicitly distinguish source mode from compiled-executable mode.
The interactive release checklist in the faculty guide is still required for actual browser
launch, file picker, password dialogs, status-window X behavior, fonts and security prompts.

## Verification on the implementation host

The implementation workspace is macOS. Windows compilation and interactive Windows testing
must be performed by the workflow/build script and a Windows reviewer. A Windows ZIP is not
produced or claimed from macOS.

Local verification on 2026-11-16:

- Complete unittest suite: **132 tests, 59.759 seconds, OK**, with no skips on this host.
- Source HTTP smoke: **PASS**, including busy-port fallback, Unicode uploads, real conversions,
  clean process shutdown, a full restart, and persistent database/templates.
- `compileall`, PyInstaller spec syntax compilation, `pip check`, and `git diff --check`: **PASS**.
- Compiled Windows EXE, Windows browser/dialog checks and distribution ZIP: **not built/tested here**.

The original 110-test suite also passed before adding the desktop tests. The private authoritative
master workbook was available on this host; it is not included in the build or committed to Git.
