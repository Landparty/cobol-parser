"""Field-lineage subcommands: lineage, field-impact, widen-check."""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from .._common import (
    _add_compact_arg,
    _add_copybook_args,
    _add_define_args,
    _add_dialect_arg,
    _add_encoding_arg,
    _add_error_recovery_arg,
    _add_output_arg,
    _add_program_arg,
    _add_source_format_args,
    _defined_symbol_pairs,
    _fail,
    _json_out,
    _parse_or_fail,
    _severity_at_least,
    _source_format_kwargs,
    _text_out,
)

# -- Subcommand: lineage ------------------------------------------------------


def _add_direction_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--direction",
        choices=["forward", "backward"],
        default="forward",
        help="forward: what the value feeds; backward: where it comes from "
        "(default: forward)",
    )


def _build_lineage_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "lineage",
        help="Field-level data lineage inside one program: every MOVE, "
        "computation, READ INTO / WRITE FROM, CALL argument and SQL host "
        "variable as a value flow, and which file / table / CALL fields "
        "reach which",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser lineage program.cbl --copybook-path ./copybooks\n"
            "  cobol-parser lineage program.cbl --format text\n"
            "  cobol-parser lineage program.cbl --field WS-AMOUNT "
            "--direction backward"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    p.add_argument(
        "--field",
        default=None,
        metavar="NAME",
        help="Report only what this data item feeds (or, with --direction "
        "backward, is fed by) inside the program",
    )
    _add_direction_args(p)
    p.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p, strict_flag=True)
    _add_program_arg(p)
    _add_define_args(p)
    _add_output_arg(p)
    p.add_argument(
        "--summary-limit",
        type=_summary_limit,
        default=None,
        metavar="N",
        help="Most port-to-port flows the summary lists (default: 10000; "
        "'all' for no limit, 0 for none)",
    )
    p.set_defaults(func=_cmd_lineage)


def _summary_limit(value: str) -> int | str:
    if value.strip().lower() == "all":
        return "all"
    try:
        limit = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected a number or 'all', got {value!r}"
        ) from None
    if limit < 0:
        raise argparse.ArgumentTypeError("must be 0 or more")
    return limit


def _cmd_lineage(args: argparse.Namespace) -> None:
    from ...analysis.field_lineage import FieldFlowAnalyzer, apply_source_map

    ast, _prof = _parse_or_fail(args)
    limit = getattr(args, "summary_limit", None)
    analyzer = (
        FieldFlowAnalyzer()
        if limit is None
        else FieldFlowAnalyzer(summary_limit=None if limit == "all" else limit)
    )
    report = apply_source_map(
        analyzer.analyze(ast), getattr(args, "_expansion_source_map", None)
    )
    text = getattr(args, "output_format", "json") == "text"
    if args.field:
        from ...analysis.lineage_graph import LineageGraph

        result = LineageGraph([report]).impact(
            args.field, program=report.program_id, direction=args.direction
        )
        if text:
            _text_out(result.to_text(), getattr(args, "output", None))
        else:
            _json_out(result.to_dict(), args.compact, getattr(args, "output", None))
        return
    if text:
        _text_out(report.to_text(), getattr(args, "output", None))
        return
    _json_out(report.to_dict(), args.compact, getattr(args, "output", None))


# -- Subcommand: field-impact -------------------------------------------------

_COBOL_EXTENSIONS = (".cbl", ".cob", ".cobol")


