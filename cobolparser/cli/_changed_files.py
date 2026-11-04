"""Which COBOL programs a change touched: ``lint --changed-since REF``.

A CI job on a pull request wants to lint what the pull request changed, not
the whole estate. "What changed" is two things for COBOL:

* a **program** whose own file changed, and
* a program that **COPYs a copybook that changed**, directly or through
  another copybook. Editing a copybook can break a program nobody touched,
  so leaving those out would pass a broken change.

The change set comes from git: every file that differs between the merge base
of *REF* and ``HEAD`` and the working tree (so committed, staged and unstaged
edits all count, which is what a pre-commit run and a CI checkout both need),
plus untracked files git does not ignore. Deleted files are left out; there
is nothing to lint.

Copybook dependencies are found by name, the way the compiler finds them: the
COPY statements of each program (and of each copybook it reaches in the
copybook directories) are read with the same shallow lexer the expander uses,
and a member is matched to a changed file by its name without extension.
Nothing is parsed, so selecting the files costs a fraction of linting them.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

#: Program extensions when neither ``--extension`` nor ``project.extensions``
#: names any: the same default ``codebase-graph`` walks for.
DEFAULT_PROGRAM_EXTENSIONS: tuple[str, ...] = (".cbl", ".cob", ".cobol")


class ChangedFilesError(Exception):
    """git could not answer: not a repository, or *REF* is unknown."""


@dataclass
class ChangeSelection:
    """The programs to lint for a change, and why each one was picked."""

    #: Programs to lint, as paths relative to the current directory, sorted.
    programs: list[str] = field(default_factory=list)
    #: Program path -> the changed copybook member names that pulled it in.
    #: A program that changed itself is not in here.
    via_copybook: dict[str, list[str]] = field(default_factory=dict)
    #: Every changed file git reported, relative to the current directory.
    changed: list[str] = field(default_factory=list)


def _git(args: Sequence[str], cwd: str | None = None) -> str:
    try:
        done = subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ChangedFilesError("git is not installed or not on PATH") from exc
    if done.returncode != 0:
        detail = done.stderr.strip() or f"exit {done.returncode}"
        raise ChangedFilesError(f"git {' '.join(args)}: {detail}")
    return done.stdout


def changed_files(ref: str) -> list[str]:
    """Files changed since the merge base of *ref* and ``HEAD``, relative to
    the current directory: committed, staged, unstaged and untracked (not
    ignored) alike. Deleted files are left out.

    Raises:
        ChangedFilesError: not in a git work tree, or *ref* cannot be
            resolved (in CI usually a shallow clone: check out with
            ``fetch-depth: 0``, or fetch the base branch first).
    """
    top = _git(["rev-parse", "--show-toplevel"]).strip()
    try:
        base = _git(["merge-base", ref, "HEAD"]).strip()
    except ChangedFilesError as exc:
        raise ChangedFilesError(
            f"cannot find where HEAD left {ref!r} ({exc}). In CI, check out "
            "the full history (actions/checkout with fetch-depth: 0) or fetch "
            "the base branch first."
        ) from exc
    names = _git(
        ["diff", "--name-only", "--diff-filter=d", "-z", base, "--"], cwd=top
    ).split("\0")
    names += _git(["ls-files", "--others", "--exclude-standard", "-z"], cwd=top).split(
        "\0"
    )
    out: list[str] = []
    seen: set[str] = set()
    for name in names:
        if not name or name in seen:
            continue
        seen.add(name)
        out.append(os.path.relpath(os.path.join(top, name)))
    return sorted(out)


def tracked_files() -> list[str]:
    """Every file git tracks under the current directory, plus untracked
    files it does not ignore, relative to the current directory."""
    names = _git(["ls-files", "--cached", "--others", "--exclude-standard", "-z"])
    return sorted({n for n in names.split("\0") if n})


def _resolved(path: str) -> str:
    try:
        return str(Path(path).resolve())
    except OSError:
        return path


def _member(path: str) -> str:
    return Path(path).stem.upper()


def _under(path: str, directories: Iterable[str]) -> bool:
    resolved = Path(_resolved(path))
    for directory in directories:
        root = Path(_resolved(directory))
        if resolved == root or root in resolved.parents:
            return True
    return False


def _copy_members(path: str) -> set[str]:
    """Upper-cased member names *path* COPYs (or EXEC SQL INCLUDEs).

    An unreadable file names none: the lint run reports it on its own.
    """
    from ..preprocess import PreprocessingError
    from ..preprocess.copy_statement_parser import extract_copy_statements
    from ..preprocess.copybook_expander import read_program_source

    try:
        text = read_program_source(path)
    except (OSError, PreprocessingError):
        return set()
    try:
        statements = extract_copy_statements(text, path, sql_include=True)
    except Exception:  # noqa: BLE001 -- a lexer slip must not drop the run
        return set()
    return {s.member_name.strip("'\"").upper() for s in statements if s.member_name}


def _copybook_index(directories: Iterable[str]) -> dict[str, list[str]]:
    """Member name -> the files in the copybook directories with that name."""
    index: dict[str, list[str]] = {}
    for directory in directories:
        for root, _dirs, files in os.walk(directory):
            for name in files:
                path = os.path.join(root, name)
                index.setdefault(_member(name), []).append(path)
    return index


def select_changed_programs(
    changed: Sequence[str],
    candidates: Sequence[str],
    copybook_dirs: Sequence[str] = (),
    extensions: Sequence[str] = DEFAULT_PROGRAM_EXTENSIONS,
) -> ChangeSelection:
    """The *candidates* a change touched: those that changed, and those that
    COPY a changed copybook (through any depth of nested COPY).

    *candidates* are the programs that may be linted (already filtered to
    program files). A changed file counts as a copybook when it is not a
    program extension or sits in one of *copybook_dirs*; its member name is
    its file name without extension, upper-cased.
    """
    exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in extensions}
    changed_keys = {_resolved(p) for p in changed}
    changed_members = {
        _member(p)
        for p in changed
        if Path(p).suffix.lower() not in exts or _under(p, copybook_dirs)
    }

    selection = ChangeSelection(changed=list(changed))
    index = _copybook_index(copybook_dirs) if changed_members else {}
    closure_cache: dict[str, set[str]] = {}

    def members_of_copybook(member: str, trail: frozenset[str]) -> set[str]:
        if member in closure_cache:
            return closure_cache[member]
        found: set[str] = set()
        for path in index.get(member, []):
            for inner in _copy_members(path):
                found.add(inner)
                if inner not in trail:
                    found |= members_of_copybook(inner, trail | {inner})
        closure_cache[member] = found
        return found

    for program in candidates:
        if _resolved(program) in changed_keys:
            selection.programs.append(program)
            continue
        if not changed_members:
            continue
        direct = _copy_members(program)
        reached = set(direct)
        for member in direct:
            reached |= members_of_copybook(member, frozenset({member}))
        hits = sorted(reached & changed_members)
        if hits:
            selection.programs.append(program)
            selection.via_copybook[program] = hits
    selection.programs.sort()
    return selection


def program_candidates(
    paths: Iterable[str],
    extensions: Sequence[str] = DEFAULT_PROGRAM_EXTENSIONS,
    copybook_dirs: Sequence[str] = (),
) -> list[str]:
    """The *paths* that are programs: a program extension (any case), and not
    inside a copybook directory (shops keep copybooks as ``.cbl`` too)."""
    exts = {e.lower() if e.startswith(".") else "." + e.lower() for e in extensions}
    return [
        p
        for p in paths
        if Path(p).suffix.lower() in exts and not _under(p, copybook_dirs)
    ]
