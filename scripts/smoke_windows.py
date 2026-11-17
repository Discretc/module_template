"""Exercise the real desktop process over HTTP, including a complete restart.

Builds call --executable; --source runs the same checks without claiming an EXE
was tested. Fixtures are synthetic authoritative-format workbooks and official
template-slot fixtures derived from the tracked runtime DOCX files.
"""
from contextlib import closing
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import build_opener, ProxyHandler, Request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]

from desktop_auth import AdministratorCredentials
from desktop_runtime import healthy

HTTP = build_opener(ProxyHandler({}))
MARKER = "Desktop persistence smoke fixture"
CODES = ("TEST1000-111", "TEST1000-112")


def workbook_bytes():
    from openpyxl import Workbook
    from import_excel import COLUMN_MAP
    book = Workbook()
    sheet = book.active
    sheet.append(list(COLUMN_MAP.values()))
    for index, code in enumerate((*CODES, CODES[0])):
        fields = {
            "faculty_code": "TEST", "faculty_zh": "測試學院", "faculty_en": "Test Faculty", "faculty_pt": "Faculdade de Teste",
            "prog_code": "P1" if code == CODES[0] else "P2", "prog_zh": "學士課程", "prog_en": "Bachelor Programme", "prog_pt": "Curso de Licenciatura",
            "class_code": code, "module_name_zh": "測試單元", "module_name_en": "Test Module", "module_name_pt": "Módulo de Teste",
            "prerequisite_code": "FND1000", "prerequisite_en": "Foundation", "prerequisite_zh": "基礎", "prerequisite_pt": "Fundamentos",
            "credits": 3, "duration": 45, "instructor_en": "Second Instructor" if index == 2 else "First Instructor",
            "instructor_zh": "教師二" if index == 2 else "教師一", "instructor_pt": "Docente Dois" if index == 2 else "Docente Um",
            "email": f"teacher{index}@example.edu", "room_zh": "科研樓 2", "room_en": "Ignored room", "room_pt": "Ignored room",
            "telephone": "12345678", "rule_code": 2, "joint_relationship": CODES[1] if code == CODES[0] else CODES[0],
        }
        sheet.append([fields[field] for field in COLUMN_MAP])
    content = io.BytesIO()
    book.save(content)
    return content.getvalue()


def official_fixture(language):
    from docx import Document
    from generator import _attendance_text
    slots = {
        "en": ("[Name of academic unit]", "[Programme name]", "[Insert marking scheme]"),
        "zh": ("[學術單位名稱]", "[課程名稱]", "[插入評分準則]"),
        "pt": ("[nome da unidade académica]", "[designação do curso]", "[Inserir o critério de classificação]"),
    }
    content = io.BytesIO()
    with zipfile.ZipFile(ROOT / "backend" / "templates" / f"template_{language}.docx") as source, zipfile.ZipFile(content, "w") as target:
        for entry in source.infolist():
            payload = source.read(entry.filename)
            if entry.filename.endswith(".xml"):
                text = payload.decode("utf-8")
                unit, programme, marking = slots[language]
                text = text.replace("{{ academic_unit }}", unit).replace("{{ programme_name }}", programme)
                text = text.replace("{{ attendance_text }}", _attendance_text("bachelor", language))
                text = text.replace("__MARKING_RULE_BLOCK__", marking)
                payload = re.sub(r"{{\s*\w+\s*}}", "", text).encode("utf-8")
            target.writestr(entry, payload)
    doc = Document(io.BytesIO(content.getvalue()))
    doc.core_properties.comments = MARKER
    output = io.BytesIO()
    doc.save(output)
    return output.getvalue()


def multipart(files):
    from werkzeug.datastructures import FileStorage
    from werkzeug.test import encode_multipart
    boundary, data = encode_multipart({key: FileStorage(io.BytesIO(content), filename=name)
                                       for key, (name, content) in files.items()})
    return data, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def request(url, path, *, body=None, headers=None, expected=200):
    req = Request(url + path, data=body, headers=headers or {})
    try:
        response = HTTP.open(req, timeout=90)
    except HTTPError as error:
        response = error
    with response:
        data = response.read()
        if response.status != expected:
            raise AssertionError(f"{path}: expected {expected}, got {response.status}: {data[:500]!r}")
        return data


