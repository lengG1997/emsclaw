# syntax=docker/dockerfile:1.4
# build context = 仓库根（见 docker-compose.yml），依赖来自根 uv.lock
ARG BASE_IMAGE=python:3.13-slim
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_BREAK_SYSTEM_PACKAGES=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai

WORKDIR /app

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
    && apt-get install -y --no-install-recommends \
      build-essential \
      curl \
      libxrender1 \
      libxext6 \
      libx11-6

# uv（pip 装，走 aliyun 源）
RUN pip install --upgrade uv

# workspace 根 manifest + lock + 各成员 manifest（uv export 需要看到完整 workspace）
COPY pyproject.toml uv.lock ./
COPY emsclaw/backend/pyproject.toml emsclaw/backend/pyproject.toml
COPY emsclaw/task-service/pyproject.toml emsclaw/task-service/pyproject.toml
COPY emsclaw/sandbox/pyproject.toml emsclaw/sandbox/pyproject.toml

# 按 uv.lock 锁定安装 backend 依赖（--package 限定只装 backend 的依赖闭包，不装 backend 包本身）
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv export --frozen --no-dev --no-hashes --package emsclaw-backend -o /tmp/reqs.txt \
    && uv pip install --system -r /tmp/reqs.txt \
    && rm -f /tmp/reqs.txt

# backend 源码（import 包 = emsclaw_backend）
COPY emsclaw/backend/emsclaw_backend /app/emsclaw_backend

# 内置 skills 烘焙进镜像（不挂载，镜像自包含）
COPY emsclaw/builtin-skills /app/builtin-skills

# Skills 烘焙进镜像（不挂载，镜像自包含）
COPY Skills /app/Skills

EXPOSE 8000

CMD ["python", "-m", "uvicorn", "emsclaw_backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
