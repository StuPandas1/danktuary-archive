@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   DankApp Database Update
echo ============================================
echo.

cd /d "%~dp0"

echo [1/8] Scanning audio files...
python scanner.py
if errorlevel 1 (
    echo.
    echo ERROR: scanner.py failed. Stopping.
    pause
    exit /b 1
)

echo.
echo [2/8] Analyzing data...
python analyze.py
if errorlevel 1 (
    echo.
    echo ERROR: analyze.py failed. Stopping.
    pause
    exit /b 1
)

echo.
echo [3/8] Building metadata...
python build_metadata.py
if errorlevel 1 (
    echo.
    echo ERROR: build_metadata.py failed. Stopping.
    pause
    exit /b 1
)

echo.
echo [4/8] Generating OneDrive links...
python generate_onedrive_urls.py
if errorlevel 1 (
    echo.
    echo ERROR: generate_onedrive_urls.py failed. Stopping.
    pause
    exit /b 1
)

echo.
echo [5/8] Uploading new recordings to the Internet Archive...
python upload_to_archive.py
if errorlevel 1 (
    echo.
    echo ERROR: upload_to_archive.py failed or hit a rate limit. Stopping.
    echo Check the output above. If it's a rate limit, wait before re-running.
    pause
    exit /b 1
)

echo.
echo [6/8] Checking for new shows and emailing the band...
python notify_band.py
if errorlevel 1 (
    echo.
    echo WARNING: notify_band.py failed. Continuing anyway.
)

echo.
echo [7/8] Checking for changes...
git add band_archive.csv song_stats.csv song_metadata.csv metadata_jam.csv

git diff --cached --quiet
if errorlevel 1 (
    echo Changes detected. Committing...
) else (
    echo No changes to the data files. Nothing to push.
    echo.
    echo ============================================
    echo   Done - database was already up to date.
    echo ============================================
    pause
    exit /b 0
)

echo.
echo [8/8] Committing and pushing to GitHub...
set TIMESTAMP=%date% %time%
git commit -m "Update archive data - %TIMESTAMP%"
if errorlevel 1 (
    echo.
    echo ERROR: git commit failed. Stopping.
    pause
    exit /b 1
)

git push
if errorlevel 1 (
    echo.
    echo ERROR: git push failed. Check your connection or credentials.
    pause
    exit /b 1
)

echo.
echo ============================================
echo   Done! Streamlit Cloud will redeploy
echo   automatically in a minute or two.
echo ============================================
pause