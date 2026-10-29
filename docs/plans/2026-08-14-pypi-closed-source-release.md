# Closed-Source PyPI Release Implementation Plan

> **Status: superseded.** The closed-source build mode was built and then
> removed: the package is AGPL-3.0-or-later and its wheels ship `.py`
> source. Kept as history only; do not follow these steps.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish `cobolparser` to public PyPI as fully compiled, closed-source wheels (no readable `.py` business logic), without touching how the backend consumes this library today.

**Architecture:** A new `COBOLPARSER_CLOSED_SOURCE=1` build mode in `setup.py` Cythonizes every module except `__init__.py` files and excludes their `.py` source from what `build_py` copies into the distribution. `pyproject.toml`'s existing `[tool.cibuildwheel]` config sets that env var for release builds. `.github/workflows/release-please.yml` drops the source-carrying sdist/fallback-wheel job and adds a PyPI Trusted Publishing (OIDC) step.

**Tech Stack:** setuptools, Cython >=3.0, cibuildwheel, GitHub Actions, `pypa/gh-action-pypi-publish`.

**Spec:** [2026-08-14-pypi-closed-source-release-design.md](2026-08-14-pypi-closed-source-release-design.md)

## Global Constraints

- Threat model is "casual access only" — no obfuscation/anti-tamper beyond default Cython compilation.
- No sdist and no pure-Python fallback wheel published anywhere (PyPI or GitHub Release) — both would leak `.py` source.
- Wheels only for CPython 3.11–3.13 on Linux (x86_64/aarch64), macOS (x86_64/arm64), Windows (AMD64) — matches existing `[tool.cibuildwheel]` matrix.
- The backend's editable-install / vendored-source consumption of this repo (`../backend/`) must be completely unaffected — the closed-source path only activates when `COBOLPARSER_CLOSED_SOURCE=1` is explicitly set, which only release CI sets.
- No `LICENSE` changes (already a proprietary EULA).
- PyPI publishing uses Trusted Publishing (OIDC) — no API token stored as a secret.

---

### Task 1: Closed-source build mode in `setup.py`

**Files:**
- Modify: `setup.py`
- Create: `scripts/verify_closed_source_wheel.py`

**Interfaces:**
- Produces: env var `COBOLPARSER_CLOSED_SOURCE` (value `"1"` enables the mode) — consumed by Task 2's `pyproject.toml` change.
- Produces: `scripts/verify_closed_source_wheel.py`, a standalone script (build wheel → assert no leaked `.py` source → install into a throwaway venv → smoke-test import), runnable via `python scripts/verify_closed_source_wheel.py`.

- [ ] **Step 1: Write the verification script**

Create `scripts/verify_closed_source_wheel.py`:

```python
#!/usr/bin/env python3
"""Build a closed-source wheel and verify no .py source leaks into it.

Usage: python scripts/verify_closed_source_wheel.py
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_wheel(dist_dir: Path) -> Path:
    env = dict(os.environ)
    env["COBOLPARSER_CLOSED_SOURCE"] = "1"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    wheels = list(dist_dir.glob("cobolparser-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one wheel, found {wheels}")
    return wheels[0]


def check_no_leaked_source(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as zf:
        py_files = [
            n
            for n in zf.namelist()
            if n.startswith("cobolparser/") and n.endswith(".py")
        ]
    leaked = [n for n in py_files if not n.endswith("__init__.py")]
    if leaked:
        raise AssertionError(f"wheel leaks source for: {leaked}")
    if not py_files:
        raise AssertionError("expected at least the __init__.py stubs, found none")
    print(f"OK: only {len(py_files)} __init__.py stub(s) present, no other .py source")


def smoke_test_install(wheel_path: Path, venv_dir: Path) -> None:
    venv.create(venv_dir, with_pip=True)
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    python = venv_dir / bin_dir / exe
    subprocess.run([str(python), "-m", "pip", "install", str(wheel_path)], check=True)
    check = (
        "import cobolparser.lexer, cobolparser.parser\n"
        "assert not cobolparser.lexer.__file__.endswith('.py'), cobolparser.lexer.__file__\n"
        "assert not cobolparser.parser.__file__.endswith('.py'), cobolparser.parser.__file__\n"
        "from cobolparser import parse_cobol\n"
        "result = parse_cobol('IDENTIFICATION DIVISION.\\nPROGRAM-ID. X.\\n')\n"
        "assert result.success, result.errors\n"
        "print('smoke test OK')\n"
    )
    subprocess.run([str(python), "-c", check], check=True)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        wheel_path = build_wheel(dist_dir)
        check_no_leaked_source(wheel_path)
        smoke_test_install(wheel_path, tmp_path / "venv")
    print("All checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Install the build frontend**

Run: `pip install build`

- [ ] **Step 3: Run the script against the unmodified `setup.py` to confirm it currently fails**

Run: `python scripts/verify_closed_source_wheel.py`
Expected: `AssertionError: wheel leaks source for: [...]` — today the env var is a no-op, so every `.py` file still ships. If it errors earlier (e.g. Cython/compiler missing), fix the local toolchain first — this repo already builds the 3 accelerator modules, so a compiler is present (see `CLAUDE.md` build instructions).

- [ ] **Step 4: Implement the closed-source build mode**

Replace the full contents of `setup.py` with:

```python
"""Build script for the Cython extension modules.

The pre-generated ``.c`` files for ``_lexer_fast`` and ``_preprocess_fast``
are checked into the repository, so a stock ``pip install .`` builds the
extensions without needing Cython at install time -- a C compiler is the
only requirement. When Cython *is* available the ``.pyx`` sources are
re-cythonized first so local edits take effect.

Compile in-place during development:
    python setup.py build_ext --inplace

Skip the C extension build (e.g. on a machine without a compiler) by setting:
    COBOLPARSER_SKIP_EXT=1
The install then succeeds with the pure-Python fallback paths and only the
~3x lexer speedup is forfeited.

Closed-source release build (used only by release CI, never local dev):
    COBOLPARSER_CLOSED_SOURCE=1
Cythonizes every cobolparser/**/*.py module (except __init__.py files, which
stay plain Python re-export stubs) in addition to the 3 accelerators above,
and excludes every compiled module's .py source from the built distribution.
See docs/plans/2026-08-14-pypi-closed-source-release-design.md.
"""

