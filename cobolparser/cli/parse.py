"""Command-line interface for parsing COBOL source files."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, NoReturn

from ..models.program import CobolDivision, CobolParagraph, CobolProgram, CobolSection
from ..parser import parse_cobol
from ..plugins.core import DialectType, ErrorRecoveryMode

_SUBCOMMANDS = frozenset(
    {
        "parse",
        "batch",
        "tokenize",
        "preprocess",
        "expand",
        "analyze",
        "dead-code",
        "program-flow",
        "generate-tests",
        "io-sequence",
        "move-type-check",
        "linkage-check",
        "language-env",
        "ims-dli",
    }
)

_DIALECT_MAP = {"ibm-enterprise": DialectType.IBM_ENTERPRISE}


# -- Shared argument helpers --------------------------------------------------


def _add_dialect_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--dialect",
        choices=["ibm-enterprise"],
        default="ibm-enterprise",
        help="COBOL dialect (default: ibm-enterprise)",
    )


def _add_compact_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Output compact (single-line) JSON instead of pretty-printed",
    )


def _add_free_form_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--free-form",
        action="store_true",
        help="Treat source as free-form COBOL",
    )


def _add_error_recovery_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--error-recovery",
        choices=["fail-fast", "collect-all"],
        default="collect-all",
        help="Error recovery mode (default: collect-all)",
    )


def _add_copybook_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--copybook-path",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory to search for copybooks (repeatable)",
    )


def _add_define_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--define",
        action="append",
        default=[],
        metavar="SYMBOL[=VALUE]",
        help="Define a conditional compilation symbol (repeatable)",
    )


def _add_output_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--output",
        "-o",
        default=None,
        metavar="FILE",
        help="Write output to FILE instead of stdout",
    )


def _add_profiling_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Profile the parse and include timing/memory metrics in output",
    )
    parser.add_argument(
        "--profile-top-n",
        type=int,
        default=20,
        metavar="N",
        help="Number of top functions to include in profiling output (default: 20)",
    )
    parser.add_argument(
        "--profile-output",
        default=None,
        metavar="PATH",
        help="Write cProfile binary to PATH (.prof for single file, directory for batch)",
    )


def _get_error_recovery(args: argparse.Namespace) -> ErrorRecoveryMode:
    mode_map = {
        "fail-fast": ErrorRecoveryMode.FAIL_FAST,
        "collect-all": ErrorRecoveryMode.COLLECT_ALL,
    }
    return mode_map[args.error_recovery]


def _parse_defines(defines: list[str]) -> dict[str, str] | None:
    if not defines:
        return None
    symbols: dict[str, str] = {}
    for d in defines:
        if "=" in d:
            key, value = d.split("=", 1)
            symbols[key.strip()] = value.strip()
        else:
            symbols[d.strip()] = "TRUE"
    return symbols


def _read_source(filepath: str) -> str:
    try:
        with open(filepath, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        _fail(f"File not found: {filepath}")
    except UnicodeDecodeError:
        _fail(f"Cannot read file (not valid UTF-8): {filepath}")
    except OSError as e:
        _fail(f"Cannot read file: {e}")


def _json_out(data: Any, compact: bool, output_path: str | None = None) -> None:
    indent = None if compact else 2
    text = json.dumps(data, indent=indent)
    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(text)
                f.write("\n")
        except OSError as e:
            _fail(f"Cannot write output file: {e}")
    else:
        print(text)


def _text_out(text: str, output_path: str | None = None) -> None:
    """Write *text* to *output_path* or stdout."""
    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(text)
                if not text.endswith("\n"):
                    f.write("\n")
        except OSError as e:
            _fail(f"Cannot write output file: {e}")
    else:
        print(text)


# -- Subcommand: parse -------------------------------------------------------


def _build_parse_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser("parse", help="Parse a COBOL source file to AST JSON")
    p.add_argument("file", help="Path to the COBOL source file")
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Dot-separated AST path (e.g., procedure.MAIN-LOGIC.display)",
    )
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    p.add_argument(
        "--errors",
        action="store_true",
        help="Include parse errors and warnings in output",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Include parse statistics in output",
    )
    p.add_argument(
        "--find-type",
        default=None,
        metavar="NODE_TYPE",
        help="Find all AST nodes of the given type (e.g., MoveStatement)",
    )
    _add_profiling_args(p)
    p.set_defaults(func=_cmd_parse)


def _do_parse(args: argparse.Namespace) -> tuple[Any, Any]:
    """Shared parse logic used by parse and analyze subcommands."""
    from ..profiling import ProfilerContext

    source = _read_source(args.file)
    dialect = _DIALECT_MAP[args.dialect]
    error_recovery = _get_error_recovery(args)

    copybook_paths = getattr(args, "copybook_path", [])
    defines = _parse_defines(getattr(args, "define", []))
    enable_profiling = getattr(args, "profile", False)
    top_n = getattr(args, "profile_top_n", 20)
    prof_output = getattr(args, "profile_output", None)

    if defines:
        from ..preprocess import preprocess_conditional_compilation

        source = preprocess_conditional_compilation(source, defines)

    parse_kwargs: dict[str, Any] = {
        "dialect": dialect,
        "error_recovery": error_recovery,
        "free_form": getattr(args, "free_form", False),
    }

    if not enable_profiling:
        if copybook_paths:
            from ..preprocess.copybook_expander import parse_cobol_with_expansion

            result = parse_cobol_with_expansion(
                source,
                filename=args.file,
                copybook_paths=copybook_paths,
                **parse_kwargs,
            )
        else:
            result = parse_cobol(source, filename=args.file, **parse_kwargs)
        return result, None

    # With profiling
    ctx = ProfilerContext(top_n=top_n, prof_output=prof_output)
    with ctx:
        if copybook_paths:
            from ..preprocess.copybook_expander import parse_cobol_with_expansion

            result = parse_cobol_with_expansion(
                source,
                filename=args.file,
                copybook_paths=copybook_paths,
                **parse_kwargs,
            )
        else:
            result = parse_cobol(source, filename=args.file, **parse_kwargs)
    assert ctx.result is not None
    return result, ctx.result


def _cmd_parse(args: argparse.Namespace) -> None:
    result, prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    # --find-type: query AST by node type
    if args.find_type:
        matched = result.ast.find_all_by_type(args.find_type)
        output: Any = [n.to_dict() for n in matched]
        if prof is not None:
            output = {"result": output, "profiling": prof.to_dict()}
        _json_out(output, args.compact, getattr(args, "output", None))
        return

    # Resolve path or output full AST
    if args.path:
        output = _resolve_path(result.ast, args.path)
    else:
        output = result.ast.to_dict()

    # Wrap with errors/stats if requested
    if args.errors or args.stats:
        wrapper: dict[str, Any] = {"ast": output}
        if args.errors:
            wrapper["errors"] = [str(e) for e in result.errors]
            wrapper["warnings"] = result.warnings
        if args.stats:
            wrapper["statistics"] = {
                "lines_processed": result.statistics.lines_processed,
                "tokens_processed": result.statistics.tokens_processed,
                "parse_time_seconds": result.statistics.parse_time_seconds,
                "memory_peak_mb": result.statistics.memory_peak_mb,
            }
        output = wrapper

    if prof is not None:
        if isinstance(output, dict):
            output["profiling"] = prof.to_dict()
        else:
            output = {"result": output, "profiling": prof.to_dict()}

    _json_out(output, args.compact, getattr(args, "output", None))


# -- Subcommand: batch --------------------------------------------------------


def _build_batch_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser("batch", help="Parse multiple COBOL files in parallel")
    p.add_argument("files", nargs="*", help="Paths to COBOL source files")
    p.add_argument(
        "--glob",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Glob pattern to collect source files (repeatable, e.g. 'src/**/*.cbl')",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Number of worker processes (default: CPU count)",
    )
    p.add_argument(
        "--encoding",
        default="utf-8",
        help="File encoding (default: utf-8)",
    )
    _add_compact_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_output_arg(p)
    p.add_argument(
        "--errors",
        action="store_true",
        help="Include parse errors and warnings per file",
    )
    p.add_argument(
        "--stats",
        action="store_true",
        help="Include parse statistics per file",
    )
    _add_profiling_args(p)
    p.set_defaults(func=_cmd_batch)


def _cmd_batch(args: argparse.Namespace) -> None:
    import glob as _glob
    from pathlib import Path as _Path

    from ..batch import parse_files

    # Combine explicit file args with --glob expansions.
    # Each glob's results are sorted so output order is deterministic
    # regardless of filesystem traversal order.
    file_list: list[str] = list(args.files)
    for pattern in args.glob:
        expanded = sorted(_glob.glob(pattern, recursive=True))
        if not expanded:
            print(
                f"warning: glob pattern {pattern!r} matched no files", file=sys.stderr
            )
        file_list.extend(expanded)

    # Deduplicate while preserving order.  Use the resolved (absolute,
    # canonical) path as the dedup key so that ./a.cbl, a.cbl, and
    # /abs/path/a.cbl all map to the same file and are not parsed twice.
    seen: set[str] = set()
    unique_files: list[str] = []
    for f in file_list:
        key = str(_Path(f).resolve())
        if key not in seen:
            seen.add(key)
            unique_files.append(f)

    if not unique_files:
        _fail("No input files specified. Provide file arguments or use --glob.")

    dialect = _DIALECT_MAP[args.dialect]
    error_recovery = _get_error_recovery(args)

    enable_profiling = getattr(args, "profile", False)
    top_n = getattr(args, "profile_top_n", 20)
    prof_output = getattr(args, "profile_output", None)

    if prof_output is not None and prof_output.endswith(".prof"):
        _fail(
            "--profile-output in batch mode must be a directory path, not a .prof file"
        )

    results = parse_files(
        unique_files,
        workers=args.workers,
        error_recovery=error_recovery,
        dialect=dialect,
        encoding=args.encoding,
        enable_profiling=enable_profiling,
        top_n=top_n,
        prof_output=prof_output,
    )

    output = []
    for br in results:
        entry: dict[str, Any] = {"path": str(br.path)}
        if br.read_error:
            entry["read_error"] = br.read_error
        elif br.result is not None:
            entry["success"] = br.result.success
            if br.result.ast is not None:
                entry["ast"] = br.result.ast.to_dict()
            if args.errors:
                entry["errors"] = [str(e) for e in br.result.errors]
                entry["warnings"] = br.result.warnings
            if args.stats and br.result.statistics:
                entry["statistics"] = {
                    "lines_processed": br.result.statistics.lines_processed,
                    "tokens_processed": br.result.statistics.tokens_processed,
                    "parse_time_seconds": br.result.statistics.parse_time_seconds,
                    "memory_peak_mb": br.result.statistics.memory_peak_mb,
                }
            if enable_profiling and br.profiling is not None:
                entry["profiling"] = br.profiling.to_dict()
        output.append(entry)

    _json_out(output, args.compact, getattr(args, "output", None))


# -- Subcommand: tokenize -----------------------------------------------------


def _build_tokenize_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser("tokenize", help="Tokenize a COBOL source file")
    p.add_argument("file", help="Path to the COBOL source file")
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_tokenize)


def _cmd_tokenize(args: argparse.Namespace) -> None:
    from ..lexer import CobolLexer

    source = _read_source(args.file)
    dialect = _DIALECT_MAP[args.dialect]

    lexer = CobolLexer(source, args.file, dialect, free_form=args.free_form)
    tokens = lexer.tokenize()

    output = [
        {
            "type": t.type.name,
            "value": t.value,
            "line": t.location.line,
            "column": t.location.column,
        }
        for t in tokens
    ]

    _json_out(output, args.compact, getattr(args, "output", None))


# -- Subcommand: preprocess ---------------------------------------------------


def _build_preprocess_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "preprocess", help="Preprocess fixed-format COBOL to free-form"
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_free_form_arg(p)
    _add_define_args(p)
    p.add_argument(
        "--strip-directives",
        action="store_true",
        help="Strip PROCESS/CBL compiler directives before normalizing",
    )
    p.set_defaults(func=_cmd_preprocess)


def _cmd_preprocess(args: argparse.Namespace) -> None:
    from ..preprocess import (
        normalize_fixed_format,
        preprocess_conditional_compilation,
        strip_compiler_directives,
    )

    source = _read_source(args.file)

    if args.strip_directives:
        source = strip_compiler_directives(source)

    defines = _parse_defines(args.define)
    if defines:
        source = preprocess_conditional_compilation(source, defines)

    if not args.free_form:
        source = normalize_fixed_format(source.splitlines())

    print(source, end="")


# -- Subcommand: expand -------------------------------------------------------


def _build_expand_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser("expand", help="Expand COPY statements (copybooks)")
    p.add_argument("file", help="Path to the COBOL source file")
    _add_copybook_args(p)
    _add_compact_arg(p)
    p.add_argument(
        "--max-depth",
        type=int,
        default=100,
        metavar="N",
        help="Maximum copybook nesting depth (default: 100)",
    )
    _add_define_args(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_expand)


def _cmd_expand(args: argparse.Namespace) -> None:
    from ..preprocess import preprocess_conditional_compilation
    from ..preprocess.copybook_expander import expand_copybooks

    source = _read_source(args.file)

    defines = _parse_defines(args.define)
    if defines:
        source = preprocess_conditional_compilation(source, defines)

    result = expand_copybooks(
        source,
        copybook_paths=args.copybook_path,
        max_nesting_depth=args.max_depth,
        process_conditionals=bool(defines),
        defined_symbols=defines,
    )

    _json_out(result.to_dict(), args.compact, getattr(args, "output", None))


# -- Subcommand: analyze ------------------------------------------------------


def _build_analyze_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "analyze", help="Analyze dynamic CALL targets in COBOL source"
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    p.set_defaults(func=_cmd_analyze)


def _cmd_analyze(args: argparse.Namespace) -> None:
    from ..analysis.value_tracker import DynamicCallAnalyzer

    result, prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    analyzer = DynamicCallAnalyzer()
    analyzer.analyze(result.ast)

    # Collect dynamic call information
    calls = []
    for stmt in result.ast.find_all_by_type("CallStatement"):
        entry: dict[str, Any] = {
            "called_program": stmt.called_program,
            "is_dynamic": stmt.is_dynamic,
        }
        if stmt.is_dynamic:
            entry["possible_values"] = stmt.possible_values
        calls.append(entry)

    output: dict[str, Any] = {"calls": calls}
    if prof is not None:
        output["profiling"] = prof.to_dict()
    _json_out(output, args.compact, getattr(args, "output", None))


# -- Subcommand: dead-code ----------------------------------------------------


def _build_dead_code_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "dead-code", help="Detect unreferenced paragraphs/sections (dead code)"
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    p.set_defaults(func=_cmd_dead_code)


def _cmd_dead_code(args: argparse.Namespace) -> None:
    from ..analysis.dead_code import DeadCodeAnalyzer

    result, prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    analyzer = DeadCodeAnalyzer()
    report = analyzer.analyze(result.ast)

    output: dict[str, Any] = report.to_dict()
    if prof is not None:
        output["profiling"] = prof.to_dict()
    _json_out(output, args.compact, getattr(args, "output", None))


# -- Subcommand: program-flow -------------------------------------------------


def _build_program_flow_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "program-flow",
        help="Display program control flow graph (paragraphs, PERFORM, GO TO, CALL)",
    )
    p.add_argument("file", help="Path to the COBOL source file")
    p.add_argument(
        "--format",
        choices=["json", "mermaid", "dot"],
        default="json",
        metavar="FORMAT",
        help="Output format: json (default), mermaid (Mermaid flowchart), or dot (Graphviz DOT)",
    )
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    p.set_defaults(func=_cmd_program_flow)


def _cmd_program_flow(args: argparse.Namespace) -> None:
    from ..analysis.program_flow import ProgramFlowAnalyzer

    result, prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    analyzer = ProgramFlowAnalyzer()
    report = analyzer.analyze(result.ast)

    fmt = getattr(args, "format", "json")
    output_path = getattr(args, "output", None)

    if fmt == "mermaid":
        from ..generators.flowchart import FlowchartOptions, MermaidFlowchartGenerator

        gen = MermaidFlowchartGenerator()
        _text_out(gen.generate(report, FlowchartOptions()), output_path)
    elif fmt == "dot":
        from ..generators.flowchart import DotFlowchartGenerator, FlowchartOptions

        gen = DotFlowchartGenerator()  # type: ignore[assignment]
        _text_out(gen.generate(report, FlowchartOptions()), output_path)
    else:
        output: dict[str, Any] = report.to_dict()
        if prof is not None:
            output["profiling"] = prof.to_dict()
        _json_out(output, args.compact, output_path)


# -- Subcommand: generate-tests -----------------------------------------------


def _build_generate_tests_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "generate-tests",
        help="Generate CobolCheck unit tests from COBOL source",
    )
    p.add_argument("file", help="Path to the COBOL source file")
    p.add_argument(
        "--output",
        "-o",
        default=None,
        metavar="FILE",
        help="Output .cut file path (default: stdout)",
    )
    p.add_argument(
        "--strategy",
        action="append",
        default=None,
        choices=["paragraph", "branch", "boundary"],
        help="Coverage strategy to use (repeatable; default: all)",
    )
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    p.set_defaults(func=_cmd_generate_tests)


def _cmd_generate_tests(args: argparse.Namespace) -> None:
    result, _prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    from ..analysis.coverage_analyzer import CoverageAnalyzer
    from ..analysis.test_plan import TestPlanGenerator
    from ..generators.cobolcheck import CobolCheckGenerator

    analyzer = CoverageAnalyzer()
    coverage_map = analyzer.analyze(result.ast)

    planner = TestPlanGenerator(strategies=args.strategy)
    test_plan = planner.generate(coverage_map)

    generator = CobolCheckGenerator()
    output = generator.generate(test_plan)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Generated {test_plan.total_test_cases} test cases -> {args.output}")
    else:
        print(output, end="")


# -- Subcommand: io-sequence --------------------------------------------------


def _build_io_sequence_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "io-sequence",
        help="Validate file I/O operation ordering (OPEN/READ/WRITE/CLOSE lifecycle)",
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_io_sequence)


def _cmd_io_sequence(args: argparse.Namespace) -> None:
    from ..analysis.io_sequence import IOSequenceAnalyzer

    result, _prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    analyzer = IOSequenceAnalyzer()
    report = analyzer.analyze(result.ast)

    _json_out(report.to_dict(), args.compact, getattr(args, "output", None))


# -- Subcommand: move-type-check ----------------------------------------------


def _build_move_type_check_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "move-type-check",
        help="Check MOVE statement data category compatibility",
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_move_type_check)


def _cmd_move_type_check(args: argparse.Namespace) -> None:
    from ..analysis.move_type_checker import MoveTypeChecker

    result, _prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    checker = MoveTypeChecker()
    report = checker.check(result.ast)

    _json_out(report.to_dict(), args.compact, getattr(args, "output", None))


# -- Subcommand: linkage-check ------------------------------------------------


def _build_linkage_check_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "linkage-check",
        help="Validate LINKAGE SECTION items against CALL/ENTRY USING clauses",
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_linkage_check)


def _cmd_linkage_check(args: argparse.Namespace) -> None:
    from ..analysis.linkage_checker import LinkageChecker

    result, _prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    checker = LinkageChecker()
    report = checker.check(result.ast)

    _json_out(report.to_dict(), args.compact, getattr(args, "output", None))


# -- Subcommand: language-env -------------------------------------------------


def _build_language_env_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "language-env",
        help="Detect COBOL intrinsic functions and IBM Language Environment service calls",
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_language_env)


def _cmd_language_env(args: argparse.Namespace) -> None:
    from ..analysis.language_env_analyzer import LanguageEnvironmentAnalyzer
    from ..analysis.value_tracker import DynamicCallAnalyzer

    result, _prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    # Populate possible_values on dynamic CALLs before LE analysis
    DynamicCallAnalyzer().analyze(result.ast)

    analyzer = LanguageEnvironmentAnalyzer()
    report = analyzer.analyze(result.ast)

    _json_out(report.to_dict(), args.compact, getattr(args, "output", None))


# -- Subcommand: ims-dli ------------------------------------------------------


def _build_ims_dli_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "ims-dli",
        help="Extract IMS DLI segment references from CBLTDLI/AIBTDLI/CEETDLI calls",
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_ims_dli)


def _cmd_ims_dli(args: argparse.Namespace) -> None:
    from ..analysis.ims_segment_analyzer import IMSSegmentAnalyzer

    result, _prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    analyzer = IMSSegmentAnalyzer()
    dli_calls = analyzer.analyze(result.ast)
    all_segments = analyzer.get_all_segment_names(dli_calls)

    calls_out = []
    for c in dli_calls:
        loc = c.location
        calls_out.append(
            {
                "interface": c.interface,
                "function_code": c.function_code,
                "function_code_var": c.function_code_var,
                "pcb_name": c.pcb_name,
                "io_area_name": c.io_area_name,
                "ssa_names": c.ssa_names,
                "segment_names": c.segment_names,
                "primary_segment": c.primary_segment,
                "location": ({"line": loc.line, "column": loc.column} if loc else None),
            }
        )

    output: dict[str, Any] = {
        "dli_call_count": len(calls_out),
        "all_segments": all_segments,
        "dli_calls": calls_out,
    }

    _json_out(output, args.compact, getattr(args, "output", None))


# -- Path resolution ---------------------------------------------------------


def _resolve_path(
    program: CobolProgram, path: str
) -> dict[str, Any] | list[dict[str, Any]]:
    """Resolve a dot-separated path against the AST.

    Path forms:
      division                          -> division dict
      division.section_or_paragraph     -> section/paragraph dict
      division.section.paragraph        -> paragraph within a section
      division.paragraph.statement_type -> filtered statement list
    """
    parts = [p.strip() for p in path.split(".")]
    # Drop empty components from leading/trailing dots
    parts = [p for p in parts if p]
    if not parts:
        _fail("Empty path")
    if len(parts) > 3:
        _fail(f"Path too deep: {path!r} (max 3 components: division.section.paragraph)")

    # --- Level 1: division ---
    div_name = parts[0].upper()
    division = program.get_division(div_name)
    if division is None:
        available = [d.division_name for d in program.divisions]
        _fail(f"Division {parts[0]!r} not found. " f"Available: {', '.join(available)}")

    if len(parts) == 1:
        return division.to_dict()

    # --- Level 2: section or paragraph ---
    target_name = parts[1].upper()
    node = division.get_section_by_name(target_name)
    if node is None:
        available = _list_section_and_paragraph_names(division)
        _fail(
            f"{parts[1]!r} not found in {div_name} division. "
            f"Available: {', '.join(available) if available else '(none)'}"
        )

    if len(parts) == 2:
        return node.to_dict()

    # --- Level 3: paragraph within section, OR statement type filter ---
    level3 = parts[2].upper()

    # If level 2 resolved to a section, try paragraph name first
    if isinstance(node, CobolSection):
        paragraph = node.get_paragraph_by_name(level3)
        if paragraph is not None:
            return paragraph.to_dict()
        # Fall through to statement type filter across all section paragraphs

    # Statement type filter
    stmt_type = level3
    statements: list[Any] = []
    if isinstance(node, CobolParagraph):
        statements = node.statements
    elif isinstance(node, CobolSection):
        for para in node.paragraphs:
            statements.extend(para.statements)

    matched = [s for s in statements if s.statement_type.upper() == stmt_type]
    if not matched:
        available_types = sorted({s.statement_type for s in statements})
        hints: list[str] = []
        if available_types:
            hints.append(f"statement types: {', '.join(available_types)}")
        if isinstance(node, CobolSection) and node.paragraphs:
            para_names = [p.paragraph_name for p in node.paragraphs]
            hints.append(f"paragraphs: {', '.join(para_names)}")
        hint_str = "; ".join(hints) if hints else "(none)"
        _fail(f"No {parts[2]!r} found in {parts[1]!r}. " f"Available: {hint_str}")
    return [s.to_dict() for s in matched]


def _list_section_and_paragraph_names(division: CobolDivision) -> list[str]:
    names: list[str] = []
    for section in division._sections.values():
        names.append(section.section_name or "(unnamed)")
    for para in division.paragraphs:
        names.append(para.paragraph_name)
    return names


def _fail(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


# -- Top-level parser with subcommands ----------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    from .. import __version__

    parser = argparse.ArgumentParser(
        prog="cobol-parser",
        description="Parse, tokenize, preprocess, and analyze COBOL source files.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    subparsers = parser.add_subparsers(dest="command")

    _build_parse_parser(subparsers)
    _build_batch_parser(subparsers)
    _build_tokenize_parser(subparsers)
    _build_preprocess_parser(subparsers)
    _build_expand_parser(subparsers)
    _build_analyze_parser(subparsers)
    _build_dead_code_parser(subparsers)
    _build_program_flow_parser(subparsers)
    _build_generate_tests_parser(subparsers)
    _build_io_sequence_parser(subparsers)
    _build_move_type_check_parser(subparsers)
    _build_linkage_check_parser(subparsers)
    _build_language_env_parser(subparsers)
    _build_ims_dli_parser(subparsers)

    return parser


def main() -> None:
    # Backward compatibility: if the first non-flag argument is not a known
    # subcommand, assume the user is using the legacy syntax and prepend "parse".
    argv = sys.argv[1:]
    if argv:
        first_positional = None
        for arg in argv:
            if not arg.startswith("-"):
                first_positional = arg
                break
        if first_positional is not None and first_positional not in _SUBCOMMANDS:
            argv = ["parse", *argv]
    else:
        argv = ["parse", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    args.func(args)
