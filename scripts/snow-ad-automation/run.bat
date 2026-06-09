@echo off
REM Quick runner script for AD Group automation (Windows)

set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM Check if venv exists, if not run setup
if not exist ".venv" (
    echo ⚠️ Virtual environment not found. Running setup...
    call setup.bat
)

REM Activate and run
call .venv\Scripts\activate.bat
python ad_group_request.py %*