import os
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py
from setuptools.extension import Extension

_PKG = "cobolparser"
_MODULES = ("_lexer_fast", "_preprocess_fast", "_data_fast")
_CLOSED_SOURCE_ENV = "COBOLPARSER_CLOSED_SOURCE"
_REPO_ROOT = Path(__file__).resolve().parent


def _closed_source_enabled() -> bool:
    return os.environ.get(_CLOSED_SOURCE_ENV) == "1"


def _iter_closed_source_py_files():
    """Yield (dotted.module.name, relative/path.py) for every cobolparser
    module that should be compiled and stripped of its .py source, i.e.
    everything except __init__.py files."""
    pkg_dir = _REPO_ROOT / _PKG
    for path in sorted(pkg_dir.rglob("*.py")):
        if path.name == "__init__.py":
            continue
        rel = path.relative_to(_REPO_ROOT)
        dotted = ".".join(rel.with_suffix("").parts)
        yield dotted, str(rel)


class _ClosedSourceBuildPy(_build_py):
    """Only copy __init__.py files -- every other .py module has a compiled
    extension twin (see _iter_closed_source_py_files) and must not ship as
    readable source in the built distribution."""

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [
            (pkg, mod, file)
            for (pkg, mod, file) in modules
            if os.path.basename(file) == "__init__.py"
        ]


def _build_ext_modules() -> list:
    if os.environ.get("COBOLPARSER_SKIP_EXT") == "1":
        return []

    try:
        from Cython.Build import cythonize
    except ImportError:
        if _closed_source_enabled():
            raise RuntimeError(
                f"{_CLOSED_SOURCE_ENV}=1 requires Cython to be installed"
            )
        # No Cython -> build directly from the checked-in .c files.
        return [
            Extension(f"{_PKG}.{m}", [os.path.join(_PKG, f"{m}.c")])
            for m in _MODULES
            if os.path.exists(os.path.join(_PKG, f"{m}.c"))
        ]

    extensions = [
        Extension(f"{_PKG}.{m}", [os.path.join(_PKG, f"{m}.pyx")]) for m in _MODULES
    ]

    if _closed_source_enabled():
        extensions += [
            Extension(dotted, [rel]) for dotted, rel in _iter_closed_source_py_files()
        ]

    return cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
        },
    )


