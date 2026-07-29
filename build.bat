@echo off
REM ------------------------------------------------------------------
REM  Build wrapper. ASCII only on purpose:
REM  cmd.exe parses .bat using the console codepage at run time, which
REM  varies (cp950 / 65001 / ...). Any non-ASCII here can be garbled
REM  into syntax errors. All Chinese output comes from build.py, which
REM  writes to the Windows console through the Unicode API.
REM ------------------------------------------------------------------
setlocal EnableExtensions
cd /d "%~dp0"
set "PYTHONUTF8=1"

python "python-scripts/build.py" %*
set "RC=%errorlevel%"

if not "%RC%"=="0" (
  echo.
  echo [BUILD FAILED] exit code %RC% - do NOT deploy.
)
exit /b %RC%
