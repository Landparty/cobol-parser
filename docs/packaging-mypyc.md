# Packaging with mypyc

This guide explains how to build a compiled, binary distribution of `cobolparser` using [mypyc](https://mypyc.readthedocs.io/). The compiled wheel contains no readable Python source — only native `.pyd` (Windows) or `.so` (Linux/macOS) extension modules.

## How it works

mypyc compiles type-annotated Python to C, then to platform-native machine code via your system's C compiler. The result is a wheel that:

- Installs and imports identically to the pure-Python version (`from cobolparser import parse_cobol`)
- Contains no `.py` source files
- Runs 1.5–4× faster than the pure-Python version for CPU-bound workloads

## Prerequisites

### Python

Python 3.13 or later is required (matches `requires-python` in `pyproject.toml`).

### C compiler

mypyc generates C code that must be compiled. You need a C compiler for your target platform.

| Platform | Compiler | How to install |
|---|---|---|
| Windows | MSVC | [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) → select "Desktop development with C++" |
| Linux | GCC | `sudo apt install build-essential` (Debian/Ubuntu) or `sudo dnf install gcc` (Fedora) |
| macOS | Clang | `xcode-select --install` |

### Python packages

```bash
pip install mypy setuptools wheel
```

> **Note:** Install mypy without pre-compiled binaries to avoid Windows Application Control policy blocks:
> ```bash
> pip install mypy --no-binary mypy
> ```

## Building locally

From the repository root:

```bash
python setup.py build_ext --inplace
```

This compiles all modules in-place alongside the source files. After the build succeeds you will see `.pyd` (Windows) or `.so` (Linux/macOS) files next to each `.py` file.

To produce a distributable wheel:

```bash
pip install build
python -m build --wheel
```

The wheel is written to `dist/cobolparser-<version>-cp313-cp313-<platform>.whl`.

> Unlike pure-Python wheels (`py3-none-any`), mypyc wheels are platform-specific. A wheel built on Windows only works on Windows. Build separately for each target platform.

## Building for multiple platforms with GitHub Actions

The recommended approach for distribution is to build wheels in CI, where the required C compilers are pre-installed on all runners.

Create `.github/workflows/build-wheels.yml`:

```yaml
name: Build wheels

on:
  push:
    tags:
      - "v*"
  workflow_dispatch:

jobs:
  build:
    name: Build on ${{ matrix.os }}
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]

    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"

      - name: Install build dependencies
        run: pip install mypy --no-binary mypy setuptools wheel build

      - name: Build wheel
        run: python -m build --wheel

      - name: Upload wheel
        uses: actions/upload-artifact@v4
        with:
          name: wheel-${{ matrix.os }}
          path: dist/*.whl
```

Push a version tag to trigger the build:

```bash
git tag v1.0.0
git push origin v1.0.0
```

The compiled wheels for all three platforms appear as artifacts on the Actions run.

## Installing a compiled wheel

```bash
pip install dist/cobolparser-1.0.0-cp313-cp313-win_amd64.whl
```

Users import the package exactly as before — no changes to their code:

```python
from cobolparser import parse_cobol

result = parse_cobol(source)
```

## Project files involved

| File | Purpose |
|---|---|
| [`setup.py`](../setup.py) | Defines which modules mypyc compiles via `mypycify()` |
| [`pyproject.toml`](../pyproject.toml) | Declares `mypy` as a build-system dependency |

## Adding or removing compiled modules

Edit the `modules` list in [`setup.py`](../setup.py). Every `.py` file listed there will be compiled; unlisted files remain as plain Python source in the wheel.

The `cobolparser/cli/coverage.py` module is intentionally excluded because it imports `render_markdown`, a runtime tool not present in user environments.

## Troubleshooting

**`ModuleNotFoundError: No module named 'distutils'`**

Python 3.12+ removed `distutils`. The fix is already in `setup.py` (`import setuptools` before `mypyc`), but requires `setuptools` to be installed:

```bash
pip install setuptools
```

**`An Application Control policy has blocked this file`** (Windows)

The pre-compiled mypy binaries are blocked by Windows Defender Application Control on some systems. Install the pure-Python version instead:

```bash
pip install mypy --no-binary mypy --force-reinstall
```

**`error: Microsoft Visual C++ 14.0 or greater is required`** (Windows)

Install [Visual Studio Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) and select "Desktop development with C++".

**Type errors during build**

mypyc runs mypy before compiling. Any type error in the package will abort the build. Run `python -m mypy cobolparser/` to see errors before attempting a full build.
