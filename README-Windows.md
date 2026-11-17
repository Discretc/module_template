# Module Outline Generator for Windows

For university faculty staff using Windows 10 or Windows 11, 64-bit.
Python, Git and Microsoft Word are not needed to generate documents.

## Download and extract

1. Obtain **ModuleOutlineGenerator-Windows.zip** from your university coordinator.
   If your coordinator publishes packages on the [project's Releases page](https://github.com/Discretc/module_template/releases), download the Windows ZIP there.
   The source-code ZIP is not the Windows application.
2. Right-click the downloaded ZIP and choose **Extract All**.
3. Open the extracted **ModuleOutlineGenerator-Windows** folder.
   Keep its files together, including **_internal**. Do not run the EXE inside the ZIP.
   You may keep the extracted folder in Downloads or move it elsewhere.

## Launch and first-time administrator setup

Double-click **ModuleOutlineGenerator.exe**. A small application status window appears.
On the first launch, an administrator must choose and confirm a password of 12–256 characters.
Use a unique password or passphrase and keep it somewhere safe. There is no default password.
Cancelling setup closes the application without enabling template updates.

Once the application is ready, your default browser opens the usual Module Outline Generator page.
The browser address starts with **http://127.0.0.1:**. This is a service on your own computer.
The port is usually 5001; another available port is chosen automatically when needed.
Internet access is not needed for import or document generation.

Keep the small application window open while working. If the browser does not open,
click **Open Browser** or copy the address shown in that window into your browser.
Double-clicking the EXE again reopens the existing application rather than starting another server.

Each Windows account has its own data, templates and administrator password.
Other faculty staff using the same Windows account do not need the password for normal generation or Excel import.

## Import the Excel master file

1. In **Data Management — Import from Excel**, click the file chooser.
2. Select the approved master workbook, normally an **.xlsx** file.
3. Click **Upload & Import** and check the result and any warnings.

Import replaces the current dataset. Back up your data first if you need to retain the previous dataset.
Use the authoritative workbook headings shown in **Required Excel Columns**.
Repeated class rows, instructors and prerequisite records are combined automatically.
Rules 1–4 must be entered explicitly; the **Rule Reference** explains their wording.
Keep all members of each joint class in the workbook and resolve conflicting rules before generating.

## Generate and download documents

1. Choose the academic year and semester.
2. Choose a faculty. Optionally narrow the selection to a programme or class.
3. Click **Download Module Outlines (.zip)**.
4. Open the downloaded ZIP in your browser's Downloads folder, or choose **Save as** if prompted.

The download contains a separate ZIP package for each selected class. Each class package contains English,
Chinese and Portuguese DOCX files. Joint-class documents include the complete joint group;
each selected joint member receives its own package.
Files use class codes and language suffixes such as **TEST1000-111_EN.docx**.
Copies also remain in the application's local **output** folder.

You can open or edit DOCX files in Microsoft Word or another compatible word processor.
Word is not needed by the generator. If text looks different on another computer, check that
the fonts used in the official university templates, including Chinese fonts, are installed.
The application preserves template formatting; it does not install or embed fonts.

## Update official templates — administrator only

Use this feature only when the university issues new official templates.

1. Expand **Convert / Update Official Templates — Administrator**.
2. Enter the administrator password established on this computer.
3. Select all three official English, Chinese and Portuguese **DOCX** files.
   Each file must be at most 10 MB. A legacy **.doc** file must first be saved as DOCX
   using Word or another tool that preserves its tables and layout.
4. Click **Convert & Validate** and wait for confirmation.

All three templates are staged, converted and validated before activation.
If validation fails, the previous templates stay active. Successful updates keep a backup and
remain active after closing, restarting, or replacing the application folder with a newer release.
Keep the backup reference shown after a successful update.

The password is cleared from the form after each attempt. It is not saved in the browser.
Five incorrect password attempts temporarily block authentication for 30 seconds.

### Forgotten administrator password

1. Stop the application using its status window.
2. Double-click **Reset Administrator.cmd** in the extracted application folder.
3. Confirm that you want to replace the local administrator password.
4. Choose and confirm a new password. The application then starts normally.

Reset keeps your imported data and templates. Cancelling keeps the existing password.
Do not delete the credential file to reset the password. Missing or damaged credentials require this explicit reset.
Anyone with access to your Windows account and its application data can perform this recovery;
protect your Windows sign-in and use separate accounts where appropriate.

## Close the application

Finish any import, generation or update, then click **Stop Application** in the small status window.
Closing that window with **X** also stops the server and waits for active file operations to finish.
You can then close the browser tab. Closing only the browser tab leaves the application running.
Avoid ending the process in Task Manager during a file operation.

## Where data is stored

Press **Windows + R**, paste **%LOCALAPPDATA%\ModuleOutlineGenerator**, and press Enter.
This opens the data folder in File Explorer; you do not need a terminal.

| Folder or file | Contents |
| --- | --- |
| **data\module_outlines.db** | Imported faculty, programme and class data |
| **data\administrator.json** | Salted administrator password hash; no readable password |
| **templates** | Active EN/ZH/PT runtime templates |
| **.template-backups** | Previous template sets, grouped by backup reference |
| **output** | Generated DOCX files and class ZIP packages |
| **logs** | Startup and application diagnostics |

Other small files coordinate the running application and recover interrupted template updates.
Keep them when making a full backup. Do not edit the **_internal** folder or copy a database into it.
Your browser's downloaded ZIP is separate from these application files.
The first launch includes demonstration data; importing your approved master file replaces it.
Subsequent launches preserve your dataset, including an intentionally empty database.

## Back up and restore

Stop the application. Copy the entire **%LOCALAPPDATA%\ModuleOutlineGenerator** folder
to a secure backup location, with the date in the backup folder name. Keep a copy of the master workbook too.
The backup contains university data and the password hash, so protect access to it.

To restore, stop the application, keep a separate copy of the current folder, then restore
the complete backed-up folder to the same location. Launch the application again.
The restored administrator password will apply. Use **Reset Administrator.cmd** if it is unknown.
Deleting the extracted program folder does not delete your data; deleting the local data folder does.

If an interrupted template update cannot recover automatically, stop the application and contact
your coordinator. Restore a complete data-folder backup rather than replacing only one language template.

## Troubleshooting

- **Windows or antivirus asks about an unknown application:** verify that the ZIP came from your university coordinator.
  The build may be unsigned. Ask university IT to verify or approve it under local policy; do not disable antivirus.
- **Missing resources or _internal:** extract the complete ZIP again. Moving only the EXE will not work.
- **A firewall prompt appears:** this application only uses the local loopback interface. It does not need public-network access.
- **The browser cannot connect:** keep the status window open and use its current address. A bookmarked old port may be wrong.
- **Already open:** find the existing application window, including any first-time password dialog. Stop that instance before resetting credentials.
- **Cannot save or start:** confirm that your Windows account can write to the local application data folder and that the disk has space.
  Security software may need approval from university IT.
- **Excel import fails:** check the approved column headings, explicit Rule values, and joint-class relationships. The error explains the offending row where possible.
- **Template update fails:** supply all three original official DOCX files. Prepared runtime templates, legacy DOC files, damaged documents and unsupported layouts are rejected.
- **Credential file is missing or damaged:** use **Reset Administrator.cmd**. Authentication is never silently disabled.
- **Template set is incomplete:** restore a complete backup or ask your coordinator for help. The application deliberately avoids mixing versions.
- **After a crash:** launch again. The operating system releases the instance lock, and interrupted template activation attempts recovery automatically.
- **More help:** send your coordinator the error message and the **logs** folder. Never send your password.

## Coordinator's interactive release check

Before supplying a newly built package to staff, use a clean Windows 10/11 account without Python:

1. Extract the ZIP into a folder containing spaces and launch the EXE.
2. Establish the first administrator password; confirm masking and confirmation work.
3. Confirm the browser opens automatically and the status window shows a loopback address.
4. Import a valid approved master workbook through the browser file chooser.
5. Exercise faculty/programme/class selection, academic year, semester and Rule display.
6. Download a mixed batch including joint classes; inspect every inner ZIP and all three document languages,
   including formatting, hyperlinks, teachers, prerequisites and Room_Chn.
7. Reject an incorrect administrator password, then convert and activate approved new EN/ZH/PT templates.
8. Close the status window; confirm the browser address stops responding.
9. Relaunch and confirm imported data and updated templates remain. Generate again.
10. Check duplicate launches, password reset, a busy port 5001, and a non-ASCII Windows username.

The automated build checks the compiled server and files. This interactive check also verifies
the actual browser, launcher dialogs, Windows security prompts and document appearance.
