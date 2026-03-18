#!/usr/bin/env bash
# SwissAgent — manual Docker image build
#
# Docker is OPTIONAL. Run this script once before using docker-compose.
# Nothing in the automated setup (scripts/install.sh) builds Docker.
#
# Usage:
#   bash scripts/docker-build.sh              # build swissagent:latest
#   bash scripts/docker-build.sh --tag 1.2.3  # build swissagent:1.2.3
#   bash scripts/docker-build.sh --no-cache   # force full rebuild

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

TAG="latest"
NO_CACHE=""

# ── Parse flags ────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag)       TAG="$2"; shift ;;
    --no-cache)  NO_CACHE="--no-cache" ;;
    -h|--help)
      echo "Usage: bash scripts/docker-build.sh [--tag TAG] [--no-cache]"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
  shift
done

IMAGE="swissagent:${TAG}"

echo "============================================================"
echo "  SwissAgent — Manual Docker Build"
echo "  Image : $IMAGE"
echo "  Context: $ROOT_DIR"
echo "============================================================"
echo ""

# Verify Docker is available
if ! command -v docker &>/dev/null; then
  echo "[ERR ] Docker is not installed or not on PATH."
  echo "       Install Docker from https://docs.docker.com/get-docker/"
  exit 1
fi

echo "[INFO] Building $IMAGE …"
# shellcheck disable=SC2086
docker build $NO_CACHE -t "$IMAGE" "$ROOT_DIR"

echo ""
echo "[ OK ] Image built: $IMAGE"
echo ""
echo "  Next steps:"
echo "    docker compose up -d         # start full stack"
echo "    docker run -p 8000:8000 \\   # or run standalone"
echo "      -v \$(pwd)/workspace:/app/workspace $IMAGE"
echo ""
