"""Build script for optional Cython extension modules.

Compile in-place during development:
    python setup.py build_ext --inplace

Install with fast extras:
    pip install -e ".[dev]"
    python setup.py build_ext --inplace
"""

from setuptools import setup

try:
    from Cython.Build import cythonize
    from setuptools.extension import Extension

    extensions = [
        Extension(
            "cobolparser._lexer_fast",
            ["cobolparser/_lexer_fast.pyx"],
        ),
        Extension(
            "cobolparser._preprocess_fast",
            ["cobolparser/_preprocess_fast.pyx"],
        ),
    ]

    ext_modules = cythonize(
        extensions,
        compiler_directives={
            "language_level": "3",
            "boundscheck": False,
            "wraparound": False,
            "cdivision": True,
        },
    )
except ImportError:
    ext_modules = []

setup(ext_modules=ext_modules)
