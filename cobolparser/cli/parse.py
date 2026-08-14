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
        "gen-data",
        "gen-fixtures",
        "analyze",
        "dead-code",
        "unused-variables",
        "program-flow",
        "io-sequence",
        "move-type-check",
        "linkage-check",
        "language-env",
        "ims-dli",
        "data-items",
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


def _identification(
    args: argparse.Namespace, ast: CobolProgram | None = None
) -> dict[str, Any]:
    """Build the identification header included in every JSON output.

    Every JSON document the CLI emits starts with ``source_file`` (the input
    path as given on the command line) and, when the source was parsed,
    ``program_id`` (the PROGRAM-ID from the IDENTIFICATION DIVISION, or null
    if the program has none).
    """
    ident: dict[str, Any] = {"source_file": args.file}
    if ast is not None:
        ident["program_id"] = ast.program_name or None
    return ident


def _emit_report(
    data: dict[str, Any],
    args: argparse.Namespace,
    prof: Any = None,
    ast: CobolProgram | None = None,
) -> None:
    """Emit an analyzer report dict as JSON, splicing in profiling if present.

    The report is prefixed with the standard identification header so the
    output is self-describing (see :func:`_identification`).
    """
    output = {**_identification(args, ast), **data}
    if prof is not None:
        output["profiling"] = prof.to_dict()
    _json_out(output, args.compact, getattr(args, "output", None))


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

        conditional_warnings: list[str] = []
        source = preprocess_conditional_compilation(
            source, defines, warnings=conditional_warnings
        )
        for cw in conditional_warnings:
            print(f"warning: {cw}", file=sys.stderr)

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


def _stats_dict(stats: Any) -> dict[str, Any]:
    """Build the statistics output dict shared by the parse and batch commands."""
    return {
        "lines_processed": stats.lines_processed,
        "tokens_processed": stats.tokens_processed,
        "parse_time_seconds": stats.parse_time_seconds,
        "memory_peak_mb": stats.memory_peak_mb,
    }


def _parse_or_fail(args: argparse.Namespace) -> tuple[Any, Any]:
    """Parse *args.file* and return ``(ast, prof)``, failing if parsing fails.

    Shared parse-then-guard logic used by the parse and analyzer subcommands.
    On parse failure (``result.ast is None``) this calls ``_fail`` (which exits)
    with the standard "Parse failed for <file>" message.
    """
    result, prof = _do_parse(args)
    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))
    if result.errors:
        # Analyzer subcommands proceed on a partial AST, but the degradation
        # must be visible rather than silent.
        print(
            f"warning: {args.file} parsed with {len(result.errors)} error(s); "
            "analysis may be incomplete",
            file=sys.stderr,
        )
    return result.ast, prof


