@echo off
chcp 65001 >nul
title ps_run_all
REM magic_share launcher — runs the project_stat demo stand.
REM This file lives in repo root; the stand code is in project_stat\.
cd /d "%~dp0project_stat\script"

REM === log everything to file for inspection (window may close instantly) ===
set "LOG=%~dp0run_all_diag.log"
echo [%DATE% %TIME%] run.bat started > "%LOG%"
echo [%DATE% %TIME%] cwd=%CD% >> "%LOG%"
echo [%DATE% %TIME%] PATH has python: >> "%LOG%"
where python >> "%LOG%" 2>&1
where pythonw >> "%LOG%" 2>&1
where py >> "%LOG%" 2>&1

REM === resolve a python interpreter (colleague may have any of these) ===
set "PYW="
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
if exist "..\workflow\production.db" del /f /q "..\workflow\production.db" >nul 2>&1
for %%d in (..\test_reports ..\test_reports\archive) do (
    if exist "%%d" for %%f in ("%%d\*.csv") do del /f /q "%%f" >nul 2>&1
)
if exist "..\workflow\reports" for %%f in ("..\workflow\reports\stat_report_*.html") do del /f /q "%%f" >nul 2>&1

REM === 3. launch SERVER hidden (no window), then 2 visible terminals ===
echo [%DATE% %TIME%] launching server (hidden) + WATCHER + GEN... >> "%LOG%"
start "" "%PYW%" server.py
ping -n 1 127.0.0.1 >nul
start "STAT_WATCHER" cmd /k "%PY% watcher.py --watch"
ping -n 1 127.0.0.1 >nul
start "STAT_GEN" cmd /k "%PY% gen_test_data.py --interactive --seed 42"

REM === 4. explorer + DEFAULT browser in a SEPARATE NEW window ===
echo [%DATE% %TIME%] launching explorer + browser (new window)... >> "%LOG%"
start "" explorer "%~dp0project_stat\test_reports"
ping -n 1 127.0.0.1 >nul

REM Resolve the default browser EXE from the registry, then open the URL
REM in a NEW window (so layout.ps1 can catch it as a standalone window,
REM not a tab in an already-open browser session).
set "BROWSER_EXE="
REM 1) UserChoice ProgId -> open command (HKCR or HKCU\Software\Classes)
for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\http\UserChoice" /v ProgId 2^>nul') do set "PROGID=%%B"
if defined PROGID (
  for /f "tokens=2,*" %%A in ('reg query "HKCR\%PROGID%\shell\open\command" /ve 2^>nul') do set "BROWSER_CMD=%%B"
  if not defined BROWSER_CMD (
    for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Classes\%PROGID%\shell\open\command" /ve 2^>nul') do set "BROWSER_CMD=%%B"
  )
  REM extract the executable path (first quoted token, else first token)
  for /f "tokens=1" %%X in ('echo %BROWSER_CMD%') do (
    set "BROWSER_EXE=%%~X"
    if not defined BROWSER_EXE set "BROWSER_EXE=%%X"
  )
)
REM 2) last-resort: StartMenuInternet default (e.g. Firefox/Chrome system-wide)
if not defined BROWSER_EXE (
  for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\Clients\StartMenuInternet" /ve 2^>nul') do set "PROGID=%%B"
  if defined PROGID (
    for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\Clients\StartMenuInternet\%PROGID%\shell\open\command" /ve 2^>nul') do set "BROWSER_CMD=%%B"
    for /f "tokens=1" %%X in ('echo %BROWSER_CMD%') do (
      set "BROWSER_EXE=%%~X"
      if not defined BROWSER_EXE set "BROWSER_EXE=%%X"
    )
  )
)
if defined BROWSER_EXE (
  echo [%DATE% %TIME%] default browser: %BROWSER_EXE% >> "%LOG%"
  start "" "%BROWSER_EXE%" --new-window http://127.0.0.1:8770/
) else (
  echo [%DATE% %TIME%] browser exe not resolved, fallback to 'start' >> "%LOG%"
  start "" http://127.0.0.1:8770/
)

REM === 5. arrange windows FIRST (2x2 grid), THEN let generation run ===
REM layout.ps1 lives in repo root (one level up from script/)
echo [%DATE% %TIME%] arranging windows (layout.ps1)... >> "%LOG%"
REM give the default browser time to open a NEW window AND paint its
REM title (must contain 127.0.0.1:8770) so layout.ps1 can catch it
REM reliably instead of grabbing an unrelated window (e.g. opencode).
ping -n 8 127.0.0.1 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0layout.ps1" >> "%LOG%" 2>&1

echo [%DATE% %TIME%] windows placed. Generation proceeds in GEN window. >> "%LOG%"
echo.
echo  Demo stand ready. Generation runs in GEN window; watcher auto-processes.
echo  Press [N] in GEN window for new data, [E] to exit.
echo  Log: %LOG%
echo  (this window will close automatically)
exit /b 0
