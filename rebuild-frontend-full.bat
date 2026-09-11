@echo off
REM ============================================================
REM 完整重建 frontend (改 package.json / 加新依赖时跑)
REM 清掉 node_modules 与 npm 缓存命名卷,容器启动时重新 npm install
REM ============================================================
chcp 65001 >nul
setlocal

REM 叠加 Langfuse overlay：`up -d frontend` 会连带校验 backend 依赖，
REM 不加 overlay 会把 backend 按「无 LANGFUSE_*」的配置重建，导致可观测性失效
set "COMPOSE_ARGS=-f docker-compose.yml -f docker-compose.langfuse.yml"

echo === [1/4] 停止并删除 frontend 容器 ===
docker-compose %COMPOSE_ARGS% stop frontend
docker-compose %COMPOSE_ARGS% rm -f frontend

echo.
echo === [2/4] 删除 node_modules 卷 ===
REM 卷名前缀是 compose 项目名(默认取目录名),这里按名字后缀筛选,不写死项目名
for /f %%v in ('docker volume ls -q --filter name=emsclaw_frontend_node_modules') do docker volume rm %%v 2>nul
for /f %%v in ('docker volume ls -q --filter name=emsclaw_frontend_npm_cache') do docker volume rm %%v 2>nul

echo.
echo === [3/4] 启动 frontend (会自动 npm install) ===
docker-compose %COMPOSE_ARGS% up -d frontend

echo.
echo === [4/4] 等待 Vite 启动 ===
:wait_frontend
docker-compose %COMPOSE_ARGS% logs --tail 80 frontend 2>&1 | findstr /C:"ready in" >nul
if errorlevel 1 (
  echo   等待 npm install + Vite 启动 (可能要 30~60 秒) ...
  timeout /t 5 /nobreak >nul
  goto wait_frontend
)

echo.
echo === Frontend 已就绪 ===
docker-compose %COMPOSE_ARGS% ps frontend
echo.
echo 访问: http://localhost:5173/
curl -s -o nul -w "HTTP %{http_code}\n" http://localhost:5173/

endlocal
