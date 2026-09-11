@echo off
REM ============================================================
REM 重建并启动 backend（改 backend 代码后必跑）
REM 源码是 COPY 进镜像的,不挂载,必须重建镜像才会生效
REM ============================================================
chcp 65001 >nul
setlocal

REM 叠加 Langfuse overlay：否则 backend 拿不到 LANGFUSE_* 环境变量，
REM 重建后会静默丢掉可观测性配置（前端「模型总览」页显示「未启用」）。
set "COMPOSE_ARGS=-f docker-compose.yml -f docker-compose.langfuse.yml"

echo === [1/3] 重建 backend 镜像 ===
docker-compose %COMPOSE_ARGS% build backend
if errorlevel 1 (
  echo [错误] backend 镜像构建失败
  exit /b 1
)

echo.
echo === [2/3] 启动 backend 容器 ===
docker-compose %COMPOSE_ARGS% up -d backend

echo.
echo === [3/3] 等待健康检查 ===
set "BACKEND_CID="
for /f %%i in ('docker-compose %COMPOSE_ARGS% ps -q backend') do set "BACKEND_CID=%%i"
if "%BACKEND_CID%"=="" (
  echo [错误] 未找到 backend 容器
  exit /b 1
)

:wait_healthy
docker inspect --format "{{.State.Health.Status}}" %BACKEND_CID% 2>nul | findstr /C:"healthy" >nul
if errorlevel 1 (
  echo   等待 backend health=healthy ...
  timeout /t 3 /nobreak >nul
  goto wait_healthy
)

echo.
echo === Backend 已就绪 ===
docker-compose %COMPOSE_ARGS% ps backend
echo.
echo 探活: curl http://localhost:12001/api/v1/auth/status
curl -s -o nul -w "HTTP %{http_code}\n" http://localhost:12001/api/v1/auth/status

endlocal
