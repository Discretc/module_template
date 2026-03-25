# Module Outline Generator

An internal web tool for Macao Polytechnic University that generates pre-filled
Module Outline Word documents in three languages (English, Chinese, Portuguese).

Users select a faculty, programme, or individual class from cascading dropdown
menus. The system retrieves all data from a database and produces a downloadable
.zip archive containing .docx files for every selected class in all three
languages. Generated files are also saved on the server in the `output/` folder.


## Project Structure

    module_template_app/
    |
    |-- backend/
    |   |-- app.py                  Flask application and API routes
    |   |-- database.py             SQLite connection and query helpers
    |   |-- generator.py            Trilingual Word document rendering (docxtpl)
    |   |-- convert_template.py     One-time script to prepare Word templates
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

4. Convert the Word templates into docxtpl templates

   This is a one-time step that reads the original university Word templates
   (EN, ZH, PT) and inserts Jinja2 placeholder tags for all auto-filled fields.

        python backend/convert_template.py

   This creates three files in `backend/templates/`:
   `template_en.docx`, `template_zh.docx`, `template_pt.docx`

5. Run the application

        python backend/app.py

   The database is created and seeded with sample data automatically on first
   run. The app starts on port **5001**.

6. Open the application in your browser

        http://127.0.0.1:5001


## How to Use

1. Select the **Academic Year** and **Semester**
2. Choose a **Faculty** from the dropdown
3. Optionally narrow down to a specific **Programme** or **Class**
4. Click **"Download Module Outlines (.zip)"**
5. The browser downloads a .zip containing EN, ZH, and PT Word documents for
   every class in the selected scope
6. Open the .docx files in Word and complete the remaining sections

**Batch generation:** leave the Programme and Class dropdowns at their default
("all") to generate documents for every class in the selected faculty at once.


## API Endpoints

    GET  /api/faculties                          List all faculties
    GET  /api/programmes?faculty_id=             Programmes filtered by faculty
    GET  /api/classes?programme_id=&faculty_id=  Classes filtered by programme or faculty
    POST /api/generate                           Generate and download a .zip

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

The Excel file should have one sheet where each row is a class, with columns:

    Faculty_Code | Faculty_Eng | Faculty_Chn | Faculty_Prt
    Prog_Code | Prog_Eng | Prog_Chn | Prog_Prt
    Class_Code | Module_Eng | Module_Chn | Module_Prt
    Prerequisite_Eng | Prerequisite_Chn | Prerequisite_Por
    Credits | Durations
    Instructor_Eng | Instructor_Chn | Instructor_Prt
    Email | Room_Eng | Room_Chn | Room_Prt | Telephone

If your file uses different column header names, open `backend/import_excel.py`
and update the `COLUMN_MAP` dictionary at the top of the file.


## Reseeding the Database (development)

To reset the database and reload the sample data:

    rm backend/module_outlines.db
    python backend/app.py
