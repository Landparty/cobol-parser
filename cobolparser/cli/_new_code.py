"""Which lines are new code: ``lint --new-code-since REF`` and ``--scope``.

A team adopting lint on a large legacy codebase cannot fix every finding at
once, but it can refuse to add new ones. "New code" is what a change added or
edited: the lines that differ between the merge base of *REF* and ``HEAD``,
plus the working tree (committed, staged, unstaged and untracked edits all
count, as they do for ``--changed-since``). A finding is **on new code**
when the line it is reported on (its ``origin`` line in a copybook, else its
line in the program) is one of those lines. A finding without a line is on
new code only when its whole file is new.

Each rule is judged on one **scope**: ``new`` keeps only its findings on new
code, ``all`` keeps every finding, wherever it is. ``--scope new`` /
``--scope all`` sets the default for every rule, and ``--scope RULE=all``
(or ``RULE/KIND=all``) one rule, so a team can gate ``call-check`` on the
whole codebase while holding style rules to new code only. Findings a scope
drops are counted in the report, not listed.

The line set comes from ``git diff -U0`` (renames followed, so a moved
program is not all new). Nothing is parsed here.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any

from ._changed_files import ChangedFilesError, _git

#: Scope values. ``new``: only findings on new code count; ``all``: every one.
SCOPES: tuple[str, ...] = ("new", "all")

_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass
class NewCode:
    """The new lines of a change, keyed by absolute, case-normalized path."""

    ref: str
    #: Path -> the 1-based line numbers added or changed in that file.
    lines: dict[str, set[int]] = field(default_factory=dict)
    #: Paths that are new as a whole (added or untracked).
    new_files: set[str] = field(default_factory=set)

    @staticmethod
    def key(path: str) -> str:
        return os.path.normcase(os.path.abspath(path))

    def contains(self, path: str, line: int | None) -> bool:
        """Whether *line* of *path* is new code (any line of a new file;
        no line only when the whole file is new)."""
        key = self.key(path)
        if key in self.new_files:
            return True
        if line is None:
            return False
        return line in self.lines.get(key, ())

    def changed_paths(self) -> list[str]:
        """Every file with at least one new line, relative to the cwd."""
        keys = self.new_files | {k for k, v in self.lines.items() if v}
        return sorted(os.path.relpath(k) for k in keys)


def _unquote(name: str) -> str:
    name = name.rstrip("\t")
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        # git C-quotes a name with control characters, quotes or backslashes.
        return (
            bytes(name[1:-1], "utf-8")
            .decode("unicode_escape")
            .encode("latin-1")
            .decode("utf-8", errors="replace")
        )
    return name


def parse_unified_diff(text: str, top: str) -> tuple[dict[str, set[int]], set[str]]:
    """``(lines, new_files)`` from ``git diff -U0`` output whose paths are
    relative to *top*. A pure deletion adds no line."""
    lines: dict[str, set[int]] = {}
    new_files: set[str] = set()
    current: str | None = None
    from_null = False
    for raw in text.splitlines():
        if raw.startswith("diff --git "):
            current, from_null = None, False
        elif raw.startswith("--- "):
            from_null = raw[4:].rstrip("\t") == "/dev/null"
        elif raw.startswith("+++ "):
            name = _unquote(raw[4:])
            if name == "/dev/null":  # a deletion: nothing to lint
                current = None
                continue
            if name.startswith("b/"):
                name = name[2:]
            current = NewCode.key(os.path.join(top, name))
            lines.setdefault(current, set())
            if from_null:
                new_files.add(current)
        elif current is not None:
            match = _HUNK_RE.match(raw)
            if match:
                start = int(match.group(1))
                count = int(match.group(2)) if match.group(2) is not None else 1
                lines[current].update(range(start, start + count))
    return lines, new_files


def new_code_since(ref: str) -> NewCode:
    """The lines added or changed since the merge base of *ref* and ``HEAD``
    (working tree and untracked files included).

    Raises:
        ChangedFilesError: not in a git work tree, or *ref* cannot be
            resolved (in CI usually a shallow clone).
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
    diff = _git(
        [
            "-c",
            "core.quotePath=false",
            "diff",
            "-U0",
            "-M",
            "--no-color",
            "--no-ext-diff",
            "--no-textconv",
            "--diff-filter=d",
            base,
            "--",
        ],
        cwd=top,
    )
    lines, new_files = parse_unified_diff(diff, top)
    for name in _git(
        ["ls-files", "--others", "--exclude-standard", "-z"], cwd=top
    ).split("\0"):
        if name:
            new_files.add(NewCode.key(os.path.join(top, name)))
    return NewCode(ref=ref, lines=lines, new_files=new_files)


