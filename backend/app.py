"""
app.py  –  Flask application (v2)
----------------------------------
Cascading-dropdown API for generating trilingual module-outline templates.

Endpoints:
    GET  /                                    → frontend SPA
    GET  /api/faculties                       → list faculties
    GET  /api/programmes?faculty_id=          → programmes (optionally filtered)
    GET  /api/classes?programme_id=&faculty_id= → classes (optionally filtered)
    POST /api/generate                        → generate & download zip
"""

import os
import secrets
from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

import tempfile

from database import (
    RuleMigrationRequiredError,
    get_academic_years,
    get_classes,
    get_classes_full,
    get_faculties,
    get_programmes,
    init_db,
)
from generator import TEMPLATE_DIR, batch_download_name, generate_batch
from import_excel import import_data, COLUMN_MAP
from rules import JointRuleConflictError, RuleValidationError, RULE_PARAGRAPHS
from template_update import MAX_REQUEST_BYTES, TemplateUpdateError, update_templates
from werkzeug.exceptions import RequestEntityTooLarge

app = Flask(__name__, static_folder="../frontend", static_url_path="")
app.config["TEMPLATE_ADMIN_TOKEN"] = os.environ.get("TEMPLATE_ADMIN_TOKEN", "")
app.config["TEMPLATE_DIR"] = TEMPLATE_DIR
app.config["TEMPLATE_STORAGE_CONFIGURED"] = bool(os.environ.get("TEMPLATE_STORAGE_DIR", ""))
CORS(app)

ALLOWED_EXTENSIONS = {".xlsx", ".xls"}

DATABASE_STARTUP_ERROR = None
try:
    init_db()
except RuleMigrationRequiredError as exc:
    DATABASE_STARTUP_ERROR = str(exc)


@app.before_request
def require_ready_database():
    if (
        DATABASE_STARTUP_ERROR
        and request.path.startswith("/api/")
        and request.path not in {"/api/import-excel", "/api/column-format", "/api/rules", "/api/templates/convert"}
    ):
        return jsonify({"error": DATABASE_STARTUP_ERROR}), 503


@app.errorhandler(JointRuleConflictError)
@app.errorhandler(RuleValidationError)
def handle_rule_error(error):
    return jsonify({"error": str(error)}), 400


# ── Frontend ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ── Cascading dropdown endpoints ─────────────────────────────────────────────
@app.route("/api/faculties")
def api_faculties():
    return jsonify(get_faculties())


@app.route("/api/programmes")
def api_programmes():
    fac_id = request.args.get("faculty_id", type=int)
    return jsonify(get_programmes(fac_id))


@app.route("/api/classes")
def api_classes():
    prog_id = request.args.get("programme_id", type=int)
    fac_id = request.args.get("faculty_id", type=int)
    return jsonify(get_classes(prog_id, fac_id))


@app.route("/api/academic-years")
def api_academic_years():
    return jsonify(get_academic_years())


@app.route("/api/rules")
def api_rules():
    """Read-only reference derived directly from the approved document wording."""
    return jsonify([
        {"code": code, "summary": " ".join(text["en"]) or "No additional marking-rule condition.",
         "paragraphs": text}
        for code, text in sorted(RULE_PARAGRAPHS.items())
    ])


@app.errorhandler(RequestEntityTooLarge)
def handle_upload_too_large(error):
    return jsonify({"error": "Template uploads must be at most 10 MB each and 32 MB in total."}), 413


@app.route("/api/templates/convert", methods=["POST"])
def api_convert_templates():
    token = app.config["TEMPLATE_ADMIN_TOKEN"]
    if not token:
        return jsonify({"error": "Template updates are disabled. Ask an administrator to configure TEMPLATE_ADMIN_TOKEN."}), 503
    provided = request.headers.get("Authorization", "")
    if not secrets.compare_digest(provided.encode(), f"Bearer {token}".encode()):
        return jsonify({"error": "An authorized administrator token is required."}), 401
    if not app.config["TEMPLATE_STORAGE_CONFIGURED"]:
        return jsonify({"error": "Template updates are disabled until an administrator configures TEMPLATE_STORAGE_DIR on persistent storage."}), 503
    request.max_content_length = MAX_REQUEST_BYTES
    try:
        uploads = {}
        for lang in ("en", "zh", "pt"):
            files = request.files.getlist(lang)
            if len(files) > 1:
                raise TemplateUpdateError(f"Upload exactly one {lang.upper()} template")
            if files:
                uploads[lang] = files[0]
        backup_id = update_templates(uploads, app.config["TEMPLATE_DIR"])
        return jsonify({"message": "All EN/ZH/PT templates converted, validated and activated successfully. Previous templates were backed up.", "backup_id": backup_id})
    except TemplateUpdateError as exc:
        return jsonify({"error": str(exc)}), 400
    except RequestEntityTooLarge:
        raise
    except Exception:
        app.logger.error("Template activation failed; check persistent storage and recovery journal")
        return jsonify({"error": "Template activation failed. Generation is blocked if recovery is incomplete; contact the administrator."}), 500


# ── Generate templates ───────────────────────────────────────────────────────
@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True) or {}

    faculty_id = data.get("faculty_id")
    programme_id = data.get("programme_id")
    class_ids = data.get("class_ids")  # list of ints, or None
    academic_year = data.get("academic_year", "")
    semester = data.get("semester", "")

    # Resolve complete joint content and validate every member's Rule, while
    # retaining scope-matching output_class_codes for individual packages.
    if class_ids:
        classes = get_classes_full(class_ids=class_ids)
    elif programme_id:
        classes = get_classes_full(programme_id=programme_id)
    elif faculty_id:
        classes = get_classes_full(faculty_id=faculty_id)
    else:
        return jsonify({"error": "Please select at least a faculty"}), 400

    if not classes:
        return jsonify({"error": "No classes found for this selection"}), 404

    try:
        zip_buf = generate_batch(classes, academic_year=academic_year, semester=semester)
    except (JointRuleConflictError, RuleValidationError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400

    return send_file(
        zip_buf,
        as_attachment=True,
        download_name=batch_download_name(academic_year, semester),
        mimetype="application/zip",
    )


# ── Import Excel data ─────────────────────────────────────────────────────────
@app.route("/api/import-excel", methods=["POST"])
def api_import_excel():
    global DATABASE_STARTUP_ERROR
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({"error": f"Invalid file type '{ext}'. Please upload .xlsx or .xls"}), 400

    with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
        f.save(tmp.name)
        tmp_path = tmp.name

    try:
        result = import_data(tmp_path)
        # Re-initialise the DB connection so new data is visible immediately
        init_db()
        DATABASE_STARTUP_ERROR = None
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        os.unlink(tmp_path)


@app.route("/api/column-format")
def api_column_format():
    """Return the expected Excel column format."""
    return jsonify(COLUMN_MAP)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    app.run(debug=False, host="0.0.0.0", port=port)
