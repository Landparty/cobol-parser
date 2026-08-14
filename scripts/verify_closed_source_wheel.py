#!/usr/bin/env python3
"""Build a closed-source wheel and verify no .py source leaks into it.

Usage: python scripts/verify_closed_source_wheel.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import venv
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def build_wheel(dist_dir: Path) -> Path:
    env = dict(os.environ)
    env["COBOLPARSER_CLOSED_SOURCE"] = "1"
    subprocess.run(
        [sys.executable, "-m", "build", "--wheel", "--outdir", str(dist_dir)],
        cwd=REPO_ROOT,
        env=env,
        check=True,
    )
    wheels = list(dist_dir.glob("cobolparser-*.whl"))
    if len(wheels) != 1:
        raise RuntimeError(f"expected exactly one wheel, found {wheels}")
    return wheels[0]


def check_no_leaked_source(wheel_path: Path) -> None:
    with zipfile.ZipFile(wheel_path) as zf:
        py_files = [
            n
            for n in zf.namelist()
            if n.startswith("cobolparser/") and n.endswith(".py")
        ]
    leaked = [n for n in py_files if not n.endswith("__init__.py")]
    if leaked:
        raise AssertionError(f"wheel leaks source for: {leaked}")
    if not py_files:
        raise AssertionError("expected at least the __init__.py stubs, found none")
    print(f"OK: only {len(py_files)} __init__.py stub(s) present, no other .py source")


def smoke_test_install(wheel_path: Path, venv_dir: Path) -> None:
    venv.create(venv_dir, with_pip=True)
    bin_dir = "Scripts" if sys.platform == "win32" else "bin"
    exe = "python.exe" if sys.platform == "win32" else "python"
    python = venv_dir / bin_dir / exe
    subprocess.run([str(python), "-m", "pip", "install", str(wheel_path)], check=True)
    check = (
        "import cobolparser.lexer, cobolparser.parser\n"
        "assert not cobolparser.lexer.__file__.endswith('.py'), cobolparser.lexer.__file__\n"
        "assert not cobolparser.parser.__file__.endswith('.py'), cobolparser.parser.__file__\n"
        "from cobolparser import parse_cobol\n"
        "result = parse_cobol('IDENTIFICATION DIVISION.\\nPROGRAM-ID. X.\\n')\n"
        "assert result.success, result.errors\n"
        "print('smoke test OK')\n"
    )
    # cwd matters here: `python -c` prepends the current directory to
    # sys.path, and REPO_ROOT contains a "cobolparser/" source tree that
    # would otherwise shadow the just-installed wheel in the venv's
    # site-packages, making this check pass even for a broken wheel. Run
    # from venv_dir (which has no such subpackage) so the import is
    # resolved from site-packages only.
    subprocess.run([str(python), "-c", check], cwd=venv_dir, check=True)


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        dist_dir = tmp_path / "dist"
        dist_dir.mkdir()
        wheel_path = build_wheel(dist_dir)
        check_no_leaked_source(wheel_path)
        smoke_test_install(wheel_path, tmp_path / "venv")
    print("All checks passed.")


if __name__ == "__main__":
    main()
