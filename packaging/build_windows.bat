@echo off
REM build_windows.bat — Reproducible PyInstaller build for FFExplorer (Windows)
REM
REM Usage:
REM   From the repo root:   packaging\build_windows.bat
REM   Or directly:          cd packaging && build_windows.bat
REM
REM Prerequisites:
REM   py -3.13 -m pip install "pyinstaller~=6.20.0" "PySide6~=6.11.1" Pillow
REM
REM IMPORTANT — interpreter note:
REM   This script unconditionally calls  py -3.13  (the Python 3.13 launcher)
REM   because the bare `python` on the session PATH may resolve to an older
REM   interpreter.  Python 3.13.13 is the campaign-standard build interpreter
REM   (FastMCP caps the stack at 3.13).
REM
REM Output:   packaging\bin\FFExplorer\FFExplorer.exe   (one-dir bundle)

setlocal enabledelayedexpansion

REM Resolve repo root as the parent of this script's directory
set "SCRIPT_DIR=%~dp0"
set "REPO_ROOT=%SCRIPT_DIR%.."

REM Canonicalise REPO_ROOT
pushd "%REPO_ROOT%"
set "REPO_ROOT=%CD%"
popd

echo [build_windows] Repo root : %REPO_ROOT%
echo [build_windows] Spec file : %SCRIPT_DIR%FFExplorer.spec

REM Optional: generate .ico from Logo FFE.png if it does not exist yet
if not exist "%REPO_ROOT%\Logo FFE.ico" (
    echo [build_windows] Logo FFE.ico not found -- running png_to_ico.py ...
    py -3.13 "%SCRIPT_DIR%scripts\png_to_ico.py" "%REPO_ROOT%\Logo FFE.png" "%REPO_ROOT%\Logo FFE.ico"
    if errorlevel 1 (
        echo [build_windows] WARNING: PNG-to-ICO conversion failed. Building without icon.
    ) else (
        echo [build_windows] Logo FFE.ico created.
    )
)

REM Run PyInstaller from the repo root so relative datas paths resolve correctly.
REM Use py -3.13 -m PyInstaller to guarantee the 3.13 interpreter regardless of
REM which python is first on PATH.
REM Use forward slashes in paths to avoid bash-escaping issues.
cd /d "%REPO_ROOT%"
py -3.13 -m PyInstaller packaging/FFExplorer.spec ^
    --noconfirm ^
    --distpath packaging/bin ^
    --workpath packaging/work ^
    --log-level WARN

if errorlevel 1 (
    echo [build_windows] ERROR: PyInstaller exited with an error.
    exit /b 1
)

echo.
echo [build_windows] Build complete.
echo [build_windows] Executable : %SCRIPT_DIR%bin\FFExplorer\FFExplorer.exe
exit /b 0
