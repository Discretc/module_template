# Module Outline Generator

An internal web tool for Macao Polytechnic University that allows lecturers to
generate a pre-filled Module Outline Word document by entering a module code.

The system retrieves module data from a database and produces a downloadable
.docx file with fields such as module code, module name, degree level,
prerequisites, and credits already filled in. The lecturer then opens the
document and completes the remaining sections manually.


## Project Structure

    module_template_app/
    |
    |-- backend/
    |   |-- app.py                  Flask application and API routes
    |   |-- database.py             SQLite connection and query helpers
    |   |-- generator.py            Word document rendering with docxtpl
    |   |-- convert_template.py     One-time script to prepare the Word template
    |   |-- schema.sql              Database schema
    |   |-- seed.sql                Sample data for development
    |   |-- templates/
    |       |-- module_outline_template.docx    The Jinja2-tagged Word template
    |
    |-- frontend/
    |   |-- index.html              Single-page web interface
    |
    |-- requirements.txt


## Prerequisites

Python 3.10 or higher is required.

You also need the original English Module Outline Template (.docx) from the
university. Place it at this path before running the setup:

    Module Outline Templates/module-outline-template_en_202305.docx


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

4. Convert the Word template into a docxtpl template

   This is a one-time step that reads the original university Word template and
   inserts Jinja2 placeholder tags for all auto-filled fields.

        python backend/convert_template.py

   This creates the file: backend/templates/module_outline_template.docx

5. Run the application

        python backend/app.py

   The database is created and seeded automatically on first run.

6. Open the application in your browser

        http://127.0.0.1:5000


## How to Use

1. Type a module code into the search box (for example: COMP1121)
2. Select the module from the suggestions
3. Optionally fill in the semester, instructor name, email, and office details
4. Click "Download Module Outline"
5. Open the downloaded .docx file in Word and complete the remaining sections


## API Endpoints

    GET /api/modules/search?q=      Search modules by code or name
    GET /api/modules/<code>         Get full details for a module
    GET /api/generate/<code>        Download the generated Word document

The generate endpoint also accepts optional query parameters:
academic_year, semester, instructor, email, office, office_phone


## Importing Real Data from Excel

When you have the real university data in an Excel file, use the import script
instead of the sample seed data.

    python backend/import_excel.py path/to/your_data.xlsx

The script will wipe the existing data and replace it with everything in the
Excel file. Restart the Flask app afterwards.

The Excel file should have one sheet where each row is a module, with columns:

    Module Code | Module Name | Programme Name | Degree Level | Academic Unit
    Pre-requisite(s) | Medium of Instruction | Credits | Contact Hours

If your file uses different column header names, open backend/import_excel.py
and update the COLUMN MAP section at the top of the file. The keys on the left
are internal names that must not be changed; only the values on the right need
to match your Excel headers.

If your programmes are listed on a separate sheet, set PROGRAMME_SHEET to the
sheet name and update PROGRAMME_COLUMN_MAP in the same section.


## Adding Modules to the Database (development)

Open backend/seed.sql to add sample modules, then delete the existing database
file and restart the app to reseed.

    rm backend/module_outlines.db
    python backend/app.py
