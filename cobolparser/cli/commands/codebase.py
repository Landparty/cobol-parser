"""Multi-program subcommands: scan, diff, codebase-graph, copybook-impact,
call-check."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from .._common import (
    _DIALECT_MAP,
    _add_compact_arg,
    _add_copybook_args,
    _add_debug_lines_arg,
    _add_define_args,
    _add_dialect_arg,
    _add_error_recovery_arg,
    _add_limit_args,
    _add_min_clone_statements_arg,
    _add_output_arg,
    _add_source_format_args,
    _collect_scan_files,
    _defined_symbol_pairs,
    _fail,
    _get_error_recovery,
    _json_out,
    _limit_kwargs,
    _parse_or_fail,
    _source_format_kwargs,
    _text_out,
    _verbatim_out,
)

# -- Subcommand: scan ---------------------------------------------------------


def _build_scan_parser(subparsers: argparse._SubParsersAction) -> None:
    from ...scan import ANALYZERS, DEFAULT_ANALYZERS

    p = subparsers.add_parser(
        "scan",
        help=(
            "Run analyzers over many files in one process, with per-file "
            "fault isolation and cross-file clone detection"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser scan src/*.cbl\n"
            "  cobol-parser scan --glob 'src/**/*.cbl' --workers 8\n"
            "  cobol-parser scan --glob 'src/**/*.cbl' --analyzer health --clones\n"
            "\n"
            "Unlike running an analyzer once per file, the parse and the\n"
            "analysis both happen inside a worker and only the reports come\n"
            "back, so a whole checkout fits in one invocation. A file that\n"
            "cannot be read or parsed is reported under `failures` and costs\n"
            "the scan nothing else."
        ),
    )
    p.add_argument("files", nargs="*", help="Paths to COBOL source files")
    p.add_argument(
        "--glob",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Glob pattern to collect source files (repeatable, e.g. 'src/**/*.cbl')",
    )
    p.add_argument(
        "--files-from",
        metavar="FILE",
        help=(
            "Read the file list from FILE, one path per line (blank lines and "
            "lines starting with # are skipped; '-' reads stdin). Combines "
            "with file arguments and --glob. Needed for a list too long for "
            "the command line: a Windows command line caps at 8191 "
            "characters, which a few dozen absolute paths already exceed."
        ),
    )
    p.add_argument(
        "--analyzer",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Analyzer to run (repeatable, or comma-separated). One of: "
            + ", ".join(ANALYZERS)
            + ". Default: "
            + ",".join(DEFAULT_ANALYZERS)
            + "."
        ),
    )
    p.add_argument(
        "--clones",
        action="store_true",
        help=(
            "Also group every scanned paragraph into cross-file clone groups. "
            "Requires the `redundancy` analyzer (in the default set); a scan "
            "without it reports no groups rather than an empty result."
        ),
    )
    p.add_argument(
        "--min-clone-members",
        type=int,
        default=2,
        metavar="N",
        help=(
            "Fewest distinct copies a cross-file clone group needs to be "
            "reported with --clones; one copybook paragraph included by "
            "several programs counts once. Default: 2."
        ),
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Number of worker processes (default: CPU count)",
    )
    _add_limit_args(p)
    p.add_argument(
        "--encoding",
        default=None,
        help=(
            "Source encoding (default: detected per file, the same way a "
            "copybook's is)"
        ),
    )
    p.add_argument(
        "--cache-dir",
        default=None,
        metavar="DIR",
        help=(
            "Keep each file's report in DIR and reuse it on the next scan "
            "while the file, its copybooks and the copybook directories are "
            "unchanged (summary.cached_file_count counts the reused ones)"
        ),
    )
    p.add_argument(
        "--format",
        choices=["json", "sarif"],
        default="json",
        dest="output_format",
        help=(
            "json (default) or a SARIF 2.1.0 log of the lint findings of "
            "every file (GitHub code scanning). sarif runs the lint "
            "analyzer, alone unless --analyzer names others too"
        ),
    )
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    _add_min_clone_statements_arg(p)
    p.set_defaults(func=_cmd_scan)


def _cmd_scan(args: argparse.Namespace) -> None:
    from ...scan import (
        ScanOptions,
        cross_file_clone_groups,
        parse_analyzer_list,
        scan_files,
    )

    files = _collect_scan_files(args)
    if not files:
        _fail("No input files specified. Provide file arguments or use --glob.")

    if args.workers is not None and args.workers < 1:
        _fail("--workers must be >= 1")

    analyzers = parse_analyzer_list(args.analyzer)
    sarif = getattr(args, "output_format", "json") == "sarif"
    if sarif:
        analyzers = (
            ("lint",)
            if not args.analyzer
            else tuple(dict.fromkeys((*analyzers, "lint")))
        )
    source_format = _source_format_kwargs(args)
    options = ScanOptions(
        analyzers=analyzers,
        dialect=_DIALECT_MAP[args.dialect],
        error_recovery=_get_error_recovery(args),
        copybook_paths=tuple(getattr(args, "copybook_path", []) or []),
        min_clone_statements=max(1, args.min_clone_statements),
        encoding=args.encoding,
        # Both halves of the layout flags: free_form alone dropped
        # --source-format fixed|free (and cobol.yml's source_format) on the
        # floor, so a tagged fixed-format member scanned as free-form.
        free_form=bool(source_format["free_form"]),
        preprocess_fixed=source_format["preprocess_fixed"],
        debug_lines=bool(source_format.get("debug_lines", False)),
        defined_symbols=_defined_symbol_pairs(args),
        cache_dir=args.cache_dir,
        **_limit_kwargs(args),
    )

    try:
        report = scan_files(files, options, workers=args.workers)
    except ValueError as exc:
        # An unknown --analyzer name. argparse `choices` would reject the
        # comma-separated spelling this flag accepts, so the check lives in
        # scan_files and its message is already the one to print.
        _fail(str(exc))

    if sarif:
        from ...analysis.sarif import (
            SarifNotification,
            lint_notifications,
            lint_results,
            sarif_log,
        )

        results = []
        notes = []
        for scanned in report.ok_files:
            lint = scanned.reports.get("lint") or {}
            results += lint_results(lint, scanned.path)
            notes += lint_notifications(lint, scanned.path)
        notes += [
            SarifNotification(
                message=f"not scanned: {f.error}", level="error", file=f.path
            )
            for f in report.failed_files
        ]
        _json_out(
            sarif_log(results, notes), args.compact, getattr(args, "output", None)
        )
        if report.failed_files:
            print(
                f"warning: {len(report.failed_files)} of {len(report.files)} "
                "file(s) could not be scanned",
                file=sys.stderr,
            )
            sys.exit(2)
        return

    output = report.to_dict()
    if args.clones:
        groups = cross_file_clone_groups(
            report, min_members=max(2, args.min_clone_members)
        )
        output["cross_file_clone_groups"] = [g.to_dict() for g in groups]
        output["summary"]["cross_file_clone_group_count"] = len(groups)

    _json_out(output, args.compact, getattr(args, "output", None))

    # Like batch: a file that produced nothing to scan fails the run, so a
    # script gating on $? does not read "nothing scanned" as success (#325).
    failed = report.failed_files
    if failed:
        print(
            f"warning: {len(failed)} of {len(report.files)} file(s) could not "
            "be scanned (see the JSON output's failures)",
            file=sys.stderr,
        )
        sys.exit(2)


# -- Subcommand: diff ---------------------------------------------------------


def _build_diff_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "diff",
        help="Structurally diff two versions of a COBOL program (what changed "
        "in behavior, not which lines moved)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser diff old/PROG.cbl new/PROG.cbl\n"
            "  cobol-parser diff old/PROG.cbl new/PROG.cbl --format text\n"
            "  cobol-parser diff old/PROG.cbl new/PROG.cbl --rename-threshold 1.0"
        ),
    )
    p.add_argument("old", help="Path to the old version of the COBOL source")
    p.add_argument("new", help="Path to the new version of the COBOL source")
    p.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )
    p.add_argument(
        "--rename-threshold",
        type=float,
        default=0.8,
        metavar="RATIO",
        help="How similar two unmatched bodies must be (0.0-1.0) before the "
        "pair is reported as a rename rather than a removal plus an addition "
        "(default: 0.8; 1.0 accepts only identical bodies)",
    )
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_diff)


def _cmd_diff(args: argparse.Namespace) -> None:
    """Diff two program versions structurally.

    Takes two positionals rather than the usual single ``file``, so it cannot
    share ``_build_analyzer_parser``. Each side is parsed through the same
    helper the single-file subcommands use, by swapping ``args.file`` -- so
    both sides honour --source-format, --dialect, --copybook-path and
    --define identically. Parsing them under different options would make the
    diff meaningless.
    """
    from ...analysis.ast_diff import ProgramDiffer

    if not 0.0 <= args.rename_threshold <= 1.0:
        print(
            f"Error: --rename-threshold must be between 0.0 and 1.0, "
            f"got {args.rename_threshold}",
            file=sys.stderr,
        )
        sys.exit(1)

    old_args = argparse.Namespace(**{**vars(args), "file": args.old})
    new_args = argparse.Namespace(**{**vars(args), "file": args.new})
    old_ast, _ = _parse_or_fail(old_args)
    new_ast, _ = _parse_or_fail(new_args)

    report = ProgramDiffer(rename_threshold=args.rename_threshold).diff(
        old_ast, new_ast
    )

    if args.output_format == "text":
        _text_out(report.to_text(), getattr(args, "output", None))
        return

    _json_out(
        {"old_file": args.old, "new_file": args.new, **report.to_dict()},
        args.compact,
        getattr(args, "output", None),
    )


# -- Subcommand: codebase-graph -----------------------------------------------


def _build_codebase_graph_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "codebase-graph",
        help="Build the cross-program CALL (and CICS LINK/XCTL) graph and "
        "copybook dependency graph for a whole source tree",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser codebase-graph ./src\n"
            "  cobol-parser codebase-graph ./src --copybook-path ./copybooks\n"
            "  cobol-parser codebase-graph ./src --format mermaid -o graph.mmd\n"
            "  cobol-parser codebase-graph a.cbl b.cbl --format dot"
        ),
    )
    p.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="One directory to walk, or any number of COBOL source files",
    )
    p.add_argument(
        "--format",
        choices=["json", "dot", "mermaid"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )
    p.add_argument(
        "--extension",
        action="append",
        dest="extensions",
        metavar="EXT",
        help="Source extension to walk for, repeatable "
        "(default: .cbl, .cob, .cobol)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Worker processes for the batch parse (default: chosen by size)",
    )
    _add_compact_arg(p)
    _add_copybook_args(p)
    _add_output_arg(p)
    _add_debug_lines_arg(p)
    p.set_defaults(func=_cmd_codebase_graph)


def _build_graph(args: argparse.Namespace) -> Any:
    """Build a CodebaseGraph from the paths given on the command line.

    A single directory argument is walked; anything else is treated as an
    explicit file list. Mixing the two is rejected rather than silently
    resolved, since "walk this and also that one file" has no obvious
    right answer and guessing one would hide a typo.
    """
    from ...analysis.codebase import CodebaseGraphBuilder

    # The same guard batch and scan apply: without it parse_files' own
    # ValueError escaped as a traceback.
    if args.workers is not None and args.workers < 1:
        _fail("--workers must be >= 1")

    builder = CodebaseGraphBuilder(
        copybook_paths=list(args.copybook_path or []),
        workers=args.workers,
        debug_lines=bool(getattr(args, "debug_lines", False)),
    )

    directories = [p for p in args.paths if os.path.isdir(p)]
    if directories and len(args.paths) > 1:
        print(
            "Error: give either one directory to walk or a list of files, " "not both",
            file=sys.stderr,
        )
        sys.exit(1)

    if directories:
        # `directories[0]` was just confirmed to be one, so
        # build_from_directory's NotADirectoryError cannot fire here and is
        # deliberately not caught -- a handler for it would be dead code.
        extensions = tuple(args.extensions) if args.extensions else None
        if extensions:
            return builder.build_from_directory(directories[0], extensions=extensions)
        return builder.build_from_directory(directories[0])

    # Anything that is not a directory is treated as a source file. A path
    # that does not exist is recorded in `errors` and `unresolved` (never as
    # a program), and the command then exits 2, so a mistyped name surfaces
    # instead of quietly shrinking the graph (#325).
    return builder.build(list(args.paths))


def _exit_on_graph_errors(graph: Any) -> None:
    """Exit 2, like ``batch``, when any input file failed: missing, unreadable
    or parsed with errors (#325). The output was already written."""
    if not graph.errors:
        return
    for error in graph.errors:
        if error.get("error") == "no such file or directory":
            print(f"error: no such file or directory: {error['path']}", file=sys.stderr)
    print(
        f"warning: {len(graph.errors)} file(s) failed (see the JSON output's "
        "errors); the graph is incomplete",
        file=sys.stderr,
    )
    sys.exit(2)


def _cmd_codebase_graph(args: argparse.Namespace) -> None:
    graph = _build_graph(args)

    if args.output_format == "dot":
        _verbatim_out(graph.to_dot(), getattr(args, "output", None))
    elif args.output_format == "mermaid":
        _verbatim_out(graph.to_mermaid(), getattr(args, "output", None))
    else:
        _json_out(graph.to_dict(), args.compact, getattr(args, "output", None))
    _exit_on_graph_errors(graph)


# -- Subcommand: copybook-impact ----------------------------------------------


def _build_copybook_impact_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "copybook-impact",
        help="Answer 'can I safely change this copybook?': every program that "
        "COPYs it, directly or through a nesting chain",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser copybook-impact CUSTREC ./src "
            "--copybook-path ./copybooks\n"
            "  cobol-parser copybook-impact CUSTREC.CPY prog1.cbl prog2.cbl"
        ),
    )
    p.add_argument("member", help="Copybook member name, file name or path")
    p.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="One directory to walk, or any number of COBOL source files",
    )
    p.add_argument(
        "--extension",
        action="append",
        dest="extensions",
        metavar="EXT",
        help="Source extension to walk for, repeatable "
        "(default: .cbl, .cob, .cobol)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Worker processes for the batch parse (default: chosen by size)",
    )
    _add_compact_arg(p)
    _add_copybook_args(p)
    _add_output_arg(p)
    _add_debug_lines_arg(p)
    p.set_defaults(func=_cmd_copybook_impact)


