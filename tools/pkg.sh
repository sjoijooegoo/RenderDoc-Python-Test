#!/bin/bash

# 设置变量
# 如果 pyinstaller 在 PATH 中，可以直接写 pyinstaller
PYINSTALLER_PATH="pyinstaller" 
BIN_DIR="../bin"

echo "[1/3] 开始打包..."
# -F: 单文件, --clean: 清理缓存, --name: 指定输出文件名
$PYINSTALLER_PATH -F --clean --name rdc_tool_linux ../main.py

if [ $? -ne 0 ]; then
    echo "[错误] 打包失败！"
    exit 1
fi

echo "[2/3] 检查 bin 目录..."
mkdir -p "$BIN_DIR"

echo "[3/3] 移动文件到 bin 目录..."

mv -f dist/rdc_tool_linux "$BIN_DIR/"

chmod +x "$BIN_DIR/rdc_tool_linux"

echo "[完成] 程序已输出并赋予执行权限"