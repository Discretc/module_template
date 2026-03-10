"""
app.py  –  Flask application
-----------------------------
Endpoints:
    GET  /                          → serves the frontend SPA
    GET  /api/modules/search?q=     → search / autocomplete
    GET  /api/modules/<code>        → module detail JSON
    GET  /api/generate/<code>       → download generated .docx
"""

import os
from flask import Flask, jsonify, request, send_file, send_from_directory
from flask_cors import CORS

from database import init_db, get_module, search_modules
from generator import generate_module_outline

app = Flask(__name__, static_folder="../frontend", static_url_path="")
CORS(app)


# ---------------------------------------------------------------------------
# Initialise DB on first import
# ---------------------------------------------------------------------------
init_db()


# ---------------------------------------------------------------------------
# Frontend – serve static files
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


# ---------------------------------------------------------------------------
# API – search modules (for autocomplete / listing)
# ---------------------------------------------------------------------------
@app.route("/api/modules/search")
def api_search_modules():
    q = request.args.get("q", "").strip()
    if len(q) < 1:
        return jsonify([])
    results = search_modules(q)
    return jsonify(results)


# ---------------------------------------------------------------------------
# API – get single module detail
# ---------------------------------------------------------------------------
@app.route("/api/modules/<module_code>")
def api_get_module(module_code: str):
    data = get_module(module_code)
    if data is None:
        return jsonify({"error": "Module not found"}), 404
    return jsonify(data)


# ---------------------------------------------------------------------------
# API – generate & download the filled Word document
# ---------------------------------------------------------------------------
@app.route("/api/generate/<module_code>")
def api_generate(module_code: str):
    module_data = get_module(module_code)
    if module_data is None:
        return jsonify({"error": "Module not found"}), 404

    # Accept optional overrides via query parameters
    # (semester, academic_year, instructor, email, office, office_phone)
    for key in ("semester", "academic_year", "instructor", "email", "office", "office_phone"):
        val = request.args.get(key, "").strip()
        if val:
            module_data[key] = val

    buf = generate_module_outline(module_data)
    filename = f"{module_code.upper()}_Module_Outline.docx"

    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
