"""The lint subcommand.

One file or many (``--glob``, ``--changed-since``, ``--new-code-since``),
baselines, severity policy, and the text / GitHub / SARIF / summary
outputs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from typing import Any

from .._common import (
    _DEFAULT_PROFILE_TOP_N,
    _add_compact_arg,
    _add_copybook_args,
    _add_define_args,
    _add_dialect_arg,
    _add_encoding_arg,
    _add_error_recovery_arg,
    _add_output_arg,
    _add_profiling_args,
    _add_program_arg,
    _add_source_format_args,
    _collect_scan_files,
    _emit_report,
    _fail,
    _identification,
    _json_out,
    _parse_result_or_fail,
    _profiling_requested,
    _severity_at_least,
    _source_format_kwargs,
    _text_out,
)

# -- Subcommand: lint ---------------------------------------------------------


def _build_lint_parser(subparsers: argparse._SubParsersAction) -> None:
    from ...analysis.lint import ALL_RULES, SEVERITIES

    p = subparsers.add_parser(
        "lint",
        help="Run several analyzers in one pass and report every finding as one list",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser lint program.cbl\n"
            "  cobol-parser lint program.cbl --format text --min-severity warning\n"
            "  cobol-parser lint program.cbl --rule dead-code --rule move-type-check\n"
            "  cobol-parser lint program.cbl --copybook-path ./copybooks --fail-on error\n"
            "  cobol-parser lint src/*.cbl --format text --fail-on error\n"
            "  cobol-parser lint --glob 'src/**/*.cbl' --format sarif -o lint.sarif\n"
            "  cobol-parser lint --changed-since origin/main --format github "
            "--fail-on error\n"
            "  cobol-parser lint --new-code-since origin/main --format github "
            "--fail-on warning\n"
            "  cobol-parser lint --new-code-since origin/main --scope "
            "call-check=all --fail-on error\n"
            "  cobol-parser lint --glob 'src/**/*.cbl' --write-baseline "
            "lint-baseline.json\n"
            "  cobol-parser lint --glob 'src/**/*.cbl' --baseline "
            "lint-baseline.json --fail-on warning\n"
            "\nSilence one finding in the source with a comment:\n"
            "  *> cobol-lint: disable=RULE              (this line, after code)\n"
            "  *> cobol-lint: disable-next-line=RULE    (the next code line)\n"
            "  *> cobol-lint: disable=RULE ... enable=RULE   (a block)\n"
            "  *> cobol-lint: disable-file=RULE         (the whole file)\n"
            "RULE is a rule id, rule/KIND, a comma-separated list, or left out\n"
            "for every rule. In fixed format the comment can be a '*' line.\n"
            "  cobol-parser lint src/PAYMAIN.cbl --callee-path src/ --rule call-check\n"
            "\nNew code (like a Sonar quality gate): --new-code-since REF keeps only\n"
            "the findings on lines added or edited since REF. --scope RULE=all\n"
            "judges one rule on the whole codebase instead (--scope all: every\n"
            "rule; lint.scope in cobol.yml).\n"
            "\nMore than one file, --glob, --files-from, --changed-since or\n"
            "--new-code-since lints\n"
            "every file in one run: text and github print each file's findings,\n"
            "json is {files, failures, summary}, sarif is one log. A file that\n"
            "cannot be read or parsed is reported and the others still run.\n"
            "\nExit codes:\n"
            "  0  ran to completion (findings may still have been reported)\n"
            "  1  a file could not be read or parsed, or the output could not\n"
            "     be written, or --changed-since could not ask git\n"
            "  2  the arguments were rejected (argparse's own usage error)\n"
            "  3  --fail-on was given and a finding at or above it was reported"
        ),
    )
    p.add_argument(
        "files",
        nargs="*",
        metavar="FILE",
        help="COBOL program(s) to lint",
    )
    p.add_argument(
        "--glob",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Also lint the files this glob matches (repeatable; ** recurses)",
    )
    p.add_argument(
        "--files-from",
        metavar="FILE",
        help="Also lint the paths listed in FILE, one per line ('-' = stdin)",
    )
    p.add_argument(
        "--changed-since",
        metavar="REF",
        help=(
            "Lint only programs changed since REF (a branch, tag or commit; "
            "compared from its merge base with HEAD, working-tree edits and "
            "untracked files included), plus every program that COPYs a "
            "changed copybook. Picks from FILE/--glob/--files-from when given, "
            "else from every git-tracked program (--extension). Nothing "
            "changed is a clean run (exit 0)."
        ),
    )
    p.add_argument(
        "--new-code-since",
        metavar="REF",
        help=(
            "Report only findings on new code: the lines added or edited "
            "since REF (from its merge base with HEAD; working-tree edits and "
            "untracked files count), like Sonar's new-code quality gate. A "
            "finding with no line counts when its whole file is new. Rules "
            "--scope sets to 'all' still report everywhere. Lints the "
            "programs the change touched (and those COPYing a changed "
            "copybook), or every program when a rule is scoped 'all'."
        ),
    )
    p.add_argument(
        "--scope",
        action="append",
        dest="scopes",
        metavar="[RULE=]new|all",
        help=(
            "With --new-code-since: judge RULE (or rule/KIND) on new code "
            "only ('new') or on the whole codebase ('all'); a bare 'new' or "
            "'all' sets every rule's default (default: new). Repeatable; "
            "lint.scope in cobol.yml"
        ),
    )
    p.add_argument(
        "--summary-file",
        metavar="FILE",
        help=(
            "Also append a Markdown summary of the run to FILE (totals, "
            "findings per rule, the findings themselves); pass "
            "$GITHUB_STEP_SUMMARY to show it on the Actions run page"
        ),
    )
    p.add_argument(
        "--extension",
        action="append",
        dest="extensions",
        metavar="EXT",
        help=(
            "Program extension for --changed-since, repeatable "
            "(default: .cbl, .cob, .cobol; any case)"
        ),
    )
    _add_encoding_arg(p)
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p, strict_flag=True)
    # Lint is the one command that covers every unit by default: it is the
    # file's diagnostics, and a contained program left unexamined would read
    # as a clean one.
    _add_program_arg(p, default_note="every unit in the file")
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    p.add_argument(
        "--rule",
        action="append",
        dest="rules",
        choices=list(ALL_RULES),
        metavar="RULE",
        help=(
            "Run only this rule (repeatable). Rule ids are the analyzer "
            "subcommand names, the bug-pattern rules, line-length "
            "(fixed-format text past column 72 or 80) and call-check (needs "
            "--callee-path): " + ", ".join(ALL_RULES) + ". Default: all "
            "of them."
        ),
    )
    p.add_argument(
        "--callee-path",
        action="append",
        default=[],
        metavar="DIR",
        help=(
            "Directory holding CALLed programs' source, found by program "
            "name (NAME, NAME.cbl, NAME.cob; repeatable; cobol.yml "
            "callee_path). Turns on the call-check rule: every CALL is "
            "compared with the callee's PROCEDURE DIVISION USING (argument "
            "count, passing mode, byte length, usage), as `call-check` does."
        ),
    )
    p.add_argument(
        "--disable",
        action="append",
        choices=list(ALL_RULES),
        metavar="RULE",
        help="Do not run this rule (repeatable; applied after --rule)",
    )
    p.add_argument(
        "--min-severity",
        choices=list(SEVERITIES),
        default=None,
        help=(
            "Drop findings below this severity from the output (default: "
            "warning for --format text and github, info -- everything -- for "
            "json and sarif). Filtering happens after the rules run, so the "
            "summary counts describe what is shown."
        ),
    )
    p.add_argument(
        "--severity",
        action="append",
        dest="severity_overrides",
        metavar="RULE=LEVEL",
        help=(
            "Report this rule (or rule/KIND, e.g. io-sequence/FILE_LEFT_OPEN) "
            "at LEVEL: error, warning or info (repeatable; lint.severity in "
            "cobol.yml)"
        ),
    )
    p.add_argument(
        "--exclude",
        action="append",
        metavar="PATTERN",
        help=(
            "Leave out files matching this glob when linting several files "
            "(repeatable; '*' also crosses folders)"
        ),
    )
    p.add_argument(
        "--baseline",
        metavar="FILE",
        help=(
            "Report only findings not recorded in this baseline file (see "
            "--write-baseline); matched on rule, kind, file and symbol, not "
            "line, so edits elsewhere in a file keep a known finding known"
        ),
    )
    p.add_argument(
        "--write-baseline",
        metavar="FILE",
        help=(
            "Record every current finding in FILE (before --min-severity) and "
            "exit 0, so a later --baseline run reports only new ones"
        ),
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Lint several files in N parallel processes (default: the CPU "
            "count; 1 runs them one by one)"
        ),
    )
    p.add_argument(
        "--fail-on",
        choices=[*SEVERITIES, "never"],
        default="never",
        help=(
            "Exit 3 when a finding at or above this severity was reported, "
            "for use as a CI gate (default: never -- findings alone never "
            "change the exit code). Exit 1 still means the run itself "
            "failed, so the two are never confused."
        ),
    )
    p.add_argument(
        "--format",
        choices=["json", "text", "sarif", "github"],
        default="json",
        dest="output_format",
        help=(
            "json (default) emits the full LintReport; text emits one "
            "grep-friendly 'file:line:column: severity [rule] message' line "
            "per finding plus a summary; sarif emits a SARIF 2.1.0 log "
            "(GitHub code scanning, IDE problem panes); github emits GitHub "
            "Actions workflow commands (::error/::warning/::notice), which "
            "annotate the pull request diff."
        ),
    )
    p.set_defaults(func=_cmd_lint)


def _lint_text_report(report: Any, source_file: str, summary: bool = True) -> str:
    """Render a :class:`LintReport` as compiler-style diagnostic lines.

    Deliberately the same ``file:line:column: severity`` prefix an editor's
    or a build log's error parser already understands, so lint output is
    clickable where JSON is not. Findings with no location (a recursion
    cycle spans procedures rather than sitting on one line) print as
    ``file: severity ...`` -- the column is omitted rather than faked as 0,
    which a parser would render as a real position at the top of the file.
    A finding with a line but no real column prints ``file:line:``.

    The column is ``origin_column``, the one an editor shows (#301); when it
    is not known the column is left out, since analyzer columns count the
    normalized text and are 7 short on a fixed-format line.
    """
    lines: list[str] = []
    for finding in report.findings:
        if finding.location is None:
            lines.append(
                f"{source_file}: {finding.severity} [{finding.rule}] {finding.message}"
            )
            continue
        # A mapped finding prints the file and line it is really on -- inside
        # an inlined copybook, that is not this file at all -- so the prefix
        # stays clickable after expansion instead of pointing at whatever
        # happens to sit at that line number of the program.
        if finding.origin_file is not None and finding.origin_line is not None:
            prefix = f"{finding.origin_file}:{finding.origin_line}:"
        else:
            prefix = f"{source_file}:{finding.location.line}:"
        # Only a column an editor would agree with is printed; the analyzer
        # column alone is 7 short on a fixed-format line, so without an
        # on-disk column (a copybook that could not be re-read, a parse error
        # that gave only a line) the prefix stops at the line.
        if finding.origin_column is not None:
            prefix += f"{finding.origin_column}:"
        lines.append(f"{prefix} {finding.severity} [{finding.rule}] {finding.message}")
    for caveat in report.caveats:
        lines.append(f"{source_file}: note: {caveat}")
    for failure in report.failed_rules:
        lines.append(
            f"{source_file}: note: rule {failure['rule']} did not run ({failure['error']})"
        )
    if summary:
        lines.append(
            f"{len(report.findings)} finding(s): {report.error_count} error, "
            f"{report.warning_count} warning, {report.info_count} info "
            f"({len(report.rules_run)} rule(s) ran)"
            + (f"; {report.suppressed} suppressed" if report.suppressed else "")
            + (f"; {report.baselined} in baseline" if report.baselined else "")
        )
    return "\n".join(lines)


#: GitHub annotation level per lint severity; GitHub has no "info".
_GITHUB_LEVELS = {"error": "error", "warning": "warning", "info": "notice"}


def _github_escape(text: str, *, prop: bool = False) -> str:
    """Escape *text* for a workflow command (message, or a property value)."""
    text = text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    if prop:
        text = text.replace(":", "%3A").replace(",", "%2C")
    return text


def _github_path(path: str) -> str:
    """*path* relative to the workspace GitHub annotates against
    (``$GITHUB_WORKSPACE``, else the current directory) when it is inside
    it; an annotation on an absolute path lands nowhere."""
    root = os.environ.get("GITHUB_WORKSPACE") or os.getcwd()
    try:
        relative = os.path.relpath(os.path.abspath(path), os.path.abspath(root))
    except ValueError:  # another drive on Windows
        return path
    if relative.startswith(".."):
        return path
    return relative.replace(os.sep, "/")


def _github_command(
    level: str,
    message: str,
    *,
    file: str | None = None,
    line: int | None = None,
    column: int | None = None,
    title: str | None = None,
) -> str:
    props: list[str] = []
    if file is not None:
        props.append(f"file={_github_escape(_github_path(file), prop=True)}")
    if line is not None:
        props.append(f"line={line}")
    if column is not None:
        props.append(f"col={column}")
    if title is not None:
        props.append(f"title={_github_escape(title, prop=True)}")
    head = f"::{level} " + ",".join(props) if props else f"::{level}"
    return f"{head}::{_github_escape(message)}"


def _lint_github_report(report: Any, source_file: str, summary: bool = True) -> str:
    """Render a :class:`LintReport` as GitHub Actions workflow commands.

    One ``::error`` / ``::warning`` / ``::notice`` per finding (info maps to
    notice), placed like the text report: the file and line it is really on
    (a copybook, when it came from one) and the on-disk column when known.
    GitHub turns them into annotations on the pull request diff, with no
    problem matcher to install. Caveats and rules that did not run print as
    plain ``note:`` lines in the log, as in the text report.
    """
    lines: list[str] = []
    for finding in report.findings:
        file = source_file
        line: int | None = None
        column: int | None = None
        if finding.location is not None:
            if finding.origin_file is not None and finding.origin_line is not None:
                file, line = finding.origin_file, finding.origin_line
            else:
                line = finding.location.line
            column = finding.origin_column
        lines.append(
            _github_command(
                _GITHUB_LEVELS.get(finding.severity, "warning"),
                finding.message,
                file=file,
                line=line,
                column=column,
                title=f"cobol-lint [{finding.rule}]",
            )
        )
    for caveat in report.caveats:
        lines.append(f"{source_file}: note: {caveat}")
    for failure in report.failed_rules:
        lines.append(
            f"{source_file}: note: rule {failure['rule']} did not run ({failure['error']})"
        )
    if summary:
        lines.append(
            f"{len(report.findings)} finding(s): {report.error_count} error, "
            f"{report.warning_count} warning, {report.info_count} info "
            f"({len(report.rules_run)} rule(s) ran)"
            + (f"; {report.suppressed} suppressed" if report.suppressed else "")
            + (f"; {report.baselined} in baseline" if report.baselined else "")
        )
    return "\n".join(lines)


def _lint_copybook_item_names(
    args: argparse.Namespace, ast: Any, result: Any
) -> set[str] | None:
    """Names that reached *ast* through an expanded COPY, or None if unknown.

    It is what lets lint grade an unused copybook field as info rather than
    warning. Read off the expansion's own source map: an item whose
    declaration line maps to another file than the program came from a
    copybook. (This used to diff against a second, unexpanded parse of the
    file -- a third of lint's time on a large codebase.) A name the program
    also declares itself is left out, so the program's own copy keeps its
    warning. Without --copybook-path there is nothing to tell apart, so the
    answer is "unknown" -- which the analyzer reads as "none came from a
    copybook", the same as it does for the unused-variables subcommand.

    Every program unit counts, because lint covers every unit:
    ``collect_declared_items`` is program-scoped, so reading the outermost
    unit alone would grade a contained program's copybook fields as the
    program's own.
    """
    from ...analysis.unused_variables import copybook_item_names

    if not getattr(args, "copybook_path", []):
        return None
    return copybook_item_names(
        ast, getattr(result, "expansion_source_map", None), args.file
    )


def _lint_column_offset(
    args: argparse.Namespace,
) -> Callable[[str, int], int | None]:
    """``(file, line) -> offset`` for lint (#301); see
    :func:`cobolparser.analysis.lint.source_column_offsets`."""
    from ...analysis.lint import source_column_offsets

    return source_column_offsets(
        args.file, _source_format_kwargs(args)["preprocess_fixed"]
    )


def _lint_one(args: argparse.Namespace) -> tuple[Any, Any, Any]:
    """Lint ``args.file``: ``(report, prof, ast)``, the report filtered by
    ``--min-severity`` and every finding placed on disk. Exits 1 through
    :func:`_fail` when the file cannot be read or parsed at all."""
    from ...analysis.lint import (
        CALL_CHECK_RULE,
        LINE_LENGTH_RULE,
        LintAnalyzer,
        add_call_check_findings,
        add_line_length_findings,
        add_parse_errors,
        apply_baseline,
        apply_severity_overrides,
        apply_source_map,
        apply_suppressions,
        filter_by_severity,
    )

    result, prof = _parse_result_or_fail(args)
    ast = result.ast

    selected = getattr(args, "rules", None)
    disabled = getattr(args, "disable", None)
    if disabled:
        from ...analysis.lint import ALL_RULES

        selected = [r for r in (selected or ALL_RULES) if r not in set(disabled)]
    try:
        analyzer = LintAnalyzer(selected)
    except (
        ValueError
    ) as e:  # unreachable via argparse choices; direct callers can hit it
        _fail(str(e))

    report = analyzer.analyze(
        ast,
        copybook_item_names=(
            _lint_copybook_item_names(args, ast, result) if analyzer.rules else None
        ),
    )
    # A COPY the search path could not supply was left as written: every
    # rule ran without that member's fields and paragraphs, so the report
    # says so rather than reading as complete.
    for warning in getattr(result, "warnings", None) or []:
        text = str(warning)
        if text.endswith("the COPY was left as written"):
            report.caveats.append(
                f"{text}; no rule saw what it declares, so findings that "
                "depend on it are missing (pass its folder with "
                "--copybook-path, or --strict-copybooks to fail instead)"
            )
    # A partial AST lints quietly, so the errors it was recovered from are
    # findings of their own: --fail-on then sees them (#249).
    add_parse_errors(report, list(result.errors))
    # With --copybook-path the analyzers ran over expanded text, so every
    # location counts expanded lines. The expander's own map turns each one
    # back into the file and line a reader can open.
    expansion_map = getattr(result, "expansion_source_map", None)
    source_map = expansion_map
    if not source_map:
        # Nothing expanded: every line is this file's own. Mapped anyway, so
        # JSON carries the on-disk column in `origin` exactly as the
        # expanded case does.
        source_map = {
            f.location.line: (args.file, f.location.line)
            for f in report.findings
            if f.location is not None
        }
    callee_paths = list(getattr(args, "callee_path", None) or [])
    if callee_paths and (selected is None or CALL_CHECK_RULE in selected):
        # Before the map: call-check lines count this parse's text too.
        add_call_check_findings(
            report, args.file, ast, _lint_callee_resolver(args, callee_paths)
        )
        source_map = expansion_map or {
            f.location.line: (args.file, f.location.line)
            for f in report.findings
            if f.location is not None
        }
    # Analyzer columns count the normalized text, 7 short of the real column
    # on a fixed-format line; the offset turns them back into the column an
    # editor shows (#301).
    apply_source_map(report, source_map, _lint_column_offset(args))
    if selected is None or LINE_LENGTH_RULE in selected:
        # After the map: these findings are placed on disk already.
        add_line_length_findings(
            report,
            args.file,
            expansion_map,
            _source_format_kwargs(args)["preprocess_fixed"],
            getattr(result, "expansion_copybooks", None) or (),
        )
    # Policy, in order: lint.severity re-grades, an inline `cobol-lint:`
    # comment silences, a baseline hides what was already known, and only
    # then --min-severity trims what is shown -- so a re-graded finding is
    # filtered at its new severity, and a baseline written before a
    # --min-severity change still covers what the change brings back.
    apply_severity_overrides(report, _lint_severity_overrides(args))
    apply_suppressions(report, args.file)
    if getattr(args, "write_baseline", None):
        return report, prof, ast  # the caller records it whole, then filters
    baseline_file = getattr(args, "baseline", None)
    if baseline_file:
        baseline = _load_lint_baseline(baseline_file)
        apply_baseline(
            report, args.file, baseline, os.path.dirname(os.path.abspath(baseline_file))
        )
    new_code = getattr(args, "_new_code", None)
    if new_code is not None:
        from .._new_code import apply_new_code

        apply_new_code(
            report, args.file, new_code, args._scope_default, args._scope_rules
        )
    report.findings = filter_by_severity(report.findings, _lint_min_severity(args))

    for failure in report.failed_rules:
        print(
            f"warning: lint rule {failure['rule']} did not run: {failure['error']}",
            file=sys.stderr,
        )
    return report, prof, ast


#: One CalleeResolver per (callee dirs, copybook dirs) for the process, so a
#: multi-file lint parses each CALLed program once, not once per caller.
_LINT_CALLEE_RESOLVERS: dict[tuple[tuple[str, ...], tuple[str, ...]], Any] = {}


def _lint_callee_resolver(args: argparse.Namespace, callee_paths: list[str]) -> Any:
    from ...analysis.call_interface import CalleeResolver

    copybooks = tuple(getattr(args, "copybook_path", None) or [])
    key = (tuple(callee_paths), copybooks)
    if key not in _LINT_CALLEE_RESOLVERS:
        _LINT_CALLEE_RESOLVERS[key] = CalleeResolver(
            callee_paths,
            copybook_paths=list(copybooks),
            debug_lines=bool(getattr(args, "debug_lines", False)),
        )
    return _LINT_CALLEE_RESOLVERS[key]


def _lint_severity_overrides(args: argparse.Namespace) -> dict[str, str] | None:
    """``--severity RULE=LEVEL`` flags, or ``lint.severity`` from cobol.yml
    (already a mapping), as one ``{selector: level}`` dict."""
    from ...analysis.lint import ALL_RULES, PARSE_RULE, SEVERITIES

    raw = getattr(args, "severity_overrides", None)
    if not raw:
        return None
    if isinstance(raw, dict):
        return {str(k): str(v) for k, v in raw.items()}
    overrides: dict[str, str] = {}
    for item in raw:
        selector, sep, level = str(item).partition("=")
        rule = selector.split("/", 1)[0]
        if not sep or level not in SEVERITIES or rule not in (*ALL_RULES, PARSE_RULE):
            print(
                f"error: --severity {item}: expected RULE=LEVEL or "
                f"RULE/KIND=LEVEL, with RULE one of {', '.join(ALL_RULES)} and "
                f"LEVEL one of {', '.join(SEVERITIES)}",
                file=sys.stderr,
            )
            sys.exit(2)  # a bad argument, as argparse would exit
        overrides[selector] = level
    return overrides


def _lint_min_severity(args: argparse.Namespace) -> str:
    """``--min-severity``, or its default for the output format: a person
    reading text or a PR's annotations wants warnings and errors; a JSON or
    SARIF consumer filters for itself and gets everything."""
    chosen = getattr(args, "min_severity", None)
    if chosen:
        return str(chosen)
    if getattr(args, "output_format", "json") in ("text", "github"):
        return "warning"
    return "info"


_BASELINE_CACHE: dict[str, Any] = {}


def _load_lint_baseline(path: str) -> Any:
    """The baseline at *path* (read once per process), or exit 1 with why."""
    from ...analysis.lint import load_baseline

    key = os.path.abspath(path)
    if key not in _BASELINE_CACHE:
        try:
            with open(path, encoding="utf-8") as handle:
                _BASELINE_CACHE[key] = load_baseline(json.load(handle))
        except FileNotFoundError:
            _fail(
                f"baseline {path} does not exist; create it with "
                f"--write-baseline {path}"
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _fail(f"baseline {path} could not be read: {exc}")
    return _BASELINE_CACHE[key]


def _write_lint_baseline(
    args: argparse.Namespace, reports: list[tuple[str, Any]]
) -> None:
    """Record *reports*' findings in ``--write-baseline`` FILE, then trim
    each report to ``--min-severity`` for display."""
    from ...analysis.lint import baseline_document, filter_by_severity

    path = args.write_baseline
    document = baseline_document(reports, os.path.dirname(os.path.abspath(path)))
    try:
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(document, handle, indent=2)
            handle.write("\n")
    except OSError as exc:
        _fail(f"could not write baseline {path}: {exc}")
    total = sum(entry["count"] for entry in document["findings"])
    print(f"note: wrote {total} finding(s) to baseline {path}", file=sys.stderr)
    for _path, report in reports:
        report.findings = filter_by_severity(report.findings, _lint_min_severity(args))


def _lint_fails(report: Any, fail_on: str) -> bool:
    """True when *report* holds a finding at or above *fail_on*."""
    if fail_on == "never":
        return False
    worst = report.worst_severity()
    return worst is not None and _severity_at_least(worst, fail_on)


def _lint_wants_many(args: argparse.Namespace) -> bool:
    """Whether this run is the multi-file form (anything but one FILE)."""
    return bool(
        len(args.files) != 1
        or args.glob
        or getattr(args, "files_from", None)
        or getattr(args, "changed_since", None)
        or getattr(args, "new_code_since", None)
    )


def _cmd_lint(args: argparse.Namespace) -> None:
    if not _lint_wants_many(args):
        args.file = args.files[0]
        _lint_single(args)
        return
    if not (
        args.files
        or args.glob
        or getattr(args, "files_from", None)
        or getattr(args, "changed_since", None)
        or getattr(args, "new_code_since", None)
    ):
        print(
            "error: lint needs a FILE, --glob, --files-from, --changed-since "
            "or --new-code-since",
            file=sys.stderr,
        )
        sys.exit(2)
    _lint_many(args)


def _lint_single(args: argparse.Namespace) -> None:
    """One FILE: the report shapes ``lint`` has always printed."""
    report, prof, ast = _lint_one(args)
    if getattr(args, "write_baseline", None):
        _write_lint_baseline(args, [(args.file, report)])
        args.fail_on = "never"  # recording the findings is not failing on them
    if getattr(args, "summary_file", None):
        counts = {
            "error": report.error_count,
            "warning": report.warning_count,
            "info": report.info_count,
        }
        hidden = {"suppressed": report.suppressed, "baselined": report.baselined}
        _write_lint_summary(
            args.summary_file, args, [(args.file, report, None)], [], counts, hidden
        )

    if args.output_format in ("text", "github"):
        if prof is not None:
            # The text report has nowhere to embed the profiling dict;
            # dropping it silently would make --profile look like a no-op.
            print(
                "warning: --profile metrics are only included in --format json "
                f"output; ignoring for --format {args.output_format}",
                file=sys.stderr,
            )
        render = (
            _lint_text_report if args.output_format == "text" else _lint_github_report
        )
        _text_out(render(report, args.file), getattr(args, "output", None))
    elif args.output_format == "sarif":
        from ...analysis.sarif import lint_notifications, lint_results, sarif_log

        data = report.to_dict()
        _json_out(
            sarif_log(
                lint_results(data, args.file), lint_notifications(data, args.file)
            ),
            args.compact,
            getattr(args, "output", None),
        )
    else:
        _emit_report(report.to_dict(), args, prof, ast)

    if _lint_fails(report, getattr(args, "fail_on", "never")):
        sys.exit(3)


def _lint_selection(args: argparse.Namespace) -> tuple[list[str], Any]:
    """The files a multi-file lint covers, and the ``ChangeSelection`` when
    ``--changed-since`` picked them (else ``None``)."""
    from .._changed_files import (
        DEFAULT_PROGRAM_EXTENSIONS,
        ChangedFilesError,
        changed_files,
        program_candidates,
        select_changed_programs,
        tracked_files,
    )

    explicit = bool(args.files or args.glob or getattr(args, "files_from", None))
    files = _collect_scan_files(args) if explicit else []
    ref = getattr(args, "changed_since", None)
    new_ref = getattr(args, "new_code_since", None)
    if new_ref:
        from .._new_code import every_rule_new, new_code_since

        try:
            args._new_code = new_code_since(new_ref)
        except ChangedFilesError as exc:
            _fail(f"--new-code-since: {exc}")
        if not ref and every_rule_new(args._scope_default, args._scope_rules):
            # Nothing outside the change can report: lint only what it touched.
            ref = new_ref
        elif not ref:
            if explicit:
                return files, None
            extensions = tuple(
                getattr(args, "extensions", None) or DEFAULT_PROGRAM_EXTENSIONS
            )
            try:
                return (
                    program_candidates(
                        tracked_files(),
                        extensions,
                        list(getattr(args, "copybook_path", None) or []),
                    ),
                    None,
                )
            except ChangedFilesError as exc:
                _fail(f"--new-code-since: {exc}")
    if not ref:
        return files, None

    extensions = tuple(getattr(args, "extensions", None) or DEFAULT_PROGRAM_EXTENSIONS)
    copybook_dirs = list(getattr(args, "copybook_path", None) or [])
    try:
        changed = changed_files(ref)
        candidates = (
            files
            if explicit
            else program_candidates(tracked_files(), extensions, copybook_dirs)
        )
    except ChangedFilesError as exc:
        flag = (
            "--changed-since"
            if getattr(args, "changed_since", None)
            else ("--new-code-since")
        )
        _fail(f"{flag}: {exc}")
    selection = select_changed_programs(changed, candidates, copybook_dirs, extensions)
    for program, members in selection.via_copybook.items():
        print(
            f"note: {program}: linted because it copies changed "
            f"copybook(s) {', '.join(members)}",
            file=sys.stderr,
        )
    return selection.programs, selection


def _lint_one_isolated(
    args: argparse.Namespace, path: str
) -> tuple[Any, Any, str | None]:
    """Lint one file of a multi-file run: ``(report, identification, None)``,
    or ``(None, None, why)`` when it could not be linted. Its diagnostics
    still reach stderr; a failure never stops the other files. Returns the
    report's identification dict rather than the AST so a worker process
    hands back only what the output needs."""
    import contextlib
    import io

    one = argparse.Namespace(**vars(args))
    one.file = path
    one.profile = False
    one.profile_top_n = _DEFAULT_PROFILE_TOP_N
    one.profile_output = None
    captured = io.StringIO()
    try:
        with contextlib.redirect_stderr(captured):
            report, _prof, ast = _lint_one(one)
    except SystemExit as exc:
        sys.stderr.write(captured.getvalue())
        errors = [
            line[len("error: ") :]
            for line in captured.getvalue().splitlines()
            if line.startswith("error: ")
        ]
        return None, None, (errors[-1] if errors else f"exit {exc.code}")
    except Exception as exc:  # noqa: BLE001 -- one file must not end the run
        sys.stderr.write(captured.getvalue())
        print(f"error: {path}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None, None, f"{type(exc).__name__}: {exc}"
    sys.stderr.write(captured.getvalue())
    return report, _identification(argparse.Namespace(file=path), ast), None


def _lint_excluded(path: str, patterns: list[str]) -> bool:
    """Whether *path* matches one of the ``--exclude`` / ``lint.exclude``
    globs (``*`` crosses folders; a pattern is tried against the path as
    given and against its absolute form, since config patterns are
    resolved to absolute ones)."""
    import fnmatch

    absolute = os.path.abspath(path)
    candidates = {
        path,
        absolute,
        path.replace(os.sep, "/"),
        absolute.replace(os.sep, "/"),
    }
    return any(
        fnmatch.fnmatch(candidate, pattern)
        or fnmatch.fnmatch(candidate, pattern + "/*")
        for pattern in patterns
        for candidate in candidates
    )


def _lint_files_parallel(
    args: argparse.Namespace, files: list[str]
) -> list[tuple[str, Any, Any, str | None]]:
    """``(path, report, identification, why)`` for every file, in order: in
    ``--workers`` processes (default the CPU count) when there is more than
    one file, else in this process."""
    workers = getattr(args, "workers", None) or os.cpu_count() or 1
    workers = max(1, min(workers, len(files)))
    if workers == 1:
        return [(path, *_lint_one_isolated(args, path)) for path in files]
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=workers) as pool:
        results = list(
            pool.map(_lint_one_isolated, [args] * len(files), files, chunksize=1)
        )
    return [(path, *result) for path, result in zip(files, results, strict=True)]


def _drop_repeated_layout_findings(linted: list[tuple[str, Any, Any]]) -> None:
    """Keep each ``line-length`` finding once per run.

    It is a fact about a line of a file, not about the program that read it:
    a copybook COPYed by twenty linted programs would otherwise print the
    same finding twenty times. The first program to report it keeps it.
    """
    from pathlib import Path

    from ...analysis.lint import LINE_LENGTH_RULE

    seen: set[tuple[str, int | None, str | None]] = set()
    for _path, report, _ast in linted:
        kept = []
        for finding in report.findings:
            if finding.rule == LINE_LENGTH_RULE and finding.origin_file:
                key = (
                    str(Path(finding.origin_file).resolve()),
                    finding.origin_line,
                    finding.kind,
                )
                if key in seen:
                    continue
                seen.add(key)
            kept.append(finding)
        report.findings = kept


def _lint_many(args: argparse.Namespace) -> None:
    """Several files in one run; see the ``lint`` epilog for the shapes."""
    if _profiling_requested(args):
        print(
            "warning: --profile is only supported when linting one file; ignoring",
            file=sys.stderr,
        )
    _lint_prepare_scopes(args)
    files, selection = _lint_selection(args)
    if not files and selection is None:
        _fail("No input files: the FILE arguments, --glob and --files-from named none.")
    if not files:
        since = getattr(args, "changed_since", None) or args.new_code_since
        print(
            f"note: no COBOL program changed since {since}; nothing to lint",
            file=sys.stderr,
        )

    excludes = list(getattr(args, "exclude", None) or [])
    if excludes:
        kept_files = [f for f in files if not _lint_excluded(f, excludes)]
        if len(kept_files) != len(files):
            print(
                f"note: {len(files) - len(kept_files)} file(s) left out by exclude",
                file=sys.stderr,
            )
        files = kept_files

    linted: list[tuple[str, Any, Any]] = []
    failures: list[tuple[str, str]] = []
    for path, report, ident, why in _lint_files_parallel(args, files):
        if report is None:
            failures.append((path, why or "could not be linted"))
        else:
            linted.append((path, report, ident))

    if getattr(args, "write_baseline", None):
        _write_lint_baseline(args, [(path, report) for path, report, _ in linted])
        args.fail_on = "never"  # recording the findings is not failing on them
    _drop_repeated_layout_findings(linted)

    fmt = args.output_format
    output = getattr(args, "output", None)
    totals = {
        "error": sum(r.error_count for _, r, _ in linted),
        "warning": sum(r.warning_count for _, r, _ in linted),
        "info": sum(r.info_count for _, r, _ in linted),
    }
    total = sum(totals.values())
    hidden = {
        "suppressed": sum(r.suppressed for _, r, _ in linted),
        "baselined": sum(r.baselined for _, r, _ in linted),
    }
    new_code = getattr(args, "_new_code", None)
    if new_code is not None:
        hidden["outside_new_code"] = sum(r.outside_new_code or 0 for _, r, _ in linted)
    summary_line = (
        f"{total} finding(s) in {len(linted)} file(s): {totals['error']} error, "
        f"{totals['warning']} warning, {totals['info']} info"
        + (f"; {hidden['suppressed']} suppressed" if hidden["suppressed"] else "")
        + (f"; {hidden['baselined']} in baseline" if hidden["baselined"] else "")
        + (
            f"; {hidden['outside_new_code']} outside new code"
            if hidden.get("outside_new_code")
            else ""
        )
        + (f"; {len(failures)} file(s) could not be linted" if failures else "")
    )
    summary_file = getattr(args, "summary_file", None)
    if summary_file:
        _write_lint_summary(summary_file, args, linted, failures, totals, hidden)

    if fmt in ("text", "github"):
        chunks: list[str] = []
        for path, report, _ast in linted:
            if fmt == "text":
                chunks.append(_lint_text_report(report, path, summary=False))
            else:
                chunks.append(_lint_github_report(report, path, summary=False))
        for path, why in failures:
            if fmt == "text":
                chunks.append(f"{path}: error [lint] could not be linted: {why}")
            else:
                chunks.append(
                    _github_command(
                        "error", f"could not be linted: {why}", file=path, title="lint"
                    )
                )
        chunks.append(summary_line)
        _text_out("\n".join(c for c in chunks if c), output)
    elif fmt == "sarif":
        from ...analysis.sarif import (
            SarifNotification,
            lint_notifications,
            lint_results,
            sarif_log,
        )

        results = []
        notes = []
        for path, report, _ast in linted:
            data = report.to_dict()
            results += lint_results(data, path)
            notes += lint_notifications(data, path)
        notes += [
            SarifNotification(
                message=f"could not be linted: {why}", level="error", file=path
            )
            for path, why in failures
        ]
        _json_out(sarif_log(results, notes), args.compact, output)
    else:
        entries = []
        for _path, report, ident in linted:
            entry = dict(ident)
            entry.update(report.to_dict())
            entries.append(entry)
        document: dict[str, Any] = {
            "files": entries,
            "failures": [{"source_file": path, "error": why} for path, why in failures],
            "summary": {
                "file_count": len(files),
                "linted": len(linted),
                "failed": len(failures),
                "total": total,
                **totals,
                **hidden,
            },
        }
        if selection is not None:
            document["changed_since"] = {
                "ref": getattr(args, "changed_since", None) or args.new_code_since,
                "changed_files": selection.changed,
                "via_copybook": selection.via_copybook,
            }
        if new_code is not None:
            document["new_code"] = {
                "ref": new_code.ref,
                "default_scope": args._scope_default,
                "rule_scopes": dict(args._scope_rules),
                "changed_files": new_code.changed_paths(),
            }
        _json_out(document, args.compact, output)

    if fmt not in ("text", "github"):
        print(summary_line, file=sys.stderr)
    if failures:
        # 2, as scan / batch / codebase-graph / call-check exit when one
        # file of a multi-file run failed: the report was still written.
        # 1 stays "the CLI never ran" (a single FILE that cannot be linted).
        sys.exit(2)
    fail_on = getattr(args, "fail_on", "never")
    if any(_lint_fails(report, fail_on) for _, report, _ in linted):
        sys.exit(3)


def _lint_prepare_scopes(args: argparse.Namespace) -> None:
    """Validate ``--scope`` / ``lint.scope`` into ``args._scope_default``
    and ``args._scope_rules`` (exit 2 on a bad value, as argparse would)."""
    from .._new_code import parse_scopes

    try:
        default, per_rule = parse_scopes(getattr(args, "scopes", None))
    except ValueError as exc:
        print(f"error: --scope: {exc}", file=sys.stderr)
        sys.exit(2)
    args._scope_default, args._scope_rules = default, per_rule
    args._new_code = None


#: The most findings a ``--summary-file`` lists one by one.
_SUMMARY_FINDING_LIMIT = 200


def _md_cell(text: Any) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def _write_lint_summary(
    path: str,
    args: argparse.Namespace,
    linted: list[tuple[str, Any, Any]],
    failures: list[tuple[str, str]],
    totals: dict[str, int],
    hidden: dict[str, int],
) -> None:
    """Append a Markdown summary of a multi-file lint to *path* (GitHub's
    ``$GITHUB_STEP_SUMMARY``, which shows every finding even past the
    annotation limits a pull request diff applies)."""
    total = sum(totals.values())
    out = ["## COBOL lint", ""]
    new_code = getattr(args, "_new_code", None)
    if new_code is not None and not (
        args._scope_default == "all"
        and all(v == "all" for v in args._scope_rules.values())
    ):
        overrides = ", ".join(
            f"`{rule}`: {scope}" for rule, scope in sorted(args._scope_rules.items())
        )
        out.append(
            f"New code since `{new_code.ref}`; rules judged on "
            + ("new code only" if args._scope_default == "new" else "all code")
            + (f" (except {overrides})" if overrides else "")
            + "."
        )
        out.append("")
    verdict = "No findings" if not total else f"**{total} finding(s)**"
    out.append(
        f"{verdict} in {len(linted)} file(s): {totals['error']} error, "
        f"{totals['warning']} warning, {totals['info']} info."
    )
    notes = []
    if hidden.get("suppressed"):
        notes.append(f"{hidden['suppressed']} suppressed by comments")
    if hidden.get("baselined"):
        notes.append(f"{hidden['baselined']} in the baseline")
    if hidden.get("outside_new_code"):
        notes.append(f"{hidden['outside_new_code']} outside new code")
    if notes:
        out.append("Not shown: " + ", ".join(notes) + ".")
    by_rule: dict[str, dict[str, int]] = {}
    rows = []
    for source, report, _ident in linted:
        for finding in report.findings:
            counts = by_rule.setdefault(
                finding.rule, {"error": 0, "warning": 0, "info": 0}
            )
            counts[finding.severity] = counts.get(finding.severity, 0) + 1
            where = finding.origin_file or source
            line = finding.origin_line or (
                finding.location.line if finding.location is not None else None
            )
            rows.append(
                (
                    {"error": 0, "warning": 1, "info": 2}.get(finding.severity, 3),
                    os.path.relpath(where) if os.path.isabs(where) else where,
                    line or 0,
                    finding,
                )
            )
    if by_rule:
        out += ["", "| Rule | Error | Warning | Info |", "|---|---:|---:|---:|"]
        for rule in sorted(by_rule):
            c = by_rule[rule]
            out.append(f"| `{rule}` | {c['error']} | {c['warning']} | {c['info']} |")
    if failures:
        out += ["", "**Could not be linted:**", ""]
        out += [f"* `{_md_cell(p)}`: {_md_cell(why)}" for p, why in failures]
    if rows:
        rows.sort(key=lambda r: (r[0], r[1], r[2]))
        out += [
            "",
            "| Severity | File | Line | Rule | Message |",
            "|---|---|---:|---|---|",
        ]
        for _rank, where, line, finding in rows[:_SUMMARY_FINDING_LIMIT]:
            out.append(
                f"| {finding.severity} | `{_md_cell(where)}` | {line or ''} | "
                f"`{finding.rule}` | {_md_cell(finding.message)} |"
            )
        if len(rows) > _SUMMARY_FINDING_LIMIT:
            out.append("")
            out.append(
                f"...and {len(rows) - _SUMMARY_FINDING_LIMIT} more (run with "
                "--format json or sarif for the full list)."
            )
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(out) + "\n\n")
    except OSError as exc:
        print(f"warning: could not write --summary-file {path}: {exc}", file=sys.stderr)
