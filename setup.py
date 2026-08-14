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
See docs/superpowers/specs/2026-08-14-pypi-closed-source-release-design.md.
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
            # The 3 .pyx accelerators type their hot paths with explicit
            # Cython syntax (`def f(str text, int pos)`), which this
            # directive does not touch. It only matters for closed-source
            # mode, where whole modules with plain PEP 484 annotations get
            # cythonized: without it, Cython enforces those annotations as
            # runtime C-level argument types, which breaks on
            # `typing.overload` stub signatures like
            # `def parse(self, filename: str = ...)` (Ellipsis is not a
            # str). Keeping annotations inert for typing purposes only
            # matches the pure-Python fallback's behavior.
            "annotation_typing": False,
        },
    )


setup(
    ext_modules=_build_ext_modules(),
    cmdclass={"build_py": _ClosedSourceBuildPy} if _closed_source_enabled() else {},
)
