#!/usr/bin/env bash
# =============================================================================
#  SwissAgent Native — build_all.sh
#  Builds both Debug and Release configurations of the SwissAgent C++ app.
#  Designed for Git Bash / MSYS2 on Windows.
#
#  Usage:
#    bash build_all.sh [--jobs N] [--config debug|release|all]
#    bash build_all.sh --help
#
#  Output layout (relative to repo root):
#    Builds/debug/   — Debug binaries
#    Builds/release/ — Release binaries
#    Logs/Build/     — Per-run log files
# =============================================================================

# ── Helpers ───────────────────────────────────────────────────────────────────
CYAN="\033[0;36m"
BOLD="\033[1m"
GREEN="\033[0;32m"
YELLOW="\033[0;33m"
RED="\033[0;31m"
RESET="\033[0m"

_info()  { printf "${GREEN}[build_all]${RESET} %s\n" "$*"; }
_warn()  { printf "${YELLOW}[build_all][WARN]${RESET} %s\n" "$*" >&2; }
_error() { printf "${RED}[build_all][ERROR]${RESET} %s\n" "$*" >&2; }
_head()  { printf "${CYAN}${BOLD}── %s ──${RESET}\n" "$*"; }
_sep()   { printf "${CYAN}${BOLD}────────────────────────────────────────${RESET}\n"; }

die() { _error "$*"; exit 1; }

# ── Defaults ──────────────────────────────────────────────────────────────────
JOBS=$(nproc 2>/dev/null || sysctl -n hw.logicalcpu 2>/dev/null || echo 4)
BUILD_CONFIG="all"   # debug | release | all

# ── Parse arguments ───────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
    case "$1" in
        --jobs|-j)       JOBS="$2";         shift 2 ;;
        --config|-c)     BUILD_CONFIG="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: bash build_all.sh [--jobs N] [--config debug|release|all]"
            exit 0 ;;
        *) die "Unknown argument: $1" ;;
    esac
done

# Validate --config
case "$BUILD_CONFIG" in
    debug|release|all) ;;
    *) die "--config must be debug, release, or all (got: $BUILD_CONFIG)" ;;
esac

# ── Paths ─────────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NATIVE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$NATIVE_DIR/.." && pwd)"

TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DEBUG_DIR="$REPO_ROOT/Builds/debug"
RELEASE_DIR="$REPO_ROOT/Builds/release"
LOG_DIR="$REPO_ROOT/Logs/Build"
LOG_FILE="$LOG_DIR/build_all_${TIMESTAMP}.log"

# Create required directories
mkdir -p "$DEBUG_DIR" "$RELEASE_DIR" "$LOG_DIR"

# ── Header ────────────────────────────────────────────────────────────────────
_head "SwissAgent — Build All  [${TIMESTAMP}]"
echo ""
_info "Repo root : $REPO_ROOT"
_info "Debug dir : $DEBUG_DIR"
_info "Release dir: $RELEASE_DIR"
_info "Log file  : $LOG_FILE"
_info "Jobs      : $JOBS"
echo ""

# ── Tee all output to log ──────────────────────────────────────────────────────
exec > >(tee -a "$LOG_FILE") 2>&1

# ── Environment ───────────────────────────────────────────────────────────────
_head "Environment"
echo ""

# cmake (required)
if ! command -v cmake &>/dev/null; then
    die "cmake not found on PATH.
         Install CMake >= 3.20 from https://cmake.org/download/
         and make sure it is on your PATH."
fi
_info "  cmake: $(cmake --version | head -1)"

# Parse cmake version for generator selection
CMAKE_VERSION_STRING="$(cmake --version | head -1)"
CMAKE_MAJOR=$(echo "$CMAKE_VERSION_STRING" | sed 's/cmake version \([0-9]*\)\..*/\1/')
CMAKE_MINOR=$(echo "$CMAKE_VERSION_STRING" | sed 's/cmake version [0-9]*\.\([0-9]*\)\..*/\1/')

# Compiler detection — try MSVC (vswhere) then MinGW/g++; neither is fatal here
COMPILER="unknown"
GENERATOR=""

# Safe way to get ProgramFiles(x86) path on Windows/Git Bash
_PF86="$(printenv 'PROGRAMFILES(X86)' 2>/dev/null || true)"
[[ -z "$_PF86" ]] && _PF86="/c/Program Files (x86)"

