"""Source-level subcommands: parse, batch, tokenize, preprocess, expand."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

from ...models.program import CobolDivision, CobolParagraph, CobolProgram, CobolSection
from .._common import (
    _DEFAULT_PROFILE_TOP_N,
    _DIALECT_MAP,
    _add_compact_arg,
    _add_copybook_args,
    _add_debug_lines_arg,
    _add_define_args,
    _add_dialect_arg,
    _add_encoding_arg,
    _add_error_recovery_arg,
    _add_limit_args,
    _add_output_arg,
    _add_profiling_args,
    _add_source_format_args,
    _do_parse,
    _fail,
    _get_error_recovery,
    _identification,
    _json_out,
    _limit_kwargs,
    _parse_defines,
    _profiling_requested,
    _read_source,
    _resolve_source_format,
    _select_program_unit,
    _source_format_kwargs,
)

# -- Subcommand: parse -------------------------------------------------------


def _build_parse_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "parse",
        help="Parse a COBOL source file to AST JSON",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser parse program.cbl\n"
            "  cobol-parser parse program.cbl --errors --stats -o ast.json"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    p.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Dot-separated AST path (e.g., procedure.MAIN-LOGIC.display)",
    )
    _add_compact_arg(p)
    _add_source_format_args(p)
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


def _stats_dict(stats: Any) -> dict[str, Any]:
    """Build the statistics output dict shared by the parse and batch commands."""
    return {
        "lines_processed": stats.lines_processed,
        "tokens_processed": stats.tokens_processed,
        "parse_time_seconds": stats.parse_time_seconds,
        "memory_peak_mb": stats.memory_peak_mb,
    }


def _cmd_parse(args: argparse.Namespace) -> None:
    result, prof = _do_parse(args)

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(f"Parse failed for {args.file}\n" + "\n".join(error_lines))

    # Record the file's program units so a multi-PROGRAM-ID file says so in
    # its identification header, the way every analyzer subcommand does.
    _select_program_unit(args, result)

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
        _exit_if_partial_parse(args.file, result)
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
        # (and, for a multi-PROGRAM-ID file, the unit list) needs to be
        # spliced in for identification.
        output = {"source_file": args.file}
        units = getattr(args, "program_units", None)
        if units:
            output["program_units"] = units
        output.update(result.ast.to_dict())

    if args.errors:
        output["errors"] = [str(e) for e in result.errors]
        output["warnings"] = result.warnings
    if args.stats:
        output["statistics"] = _stats_dict(result.statistics)

    if prof is not None:
        output["profiling"] = prof.to_dict()

    _json_out(output, args.compact, getattr(args, "output", None))
    _exit_if_partial_parse(args.file, result, errors_in_output=bool(args.errors))


def _exit_if_partial_parse(
    file: str, result: Any, errors_in_output: bool = False
) -> None:
    """Exit 2 after the JSON is out when the parse recovered from errors.

    A recovered-but-errored parse must not report success to the shell:
    scripts and CI gate on the exit code, and exiting 0 here silently
    promoted every partial parse to a clean one. The hint to re-run with
    ``--errors`` is left out when the JSON already carries them (#745).
    """
    if result.errors:
        where = (
            "they are in the JSON output's errors"
            if errors_in_output
            else "re-run with --errors to include them in the JSON output"
        )
        print(
            f"warning: parse of {file} completed with "
            f"{len(result.errors)} error(s); AST may be incomplete ({where})",
            file=sys.stderr,
        )
        sys.exit(2)


# -- Subcommand: batch --------------------------------------------------------


def _build_batch_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "batch",
        help="Parse multiple COBOL files in parallel",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser batch a.cbl b.cbl c.cbl\n"
            "  cobol-parser batch --glob 'src/**/*.cbl' --workers 4"
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
    _add_debug_lines_arg(p)
    p.set_defaults(func=_cmd_batch)


def _cmd_batch(args: argparse.Namespace) -> None:
    import glob as _glob
    from pathlib import Path as _Path

    from ...batch import parse_files

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

    enable_profiling = _profiling_requested(args)
    top_n = getattr(args, "profile_top_n", _DEFAULT_PROFILE_TOP_N)
    prof_output = getattr(args, "profile_output", None)

    if prof_output is not None and prof_output.endswith(".prof"):
        _fail(
            "--profile-output in batch mode must be a directory path, not a .prof file"
        )
    if (
        prof_output is not None
        and os.path.exists(prof_output)
        and not os.path.isdir(prof_output)
    ):
        _fail(
            f"--profile-output {prof_output} is a file; batch mode writes "
            "one .prof per input into a directory"
        )

    if args.workers is not None and args.workers < 1:
        _fail("--workers must be >= 1")

    limits = _limit_kwargs(args)
    results = parse_files(
        unique_files,
        workers=args.workers,
        **limits,
        error_recovery=error_recovery,
        dialect=dialect,
        encoding=args.encoding,
        enable_profiling=enable_profiling,
        top_n=top_n,
        prof_output=prof_output,
        debug_lines=bool(getattr(args, "debug_lines", False)),
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
    p = subparsers.add_parser(
        "tokenize",
        help="Tokenize a COBOL source file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser tokenize program.cbl\n"
            "  cobol-parser tokenize program.cbl --free-form"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    _add_compact_arg(p)
    _add_source_format_args(p)
    _add_dialect_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_tokenize)


def _cmd_tokenize(args: argparse.Namespace) -> None:
    from ...lexer import _tokenize_source

    source = _read_source(args.file, getattr(args, "encoding", None))
    dialect = _DIALECT_MAP[args.dialect]

    # Unified pipeline (M6): fixed-format source is normalized and lexed
    # free-form exactly like `cobol-parser parse`, with comment lines
    # preserved as COMMENT tokens. Lexer errors are ignored here, matching
    # the previous behavior of this subcommand (best-effort token dump).
    tokens, _errors, _warnings = _tokenize_source(
        source, args.file, dialect, **_source_format_kwargs(args)
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
        "preprocess",
        help="Preprocess fixed-format COBOL to free-form",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser preprocess program.cbl\n"
            "  cobol-parser preprocess program.cbl --define DEBUG"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    _add_source_format_args(p)
    _add_define_args(p)
    p.add_argument(
        "--strip-directives",
        action="store_true",
        help="Strip PROCESS/CBL compiler directives before normalizing",
    )
    p.set_defaults(func=_cmd_preprocess)


def _cmd_preprocess(args: argparse.Namespace) -> None:
    from ..._source_text.source_format import (
        detect_fixed_format,
        normalize_with_recovery,
    )
    from ...preprocess import (
        preprocess_conditional_compilation,
        strip_compiler_directives,
    )

    source = _read_source(args.file, getattr(args, "encoding", None))

    if args.strip_directives:
        source = strip_compiler_directives(source)

    # Always evaluated, --define or not: >>IF / >>EVALUATE / >>DEFINE in the
    # source are themselves directives, and gating this on --define printed
    # both arms of every >>IF ... >>ELSE when no symbol was given (#271).
    defines = _parse_defines(args.define)
    conditional_warnings: list[str] = []
    # Kept for normalize_fixed_format below (see _do_parse).
    source = preprocess_conditional_compilation(
        source,
        defines or {},
        warnings=conditional_warnings,
        keep_source_format_directives=True,
    )
    for cw in conditional_warnings:
        print(f"warning: {cw}", file=sys.stderr)

    # 'fixed' always normalizes; 'auto' (the default) normalizes only when
    # detection classifies the source as fixed-format -- previously auto
    # normalized unconditionally, silently slicing columns off genuine
    # free-form input; 'free' never normalizes.
    source_format = _resolve_source_format(args)
    if source_format == "fixed" or (
        source_format == "auto" and detect_fixed_format(source)
    ):
        from ..._lines import split_source_lines

        normalize_warnings: list[str] = []
        # split_source_lines, not str.splitlines(): the latter also breaks on
        # a form feed (a page eject inside a comment record), NEL, U+2028...
        # which split one record in two and emitted the tail of a comment
        # as code -- output `parse` itself never sees.
        # normalize_with_recovery, not normalize_fixed_format: an
        # unterminated literal at EOF (a truncated upload) raised ValueError
        # straight out as a traceback (#372). Like `parse` / `tokenize`, it
        # is reported and the never-raising pass's text is printed instead.
        text, error = normalize_with_recovery(
            split_source_lines(source),
            normalize_warnings,
            debug_lines_as_comments=not getattr(args, "debug_lines", False),
        )
        assert text is not None  # recover=True always yields text
        source = text
        if error is not None:
            print(f"warning: {error}", file=sys.stderr)
        for nw in normalize_warnings:
            print(f"warning: {nw}", file=sys.stderr)

    print(source, end="")


# -- Subcommand: expand -------------------------------------------------------


def _build_expand_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "expand",
        help="Expand COPY statements (copybooks)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Example:\n"
            "  cobol-parser expand program.cbl --copybook-path ./copybooks\n"
            "  cobol-parser expand program.cbl --copybook-path ./cpy --source-map"
        ),
    )
    p.add_argument("file", help="Path to the COBOL source file")
    _add_encoding_arg(p)
    _add_copybook_args(p)
    _add_compact_arg(p)
    p.add_argument(
        "--keep-comments",
        action="store_true",
        help=(
            "Keep comment lines' original text in the expanded listing "
            "(they are blanked by default, since a COPY inside a comment "
            "must not be expanded)"
        ),
    )
    p.add_argument(
        "--source-map",
        action="store_true",
        help=(
            "Include source_location_map: one entry per expanded line, naming "
            "the file and line it came from"
        ),
    )
    p.add_argument(
        "--max-depth",
        type=int,
        default=100,
        metavar="N",
        help="Maximum copybook nesting depth (default: 100)",
    )
    _add_define_args(p)
    _add_output_arg(p)
    _add_debug_lines_arg(p)
    p.set_defaults(func=_cmd_expand)


def _cmd_expand(args: argparse.Namespace) -> None:
    from ...preprocess import PreprocessingError
    from ...preprocess.copybook_expander import expand_copybooks

    source = _read_source(args.file, getattr(args, "encoding", None))

    # Conditional compilation is left to expand_copybooks (process_conditionals
    # below): it must see the program's own >>DEFINE lines to hand them to the
    # copybooks COPYd beneath them. Running it here first consumed those
    # lines, so every copybook saw only the --define symbols. Its diagnostics
    # land in the JSON's statistics.warnings. Always evaluated, --define or
    # not: gating it on --define printed both arms of every >>IF ... >>ELSE
    # and ignored the program's own >>DEFINE (#583, as #271 for preprocess).
    defines = _parse_defines(args.define)

    try:
        result = expand_copybooks(
            source,
            copybook_paths=args.copybook_path,
            max_nesting_depth=args.max_depth,
            process_conditionals=True,
            defined_symbols=defines or {},
            preserve_source_locations=getattr(args, "source_map", False),
            source_file=args.file,
            preserve_comments=getattr(args, "keep_comments", False),
            debug_lines=bool(getattr(args, "debug_lines", False)),
        )
    except PreprocessingError as exc:
        # The same one-line error and exit status `parse --copybook-path`
        # gives: a missing / circular / traversing COPY is a configuration
        # error, not a crash, and a traceback hid the one line that says so.
        _fail(f"Copybook expansion failed for {args.file}: {exc}")

    _json_out(
        {"source_file": args.file, **result.to_dict()},
        args.compact,
        getattr(args, "output", None),
    )


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
