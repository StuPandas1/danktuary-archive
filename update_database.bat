@echo off
setlocal enabledelayedexpansion

echo ============================================
echo   DankApp Database Update
echo ============================================
echo.

cd /d "%~dp0"

echo [1/8] Scanning files to update band_archive.csv...
python scanner.py
if errorlevel 1 (
    echo.
    echo ERROR: scanner.py failed. Stopping.
    pause
    exit /b 1
)

echo.
echo [2/8] Uploading new recordings to the Internet Archive...
set UPLOAD_MAX_RETRIES=3
set UPLOAD_WAIT_SECONDS=3600
set UPLOAD_ATTEMPT=0

:upload_retry
set /a UPLOAD_ATTEMPT+=1
python upload_to_archive.py
if errorlevel 1 (
    if !UPLOAD_ATTEMPT! GEQ !UPLOAD_MAX_RETRIES! (
        echo.
        echo ERROR: upload_to_archive.py failed after !UPLOAD_MAX_RETRIES! attempt^(s^). Stopping.
        echo Check the output above. If it's still a rate limit, wait longer and re-run manually.
        pause
        exit /b 1
    )
    echo.
    echo upload_to_archive.py failed on attempt !UPLOAD_ATTEMPT! of !UPLOAD_MAX_RETRIES!
    echo ^(likely IA's rate limiter -- this retry loop can't tell that apart from
    echo  other failures, so it'll retry regardless and just fail again quickly
    echo  if it's something else^).
    echo Waiting !UPLOAD_WAIT_SECONDS! seconds before retrying... ^(press any key to retry now^)
    timeout /t !UPLOAD_WAIT_SECONDS!
    goto upload_retry
)

echo.
echo [3/8] Analyzing data...
python analyze.py
if errorlevel 1 (
    echo.
    echo ERROR: analyze.py failed. Stopping.
    pause
    exit /b 1
)

echo.
echo [4/8] Building metadata...
python build_metadata.py
if errorlevel 1 (
    echo.
    echo ERROR: build_metadata.py failed. Stopping.
    pause
    exit /b 1
)

echo.
echo [5/8] Adding share OD links...
python generate_share_links.py
if errorlevel 1 (
    echo.
    echo ERROR: generate_share_links.py failed. Stopping.
    pause
    exit /b 1
)

echo.
echo [6/8] Checking for changes...
git add band_archive.csv song_stats.csv song_metadata.csv metadata_jam.csv uploaded_shows_cache.json last_known_shows.csv

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
echo [7/8] Committing to GitHub...
set TIMESTAMP=%date% %time%
git commit -m "Update archive data - %TIMESTAMP%"
if errorlevel 1 (
    echo.
    echo ERROR: git commit failed. Stopping.
    pause
    exit /b 1
)

echo.
echo [8/8] Pushing to GitHub...
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