def _build_field_impact_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "field-impact",
        help="Field-level impact across programs: every program, table and "
        "dataset field a value reaches (or comes from), joined through "
        "JCL datasets, CALL arguments and DB2 columns",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exactly one of FIELD, --table or --dataset names the start.\n\n"
            "Examples:\n"
            "  cobol-parser field-impact HV-TRAN-AMOUNT ./cobol --program CHKCLR "
            "--copybook-path ./copybook\n"
            "  cobol-parser field-impact --table TRANSACTION_HIST.AMOUNT ./cobol "
            "--direction backward\n"
            "  cobol-parser field-impact --dataset BANK.PROD.TRAN.DAILY ./cobol "
            "--jcl ./jcl --proc-path ./proc --format text\n\n"
            "Exit status: 0 when the start was found (hits or not); 1 when no "
            "source produced a report, the start matches nothing (the report "
            "is still printed), or the arguments are wrong."
        ),
    )
    p.add_argument(
        "targets",
        nargs="+",
        metavar="[FIELD] PATH",
        help="The data item to start from (omit it with --table / --dataset), "
        "then COBOL source files or directories to walk",
    )
    p.add_argument(
        "--program",
        default=None,
        metavar="NAME",
        help="PROGRAM-ID that owns FIELD (default: every program with a field "
        "of that name)",
    )
    p.add_argument("--table", default=None, metavar="TABLE.COLUMN")
    p.add_argument("--dataset", default=None, metavar="DSN")
    _add_direction_args(p)
    p.add_argument(
        "--depth",
        type=int,
        default=None,
        metavar="N",
        help="Joins between programs a path may cross (default: unlimited)",
    )
    _add_binding_args(p)
    p.add_argument(
        "--key-relationships",
        action="store_true",
        help="Also report candidate key relationships: values from one "
        "dataset or table used to look up records in another",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Worker processes for the parse (default: chosen by size)",
    )
    p.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )
    _add_compact_arg(p)
    _add_copybook_args(p)
    _add_output_arg(p)
    _add_source_format_args(p)
    _add_define_args(p)
    p.set_defaults(func=_cmd_field_impact)


def _add_binding_args(p: argparse.ArgumentParser) -> None:
    """``--jcl`` / ``--proc-path`` / ``--bindings``: how programs' DDs are
    bound to datasets, for the commands built on ``LineageGraph``."""
    p.add_argument(
        "--jcl",
        action="append",
        default=[],
        metavar="PATH",
        help="JCL file or directory whose DD statements bind programs to "
        "datasets (repeatable; needs jcl-parser installed)",
    )
    p.add_argument(
        "--proc-path",
        action="append",
        default=None,
        metavar="DIR",
        help="Folder of cataloged PROCs (NAME.prc / NAME.jcl), or a JCLLIB "
        "base, used to expand EXEC PROC= steps in --jcl (repeatable, searched "
        "in order)",
    )
    p.add_argument(
        "--bindings",
        default=None,
        metavar="FILE.json",
        help='Bindings computed elsewhere: {"bindings": [{"program", "ddname", '
        '"dataset", "job"?, "step"?}], "passthroughs": [...]}',
    )


def _lineage_reports(
    args: argparse.Namespace, targets: list[str]
) -> tuple[list[dict[str, Any]], list[str], str | None]:
    """Every lineage report under *targets*, the problems (files that
    produced none) and the unresolved-copybook caveat (``None`` when every
    COPY expanded); exits when there is no report at all."""
    from ...analysis.lineage_graph import reports_from_scan
    from ...scan import ScanOptions, scan_files

    files = _cobol_files(targets)
    source_format = _source_format_kwargs(args)
    scan = scan_files(
        files,
        ScanOptions(
            analyzers=("lineage",),
            copybook_paths=tuple(args.copybook_path or []),
            free_form=bool(source_format["free_form"]),
            preprocess_fixed=source_format["preprocess_fixed"],
            debug_lines=bool(source_format.get("debug_lines", False)),
            defined_symbols=_defined_symbol_pairs(args),
            abend_programs=tuple(getattr(args, "abend_programs", None) or ()),
        ),
        workers=args.workers,
    )
    reports, problems = reports_from_scan(scan)
    if not reports:
        for problem in problems:
            print(problem, file=sys.stderr)
        _fail("no COBOL program under the given paths produced a lineage report")
    return reports, problems, _unresolved_copybook_caveat(scan)


