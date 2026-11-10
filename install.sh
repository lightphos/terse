#!/bin/sh
# Install Terse host compiler to ~/.terse/compiler and put `tc` on PATH via ~/.terse/bin.
#
#   curl -fsSL https://raw.githubusercontent.com/<org>/terse/main/install.sh | sh
#
# Or from a local clone:
#   ./install.sh
#
# Env:
#   TERSE_HOME   install prefix (default: $HOME/.terse)
#   TERSE_REPO   git URL when installing via curl (default below)
#   TERSE_REF    git ref/branch/tag (default: main)

set -eu

TERSE_HOME="${TERSE_HOME:-${HOME}/.terse}"
TERSE_REPO="${TERSE_REPO:-https://github.com/lightphos/terse.git}"
TERSE_REF="${TERSE_REF:-main}"
COMPILER_DIR="${TERSE_HOME}/compiler"
BIN_DIR="${TERSE_HOME}/bin"
LIB_DIR="${TERSE_HOME}/lib"

echo "Terse install -> ${TERSE_HOME}"

# Resolve source tree: local repo (script lives in it) or shallow clone
SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0" 2>/dev/null)" 2>/dev/null && pwd || true)
SRC=""

if [ -n "${SCRIPT_DIR}" ] && [ -f "${SCRIPT_DIR}/compiler/tersec.py" ]; then
  SRC="${SCRIPT_DIR}"
  echo "Using local tree: ${SRC}"
elif [ -f "./compiler/tersec.py" ]; then
  SRC=$(pwd)
  echo "Using cwd tree: ${SRC}"
else
  # curl | sh — $0 may be stdin; clone into cache
  CACHE="${TERSE_HOME}/src"
  echo "Cloning ${TERSE_REPO} (${TERSE_REF}) -> ${CACHE}"
  mkdir -p "${TERSE_HOME}"
  if [ -d "${CACHE}/.git" ]; then
    git -C "${CACHE}" fetch --depth 1 origin "${TERSE_REF}" 2>/dev/null || true
    git -C "${CACHE}" checkout -q "FETCH_HEAD" 2>/dev/null || git -C "${CACHE}" checkout -q "${TERSE_REF}"
  else
    rm -rf "${CACHE}"
    git clone --depth 1 --branch "${TERSE_REF}" "${TERSE_REPO}" "${CACHE}"
  fi
  SRC="${CACHE}"
fi

if [ ! -f "${SRC}/compiler/tersec.py" ]; then
  echo "error: compiler/tersec.py not found under ${SRC}" >&2
  exit 1
fi

# Require python3 + a C compiler (runtime builds)
if ! command -v python3 >/dev/null 2>&1; then
  echo "error: python3 is required" >&2
  exit 1
fi
if ! command -v cc >/dev/null 2>&1 && ! command -v gcc >/dev/null 2>&1 && ! command -v clang >/dev/null 2>&1; then
  echo "warning: no C compiler (cc/gcc/clang) on PATH — builds will fail until one is installed" >&2
fi

mkdir -p "${COMPILER_DIR}" "${BIN_DIR}" "${LIB_DIR}" "${TERSE_HOME}/out"

# Sync compiler package
rm -rf "${COMPILER_DIR}"
mkdir -p "${COMPILER_DIR}"
cp -R "${SRC}/compiler/." "${COMPILER_DIR}/"
# Drop caches / junk
rm -rf "${COMPILER_DIR}/__pycache__" "${COMPILER_DIR}/tersec/__pycache__" 2>/dev/null || true

# Sync standard libraries
if [ -d "${SRC}/lib" ]; then
  rm -rf "${LIB_DIR}"
  mkdir -p "${LIB_DIR}"
  cp -R "${SRC}/lib/." "${LIB_DIR}/"
fi

# Wrapper: tc
cat > "${BIN_DIR}/tc" << 'WRAP'
#!/usr/bin/env sh
set -eu
TERSE_HOME="${TERSE_HOME:-${HOME}/.terse}"
COMPILER="${TERSE_HOME}/compiler"
if [ ! -f "${COMPILER}/tersec.py" ]; then
  echo "error: Terse compiler not found at ${COMPILER}/tersec.py — re-run install.sh" >&2
  exit 1
fi
# Prefer package imports from the install tree
export PYTHONPATH="${COMPILER}${PYTHONPATH:+:$PYTHONPATH}"
export TERSE_HOME
# Default lib search includes installed libs
export TERSE_LIB="${TERSE_LIB:-${TERSE_HOME}/lib}"
exec python3 "${COMPILER}/tersec.py" "$@"
WRAP
chmod +x "${BIN_DIR}/tc"

# Optional: tersec alias same as tc
cp "${BIN_DIR}/tc" "${BIN_DIR}/tersec"
chmod +x "${BIN_DIR}/tersec"

echo ""
echo "Installed:"
echo "  compiler  ${COMPILER_DIR}"
echo "  libs      ${LIB_DIR}"
echo "  command   ${BIN_DIR}/tc"
echo ""
echo "Add to your shell profile:"
echo "  export PATH=\"${BIN_DIR}:\$PATH\""
echo "  export TERSE_HOME=\"${TERSE_HOME}\""
echo ""
echo "Then:"
echo "  tc build path/to/app.te -o ~/.terse/out/app"
echo "  tc run path/to/app.te"
echo ""

# Smoke check
if python3 "${COMPILER_DIR}/tersec.py" --help >/dev/null 2>&1 || \
   PYTHONPATH="${COMPILER_DIR}" python3 "${COMPILER_DIR}/tersec.py" 2>&1 | head -1 >/dev/null; then
  echo "Smoke: tersec.py is runnable."
fi

# If PATH already contains bin, note it
case ":${PATH}:" in
  *":${BIN_DIR}:"*) echo "PATH already includes ${BIN_DIR}";;
  *) echo "Note: ${BIN_DIR} is not on your PATH yet.";;
esac
