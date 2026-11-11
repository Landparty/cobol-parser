"""Single-program analyzer subcommands."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ...parser import parse_cobol
from .._common import (
    _DIALECT_MAP,
    _add_compact_arg,
    _add_copybook_args,
    _add_define_args,
    _add_dialect_arg,
    _add_encoding_arg,
    _add_error_recovery_arg,
    _add_min_clone_statements_arg,
    _add_output_arg,
    _add_profiling_args,
    _add_program_arg,
    _add_source_format_args,
    _emit_report,
    _fail,
    _get_error_recovery,
    _json_out,
    _loc,
    _parse_defines,
    _parse_or_fail,
    _parse_result_or_fail,
    _read_source,
    _source_format_kwargs,
    _text_out,
)


def _cmd_analyze(args: argparse.Namespace) -> None:
    from ...analysis.value_tracker import DynamicCallAnalyzer

    ast, prof = _parse_or_fail(args)

    analyzer = DynamicCallAnalyzer()
    analyzer.analyze(ast)

    # Collect dynamic call information
    calls = []
    for stmt in ast.find_all_by_type("CallStatement"):
        entry: dict[str, Any] = {
            "called_program": stmt.called_program,
            "is_dynamic": stmt.is_dynamic,
        }
        if stmt.is_dynamic:
            entry["possible_values"] = stmt.possible_values
            # DynamicCallAnalyzer marks a value set it could not fully
            # resolve (an untracked identifier MOVE source, ...) so the
            # list must not be presented as exhaustive.
            if stmt.get_metadata("possible_values_incomplete"):
                entry["possible_values_incomplete"] = True
        calls.append(entry)

    _emit_report({"calls": calls}, args, prof, ast)


# -- Subcommand: unused-variables ---------------------------------------------


def _build_unused_variables_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "unused-variables",
        help="Detect DATA DIVISION items never referenced in PROCEDURE DIVISION",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser unused-variables program.cbl\n"
            "  cobol-parser unused-variables program.cbl --copybook-path ./copybooks "
            "--exclude-copybook-variables"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p, strict_flag=True)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    _add_program_arg(p)
    p.add_argument(
        "--exclude-copybook-variables",
        action="store_true",
        help=(
            "Exclude unused items that originated from an expanded COPY "
            "statement. Only takes effect together with --copybook-path "
            "(copybook origin is determined by diffing declared items "
            "against an unexpanded parse of the same source); a no-op "
            "otherwise, with a warning on stderr."
        ),
    )
    p.set_defaults(func=_cmd_unused_variables)


def _parse_without_copybook_expansion(args: argparse.Namespace) -> Any:
    """Parse *args.file* the same way ``_do_parse`` does, but never
    expanding COPY statements.

    Used by ``_cmd_unused_variables`` to determine which declared data
    items came from a copybook: ``expand_copybooks``'s own
    ``preserve_source_locations`` line-tracking is not implemented (see
    ``UnusedVariableAnalyzer``'s docstring), so provenance is instead
    determined by set-difference -- names declared in the expanded AST but
    not in this unexpanded one must have come from an expanded COPY.
    """
    source = _read_source(args.file, getattr(args, "encoding", None))
    dialect = _DIALECT_MAP[args.dialect]
    error_recovery = _get_error_recovery(args)
    defines = _parse_defines(getattr(args, "define", []))

    if defines:
        from ...preprocess import preprocess_conditional_compilation

        source = preprocess_conditional_compilation(
            source, defines, warnings=[], keep_source_format_directives=True
        )

    parse_kwargs: dict[str, Any] = {
        "dialect": dialect,
        "error_recovery": error_recovery,
        **_source_format_kwargs(args),
    }
    return parse_cobol(source, filename=args.file, **parse_kwargs)


def _cmd_unused_variables(args: argparse.Namespace) -> None:
    from ...analysis.unused_variables import (
        UnusedVariableAnalyzer,
        collect_declared_items,
    )

    result, prof = _parse_result_or_fail(args)
    ast = result.ast

    copybook_paths = getattr(args, "copybook_path", [])
    exclude_copybook = getattr(args, "exclude_copybook_variables", False)
    copybook_item_names: set[str] | None = None

    if copybook_paths:
        unexpanded_result = _parse_without_copybook_expansion(args)
        if unexpanded_result.ast is None:
            print(
                f"warning: {args.file} could not be parsed without copybook "
                "expansion; copybook-origin detection disabled",
                file=sys.stderr,
            )
        else:
            # `ast` is already narrowed when --program named a unit; narrow
            # the unexpanded parse the same way, or another unit's own
            # declaration of a name would subtract from this one's set.
            local_root = unexpanded_result.ast
            wanted = getattr(args, "program", None)
            if wanted:
                local_root = local_root.find_program_unit(wanted) or local_root
            local_names = {
                item.name.upper() for item in collect_declared_items(local_root)
            }
            expanded_names = {item.name.upper() for item in collect_declared_items(ast)}
            copybook_item_names = expanded_names - local_names
    elif exclude_copybook:
        print(
            "warning: --exclude-copybook-variables has no effect without "
            "--copybook-path",
            file=sys.stderr,
        )

    analyzer = UnusedVariableAnalyzer()
    report = analyzer.analyze(
        ast,
        include_copybook_variables=not exclude_copybook,
        copybook_item_names=copybook_item_names,
    )

    # Locations count lines of the copybook-expanded text; _emit_report
    # stamps where each item really is, the way lint does.
    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: program-flow -------------------------------------------------


def _build_program_flow_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "program-flow",
        help="Display program control flow graph (paragraphs, PERFORM, GO TO, CALL)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser program-flow program.cbl\n"
            "  cobol-parser program-flow program.cbl --format mermaid"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    p.add_argument(
        "--format",
        choices=["json", "mermaid", "dot"],
        default="json",
        metavar="FORMAT",
        help="Output format: json (default), mermaid (Mermaid flowchart), or dot (Graphviz DOT)",
    )
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p, strict_flag=True)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    _add_program_arg(p)
    p.set_defaults(func=_cmd_program_flow)


def _cmd_program_flow(args: argparse.Namespace) -> None:
    from ...analysis.program_flow import ProgramFlowAnalyzer

    ast, prof = _parse_or_fail(args)

    analyzer = ProgramFlowAnalyzer()
    report = analyzer.analyze(ast)

    fmt = getattr(args, "format", "json")
    output_path = getattr(args, "output", None)

    if prof is not None and fmt != "json":
        # Text flowchart formats have nowhere to embed the profiling dict;
        # dropping it silently would make --profile look like a no-op.
        print(
            "warning: --profile metrics are only included in --format json "
            "output; ignoring for --format " + fmt,
            file=sys.stderr,
        )

    if fmt == "mermaid":
        from ...generators.flowchart import FlowchartOptions, MermaidFlowchartGenerator

        gen = MermaidFlowchartGenerator()
        _text_out(gen.generate(report, FlowchartOptions()), output_path)
    elif fmt == "dot":
        from ...generators.flowchart import DotFlowchartGenerator, FlowchartOptions

        gen = DotFlowchartGenerator()  # type: ignore[assignment]
        _text_out(gen.generate(report, FlowchartOptions()), output_path)
    else:
        _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: recursion-check -----------------------------------------------


def _cmd_recursion_check(args: argparse.Namespace) -> None:
    from ...analysis.recursion_risk import RecursionRiskAnalyzer

    ast, prof = _parse_or_fail(args)

    report = RecursionRiskAnalyzer().analyze(ast)

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: health ---------------------------------------------------------


def _cmd_health(args: argparse.Namespace) -> None:
    from ...analysis.technical_debt import TechnicalDebtAnalyzer

    result, prof = _parse_result_or_fail(args)
    ast = result.ast

    # A partial AST is a quiet one: a file that mostly failed to parse used
    # to grade "A". With the error count the grade is withheld (#397).
    report = TechnicalDebtAnalyzer().analyze(ast, parse_error_count=len(result.errors))

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: redundancy ---------------------------------------------------


def _build_redundancy_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "redundancy",
        help=(
            "Report dead code, unused variables and duplicate-paragraph "
            "clone groups, with a structural digest per paragraph"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser redundancy program.cbl\n"
            "  cobol-parser redundancy program.cbl --min-clone-statements 5"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p, strict_flag=True)
    _add_program_arg(p)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    _add_min_clone_statements_arg(p)
    p.set_defaults(func=_cmd_redundancy)


def _cmd_redundancy(args: argparse.Namespace) -> None:
    from ...analysis.redundancy import RedundancyAnalyzer

    ast, prof = _parse_or_fail(args)

    report = RedundancyAnalyzer().analyze(
        ast, min_clone_statements=max(1, args.min_clone_statements)
    )

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: language-env -------------------------------------------------


def _cmd_language_env(args: argparse.Namespace) -> None:
    from ...analysis.language_env_analyzer import LanguageEnvironmentAnalyzer
    from ...analysis.value_tracker import DynamicCallAnalyzer

    ast, _prof = _parse_or_fail(args)

    # Populate possible_values on dynamic CALLs before LE analysis
    DynamicCallAnalyzer().analyze(ast)

    analyzer = LanguageEnvironmentAnalyzer()
    report = analyzer.analyze(ast)

    _emit_report(report.to_dict(), args, ast=ast)


# -- Subcommand: ims-dli ------------------------------------------------------


def _cmd_ims_dli(args: argparse.Namespace) -> None:
    from ...analysis.ims_segment_analyzer import IMSSegmentAnalyzer

    ast, _prof = _parse_or_fail(args)

    analyzer = IMSSegmentAnalyzer()
    dli_calls = analyzer.analyze(ast)
    all_segments = analyzer.get_all_segment_names(dli_calls)
    entry_points_raw = analyzer.get_entry_points(ast)

    calls_out = [
        {
            "interface": c.interface,
            "function_code": c.function_code,
            "function_code_var": c.function_code_var,
            "pcb_name": c.pcb_name,
            "io_area_name": c.io_area_name,
            "ssa_names": c.ssa_names,
            "segment_names": c.segment_names,
            "primary_segment": c.primary_segment,
            "location": _loc(c.location),
        }
        for c in dli_calls
    ]

    entry_points_out = [
        {
            "entry_name": ep.entry_name,
            "pcb_names": ep.pcb_names,
            "location": _loc(ep.location),
        }
        for ep in entry_points_raw
    ]

    output: dict[str, Any] = {
        "is_ims_program": ast.has_ims() or ast.uses_ims_interface(),
        "entry_points": entry_points_out,
        "dli_call_count": len(calls_out),
        "all_segments": all_segments,
        "dli_calls": calls_out,
    }

    _emit_report(output, args, ast=ast)


# -- Subcommand: data-items ---------------------------------------------------


def _cmd_data_items(args: argparse.Namespace) -> None:
    from ...layout.offsets import compute_program_data_items

    args._wrap_copybook_fragment = True
    ast, prof = _parse_or_fail(args)
    if ast.data_division is None:
        # Nothing to lay out: say so rather than print `"items": []` and
        # exit 0, which reads as "this file declares no data".
        _fail(f"{args.file}: no DATA DIVISION found; no data items to report")

    output = compute_program_data_items(ast)

    _emit_report(output, args, prof, ast)


# -- Subcommand: program-signature --------------------------------------------


def _cmd_program_signature(args: argparse.Namespace) -> None:
    """Report the calling interface of every program unit in the file.

    Unlike the other analyzer subcommands, this one defaults to reporting
    *every* unit rather than the outermost: the question it answers is "what
    may a caller call in this file, and with what", and a caller may target a
    contained program as readily as the outermost one. Reporting only the
    outermost would hide the other entry points from exactly the consumer
    that needs them.

    ``--program`` still narrows, via the shared parse path, for a caller that
    knows which unit it means.
    """
    from ...analysis.program_signature import extract_signatures

    ast, prof = _parse_or_fail(args)

    signatures = extract_signatures(ast)
    _emit_report(
        {"signatures": [s.to_dict() for s in signatures]},
        args,
        prof,
        ast,
    )


# -- Subcommand: xref ---------------------------------------------------------


def _cmd_xref(args: argparse.Namespace) -> None:
    from ...analysis.xref import XrefAnalyzer

    result, prof = _parse_result_or_fail(args)
    ast = result.ast

    report = XrefAnalyzer().analyze(ast)
    # A COPY member the parser could not expand leaves every field it
    # declares looking undeclared; the parse warning that says so belongs
    # next to the ``undefined`` list it explains.
    for warning in getattr(result, "warnings", None) or []:
        if "COPY" in str(warning).upper():
            report.caveats.append(f"parse warning: {warning}")

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: business-rules -------------------------------------------------


def _build_business_rules_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "business-rules",
        help="Extract the program's business rules: decisions (IF / EVALUATE / "
        "SEARCH as decision tables), validations and calculations, with the "
        "data each one reads and writes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser business-rules program.cbl\n"
            "  cobol-parser business-rules program.cbl --format text\n"
            "  cobol-parser business-rules program.cbl --include-technical"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    p.add_argument(
        "--format",
        choices=["json", "text"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )
    p.add_argument(
        "--include-technical",
        action="store_true",
        help="Also report technical rules (file status, EOF, SQLCODE / "
        "EIBRESP checks, ...), which are counted but left out by default",
    )
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p, strict_flag=True)
    _add_program_arg(p)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    p.set_defaults(func=_cmd_business_rules)


def _cmd_business_rules(args: argparse.Namespace) -> None:
    from ...analysis.business_rules import BusinessRuleExtractor

    ast, prof = _parse_or_fail(args)

    report = BusinessRuleExtractor(
        include_technical=getattr(args, "include_technical", False)
    ).analyze(ast)

    if getattr(args, "output_format", "json") == "text":
        if prof is not None:
            print(
                "warning: --profile metrics are only included in --format json "
                "output; ignoring for --format text",
                file=sys.stderr,
            )
        _text_out(report.to_text(), getattr(args, "output", None))
        return

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: le-info ------------------------------------------------------


def _build_le_info_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "le-info",
        help=(
            "Show the call signature of IBM Language Environment services and "
            "COBOL intrinsic functions"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser le-info                # the whole catalogue\n"
            "  cobol-parser le-info CEEDAYS        # one service\n"
            "  cobol-parser le-info NUMVAL-C       # one intrinsic function\n"
            "  cobol-parser le-info --kind service # every catalogued service\n"
        ),
    )
    p.add_argument(
        "name",
        nargs="*",
        help=(
            "Service or function name to describe (case-insensitive). "
            "Omit for the whole catalogue."
        ),
    )
    p.add_argument(
        "--kind",
        choices=["service", "function", "all"],
        default="all",
        help=(
            "Restrict the answer to LE callable services or to intrinsic "
            "functions (default: all)"
        ),
    )
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_le_info)


def _cmd_le_info(args: argparse.Namespace) -> None:
    """Emit the LE/intrinsic call-signature catalogue as JSON.

    Unlike every other subcommand this one reads no source file -- it is the
    static knowledge behind an editor tooltip ("what does this CALL need?"),
    which is why it is a catalogue dump rather than an analysis. The output
    therefore carries no ``source_file`` identification header.
    """
    from ...dialects.le_signatures import (
        catalog_to_dict,
        intrinsic_signature,
        le_service_signature,
        services_without_signature,
    )

    catalog = catalog_to_dict()

    if not args.name:
        output: dict[str, Any] = {
            "catalog_version": catalog["catalog_version"],
            "reference": catalog["reference"],
        }
        if args.kind in ("service", "all"):
            output["services"] = catalog["services"]
            output["services_without_signature"] = catalog["services_without_signature"]
        if args.kind in ("function", "all"):
            output["functions"] = catalog["functions"]
        _json_out(output, args.compact, args.output)
        return

    uncatalogued = {entry["name"]: entry for entry in services_without_signature()}
    entries: list[dict[str, Any]] = []
    for raw_name in args.name:
        name = raw_name.strip().upper()
        service = le_service_signature(name) if args.kind != "function" else None
        function = intrinsic_signature(name) if args.kind != "service" else None
        if service is not None:
            entries.append(service.to_dict())
        elif function is not None:
            entries.append(function.to_dict())
        elif args.kind != "function" and name in uncatalogued:
            # Known to the dialect, but no signature to report. Said out loud
            # rather than dropped: "we don't have this one" and "that is not
            # an LE service" are different answers.
            entries.append(
                {
                    "name": name,
                    "kind": "service",
                    "category": uncatalogued[name]["category"],
                    "summary": None,
                    "parameters": None,
                    "notes": ["No call signature is catalogued for this service."],
                }
            )
        else:
            _fail(
                f"Unknown name: {raw_name!r}. Run `cobol-parser le-info` with "
                f"no arguments to list everything the catalogue knows."
            )

    _json_out(
        {
            "catalog_version": catalog["catalog_version"],
            "reference": catalog["reference"],
            "entries": entries,
        },
        args.compact,
        args.output,
    )


# -- Shared analyzer subcommand builder ---------------------------------------


def _build_analyzer_parser(
    subparsers: argparse._SubParsersAction,
    name: str,
    help: str,
    func: Any,
    *,
    profiling: bool = False,
    examples: str,
) -> None:
    """Build a standard analyzer subcommand.

    Shared by the analyzer subcommands whose argument set is identical:
    a ``file`` positional plus the common compact/free-form/dialect/
    error-recovery/copybook/define/output flags. ``profiling=True`` also adds
    the profiling flags. ``examples`` is a "cobol-parser <name> ..." example
    block (one or two lines, no leading "Example(s):" label) shown in --help.
    """
    label = "Example:" if "\n" not in examples else "Examples:"
    p = subparsers.add_parser(
        name,
        help=help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"{label}\n{examples}",
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p, strict_flag=True)
    _add_program_arg(p)
    _add_define_args(p)
    _add_output_arg(p)
    if profiling:
        _add_profiling_args(p)
    p.set_defaults(func=func)


# -- The standard analyzer subcommands ----------------------------------------


@dataclass(frozen=True)
class AnalyzerCommand:
    """One single-file analyzer subcommand with the standard flag set **A**.

    Either *analyzer* names ``(module in cobolparser.analysis, class,
    method)``: the handler parses the file, runs ``Class().method(ast)`` and
    emits the report's ``to_dict()``. Or *handler* is a ``_cmd_*`` function,
    for a subcommand that does more than that.
    """

    help: str
    examples: str
    profiling: bool = False
    analyzer: tuple[str, str, str] | None = None
    handler: Callable[[argparse.Namespace], None] | None = None

    def run(self, args: argparse.Namespace) -> None:
        if self.handler is not None:
            self.handler(args)
            return
        assert self.analyzer is not None
        module_name, class_name, method = self.analyzer
        module = importlib.import_module(f"...analysis.{module_name}", __package__)
        ast, prof = _parse_or_fail(args)
        report = getattr(getattr(module, class_name)(), method)(ast)
        _emit_report(report.to_dict(), args, prof, ast)


#: Every subcommand built by ``_build_analyzer_parser``, by name.
#: ``_build_parser`` adds each one with ``_add_analyzer`` (in its own place
#: in the subcommand order).
ANALYZERS: dict[str, AnalyzerCommand] = {
    "analyze": AnalyzerCommand(
        help="Analyze dynamic CALL targets in COBOL source",
        handler=_cmd_analyze,
        profiling=True,
        examples="  cobol-parser analyze program.cbl",
    ),
    "dead-code": AnalyzerCommand(
        help="Detect unreachable paragraphs/sections (dead code)",
        analyzer=("dead_code", "DeadCodeAnalyzer", "analyze"),
        profiling=True,
        examples="  cobol-parser dead-code program.cbl",
    ),
    "recursion-check": AnalyzerCommand(
        help="Detect PERFORM/GO TO cycles and self-recursive CALLs that risk an "
        "infinite loop",
        handler=_cmd_recursion_check,
        profiling=True,
        examples="  cobol-parser recursion-check program.cbl",
    ),
    "complexity": AnalyzerCommand(
        help="Compute per-paragraph cyclomatic complexity and maintainability metrics",
        analyzer=("complexity", "ComplexityAnalyzer", "analyze"),
        profiling=True,
        examples="  cobol-parser complexity program.cbl",
    ),
    "health": AnalyzerCommand(
        help="Compute a composite technical-debt score (complexity, redundancy, "
        "control-flow smells, size) with a top-offenders breakdown",
        handler=_cmd_health,
        profiling=True,
        examples="  cobol-parser health program.cbl",
    ),
    "io-sequence": AnalyzerCommand(
        help="Validate file I/O operation ordering (OPEN/READ/WRITE/CLOSE lifecycle)",
        analyzer=("io_sequence", "IOSequenceAnalyzer", "analyze"),
        examples="  cobol-parser io-sequence program.cbl",
    ),
    "move-type-check": AnalyzerCommand(
        help="Check MOVE statement data category compatibility",
        analyzer=("move_type_checker", "MoveTypeChecker", "check"),
        examples="  cobol-parser move-type-check program.cbl",
    ),
    "linkage-check": AnalyzerCommand(
        help="Validate LINKAGE SECTION items against CALL/ENTRY USING clauses",
        analyzer=("linkage_checker", "LinkageChecker", "check"),
        examples="  cobol-parser linkage-check program.cbl",
    ),
    "language-env": AnalyzerCommand(
        help="Detect COBOL intrinsic functions and IBM Language Environment service calls",
        handler=_cmd_language_env,
        examples="  cobol-parser language-env program.cbl",
    ),
    "ims-dli": AnalyzerCommand(
        help="Extract IMS DLI segment references from CBLTDLI/AIBTDLI/CEETDLI calls",
        handler=_cmd_ims_dli,
        examples="  cobol-parser ims-dli program.cbl",
    ),
    "dclgen-check": AnalyzerCommand(
        help="Cross-check EXEC SQL host variables against the DCLGEN DECLARE TABLE "
        "columns they bind to (type, scale, precision, length, sign, null "
        "indicator)",
        analyzer=("dclgen_check", "DclgenChecker", "check"),
        profiling=True,
        examples="  cobol-parser dclgen-check program.cbl",
    ),
    "data-items": AnalyzerCommand(
        help="Compute byte offset, byte length, REDEFINES chains, and level-88 "
        "condition values for every data item in the program",
        handler=_cmd_data_items,
        profiling=True,
        examples="  cobol-parser data-items program.cbl",
    ),
    "program-signature": AnalyzerCommand(
        help="Report a program's calling interface: every entry point's USING "
        "operands joined to their LINKAGE declarations, with the direction "
        "the callee uses each one in",
        handler=_cmd_program_signature,
        profiling=True,
        examples="  cobol-parser program-signature SUBPGM.cbl\n"
        "  cobol-parser program-signature SUBPGM.cbl --copybook-path ./copybooks",
    ),
    "xref": AnalyzerCommand(
        help="Cross-reference listing: every symbol's definition and every "
        "reference to it, with the role each reference plays",
        handler=_cmd_xref,
        profiling=True,
        examples="  cobol-parser xref program.cbl",
    ),
    "sql-cics-check": AnalyzerCommand(
        help="Lint embedded SQL and CICS: unchecked SQLCODE, dynamic SQL built by "
        "concatenation, hardcoded credentials, CICS commands with no RESP or "
        "HANDLE CONDITION",
        analyzer=("sql_cics_lint", "SqlCicsAnalyzer", "analyze"),
        profiling=True,
        examples="  cobol-parser sql-cics-check program.cbl",
    ),
}


def _add_analyzer(subparsers: argparse._SubParsersAction, name: str) -> None:
    """Add the ANALYZERS entry *name* as a subcommand."""
    spec = ANALYZERS[name]
    _build_analyzer_parser(
        subparsers,
        name,
        spec.help,
        spec.handler if spec.handler is not None else spec.run,
        profiling=spec.profiling,
        examples=spec.examples,
    )