def _unresolved_copybook_caveat(scan: Any) -> str | None:
    """One caveat naming the program files whose copybooks did not all
    expand, or ``None``.

    A field declared in a member that was not expanded is invisible to the
    lineage graph, so field-impact and widen-check silently covered fewer
    programs (GenApp: 2 of the 21 that COPY LGCMAREA) with ``problems: []``.
    The MCP ``impact_of_change`` tool already says this; so does the CLI now.
    """
    files: list[str] = []
    members: list[str] = []
    for file_scan in scan.files:
        if file_scan.error is not None:
            continue  # already a problem of its own
        names = list(getattr(file_scan, "unexpanded_copybooks", None) or [])
        if not names and file_scan.copybook_error is None:
            continue
        files.append(os.path.basename(file_scan.path))
        for name in names:
            if name not in members:
                members.append(name)
    if not files:
        return None

    def _shown(items: list[str], limit: int) -> str:
        head = ", ".join(items[:limit])
        return head + (f", and {len(items) - limit} more" if len(items) > limit else "")

    named = f" (members: {_shown(members, 8)})" if members else ""
    return (
        f"copybooks not expanded in {len(files)} program file(s): "
        f"{_shown(files, 5)}{named}; field flows in those members are missing, "
        "so programs that use the field only through them are not reported -- "
        "pass --copybook-path DIR for the folders that hold them"
    )


def _missing_field_hint(copybook_caveat: str | None) -> str:
    """The "no such field" error's tail when copybooks went unexpanded: the
    field may well be declared in one of them."""
    if copybook_caveat is None:
        return ""
    return (
        "; it may be declared in a copybook that was not expanded -- " + copybook_caveat
    )


def _cobol_files(paths: list[str]) -> list[str]:
    files: list[str] = []
    for raw in paths:
        if os.path.isdir(raw):
            for root, _dirs, names in sorted(os.walk(raw)):
                files += [
                    os.path.join(root, n)
                    for n in sorted(names)
                    if n.lower().endswith(_COBOL_EXTENSIONS)
                ]
        else:
            files.append(raw)
    return files


