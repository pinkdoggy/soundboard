@echo off
setlocal EnableExtensions
pushd "%~dp0"

REM --- UTF-8，避免中文亂碼 ---
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=UTF-8"

REM === 這裡的 ..\config 代表：以本 .bat (與 ufid64.py) 所在目錄為基準，往上一層的 config 目錄 ===
set "CFG_DIR=..\config"
set "SRC=%CFG_DIR%\sounds.json"
set "OLD=%CFG_DIR%\sounds-old.json"

echo [INFO] 批次檔所在：%CD%
echo [INFO] 目標資料夾：%CFG_DIR%
echo [INFO] 輸入(舊)：%OLD%
echo [INFO] 輸出(新)：%SRC%

set "RC=0"

REM --- 將 ../config/sounds.json 改名為 sounds-old.json（若存在） ---
if exist "%SRC%" (
  echo 重新命名 "%SRC%" -> "%OLD%"
  move /Y "%SRC%" "%OLD%" >nul
) else (
  echo [提示] 找不到 "%SRC%"（將嘗試直接使用已存在的 "%OLD%" 作為輸入）
)

REM --- 檢查輸入檔是否存在 ---
if not exist "%OLD%" (
  echo [ERROR] 找不到輸入檔：%OLD%
  set "RC=1"
  goto :END
)

REM --- 偵測 Python 執行器 ---
set "PY_EXE="
where py >nul 2>&1 && set "PY_EXE=py -3"
if not defined PY_EXE where python >nul 2>&1 && set "PY_EXE=python"
if not defined PY_EXE (
  echo [ERROR] 找不到 Python 3（請安裝或加入 PATH）。
  set "RC=1"
  goto :END
)

echo.
echo 執行：ufid64.py "%OLD%" -o "%SRC%"
%PY_EXE% ".\ufid64.py" "%OLD%" -o "%SRC%"
set "RC=%ERRORLEVEL%"
echo.

if %RC% NEQ 0 (
  echo [失敗] ufid64.py 結束代碼：%RC%
) else (
  echo [完成] 已輸出：%SRC%
)

:END
popd
pause
exit /b %RC%