def _cmd_parse(args: argparse.Namespace) -> None:
    result, prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    # --find-type: query AST by node type
    if args.find_type:
        matched = result.ast.find_all_by_type(args.find_type)
        output: dict[str, Any] = {
            **_identification(args, result.ast),
            "node_type": args.find_type,
            "matches": [n.to_dict() for n in matched],
        }
        if prof is not None:
            output["profiling"] = prof.to_dict()
        _json_out(output, args.compact, getattr(args, "output", None))
        return

    # Resolve path or output full AST
    if args.path:
        output = {
            **_identification(args, result.ast),
            "path": args.path,
            "result": _resolve_path(result.ast, args.path),
        }
    elif args.errors or args.stats:
        output = {**_identification(args, result.ast), "ast": result.ast.to_dict()}
    else:
        # The AST dict already carries program_name; only the source file
        # needs to be spliced in for identification.
        output = {"source_file": args.file, **result.ast.to_dict()}

    if args.errors:
        output["errors"] = [str(e) for e in result.errors]
        output["warnings"] = result.warnings
    if args.stats:
        output["statistics"] = _stats_dict(result.statistics)

    if prof is not None:
        output["profiling"] = prof.to_dict()

    _json_out(output, args.compact, getattr(args, "output", None))

    # A recovered-but-errored parse must not report success to the shell:
    # scripts and CI gate on the exit code, and exiting 0 here silently
    # promoted every partial parse to a clean one.
    if result.errors:
        print(
            f"warning: parse of {args.file} completed with "
            f"{len(result.errors)} error(s); AST may be incomplete "
            "(re-run with --errors to include them in the JSON output)",
            file=sys.stderr,
        )
        sys.exit(2)


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
                entry["program_id"] = br.result.ast.program_name or None
                entry["ast"] = br.result.ast.to_dict()
            if args.errors:
                entry["errors"] = [str(e) for e in br.result.errors]
                entry["warnings"] = br.result.warnings
            if args.stats and br.result.statistics:
                entry["statistics"] = _stats_dict(br.result.statistics)
            if enable_profiling and br.profiling is not None:
                entry["profiling"] = br.profiling.to_dict()
        output.append(entry)

    _json_out(output, args.compact, getattr(args, "output", None))

    # Surface per-file failures in the process exit code — the batch JSON
    # already records them, but scripts gating on $? previously saw 0 even
    # when every file failed.
    failed = [
        br
        for br in results
        if br.read_error or (br.result is not None and not br.result.success)
    ]
    if failed:
        print(
            f"warning: {len(failed)} of {len(results)} file(s) failed to "
            "parse cleanly (see JSON output for details)",
            file=sys.stderr,
        )
        sys.exit(2)


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
    from ..lexer import _tokenize_source

    source = _read_source(args.file)
    dialect = _DIALECT_MAP[args.dialect]

    # Unified pipeline (M6): fixed-format source is normalized and lexed
    # free-form exactly like `cobol-parser parse`, with comment lines
    # preserved as COMMENT tokens. Lexer errors are ignored here, matching
    # the previous behavior of this subcommand (best-effort token dump).
    tokens, _errors, _warnings = _tokenize_source(
        source, args.file, dialect, free_form=args.free_form
    )

    output = {
        "source_file": args.file,
        "tokens": [
            {
                "type": t.type.name,
                "value": t.value,
                "line": t.location.line,
                "column": t.location.column,
            }
            for t in tokens
        ],
    }

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
        conditional_warnings: list[str] = []
        source = preprocess_conditional_compilation(
            source, defines, warnings=conditional_warnings
        )
        for cw in conditional_warnings:
            print(f"warning: {cw}", file=sys.stderr)

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
        conditional_warnings: list[str] = []
        source = preprocess_conditional_compilation(
            source, defines, warnings=conditional_warnings
        )
        for cw in conditional_warnings:
            print(f"warning: {cw}", file=sys.stderr)

    result = expand_copybooks(
        source,
        copybook_paths=args.copybook_path,
        max_nesting_depth=args.max_depth,
        process_conditionals=bool(defines),
        defined_symbols=defines,
    )

    _json_out(
        {"source_file": args.file, **result.to_dict()},
        args.compact,
        getattr(args, "output", None),
    )


# -- Subcommand: gen-data -----------------------------------------------------


def _build_gen_data_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "gen-data",
        help="Generate synthetic CSV test data from a copybook record layout",
    )
    p.add_argument("file", help="Path to the copybook (or COBOL source) file")
    p.add_argument(
        "--rows",
        "-n",
        type=int,
        default=10,
        metavar="N",
        help="Number of records to generate (default: 10)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="RNG seed for reproducible output (default: random, reported in --describe)",
    )
    p.add_argument(
        "--record",
        default=None,
        metavar="NAME",
        help="Level-01 record to generate from (default: the first in the copybook)",
    )
    p.add_argument(
        "--list-records",
        action="store_true",
        help="List the level-01 records in the copybook and exit",
    )
    p.add_argument(
        "--describe",
        action="store_true",
        help="Emit the resolved layout and rows as JSON instead of CSV",
    )
    p.add_argument(
        "--header-style",
        choices=["short", "path"],
        default="short",
        help="CSV header naming: short field name (default) or dotted record path",
    )
    p.add_argument(
        "--include-filler",
        action="store_true",
        help="Include FILLER items as columns (skipped by default)",
    )
    p.add_argument(
        "--include-redefines",
        action="store_true",
        help="Include REDEFINES fields, which alias bytes another column covers",
    )
    p.add_argument(
        "--no-expand-occurs",
        action="store_true",
        help="Emit only the first occurrence of each OCCURS table",
    )
    p.add_argument(
        "--max-occurs",
        type=int,
        default=None,
        metavar="N",
        help="Cap the occurrences expanded per OCCURS table",
    )
    p.add_argument(
        "--no-semantic",
        action="store_true",
        help="Disable field-name value heuristics (NAME, CITY, DATE, ...)",
    )
    p.add_argument(
        "--ignore-values",
        action="store_true",
        help="Ignore VALUE clauses and level-88 values when generating",
    )
    p.add_argument(
        "--unique",
        action="append",
        default=[],
        metavar="FIELD",
        help="Field whose column must hold distinct values (repeatable)",
    )
    p.add_argument(
        "--blank-rate",
        type=float,
        default=0.0,
        metavar="RATE",
        help="Fraction of cells (0.0-1.0) to leave blank (default: 0.0)",
    )
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_gen_data)