setup(
    ext_modules=_build_ext_modules(),
    cmdclass={"build_py": _ClosedSourceBuildPy} if _closed_source_enabled() else {},
)
```

- [ ] **Step 5: Run the script again to confirm it now passes**

Run: `python scripts/verify_closed_source_wheel.py`
Expected: prints `OK: only N __init__.py stub(s) present, no other .py source`, then `smoke test OK`, then `All checks passed.` (this step compiles ~125 modules through Cython + a C compiler in an isolated build environment — expect several minutes, not seconds).

- [ ] **Step 6: Confirm the default (non-closed-source) build path is unaffected**

Run: `pip install -e ".[dev,fast]"` then `python setup.py build_ext --inplace`
Expected: succeeds exactly as before (this mirrors the existing CI `build` job in `.github/workflows/ci.yml`) — only the 3 accelerator modules compile, everything else stays plain `.py`, `COBOLPARSER_CLOSED_SOURCE` is unset so `_ClosedSourceBuildPy` never activates.

- [ ] **Step 7: Commit**

```bash
git add setup.py scripts/verify_closed_source_wheel.py
git commit -m "feat: add closed-source Cythonized build mode"
```

---

### Task 2: Wire the closed-source flag into `cibuildwheel`

**Files:**
- Modify: `pyproject.toml` (the existing `[tool.cibuildwheel]` table)

**Interfaces:**
- Consumes: env var `COBOLPARSER_CLOSED_SOURCE` from Task 1.

- [ ] **Step 1: Update the `[tool.cibuildwheel]` table**

In `pyproject.toml`, replace:

```toml
[tool.cibuildwheel]
# Build CPython 3.11–3.13 only (matches requires-python)
build = "cp311-* cp312-* cp313-*"
# Smoke-test: verify the C extension actually loaded, not just the pure-Python fallback
test-command = "python -c \"from cobolparser._lexer_fast import CobolLexer; from cobolparser._preprocess_fast import normalize_fixed_format; from cobolparser._data_fast import parse_data_item_clauses_fast; print('C extensions OK')\""
```

with:

```toml
[tool.cibuildwheel]
# Build CPython 3.11–3.13 only (matches requires-python)
build = "cp311-* cp312-* cp313-*"
# Full closed-source build: every cobolparser module compiles, not just the
# 3 hot-path accelerators. See setup.py and
# docs/plans/2026-08-14-pypi-closed-source-release-design.md.
environment = { COBOLPARSER_CLOSED_SOURCE = "1" }
test-requires = "pytest"
# Smoke-test against the INSTALLED wheel (not the source tree): verify
# ordinary modules loaded as compiled extensions (no .py source backing
# them), then run a fast subset of the suite. --no-cov disables this repo's
# default --cov-fail-under=81 gate (see [tool.pytest.ini_options] addopts),
# which coverage.py can't evaluate meaningfully against compiled extensions.
test-command = "python -c \"import cobolparser.lexer, cobolparser.parser; assert not cobolparser.lexer.__file__.endswith('.py'); assert not cobolparser.parser.__file__.endswith('.py'); from cobolparser._lexer_fast import CobolLexer; from cobolparser._preprocess_fast import normalize_fixed_format; from cobolparser._data_fast import parse_data_item_clauses_fast; print('closed-source build OK')\" && pytest {project}/tests/unit/test_lexer.py {project}/tests/test_all_samples.py --no-cov -q"
```

(Leave `[tool.cibuildwheel.linux]`, `[tool.cibuildwheel.macos]`, `[tool.cibuildwheel.windows]` untouched.)

- [ ] **Step 2: Verify the TOML is well-formed and contains the expected keys**

Run:

```bash
python -c "
import tomllib
with open('pyproject.toml', 'rb') as f:
    data = tomllib.load(f)
cfg = data['tool']['cibuildwheel']
assert cfg['environment']['COBOLPARSER_CLOSED_SOURCE'] == '1'
assert cfg['test-requires'] == 'pytest'
assert 'cobolparser.lexer' in cfg['test-command']
assert 'cobolparser.parser' in cfg['test-command']
assert 'pytest {project}' in cfg['test-command']
assert '--no-cov' in cfg['test-command']
print('pyproject.toml cibuildwheel config OK')
"
```

Expected: `pyproject.toml cibuildwheel config OK`

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: compile the full package for closed-source release wheels"
```

---

### Task 3: Drop the source-carrying release job, add PyPI publishing

**Files:**
- Modify: `.github/workflows/release-please.yml`

**Interfaces:**
- Consumes: nothing new at the code level (cibuildwheel reads `pyproject.toml` automatically); relies on the `build-binary-wheels` job and `dist-wheels-*` artifact naming already present in the file being unchanged.

- [ ] **Step 1: Replace the workflow file**

Replace the full contents of `.github/workflows/release-please.yml` with:

