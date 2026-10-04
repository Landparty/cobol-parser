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
_MODULES = ("_lexer_fast", "_preprocess_fast", "_data_fast")


def _build_ext_modules() -> list:
    if os.environ.get("COBOLPARSER_SKIP_EXT") == "1":
        return []

    try:
        from Cython.Build import cythonize
    except ImportError:
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
    # were audited for it. Do not extend them to ordinary Python modules --
    # plain `list[-1]` indexing would become an unchecked raw read.
    accelerators = cythonize(
        accelerator_extensions,
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
        },
    )

    return accelerators


setup(ext_modules=_build_ext_modules())
