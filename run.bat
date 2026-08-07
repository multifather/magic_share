@echo off
chcp 65001 >nul
title ps_run_all
cd /d "%~dp0script"

REM === log everything to file for inspection (window may close instantly) ===
set "LOG=%~dp0run_all_diag.log"
echo [%DATE% %TIME%] run.bat started > "%LOG%"
echo [%DATE% %TIME%] cwd=%CD% >> "%LOG%"
echo [%DATE% %TIME%] PATH has python: >> "%LOG%"
where python >> "%LOG%" 2>&1
where pythonw >> "%LOG%" 2>&1
where py >> "%LOG%" 2>&1

REM === resolve a python interpreter (colleague may have any of these) ===
set "PY="
if exist "%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe" (
    set "PYW=%LOCALAPPDATA%\Programs\Python\Python314\pythonw.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe" (
    set "PYW=%LOCALAPPDATA%\Programs\Python\Python313\pythonw.exe"
) else (
    set "PYW=pythonw"
)
where py >nul 2>&1 && set "PY=py -3" || set "PY=python"

REM === 1. kill old demo windows by title (tree, incl. child python) ===
echo [%DATE% %TIME%] killing old windows... >> "%LOG%"
taskkill /FI "WINDOWTITLE eq STAT_*" /F /T >nul 2>&1
ping -n 2 127.0.0.1 >nul

REM === 2. full reset: DB + folders (matches demo) ===
echo [%DATE% %TIME%] resetting DB and folders... >> "%LOG%"
if exist "..\\workflow\production.db" del /f /q "..\\workflow\production.db" >nul 2>&1
for %%d in (..\\test_reports ..\\test_reports\\archive) do (
    if exist "%%d" for %%f in ("%%d\*.csv") do del /f /q "%%f" >nul 2>&1
)
REM old HTML reports cleanup (keep latest.html)
if exist "..\\workflow\\reports" for %%f in ("..\\workflow\\reports\\stat_report_*.html") do del /f /q "%%f" >nul 2>&1

REM === 3. launch SERVER hidden (no window), then 2 visible terminals ===
echo [%DATE% %TIME%] launching server (hidden) + WATCHER + GEN... >> "%LOG%"
start "" "%PYW%" server.py
ping -n 1 127.0.0.1 >nul
start "STAT_WATCHER" cmd /k "%PY% watcher.py --watch"
ping -n 1 127.0.0.1 >nul
start "STAT_GEN" cmd /k "%PY% gen_test_data.py --interactive --seed 42"

REM === 4. explorer + DEFAULT browser (no hard Firefox dependency) ===
echo [%DATE% %TIME%] launching explorer + browser... >> "%LOG%"
start "" explorer "%~dp0test_reports"
ping -n 1 127.0.0.1 >nul
start "" http://127.0.0.1:8770/

REM === 5. arrange windows FIRST (2x2 grid), THEN let generation run ===
echo [%DATE% %TIME%] arranging windows (layout.ps1)... >> "%LOG%"
ping -n 3 127.0.0.1 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0layout.ps1" >> "%LOG%" 2>&1

echo [%DATE% %TIME%] windows placed. Generation proceeds in GEN window. >> "%LOG%"
echo.
echo  Demo stand ready. Generation runs in GEN window; watcher auto-processes.
echo  Press [N] in GEN window for new data, [E] to exit.
echo  Log: %LOG%
echo  (this window will close automatically)
REM no pause: close automatically so the user does not have to press a key
exit /b 0
