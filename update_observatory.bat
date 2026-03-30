@echo off
setlocal
title AI-DOC Observatory Updater
color 1F

echo ============================================================
echo   AI-DOC Publication Aquarium - Update Script
echo ============================================================
echo.

:: ─── Configuration ───────────────────────────────────────────
:: Edit these paths to match your setup
set CONDA_ENV=scholar_api
set PROJECT_DIR=%~dp0
set AUTHORS_FILE=semantic_scholar_ids_2026-03-25.xlsx
set SCIMAGO_FILE=scopus2026a.csv
set GS_FILE=googlescholar2026.csv
set JCR_FILE=jif2026.csv
set JUFO_FILE=jufo2026.csv
:: If you have the JUFO CSV, set it above, e.g.:
:: set JUFO_FILE=jufo_channels.csv
:: ─────────────────────────────────────────────────────────────

:: Navigate to project folder
cd /d "%PROJECT_DIR%"
echo Working directory: %CD%
echo.

:: Activate conda
echo [1/5] Activating conda environment: %CONDA_ENV%
call conda activate %CONDA_ENV%
if errorlevel 1 (
    echo ERROR: Could not activate conda environment "%CONDA_ENV%"
    echo Make sure Anaconda is installed and the environment exists.
    pause
    exit /b 1
)
echo       Done.
echo.

:: Build the command
set CMD=python run_observatory_26.py "%AUTHORS_FILE%"
if exist "%SCIMAGO_FILE%" (
    set CMD=%CMD% --scimago "%SCIMAGO_FILE%"
) else (
    echo WARNING: SCImago file not found: %SCIMAGO_FILE%
)
if exist "%GS_FILE%" (
    set CMD=%CMD% --gs "%GS_FILE%"
) else (
    echo WARNING: Google Scholar file not found: %GS_FILE%
)
if defined JCR_FILE (
    if exist "%JCR_FILE%" (
        set CMD=%CMD% --jcr "%JCR_FILE%"
    ) else (
        echo WARNING: JCR file not found: %JCR_FILE%
    )
)
if defined JUFO_FILE (
    if exist "%JUFO_FILE%" (
        set CMD=%CMD% --jufo "%JUFO_FILE%"
    ) else (
        echo WARNING: JUFO file not found: %JUFO_FILE%
    )
)
set CMD=%CMD% --output index.html

:: Run the pipeline
echo [2/5] Running observatory pipeline...
echo       Command: %CMD%
echo.
echo ────────────────────────────────────────────────────────────
%CMD%
echo ────────────────────────────────────────────────────────────
echo.

if errorlevel 1 (
    echo ERROR: Pipeline failed! Check the output above.
    pause
    exit /b 1
)

:: Show results and ask for confirmation
echo.
echo [3/5] Results ready. Checking files...
echo.
if exist index.html (
    for %%A in (index.html) do echo       index.html            %%~zA bytes
) else (
    echo ERROR: index.html was not created!
    pause
    exit /b 1
)
if exist ai_doc_history.json (
    for %%A in (ai_doc_history.json) do echo       ai_doc_history.json   %%~zA bytes
)

echo.
echo ============================================================
echo   Review: Open index.html in your browser to check the
echo   results before pushing to GitHub.
echo ============================================================
echo.
set /p CONFIRM="Push updates to GitHub? (Y/N): "
if /i not "%CONFIRM%"=="Y" (
    echo.
    echo Cancelled. Files are saved locally but NOT pushed to GitHub.
    echo You can push manually later with:
    echo   git add index.html ai_doc_history.json
    echo   git commit -m "Update"
    echo   git push
    pause
    exit /b 0
)

:: Git push
echo.
echo [4/5] Committing to git...
set TODAY=%date:~-4%-%date:~-7,2%-%date:~-10,2%

:: Check if git is available
git --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: git is not installed or not in PATH.
    echo Install from https://git-scm.com/downloads
    echo Or push files manually via github.com website.
    pause
    exit /b 1
)

git add index.html ai_doc_history.json
git commit -m "Update observatory %TODAY%"

echo.
echo [5/5] Pushing to GitHub...
git push

if errorlevel 1 (
    echo.
    echo ERROR: git push failed. You may need to:
    echo   1. Set up git credentials: git config --global credential.helper manager
    echo   2. Or push manually: git push origin main
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   Done! GitHub Pages will update in 1-2 minutes.
echo   Hard-refresh your browser (Ctrl+Shift+R) to see changes.
echo ============================================================
echo.
pause