def _cmd_gen_data(args: argparse.Namespace) -> None:
    from ..generators.copybook_data import (
        CopybookDataGenerator,
        CopybookLayoutError,
        DataGeneratorOptions,
        parse_copybook_records,
    )

    source = _read_source(args.file)

    if args.list_records:
        try:
            records = parse_copybook_records(source, filename=args.file)
        except CopybookLayoutError as exc:
            _fail(str(exc))
        _json_out(
            {
                "source_file": args.file,
                "records": [
                    {"name": r.name, "level": r.level, "size": r.calculate_size()}
                    for r in records
                ],
            },
            args.compact,
            getattr(args, "output", None),
        )
        return

    try:
        options = DataGeneratorOptions(
            rows=args.rows,
            seed=args.seed,
            include_filler=args.include_filler,
            include_redefines=args.include_redefines,
            expand_occurs=not args.no_expand_occurs,
            max_occurs=args.max_occurs,
            respect_values=not args.ignore_values,
            use_condition_values=not args.ignore_values,
            semantic_hints=not args.no_semantic,
            header_style=args.header_style,
            unique_fields=tuple(args.unique),
            blank_rate=args.blank_rate,
        )
    except ValueError as exc:
        _fail(str(exc))

    try:
        dataset = CopybookDataGenerator(options).generate_from_source(
            source, filename=args.file, record=args.record
        )
    except CopybookLayoutError as exc:
        _fail(str(exc))

    if args.describe:
        _json_out(
            {"source_file": args.file, **dataset.to_dict()},
            args.compact,
            getattr(args, "output", None),
        )
        return

    output_path = getattr(args, "output", None)
    if output_path:
        # Write through the csv module so embedded newlines round-trip.
        try:
            dataset.write_csv(output_path)
        except OSError as e:
            _fail(f"Cannot write output file: {e}")
    else:
        print(dataset.to_csv(), end="")


def _build_gen_fixtures_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "gen-fixtures",
        help="Generate program-scoped test fixtures (boundary mocks/asserts) for a COBOL program",
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_copybook_args(p)
    p.add_argument(
        "--callee-path",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory to search for a CALLed program's source, to resolve "
        "CALL argument direction (repeatable)",
    )
    p.add_argument(
        "--rows",
        "-n",
        type=int,
        default=10,
        metavar="N",
        help="Rows to generate per IN file/SQL boundary (default: 10)",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        metavar="N",
        help="RNG seed for reproducible output (default: random, reported in the bundle)",
    )
    p.add_argument(
        "--max-occurs",
        type=int,
        default=None,
        metavar="N",
        help="Cap the occurrences expanded per OCCURS table",
    )
    p.add_argument(
        "--scenarios",
        choices=["happy", "branches", "all"],
        default="happy",
        help="Scenario strategy: happy (one unconstrained scenario, default), "
        "branches (one scenario per reachable/satisfiable branch arm, merged "
        "where possible), all (branches + fixed empty-input/error-status/"
        "boundary-values families)",
    )
    p.add_argument(
        "--format",
        choices=["json", "csv-dir"],
        default="json",
        help="Output format: one JSON bundle, or one CSV per file boundary "
        "under --output DIR (default: json)",
    )
    p.add_argument(
        "--list-boundaries",
        action="store_true",
        help="List every boundary (category/key/paragraph/line/direction) and exit",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 2 if the bundle has any unresolved boundary/argument",
    )
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_gen_fixtures)