def _cmd_copybook_impact(args: argparse.Namespace) -> None:
    from ...analysis.codebase import CopybookImpactAnalyzer

    graph = _build_graph(args)
    report = CopybookImpactAnalyzer(graph).analyze(args.member)

    _json_out(report.to_dict(), args.compact, getattr(args, "output", None))
    _exit_on_graph_errors(graph)


# -- Subcommand: call-check ---------------------------------------------------


def _build_call_check_parser(subparsers: argparse._SubParsersAction) -> None:
    from ...analysis.call_interface import SEVERITIES

    p = subparsers.add_parser(
        "call-check",
        help="Check every CALL against the interface of the program it reaches, "
        "across files: argument count, BY VALUE/REFERENCE, byte lengths, "
        "usages and RETURNING",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser call-check ./src\n"
            "  cobol-parser call-check ./src --copybook-path ./copybooks "
            "--fail-on error\n"
            "  cobol-parser call-check CALLER.cbl SUBPGM.cbl --format text\n"
            "\n"
            "Exit codes:\n"
            "  0  the run completed (findings or not)\n"
            "  2  a file was missing or failed to parse; the report is incomplete\n"
            "  3  --fail-on was given and a finding at or above it was reported"
        ),
    )
    p.add_argument(
        "paths",
        nargs="+",
        metavar="PATH",
        help="One directory to walk, or any number of COBOL source files",
    )
    p.add_argument(
        "--extension",
        action="append",
        dest="extensions",
        metavar="EXT",
        help="Source extension to walk for, repeatable "
        "(default: .cbl, .cob, .cobol)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Worker processes for the batch parse (default: chosen by size)",
    )
    p.add_argument(
        "--min-severity",
        choices=list(SEVERITIES),
        default="info",
        help="Drop findings below this severity from the output (default: info)",
    )
    p.add_argument(
        "--fail-on",
        choices=[*SEVERITIES, "never"],
        default="never",
        help="Exit 3 when a finding at or above this severity was reported "
        "(default: never)",
    )
    p.add_argument(
        "--format",
        choices=["json", "text", "sarif"],
        default="json",
        dest="output_format",
        help="json (default), one 'file:line: severity: [kind] message' "
        "line per finding plus a summary, or a SARIF 2.1.0 log (GitHub code "
        "scanning, IDE problem panes)",
    )
    _add_compact_arg(p)
    _add_copybook_args(p)
    _add_output_arg(p)
    _add_debug_lines_arg(p)
    p.set_defaults(func=_cmd_call_check)


