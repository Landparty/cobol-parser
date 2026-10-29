# Closed-source PyPI release for cobol-parser

**Date:** 2026-08-14
**Status:** Superseded. The closed-source build mode was removed; the package is AGPL-3.0-or-later and ships `.py` source.

## Goal

Publish `cobol-parser` to the public PyPI index as `pip install cobol-parser`,
without shipping readable `.py` source in the distributed package. This is a
new, separate release artifact — it does not change how the LegacyLens
`backend/` repo consumes this library today (editable install + vendored
source from the sibling directory), which continues unchanged.

## Threat model

**Casual access only.** The goal is to stop someone from doing
`pip download cobol-parser && unzip` and reading the `.py` files directly.
Native-compiled extension modules (Cython) satisfy this. Resistance to a
motivated reverse engineer with a disassembler is explicitly out of scope —
no code obfuscation, anti-tamper, or symbol-stripping pass beyond what Cython
produces by default.

`LICENSE` is already a proprietary EULA ("All rights reserved"), not an open
license, so no license change is needed — the compiled-only wheel is
consistent with what's already declared.

## Current state (as found)

- `pyproject.toml` already declares `[tool.cibuildwheel]` targeting
  `cp311/cp312/cp313` across Linux (x86_64/aarch64), macOS (x86_64/arm64),
  and Windows (AMD64).
- `.github/workflows/release-please.yml` already has a release pipeline that,
  on every release-please-cut release:
  - `build-sdist`: builds a full source sdist **and** a pure-Python fallback
    wheel (`COBOLPARSER_SKIP_EXT=1`) — both contain complete `.py` source.
  - `build-binary-wheels`: runs `cibuildwheel`, which compiles only the 3
    existing accelerator modules (`_lexer_fast`, `_preprocess_fast`,
    `_data_fast`); every other `.py` file (~125 modules) still ships as
    plain source inside these wheels too.
  - `publish`: attaches all of the above as **GitHub Release assets**. It
    does not upload to PyPI — nothing from this repo is on PyPI today.

So the wheel-matrix CI scaffolding already exists; the actual gaps are (a)
full-package compilation, (b) dropping the source-carrying artifacts, and
(c) actually publishing to PyPI.

## Design

### 1. `setup.py` — closed-source build mode

Add a build mode gated behind a new env var, `COBOLPARSER_CLOSED_SOURCE=1`,
set only by the release CI job (never by local dev, `pip install -e .`, or
the backend's vendoring flow):

- Cythonize every `cobolparser/**/*.py` file **except** `__init__.py` files,
  in addition to the existing 3 `.pyx` accelerator modules (unchanged).
- `__init__.py` files stay plain Python — they only do package-level
  re-exports, so they leak the public API surface (already documented in
  this repo's `CLAUDE.md`) but no implementation logic.
- Override the `build_py` setuptools command so that, in this mode, only
  `__init__.py` files (and non-code package data, e.g. `py.typed`) are
  copied into the build output — every `.py` file with a compiled extension
  twin is excluded from what actually lands in the wheel.
- Outside of `COBOLPARSER_CLOSED_SOURCE=1`, `setup.py` behaves exactly as
  it does today (3 accelerator modules, pure-Python fallback, honors
  `COBOLPARSER_SKIP_EXT=1`).

### 2. `pyproject.toml` — cibuildwheel config

Add `COBOLPARSER_CLOSED_SOURCE = "1"` to `[tool.cibuildwheel.environment]`
so every wheel built by the release pipeline is a full closed-source build.
Update `[tool.cibuildwheel] test-command` to smoke-test that ordinary
business-logic modules (not just the 3 named accelerators) actually loaded
as compiled extensions rather than falling back — e.g. asserting a couple of
representative modules (say `cobolparser.parser`, `cobolparser.lexer`) have
no `.py` source file backing them (`__file__` ends in `.pyd`/`.so`, or
`inspect.getsource()` raises).

### 3. `release-please.yml` — pipeline changes

- **Remove** the `build-sdist` job entirely (it only exists to build
  source-carrying artifacts, which we no longer want to publish).
- **Keep** `build-binary-wheels` as-is structurally (matrix, QEMU for
  aarch64, `pypa/cibuildwheel`) — it now produces fully closed-source wheels
  because of the `pyproject.toml` change above.
- **Keep** the existing `publish` step that attaches wheels to the GitHub
  Release (useful for traceability / manual download), but **add a new
  `publish-pypi` job** that uploads the same wheels to PyPI using
  [Trusted Publishing](https://docs.pypi.org/trusted-publishers/) (OIDC) via
  `pypa/gh-action-pypi-publish` — no stored API token/secret to manage.
  Requires a one-time manual step (outside this repo, on pypi.org) to
  register the trusted publisher for this GitHub repo/workflow, since PyPI
  requires the project to exist there first for the OIDC binding — see
  "Manual steps" below.
- No sdist is published to PyPI or attached to the release. Consequence:
  installs only work on the platforms/interpreters covered by the
  `cibuildwheel` matrix (Linux x86_64/aarch64, macOS x86_64/arm64, Windows
  AMD64; CPython 3.11–3.13). This matches the "casual access only, public
  PyPI" decision — accepted trade-off, not a bug.

### 4. Testing

`cibuildwheel`'s `test-command` runs against each just-built wheel in an
isolated environment (already the pattern for the existing 3-module check).
For the closed-source build, extend this to a fast smoke subset of the test
suite (not the full ~8,000-test suite, which stays `workflow_dispatch`-only
per existing CI convention) — e.g. `pytest tests/unit/test_lexer.py
tests/test_all_samples.py -q` — run against the **installed wheel**, to
catch anything the full-package Cythonization silently broke (e.g. a module
using an introspection pattern Cython doesn't support identically).

### 5. Out of scope / explicitly not doing

- No obfuscation, symbol stripping, or anti-decompilation beyond default
  Cython compilation (threat model is "casual access only").
- No change to the backend's install/vendoring flow.
- No sdist, no pure-Python fallback wheel, on PyPI or the GitHub Release.
- No change to `LICENSE`.

## Manual steps (outside this repo, not part of implementation)

1. Create the `cobol-parser` project on PyPI (first upload of a brand-new
   project name currently requires either a manual first upload or PyPI's
   pending-publisher flow — confirm which at implementation time) and
   register `Landparty/cobol-parser`'s `release-please.yml` workflow as a
   Trusted Publisher for it.
2. No PyPI API token needs to be stored as a GitHub secret (Trusted
   Publishing uses short-lived OIDC tokens instead).

## Testing plan for this change itself

- Local: `python setup.py build_ext --inplace` with
  `COBOLPARSER_CLOSED_SOURCE=1` set, then run the smoke subset against the
  in-place build to confirm the closed-source Cythonization compiles
  cleanly across all ~125 modules before relying on CI to find failures.
- CI: the modified `release-please.yml` is exercised for real the next time
  release-please cuts a release; until then, verify the `cibuildwheel`
  config change with a manual `pipx run cibuildwheel` dry run locally or via
  `workflow_dispatch` if one is added.
