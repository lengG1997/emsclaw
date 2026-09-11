#!/usr/bin/env bash
set -euo pipefail

# 启用 BuildKit（Dockerfile 中 apt/pip/npm 缓存挂载需要）
export DOCKER_BUILDKIT=1
VERSION="${VERSION:-v0.0.4}"

# 构建 emsclaw 下所有带 Dockerfile 的子目录镜像
# 镜像标签 = release-${VERSION}
# 支持多平台: linux/amd64, linux/arm64
#
# 用法:
#   ./release.sh                    # 构建全部模块
#   ./release.sh backend frontend   # 只构建指定模块
#   REGISTRY=myregistry.io/myuser ./release.sh   # 构建并推送

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
EMSCLAW="${SCRIPT_DIR}/emsclaw"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"

# 可选: 设置 REGISTRY 后镜像名为 $REGISTRY/目录名:release-$VERSION，并执行 push
REGISTRY="${REGISTRY:-}"

if [[ ! -d "$EMSCLAW" ]]; then
  echo "Error: emsclaw directory not found: $EMSCLAW"
  exit 1
fi

# 收集待构建模块列表
TARGETS=("$@")

modules=()
if [[ ${#TARGETS[@]} -gt 0 ]]; then
  for t in "${TARGETS[@]}"; do
    dir="${EMSCLAW}/${t}"
    if [[ ! -d "$dir" ]]; then
      echo "Error: module not found: $t"
      exit 1
    fi
    modules+=("$dir")
  done
else
  for dir in "$EMSCLAW"/*; do
    [[ -d "$dir" ]] && modules+=("$dir")
  done
fi

for dir in "${modules[@]}"; do
  name="emsclaw-$(basename "$dir")"
  dockerfile="${dir}/Dockerfile"
  if [[ ! -f "$dockerfile" ]]; then
    echo "Skip (no Dockerfile): $name"
    continue
  fi

  if [[ -n "$REGISTRY" ]]; then
    image="${REGISTRY}/${name}:release-${VERSION}"
    push_flag="--push"
    cache_repo="${REGISTRY}/${name}:buildcache"
    cache_args=(
      --cache-from "type=registry,ref=${cache_repo}"
      --cache-to   "type=registry,ref=${cache_repo},mode=max"
    )
  else
    image="${name}:release-${VERSION}"
    push_flag=""
    cache_args=()
  fi

  echo "Building: $image (platforms: $PLATFORMS)"
  docker buildx build \
    --platform "$PLATFORMS" \
    --provenance=false \
    --sbom=false \
    ${cache_args[@]+"${cache_args[@]}"} \
    -t "$image" \
    -f "$dockerfile" \
    $push_flag \
    "$dir"
done

echo "Done. Version: $VERSION"
