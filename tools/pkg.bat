@echo off
setlocal

set PYINSTALLER_PATH=C:\Users\v_sycisong\AppData\Local\Programs\Python\Python310\Scripts\pyinstaller.exe
set BIN_DIR=..\bin

echo [1/3] start packaging...
%PYINSTALLER_PATH% -F --clean --name rdc_tool_win --hidden-import parse.environment.cos_params ..\src\main.py

if %ERRORLEVEL% NEQ 0 (
    echo [error] package failed
    exit /b %ERRORLEVEL%
)

echo [2/3] ensure bin dir...
if not exist %BIN_DIR% mkdir %BIN_DIR%

echo [3/3] move exe to bin...
move /y dist\rdc_tool_win.exe %BIN_DIR%\

echo [done] output: %BIN_DIR%\rdc_tool_win.exe
