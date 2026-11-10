"""Fetch the open-source COBOL corpus listed in ``manifest.toml``.

Usage::

    python tools/corpus/fetch.py                 # every source, into .corpus/
    python tools/corpus/fetch.py --only carddemo --dest /tmp/corpus

Each git source is fetched shallow at its pinned commit (so results are
repeatable) into ``<dest>/<id>/``. A ``gnucobol-at`` source is then unpacked:
every ``AT_DATA`` file of a test whose compile step is expected to succeed is
written to ``<dest>/<id>/_extracted/<at-file>/<NNN>/``, programs and the
copybooks they COPY side by side. Nothing fetched is ever written inside the
package or committed; ``.corpus/`` is git-ignored.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tomllib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent.parent
DEFAULT_DEST = REPO_ROOT / ".corpus"


def load_manifest(path: Path = HERE / "manifest.toml") -> list[dict]:
    with path.open("rb") as fh:
        return list(tomllib.load(fh)["source"])


def _git(*args: str, cwd: Path) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, stdout=subprocess.DEVNULL)


def fetch_git(source: dict, dest: Path) -> Path:
    target = dest / source["id"]
    stamp = target / ".corpus-commit"
    if stamp.exists() and stamp.read_text().strip() == source["commit"]:
        return target
    target.mkdir(parents=True, exist_ok=True)
    if not (target / ".git").exists():
        _git("init", "-q", cwd=target)
        _git("remote", "add", "origin", source["repo"], cwd=target)
    _git("fetch", "-q", "--depth", "1", "origin", source["commit"], cwd=target)
    _git("checkout", "-q", "--force", "FETCH_HEAD", cwd=target)
    stamp.write_text(source["commit"] + "\n")
    return target


# -- GnuCOBOL autotest extraction ------------------------------------------

_SETUP_RE = re.compile(r"^AT_SETUP\(\[(.*?)\]\)", re.M)
_DATA_RE = re.compile(r"^AT_DATA\(\[([^\]]+)\],\s*\[\n?(.*?)^\]\)", re.M | re.S)
# m4 quadrigraphs used inside quoted test data.
_QUADRIGRAPHS = {"@<:@": "[", "@:>@": "]", "@S|@": "$", "@%:@": "#", "@&t@": ""}
_COBOL_SUFFIXES = (".cob", ".cbl", ".cpy", ".CPY", ".CBL", ".COB")


def _unquote(text: str) -> str:
    for quad, char in _QUADRIGRAPHS.items():
        text = text.replace(quad, char)
    return text


def extract_autotest(at_file: Path, out_dir: Path) -> int:
    """Write the COBOL files of every compile-success test in *at_file*."""
    text = at_file.read_text(encoding="utf-8", errors="replace")
    written = 0
    blocks = re.split(r"^AT_CLEANUP", text, flags=re.M)
    for number, block in enumerate(blocks, 1):
        if not _SETUP_RE.search(block):
            continue
        # Only tests that expect the compile to succeed (status 0) hold
        # programs the compiler accepts; a non-zero status marks a test of a
        # diagnostic.
        if not re.search(r"AT_CHECK\(\[\$COMPILE[^\]]*\],\s*\[0\]", block):
            continue
        files = [
            (name.strip(), _unquote(body))
            for name, body in _DATA_RE.findall(block)
            if name.strip().endswith(_COBOL_SUFFIXES)
        ]
        if not files:
            continue
        test_dir = out_dir / at_file.stem / f"{number:03d}"
        test_dir.mkdir(parents=True, exist_ok=True)
        for name, body in files:
            (test_dir / Path(name).name).write_text(body, encoding="utf-8")
            written += 1
    return written


def fetch(source: dict, dest: Path) -> Path:
    if "local" in source:
        return REPO_ROOT / source["local"]
    root = fetch_git(source, dest)
    if source.get("kind") == "gnucobol-at":
        out_dir = root / "_extracted"
        if not out_dir.exists():
            for pattern in source["programs"]:
                for at_file in sorted(root.glob(pattern)):
                    extract_autotest(at_file, out_dir)
    return root


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST)
    parser.add_argument("--only", action="append", help="source id (repeatable)")
    args = parser.parse_args(argv)
    args.dest.mkdir(parents=True, exist_ok=True)
    failed = 0
    for source in load_manifest():
        if args.only and source["id"] not in args.only:
            continue
        try:
            path = fetch(source, args.dest)
            print(f"ok    {source['id']:<26} {path}")
        except subprocess.CalledProcessError as exc:
            failed += 1
            print(f"FAIL  {source['id']:<26} {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
