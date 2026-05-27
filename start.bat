@echo off
chcp 65001 > nul
title 视频下载器
echo.
echo ============================================
echo         视频下载器 - VideoDown
echo ============================================
echo.

cd /d "%~dp0"

python --version > nul 2>&1
if %errorlevel% neq 0 (
    echo [错误] 未找到 Python，请先安装 Python 3.8+
    echo 下载地址：https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/2] 安装/更新依赖...
python -m pip install -r requirements.txt -q --disable-pip-version-check
echo [2/2] 启动服务...
echo.
echo 浏览器将自动打开，如未打开请访问：http://localhost:5000
echo 按 Ctrl+C 可停止服务
echo.
python app.py
pause
