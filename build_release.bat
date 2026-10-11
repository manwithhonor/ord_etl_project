@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"

set "APP_NAME=ORD_Report"
set "VERSION=1.0.0"
set "VENV_DIR=.venv"
set "DIST_DIR=dist"
set "BUILD_DIR=build"
set "RELEASE_ROOT=release"
set "RELEASE_DIR=%RELEASE_ROOT%\%APP_NAME%_v%VERSION%"
set "ZIP_PATH=%RELEASE_ROOT%\%APP_NAME%_v%VERSION%.zip"

echo.
echo ============================================================
echo  ORD ETL build v%VERSION%
echo ============================================================
echo.

if exist "%VENV_DIR%\Scripts\python.exe" (
    echo [1/5] Existing virtual environment found: %VENV_DIR%
) else (
    echo [1/5] Creating virtual environment...
    set "BASE_PY="

    if exist "C:\ProgramData\anaconda3\python.exe" (
        set "BASE_PY=C:\ProgramData\anaconda3\python.exe"
    )

    if not defined BASE_PY (
        where py >nul 2>nul
        if not errorlevel 1 set "BASE_PY=py"
    )

    if not defined BASE_PY (
        where python >nul 2>nul
        if not errorlevel 1 set "BASE_PY=python"
    )

    if not defined BASE_PY (
        echo ERROR: Python was not found.
        goto :fail
    )

    echo Using Python: !BASE_PY!

    if "!BASE_PY!"=="py" (
        py -m venv "%VENV_DIR%"
    ) else if "!BASE_PY!"=="python" (
        python -m venv "%VENV_DIR%"
    ) else (
        "!BASE_PY!" -m venv "%VENV_DIR%"
    )

    if errorlevel 1 goto :fail
)

echo.
echo [2/5] Activating virtual environment...
call "%VENV_DIR%\Scripts\activate.bat"
if errorlevel 1 goto :fail

echo Python:
python --version
echo Pip:
python -m pip --version

echo.
echo [3/5] Installing dependencies...
python -m pip install --upgrade pip
if errorlevel 1 goto :fail

if not exist "requirements.txt" (
    echo ERROR: requirements.txt not found.
    goto :fail
)

python -m pip install -r requirements.txt
if errorlevel 1 goto :fail

python -m pip install pyinstaller
if errorlevel 1 goto :fail

echo.
echo [4/5] Building EXE...

if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
if exist "%DIST_DIR%\%APP_NAME%" rmdir /s /q "%DIST_DIR%\%APP_NAME%"
if exist "%APP_NAME%.spec" del /q "%APP_NAME%.spec"

python -m PyInstaller ^
    --noconfirm ^
    --clean ^
    --name "%APP_NAME%" ^
    --onedir ^
    --windowed ^
    gui.py

if errorlevel 1 goto :fail

if not exist "%DIST_DIR%\%APP_NAME%\%APP_NAME%.exe" (
    echo ERROR: EXE was not created.
    goto :fail
)

echo.
echo [5/5] Creating GitHub Release ZIP...

if exist "%RELEASE_DIR%" rmdir /s /q "%RELEASE_DIR%"
if not exist "%RELEASE_ROOT%" mkdir "%RELEASE_ROOT%"
mkdir "%RELEASE_DIR%"

xcopy "%DIST_DIR%\%APP_NAME%\*" "%RELEASE_DIR%\" /E /I /Y >nul
if errorlevel 1 goto :fail

if exist "config.yaml" copy /Y "config.yaml" "%RELEASE_DIR%\config.yaml" >nul
if exist "README.md" copy /Y "README.md" "%RELEASE_DIR%\README.md" >nul
if exist ".env.example" copy /Y ".env.example" "%RELEASE_DIR%\.env.example" >nul

if not exist "%RELEASE_DIR%\statics" mkdir "%RELEASE_DIR%\statics"
if exist "statics\credentials.example.json" (
    copy /Y "statics\credentials.example.json" "%RELEASE_DIR%\statics\credentials.example.json" >nul
)

if not exist "%RELEASE_DIR%\logs" mkdir "%RELEASE_DIR%\logs"

(
    echo ORD Report v%VERSION%
    echo.
    echo Before first launch:
    echo 1. Copy .env.example to .env and fill in tokens.
    echo 2. Put the real Google credentials file into statics\credentials.json
    echo 3. Check config.yaml
    echo 4. Run %APP_NAME%.exe
    echo.
    echo Real .env and credentials.json are intentionally NOT included.
) > "%RELEASE_DIR%\FIRST_RUN.txt"

if exist "%ZIP_PATH%" del /q "%ZIP_PATH%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "Compress-Archive -Path '%RELEASE_DIR%\*' -DestinationPath '%ZIP_PATH%' -Force"

if errorlevel 1 goto :fail

echo.
echo ============================================================
echo  BUILD COMPLETED SUCCESSFULLY
echo ============================================================
echo.
echo EXE folder:
echo   %CD%\%DIST_DIR%\%APP_NAME%
echo.
echo GitHub Release ZIP:
echo   %CD%\%ZIP_PATH%
echo.
pause
exit /b 0

:fail
echo.
echo ============================================================
echo  BUILD FAILED
echo ============================================================
echo.
pause
exit /b 1
