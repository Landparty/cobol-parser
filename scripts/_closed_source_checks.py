"""Shared assertions for the closed-source no-leaked-source invariant.

Used by both verify_closed_source_wheel.py (checks a built wheel's zip
contents, any platform, run manually/locally) and
check_installed_no_leaked_source.py (checks an already-installed package's
files; cibuildwheel's test-command has no access to the wheel path itself,
only to what got installed, so it needs a filesystem-based variant of the
same check).
"""

from __future__ import annotations

# Kept in sync with setup.py's _UNCOMPILED_FILENAMES: the only .py files a
# closed-source build may legitimately contain.
ALLOWED_PY_NAMES = ("__init__.py", "__main__.py")

# Cython embeds the original source verbatim, line by line, in C comments, so
# a shipped .c file is a fully readable copy of the module it came from. .pyx
# and .h are excluded on the same principle; .pyi would disclose the API
# surface the wheel is meant to keep opaque.
FORBIDDEN_SUFFIXES = (".c", ".pyx", ".h", ".pyi")


def assert_no_leaked_source(names: list[str]) -> tuple[int, int]:
    """Check a list of cobolparser-relative path strings (zip entries or
    filesystem paths) for leaked source. Returns (py_file_count,
    ext_file_count) on success; raises AssertionError otherwise.
    """
    py_files = [n for n in names if n.endswith(".py")]
    leaked = [n for n in py_files if not n.endswith(ALLOWED_PY_NAMES)]
    if leaked:
        raise AssertionError(f"leaks .py source for: {leaked}")
    if not py_files:
        raise AssertionError("expected at least the __init__.py stubs, found none")

    leaked_native = [n for n in names if n.endswith(FORBIDDEN_SUFFIXES)]
    if leaked_native:
        raise AssertionError(
            "leaks Cython/C source (these embed the original .py source "
            f"verbatim in comments): {leaked_native}"
        )

    ext_files = [n for n in names if n.endswith((".so", ".pyd"))]
    if not ext_files:
        raise AssertionError("contains no compiled extension modules at all")

    return len(py_files), len(ext_files)
