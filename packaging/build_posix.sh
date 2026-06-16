#!/usr/bin/env bash
# build_posix.sh — Reproducible PyInstaller build for FFExplorer (Linux / macOS)
#
# Usage:
#   From the repo root:   bash packaging/build_posix.sh
#   Or directly:          cd packaging && bash build_posix.sh
#
# Prerequisites:
#   pip install "pyinstaller~=6.20.0" "PySide6~=6.11.1"
#
# Output:   packaging/bin/FFExplorer/FFExplorer   (one-dir bundle, Linux)
#           packaging/bin/FFExplorer.app/          (macOS — .app bundle when console=False)
#
# Note: on macOS PyInstaller produces a .app bundle automatically when
# console=False is set in the spec.  The output will be FFExplorer.app inside
# packaging/bin/.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

echo "[build_posix] Repo root : ${REPO_ROOT}"
echo "[build_posix] Spec file : ${SCRIPT_DIR}/FFExplorer.spec"

# Run PyInstaller from the repo root so relative datas paths resolve correctly
cd "${REPO_ROOT}"

pyinstaller "${SCRIPT_DIR}/FFExplorer.spec" \
    --noconfirm \
    --distpath "${SCRIPT_DIR}/bin" \
    --workpath "${SCRIPT_DIR}/work" \
    --log-level WARN

echo ""
echo "[build_posix] Build complete."
echo "[build_posix] Bundle : ${SCRIPT_DIR}/bin/FFExplorer/"