def start(command, data, cwd):
    env = dict(os.environ)
    for name in ("TEMPLATE_STORAGE_DIR", "MODULE_OUTLINE_DATA_DIR", "MODULE_OUTLINE_DESKTOP"):
        env.pop(name, None)
    # A hosted token must not authorize desktop updates.
    env["TEMPLATE_ADMIN_TOKEN"] = "hosted-token-must-not-work"
    process = subprocess.Popen([*command, "--headless", "--no-browser", "--data-dir", str(data)],
                               cwd=cwd, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise AssertionError(f"Desktop process exited during startup ({process.returncode}); inspect {data / 'logs/desktop.log'}")
            try:
                state = json.loads((data / "instance.json").read_text(encoding="utf-8"))
                if healthy(state["url"], state["nonce"]):
                    return process, state
            except (OSError, ValueError):
                pass
            time.sleep(0.1)
        raise AssertionError("Desktop startup timed out")
    except BaseException:
        process.kill()
        process.wait(timeout=10)
        raise


def stop(process, data):
    (data / ".stop-request").touch()
    try:
        result = process.wait(timeout=30)
        if result != 0:
            raise AssertionError(f"Unclean desktop exit: {result}")
    except BaseException:
        process.kill()
        process.wait(timeout=10)
        raise


def check_download(url, *, updated=False):
    from docx import Document
    faculties = json.loads(request(url, "/api/faculties"))
    programmes = json.loads(request(url, f"/api/programmes?faculty_id={faculties[0]['id']}"))
    assert len(programmes) == 2
    classes = json.loads(request(url, f"/api/classes?faculty_id={faculties[0]['id']}"))
    assert len(classes) >= 1 and classes[0]["joint_class"]
    body = json.dumps({"faculty_id": faculties[0]["id"], "academic_year": "2026/2027", "semester": "1"}).encode()
    content = request(url, "/api/generate", body=body, headers={"Content-Type": "application/json"})
    with zipfile.ZipFile(io.BytesIO(content)) as outer:
        assert outer.namelist() == [code + ".zip" for code in CODES]
        for code in CODES:
            with zipfile.ZipFile(io.BytesIO(outer.read(code + ".zip"))) as inner:
                assert inner.namelist() == [f"{code}_{language}.docx" for language in ("EN", "ZH", "PT")]
                for language in ("EN", "ZH", "PT"):
                    document = Document(io.BytesIO(inner.read(f"{code}_{language}.docx")))
                    assert document.tables[0].cell(1, 1).text == ", ".join(CODES)
                    assert document.tables[0].cell(4, 1).text == {"EN": "English", "ZH": "中文", "PT": "Português"}[language]
                    text = "\n".join(cell.text for table in document.tables for row in table.rows for cell in row.cells)
                    assert "科研樓 2" in text and "FND1000" in text
                    if language == "EN":
                        assert "First Instructor" in text and "Second Instructor" in text
                    if updated:
                        assert document.core_properties.comments == MARKER


def run_smoke(command, data, cwd, *, occupied_default=False):
    password = secrets.token_urlsafe(24) + "測試"
    credentials = AdministratorCredentials(data / "data" / "administrator.json")
    credentials.establish(password)
    original_verifier = credentials.path.read_bytes()
    process, state = start(command, data, cwd)
    try:
        url = state["url"]
        if occupied_default:
            assert url != "http://127.0.0.1:5001", "Desktop failed to choose another local port"
        assert b"Module Outline Generator" in request(url, "/")
        assert json.loads(request(url, "/api/runtime")) == {"desktop": True}
        request(url, "/api/faculties", headers={"Origin": "https://untrusted.example"}, expected=403)
        request(url, "/api/templates/convert", body=b"", expected=401)
        request(url, "/api/templates/convert", body=b"", headers={"Authorization": "Bearer hosted-token-must-not-work"}, expected=401)
        body, headers = multipart({"file": ("教務 master.xlsx", workbook_bytes())})
        imported = json.loads(request(url, "/api/import-excel", body=body, headers=headers))
        assert (imported["total_rows"], imported["classes"], imported["joint_groups"]) == (3, 2, 1)
        check_download(url)
        files = {lang: (f"教務_{lang}_Português.docx", official_fixture(lang)) for lang in ("en", "zh", "pt")}
        body, headers = multipart(files)
        headers["Authorization"] = "Desktop " + quote(password, safe="")
        result = json.loads(request(url, "/api/templates/convert", body=body, headers=headers))
        backup = data / ".template-backups" / result["backup_id"]
        assert len(list(backup.glob("*.docx"))) == 3
        snapshot = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (data / "templates").glob("*.docx")}
        check_download(url, updated=True)
        duplicate = subprocess.run([*command, "--headless", "--no-browser", "--data-dir", str(data)], cwd=cwd, timeout=30)
        assert duplicate.returncode == 0
        assert json.loads((data / "instance.json").read_text(encoding="utf-8")) == state
    finally:
        stop(process, data)
    assert not healthy(state["url"], state["nonce"])
    assert not (data / "instance.json").exists()
    with closing(sqlite3.connect(data / "data" / "module_outlines.db")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM classes").fetchone()[0] == 2
    process, state = start(command, data, cwd)
    try:
        check_download(state["url"], updated=True)
        assert snapshot == {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (data / "templates").glob("*.docx")}
        assert credentials.path.read_bytes() == original_verifier
        assert list((data / "output").rglob("*.zip"))
        assert password not in (data / "logs" / "desktop.log").read_text(encoding="utf-8")
    finally:
        stop(process, data)


def main():
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--executable", type=Path)
    mode.add_argument("--source", action="store_true")
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="Module smoke 測試 ") as temporary:
        root = Path(temporary)
        if args.executable:
            if os.name != "nt":
                raise SystemExit("Windows executable smoke tests must run on Windows.")
            distribution = root / "Extracted application 葡文"
            shutil.copytree(args.executable.resolve().parent, distribution)
            command = [str(distribution / args.executable.name)]
        else:
            command = [sys.executable, str(ROOT / "desktop_launcher.py")]
        with socket.socket() as conflict:
            try:
                if os.name == "nt":
                    conflict.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                conflict.bind(("127.0.0.1", 5001))
                conflict.listen()
                occupied_default = True
            except OSError:
                conflict.close()  # Another program may already have this port.
                occupied_default = False
            run_smoke(command, root / "Local data 教務", root, occupied_default=occupied_default)
    print("PASS: desktop HTTP startup, local import, repeated rows, joint EN/ZH/PT nested ZIPs, administrator authentication, Unicode template conversion/backups, duplicate launch, port conflict, clean shutdown, restart and persistent data/templates.")
    print("Mode: compiled Windows executable" if args.executable else "Mode: Python source (no Windows executable tested)")


if __name__ == "__main__":
    main()
