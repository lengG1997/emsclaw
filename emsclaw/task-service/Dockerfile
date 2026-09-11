# syntax=docker/dockerfile:1.4
# build context = 仓库根（见 docker-compose.yml），依赖来自根 uv.lock
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai

WORKDIR /app

# 编译工具：greenlet/psycopg 等可能从 sdist 构建，需要 g++
# 先把 apt 源切到国内可达镜像，避免直连 deb.debian.org / archive.ubuntu.com 超时
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    for f in /etc/apt/sources.list /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list.d/ubuntu.sources; do \
      if [ -f "$f" ]; then sed -i \
        -e 's|//deb.debian.org|//mirrors.aliyun.com|g' \
        -e 's|//security.debian.org|//mirrors.aliyun.com|g' \
        -e 's|//archive.ubuntu.com|//mirrors.aliyun.com|g' \
        -e 's|//security.ubuntu.com|//mirrors.aliyun.com|g' "$f"; fi; \
    done; \
    apt-get update \
    && apt-get install -y --no-install-recommends build-essential

# uv（pip 装，走 aliyun 源）
RUN pip install --upgrade uv

# workspace 根 manifest + lock + 各成员 manifest
COPY pyproject.toml uv.lock ./
COPY emsclaw/backend/pyproject.toml emsclaw/backend/pyproject.toml
COPY emsclaw/task-service/pyproject.toml emsclaw/task-service/pyproject.toml
COPY emsclaw/sandbox/pyproject.toml emsclaw/sandbox/pyproject.toml

# 按 uv.lock 锁定安装 task-service 依赖
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv export --frozen --no-dev --no-hashes --package emsclaw-task-service -o /tmp/reqs.txt \
    && uv pip install --system -r /tmp/reqs.txt \
    && rm -f /tmp/reqs.txt

COPY emsclaw/task-service/app ./app

# 默认跑 API server（worker/beat 在 compose 里覆盖 command）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001"]
