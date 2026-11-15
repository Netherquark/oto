#!/bin/sh
# scripts/build_tensile_client.sh — build Tensile's benchmark client (`tensile-client`)
# from the checkout named by TENSILE_ROOT, against the ROCm toolchain you choose.
#
# Why this exists: oto needs Tensile's *benchmark client* (not the Python API) to
# run phases, and ROCm 7.x moved Tensile's client build out of-tree to `next-cmake`.
# The client must be built once per machine. Compiling is CPU-only; nothing here
# touches a GPU.
#
# USAGE
#   scripts/build_tensile_client.sh [options]
#
# OPTIONS
#   --rocm-prefix DIR   ROCm install prefix to build against. Defaults to $ROCM_PATH.
#                       Must be a *complete* SDK (see CHECKS) — a venv or SDK wheel
#                       that ships a partial include/hip is not enough; point at
#                       the full extracted dist (e.g. TheRock tarball prefix).
#   --targets LIST      Comma-separated AMDGPU targets. Default: gfx90c.
#                       Example: --targets gfx90c,  or --targets gfx902
#   --jobs N            Parallel build jobs (default: nproc, minimum 1).
#   --tensile-root DIR  Tensile checkout root (default: $TENSILE_ROOT; it must
#                       contain shared/tensile/next-cmake for the rocm-libraries
#                       layout, or <root>/next-cmake for a bare Tensile tree).
#   --build-dir DIR     Build directory (default: <next-cmake>/build).
#   --install-to DIR    Where to place the built binary, as <DIR>/client/tensile-client.
#                       Default: $TENSILE_ROOT/build/client (what `oto doctor` probes).
#   --amd-smi-dir DIR   amd_smi CMake package directory (default: auto-detected
#                       under the prefix; pass explicitly when your layout differs).
#   --dry-run           Print the exact configure/build/install commands, run nothing.
#   -h, --help          Show this help.
#
# CHECKS (fail fast, nothing guessed)
#   * prefix/include/hip/amd_detail/amd_warp_functions.h must exist — a full SDK
#     marker; missing => the prefix is a partial SDK (common with python-sdk venvs);
#     point --rocm-prefix at a complete dist/tarball install instead.
#   * The C compiler and C++ compiler are resolved from the prefix only
#     (lib/llvm/bin or llvm/bin or the python-sdk wheel layout). No /usr fallback.
#   * cmake >= 3.21.2 (next-cmake requirement).
#   * amd_smi is resolved and passed as amd_smi_DIR when found (sysdep of the client).
#
# After install, re-check with: python3 -m oto doctor   (expect 0 FAIL)
set -eu

PREFIX=${ROCM_PATH:-}
TARGETS=gfx90c
JOBS=$(nproc 2>/dev/null || echo 1)
TENSILE_ROOT=${TENSILE_ROOT:-}
BUILD_DIR=
INSTALL_TO=
AMD_SMI_DIR=
DRY_RUN=0

usage() { sed -n '2,40p' "$0" | grep '^#' | sed 's/^# \{0,1\}//'; }

fail() { echo "build_tensile_client: error: $*" >&2; exit 1; }

run() {
    echo "+ $*"
    if [ "$DRY_RUN" -eq 0 ]; then "$@"; fi
}

while [ $# -gt 0 ]; do
    case "$1" in
        --rocm-prefix) PREFIX=$2; shift 2 ;;
        --targets)     TARGETS=$2; shift 2 ;;
        --jobs)        JOBS=$2; shift 2 ;;
        --tensile-root) TENSILE_ROOT=$2; shift 2 ;;
        --build-dir)   BUILD_DIR=$2; shift 2 ;;
        --install-to)  INSTALL_TO=$2; shift 2 ;;
        --amd-smi-dir) AMD_SMI_DIR=$2; shift 2 ;;
        --dry-run)     DRY_RUN=1; shift ;;
        -h|--help)     usage; exit 0 ;;
        *) fail "unknown option: $1" ;;
    esac
done

[ -n "$PREFIX" ] || fail "--rocm-prefix is required (or set ROCM_PATH). No /usr fallback exists."
[ -d "$PREFIX" ]  || fail "ROCM prefix '$PREFIX' is not a directory."
PREFIX=$(cd "$PREFIX" && pwd)

# --- full-SDK marker -----------------------------------------------------------
[ -f "$PREFIX/include/hip/amd_detail/amd_warp_functions.h" ] || {
    echo "build_tensile_client: prefix '$PREFIX' is not a full ROCm SDK:" >&2
    echo "  missing $PREFIX/include/hip/amd_detail/amd_warp_functions.h" >&2
    echo "  (python-sdk venvs ship a partial include/hip; use the full extracted" >&2
    echo "   dist/tarball prefix, e.g. .../dist-<ver> or /opt/rocm)" >&2
    exit 1
}

