"""
One-pass lint aggregation over the existing per-concern analyzers.

Every analyzer in this package answers one question well and returns its own
report shape -- ``DeadCodeReport.dead_items``, ``MoveTypeReport.violations``,
``ComplexityReport.procedures``, and so on. That is right for a caller who
wants *that* answer, and wrong for the two callers who want "tell me what is
wrong with this program": a CI gate and an editor. Both have to spawn one
process per analyzer today (each re-parsing the same file), then learn seven
different JSON shapes to render one list of problems.

:class:`LintAnalyzer` is that list. It runs a chosen set of rules over one
already-parsed AST and flattens every report into a single stream of
:class:`LintFinding` -- ``rule``, ``severity``, ``message``, ``location``,
``symbol`` -- ordered by source position. Nothing here re-implements any
analysis: each rule is a thin mapping from an existing analyzer's report onto
that shape, so a fix or an improvement in (say) ``move_type_checker.py``
reaches lint output with no change here.

Rule ids are deliberately the *CLI subcommand names* of the analyzers behind
them (``dead-code``, ``move-type-check``, ...) rather than a second private
vocabulary, so ``cobol-parser lint --rule dead-code`` and
``cobol-parser dead-code`` are visibly the same analyzer.

Two properties matter more than breadth here:

- **Severity is per finding, not per rule.** An analyzer that already grades
  its own findings (MOVE's ERROR/WARNING kinds, recursion's HIGH/MEDIUM,
  complexity's LOW/MODERATE/HIGH rating) keeps that grading; the rest carry
  a fixed severity chosen for the rule. ``_SEVERITY_*`` tables below are the
  whole of that policy.
- **A quiet report is not automatically a clean program.** Anything an
  analyzer could not check (MOVE operands whose data category never
  resolved, most often an unresolved COPY) is surfaced in
  :attr:`LintReport.caveats`, and a rule that raised is recorded in
  :attr:`LintReport.failed_rules` instead of taking the rest of the report
  down with it. A caller that gates on ``findings`` alone must still show
  those two lists, or it will report "no problems" for a file that was
  largely unexamined.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.program import CobolProgram
from .program_flow import ProgramFlowAnalyzer, ProgramFlowReport

# Severity vocabulary, most severe first. Ordering is meaningful: it backs
# --min-severity filtering and --fail-on gating in the CLI.
SEVERITIES: tuple[str, ...] = ("error", "warning", "info")

_SEVERITY_RANK: dict[str, int] = {name: rank for rank, name in enumerate(SEVERITIES)}

# Every rule this module can run, in the order findings from a program are
# reported when two land on the same line. The CLI exposes these verbatim as
# --rule values.
RULES: tuple[str, ...] = (
    "dead-code",
    "unused-variables",
    "move-type-check",
    "io-sequence",
    "linkage-check",
    "recursion-check",
    "complexity",
    "dclgen-check",
    "sql-cics-check",
)

#: Rule id of the fixed-format layout check (:func:`add_line_length_findings`).
#: It reads the files on disk rather than the AST, so it is not one of the
#: :class:`LintAnalyzer` rules above; the ``lint`` CLI and ``scan`` run it
#: next to them, and ``--rule`` selects it like any other.
LINE_LENGTH_RULE = "line-length"

#: Rules that check the source text itself rather than the parsed program.
SOURCE_RULES: tuple[str, ...] = (LINE_LENGTH_RULE,)

#: Every rule id a caller can select: the AST rules, then the source rules.
ALL_RULES: tuple[str, ...] = RULES + SOURCE_RULES

_RULE_ORDER: dict[str, int] = {name: order for order, name in enumerate(ALL_RULES)}

# I/O sequencing: every kind but one describes an operation that fails at
# run time (reading a file that was never opened, closing it twice). The
# exception -- a file still open when the program ends -- is a hygiene
# problem, not a failure, since the runtime closes it anyway.
_SEVERITY_IO: dict[str, str] = {
    "READ_BEFORE_OPEN": "error",
    "WRITE_BEFORE_OPEN": "error",
    "REWRITE_BEFORE_OPEN": "error",
    "DELETE_BEFORE_OPEN": "error",
    "START_BEFORE_OPEN": "error",
    "DOUBLE_OPEN": "error",
    "CLOSE_NOT_OPEN": "error",
    "DOUBLE_CLOSE": "error",
    "FILE_LEFT_OPEN": "warning",
    "READ_WRONG_MODE": "error",
    "START_WRONG_MODE": "error",
    "WRITE_WRONG_MODE": "error",
    "REWRITE_WRONG_MODE": "error",
    "DELETE_WRONG_MODE": "error",
    "OPEN_AFTER_LOCK": "error",
    # A warning, as settled in #736: the newest rule, and the only one
    # that depends on which statement ran last rather than on the mode.
    "REWRITE_WITHOUT_READ": "warning",
}

# LINKAGE: an argument-count mismatch or an unknown entry point is a wrong
# call that will misbehave at run time. A declared-but-unreferenced LINKAGE
# item is only ever suspicious -- a called program is entitled to ignore a
# parameter its caller passes.
_SEVERITY_LINKAGE: dict[str, str] = {
    "TOO_MANY_ARGS": "error",
    "TOO_FEW_ARGS": "error",
    "UNKNOWN_ENTRY": "error",
    "UNREFERENCED_LINKAGE": "warning",
    "PASSING_MODE_MISMATCH": "error",
}

# Recursion risk grades itself HIGH when the cycle it found has no escape
# route (an unconditional PERFORM/GO TO loop, or a program that CALLs
# itself) -- that is an infinite loop, not a smell. MEDIUM means an escape
# route exists and the loop terminates if the data ever satisfies it.
# LOW is a self-CALL in a program declared IS RECURSIVE: legal, only noted.
#
# MEDIUM is info, not warning: a loop with a way out is how COBOL without
# PERFORM UNTIL writes every loop (``GO TO DELAY-LOOP`` behind an IF), and
# whether the data ever takes the way out is not something the analyzer can
# know. On the NIST suite it was 3,600 warnings, a sixth of the whole report.
_SEVERITY_RECURSION: dict[str, str] = {
    "HIGH": "error",
    "MEDIUM": "info",
    "LOW": "info",
}

# Complexity is never an error: a 40-branch paragraph is hard to test, not
# wrong. HIGH (above the thresholds' `high` band) is worth a warning, and
# MODERATE is informational. LOW produces no finding at all.
_SEVERITY_COMPLEXITY: dict[str, str] = {"HIGH": "warning", "MODERATE": "info"}


@dataclass
class LintFinding:
    """One problem found in a program, by one rule.

    ``symbol`` is the program name the finding is *about* -- the paragraph,
    data item, file or called program -- not a source excerpt. It is what
    lets a consumer whose line numbers have shifted (an editor holding the
    unexpanded file while the analyzers ran over copybook-expanded text)
    re-anchor the finding by searching for the declaration instead of
    trusting :attr:`location` blindly.
    """

    rule: str
    severity: str
    message: str
    location: SourceLocation | None = None
    symbol: str | None = None
    # Where :attr:`location` really is, when the analyzed text was
    # copybook-expanded: the file on disk and the line in it. Set by
    # :func:`apply_source_map` from the expander's own per-line map, so a
    # consumer no longer has to guess by searching for :attr:`symbol`.
    # ``None`` means no expansion ran (``location`` is already on-disk truth)
    # or the map had nothing for that line.
    origin_file: str | None = None
    origin_line: int | None = None
    # The column in that file, when :func:`apply_source_map` was told how
    # far each file's columns sit from the analyzed text's (#301). A
    # fixed-format line is analyzed as columns 8-72 only, so its analyzer
    # column is 7 short of the column an editor shows. ``None`` means the
    # offset was not known, or the finding has no real column at all.
    origin_column: int | None = None
    # False when ``location.column`` is a placeholder (a parse error that
    # reported only a line): no column is then printed or mapped, rather
    # than a made-up one. Not serialized.
    column_known: bool = True
    # The underlying analyzer's own category for this finding, when it has
    # one (IOViolationKind.READ_BEFORE_OPEN, RecursionRisk.severity, ...).
    # Preserved so a consumer can filter more finely than by rule without
    # parsing `message`.
    kind: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
            "location": self.location.to_dict() if self.location else None,
            "symbol": self.symbol,
            "kind": self.kind,
        }
        # Emitted only when BOTH halves are known, so a consumer can tell
        # "this finding is on line 42 of THIS file" from "nobody mapped it"
        # -- rather than having to treat a defaulted echo of `location`, or a
        # half-filled `{"file": null, "line": 12}`, as an answer.
        if self.origin_file is not None and self.origin_line is not None:
            origin: dict[str, Any] = {
                "file": self.origin_file,
                "line": self.origin_line,
            }
            if self.origin_column is not None:
                origin["column"] = self.origin_column
            result["origin"] = origin
        return result


@dataclass
class LintReport:
    """Every finding from one lint run, plus what was and wasn't checked."""

    findings: list[LintFinding] = field(default_factory=list)
    # Rules that actually ran to completion, in RULES order.
    rules_run: list[str] = field(default_factory=list)
    # Rules that raised, as {"rule": ..., "error": ...}. A rule in here
    # contributed no findings; its concern is unexamined.
    failed_rules: list[dict[str, str]] = field(default_factory=list)
    # Human-readable limits on this run's coverage -- see the module
    # docstring. Empty means every rule that ran examined everything it
    # knows how to examine.
    caveats: list[str] = field(default_factory=list)
    # Findings an inline ``cobol-lint: disable`` comment silenced
    # (apply_suppressions), and findings already recorded in the baseline
    # file (apply_baseline). Counted, not listed: a reader should know the
    # report is quieter than the program, not wade through what was hidden.
    suppressed: int = 0
    baselined: int = 0

    @property
    def error_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "error")

    @property
    def warning_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "warning")

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "info")

    def counts_by_rule(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for finding in self.findings:
            counts[finding.rule] = counts.get(finding.rule, 0) + 1
        return counts

    def worst_severity(self) -> str | None:
        """The most severe severity present, or None for a clean report."""
        worst: str | None = None
        for finding in self.findings:
            if (
                worst is None
                or _SEVERITY_RANK[finding.severity] < _SEVERITY_RANK[worst]
            ):
                worst = finding.severity
        return worst

    def to_dict(self) -> dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "rules_run": list(self.rules_run),
            "failed_rules": list(self.failed_rules),
            "caveats": list(self.caveats),
            "summary": {
                "total": len(self.findings),
                "error": self.error_count,
                "warning": self.warning_count,
                "info": self.info_count,
                "by_rule": self.counts_by_rule(),
                "suppressed": self.suppressed,
                "baselined": self.baselined,
            },
        }


