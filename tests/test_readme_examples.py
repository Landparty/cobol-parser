"""Every example in README.md's command and Python API sections, run as written.

The README promises one working example per subcommand and per public entry
point. This test builds the project the README describes (``src/``,
``copybooks/``, ``jcl/``, ``proclib/``, ``old/``, ``defs/`` and a
``cobol.yml``) from the repo's own sample sources, then runs each
``cobol-parser ...`` line of every ``bash`` block and each ``python`` block
there, in order (later examples read files earlier ones wrote). A README edit
that adds a command example is checked with no change here; one that names a
new sample file needs that file added to :func:`_build_project`.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.slow]

REPO_ROOT = Path(__file__).resolve().parent.parent
README = REPO_ROOT / "README.md"
SHOP = REPO_ROOT / "tests" / "eval" / "shop"
ENTERPRISE = REPO_ROOT / "tests" / "samples" / "enterprise"
DEFINITIONS = REPO_ROOT / "tests" / "samples" / "definitions"

_BLOCK_RE = re.compile(r"```(bash|python)\n(.*?)```", re.S)


def _examples() -> list[tuple[str, str]]:
    text = README.read_text(encoding="utf-8")
    start = text.index("## Every command, with an example")
    end = text.index("## Language coverage")
    out: list[tuple[str, str]] = []
    for lang, block in _BLOCK_RE.findall(text[start:end]):
        if lang == "python":
            out.append(("python", block))
            continue
        for line in block.splitlines():
            command = line.split("  #")[0].strip()
            if command.startswith("cobol-parser "):
                out.append(("bash", command))
    return out


def _build_project(root: Path) -> None:
    for name in ("src", "copybooks", "jcl", "proclib", "old", "defs"):
        (root / name).mkdir()
    for path in (SHOP / "orders").glob("*.cbl"):
        shutil.copy(path, root / "src")
    for path in (SHOP / "orders" / "copy").glob("*.cpy"):
        shutil.copy(path, root / "copybooks")
    for path in (SHOP / "jcl").glob("*.jcl"):
        shutil.copy(path, root / "jcl")
    for lib in ("SHOP.ORD.PROCLIB", "SYS1.PROCLIB"):
        for path in (SHOP / lib).iterdir():
            shutil.copy(path, root / "proclib")
    for name in ("DB2BATCH", "CICSONLN", "IMSMPP", "LESERV"):
        shutil.copy(ENTERPRISE / f"{name}.cbl", root / "src")
    for path in (ENTERPRISE / "copybooks").iterdir():
        shutil.copy(path, root / "copybooks")
    shutil.copy(DEFINITIONS / "BANKDDL.ddl", root / "defs")
    # The "old" version the diff examples compare against.
    current = (root / "src" / "ORDPOST.cbl").read_text(encoding="utf-8")
    old = current.replace("VALUE 0.0125", "VALUE 0.0150").replace(
        "IF ORD-HELD\n", "IF ORD-HELD OR ORD-REJECTED\n"
    )
    assert old != current, "ORDPOST.cbl changed; update the diff fixture"
    (root / "old" / "ORDPOST.cbl").write_text(old, encoding="utf-8")
    (root / "cobol.yml").write_text(
        "version: 1\nproject:\n  copybook_path: [copybooks]\n  proc_path: [proclib]\n",
        encoding="utf-8",
    )


def _git_repo(root: Path) -> bool:
    """A repo whose ``origin/main`` is the project, plus one edit, for
    ``lint --changed-since origin/main``."""
    if shutil.which("git") is None:
        return False

    def git(*args: str) -> None:
        subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=root,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    git("add", "-A")
    git("commit", "-qm", "base")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    path = root / "src" / "ORDPOST.cbl"
    path.write_text(
        path.read_text(encoding="utf-8").replace("'AUDIT '", "'AUDIT: '"),
        encoding="utf-8",
    )
    return True


def _needs_jcl(command: str) -> bool:
    return command.startswith("cobol-parser jcl ") or "--jcl" in command


def test_readme_examples_run(tmp_path: Path) -> None:
    examples = _examples()
    assert len(examples) > 50, "README examples were not found"
    _build_project(tmp_path)
    has_git = _git_repo(tmp_path)
    try:
        import jclparser  # noqa: F401

        has_jcl = True
    except ImportError:
        has_jcl = False

    failures: list[str] = []
    for kind, example in examples:
        if kind == "bash":
            if (_needs_jcl(example) and not has_jcl) or (
                ("--changed-since" in example or "--new-code-since" in example)
                and not has_git
            ):
                continue
            args = example.split(maxsplit=1)[1]
            proc = subprocess.run(
                f"{sys.executable} -m cobolparser {args}",
                shell=True,
                cwd=tmp_path,
                capture_output=True,
                text=True,
            )
            # compare exits like cmp: 1 means "the files differ".
            allowed = {0, 1} if args.startswith("compare ") else {0}
        else:
            if not has_jcl and "cobolparser.jcl" in example:
                continue
            if not has_jcl and "load_jobs" in example:
                continue
            proc = subprocess.run(
                [sys.executable, "-c", example],
                cwd=tmp_path,
                capture_output=True,
                text=True,
            )
            allowed = {0}
        if proc.returncode not in allowed:
            label = example if kind == "bash" else example.strip().splitlines()[0]
            failures.append(
                f"{label}\n  exit {proc.returncode}: {(proc.stderr or proc.stdout)[-800:]}"
            )
    assert not failures, "\n\n".join(failures)