def parse_scopes(items: Any) -> tuple[str, dict[str, str]]:
    """``(default, {selector: scope})`` from ``--scope`` values (``new``,
    ``all``, ``RULE=new``, ``RULE/KIND=all``) or the ``lint.scope``
    mapping (``{default: new, call-check: all}``) or string.

    Raises:
        ValueError: a value that is none of those, or names no rule.
    """
    from ..analysis.lint import ALL_RULES, PARSE_RULE

    default = "new"
    per_rule: dict[str, str] = {}
    if items is None:
        return default, per_rule
    if isinstance(items, str):
        items = [items]
    pairs: list[tuple[str | None, str]] = []
    if isinstance(items, dict):
        pairs = [
            (None if str(k) == "default" else str(k), str(v)) for k, v in items.items()
        ]
    else:
        for item in items:
            name, sep, value = str(item).partition("=")
            pairs.append((name, value) if sep else (None, name))
    for selector, value in pairs:
        if value not in SCOPES:
            raise ValueError(
                f"scope {value!r} for {selector or 'every rule'}: expected "
                f"{' or '.join(SCOPES)}"
            )
        if selector is None:
            default = value
            continue
        rule = selector.split("/", 1)[0].lower()
        if rule not in (*ALL_RULES, PARSE_RULE):
            raise ValueError(
                f"scope {selector}={value}: unknown rule {rule!r} "
                f"(recognized: {', '.join((*ALL_RULES, PARSE_RULE))})"
            )
        per_rule[selector] = value
    return default, per_rule


def scope_of(finding: Any, default: str, per_rule: dict[str, str]) -> str:
    """The scope *finding* is judged on: a ``rule/KIND`` entry wins over a
    bare ``rule`` entry, which wins over the default."""
    if finding.kind:
        specific = f"{finding.rule}/{finding.kind}".upper()
        for selector, value in per_rule.items():
            if selector.upper() == specific:
                return value
    for selector, value in per_rule.items():
        if "/" not in selector and selector.lower() == finding.rule:
            return value
    return default


def every_rule_new(default: str, per_rule: dict[str, str]) -> bool:
    """Whether no rule is judged on the whole codebase, so only the files
    a change touched need linting."""
    return default == "new" and all(v == "new" for v in per_rule.values())


def apply_new_code(
    report: Any,
    source_file: str,
    new_code: NewCode,
    default: str,
    per_rule: dict[str, str],
) -> Any:
    """Drop the findings of ``new``-scoped rules that are not on new code;
    the count lands in ``report.outside_new_code``."""
    kept = []
    dropped = 0
    for finding in report.findings:
        if scope_of(finding, default, per_rule) == "new":
            if finding.origin_file is not None and finding.origin_line is not None:
                path, line = finding.origin_file, finding.origin_line
            else:
                path = source_file
                line = finding.location.line if finding.location is not None else None
            if not new_code.contains(path, line):
                dropped += 1
                continue
        kept.append(finding)
    report.findings = kept
    report.outside_new_code = (report.outside_new_code or 0) + dropped
    return report