def _json_rows(value: Any, key: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        _fail(f'--bindings: "{key}" must be a list of objects')
    for index, row in enumerate(value):
        if not isinstance(row, dict):
            _fail(f'--bindings: "{key}"[{index}] is not an object: {row!r}')
    return value


def _binding_rows(value: Any) -> list[dict[str, Any]]:
    """The usable ``--bindings`` rows. A row with no ``program`` or no
    ``dataset`` binds nothing (``cobol-parser jcl --bindings`` writes such
    rows for SYSOUT / DUMMY DDs and ``EXEC proc`` steps) and is skipped; a
    row that is not a binding at all is an error naming it."""
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(_json_rows(value, "bindings")):
        for field in ("program", "ddname", "dataset", "job", "step"):
            if row.get(field) is not None and not isinstance(row[field], str):
                _fail(
                    f'--bindings: "bindings"[{index}]: "{field}" must be a '
                    f"string: {row!r}"
                )
        if not row.get("ddname"):
            _fail(f'--bindings: "bindings"[{index}] has no "ddname": {row!r}')
        if row.get("program") and row.get("dataset"):
            rows.append(row)
    return rows


def _passthrough_rows(value: Any) -> list[dict[str, Any]]:
    rows = _json_rows(value, "passthroughs")
    for index, row in enumerate(rows):
        for field in ("input", "output"):
            if not isinstance(row.get(field), str) or not row[field]:
                _fail(
                    f'--bindings: "passthroughs"[{index}] needs a string '
                    f'"{field}": {row!r}'
                )
        ranges = row.get("aggregate_ranges") or []
        if not isinstance(ranges, list) or not all(
            isinstance(r, list)
            and len(r) == 2
            and all(isinstance(n, int) and not isinstance(n, bool) for n in r)
            for r in ranges
        ):
            _fail(
                f'--bindings: "passthroughs"[{index}]: "aggregate_ranges" must '
                f"be a list of [offset, length] pairs: {row!r}"
            )
    return rows


def _load_bindings(
    args: argparse.Namespace,
) -> tuple[list[Any], list[Any], list[str], list[str]]:
    """Bindings, pass-throughs, problems (files not read) and caveats (JCL
    steps whose flow could not be read)."""
    bindings: list[Any] = []
    passthroughs: list[Any] = []
    problems: list[str] = []
    caveats: list[str] = []
    if args.bindings:
        try:
            with open(args.bindings, encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError) as exc:
            _fail(f"--bindings could not be read: {exc}")
        if not isinstance(data, dict):
            _fail("--bindings must hold a JSON object")
        bindings += _binding_rows(data.get("bindings"))
        passthroughs += _passthrough_rows(data.get("passthroughs"))
    if args.jcl:
        from ...analysis.lineage_jcl import bindings_from_jobs, load_jobs

        try:
            jobs, problems = load_jobs(args.jcl, proc_path=args.proc_path)
        except ImportError:
            _fail("--jcl needs jcl-parser: pip install jcl-parser")
        found, carried = bindings_from_jobs(jobs, caveats)
        bindings += found
        passthroughs += carried
    return bindings, passthroughs, problems, caveats


def _cmd_field_impact(args: argparse.Namespace) -> None:
    from ...analysis.lineage_graph import LineageGraph

    starts = sum(bool(x) for x in (args.table, args.dataset))
    if starts > 1:
        _fail("give at most one of --table and --dataset")
    targets = list(args.targets)
    field_name = None if starts else targets.pop(0)
    if not targets:
        _fail("no COBOL sources given")
    if args.workers is not None and args.workers < 1:
        _fail("--workers must be >= 1")
    if args.depth is not None and args.depth < 0:
        _fail("--depth must be >= 0")

    reports, problems, copybook_caveat = _lineage_reports(args, targets)
    bindings, passthroughs, jcl_problems, jcl_caveats = _load_bindings(args)
    graph = LineageGraph(reports, bindings, passthroughs, join_caveats=jcl_caveats)

    if args.table:
        result = graph.impact_table(args.table, args.direction, args.depth)
    elif args.dataset:
        result = graph.impact_dataset(args.dataset, args.direction, args.depth)
    else:
        assert field_name is not None
        result = graph.impact(field_name, args.program, args.direction, args.depth)
    if copybook_caveat is not None:
        result.caveats.insert(0, copybook_caveat)

    relationships = graph.key_relationships() if args.key_relationships else []
    all_problems = problems + jcl_problems
    if args.output_format == "text":
        text = result.to_text()
        if relationships:
            text += "\nKey relationships:\n" + "".join(
                f"  {k.source} -> {k.key}  ({k.program} line {k.line})\n"
                for k in relationships
            )
        if graph.unjoined:
            text += "\nUnjoined:\n" + "".join(f"  - {u}\n" for u in graph.unjoined)
        if all_problems:
            text += "\nProblems:\n" + "".join(f"  - {p}\n" for p in all_problems)
        _text_out(text, getattr(args, "output", None))
    else:
        output = result.to_dict()
        output["graph"] = graph.to_dict()
        output["problems"] = all_problems
        if args.key_relationships:
            output["key_relationships"] = [k.to_dict() for k in relationships]
        _json_out(output, args.compact, getattr(args, "output", None))
    if not result.start_found:
        # The report above says so too; the exit code is for scripts.
        _fail(
            f"{', '.join(result.start)}: no such field in any report"
            + _missing_field_hint(copybook_caveat)
        )


# -- Subcommand: widen-check --------------------------------------------------


def _build_widen_check_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "widen-check",
        help="What a PICTURE change to one field breaks across programs: "
        "every receiver that truncates the new value, and every record, "
        "file, dataset, CALL and REDEFINES whose layout must change with it",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser widen-check CUST-ID --to '9(9)' ./cobol "
            "--copybook-path ./copybook\n"
            "  cobol-parser widen-check WS-AMT --to 'S9(11)V99' --usage COMP-3 "
            "./cobol --program PAYCALC --jcl ./jcl --format text\n\n"
            "A narrowing (--to smaller than today) is checked the other way: "
            "every field that feeds FIELD with more than the new PICTURE holds."
            "\n\nExit status:\n"
            "  0  checked (findings or not)\n"
            "  1  no source produced a report, FIELD matches nothing, or the "
            "arguments are wrong\n"
            "  3  --fail-on was given and a finding at or above it was reported"
        ),
    )
    p.add_argument("field", metavar="FIELD", help="The data item to change")
    p.add_argument(
        "targets",
        nargs="+",
        metavar="PATH",
        help="COBOL source files or directories to walk",
    )
    p.add_argument(
        "--to",
        required=True,
        dest="new_picture",
        metavar="PIC",
        help="The new PICTURE, e.g. '9(9)' or 'PIC S9(7)V99'",
    )
    p.add_argument(
        "--usage",
        default=None,
        dest="new_usage",
        metavar="USAGE",
        help="The new USAGE (default: the field keeps its own)",
    )
    p.add_argument(
        "--program",
        default=None,
        metavar="NAME",
        help="PROGRAM-ID that owns FIELD (default: every program with a field "
        "of that name)",
    )
    p.add_argument(
        "--depth",
        type=int,
        default=None,
        metavar="N",
        help="Joins between programs a value path may cross (default: unlimited)",
    )
    _add_binding_args(p)
    p.add_argument(
        "--min-severity",
        choices=["error", "warning", "info"],
        default="info",
        help="Report only findings at or above this severity (default: info)",
    )
    p.add_argument(
        "--fail-on",
        choices=["error", "warning", "info", "never"],
        default="never",
        help="Exit 3 when a reported finding is at or above this severity "
        "(default: never)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Worker processes for the parse (default: chosen by size)",
    )
    p.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )
    _add_compact_arg(p)
    _add_copybook_args(p)
    _add_output_arg(p)
    _add_source_format_args(p)
    _add_define_args(p)
    p.set_defaults(func=_cmd_widen_check)