def _cmd_gen_fixtures(args: argparse.Namespace) -> None:
    from ..generators.data.errors import ProgramLayoutError
    from ..generators.program_fixtures import ProgramFixtureGenerator

    generator = ProgramFixtureGenerator()
    copybook_paths = args.copybook_path or None
    callee_paths = args.callee_path or None

    if args.list_boundaries:
        try:
            _, _, report = generator.analyze_from_file(
                args.file, copybook_paths=copybook_paths, callee_paths=callee_paths
            )
        except ProgramLayoutError as exc:
            _fail(str(exc))
        _json_out(
            {
                "source_file": args.file,
                "boundaries": [
                    {
                        "category": b.ref.category,
                        "key": b.ref.key,
                        "paragraph": b.ref.paragraph,
                        "line": b.ref.line,
                        "direction": b.direction,
                    }
                    for b in report.boundaries
                ],
            },
            args.compact,
            getattr(args, "output", None),
        )
        return

    try:
        from ..generators.data.options import DataGeneratorOptions

        generator = ProgramFixtureGenerator(
            DataGeneratorOptions(rows=args.rows, max_occurs=args.max_occurs)
        )
        bundle = generator.generate_with_scenarios_from_file(
            args.file,
            copybook_paths=copybook_paths,
            callee_paths=callee_paths,
            mode=args.scenarios,
            seed=args.seed,
        )
    except ProgramLayoutError as exc:
        _fail(str(exc))

    if args.strict and bundle.unresolved:
        print(
            f"error: {len(bundle.unresolved)} unresolved item(s) in strict mode:",
            file=sys.stderr,
        )
        for item in bundle.unresolved:
            print(f"  {item}", file=sys.stderr)
        sys.exit(2)

    if args.format == "csv-dir":
        output_dir = getattr(args, "output", None)
        if not output_dir:
            _fail("--format csv-dir requires --output DIR")
        try:
            bundle.write_csv_dir(output_dir)
        except OSError as e:
            _fail(f"Cannot write output directory: {e}")
        return

    _json_out(
        {"source_file": args.file, **bundle.to_dict()},
        args.compact,
        getattr(args, "output", None),
    )


# -- Shared analyzer subcommand builder ---------------------------------------


def _build_analyzer_parser(
    subparsers: argparse._SubParsersAction,
    name: str,
    help: str,
    func: Any,
    *,
    profiling: bool = False,
) -> None:
    """Build a standard analyzer subcommand.

    Shared by the analyzer subcommands whose argument set is identical:
    a ``file`` positional plus the common compact/free-form/dialect/
    error-recovery/copybook/define/output flags. ``profiling=True`` also adds
    the profiling flags.
    """
    p = subparsers.add_parser(name, help=help)
    p.add_argument("file", help="Path to the COBOL source file")
    _add_compact_arg(p)
    _add_free_form_arg(p)
    _add_dialect_arg(p)
    _add_error_recovery_arg(p)
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    if profiling:
        _add_profiling_args(p)
    p.set_defaults(func=func)


def _cmd_analyze(args: argparse.Namespace) -> None:
    from ..analysis.value_tracker import DynamicCallAnalyzer

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
        calls.append(entry)

    _emit_report({"calls": calls}, args, prof, ast)


# -- Subcommand: dead-code ----------------------------------------------------


def _cmd_dead_code(args: argparse.Namespace) -> None:
    from ..analysis.dead_code import DeadCodeAnalyzer

    ast, prof = _parse_or_fail(args)

    analyzer = DeadCodeAnalyzer()
    report = analyzer.analyze(ast)

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: unused-variables ---------------------------------------------


def _build_unused_variables_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "unused-variables",
        help="Detect DATA DIVISION items never referenced in PROCEDURE DIVISION",
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
    source = _read_source(args.file)
    dialect = _DIALECT_MAP[args.dialect]
    error_recovery = _get_error_recovery(args)
    defines = _parse_defines(getattr(args, "define", []))

    if defines:
        from ..preprocess import preprocess_conditional_compilation

        source = preprocess_conditional_compilation(source, defines, warnings=[])

    parse_kwargs: dict[str, Any] = {
        "dialect": dialect,
        "error_recovery": error_recovery,
        "free_form": getattr(args, "free_form", False),
    }
    return parse_cobol(source, filename=args.file, **parse_kwargs)