def _sort_key(finding: LintFinding) -> tuple[int, int, int, int, str]:
    """Order findings by source position, then by rule, then by message.

    Findings with no location sort *after* every located one (a program-level
    observation belongs at the end of a file-ordered listing, not at line 0
    pretending to be the first problem in the file). The rule and message
    tie-breakers keep the order total, so the same program always yields
    byte-identical output.
    """
    if finding.location is None:
        return (1, 0, 0, _RULE_ORDER.get(finding.rule, len(ALL_RULES)), finding.message)
    return (
        0,
        finding.location.line,
        finding.location.column,
        _RULE_ORDER.get(finding.rule, len(ALL_RULES)),
        finding.message,
    )


def _deduplicate(findings: list[LintFinding]) -> list[LintFinding]:
    """Drop findings identical to one already in the list.

    An analyzer can legitimately report the same problem twice -- the I/O
    sequence checker reaches one READ down two different paragraph paths and
    reports "READ before OPEN" once per path, for instance. Those are two
    facts about the control flow graph, but only one thing to fix, and every
    field a consumer can see (rule, severity, message, symbol, kind,
    location) is identical, so the second is indistinguishable noise here: an
    editor would stack two identical squiggles on one line and a CI log would
    print the line twice. Order-preserving, so the first occurrence keeps the
    position :func:`_sort_key` gave it.

    Deliberately not pushed down into the analyzers: each of them reports
    what its own analysis found, and collapsing that is this aggregate
    view's choice to make, not a change to what they mean.
    """
    seen: set[tuple[Any, ...]] = set()
    unique: list[LintFinding] = []
    for finding in findings:
        location = finding.location
        key = (
            finding.rule,
            finding.severity,
            finding.message,
            finding.symbol,
            finding.kind,
            (
                None
                if location is None
                else (location.line, location.column, location.length)
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(finding)
    return unique


# -- Severity overrides, inline suppressions, baseline ----------------------


def _rule_matches(selector: str, finding: LintFinding) -> bool:
    """Whether *selector* (``all``, ``rule`` or ``rule/KIND``) names *finding*."""
    if selector.lower() == "all":
        return True
    rule, _, kind = selector.partition("/")
    if rule.lower() != finding.rule:
        return False
    return not kind or kind.upper() == (finding.kind or "").upper()


def apply_severity_overrides(
    report: LintReport, overrides: dict[str, str] | None
) -> LintReport:
    """Re-grade findings by ``lint.severity``: a ``rule/KIND`` key wins over a
    bare ``rule`` key (``{recursion-check: warning,
    io-sequence/FILE_LEFT_OPEN: error}``)."""
    if not overrides:
        return report
    for finding in report.findings:
        specific = f"{finding.rule}/{finding.kind}" if finding.kind else None
        level = None
        if specific is not None:
            level = next(
                (v for k, v in overrides.items() if k.upper() == specific.upper()),
                None,
            )
        if level is None:
            level = overrides.get(finding.rule)
        if level is not None:
            if level not in _SEVERITY_RANK:
                raise ValueError(f"unknown severity: {level!r}")
            finding.severity = level
    return report


#: ``cobol-lint: disable=dead-code,unused-variables`` and its siblings. The
#: rule list is optional: without it the directive covers every rule.
_DIRECTIVE_RE = re.compile(
    r"cobol-lint:\s*(disable-next-line|disable-file|disable|enable)\b"
    r"(?:\s*=\s*([A-Za-z0-9_\-/]+(?:\s*,\s*[A-Za-z0-9_\-/]+)*))?",
    re.IGNORECASE,
)


def _is_comment_line(line: str) -> bool:
    """A whole-line comment: column 7 ``*`` or ``/`` in fixed format, or a
    line whose text starts with ``*>`` (or ``*``) in free format."""
    if len(line) > 6 and line[6] in "*/":
        return True
    return line.lstrip().startswith("*>")


def _directive_in_comment(line: str, start: int) -> bool:
    """Whether the directive found at *start* sits in a comment: a comment
    line, or after a ``*>`` that is not inside a literal."""
    if _is_comment_line(line):
        return True
    quote: str | None = None
    for position in range(min(start, len(line) - 1)):
        ch = line[position]
        if quote is not None:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "*" and line[position + 1] == ">":
            return True
    return False


@dataclass
class _FileDirectives:
    """The suppressions one file declares."""

    whole_file: set[str] = field(default_factory=set)
    lines: dict[int, set[str]] = field(default_factory=dict)
    #: ``(first, last, rules)``; *last* is ``None`` while still open.
    blocks: list[tuple[int, int | None, set[str]]] = field(default_factory=list)

    def covers(self, line: int | None, finding: LintFinding) -> bool:
        selectors = set(self.whole_file)
        if line is not None:
            selectors |= self.lines.get(line, set())
            for first, last, rules in self.blocks:
                if first <= line and (last is None or line <= last):
                    selectors |= rules
        return any(_rule_matches(sel, finding) for sel in selectors)


def _enable_closes(enabled: set[str], disabled: set[str]) -> bool:
    """Whether ``enable=<enabled>`` ends a ``disable=<disabled>`` block:
    ``all`` ends every block, a bare rule ends that rule's blocks (with or
    without a KIND), and ``rule/KIND`` ends only a block of exactly that."""
    wanted = {e.lower() for e in enabled}
    if "all" in wanted:
        return True
    for selector in (d.lower() for d in disabled):
        if selector in wanted or selector.partition("/")[0] in wanted:
            return True
    return False


def parse_suppressions(text: str) -> _FileDirectives:
    """Read every ``cobol-lint:`` directive in one file's text.

    * ``*> cobol-lint: disable=RULE`` after code silences that line;
    * on a comment line of its own, ``disable=RULE`` silences from there to
      the matching ``enable=RULE`` (or the end of the file);
    * ``disable-next-line=RULE`` silences the next line that is not a
      comment or blank;
    * ``disable-file=RULE`` silences the whole file.

    RULE is a rule id, ``rule/KIND`` (``unused-variables/FILE``), or a
    comma-separated list of them; leaving it out means every rule.
    """
    from .._lines import split_source_lines

    directives = _FileDirectives()
    lines = split_source_lines(text)
    pending_next: set[str] = set()
    for number, line in enumerate(lines, start=1):
        match = _DIRECTIVE_RE.search(line)
        comment_only = _is_comment_line(line) or not line.strip()
        if pending_next and not comment_only:
            directives.lines.setdefault(number, set()).update(pending_next)
            pending_next = set()
        if match is None or not _directive_in_comment(line, match.start()):
            continue
        action = match.group(1).lower()
        rules = {r.strip() for r in (match.group(2) or "all").split(",") if r.strip()}
        if action == "disable-file":
            directives.whole_file |= rules
        elif action == "disable-next-line":
            pending_next |= rules
        elif action == "disable":
            if _is_comment_line(line):
                directives.blocks.append((number, None, rules))
            else:
                directives.lines.setdefault(number, set()).update(rules)
        else:  # enable: close the open blocks it names
            for index, (first, last, block_rules) in enumerate(directives.blocks):
                if last is None and _enable_closes(rules, block_rules):
                    directives.blocks[index] = (first, number, block_rules)
    return directives


def apply_suppressions(
    report: LintReport,
    source_file: str,
    read_text: Callable[[str], str | None] | None = None,
) -> LintReport:
    """Drop findings an inline ``cobol-lint:`` comment silences.

    A finding is judged in the file it is reported in -- its ``origin`` when
    the program was copybook-expanded (so a directive inside a copybook
    silences that copybook's findings in every program), else
    *source_file* -- and on that file's line. A finding with no line can be
    silenced only by ``disable-file``. The count lands in
    ``report.suppressed``.
    """
    import os

    def default_read(path: str) -> str | None:
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError:
            return None

    read = read_text or default_read
    cache: dict[str, _FileDirectives | None] = {}

    def directives_for(path: str) -> _FileDirectives | None:
        key = os.path.normcase(os.path.abspath(path))
        if key not in cache:
            text = read(path)
            cache[key] = (
                parse_suppressions(text)
                if text is not None and "cobol-lint:" in text.lower()
                else None
            )
        return cache[key]

    kept: list[LintFinding] = []
    for finding in report.findings:
        line: int | None
        if finding.origin_file is not None and finding.origin_line is not None:
            path, line = finding.origin_file, finding.origin_line
        else:
            path = source_file
            line = finding.location.line if finding.location is not None else None
        directives = directives_for(path)
        if directives is not None and directives.covers(line, finding):
            report.suppressed += 1
            continue
        kept.append(finding)
    report.findings = kept
    return report


BASELINE_VERSION = 1

_DIGITS_RE = re.compile(r"\d+")


def baseline_fingerprint(
    finding: LintFinding, source_file: str, base: str
) -> tuple[str, str, str, str]:
    """What a baseline entry matches on: rule, kind, the file the finding is
    in (relative to *base*, posix), and its symbol -- or, for a finding with
    no symbol, its message with numbers blanked. Never the line: an edit
    above a known finding must not make it new."""
    import os

    path = finding.origin_file or source_file
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(base))
    except ValueError:  # another drive on Windows
        rel = os.path.abspath(path)
    anchor = finding.symbol or _DIGITS_RE.sub("#", finding.message)
    return (finding.rule, finding.kind or "", rel.replace(os.sep, "/"), anchor)


def baseline_document(
    reports: Iterable[tuple[str, LintReport]], base: str
) -> dict[str, Any]:
    """The baseline JSON for these per-file reports.

    A finding inside a copybook is reported by every program that COPYs it;
    each program is matched against the baseline on its own, so an entry's
    count is the most any one program reported, not their sum.
    """
    counts: dict[tuple[str, str, str, str], int] = {}
    for source_file, report in reports:
        mine: dict[tuple[str, str, str, str], int] = {}
        for finding in report.findings:
            key = baseline_fingerprint(finding, source_file, base)
            mine[key] = mine.get(key, 0) + 1
        for key, count in mine.items():
            counts[key] = max(counts.get(key, 0), count)
    return {
        "version": BASELINE_VERSION,
        "tool": "cobol-parser lint",
        "findings": [
            {"rule": r, "kind": k or None, "file": f, "anchor": a, "count": n}
            for (r, k, f, a), n in sorted(counts.items())
        ],
    }


def load_baseline(document: dict[str, Any]) -> dict[tuple[str, str, str, str], int]:
    """Counts by fingerprint from a :func:`baseline_document`."""
    if not isinstance(document, dict) or document.get("version") != BASELINE_VERSION:
        raise ValueError(
            f"not a cobol-parser lint baseline (expected version {BASELINE_VERSION})"
        )
    counts: dict[tuple[str, str, str, str], int] = {}
    for entry in document.get("findings") or []:
        key = (
            str(entry["rule"]),
            str(entry.get("kind") or ""),
            str(entry["file"]),
            str(entry["anchor"]),
        )
        counts[key] = counts.get(key, 0) + int(entry.get("count", 1))
    return counts


def apply_baseline(
    report: LintReport,
    source_file: str,
    baseline: dict[tuple[str, str, str, str], int],
    base: str,
) -> LintReport:
    """Drop the findings *baseline* already records, up to its count for
    each fingerprint; what is left is new. ``baseline`` is not modified."""
    budget = dict(baseline)
    kept: list[LintFinding] = []
    for finding in report.findings:
        key = baseline_fingerprint(finding, source_file, base)
        if budget.get(key, 0) > 0:
            budget[key] -= 1
            report.baselined += 1
            continue
        kept.append(finding)
    report.findings = kept
    return report


def filter_by_severity(
    findings: list[LintFinding], min_severity: str
) -> list[LintFinding]:
    """Keep only findings at or above *min_severity* (see :data:`SEVERITIES`)."""
    if min_severity not in _SEVERITY_RANK:
        raise ValueError(
            f"unknown severity: {min_severity!r} (expected one of {', '.join(SEVERITIES)})"
        )
    limit = _SEVERITY_RANK[min_severity]
    return [f for f in findings if _SEVERITY_RANK[f.severity] <= limit]


#: Rule id of the findings :func:`add_parse_errors` makes from parse errors.
#: Not in :data:`RULES`: it is not an analyzer that ``--rule`` can select or
#: drop, it is the parse every rule ran on.
PARSE_RULE = "parse"


def add_parse_errors(report: LintReport, errors: list[Any]) -> LintReport:
    """Turn each parse error into an error-severity ``parse`` finding.

    A file that parsed with errors still hands the analyzers a (partial)
    AST, and a partial AST is usually a quiet one: a file that is not COBOL
    at all used to lint as "0 finding(s)" and pass ``--fail-on info``
    (#249). As findings, the parse errors show up in the JSON and the text
    report, and ``--fail-on`` decides what they cost -- a file that mostly
    parses keeps its other findings usable instead of failing outright.

    *errors* is ``ParseResult.errors``. Each finding sits at the error's
    line and column when it has one (so :func:`apply_source_map`, run
    afterwards, maps it like any other finding); the findings are merged
    into the report in source order. Modified in place and returned.
    """
    added: list[LintFinding] = []
    for error in errors:
        line = getattr(error, "line_number", None)
        column = getattr(error, "column", None)
        location = (
            SourceLocation(line=line, column=column or 1)
            if isinstance(line, int) and line > 0
            else None
        )
        message = getattr(error, "message", None) or str(error)
        added.append(
            LintFinding(
                rule=PARSE_RULE,
                severity="error",
                message=message,
                location=location,
                # SourceLocation needs a column; 1 stands in for "none".
                column_known=bool(column),
                kind=getattr(error, "code", None) or type(error).__name__,
            )
        )
    if added:
        report.findings = _deduplicate(sorted(report.findings + added, key=_sort_key))
    return report


def apply_source_map(
    report: LintReport,
    source_map: dict[int, tuple[str, int]] | None,
    column_offset: Callable[[str, int], int | None] | None = None,
) -> LintReport:
    """Stamp every located finding with the file and line it really came from.

    Analyzer locations count lines in whatever text was parsed. When that text
    is the copybook-*expanded* source, a finding after an expanded ``COPY``
    sits well below the line the same code occupies in the file on disk, and
    a finding inside an inlined member does not belong to that file at all.
    ``source_map`` -- the expander's own per-line record, carried on
    ``ParseResult.expansion_source_map`` -- answers both exactly, replacing
    the search-for-the-symbol guesswork every consumer had to do instead.

    A ``None`` map leaves the report untouched. So does a line the map does
    not cover; the finding keeps ``origin_file``/``origin_line`` unset rather
    than claiming a line nobody vouched for.

    ``column_offset(file, line)`` says how many columns that line of that
    file sits to the right of the analyzed text (7 on a fixed-format line,
    whose columns 1-7 never reach the analyzers; see
    :func:`fixed_format_column_offset`), or ``None`` when it cannot say.
    With an answer, ``origin_column`` is stamped with the column an editor
    shows; without one it stays ``None``.

    The report is modified in place and returned, for chaining.
    """
    if not source_map:
        return report
    for finding in report.findings:
        if finding.location is None:
            continue
        origin = source_map.get(finding.location.line)
        if origin is None:
            continue
        finding.origin_file, finding.origin_line = origin
        if column_offset is not None and finding.column_known:
            offset = column_offset(*origin)
            if offset is not None:
                finding.origin_column = finding.location.column + offset
    return report


#: How far a fixed-format line's analyzer column sits left of its real one:
#: ``normalize_fixed_format`` hands the lexer columns 8-72, so column 8 on
#: disk is column 1 to every analyzer.
FIXED_FORMAT_COLUMN_OFFSET = 7


def fixed_format_column_offset(parsed_fixed: bool, file_fixed: bool) -> int:
    """Columns to add to an analyzer column to get *a file's* on-disk column.

    *parsed_fixed* is whether the text the analyzers ran over was normalized
    from fixed format (the program, or the expanded listing built from it);
    *file_fixed* is whether the file a line came from is itself fixed-format.

    * fixed listing, fixed file -- the line kept its columns, then lost 1-7
      to normalization: 7.
    * fixed listing, free-form copybook -- the expander re-padded the member
      by exactly the 7 columns normalization strips again: 0.
    * free-form listing, fixed-format copybook -- the expander cut the
      member's 6-column sequence area, keeping its indicator column: 6.
    * free-form throughout: 0.
    """
    if not file_fixed:
        return 0
    return FIXED_FORMAT_COLUMN_OFFSET if parsed_fixed else 6


def source_column_offsets(
    main_file: str, preprocess_fixed: bool | None = None
) -> Callable[[str, int], int | None]:
    """``(file, line) -> offset``: how far a line's on-disk column sits right
    of the analyzer's, for every file a parse of *main_file* read (#301).

    The ``column_offset`` argument :func:`apply_source_map` takes. Whether the
    parse normalized fixed format is decided the way ``CobolParser`` decides
    it (*preprocess_fixed* -- ``parse_cobol``'s own override -- first, else
    the detector); each copybook is judged the way the expander judged it
    when it spliced the member in. Within a fixed-format file, a line after
    ``>>SOURCE FORMAT FREE`` is free-form and is not shifted. A file that
    cannot be read again answers ``None``, so its findings keep no column
    rather than a guessed one.
    """
    from pathlib import Path

    from .._lines import split_source_lines
    from .._source_directive import free_format_flags
    from ..preprocess import strip_compiler_directives
    from ..preprocess.copybook_expander import _looks_fixed_format
    from ..preprocess.source_format import detect_fixed_format

    def read(path: str) -> str | None:
        # Decoded as the parse decoded it (#522): read as UTF-8, an EBCDIC
        # file has no line breaks and no fixed-format columns to find.
        from ..preprocess import PreprocessingError
        from ..preprocess.copybook_expander import read_program_source

        try:
            return read_program_source(path)
        except (OSError, PreprocessingError):
            return None

    def same_file(path: str) -> bool:
        try:
            return bool(Path(path).resolve() == Path(main_file).resolve())
        except OSError:
            return bool(path == main_file)

    main_source = read(main_file)
    if preprocess_fixed is not None:
        parsed_fixed = bool(preprocess_fixed)
    elif main_source is not None:
        parsed_fixed = detect_fixed_format(strip_compiler_directives(main_source))
    else:
        return lambda _file, _line: None

    # file -> (offset of a fixed-format line, per-line free-format flags)
    layouts: dict[str, tuple[int, list[bool]] | None] = {}

    def layout(path: str) -> tuple[int, list[bool]] | None:
        if path not in layouts:
            main = same_file(path)
            text = main_source if main else read(path)
            if text is None:
                layouts[path] = None
            else:
                file_fixed = parsed_fixed if main else _looks_fixed_format(text)
                offset = fixed_format_column_offset(parsed_fixed, file_fixed)
                flags = (
                    free_format_flags(split_source_lines(text)) if file_fixed else []
                )
                layouts[path] = (offset, flags)
        return layouts[path]

    def column_offset(path: str, line: int) -> int | None:
        known = layout(path)
        if known is None:
            return None
        offset, free_flags = known
        if 0 < line <= len(free_flags) and free_flags[line - 1]:
            return 0
        return offset

    return column_offset


def _comment_start(line: str, indicators: Iterable[str]) -> int | None:
    """0-based column where a fixed-format line's comment starts: 6 for a
    comment line (indicator column), the ``*>`` of an inline comment outside
    any literal, else ``None``."""
    if len(line) > 6 and line[6] in indicators:
        return 6
    quote: str | None = None
    for position in range(7, len(line) - 1):
        ch = line[position]
        if quote is not None:
            if ch == quote:
                quote = None
        elif ch in "'\"":
            quote = ch
        elif ch == "*" and line[position + 1] == ">":
            return position
    return None


def _id_shape(tail: str) -> str:
    """The shape of an identification-area tail: digits as ``9``, letters as
    ``A``, anything else as itself (``IX2094.2`` -> ``AA9999.9``)."""
    return "".join("9" if ch.isdigit() else "A" if ch.isalpha() else ch for ch in tail)


def _identification_shapes(lines: list[str]) -> set[str]:
    """Tail shapes this file demonstrably stamps into columns 73-80.

    Evidence is only a line no word can have been cut on: column 72 blank,
    something in 73-80, nothing past 80. A shape seen on at least
    ``MIN_ID_STAMP_EVIDENCE_LINES`` such lines is the file's convention (a
    per-member id, a change tag), so the same shape right after a non-blank
    column 72 is that stamp abutting the code, not the rest of a word. The
    file-level generalization of ``_has_identification_stamp_convention``
    to stamps that are not purely numeric.
    """
    from collections import Counter

    from ..preprocess._normalize import (
        IDENTIFICATION_END_COL,
        MIN_ID_STAMP_EVIDENCE_LINES,
        TEXT_END_COL,
    )

    counts: Counter[str] = Counter()
    for raw in lines:
        line = raw.rstrip("\r\n").expandtabs(8)
        width = len(line.rstrip())
        if width <= TEXT_END_COL or width > IDENTIFICATION_END_COL:
            continue
        if not line[TEXT_END_COL - 1].isspace():
            continue
        tail = line[TEXT_END_COL:].strip()
        if tail:
            counts[_id_shape(tail)] += 1
    return {shape for shape, n in counts.items() if n >= MIN_ID_STAMP_EVIDENCE_LINES}


def line_length_findings(
    path: str, text: str, free_lines: list[bool] | None = None
) -> list[LintFinding]:
    """The ``line-length`` findings of one fixed-format file, on its own lines.

    Two problems, both silent to the compiler and to the parse:

    * **Past column 80** (error, ``kind`` ``LINE_PAST_COLUMN_80``): a
      fixed-format record is 80 columns. Anything after column 80 is lost
      when the member goes to a mainframe library (an RECFM=FB LRECL=80
      dataset), and was never program text anyway. A line whose text past
      column 72 is all comment (a comment line, or an inline ``*>`` comment)
      is a warning instead: the transfer truncates it all the same, but
      nothing the compiler reads is lost.
    * **Text cut at column 72** (warning, ``kind`` ``TEXT_PAST_COLUMN_72``):
      columns 73-80 are the identification area, which the compiler ignores.
      When a word runs across the 72/73 boundary, the part in 73+ is dropped
      without a message and the word that remains is a different word (a
      data name, a literal, a verb). Judged exactly as
      ``normalize_fixed_format`` judges it for its own warning: a numeric
      identification stamp (the full 73-80 field, or a shorter one when the
      file shows that convention) and a lone terminating period are not
      flagged, and neither is a comment line or a cut inside an inline
      ``*>`` comment. Neither is a tail with the
      shape of the file's own identification stamps (NIST's ``IX2094.2``,
      see :func:`_identification_shapes`).

    *free_lines* flags the lines after a ``>>SOURCE FORMAT FREE`` (see
    :func:`~cobolparser._source_directive.free_format_flags`); those have no
    column limit here. Every finding carries its on-disk file, line and
    column in both ``location`` and ``origin``, so no source map is needed.
    """
    from .._lines import split_source_lines
    from ..preprocess._normalize import (
        ALL_COMMENT_INDICATORS,
        IDENTIFICATION_END_COL,
        TEXT_END_COL,
        _has_identification_stamp_convention,
        _is_numeric_id_stamp_text,
    )

    lines = split_source_lines(text)
    stamps: bool | None = None
    shapes: set[str] | None = None
    findings: list[LintFinding] = []

    def found(
        line_no: int, column: int, severity: str, kind: str, message: str
    ) -> None:
        findings.append(
            LintFinding(
                rule=LINE_LENGTH_RULE,
                severity=severity,
                message=message,
                location=SourceLocation(line=line_no, column=column),
                kind=kind,
                origin_file=path,
                origin_line=line_no,
                origin_column=column,
            )
        )

    for index, raw in enumerate(lines):
        if free_lines is not None and index < len(free_lines) and free_lines[index]:
            continue
        line = raw.rstrip("\r\n").expandtabs(8)
        width = len(line.rstrip())
        if width <= TEXT_END_COL:
            continue
        line_no = index + 1
        comment_at = _comment_start(line, ALL_COMMENT_INDICATORS)
        if width > IDENTIFICATION_END_COL:
            # Past column 80 only inside a comment loses nothing the
            # compiler reads: still worth fixing, never worth failing a build.
            in_comment = comment_at is not None and comment_at < IDENTIFICATION_END_COL
            found(
                line_no,
                IDENTIFICATION_END_COL + 1,
                "warning" if in_comment else "error",
                "LINE_PAST_COLUMN_80",
                f"line is {width} columns long; a fixed-format record ends at "
                f"column {IDENTIFICATION_END_COL}, so columns "
                f"{IDENTIFICATION_END_COL + 1}-{width} are lost"
                + (" (comment text only)" if in_comment else ""),
            )
        if comment_at is not None and comment_at < TEXT_END_COL:
            continue
        before, after = line[TEXT_END_COL - 1], line[TEXT_END_COL]
        if before.isspace() or after.isspace():
            continue
        dropped = line[TEXT_END_COL:IDENTIFICATION_END_COL].rstrip()
        if dropped == ".":
            continue
        if _is_numeric_id_stamp_text(dropped):
            if width == IDENTIFICATION_END_COL:
                continue
            if stamps is None:
                stamps = _has_identification_stamp_convention(lines)
            if stamps and width <= IDENTIFICATION_END_COL:
                continue
        if shapes is None:
            shapes = _identification_shapes(lines)
        if _id_shape(dropped.strip()) in shapes:
            # The file's own identification-area convention (NIST's
            # ``IX2094.2``): the stamp abuts column 72, nothing is cut.
            continue
        found(
            line_no,
            TEXT_END_COL + 1,
            "warning",
            "TEXT_PAST_COLUMN_72",
            f"text runs past column {TEXT_END_COL}: {dropped!r} is in the "
            "identification area (columns 73-80), which the compiler ignores, "
            "so the word it ends is cut short",
        )
    return findings


def add_line_length_findings(
    report: LintReport,
    main_file: str,
    source_map: dict[int, tuple[str, int]] | None = None,
    preprocess_fixed: bool | None = None,
    copybooks: Iterable[str] = (),
) -> LintReport:
    """Run the ``line-length`` rule over *main_file* and every copybook its
    parse read, and merge the findings into *report*.

    Run it AFTER :func:`apply_source_map`: these findings are placed on disk
    already, and the map would re-place them by their line number. Each file
    is judged fixed or free the way the parse judged it (the program by
    *preprocess_fixed*, else the detector; a copybook as the expander did); a
    free-format file has no column limit and is skipped. A finding inside a
    copybook names the copybook. Its ``location`` is the expanded-text line
    that copybook line became, when *source_map* has one, so the report keeps
    sorting by the listing; otherwise the on-disk line (``origin`` is always
    the on-disk place, and what text and SARIF output print).

    *copybooks* adds members the map does not show (one that only COPYs
    another adds no line of its own). A file that cannot be read again is
    skipped. Modified in place and returned.
    """
    from pathlib import Path

    from .._lines import split_source_lines
    from .._source_directive import free_format_flags
    from ..preprocess import PreprocessingError, strip_compiler_directives
    from ..preprocess.copybook_expander import (
        _looks_fixed_format,
        read_program_source,
    )
    from ..preprocess.source_format import detect_fixed_format

    def key(path: str) -> str:
        try:
            return str(Path(path).resolve())
        except OSError:
            return path

    files: dict[str, str] = {key(main_file): main_file}
    for name, _ in (source_map or {}).values():
        files.setdefault(key(name), name)
    for name in copybooks:
        files.setdefault(key(name), name)
    # (file, line) -> the first expanded line it became.
    listing: dict[tuple[str, int], int] = {}
    for expanded, (name, line) in sorted((source_map or {}).items()):
        listing.setdefault((key(name), line), expanded)

    main_key = key(main_file)
    added: list[LintFinding] = []
    for file_key, name in files.items():
        try:
            text = read_program_source(name)
        except (OSError, PreprocessingError):
            continue
        if file_key == main_key:
            fixed = (
                bool(preprocess_fixed)
                if preprocess_fixed is not None
                else detect_fixed_format(strip_compiler_directives(text))
            )
        else:
            fixed = _looks_fixed_format(text)
        if not fixed:
            continue
        flags = free_format_flags(split_source_lines(text))
        for finding in line_length_findings(name, text, flags):
            assert finding.location is not None and finding.origin_line is not None
            listing_line = listing.get((file_key, finding.origin_line))
            if listing_line is not None:
                finding.location = SourceLocation(
                    line=listing_line, column=finding.location.column
                )
            added.append(finding)

    if LINE_LENGTH_RULE not in report.rules_run:
        report.rules_run.append(LINE_LENGTH_RULE)
    if added:
        report.findings = _deduplicate(sorted(report.findings + added, key=_sort_key))
    return report


#: The location-shaped keys :func:`stamp_report_origins` stamps, each with
#: the sibling key its origin goes under. A ``"location"`` keeps the plain
#: ``"origin"`` every consumer already reads; the rest name their own, since
#: one dict can carry more than one of them.
_ORIGIN_KEYS: dict[str, str] = {
    "location": "origin",
    "definition": "definition_origin",
    "exit_statement_location": "exit_statement_origin",
}


def stamp_report_origins(
    report: Any, source_map: dict[int, tuple[str, int]] | None
) -> Any:
    """The dict-shaped twin of :func:`apply_source_map`, for a serialized
    analyzer report (``report.to_dict()``) rather than a :class:`LintReport`.

    Every ``"location": {"line": N, ...}`` mapping anywhere in *report* gains
    a sibling ``"origin": {"file", "line"}`` from *source_map*, under the same
    rules: nothing is added for a ``None`` map or a line the map does not
    cover. The other location-shaped keys in :data:`_ORIGIN_KEYS` -- xref's
    ``definition``, program-flow's ``exit_statement_location`` -- gain a
    sibling of their own name (``definition_origin``, ...) the same way
    (#367). The location itself is left alone, so a consumer that indexes
    the expanded listing still can. Modified in place and returned.
    """
    if not source_map:
        return report
    if isinstance(report, dict):
        for key, origin_key in _ORIGIN_KEYS.items():
            location = report.get(key)
            # An origin already there was stamped with more than this map
            # knows (a lint finding's ``origin.column``, #301); keep it.
            if (
                origin_key not in report
                and isinstance(location, dict)
                and isinstance(location.get("line"), int)
            ):
                origin = source_map.get(location["line"])
                if origin is not None:
                    report[origin_key] = {"file": origin[0], "line": origin[1]}
        for value in list(report.values()):
            stamp_report_origins(value, source_map)
    elif isinstance(report, list):
        for value in report:
            stamp_report_origins(value, source_map)
    return report


def _procedure_nodes(ast: CobolProgram) -> dict[str, Any]:
    """Every paragraph and section of *ast*, by its procedure key (the bare
    name, or ``"<para> OF <section>"`` for a shared name)."""
    from ._procedures import ProcedureIndex

    if ast.procedure_division is None:
        return {}
    index = ProcedureIndex.build(ast.procedure_division)
    return {entry.key: entry.node for entry in index.entries}


def _is_exit_only(node: Any) -> bool:
    """Whether a paragraph holds nothing but a bare ``EXIT`` (or nothing)."""
    from ..models.statements.misc import ExitStatement

    statements = list(getattr(node, "statements", None) or [])
    if getattr(node, "paragraphs", None):  # a section: never "only EXIT"
        return False
    return all(
        isinstance(stmt, ExitStatement) and stmt.exit_type in (None, "PARAGRAPH")
        for stmt in statements
    )


class LintAnalyzer:
    """Runs several analyzers over one AST and flattens them into findings.

    Args:
        rules: The rule ids to run, defaulting to all of :data:`RULES`. An
            unknown id raises ``ValueError`` rather than being ignored --
            a typo'd ``--rule`` must not read as "that rule found nothing".

    Example:
        >>> report = LintAnalyzer().analyze(ast)              # doctest: +SKIP
        >>> [f.rule for f in report.findings]                 # doctest: +SKIP
        ['move-type-check', 'dead-code']
    """

    def __init__(self, rules: list[str] | tuple[str, ...] | None = None) -> None:
        selected = tuple(RULES) if rules is None else tuple(rules)
        unknown = [r for r in selected if r not in _RULE_ORDER]
        if unknown:
            raise ValueError(
                f"unknown lint rule(s): {', '.join(sorted(unknown))} "
                f"(expected one of {', '.join(ALL_RULES)})"
            )
        # A source rule (line-length) is accepted so a caller can pass one
        # selection list everywhere, but it is not run here: it reads files
        # on disk, which an AST does not carry. See add_line_length_findings.
        # Deduplicated and put back into RULES order, so `--rule complexity
        # --rule dead-code` and the reverse produce the same report.
        self._rules = tuple(r for r in RULES if r in set(selected))
        self._flow_cache: tuple[CobolProgram, ProgramFlowReport] | None = None

    @property
    def rules(self) -> tuple[str, ...]:
        return self._rules

    def analyze(
        self,
        ast: CobolProgram,
        *,
        flow_report: ProgramFlowReport | None = None,
        copybook_item_names: set[str] | None = None,
    ) -> LintReport:
        """Run the selected rules over *ast* and return one merged report.

        Args:
            ast: The parsed COBOL program AST.
            flow_report: An already-computed :class:`ProgramFlowReport` to
                reuse. Two rules (``recursion-check``, ``complexity``) need
                the control flow graph; without this they would each build
                their own, walking the same AST twice.
            copybook_item_names: Upper-cased names of data items that
                reached *ast* through an expanded COPY, when the caller
                knows them (the ``lint`` CLI works them out by diffing an
                unexpanded parse). ``unused-variables`` grades a finding on
                one of these as info rather than warning. Omitting it means
                "not known", which grades every unused item as the program's
                own -- never the reverse, so a missing set can only
                over-report, not hide anything.

        A source file with several ``PROGRAM-ID``s parses into one outer
        program carrying the rest as ``contained_programs``; every rule here
        is program-scoped, so each unit is linted on its own and the findings
        are merged. Linting only the outermost unit -- what this did before --
        left a contained program entirely unexamined while reporting a clean
        file.

        Returns:
            A :class:`LintReport`. A rule that raises is recorded in
            ``failed_rules`` and costs only its own findings -- the point of
            a lint pass is to report as much as it can, and one analyzer
            tripping over an exotic program should not blank the other six.
        """
        report = LintReport()
        units = ast.program_units()
        entry_interfaces: dict[str, list[str]] | None = None
        entry_parameter_modes: dict[str, dict[str, str]] | None = None
        if "linkage-check" in self._rules:
            from .linkage_checker import LinkageChecker

            # Scope-wide (every unit's ENTRY / PROCEDURE DIVISION USING),
            # computed once and handed to every unit's own linkage-check
            # collector below -- otherwise each of the file's N units would
            # redo this same whole-scope walk, an O(N^2) cost in program
            # units for no correctness benefit (LinkageChecker.check()'s own
            # collection loop, run N times over the same N units).
            entry_interfaces, entry_parameter_modes = (
                LinkageChecker.collect_scope_interfaces(ast)
            )
        for index, unit in enumerate(units):
            # A caller-supplied flow report describes the outermost unit only;
            # the others build their own.
            self._analyze_unit(
                unit,
                report,
                root=ast,
                flow_report=flow_report if index == 0 else None,
                copybook_item_names=copybook_item_names,
                entry_interfaces=entry_interfaces,
                entry_parameter_modes=entry_parameter_modes,
            )

        report.findings.sort(key=_sort_key)
        report.findings = _deduplicate(report.findings)
        # Two units that hit the same limit ("a COPY could not be resolved")
        # produce the same caveat text twice; say it once.
        report.caveats = list(dict.fromkeys(report.caveats))
        return report

    def _analyze_unit(
        self,
        ast: CobolProgram,
        report: LintReport,
        *,
        root: CobolProgram,
        flow_report: ProgramFlowReport | None,
        copybook_item_names: set[str] | None,
        entry_interfaces: dict[str, list[str]] | None = None,
        entry_parameter_modes: dict[str, dict[str, str]] | None = None,
    ) -> None:
        """Run every selected rule over one program unit, into *report*.

        *root* is the outermost program of the file, for the one rule
        (``linkage-check``) whose findings are per unit but whose knowledge
        -- which entry declares which parameters, and in what passing mode
        -- spans the file. *entry_interfaces*/*entry_parameter_modes* are
        that same rule's precomputed ``LinkageChecker.collect_entry_interfaces
        (root)``/``collect_entry_parameter_modes(root)``, when the caller
        (``analyze()``) already built them for every unit to share.
        """
        collectors: dict[str, Callable[[], list[LintFinding]]] = {
            "dead-code": lambda: self._dead_code(ast),
            "unused-variables": lambda: self._unused_variables(
                ast, copybook_item_names
            ),
            "move-type-check": lambda: self._move_type_check(ast, report),
            "io-sequence": lambda: self._io_sequence(ast),
            "linkage-check": lambda: self._linkage_check(
                ast, root, entry_interfaces, entry_parameter_modes
            ),
            "recursion-check": lambda: self._recursion_check(
                ast, self._flow(ast, flow_report)
            ),
            "complexity": lambda: self._complexity(ast, self._flow(ast, flow_report)),
            "dclgen-check": lambda: self._dclgen_check(ast, report),
            "sql-cics-check": lambda: self._sql_cics(ast, report),
        }

        for rule in self._rules:
            try:
                report.findings.extend(collectors[rule]())
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                # One entry per rule however many units it failed on: the
                # reader needs to know the concern went unexamined, not how
                # many times the same exception was raised.
                if not any(f["rule"] == rule for f in report.failed_rules):
                    report.failed_rules.append(
                        {"rule": rule, "error": f"{type(exc).__name__}: {exc}"}
                    )
                continue
            if rule not in report.rules_run:
                report.rules_run.append(rule)

    # -- Shared control flow graph --------------------------------------------

    def _flow(
        self, ast: CobolProgram, provided: ProgramFlowReport | None
    ) -> ProgramFlowReport:
        """The CFG the flow-dependent rules share, built at most once.

        Cached on the instance for the duration of one analyze() call rather
        than passed around, so adding a third flow-dependent rule does not
        mean threading another argument through every collector.
        """
        if provided is not None:
            return provided
        cached = self._flow_cache
        if cached is None or cached[0] is not ast:
            cached = (ast, ProgramFlowAnalyzer().analyze(ast))
            self._flow_cache = cached
        return cached[1]

    # -- Per-rule collectors ---------------------------------------------------

    def _dead_code(self, ast: CobolProgram) -> list[LintFinding]:
        from .dead_code import DeadCodeAnalyzer

        report = DeadCodeAnalyzer().analyze(ast)
        procedures = _procedure_nodes(ast)
        findings: list[LintFinding] = []
        for item in report.dead_items:
            node = procedures.get(item.qualified_name or item.name)
            # An unreachable `0000-MAIN-EXIT. EXIT.` after a CICS RETURN is
            # a convention, not dead logic: there is nothing in it to delete
            # but the label. Seen, as info, rather than a warning to fix.
            exit_only = node is not None and _is_exit_only(node)
            findings.append(
                LintFinding(
                    rule="dead-code",
                    severity="info" if exit_only else "warning",
                    message=(
                        f"{item.procedure_type.lower()} {item.name} can never be reached"
                        + (" (it holds only EXIT)" if exit_only else "")
                    ),
                    location=item.location,
                    symbol=item.name,
                    kind=item.procedure_type,
                )
            )
        return findings

    def _unused_variables(
        self, ast: CobolProgram, copybook_item_names: set[str] | None
    ) -> list[LintFinding]:
        from .unused_variables import UnusedVariableAnalyzer

        result = UnusedVariableAnalyzer().analyze(
            ast, copybook_item_names=copybook_item_names
        )
        findings: list[LintFinding] = []
        for item in result.unused_items:
            message = (
                f"{item.section} item {item.name} (level {item.level:02d}) "
                "is never referenced in the PROCEDURE DIVISION"
            )
            if item.used_group:
                message = (
                    f"{item.section} item {item.name} (level {item.level:02d}) "
                    f"is never referenced by name; its group {item.used_group} "
                    "is used as a whole"
                )
            findings.append(
                LintFinding(
                    rule="unused-variables",
                    # An unused item the program declares itself is dead
                    # weight its author can delete. Three kinds are info:
                    # one that arrived through a COPY (a copybook describes
                    # a whole record and no single program uses every field
                    # of it), a FILE record field (likewise the layout of a
                    # record the program reads or writes whole, often INTO
                    # or FROM working storage), and a field of a group the
                    # code names (`IF ACCTFILE-STATUS = '00'`): its bytes
                    # are used, only its own name is not.
                    severity=(
                        "info"
                        if item.from_copybook
                        or item.used_group
                        or item.section == "FILE"
                        else "warning"
                    ),
                    message=message,
                    location=item.location,
                    symbol=item.name,
                    kind=item.section,
                )
            )
        return findings

    def _move_type_check(
        self, ast: CobolProgram, report: LintReport
    ) -> list[LintFinding]:
        from .move_type_checker import MoveTypeChecker

        result = MoveTypeChecker().check(ast)
        unresolved_operands = result.unresolved_count - result.unresolved_function_count
        if unresolved_operands:
            report.caveats.append(
                f"move-type-check skipped {unresolved_operands} MOVE operand(s) whose data "
                "category could not be resolved (most often an unresolved COPY) -- pass "
                "--copybook-path so they can be checked"
            )
        if result.unresolved_function_count:
            # No copybook can resolve these, so the --copybook-path hint
            # above would send the user after a COPY that is not missing.
            report.caveats.append(
                f"move-type-check skipped {result.unresolved_function_count} MOVE "
                "operand(s) whose source is an intrinsic FUNCTION it cannot check "
                "(a NATIONAL result, an uncatalogued function, or a numeric result "
                "that may not be an integer moved to an alphanumeric item)"
            )
        return [
            LintFinding(
                rule="move-type-check",
                severity="error" if v.kind.name == "ERROR" else "warning",
                message=v.message,
                location=v.location,
                symbol=v.source_name,
                kind=v.kind.name,
            )
            for v in result.violations
        ]

    def _io_sequence(self, ast: CobolProgram) -> list[LintFinding]:
        from .io_sequence import IOSequenceAnalyzer

        result = IOSequenceAnalyzer().analyze(ast)
        return [
            LintFinding(
                rule="io-sequence",
                severity=_SEVERITY_IO.get(v.kind.name, "warning"),
                message=v.message,
                location=v.location,
                symbol=v.file_name,
                kind=v.kind.name,
            )
            for v in result.violations
        ]

    def _linkage_check(
        self,
        ast: CobolProgram,
        root: CobolProgram,
        entry_interfaces: dict[str, list[str]] | None = None,
        entry_parameter_modes: dict[str, dict[str, str]] | None = None,
    ) -> list[LintFinding]:
        from .linkage_checker import LinkageChecker

        # This unit only: analyze() already visits every unit, and letting
        # the checker recurse too would report a contained program's items
        # twice -- or, for two units declaring a same-named item, once with
        # no location, which _deduplicate then folds into one finding.
        #
        # entry_interfaces/entry_parameter_modes, when the caller
        # (analyze()) already built them for `root`, are passed straight
        # through instead of interface_scope -- letting LinkageChecker.
        # check() skip its own scope-wide collection pass, which would
        # otherwise re-walk every unit of `root` again for each of this
        # file's units.
        result = LinkageChecker(include_contained_programs=False).check(
            ast,
            interface_scope=root,
            entry_interfaces=entry_interfaces,
            entry_parameter_modes=entry_parameter_modes,
        )
        return [
            LintFinding(
                rule="linkage-check",
                severity=_SEVERITY_LINKAGE.get(v.kind.name, "warning"),
                message=v.message,
                location=v.location,
                symbol=v.call_target or v.item_name,
                kind=v.kind.name,
            )
            for v in result.violations
        ]

    def _recursion_check(
        self, ast: CobolProgram, flow_report: ProgramFlowReport
    ) -> list[LintFinding]:
        from .recursion_risk import RecursionRiskAnalyzer

        result = RecursionRiskAnalyzer().analyze(ast, flow_report=flow_report)
        procedures = _procedure_nodes(ast)
        findings: list[LintFinding] = []
        for risk in result.risks:
            # A risk describes a cycle, not a point -- RecursionRisk carries
            # no location of its own. The cycle's first procedure (or the
            # self-called program) is what a reader needs to find it, and is
            # enough for a consumer to re-anchor by name.
            symbol = (
                risk.program
                if risk.mechanism == "CALL"
                else (risk.procedures[0] if risk.procedures else None)
            )
            # Anchored on that procedure's header, so the finding has a line
            # a GitHub annotation, a SARIF result and an inline suppression
            # can point at (a CALL cycle on the PROGRAM-ID's unit is left
            # without one: the self-CALL itself is not tracked here).
            node = (
                procedures.get(risk.procedures[0])
                if risk.mechanism != "CALL" and risk.procedures
                else None
            )
            findings.append(
                LintFinding(
                    rule="recursion-check",
                    severity=_SEVERITY_RECURSION.get(risk.severity, "warning"),
                    message=risk.explanation,
                    location=node.location if node is not None else None,
                    symbol=symbol,
                    kind=risk.mechanism,
                )
            )
        return findings

    def _complexity(
        self, ast: CobolProgram, flow_report: ProgramFlowReport
    ) -> list[LintFinding]:
        from .complexity import ComplexityAnalyzer

        result = ComplexityAnalyzer().analyze(ast, flow_report=flow_report)
        findings: list[LintFinding] = []
        for proc in result.procedures:
            severity = _SEVERITY_COMPLEXITY.get(proc.rating)
            if severity is None:  # LOW -- nothing to say
                continue
            findings.append(
                LintFinding(
                    rule="complexity",
                    severity=severity,
                    message=(
                        f"{proc.procedure_type.lower()} {proc.name} has cyclomatic complexity "
                        f"{proc.cyclomatic_complexity} ({proc.rating}), nesting depth "
                        f"{proc.max_nesting_depth}, {proc.statement_count} statement(s)"
                    ),
                    location=proc.location,
                    symbol=proc.name,
                    kind=proc.rating,
                )
            )
        return findings

    def _dclgen_check(self, ast: CobolProgram, report: LintReport) -> list[LintFinding]:
        from .dclgen_check import DclgenChecker

        result = DclgenChecker().check(ast)
        # A host variable no DECLARE TABLE speaks for is not a clean one: the
        # DCLGEN block may simply not have been COPY'd into this compile.
        # Said once, with a count, rather than as a finding per variable.
        if result.unchecked:
            report.caveats.append(
                f"dclgen-check: {len(result.unchecked)} host variable(s) could "
                "not be (fully) checked against a DECLARE TABLE column -- run "
                "`cobol-parser dclgen-check` for the reason per variable"
            )
        for column, tables in sorted(result.ambiguous_columns.items()):
            report.caveats.append(
                f"dclgen-check: column {column} is declared by "
                f"{', '.join(sorted(tables))}; host variables of that name "
                "were checked against the first"
            )
        return [
            LintFinding(
                rule="dclgen-check",
                severity=violation.severity,
                message=violation.message,
                location=violation.location,
                symbol=violation.host_variable,
                kind=violation.kind,
            )
            for violation in result.violations
        ]

    def _sql_cics(self, ast: CobolProgram, report: LintReport) -> list[LintFinding]:
        from .sql_cics_lint import SqlCicsAnalyzer

        result = SqlCicsAnalyzer().analyze(ast)
        # An EXEC block whose handler state or host-variable origin could not
        # be established is not a clean one -- it is an unexamined one. Said
        # once with a count, like dclgen-check above, rather than as a finding
        # per block, since "could not check" is not a defect in the program.
        if ast.procedure_division is None and result.unchecked:
            # Nothing was examined at all -- say so, rather than counting the
            # unit's one reason as an "EXEC block" a file may not even have
            # (a file that did not parse lints with no PROCEDURE DIVISION, #249).
            report.caveats.append(f"sql-cics-check: {result.unchecked[0]}")
        elif result.unchecked:
            report.caveats.append(
                f"sql-cics-check: {len(result.unchecked)} EXEC block(s) or host "
                "variable(s) could not be checked -- run "
                "`cobol-parser sql-cics-check` for the reason per item"
            )
        return [
            LintFinding(
                rule="sql-cics-check",
                severity=violation.severity,
                message=violation.message,
                location=violation.location,
                symbol=violation.symbol,
                kind=violation.kind,
            )
            for violation in result.violations
        ]
