@echo off
REM ============================================================
REM 一键重建所有服务 (前后端代码都改了)
REM 等价于: rebuild-backend.bat + rebuild-frontend-full.bat
REM ============================================================
chcp 65001 >nul
setlocal

REM 与 rebuild-backend.bat 保持一致：叠加 Langfuse overlay，避免 backend 丢 LANGFUSE_* 配置
set "COMPOSE_ARGS=-f docker-compose.yml -f docker-compose.langfuse.yml"

echo.
echo ============== 第一阶段: 重建 backend ==============
call rebuild-backend.bat
if errorlevel 1 (
  echo [错误] backend 阶段失败
  exit /b 1
)

echo.
echo ============== 第二阶段: 重建 frontend ==============
call rebuild-frontend-full.bat
if errorlevel 1 (
  echo [错误] frontend 阶段失败
  exit /b 1
)

echo.
echo ============== 全部完成 ==============
docker-compose %COMPOSE_ARGS% ps

endlocal
