#!/usr/bin/env bash
# Builds a single-file, source-free cobol-parser executable with Nuitka.
#
# Compiles the cobolparser package straight to machine code (Nuitka follows
# the import graph), so the end user gets one binary and never runs pip/uv
# against this private repo themselves. This is the analysis-only subset of
# what the sibling mocky-mock repo's build already produces -- its binary
# compiles mockymock AND cobolparser in one pass; this one stops at
# cobolparser.
#
# Every non-.py file the package resolves via Path(__file__) would need its
# own --include-data-* flag here (Nuitka does not read pyproject's
# [tool.setuptools.package-data], so a file can ship correctly in the wheel
# and still be missing from the binary). cobolparser currently resolves NO
# such runtime data file -- py.typed is a type-checker marker, and the only
# Path(__file__) uses are cli/coverage.py's repo-root walk, a dev-only IO
# coverage tool that is not reachable from the analyzer subcommands. Add a
# flag here the moment that changes.
#
# Usage: scripts/build_executable.sh <output-filename>
# Run from the repo root, with cobol-parser and nuitka already installed
# into the active Python environment (see the consuming release workflow for
# the exact install steps, including patchelf on Linux).
#
# No automated workflow in THIS repo calls this script. Its CI caller is the
# sibling cobol-analyzer VS Code extension repo's build-and-release.yml
# (cross-repo), which checks this repo out at a release tag and runs it. Do
# not delete this as apparent dead code.
set -euo pipefail

OUTPUT_NAME="${1:?usage: build_executable.sh <output-filename>}"

# Without --onefile-tempdir-spec, Nuitka's onefile bootstrap re-unpacks the
# whole payload into a fresh temp dir on EVERY launch and deletes it on exit
# -- a multi-second tax paid by each of the several `cobol-parser`
# invocations the VS Code extension fires per editor switch (program-flow
# JSON, program-flow mermaid, move-type-check, ...). Pointing the spec at a
# stable, version-scoped directory under the platform cache dir lets the
# bootstrap's own payload-hash check skip re-extraction on the common case
# (same build, already unpacked), while still safely detecting and
# re-extracting for a genuinely different build that happens to reuse the
# path. {VERSION} comes from --product-version below; Nuitka embeds it and
# substitutes it into the spec.
#
# Read from the INSTALLED DISTRIBUTION metadata, not `cobolparser.__version__`
# -- release-please's python release-type bumps pyproject.toml's `version`
# and this repo declares no `extra-files`, so the module attribute drifts
# behind the real release (1.8.0 vs 1.8.2 as of this writing). Using the
# stale attribute would scope two genuinely different releases to the same
# cache directory, leaving the payload-hash check as the only thing standing
# between them.
COBOL_PARSER_VERSION="$(python -c 'from importlib.metadata import version; print(version("cobol-parser"))')"

python -m nuitka \
  --onefile \
  --onefile-tempdir-spec="{CACHE_DIR}/cobol-parser/{VERSION}" \
  --product-version="$COBOL_PARSER_VERSION" \
  --output-dir=build \
  --output-filename="$OUTPUT_NAME" \
  --assume-yes-for-downloads \
  --lto=no \
  packaging/nuitka_entry.py
