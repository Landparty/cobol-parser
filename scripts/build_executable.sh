#!/usr/bin/env bash
# Builds a single-file, source-free cobol-parser executable with Nuitka.
#
# Unlike the wheels cibuildwheel produces (which compile only the three
# Cython hot-path modules -- _lexer_fast / _preprocess_fast / _data_fast --
# and still ship plain .py source for the rest of the package), Nuitka
# compiles the whole cobolparser package straight to machine code, so the
# resulting binary embeds no application source at all. See PUBLISHING.md.
#
# Usage: scripts/build_executable.sh <output-filename>
# Run from the repo root, with cobolparser and nuitka already installed
# into the active Python environment (see the release workflow for the
# exact install steps, including patchelf on Linux).
set -euo pipefail

OUTPUT_NAME="${1:?usage: build_executable.sh <output-filename>}"

python -m nuitka \
  --onefile \
  --output-dir=build \
  --output-filename="$OUTPUT_NAME" \
  --assume-yes-for-downloads \
  --lto=no \
  packaging/nuitka_entry.py
