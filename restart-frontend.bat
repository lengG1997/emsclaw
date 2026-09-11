@echo off
REM ============================================================
REM 重启 frontend 容器
REM 注意:源码烘焙在镜像里,restart 不会加载新代码。
REM 改了前端代码请用 rebuild-frontend-full.bat;
REM 只改了 package.json / 加了新依赖也用它(会清 node_modules 命名卷)
REM ============================================================
chcp 65001 >nul
setlocal

REM 叠加 Langfuse overlay：保证 backend 的 LANGFUSE_* 配置不会被 compose 配置哈希差异清掉
set "COMPOSE_ARGS=-f docker-compose.yml -f docker-compose.langfuse.yml"

echo === [1/2] 重启 frontend 容器 ===
docker-compose %COMPOSE_ARGS% restart frontend

echo.
echo === [2/2] 等待 Vite 启动 ===
:wait_frontend
docker-compose %COMPOSE_ARGS% logs --tail 50 frontend 2>&1 | findstr /C:"ready in" >nul
if errorlevel 1 (
  echo   等待 Vite 启动 ...
  timeout /t 3 /nobreak >nul
  goto wait_frontend
)

echo.
echo === Frontend 已就绪 ===
docker-compose %COMPOSE_ARGS% ps frontend
echo.
echo 访问: http://localhost:5173/
curl -s -o nul -w "HTTP %{http_code}\n" http://localhost:5173/

endlocal
