#!/usr/bin/env python3
"""Verify an INSTALLED cobolparser package has no leaked closed-source files.

Run by cibuildwheel's [tool.cibuildwheel] test-command (pyproject.toml),
once per built wheel across the full OS x Python matrix. cibuildwheel's
test-command only has access to the installed package, not the original
wheel file, so this walks site-packages instead of unzipping a wheel --
see verify_closed_source_wheel.py for the equivalent zip-based check used
for manual/local verification.
"""

from __future__ import annotations

from pathlib import Path

from _closed_source_checks import assert_no_leaked_source


def main() -> None:
    import cobolparser

    pkg_dir = Path(cobolparser.__file__).resolve().parent
    names = [
        str(p.relative_to(pkg_dir.parent)) for p in pkg_dir.rglob("*") if p.is_file()
    ]

    py_count, ext_count = assert_no_leaked_source(names)
    print(
        f"OK: {py_count} allowed .py shim(s), {ext_count} compiled "
        "extension(s), no .c/.pyx/.h/.pyi source"
    )


if __name__ == "__main__":
    main()
