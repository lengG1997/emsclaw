# syntax=docker/dockerfile:1.4
# build context = 仓库根（见 docker-compose.yml），依赖来自根 uv.lock
#FROM ghcr.io/agent-infra/sandbox:latest
FROM enterprise-public-cn-beijing.cr.volces.com/vefaas-public/all-in-one-sandbox:latest

ARG NPM_MIRROR=https://registry.npmmirror.com

# ── 0. 统一 Python 环境为 3.12 ─────────────────────────────────────
ENV PATH="/opt/python3.12/bin:${PATH}" \
    PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    PIP_TRUSTED_HOST=mirrors.aliyun.com \
    UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_BREAK_SYSTEM_PACKAGES=1 \
    TZ=Asia/Shanghai

RUN ln -sf /opt/python3.12/bin/python3.12 /usr/local/bin/python3 \
    && ln -sf /opt/python3.12/bin/python3.12 /usr/local/bin/python \
    && ln -sf /opt/python3.12/bin/pip3 /usr/local/bin/pip3 \
    && ln -sf /opt/python3.12/bin/pip3 /usr/local/bin/pip

# 系统依赖 + Node 工具（BuildKit 缓存）
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
        build-essential clang \
        fonts-wqy-microhei fontconfig \
        poppler-utils pandoc libreoffice-writer \
    && fc-cache -fv
RUN --mount=type=cache,target=/root/.npm,sharing=locked \
    npm config set registry ${NPM_MIRROR} \
    && npm install -g skills docx pptxgenjs

# uv（pip 装，走 aliyun 源；用 /opt/python3.12 的 pip）
RUN pip install --upgrade uv

# ── 2. Python 依赖：sandbox 用 Python 3.12，与 backend(3.13) 共享 uv.lock 会冲突
# （uv.lock 锁了 audioop-lts 需 3.13+，而 3.12 标准库自带 audioop）。
# 改用 uv pip compile 按 Python 3.12 重新解析，绕过 uv.lock。
COPY pyproject.toml uv.lock ./
COPY emsclaw/sandbox/pyproject.toml emsclaw/sandbox/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv pip compile --python-version 3.12 \
      emsclaw/sandbox/pyproject.toml -o /tmp/reqs.txt \
    && uv pip install --system --python /opt/python3.12/bin/python3.12 -r /tmp/reqs.txt \
    && rm -f /tmp/reqs.txt \
    && python3 -c "import matplotlib; matplotlib.get_cachedir()" \
    && python3 -c "import matplotlib.font_manager; matplotlib.font_manager._load_fontmanager(try_read_cache=False)"

ENV CC=clang NODE_PATH="/usr/lib/node_modules"
RUN mkdir -p /home/emsclaw && chmod -R 777 /home/emsclaw

