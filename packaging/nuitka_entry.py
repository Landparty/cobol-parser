"""Standalone entry point for the Nuitka-compiled cobol-parser executable.

Lives outside the cobolparser package deliberately: Nuitka compiles this
file as the onefile's __main__, and cobolparser/cli/__init__.py does a
relative `from .parse import main` that only resolves with real package
context, which a file executed as __main__ never has. See
scripts/build_executable.sh and PUBLISHING.md.
"""

from cobolparser.cli import main

if __name__ == "__main__":
    main()
