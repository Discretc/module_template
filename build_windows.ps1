[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$ProjectRoot = $PSScriptRoot
if ($env:OS -ne 'Windows_NT') { throw 'Build this package on 64-bit Windows 10/11 or windows-latest.' }

function Invoke-Checked {
    param([string]$Program, [string[]]$Arguments)
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Command failed (exit $LASTEXITCODE): $Program" }
}

Push-Location $ProjectRoot
$EnvironmentNames = @('PYTHONPATH', 'PYTHONUTF8', 'TEMPLATE_ADMIN_TOKEN', 'TEMPLATE_STORAGE_DIR', 'MODULE_OUTLINE_DATA_DIR', 'MODULE_OUTLINE_DESKTOP')
$PreviousEnvironment = @{}
foreach ($Name in $EnvironmentNames) {
    $PreviousEnvironment[$Name] = [Environment]::GetEnvironmentVariable($Name, 'Process')
    [Environment]::SetEnvironmentVariable($Name, $null, 'Process')
}
try {
    $env:PYTHONUTF8 = '1'
    # GitHub setup-python and normal python.org installations both expose python.
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        throw 'The build machine needs 64-bit Python 3.11 or 3.12 from python.org (including Tcl/Tk). End users do not need Python.'
    }
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw 'The existing frontend regression test needs Node.js on the build machine. The packaged application does not need Node.js.'
    }
    Invoke-Checked 'python' @('-c', 'import struct,sys,tkinter; assert (3,11) <= sys.version_info[:2] < (3,13) and struct.calcsize("P")==8, "Use 64-bit Python 3.11/3.12"')
    Invoke-Checked 'python' @('-m', 'venv', '.build-venv')
    $BuildPython = Join-Path $ProjectRoot '.build-venv\Scripts\python.exe'
    Invoke-Checked $BuildPython @('-m', 'pip', 'install', '--upgrade', 'pip')
    Invoke-Checked $BuildPython @('-m', 'pip', 'install', '-r', 'requirements-windows-build.txt')
    Invoke-Checked $BuildPython @('-m', 'pip', 'check')
    $env:PYTHONPATH = "$ProjectRoot;$ProjectRoot\backend"
    Invoke-Checked $BuildPython @('-m', 'unittest', 'discover', '-s', 'tests', '-v')
    Invoke-Checked $BuildPython @('-m', 'compileall', '-q', 'backend', 'desktop_launcher.py', 'desktop_runtime.py', 'desktop_auth.py', 'scripts/smoke_windows.py')
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Invoke-Checked 'git' @('diff', '--check')
    }
    Invoke-Checked $BuildPython @('-m', 'PyInstaller', '--clean', '--noconfirm', 'ModuleOutlineGenerator.spec')
    $Distribution = Join-Path $ProjectRoot 'dist\ModuleOutlineGenerator-Windows'
    Copy-Item 'README-Windows.md' (Join-Path $Distribution 'README-Windows.txt')
    Copy-Item 'README-Windows.md' (Join-Path $Distribution 'README-Windows.md')
    Copy-Item 'scripts\Reset Administrator.cmd' $Distribution
    # Test the compiled executable from a path containing spaces and Unicode.
    Invoke-Checked $BuildPython @('scripts/smoke_windows.py', '--executable', (Join-Path $Distribution 'ModuleOutlineGenerator.exe'))
    Invoke-Checked $BuildPython @('-m', 'pip', 'freeze') | Out-File (Join-Path $Distribution 'build-dependencies.txt') -Encoding utf8
    New-Item -ItemType Directory -Force 'release' | Out-Null
    $Archive = Join-Path $ProjectRoot 'release\ModuleOutlineGenerator-Windows.zip'
    Compress-Archive -Path $Distribution -DestinationPath $Archive -Force
    Write-Host "Built and smoke tested: $Archive"
    Write-Host 'Complete the interactive browser/launcher checklist in README-Windows.md before distributing to staff.'
}
finally {
    foreach ($Name in $EnvironmentNames) {
        [Environment]::SetEnvironmentVariable($Name, $PreviousEnvironment[$Name], 'Process')
    }
    Pop-Location
}
