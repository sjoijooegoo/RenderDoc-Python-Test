@echo off
set PYINSTALLER_PATH=D:\dev\python\python36\Scripts\pyinstaller.exe
set BIN_DIR=..\bin

echo [1/3] 开始打包...
%PYINSTALLER_PATH% -F --clean --name rdc_tool_win ..\src\main.py

if %ERRORLEVEL% NEQ 0 (
    echo [错误] 打包失败！
    pause
    exit /b %ERRORLEVEL%
)

echo [2/3] 检查 bin 目录...
if not exist %BIN_DIR% mkdir %BIN_DIR%

echo [3/3] 移动文件到 bin 目录...
move /y dist\rdc_tool_win.exe %BIN_DIR%\

echo [完成] 程序已输出至 %BIN_DIR%\rdc_tool_win.exe