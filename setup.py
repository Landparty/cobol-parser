"""Build script for the optional Cython extension modules.

The pure-Python implementation is the default, so a stock ``pip install .``
compiles nothing and needs no C compiler. The three accelerators
(``_lexer_fast``, ``_preprocess_fast``, ``_data_fast``) are an opt-in, chosen
by one environment variable at both ends:

    COBOLPARSER_ACCEL=1 pip install .                     # compile them
    COBOLPARSER_ACCEL=1 python setup.py build_ext --inplace  # in a checkout
    COBOLPARSER_ACCEL=1 python -m cobolparser ...         # and use them

The variable is read again at import time (``cobolparser._accel``): an
installed extension is ignored unless it is set, so building them alone does
not change which backend runs.

The pre-generated ``.c`` files are checked into the repository, so the opt-in
build needs only a C compiler; when Cython *is* available the ``.pyx`` sources
are re-cythonized first so local edits take effect.

``COBOLPARSER_SKIP_EXT=1`` (the old opt-out) is still honoured and wins over
``COBOLPARSER_ACCEL``.
"""

import os

from setuptools import setup
from setuptools.extension import Extension

_PKG = "cobolparser"
_MODULES = ("_lexer_fast", "_preprocess_fast", "_data_fast")


def _build_ext_modules() -> list:
    if os.environ.get("COBOLPARSER_SKIP_EXT") == "1":
        return []
    # Same truthy spellings as cobolparser._accel, which setup.py cannot import
    # (the package is not importable before it is built).
    accel = os.environ.get("COBOLPARSER_ACCEL", "").strip().lower()
    if accel not in {"1", "true", "yes", "on"}:
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