def _cmd_unused_variables(args: argparse.Namespace) -> None:
    from ..analysis.unused_variables import (
        UnusedVariableAnalyzer,
        collect_declared_items,
    )

    ast, prof = _parse_or_fail(args)

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
            local_names = {
                item.name.upper()
                for item in collect_declared_items(unexpanded_result.ast)
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

    _emit_report(report.to_dict(), args, prof, ast)


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

    ast, prof = _parse_or_fail(args)

    analyzer = ProgramFlowAnalyzer()
    report = analyzer.analyze(ast)

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
        _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: io-sequence --------------------------------------------------


def _cmd_io_sequence(args: argparse.Namespace) -> None:
    from ..analysis.io_sequence import IOSequenceAnalyzer

    ast, _prof = _parse_or_fail(args)

    analyzer = IOSequenceAnalyzer()
    report = analyzer.analyze(ast)

    _emit_report(report.to_dict(), args, ast=ast)


# -- Subcommand: move-type-check ----------------------------------------------


def _cmd_move_type_check(args: argparse.Namespace) -> None:
    from ..analysis.move_type_checker import MoveTypeChecker

    ast, _prof = _parse_or_fail(args)

    checker = MoveTypeChecker()
    report = checker.check(ast)

    _emit_report(report.to_dict(), args, ast=ast)


# -- Subcommand: linkage-check ------------------------------------------------


def _cmd_linkage_check(args: argparse.Namespace) -> None:
    from ..analysis.linkage_checker import LinkageChecker

    ast, _prof = _parse_or_fail(args)

    checker = LinkageChecker()
    report = checker.check(ast)

    _emit_report(report.to_dict(), args, ast=ast)


# -- Subcommand: language-env -------------------------------------------------


def _cmd_language_env(args: argparse.Namespace) -> None:
    from ..analysis.language_env_analyzer import LanguageEnvironmentAnalyzer
    from ..analysis.value_tracker import DynamicCallAnalyzer

    ast, _prof = _parse_or_fail(args)

    # Populate possible_values on dynamic CALLs before LE analysis
    DynamicCallAnalyzer().analyze(ast)

    analyzer = LanguageEnvironmentAnalyzer()
    report = analyzer.analyze(ast)

    _emit_report(report.to_dict(), args, ast=ast)


# -- Subcommand: ims-dli ------------------------------------------------------


def _cmd_ims_dli(args: argparse.Namespace) -> None:
    from ..analysis.ims_segment_analyzer import IMSSegmentAnalyzer

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
        "is_ims_program": ast.has_ims(),
        "entry_points": entry_points_out,
        "dli_call_count": len(calls_out),
        "all_segments": all_segments,
        "dli_calls": calls_out,
    }

    _emit_report(output, args, ast=ast)


# -- Subcommand: data-items ----------------------------------------------------


def _cmd_data_items(args: argparse.Namespace) -> None:
    from ..generators.data.layout_offsets import compute_program_data_items

    ast, prof = _parse_or_fail(args)

    output = compute_program_data_items(ast)

    _emit_report(output, args, prof, ast)


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


def _loc(loc: Any) -> dict[str, int] | None:
    """Render a source location as ``{"line": ..., "column": ...}`` or None."""
    if loc is None:
        return None
    return {"line": loc.line, "column": loc.column}


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
    _build_gen_data_parser(subparsers)
    _build_gen_fixtures_parser(subparsers)
    _build_analyzer_parser(
        subparsers,
        "analyze",
        "Analyze dynamic CALL targets in COBOL source",
        _cmd_analyze,
        profiling=True,
    )
    _build_analyzer_parser(
        subparsers,
        "dead-code",
        "Detect unreferenced paragraphs/sections (dead code)",
        _cmd_dead_code,
        profiling=True,
    )
    _build_unused_variables_parser(subparsers)
    _build_program_flow_parser(subparsers)
    _build_analyzer_parser(
        subparsers,
        "io-sequence",
        "Validate file I/O operation ordering (OPEN/READ/WRITE/CLOSE lifecycle)",
        _cmd_io_sequence,
    )
    _build_analyzer_parser(
        subparsers,
        "move-type-check",
        "Check MOVE statement data category compatibility",
        _cmd_move_type_check,
    )
    _build_analyzer_parser(
        subparsers,
        "linkage-check",
        "Validate LINKAGE SECTION items against CALL/ENTRY USING clauses",
        _cmd_linkage_check,
    )
    _build_analyzer_parser(
        subparsers,
        "language-env",
        "Detect COBOL intrinsic functions and IBM Language Environment service calls",
        _cmd_language_env,
    )
    _build_analyzer_parser(
        subparsers,
        "ims-dli",
        "Extract IMS DLI segment references from CBLTDLI/AIBTDLI/CEETDLI calls",
        _cmd_ims_dli,
    )
    _build_analyzer_parser(
        subparsers,
        "data-items",
        "Compute byte offset, byte length, REDEFINES chains, and level-88 "
        "condition values for every data item in the program",
        _cmd_data_items,
        profiling=True,
    )

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
