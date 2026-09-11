@echo off
chcp 65001 >nul 2>&1
cd /d %~dp0

REM sandbox 容器要往这两个目录写文件,Windows 下需先放开权限
mkdir workspace 2>nul
mkdir Skills 2>nul
icacls workspace /grant %USERNAME%:(OI)(CI)M /T >nul
icacls Skills /grant %USERNAME%:(OI)(CI)M /T >nul

REM Langfuse overlay 需要 .env 里的 LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY
if not exist ".env" (
    echo [提示] 未找到 .env，将使用示例配置。
    echo        如需接入 Langfuse 可观测性：copy .env.example .env 后填写其中的密钥。
    echo.
)

echo ========================================
echo   正在启动 emsclaw 服务...
echo ========================================
docker-compose -f docker-compose.yml -f docker-compose.langfuse.yml up -d

echo.
echo 正在等待服务启动，每 2 秒检测一次...
echo.

:check_loop
timeout /t 2 /nobreak >nul

curl -fsS http://127.0.0.1:5173 >nul 2>&1
if %errorlevel% neq 0 (
    echo [%time%] 服务尚未就绪，继续等待...
    goto check_loop
)

echo.
echo ========================================
echo   服务启动成功！正在打开浏览器...
echo ========================================
start http://127.0.0.1:5173