def _program_files(args: argparse.Namespace) -> list[str]:
    """The source files named on the command line: the files given, or every
    program under the one directory given (the codebase-graph rule)."""
    from ...analysis.codebase import DEFAULT_PROGRAM_EXTENSIONS

    directories = [p for p in args.paths if os.path.isdir(p)]
    if directories and len(args.paths) > 1:
        _fail("give either one directory to walk or a list of files, not both")
    if not directories:
        missing = [p for p in args.paths if not os.path.exists(p)]
        for path in missing:
            print(f"error: no such file or directory: {path}", file=sys.stderr)
        if missing:
            sys.exit(2)
        return list(args.paths)
    extensions = tuple(args.extensions or DEFAULT_PROGRAM_EXTENSIONS)
    wanted = {(e if e.startswith(".") else f".{e}").lower() for e in extensions}
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(directories[0]):
        dirnames.sort()
        for filename in sorted(filenames):
            if os.path.splitext(filename)[1].lower() in wanted:
                found.append(os.path.join(dirpath, filename))
    return found


def _cmd_call_check(args: argparse.Namespace) -> None:
    from ...analysis.call_interface import SEVERITIES, CallInterfaceChecker

    if args.workers is not None and args.workers < 1:
        _fail("--workers must be >= 1")
    files = _program_files(args)
    report = CallInterfaceChecker(
        copybook_paths=list(args.copybook_path or []),
        workers=args.workers,
        debug_lines=bool(getattr(args, "debug_lines", False)),
    ).check_files(files)

    cutoff = SEVERITIES.index(args.min_severity)
    report.findings = [
        f for f in report.findings if SEVERITIES.index(f.severity) <= cutoff
    ]
    # Like lint: --fail-on judges the findings shown, not those filtered out.
    worst = report.worst_severity()
    if args.output_format == "text":
        _text_out(report.to_text(), getattr(args, "output", None))
    elif args.output_format == "sarif":
        from ...analysis.sarif import (
            call_check_notifications,
            call_check_results,
            sarif_log,
        )

        _json_out(
            sarif_log(call_check_results(report), call_check_notifications(report)),
            args.compact,
            getattr(args, "output", None),
        )
    else:
        _json_out(report.to_dict(), args.compact, getattr(args, "output", None))

    if report.errors:
        print(
            f"warning: {len(report.errors)} file(s) failed to parse cleanly; "
            "the report is incomplete",
            file=sys.stderr,
        )
    fail_on = getattr(args, "fail_on", "never")
    if (
        fail_on != "never"
        and worst is not None
        and SEVERITIES.index(worst) <= SEVERITIES.index(fail_on)
    ):
        sys.exit(3)
    if report.errors:
        sys.exit(2)
