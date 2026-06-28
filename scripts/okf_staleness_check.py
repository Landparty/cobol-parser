#!/usr/bin/env python3
"""OKF staleness checker — keeps docs/okf/ in sync with source changes.

Modes
-----
  (no args)      Claude Code PostToolUse hook: read tool JSON from stdin,
                 print a one-line reminder if the OKF file wasn't touched yet.
  --mode=git     Git pre-commit hook: check staged files and exit 1 if any
                 OKF-covered source changed without a corresponding OKF update.
"""

import json
import subprocess
import sys
from pathlib import Path

OKF_MAP = [
    ("cobolparser/lexer.py", ["docs/okf/lexer.md"]),
    ("cobolparser/_lexer_fast.pyx", ["docs/okf/lexer.md"]),
    ("cobolparser/preprocess/", ["docs/okf/preprocessing.md"]),
    ("cobolparser/_preprocess_fast.pyx", ["docs/okf/preprocessing.md"]),
    ("cobolparser/parsers/", ["docs/okf/parser.md"]),
    ("cobolparser/core/", ["docs/okf/parser.md"]),
    ("cobolparser/models/", ["docs/okf/ast-models.md"]),
    ("cobolparser/_data_fast.pyx", ["docs/okf/ast-models.md"]),
    ("cobolparser/analysis/", ["docs/okf/analysis.md"]),
    ("cobolparser/batch.py", ["docs/okf/batch.md"]),
    ("cobolparser/cli/", ["docs/okf/cli.md"]),
    ("cobolparser/dialects/", ["docs/okf/dialects.md"]),
    ("tests/", ["docs/okf/tests.md"]),
]


def _get_okf_files(rel_path: str) -> list:
    seen: set = set()
    result = []
    for prefix, okf_files in OKF_MAP:
        if rel_path.startswith(prefix) or rel_path == prefix.rstrip("/"):
            for f in okf_files:
                if f not in seen:
                    seen.add(f)
                    result.append(f)
    return result


def _git(args, cwd):
    r = subprocess.run(["git"] + args, cwd=cwd, capture_output=True, text=True)
    return r.stdout.strip()


def _is_okf_modified(okf_file: str, repo_root: Path) -> bool:
    return bool(_git(["status", "--porcelain", okf_file], repo_root))


def _git_mode(repo_root: Path) -> int:
    staged_raw = _git(["diff", "--cached", "--name-only"], repo_root)
    staged = set(f.strip() for f in staged_raw.splitlines() if f.strip())

    needs_update: dict = {}
    for src in staged:
        if src.startswith("docs/"):
            continue
        for okf_file in _get_okf_files(src):
            if okf_file not in staged:
                needs_update.setdefault(okf_file, set()).add(src)

    if not needs_update:
        return 0

    print("OKF staleness warning — update these docs before committing:")
    for okf_file in sorted(needs_update):
        triggers = ", ".join(sorted(needs_update[okf_file]))
        print(f"  {okf_file}  (changed by: {triggers})")
    print()
    print("To bypass: git commit --no-verify")
    return 1


def _claude_mode(repo_root: Path) -> int:
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    file_path = (data.get("tool_input") or {}).get("file_path", "")
    if not file_path:
        return 0

    try:
        rel = Path(file_path).relative_to(repo_root).as_posix()
    except ValueError:
        rel = file_path.replace("\\", "/")
        for marker in ("cobolparser/", "tests/", "docs/"):
            idx = rel.find(marker)
            if idx != -1:
                rel = rel[idx:]
                break

    if rel.startswith("docs/"):
        return 0

    okf_files = _get_okf_files(rel)
    stale = [f for f in okf_files if not _is_okf_modified(f, repo_root)]
    for f in stale:
        print(f"[OKF] {rel} — consider updating {f}")

    return 0


def main():
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        return 0
    repo_root = Path(result.stdout.strip())

    if "--mode=git" in sys.argv:
        return _git_mode(repo_root)
    return _claude_mode(repo_root)


if __name__ == "__main__":
    sys.exit(main())