# Try vswhere.exe to find Visual Studio
VSWHERE_PATHS=(
    "/c/Program Files/Microsoft Visual Studio/Installer/vswhere.exe"
    "/c/Program Files (x86)/Microsoft Visual Studio/Installer/vswhere.exe"
    "${PROGRAMFILES}/Microsoft Visual Studio/Installer/vswhere.exe"
    "${_PF86}/Microsoft Visual Studio/Installer/vswhere.exe"
)
for vswhere in "${VSWHERE_PATHS[@]}"; do
    if [[ -f "$vswhere" ]]; then
        VS_NAME="$("$vswhere" -latest -products '*' \
                    -requires Microsoft.VisualCpp.Tools.HostX64.TargetX64 \
                    -property displayName 2>/dev/null || true)"
        if [[ -n "$VS_NAME" ]]; then
            COMPILER="MSVC"
            case "$VS_NAME" in
                *"2022"*) GENERATOR="Visual Studio 17 2022" ;;
                *"2019"*) GENERATOR="Visual Studio 16 2019" ;;
                *"2017"*) GENERATOR="Visual Studio 15 2017" ;;
                *)        GENERATOR="Visual Studio 17 2022" ;;
            esac
            _info "  compiler: MSVC — $VS_NAME"
            _info "  generator: $GENERATOR"
            break
        fi
    fi
done

# Fall back to g++ (MinGW / MSYS2)
if [[ "$COMPILER" == "unknown" ]]; then
    if command -v g++ &>/dev/null; then
        COMPILER="MinGW"
        GPP_VER="$(g++ --version | head -1)"
        _info "  compiler: $GPP_VER"
        if command -v ninja &>/dev/null; then
            GENERATOR="Ninja"
            _info "  generator: Ninja"
        else
            GENERATOR="MinGW Makefiles"
            _info "  generator: MinGW Makefiles"
        fi
    fi
fi

if [[ "$COMPILER" == "unknown" ]]; then
    _warn "No C++ compiler detected (MSVC or MinGW g++ not found)."
    _warn "CMake will attempt to find one automatically; configure may fail."
    # cmake will pick a default generator — don't abort here
fi
echo ""

# ── cmake helper ─────────────────────────────────────────────────────────────
cmake_configure() {
    local config="$1"
    local build_dir="$2"
    local extra_args=()

    # Multi-config generators (Visual Studio) don't use -DCMAKE_BUILD_TYPE
    if [[ "$GENERATOR" == Visual\ Studio* ]]; then
        extra_args+=(-G "$GENERATOR" -A x64)
    elif [[ -n "$GENERATOR" ]]; then
        extra_args+=(-G "$GENERATOR" -DCMAKE_BUILD_TYPE="$config")
    else
        extra_args+=(-DCMAKE_BUILD_TYPE="$config")
    fi

    cmake -B "$build_dir" \
          "${extra_args[@]}" \
          -DSA_USE_WEBVIEW2=OFF \
          "$NATIVE_DIR"
}

cmake_build() {
    local config="$1"
    local build_dir="$2"

    cmake --build "$build_dir" \
          --config "$config" \
          --parallel "$JOBS"
}

# ── Build function ─────────────────────────────────────────────────────────────
build_one() {
    local config="$1"         # Debug or Release
    local build_dir="$2"

    local cfg_lower="${config,,}"   # lowercase label

    _head "${config} Build"
    echo ""

    # Configure
    _info "[1/2] Configuring $config ..."
    if ! cmake_configure "$config" "$build_dir"; then
        _error "CMake configure failed for $config."
        return 1
    fi
    echo ""

    # Build
    _info "[2/2] Building $config ..."
    if ! cmake_build "$config" "$build_dir"; then
        _error "CMake build failed for $config."
        return 1
    fi

    # Locate executable
    local exe=""
    for candidate in \
            "$build_dir/${config}/SwissAgent.exe" \
            "$build_dir/SwissAgent.exe"; do
        if [[ -f "$candidate" ]]; then
            exe="$candidate"
            break
        fi
    done

    echo ""
    if [[ -n "$exe" ]]; then
        _info "${config} build complete ✓"
        _info "  Executable: $exe"
    else
        _warn "${config} build finished but SwissAgent.exe not found at expected path."
    fi
    echo ""
    return 0
}

# ── Run builds ────────────────────────────────────────────────────────────────
FAILED=()

if [[ "$BUILD_CONFIG" == "debug" || "$BUILD_CONFIG" == "all" ]]; then
    build_one "Debug" "$DEBUG_DIR" || FAILED+=("Debug")
fi

if [[ "$BUILD_CONFIG" == "release" || "$BUILD_CONFIG" == "all" ]]; then
    build_one "Release" "$RELEASE_DIR" || FAILED+=("Release")
fi

# ── Summary ───────────────────────────────────────────────────────────────────
_sep
if [[ ${#FAILED[@]} -eq 0 ]]; then
    printf "${GREEN}${BOLD}[build_all] All builds succeeded.${RESET}\n"
    printf "${GREEN}[build_all]${RESET} Log: %s\n" "$LOG_FILE"
    exit 0
else
    printf "${RED}${BOLD}[build_all] The following configurations failed:${RESET}\n"
    for f in "${FAILED[@]}"; do
        printf "${RED}[build_all]   ✗ %s${RESET}\n" "$f"
    done
    printf "${YELLOW}[build_all]${RESET} See log for details: %s\n" "$LOG_FILE"
    exit 1
fi
