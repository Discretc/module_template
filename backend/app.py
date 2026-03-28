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
from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

import tempfile

from database import init_db, get_faculties, get_programmes, get_classes, get_classes_full
from generator import generate_batch
from import_excel import import_data, COLUMN_MAP

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)

ALLOWED_EXTENSIONS = {".xlsx", ".xls"}

init_db()


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


# ── Generate templates ───────────────────────────────────────────────────────
@app.route("/api/generate", methods=["POST"])
def api_generate():
    data = request.get_json(silent=True) or {}

    faculty_id = data.get("faculty_id")
    programme_id = data.get("programme_id")
    class_ids = data.get("class_ids")  # list of ints, or None
    academic_year = data.get("academic_year", "")
    semester = data.get("semester", "")

    # Fetch classes based on selection scope
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

    zip_buf = generate_batch(classes, academic_year=academic_year, semester=semester)

    return send_file(
        zip_buf,
        as_attachment=True,
        download_name="Module_Outlines.zip",
        mimetype="application/zip",
    )


# ── Import Excel data ─────────────────────────────────────────────────────────
@app.route("/api/import-excel", methods=["POST"])
def api_import_excel():
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
