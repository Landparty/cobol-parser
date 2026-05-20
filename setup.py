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
"""

import os

from setuptools import setup
from setuptools.extension import Extension

_PKG = "cobolparser"
_MODULES = ("_lexer_fast", "_preprocess_fast")


def _build_ext_modules() -> list:
    if os.environ.get("COBOLPARSER_SKIP_EXT") == "1":
        return []

    try:
        from Cython.Build import cythonize

        sources = [os.path.join(_PKG, f"{m}.pyx") for m in _MODULES]
        extensions = [Extension(f"{_PKG}.{m}", [s]) for m, s in zip(_MODULES, sources)]
        return cythonize(
            extensions,
            compiler_directives={
                "language_level": "3",
                "boundscheck": False,
                "wraparound": False,
                "cdivision": True,
            },
        )
    except ImportError:
        # No Cython -> build directly from the checked-in .c files.
        return [
            Extension(f"{_PKG}.{m}", [os.path.join(_PKG, f"{m}.c")])
            for m in _MODULES
            if os.path.exists(os.path.join(_PKG, f"{m}.c"))
        ]


setup(ext_modules=_build_ext_modules())