```yaml
name: release-please

on:
  push:
    branches:
      - main

permissions:
  contents: write
  pull-requests: write
  issues: write

jobs:
  release-please:
    runs-on: ubuntu-latest
    outputs:
      # `releases_created` is the aggregate flag for manifest mode: true on the
      # run where the "chore: release X" PR is merged and the release is cut.
      releases_created: ${{ steps.release.outputs.releases_created }}
    steps:
      - uses: googleapis/release-please-action@v4
        id: release
        with:
          # GITHUB_TOKEN works out of the box. Releases it creates do NOT
          # trigger other workflows -- that's why the publish jobs below live
          # in THIS same workflow (gated on the output) instead of a separate
          # release-triggered workflow, which would never fire.
          token: ${{ secrets.GITHUB_TOKEN }}
          config-file: release-please-config.json
          manifest-file: .release-please-manifest.json

  # Build binary wheels for Linux, macOS, Windows. cibuildwheel compiles
  # EVERY cobolparser module (COBOLPARSER_CLOSED_SOURCE=1, set in
  # pyproject.toml's [tool.cibuildwheel.environment]) into .so/.pyd files, so
  # the resulting wheels never contain readable .py source (only thin
  # __init__.py re-export stubs). No sdist and no pure-Python fallback wheel
  # are built anywhere -- both would ship full source.
  build-binary-wheels:
    needs: release-please
    if: ${{ needs.release-please.outputs.releases_created == 'true' }}
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, macos-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      # QEMU lets the Linux runner cross-compile aarch64 wheels without a real ARM machine.
      - uses: docker/setup-qemu-action@v3
        if: runner.os == 'Linux'
        with:
          platforms: aarch64
      - uses: pypa/cibuildwheel@v2.21.3
      - uses: actions/upload-artifact@v4
        with:
          name: dist-wheels-${{ matrix.os }}
          path: wheelhouse/

  # Attach the closed-source wheels to the GitHub Release for traceability /
  # manual download.
  publish:
    needs: [release-please, build-binary-wheels]
    if: ${{ needs.release-please.outputs.releases_created == 'true' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/download-artifact@v4
        with:
          pattern: dist-wheels-*
          path: dist/
          merge-multiple: true
      - name: Resolve the release tag from the manifest
        id: tag
        # The merge commit that triggered this run already bumped the manifest
        # to the released version; tags use the v<version> format
        # (include-component-in-tag: false).
        run: echo "tag=v$(jq -r '.["."]' .release-please-manifest.json)" >> "$GITHUB_OUTPUT"
      - name: Attach distributions to the GitHub Release
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: gh release upload "${{ steps.tag.outputs.tag }}" dist/* --clobber

  # Publish the same closed-source wheels to PyPI via Trusted Publishing
  # (OIDC) -- no stored API token/secret. Requires a one-time manual step on
  # pypi.org registering this repo/workflow as a trusted publisher for the
  # "cobolparser" project; see
  # docs/plans/2026-08-14-pypi-closed-source-release-design.md.
  publish-pypi:
    needs: [release-please, build-binary-wheels]
    if: ${{ needs.release-please.outputs.releases_created == 'true' }}
    runs-on: ubuntu-latest
    environment:
      name: pypi
      url: https://pypi.org/project/cobolparser/
    permissions:
      id-token: write
    steps:
      - uses: actions/download-artifact@v4
        with:
          pattern: dist-wheels-*
          path: dist/
          merge-multiple: true
      - uses: pypa/gh-action-pypi-publish@release/v1
        with:
          packages-dir: dist/
```

- [ ] **Step 2: Verify the workflow structure**

Run:

```bash
grep -q "^  publish-pypi:" .github/workflows/release-please.yml && echo "publish-pypi job present"
grep -q "id-token: write" .github/workflows/release-please.yml && echo "OIDC permission present"
grep -q "^  build-sdist:" .github/workflows/release-please.yml && echo "FAIL: build-sdist still present" || echo "build-sdist job removed"
grep -q "pypa/gh-action-pypi-publish" .github/workflows/release-please.yml && echo "PyPI publish action present"
```

Expected: all four lines print their "present"/"removed" success message, none print `FAIL`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release-please.yml
git commit -m "ci: publish closed-source wheels to PyPI, drop source-carrying sdist job"
```

---

## Manual step (not part of this plan's tasks, cannot be automated from this repo)

Before the next release-please release runs, register `Landparty/cobol-parser`'s `release-please.yml` workflow (job `publish-pypi`, environment `pypi`) as a **Trusted Publisher** for the `cobolparser` project on pypi.org. Since `cobolparser` doesn't exist on PyPI yet, use PyPI's "pending publisher" flow (create the pending trusted publisher entry before the first run — no manual first upload needed). Without this, `publish-pypi` will fail with an OIDC authentication error on the first release.