def _cmd_widen_check(args: argparse.Namespace) -> None:
    from ...analysis.field_widening import FieldWideningAnalyzer
    from ...analysis.lineage_graph import LineageGraph

    targets = list(args.targets)
    field_name = args.field
    if args.workers is not None and args.workers < 1:
        _fail("--workers must be >= 1")
    if args.depth is not None and args.depth < 0:
        _fail("--depth must be >= 0")
    reports, problems, copybook_caveat = _lineage_reports(args, targets)
    bindings, passthroughs, jcl_problems, jcl_caveats = _load_bindings(args)
    graph = LineageGraph(reports, bindings, passthroughs, join_caveats=jcl_caveats)
    report = FieldWideningAnalyzer(graph).analyze(
        field_name,
        args.new_picture,
        program=args.program,
        new_usage=args.new_usage,
        depth=args.depth,
    )
    if copybook_caveat is not None:
        report.caveats.insert(0, copybook_caveat)
    report.findings = [
        f for f in report.findings if _severity_at_least(f.severity, args.min_severity)
    ]
    all_problems = problems + jcl_problems
    if args.output_format == "text":
        text = report.to_text()
        if all_problems:
            text += "Problems:\n" + "".join(f"  - {p}\n" for p in all_problems)
        _text_out(text, getattr(args, "output", None))
    else:
        output = report.to_dict()
        output["problems"] = all_problems
        _json_out(output, args.compact, getattr(args, "output", None))
    if not report.start_found:
        _fail(
            f"{field_name.upper()}: no such field in any report"
            + _missing_field_hint(copybook_caveat)
        )
    if not report.starts:
        _fail(f"{field_name.upper()}: nothing to check (see caveats)")
    worst = report.worst_severity()
    if (
        args.fail_on != "never"
        and worst is not None
        and _severity_at_least(worst, args.fail_on)
    ):
        sys.exit(3)