# --- compiler resolution (layout-aware; no /usr guessing) ----------------------
llvm_bins() {
    for cand in \
        "$PREFIX/lib/llvm/bin" \
        "$PREFIX/llvm/bin" \
        "$PREFIX"/lib/python*/site-packages/_rocm_sdk_core/lib/llvm/bin \
        "$PREFIX/lib64/rocm/llvm/bin"; do
        [ -d "$cand" ] && echo "$cand"
    done
}
find_compiler() {
    # AMD takes its name first; upstream clang and the hipcc wrapper trail.
    for want in "$@"; do
        for bin in $(llvm_bins); do
            c="$bin/$want"
            [ -x "$c" ] && { echo "$c"; return 0; }
        done
        # hipcc lives in the prefix's top bin/ on RPM/tarball layouts
        c="$PREFIX/bin/$want"
        [ -x "$c" ] && { echo "$c"; return 0; }
    done
    return 1
}
CC_BIN=$(find_compiler amdclang clang-19 clang hipcc || true)
CXX_BIN=$(find_compiler amdclang++ clang++ hipcc || true)
[ -n "$CC_BIN" ]  || fail "no C compiler found under the prefix (checked amdclang, clang-19, clang, hipcc in lib/llvm/bin, llvm/bin, python-sdk layout, lib64/rocm/llvm/bin, bin)."
[ -n "$CXX_BIN" ] || fail "no C++ compiler found under the prefix (checked amdclang++, clang++, hipcc in the same layouts)."

# --- amd_smi resolution ---------------------------------------------------------
if [ -z "$AMD_SMI_DIR" ]; then
    for cand in \
        "$PREFIX/lib/cmake/amd_smi" \
        "$PREFIX"/lib/python*/site-packages/_rocm_sdk_core/lib/cmake/amd_smi; do
        for c in $cand; do
            [ -f "$c/amd_smi-config.cmake" ] && { AMD_SMI_DIR=$c; break; }
        done
        [ -n "$AMD_SMI_DIR" ] && break
    done
fi
[ -n "$AMD_SMI_DIR" ] || fail "amd_smi cmake config not found under the prefix (lib/cmake/amd_smi or the python-sdk layout). Pass --amd-smi-dir explicitly."
[ -d "$AMD_SMI_DIR" ] || fail "--amd-smi-dir '$AMD_SMI_DIR' is not a directory."

# --- cmake floor ----------------------------------------------------------------
command -v cmake >/dev/null 2>&1 || fail "cmake is not installed."
CMAKE_VER=$(cmake --version | sed -n 's/^cmake version //p' | head -1)
if ! awk 'BEGIN{split("'"$CMAKE_VER"'",v,"."); exit !(v[1]>3 || (v[1]==3 && (v[2]>21 || (v[2]==21 && v[3]>=2))))}' /dev/null; then
    echo "build_tensile_client: warning: cmake $CMAKE_VER may be below the next-cmake requirement (3.21.2)" >&2
fi

# --- locate next-cmake ----------------------------------------------------------
if [ -n "$TENSILE_ROOT" ]; then
    for sub in shared/tensile/next-cmake shared/tensile/next-cmake next-cmake; do
        [ -d "$TENSILE_ROOT/$sub" ] && { NEXTCMAKE=$TENSILE_ROOT/$sub; break; }
    done
    [ -n "${NEXTCMAKE:-}" ] || fail "--tensile-root '$TENSILE_ROOT' has no Tensile/next-cmake (expected $TENSILE_ROOT/shared/tensile/next-cmake or $TENSILE_ROOT/next-cmake)."
else
    fail "--tensile-root is required (or set TENSILE_ROOT). Expected the rocm-libraries root or a Tensile checkout root."
fi
[ -f "$NEXTCMAKE/CMakeLists.txt" ] || fail "next-cmake at '$NEXTCMAKE' has no CMakeLists.txt."
[ -n "$BUILD_DIR" ] || BUILD_DIR="$NEXTCMAKE/build"
[ -n "$INSTALL_TO" ] || INSTALL_TO="$TENSILE_ROOT/build/client"

echo "ROCM prefix : $PREFIX"
echo "compilers   : CC=$CC_BIN"
echo "              CXX=$CXX_BIN"
echo "amd_smi     : $AMD_SMI_DIR"
echo "targets     : $TARGETS"
echo "jobs        : $JOBS"
echo "next-cmake  : $NEXTCMAKE"
echo "build dir   : $BUILD_DIR"
echo "install to  : $INSTALL_TO/tensile-client"

run cmake -B "$BUILD_DIR" -S "$NEXTCMAKE" \
    -D CMAKE_BUILD_TYPE=Release \
    -D CMAKE_PREFIX_PATH="$PREFIX" \
    -D amd_smi_DIR="$AMD_SMI_DIR" \
    -D CMAKE_C_COMPILER="$CC_BIN" \
    -D CMAKE_CXX_COMPILER="$CXX_BIN" \
    -D GPU_TARGETS="$TARGETS"

run cmake --build "$BUILD_DIR" --target tensile-client --parallel "$JOBS"

BUILT="$BUILD_DIR/tensile-client"
[ "$DRY_RUN" -eq 1 ] || [ -x "$BUILT" ] || fail "build finished but no $BUILT was produced."
if [ "$DRY_RUN" -eq 0 ]; then
    mkdir -p "$INSTALL_TO"
    cp "$BUILT" "$INSTALL_TO/tensile-client"
    "$INSTALL_TO/tensile-client" --version || fail "installed client failed to run."
    echo "installed: $INSTALL_TO/tensile-client"
    echo "next: python3 -m oto doctor    (expect: Tensile client OK)"
fi
