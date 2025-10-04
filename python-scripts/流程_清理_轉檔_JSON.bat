@echo off
setlocal EnableExtensions EnableDelayedExpansion
pushd "%~dp0"

REM ---- UTF-8 避免中文亂碼 ----
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=UTF-8"

REM ---- INI 檔保存上次使用路徑 ----
set "INI=%~dp0workflow.ini"
set "LAST_IN="
set "LAST_OUT="
if exist "%INI%" (
  for /f "usebackq tokens=1* delims==" %%A in ("%INI%") do (
    if /I "%%A"=="IN"  set "LAST_IN=%%B"
    if /I "%%A"=="OUT" set "LAST_OUT=%%B"
  )
)

REM ---- 解析命令列參數（console 模式）----
set "IN="
set "OUT="
set "JSON="
set "CONVERT_ARGS="

if not "%~1"=="" (
  :parse
  if "%~1"=="" goto after_parse
  if /I "%~1"=="--json" (
    shift
    if "%~1"=="" goto usage
    set "JSON=%~1"
  ) else (
    if not defined IN (
      set "IN=%~1"
    ) else if not defined OUT (
      set "OUT=%~1"
    ) else (
      set CONVERT_ARGS=%CONVERT_ARGS% %1
    )
  )
  shift
  goto parse
)

:after_parse

REM ---- 若未提供參數，進入互動模式（雙擊）----
if defined IN goto have_args

echo.
echo ===============================
echo   清理 ^> 轉檔 ^> 生成 JSON
echo   互動設定模式（雙擊啟動）
echo ===============================
echo.

call :pick_dir "輸入資料夾" IN "%LAST_IN%"
if not defined IN goto fail

call :pick_dir "輸出資料夾" OUT "%LAST_OUT%"
if not defined OUT goto fail

set "JSON=%OUT%\mp3_index.json"
goto next

:have_args
if not defined OUT goto usage
if not defined JSON set "JSON=%OUT%\mp3_index.json"

:next
REM ---- 將本次選擇寫回 INI ----
> "%INI%" echo IN=%IN%
>>"%INI%" echo OUT=%OUT%

REM ---- 尋找 Python ----
set "PY_EXE="
where py >nul 2>nul && set "PY_EXE=py -3"
if not defined PY_EXE where python >nul 2>nul && set "PY_EXE=python"
if not defined PY_EXE (
  echo [ERROR] 找不到 Python 3。請先安裝並加入 PATH。
  goto fail
)

REM ---- 步驟 1：檔名清理（-o 僅為統一，實際忽略）----
echo.
echo [1/3] 檔名清理.py -i "%IN%"
%PY_EXE% "./檔名清理.py" -i "%IN%"
if errorlevel 1 goto fail

REM ---- 步驟 2：轉檔（預設不遞迴；如要遞迴請在 console 模式帶 --recursive）----
echo.
echo [2/3] 轉檔v3.py -i "%IN%" -o "%OUT%" %CONVERT_ARGS%
%PY_EXE% "./轉檔v3.py" -i "%IN%" -o "%OUT%" %CONVERT_ARGS%
if errorlevel 1 goto fail

REM ---- 步驟 3：生成 JSON 索引（掃描輸出資料夾）----
echo.
echo [3/3] JSON生成v3.py -i "%OUT%" -o "%JSON%"
%PY_EXE% "./JSON生成v3.py" -i "%OUT%" -o "%JSON%"
if errorlevel 1 goto fail

echo.
echo [完成] 已依序完成：檔名清理 → 轉檔 → 生成 JSON
echo JSON 輸出：%JSON%
popd
    pause
exit /b 0

:usage
echo 用法：
echo   %~nx0 ^<輸入資料夾^> ^<輸出資料夾^> [轉檔v3 其他參數...] [--json ^<JSON輸出路徑^>]
echo 範例（非遞迴）：
echo   %~nx0 "D:\來源" "E:\輸出"
echo 範例（遞迴 + 覆寫）：
echo   %~nx0 "D:\來源" "E:\輸出" --recursive --force
echo 範例（指定 JSON）：
echo   %~nx0 "D:\來源" "E:\輸出" --json "E:\輸出\library.json"
goto fail

:fail
echo.
echo [失敗] 流程中止（上一個步驟返回非零代碼或參數不足）。
popd
    pause
exit /b 1

REM ===============================
REM ========== 子程序們 ===========
REM ===============================

:pick_dir
REM %1=提示文字  %2=回填變數名  %3=預設路徑(可空)
set "PROMPT=%~1"
set "VAR=%~2"
set "DEF=%~3"

echo.
echo 選擇 %PROMPT%：
if defined DEF (
  if exist "%DEF%" (
    echo   [D] 使用上次： "%DEF%"
    set "HASDEF=1"
  ) else (
    echo   （注意：上次路徑不存在："%DEF%"）
    set "HASDEF="
  )
)
echo   [E] 手動輸入完整路徑
if defined HASDEF (
  choice /c DE /n /m "選擇 (D/E): "
  set "ans=!errorlevel!"
  if "!ans!"=="1" (
    set "%VAR%=%DEF%"
    goto :eof
  ) else (
    set /p "%VAR%=請輸入%PROMPT%： "
    if defined %VAR% goto :eof
    goto :pick_dir
  )
) else (
  choice /c E /n /m "選擇 (E): "
  set "ans=!errorlevel!"
  if "!ans!"=="1" (
  set /p "%VAR%=請輸入%PROMPT%： "
  if defined %VAR% goto :eof
  goto :pick_dir
) else (
    set /p "%VAR%=請輸入%PROMPT%： "
    if defined %VAR% goto :eof
    goto :pick_dir
  )
)
goto :eof
