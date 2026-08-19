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

# File names that must stay plain .py source even in a closed-source build.
#
# __init__.py: the whole strategy assumes package __init__ files are thin
#   re-export stubs with no business logic of their own. Keep them that way --
#   anything substantial belongs in a private sibling module that *does* get
#   compiled (see cobolparser/preprocess/_normalize.py, which was split out of
#   preprocess/__init__.py for exactly this reason).
# __main__.py: runpy needs a code object to execute `python -m cobolparser`,
#   and extension-module loaders return None from get_code(), which fails with
#   an opaque "No code object available". It is a 3-line shim over
#   cobolparser.cli:main, so shipping it as source discloses nothing.
_UNCOMPILED_FILENAMES = frozenset({"__init__.py", "__main__.py"})


def _closed_source_enabled() -> bool:
    return os.environ.get(_CLOSED_SOURCE_ENV) == "1"


def _iter_closed_source_py_files():
    """Yield (dotted.module.name, relative/path.py) for every cobolparser
    module that should be compiled and stripped of its .py source, i.e.
    everything except the _UNCOMPILED_FILENAMES shims."""
    pkg_dir = _REPO_ROOT / _PKG
    for path in sorted(pkg_dir.rglob("*.py")):
        if path.name in _UNCOMPILED_FILENAMES:
            continue
        rel = path.relative_to(_REPO_ROOT)
        dotted = ".".join(rel.with_suffix("").parts)
        yield dotted, str(rel)


class _ClosedSourceBuildPy(_build_py):
    """Only copy the _UNCOMPILED_FILENAMES shims -- every other .py module has
    a compiled extension twin (see _iter_closed_source_py_files) and must not
    ship as readable source in the built distribution."""

    def find_package_modules(self, package, package_dir):
        modules = super().find_package_modules(package, package_dir)
        return [
            (pkg, mod, file)
            for (pkg, mod, file) in modules
            if os.path.basename(file) in _UNCOMPILED_FILENAMES
        ]


def _build_ext_modules() -> list:
    if os.environ.get("COBOLPARSER_SKIP_EXT") == "1":
        if _closed_source_enabled():
            # Closed-source mode strips .py source for every compiled module
            # (_ClosedSourceBuildPy). Skipping the extension build on top of
            # that would ship a distribution with neither the compiled
            # extension nor the .py source for those modules -- broken, not
            # merely slower. Fail fast instead of silently producing it.
            raise RuntimeError(
                f"COBOLPARSER_SKIP_EXT=1 and {_CLOSED_SOURCE_ENV}=1 are "
                "mutually exclusive: skipping the extension build while "
                "also stripping .py source would produce a distribution "
                "missing both the compiled extensions and the source for "
                "every closed-source module."
            )
        return []

    try:
        from Cython.Build import cythonize
    except ImportError as exc:
        if _closed_source_enabled():
            raise RuntimeError(
                f"{_CLOSED_SOURCE_ENV}=1 requires Cython to be installed"
            ) from exc
        # No Cython -> build directly from the checked-in .c files.
        return [
            Extension(f"{_PKG}.{m}", [os.path.join(_PKG, f"{m}.c")])
            for m in _MODULES
            if os.path.exists(os.path.join(_PKG, f"{m}.c"))
        ]

    accelerator_extensions = [
        Extension(f"{_PKG}.{m}", [os.path.join(_PKG, f"{m}.pyx")]) for m in _MODULES
    ]
    # boundscheck/wraparound/cdivision=False are safe ONLY for these 3
    # accelerators: they're hand-written in explicit Cython-typed style and
    # were audited for it. They must NOT extend to the ~113 auto-Cythonized
    # closed-source modules below -- those are ordinary Python business
    # logic that uses plain `list[-1]` indexing throughout (e.g.
    # divisions/procedure.py's `active[-1]`), and wraparound=False silently
    # turns that into an unchecked, unadjusted raw index -1: an
    # out-of-bounds read, not a Python-level error. Root-caused via a gdb
    # backtrace on a closed-source Linux build landing in
    # __Pyx_GetItemInt_Fast with wraparound=0, i=-1 against a genuine
    # one-element list -- confirmed by rebuilding with these two directive
    # sets split apart, which alone fixed a reproducible segfault in
    # CobolParser(free_form=True).parse(...). See
    # docs/superpowers/specs/2026-08-18-overload-cython-crash-fix.md.
    accelerators = cythonize(
        accelerator_extensions,
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
        },
    )

    if not _closed_source_enabled():
        return accelerators

    closed_source_extensions = [
        Extension(dotted, [rel]) for dotted, rel in _iter_closed_source_py_files()
    ]
    closed_source = cythonize(
        closed_source_extensions,
        # Closed-source mode cythonizes ~113 modules; translating them one at
        # a time dominates the build (and, on the emulated aarch64 CI runner,
        # risks the 6-hour job limit). 0 means "serial" to Cython, so clamp to
        # at least 1 when os.cpu_count() returns None.
        nthreads=os.cpu_count() or 1,
        compiler_directives={
            "language_level": "3",
            # Deliberately NOT boundscheck/wraparound/cdivision=False --
            # see the comment above. Cython's real defaults (bounds- and
            # wraparound-checked) are correctness-over-speed for this
            # whole-program business-logic build.
            #
            # annotation_typing=False applies to every extension in this
            # cythonize() call. It's a no-op here now that parser.py's
            # @overload stubs are TYPE_CHECKING-guarded (never reach
            # Cython at all), but is kept as a defensive default: without
            # it, Cython enforces PEP 484 annotations as runtime C-level
            # argument types, which breaks on any future
            # `def f(x: str = ...)`-style overload stub the same way.
            "annotation_typing": False,
        },
    )
    return accelerators + closed_source


setup(
    ext_modules=_build_ext_modules(),
    cmdclass={"build_py": _ClosedSourceBuildPy} if _closed_source_enabled() else {},
)
