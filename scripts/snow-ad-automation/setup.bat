@echo off
REM Setup script for ServiceNow AD Group Automation (Windows)

echo 🔧 Setting up ServiceNow AD Group Automation...
echo.

REM Check if Python is installed
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ Python is not installed. Please install Python 3.8+ first.
    exit /b 1
)

echo ✅ Python found

REM Get the directory where this script is located
set SCRIPT_DIR=%~dp0
cd /d "%SCRIPT_DIR%"

REM Create virtual environment
if not exist ".venv" (
    echo 📦 Creating virtual environment...
    python -m venv .venv
) else (
    echo ✅ Virtual environment already exists
)

REM Activate and install dependencies
echo 📥 Installing dependencies...
call .venv\Scripts\activate.bat
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo.
echo ✅ Setup complete!
echo.
echo Usage:
echo   .venv\Scripts\activate.bat
echo   python ad_group_request.py --groups "GROUP-NAME" --users "username" --justification "Reason"
echo.
echo Or use the shortcut:
echo   run.bat --groups "GROUP-NAME" --users "username" --justification "Reason"
