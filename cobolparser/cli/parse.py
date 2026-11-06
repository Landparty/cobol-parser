"""Command-line interface for parsing COBOL source files."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Callable
from typing import Any, NoReturn

from ..config import ConfigError, ProjectConfig, load_project_config
from ..models.program import CobolDivision, CobolParagraph, CobolProgram, CobolSection
from ..parser import parse_cobol
from ..plugins.core import DialectType, ErrorRecoveryMode
from . import _help, _project_config

_SUBCOMMANDS = frozenset(
    {
        "parse",
        "batch",
        "tokenize",
        "preprocess",
        "expand",
        "gen-data",
        "gen-fixtures",
        "decode",
        "compare",
        "dclgen-check",
        "analyze",
        "lint",
        "dead-code",
        "unused-variables",
        "program-flow",
        "recursion-check",
        "complexity",
        "health",
        "redundancy",
        "scan",
        "io-sequence",
        "move-type-check",
        "linkage-check",
        "language-env",
        "ims-dli",
        "data-items",
        "le-info",
        "program-signature",
        "xref",
        "diff",
        "codebase-graph",
        "copybook-impact",
        "call-check",
        "sql-cics-check",
        "business-rules",
        "lineage",
        "field-impact",
        "widen-check",
        "jcl",
        "config",
        "mcp",
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


def _add_source_format_args(parser: argparse.ArgumentParser) -> None:
    """Add the source-layout flags shared by the source-reading subcommands.

    ``--source-format`` is the current spelling. ``--free-form`` predates it
    and keeps its historical, weaker semantics: a lexer-mode hint that
    fixed-format auto-detection may still override by normalizing (so
    existing invocations that passed it against conventional fixed-format
    members keep working). ``--source-format=free`` is the strict form that
    disables normalization outright. They are mutually exclusive because
    ``--free-form --source-format=fixed`` has no coherent meaning.
    """
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--source-format",
        choices=["auto", "fixed", "free"],
        default="auto",
        help=(
            "How to interpret source columns (default: auto). 'fixed' forces "
            "fixed-format normalization -- columns 1-6 are stripped even when "
            "they hold change-tracking tags rather than blanks or sequence "
            "numbers; 'free' disables normalization entirely"
        ),
    )
    group.add_argument(
        "--free-form",
        action="store_true",
        help=(
            "Legacy free-form hint; auto-detection may still normalize source "
            "it classifies as fixed-format. Use --source-format=free to "
            "disable normalization outright"
        ),
    )
    _add_debug_lines_arg(parser)


def _add_debug_lines_arg(parser: argparse.ArgumentParser) -> None:
    """``--debug-lines`` / ``--no-debug-lines``, bound to cobol.yml's
    ``project.debug_lines``. Every subcommand that parses COBOL takes it --
    a subcommand without the dest would silently ignore the config key."""
    parser.add_argument(
        "--debug-lines",
        action=argparse.BooleanOptionalAction,
        default=False,
        help=(
            "Compile fixed-format debugging lines (D in column 7) as code, "
            "as IBM Enterprise COBOL does under SOURCE-COMPUTER ... WITH "
            "DEBUGGING MODE. By default they are dropped as comments, with a "
            "warning when the program declares WITH DEBUGGING MODE. "
            "--no-debug-lines overrides debug_lines: true in cobol.yml"
        ),
    )


def _resolve_source_format(args: argparse.Namespace) -> str:
    """Collapse the two layout flags into one 'auto' | 'fixed' | 'free' value."""
    if getattr(args, "free_form", False):
        return "free"
    return str(getattr(args, "source_format", "auto"))


def _source_format_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    """Map the layout flags onto ``parse_cobol``'s two format parameters.

    ``preprocess_fixed`` is the override (None = auto-detect) and
    ``free_form`` selects the lexer mode used when no normalization runs.

    Legacy ``--free-form`` deliberately maps to ``preprocess_fixed=None``,
    not ``False``: before ``--source-format`` existed, the flag passed only
    ``free_form=True`` and ``parse_cobol``'s auto-detection still normalized
    source it classified as fixed-format -- scripts that always passed
    ``--free-form`` against conventional fixed-format members relied on
    that. ``--source-format=free`` is the strict spelling that hard-disables
    normalization.
    """
    source_format = str(getattr(args, "source_format", "auto"))
    kwargs: dict[str, Any]
    if source_format == "free":
        kwargs = {"free_form": True, "preprocess_fixed": False}
    elif source_format == "fixed":
        kwargs = {"free_form": False, "preprocess_fixed": True}
    elif getattr(args, "free_form", False):
        kwargs = {"free_form": True, "preprocess_fixed": None}
    else:
        kwargs = {"free_form": False, "preprocess_fixed": None}
    # Only when set: the callers splat this into parse_cobol and
    # _tokenize_source, both of which default it off.
    if getattr(args, "debug_lines", False):
        kwargs["debug_lines"] = True
    return kwargs


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


def _add_program_arg(
    parser: argparse.ArgumentParser, default_note: str = "the outermost"
) -> None:
    parser.add_argument(
        "--program",
        default=None,
        metavar="NAME",
        help=(
            "PROGRAM-ID to analyze in a file holding several program units "
            f"(default: {default_note}). The full list is reported as "
            "program_units."
        ),
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


_DEFAULT_PROFILE_TOP_N = 20


def _add_profiling_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        action="store_true",
        help="Profile the parse and include timing/memory metrics in output",
    )
    parser.add_argument(
        "--profile-top-n",
        type=int,
        default=_DEFAULT_PROFILE_TOP_N,
        metavar="N",
        help="Number of top functions to include in profiling output "
        f"(default: {_DEFAULT_PROFILE_TOP_N}; implies --profile)",
    )
    parser.add_argument(
        "--profile-output",
        default=None,
        metavar="PATH",
        help="Write cProfile binary to PATH (.prof for single file, directory "
        "for batch; implies --profile)",
    )


def _profiling_requested(args: argparse.Namespace) -> bool:
    """Whether to profile: ``--profile``, or a flag only profiling reads.

    ``--profile-output`` (or a non-default ``--profile-top-n``) on its own
    used to do nothing and say nothing (#328); asking for the profile's
    output is asking for the profile. ``args.profile`` is set too, so the
    callers' "metrics only in --format json" warnings see the same answer.
    """
    if (
        getattr(args, "profile_output", None) is not None
        or getattr(args, "profile_top_n", _DEFAULT_PROFILE_TOP_N)
        != _DEFAULT_PROFILE_TOP_N
    ):
        args.profile = True
    return bool(getattr(args, "profile", False))


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


def _defined_symbol_pairs(args: argparse.Namespace) -> tuple[tuple[str, str], ...]:
    """``--define`` (or cobol.yml ``project.define``) as picklable pairs, for
    ``ScanOptions.defined_symbols``."""
    return tuple((_parse_defines(getattr(args, "define", [])) or {}).items())


def _read_source(filepath: str, encoding: str | None = None) -> str:
    """Read a program source, decoded the way a copybook is (#522).

    *encoding* None detects it (a cp1252 / Latin-1 program reads as such, not
    "not valid UTF-8"); a named one is used as given. Bytes the encoding
    cannot map become U+FFFD with a ``warning:`` on stderr.
    """
    from ..preprocess import PreprocessingError
    from ..preprocess.copybook_expander import read_program_source

    if not os.path.exists(filepath):
        _fail(f"File not found: {filepath}")
    if os.path.isdir(filepath):
        _fail(
            f"{filepath} is a directory; pass a COBOL source file (for a "
            "whole tree use `cobol-parser lint --glob 'DIR/**/*.cbl'` or "
            "`cobol-parser scan DIR/*.cbl`)"
        )
    warnings: list[str] = []
    try:
        text = read_program_source(filepath, encoding, warnings=warnings)
    except LookupError:
        _fail(f"Unknown encoding: {encoding}")
    except PreprocessingError as e:
        _fail(f"Cannot read file: {e}")
    except OSError as e:
        _fail(f"Cannot read file: {e}")
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    return text


def _add_encoding_arg(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--encoding",
        default=None,
        metavar="ENC",
        help=(
            "Source encoding (e.g. cp1252, latin-1, cp037). Default: detected, "
            "the same way a copybook's encoding is"
        ),
    )


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
    # Recorded by _parse_result_or_fail off the WHOLE parse, so it still lists
    # every unit in the file after --program narrowed `ast` to one of them.
    # Present only when the file holds more than one program, so the output of
    # the ordinary one-program file is unchanged: the key appearing at all
    # means "several programs here, and this report covers program_id".
    units = getattr(args, "program_units", None)
    if units:
        ident["program_units"] = list(units)
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
    # With --copybook-path every location counts lines of the expanded
    # text; stamp each with the file and line it really came from, the way
    # lint does. Additive: nothing is added without an expansion map.
    from ..analysis.lint import stamp_report_origins

    data = stamp_report_origins(data, getattr(args, "_expansion_source_map", None))
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


def _verbatim_out(text: str, output_path: str | None = None) -> None:
    """Write *text* to *output_path* or stdout with nothing added.

    Unlike :func:`_text_out`, which appends a newline: CSV and hex-dump
    output already ends in one, and a second would make ``> out.csv`` and
    ``-o out.csv`` produce different bytes for the same run.
    """
    if output_path:
        try:
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(text)
        except OSError as e:
            _fail(f"Cannot write output file: {e}")
    else:
        print(text, end="")


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


def _do_parse(args: argparse.Namespace) -> tuple[Any, Any]:
    """Shared parse logic used by parse and analyze subcommands."""
    from ..profiling import ProfilerContext

    source = _read_source(args.file, getattr(args, "encoding", None))
    if getattr(args, "_wrap_copybook_fragment", False):
        # data-items on a bare copybook: parse it the way gen-data does,
        # inside a program skeleton, instead of as a program with no
        # divisions (an empty answer with exit 0, #536).
        from ..generators.data.copybook import wrap_copybook_fragment

        wrapped = wrap_copybook_fragment(source)
        if wrapped is not None:
            source = wrapped
    dialect = _DIALECT_MAP[args.dialect]
    error_recovery = _get_error_recovery(args)

    copybook_paths = getattr(args, "copybook_path", [])
    defines = _parse_defines(getattr(args, "define", []))
    enable_profiling = _profiling_requested(args)
    top_n = getattr(args, "profile_top_n", _DEFAULT_PROFILE_TOP_N)
    prof_output = getattr(args, "profile_output", None)
    if prof_output is not None and os.path.isdir(prof_output):
        # Checked before the parse: cProfile's dump_stats() would only raise
        # IsADirectoryError after all the work was done.
        _fail(f"--profile-output {prof_output} is a directory; give a .prof file path")

    # With copybook paths, conditional compilation is left to the expander
    # (process_conditionals below): run here first, it consumed the program's
    # >>DEFINE lines and the --define symbols never reached the copybooks --
    # the parser's own directive pass over the expanded text sees neither --
    # so a member's `>>IF DBG DEFINED` took the wrong branch under
    # `--define DBG`.
    if defines and not copybook_paths:
        from ..preprocess import preprocess_conditional_compilation

        conditional_warnings: list[str] = []
        # keep_source_format_directives: this runs on the raw source, before
        # the parser's own fixed-format normalization, which still has to
        # see where ``>>SOURCE FORMAT IS FREE`` switches the reference
        # format. Blanked here, every free-format line after it was column-
        # sliced as fixed format (``DISPLAY "X".`` read as `` "X".``).
        source = preprocess_conditional_compilation(
            source,
            defines,
            warnings=conditional_warnings,
            keep_source_format_directives=True,
        )
        for cw in conditional_warnings:
            print(f"warning: {cw}", file=sys.stderr)

    parse_kwargs: dict[str, Any] = {
        "dialect": dialect,
        "error_recovery": error_recovery,
        **_source_format_kwargs(args),
    }

    def _parse_once() -> Any:
        if copybook_paths:
            from ..preprocess import PreprocessingError
            from ..preprocess.copybook_expander import parse_cobol_with_expansion

            try:
                return parse_cobol_with_expansion(
                    source,
                    filename=args.file,
                    copybook_paths=copybook_paths,
                    process_conditionals=True,
                    defined_symbols=defines,
                    **parse_kwargs,
                )
            except PreprocessingError as exc:
                # A copybook that cannot be found (or expands circularly)
                # is a configuration error the caller has to see on one
                # line, not a traceback: the VS Code extension clears its
                # diagnostics on any non-zero exit and reads stderr for why.
                _fail(f"Copybook expansion failed for {args.file}: {exc}")
        return parse_cobol(source, filename=args.file, **parse_kwargs)

    if not enable_profiling:
        return _parse_once(), None

    # With profiling
    ctx = ProfilerContext(top_n=top_n, prof_output=prof_output)
    with ctx:
        result = _parse_once()
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
    result, prof = _parse_result_or_fail(args)
    return result.ast, prof


def _parse_result_or_fail(args: argparse.Namespace) -> tuple[Any, Any]:
    """The same guard, keeping the whole ``ParseResult``.

    A command that needs more off the result than its AST -- lint wants
    ``expansion_source_map``, so it can report where a finding is in the file
    on disk rather than in the expanded text -- calls this instead.
    """
    result, prof = _do_parse(args)
    _hint_unexpanded_copybooks(args, result)
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
    _select_program_unit(args, result)
    # Remembered for `_emit_report`, which stamps source-map origins onto
    # every report location (see `stamp_report_origins`).
    args._expansion_source_map = getattr(result, "expansion_source_map", None)
    return result, prof


_UNEXPANDED_COPY = re.compile(r"^COPY (\S+) was not expanded")


def _hint_unexpanded_copybooks(args: argparse.Namespace, result: Any) -> None:
    """Say on stderr when COPY statements were left out for want of a
    copybook path.

    Without ``--copybook-path`` the parse still succeeds, so the only trace
    of the missing copybooks was a warning inside the JSON, and an analyzer
    report silently covered less of the program than the user expected.
    """
    if getattr(args, "copybook_path", None):
        return
    names = []
    for warning in getattr(result, "warnings", None) or []:
        match = _UNEXPANDED_COPY.match(str(warning))
        if match and match.group(1) not in names:
            names.append(match.group(1))
    if not names:
        return
    shown = ", ".join(names[:5]) + (
        f" and {len(names) - 5} more" if len(names) > 5 else ""
    )
    print(
        f"warning: {args.file}: {len(names)} copybook(s) not expanded ({shown}); "
        "pass --copybook-path DIR or set project.copybook_path in cobol.yml",
        file=sys.stderr,
    )


def _select_program_unit(args: argparse.Namespace, result: Any) -> None:
    """Narrow ``result.ast`` to the program unit ``--program`` names.

    A source file may hold several ``PROGRAM-ID``s (stacked or nested program
    units); the parse returns the outermost with the rest on
    ``contained_programs``. Every analyzer is program-scoped, so a report has
    to be about one unit -- the outermost by default, which is what these
    subcommands have always reported, or the one ``--program`` names.

    The whole file's unit names are recorded on *args* either way, so the
    emitted report can say which programs it did NOT cover.
    """
    ast = result.ast
    if ast is None:
        return
    units = ast.program_units()
    if len(units) > 1:
        args.program_units = [u.program_name or None for u in units]

    wanted = getattr(args, "program", None)
    if not wanted:
        return
    selected = ast.find_program_unit(wanted)
    if selected is None:
        available = ", ".join(u.program_name or "<unnamed>" for u in units)
        _fail(f"No program unit named {wanted!r} in {args.file} (found: {available})")
    result.ast = selected


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

    results = parse_files(
        unique_files,
        workers=args.workers,
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
    from ..lexer import _tokenize_source

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
    from ..preprocess import (
        preprocess_conditional_compilation,
        strip_compiler_directives,
    )
    from ..preprocess.source_format import (
        detect_fixed_format,
        normalize_with_recovery,
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
        from .._lines import split_source_lines

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
    from ..preprocess import PreprocessingError
    from ..preprocess.copybook_expander import expand_copybooks

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


# -- Subcommand: gen-data -----------------------------------------------------


def _build_gen_data_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "gen-data",
        help="Generate synthetic CSV test data from a copybook record layout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser gen-data CUSTOMER.cpy --rows 100 --seed 7 -o out.csv\n"
            "  cobol-parser gen-data CUSTOMER.cpy --list-records"
        ),
    )
    p.add_argument("file", help="Path to the copybook (or COBOL source) file")
    _add_encoding_arg(p)
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
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["csv", "json", "record", "hex"],
        default="csv",
        help=(
            "csv (default) / json display values; record writes the real "
            "COBOL record image (COMP-3 packed, COMP big-endian binary, "
            "signed DISPLAY overpunched); hex is that image annotated "
            "field by field"
        ),
    )
    p.add_argument(
        "--charset",
        choices=["ascii", "ebcdic"],
        default="ascii",
        help="Encoding of DISPLAY bytes for --format record/hex (default: ascii)",
    )
    p.add_argument(
        "--endian",
        choices=["auto", "big", "little", "native"],
        default="auto",
        help=(
            "Byte order for COMP-5 and COMP-1/COMP-2 (default: auto -- "
            "big-endian for --charset ebcdic, host order otherwise). "
            "COMP/COMP-4 are always big-endian"
        ),
    )
    p.add_argument(
        "--record-format",
        choices=["fixed", "variable", "variable-bare", "auto"],
        # Not "fixed": the default has to stay distinguishable from an
        # explicit --record-format fixed, so that --record-varying (which is
        # a statement that records are *not* fixed) can default to auto
        # without overriding a caller who really did ask for fixed.
        default=None,
        help=(
            "Record length for --format record/hex: fixed (default) writes "
            "every record at the layout's full length, as RECFM=F/FB expects; "
            "variable writes only the OCCURS DEPENDING ON occurrences each "
            "record's own counter names, behind the 4-byte RDW that RECFM=V/VB "
            "uses to delimit them; variable-bare is the same records without "
            "the RDW; auto picks variable when the layout has a DEPENDING ON "
            "table and fixed otherwise"
        ),
    )
    p.add_argument(
        "--record-varying",
        default=None,
        metavar="MIN:MAX",
        help=(
            "Record length range, as an FD's RECORD VARYING FROM MIN TO MAX "
            "declares. Only needed for a bare copybook, which carries no FD: "
            "given a whole COBOL program, the clause is read off the record "
            "itself. Implies a variable record format unless --record-format "
            "says otherwise"
        ),
    )
    p.add_argument(
        "--record-separator",
        choices=["none", "newline"],
        default="none",
        help=(
            "Bytes between records for --format record (default: none, a "
            "true fixed-length RECFM=F image)"
        ),
    )
    _add_compact_arg(p)
    _add_copybook_args(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_gen_data)


def _warn_layout(warnings: list[str]) -> None:
    """Say on stderr that a record layout is short a ``COPY`` member.

    ``gen-data``, ``decode`` and ``compare`` frame every record by the
    layout's length, so a ``COPY`` left unexpanded (no ``--copybook-path``,
    or its member not found there) silently drops fields and shortens every
    record. Never silent: this is the one place that says so.
    """
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)


def _encoding_options(args: argparse.Namespace) -> Any:
    """Build the EncodingOptions the record-image formats are rendered with."""
    from ..generators.data.encoding import (
        Charset,
        EncodingOptions,
        Endian,
        RecordFormat,
    )

    chosen = getattr(args, "record_format", None)
    if chosen is None:
        # Asking for a length range is itself saying the records vary, so
        # --record-varying alone reaches auto rather than silently writing
        # the fixed-length file the caller just said this is not.
        chosen = "auto" if getattr(args, "record_varying", None) else "fixed"
    return EncodingOptions(
        charset=Charset(args.charset),
        endian=Endian(args.endian),
        record_separator=b"\n" if args.record_separator == "newline" else b"",
        record_format=RecordFormat(chosen),
    )


def _cmd_gen_data(args: argparse.Namespace) -> None:
    from ..generators.copybook_data import (
        CopybookDataGenerator,
        CopybookLayoutError,
        DataGeneratorOptions,
        parse_copybook_records,
    )

    source = _read_source(args.file, getattr(args, "encoding", None))
    copybook_paths = args.copybook_path or None

    if args.list_records:
        layout_warnings: list[str] = []
        try:
            records = parse_copybook_records(
                source,
                filename=args.file,
                copybook_paths=copybook_paths,
                warnings=layout_warnings,
            )
        except CopybookLayoutError as exc:
            _fail(str(exc))
        _warn_layout(layout_warnings)
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

    wants_record_image = args.output_format in ("record", "hex")

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
            record_varying=_parse_record_varying(args.record_varying),
        )
    except ValueError as exc:
        _fail(str(exc))

    if wants_record_image:
        # A record image has to account for every byte, which the
        # column-shaped defaults deliberately do not -- see
        # DataGeneratorOptions.for_record_image. Overriding silently would
        # make --include-filler/--max-occurs look ignored, so say so.
        adjusted = options.for_record_image()
        if adjusted != options:
            print(
                f"note: --format {args.output_format} lays out every byte of "
                "the record, so FILLER is included, REDEFINES excluded, and "
                "every OCCURS occurrence expanded",
                file=sys.stderr,
            )
        options = adjusted

    try:
        dataset = CopybookDataGenerator(options).generate_from_source(
            source,
            filename=args.file,
            record=args.record,
            copybook_paths=copybook_paths,
        )
    except CopybookLayoutError as exc:
        _fail(str(exc))
    # Whatever the format: a --record-varying range clamped or ignored to
    # fit the layout is otherwise invisible in CSV/JSON/record output.
    for caveat in dataset.caveats:
        print(f"warning: {caveat}", file=sys.stderr)

    output_path = getattr(args, "output", None)

    if args.describe or args.output_format == "json":
        _json_out(
            {"source_file": args.file, **dataset.to_dict()},
            args.compact,
            output_path,
        )
        return

    if args.output_format == "hex":
        text = dataset.to_hex_dump(_encoding_options(args))
        if output_path:
            try:
                with open(output_path, "w", encoding="utf-8") as handle:
                    handle.write(text)
            except OSError as e:
                _fail(f"Cannot write output file: {e}")
        else:
            print(text, end="")
        return

    if args.output_format == "record":
        # Encode once and reuse the bytes for whichever destination follows.
        # Encoding here and then calling dataset.write_records() would encode
        # the whole dataset a second time -- twice the CPU, and both copies
        # resident at once, which is a real ceiling on a large --rows.
        encoding = _encoding_options(args)
        try:
            raw = dataset.to_records(encoding)
        except CopybookLayoutError as exc:
            _fail(str(exc))
        for caveat in _record_caveats(dataset, encoding):
            print(f"note: {caveat}", file=sys.stderr)
        for note in _record_length_notes(dataset, encoding):
            print(f"note: {note}", file=sys.stderr)
        if output_path:
            # Binary mode is not incidental: a COMP field routinely contains
            # 0x0A, which a text-mode write would translate on Windows.
            try:
                with open(output_path, "wb") as handle:
                    handle.write(raw)
            except OSError as e:
                _fail(f"Cannot write output file: {e}")
        else:
            # Same reason, on the way to stdout: go through the buffer so
            # nothing re-encodes or newline-translates the bytes.
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
        return

    if output_path:
        # Write through the csv module so embedded newlines round-trip.
        try:
            dataset.write_csv(output_path)
        except OSError as e:
            _fail(f"Cannot write output file: {e}")
    else:
        print(dataset.to_csv(), end="")


def _parse_record_varying(raw: str | None) -> tuple[int, int] | None:
    """Parse ``--record-varying MIN:MAX`` into a length range.

    ``MIN-MAX`` is accepted too, since that is how the range reads in an FD
    (``FROM 47 TO 80``) and a hyphen is the likelier typo of the two.
    """
    if raw is None:
        return None
    parts = raw.replace("-", ":").split(":")
    if len(parts) != 2 or not all(part.strip().isdigit() for part in parts):
        _fail(f"--record-varying expects MIN:MAX (two integers), got {raw!r}")
    return (int(parts[0]), int(parts[1]))


def _record_caveats(dataset: Any, opts: Any) -> list[str]:
    """Reasons a written record image may not match a real compiler's."""
    from ..generators.data.encoding import encoding_caveats

    return encoding_caveats(dataset.fields, opts, varying=dataset.varying)


def _record_length_notes(dataset: Any, opts: Any) -> list[str]:
    """The LRECL a reader of ``--format record`` output has to be told.

    ``--format hex`` prints this in its own header; the raw bytes have no
    header to print it in, and a record image whose length nobody states is
    a file nobody can read back.
    """
    from ..generators.data.encoding import RecordFormat

    lengths = dataset.record_lengths(opts)
    if not lengths:
        return []
    fmt = opts.resolved_format(dataset.fields, varying=dataset.varying is not None)
    framed = " (RDW included)" if fmt is RecordFormat.VARIABLE else ""
    low, high = min(lengths), max(lengths)
    span = f"{high}" if low == high else f"{low} to {high}"
    notes = [
        f"{fmt.value} record length: {span} bytes across "
        f"{len(lengths)} records{framed}"
    ]
    varying = dataset.varying
    if varying is not None and fmt.is_variable:
        # What this file *happens* to contain is not what the dataset holding
        # it has to be allocated for: LRECL comes from the declared maximum,
        # which a short run of --rows may never actually hit.
        rdw = 4 if fmt is RecordFormat.VARIABLE else 0
        notes.append(
            f"declared RECORD VARYING FROM {varying.minimum} TO "
            f"{varying.maximum}, so LRECL is {varying.maximum + rdw}"
            + (" (max record + RDW)" if rdw else "")
        )
    return notes


def _add_record_file_args(p: argparse.ArgumentParser) -> None:
    """How a record image file is encoded and framed -- decode and compare."""
    p.add_argument(
        "--charset",
        choices=["ascii", "ebcdic"],
        default="ascii",
        help="Encoding of the file's DISPLAY bytes (default: ascii)",
    )
    p.add_argument(
        "--endian",
        choices=["auto", "big", "little", "native"],
        default="auto",
        help=(
            "Byte order for COMP-5 and COMP-1/COMP-2 (default: auto -- "
            "big-endian for --charset ebcdic, host order otherwise). "
            "COMP/COMP-4 are always big-endian"
        ),
    )
    p.add_argument(
        "--record-format",
        choices=["fixed", "variable", "variable-bare", "auto"],
        default=None,
        help=(
            "How the file frames its records: fixed (default) cuts every "
            "record at the layout's length, as RECFM=F/FB writes them; "
            "variable reads the 4-byte RDW in front of each record, as "
            "RECFM=V/VB writes it; variable-bare has no RDW and is framed by "
            "the layout's own OCCURS DEPENDING ON counters; auto picks "
            "variable when the layout has a DEPENDING ON table or --copybook "
            "is a whole program whose FD declares RECORD VARYING -- the same "
            "choice gen-data's auto makes for the same source"
        ),
    )
    p.add_argument(
        "--record-length",
        type=int,
        default=None,
        metavar="N",
        help=(
            "LRECL to cut fixed-length records at, when the file's records "
            "are longer than the copybook describes (trailing slack, or a "
            "copybook covering only a prefix). Defaults to the FD's LRECL "
            "when the source is a whole program"
        ),
    )
    p.add_argument(
        "--record-separator",
        choices=["none", "newline"],
        default="none",
        help="Bytes separating records in the file (default: none)",
    )


def _build_decode_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "decode",
        help="Decode a record image / EBCDIC flat file through a copybook layout",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser decode CUSTOMER.DAT --copybook CUSTOMER.cpy "
            "--charset ebcdic\n"
            "  cobol-parser decode ORDER.VB --copybook ORDER.cpy "
            "--record-format variable --format hex\n"
            "  cobol-parser decode CUSTOMER.DAT --copybook CUSTOMER.cpy "
            "--list-views\n"
            "  cobol-parser decode CUSTOMER.DAT --copybook CUSTOMER.cpy "
            "--view ADDR-OVERSEAS --max-records 20"
        ),
    )
    p.add_argument(
        "file",
        nargs="?",
        default=None,
        help=(
            "Path to the data file (record images). Optional with "
            "--list-views, which only reads the copybook"
        ),
    )
    p.add_argument(
        "--copybook",
        "-c",
        required=True,
        metavar="FILE",
        help="Copybook (or COBOL program) whose record layout describes the data",
    )
    p.add_argument(
        "--record",
        default=None,
        metavar="NAME",
        help="Level-01 record in the copybook to decode through (default: the first)",
    )
    p.add_argument(
        "--view",
        default=None,
        metavar="NAME",
        help=(
            "REDEFINES overlay to read the bytes through, by its own name or "
            "its qualified path (default: the record as declared)"
        ),
    )
    p.add_argument(
        "--list-views",
        action="store_true",
        help=(
            "List the record's layout and every REDEFINES overlay of it, with "
            "byte offsets, and exit without reading the data file"
        ),
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["csv", "json", "hex"],
        default="csv",
        help=(
            "csv (default) is one row per record; json adds every field's "
            "offset, length and raw bytes; hex is a byte pane whose lines are "
            "the field boundaries"
        ),
    )
    _add_record_file_args(p)
    p.add_argument(
        "--max-records",
        type=int,
        default=None,
        metavar="N",
        help="Decode at most N records (default: all of them)",
    )
    p.add_argument(
        "--skip",
        type=int,
        default=0,
        metavar="N",
        help="Skip the first N records before decoding (default: 0)",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help=(
            "Exit 1 when any field failed to decode or the file had trailing "
            "bytes -- the copybook probably does not match the data"
        ),
    )
    _add_copybook_args(p)
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_decode)


def _decode_encoding_options(args: argparse.Namespace) -> Any:
    """The EncodingOptions a data file is read back through."""
    from ..generators.data.encoding import (
        Charset,
        EncodingOptions,
        Endian,
        RecordFormat,
    )

    return EncodingOptions(
        charset=Charset(args.charset),
        endian=Endian(args.endian),
        record_separator=b"\n" if args.record_separator == "newline" else b"",
        record_format=RecordFormat(args.record_format or "fixed"),
    )


def _cmd_decode(args: argparse.Namespace) -> None:
    from ..generators.data.decoding import (
        RecordDecoder,
        RecordDecodingError,
        decoded_hex_dump,
    )
    from ..generators.data.errors import CopybookLayoutError

    # Checked here rather than left to the decoder: a negative --record-length
    # surfaced as "the layout is zero bytes long", --record-length 0 was
    # silently replaced by the layout's own length, and a negative
    # --max-records decoded nothing without a word.
    if args.record_length is not None and args.record_length <= 0:
        _fail("--record-length must be a positive number of bytes")
    if args.max_records is not None and args.max_records < 0:
        _fail("--max-records cannot be negative")
    if args.skip < 0:
        _fail("--skip cannot be negative")
    encoding = _decode_encoding_options(args)
    try:
        decoder = RecordDecoder.from_copybook_file(
            args.copybook,
            record=args.record,
            opts=encoding,
            record_length=args.record_length,
            copybook_paths=args.copybook_path or None,
        )
    except CopybookLayoutError as exc:
        _fail(str(exc))
    except OSError as exc:
        _fail(f"Cannot read copybook: {exc}")
    except UnicodeDecodeError as exc:
        # A non-UTF-8 copybook (a Latin-1 accent in a comment): a one-line
        # error, as compare gives, not a traceback (#496).
        _fail(f"Cannot read copybook {args.copybook}: {exc}")
    _warn_layout(decoder.layout_warnings)

    output_path = getattr(args, "output", None)

    if args.list_views:
        # The layout alone, with no data file needed: this is what an editor
        # asks for to draw a record map, and what a user runs to find out
        # what --view will accept.
        _json_out(
            {"copybook": args.copybook, **decoder.views.to_dict()},
            args.compact,
            output_path,
        )
        return

    if args.file is None:
        _fail("decode needs a data file (or --list-views, which does not)")

    try:
        result = decoder.decode_file(
            args.file,
            view=args.view,
            max_records=args.max_records,
            skip=args.skip,
        )
    except RecordDecodingError as exc:
        _fail(str(exc))
    except OSError as exc:
        _fail(f"Cannot read data file: {exc}")

    for caveat in result.caveats:
        if caveat not in decoder.layout_warnings:  # already said, as a warning
            print(f"note: {caveat}", file=sys.stderr)
    if result.trailing:
        # Never silent: a tail that is not a whole record almost always means
        # the record length is wrong, and a table of plausible rows above it
        # is exactly how that goes unnoticed.
        print(
            f"warning: {len(result.trailing)} trailing bytes are not a whole "
            f"record -- check --record-length / --record-format",
            file=sys.stderr,
        )
    if result.error_count:
        print(
            f"warning: {result.error_count} field(s) did not decode cleanly "
            "-- run with --format json or hex to see which",
            file=sys.stderr,
        )

    if args.output_format == "json":
        _json_out(
            {"data_file": args.file, "copybook": args.copybook, **result.to_dict()},
            args.compact,
            output_path,
        )
    elif args.output_format == "hex":
        _verbatim_out(decoded_hex_dump(result, encoding), output_path)
    else:
        _verbatim_out(result.to_csv(), output_path)

    if args.strict and (result.error_count or result.trailing):
        sys.exit(1)


def _build_compare_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "compare",
        help=(
            "Compare two record files field by field through a copybook "
            "(expected vs actual output of a batch run)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Exit status is 0 when the files are equal, 1 when they differ, "
            "and 2 when\nthe comparison could not be made -- like cmp and "
            "diff, so a test or CI\nstep can gate on it directly.\n\n"
            "Examples:\n"
            "  cobol-parser compare CUST.EXPECTED CUST.ACTUAL --copybook "
            "CUSTOMER.cpy --charset ebcdic\n"
            "  cobol-parser compare BASE.DAT OUT.DAT -c CUSTOMER.cpy "
            "--key CUST-ID --ignore LAST-UPDATE-TS\n"
            "  cobol-parser compare BASE.VB OUT.VB -c ORDER.cpy "
            "--record-format variable --format json"
        ),
    )
    p.add_argument("expected", help="The baseline record file")
    p.add_argument("actual", help="The record file under test")
    p.add_argument(
        "--copybook",
        "-c",
        required=True,
        metavar="FILE",
        help="Copybook (or COBOL program) whose record layout describes both files",
    )
    p.add_argument(
        "--record",
        default=None,
        metavar="NAME",
        help="Level-01 record in the copybook to read through (default: the first)",
    )
    p.add_argument(
        "--view",
        default=None,
        metavar="NAME",
        help="REDEFINES overlay to read both files through (default: the record)",
    )
    p.add_argument(
        "--key",
        action="append",
        default=[],
        metavar="FIELD",
        help=(
            "Pair records on this field instead of by position (repeatable, "
            "for a multi-field key). An inserted or deleted record is then "
            "reported once instead of shifting every record after it"
        ),
    )
    p.add_argument(
        "--ignore",
        action="append",
        default=[],
        metavar="FIELD",
        help=(
            "Leave a field out of the compare (repeatable): a column "
            "(QTY(2)), a field name (QTY, every occurrence), or a group "
            "(everything under it). For timestamps, run ids and the like"
        ),
    )
    p.add_argument(
        "--compare-bytes",
        action="store_true",
        help=(
            "Compare raw bytes rather than decoded values (a C and an F sign "
            "nibble then differ), and report bytes no field covers"
        ),
    )
    p.add_argument(
        "--max-differences",
        type=int,
        default=None,
        metavar="N",
        help="Report at most N differing records (the counts stay exact)",
    )
    p.add_argument(
        "--format",
        dest="output_format",
        choices=["text", "json"],
        default="text",
        help="text (default) is a report to read; json is every difference in full",
    )
    _add_record_file_args(p)
    _add_copybook_args(p)
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_compare)


def _compare_fail(message: str) -> NoReturn:
    """Exit 2: ``compare`` keeps 1 for "the files differ", as cmp/diff do."""
    print(f"error: {message}", file=sys.stderr)
    sys.exit(2)


def _cmd_compare(args: argparse.Namespace) -> None:
    from ..generators.data.compare import CompareError, compare_files
    from ..generators.data.decoding import RecordDecoder, RecordDecodingError
    from ..generators.data.errors import CopybookLayoutError

    if args.max_differences is not None and args.max_differences < 0:
        _compare_fail("--max-differences cannot be negative")
    if args.record_length is not None and args.record_length <= 0:
        _compare_fail("--record-length must be a positive number of bytes")
    try:
        decoder = RecordDecoder.from_copybook_file(
            args.copybook,
            record=args.record,
            opts=_decode_encoding_options(args),
            record_length=args.record_length,
            copybook_paths=args.copybook_path or None,
        )
        _warn_layout(decoder.layout_warnings)
        result = compare_files(
            decoder,
            args.expected,
            args.actual,
            view=args.view,
            key=args.key,
            ignore=args.ignore,
            compare_bytes=args.compare_bytes,
            max_differences=args.max_differences,
        )
    except (CompareError, RecordDecodingError, CopybookLayoutError) as exc:
        _compare_fail(str(exc))
    except OSError as exc:
        _compare_fail(f"Cannot read file: {exc}")
    except UnicodeDecodeError as exc:
        # A copybook that is not text (a record file passed as --copybook).
        # Uncaught, the traceback exits 1 -- "the files differ".
        _compare_fail(f"Cannot read copybook {args.copybook}: {exc}")

    if args.output_format == "json":
        text = (
            json.dumps(
                {
                    "expected_file": args.expected,
                    "actual_file": args.actual,
                    "copybook": args.copybook,
                    **result.to_dict(),
                },
                indent=None if args.compact else 2,
            )
            + "\n"
        )
    else:
        text = result.to_text()
    output_path = getattr(args, "output", None)
    if output_path:
        # Not _verbatim_out: its failure exits 1, which here means "differ".
        try:
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(text)
        except OSError as exc:
            _compare_fail(f"Cannot write output file: {exc}")
    else:
        print(text, end="")
    sys.exit(0 if result.equal else 1)


def _build_gen_fixtures_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    p = subparsers.add_parser(
        "gen-fixtures",
        help="Generate program-scoped test fixtures (boundary mocks/asserts) for a COBOL program",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser gen-fixtures INVUPDT.cbl --seed 7 -o fixtures.json\n"
            "  cobol-parser gen-fixtures INVUPDT.cbl --scenarios all --format csv-dir -o fixtures/"
        ),
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
    _add_debug_lines_arg(p)
    p.set_defaults(func=_cmd_gen_fixtures)


def _verification_reasons(verification: dict[str, Any]) -> list[str]:
    """Flatten one scenario's verification verdict into printable reasons.

    Reads the serialized dict rather than the `ScenarioVerification` object
    so this module keeps importing nothing from `generators.verification` --
    the CLI consumes the same shape a bundle consumer would.
    """
    return [
        f"{entry['field']}: {entry['detail']}"
        for entry in verification.get("fields", [])
        if entry.get("status") != "satisfied"
    ] + list(verification.get("gaps", []))


def _cmd_gen_fixtures(args: argparse.Namespace) -> None:
    from ..generators.data.errors import ProgramLayoutError
    from ..generators.program_fixtures import ProgramFixtureGenerator

    generator = ProgramFixtureGenerator()
    copybook_paths = args.copybook_path or None
    callee_paths = args.callee_path or None
    debug_lines = bool(getattr(args, "debug_lines", False))

    if args.list_boundaries:
        try:
            _, _, report = generator.analyze_from_file(
                args.file,
                copybook_paths=copybook_paths,
                callee_paths=callee_paths,
                debug_lines=debug_lines,
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

    from ..generators.data.options import DataGeneratorOptions

    try:
        options = DataGeneratorOptions(rows=args.rows, max_occurs=args.max_occurs)
    except ValueError as exc:
        # `--rows -1`, `--max-occurs 0` or `data.rows: -5` in cobol.yml: a
        # usage error on one line, as `gen-data` reports it, not a traceback.
        _fail(str(exc))

    try:
        generator = ProgramFixtureGenerator(options)
        # analyze + generate rather than generate_with_scenarios_from_file,
        # whose signature is mocky-mock's contract (interface-contract.md):
        # the same two steps, with debug_lines reaching the parse.
        ast, index, report = generator.analyze_from_file(
            args.file,
            copybook_paths=copybook_paths,
            callee_paths=callee_paths,
            debug_lines=debug_lines,
        )
        bundle = generator.generate_with_scenarios(
            ast, index, report, mode=args.scenarios, seed=args.seed
        )
    except ProgramLayoutError as exc:
        _fail(str(exc))

    # Self-verification summary on stderr (stdout stays JSON-only -- see
    # mockymock's `fixtures` contract). A scenario named for a branch arm
    # whose own generated data does not satisfy that arm is the finding
    # users previously had to discover by running each case under a tracer,
    # so it is worth saying out loud even on a successful run.
    unverified = [
        scenario
        for scenario in bundle.scenarios
        if (scenario.verification or {}).get("status") == "unverified"
    ]
    if unverified:
        print(
            f"warning: {len(unverified)} of {len(bundle.scenarios)} scenario(s) "
            f"could not be verified against their own generated data:",
            file=sys.stderr,
        )
        for scenario in unverified:
            print(f"  {scenario.name}:", file=sys.stderr)
            for reason in _verification_reasons(scenario.verification or {}):
                print(f"    - {reason}", file=sys.stderr)

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
    _add_copybook_args(p)
    _add_program_arg(p)
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
            # DynamicCallAnalyzer marks a value set it could not fully
            # resolve (an untracked identifier MOVE source, ...) so the
            # list must not be presented as exhaustive.
            if stmt.get_metadata("possible_values_incomplete"):
                entry["possible_values_incomplete"] = True
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
    _add_copybook_args(p)
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
        from ..preprocess import preprocess_conditional_compilation

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
    from ..analysis.unused_variables import (
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
    _add_copybook_args(p)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    _add_program_arg(p)
    p.set_defaults(func=_cmd_program_flow)


def _cmd_program_flow(args: argparse.Namespace) -> None:
    from ..analysis.program_flow import ProgramFlowAnalyzer

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
        from ..generators.flowchart import FlowchartOptions, MermaidFlowchartGenerator

        gen = MermaidFlowchartGenerator()
        _text_out(gen.generate(report, FlowchartOptions()), output_path)
    elif fmt == "dot":
        from ..generators.flowchart import DotFlowchartGenerator, FlowchartOptions

        gen = DotFlowchartGenerator()  # type: ignore[assignment]
        _text_out(gen.generate(report, FlowchartOptions()), output_path)
    else:
        _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: recursion-check -----------------------------------------------


def _cmd_recursion_check(args: argparse.Namespace) -> None:
    from ..analysis.program_flow import ProgramFlowAnalyzer
    from ..analysis.recursion_risk import RecursionRiskAnalyzer

    ast, prof = _parse_or_fail(args)

    flow_report = ProgramFlowAnalyzer().analyze(ast)
    report = RecursionRiskAnalyzer().analyze(ast, flow_report=flow_report)

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: complexity ----------------------------------------------------


def _cmd_complexity(args: argparse.Namespace) -> None:
    from ..analysis.complexity import ComplexityAnalyzer

    ast, prof = _parse_or_fail(args)

    report = ComplexityAnalyzer().analyze(ast)

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: health ---------------------------------------------------------


def _cmd_health(args: argparse.Namespace) -> None:
    from ..analysis.technical_debt import TechnicalDebtAnalyzer

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
    _add_copybook_args(p)
    _add_program_arg(p)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    _add_min_clone_statements_arg(p)
    p.set_defaults(func=_cmd_redundancy)


def _add_min_clone_statements_arg(p: argparse.ArgumentParser) -> None:
    """The clone-size floor, shared by ``redundancy`` and ``scan``.

    Both subcommands must default to the same number, and to the same one
    ``RedundancyAnalyzer.analyze`` defaults to: a workspace scan and a
    single-file run that disagreed about what counts as a clone would report
    different clone groups for the same program, which reads as a bug in
    whichever one the user ran second.
    """
    p.add_argument(
        "--min-clone-statements",
        type=int,
        default=3,
        metavar="N",
        help=(
            "Smallest paragraph (in leaf statements) eligible to be reported "
            "as a clone. Below this, two trivially-small paragraphs matching "
            "each other is not meaningful redundancy. Default: 3."
        ),
    )


def _cmd_redundancy(args: argparse.Namespace) -> None:
    from ..analysis.redundancy import RedundancyAnalyzer

    ast, prof = _parse_or_fail(args)

    report = RedundancyAnalyzer().analyze(
        ast, min_clone_statements=max(1, args.min_clone_statements)
    )

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: scan ---------------------------------------------------------


def _build_scan_parser(subparsers: argparse._SubParsersAction) -> None:
    from ..scan import ANALYZERS, DEFAULT_ANALYZERS

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


def _collect_scan_files(args: argparse.Namespace) -> list[str]:
    """Explicit paths plus every ``--glob`` expansion, deduped, in order.

    Lifted from ``_cmd_batch``'s own collection, and deliberately identical
    to it: the two subcommands take the same ``files``/``--glob`` pair, and a
    user who learned one spelling should not discover that the other resolves
    duplicates differently.
    """
    import glob as _glob
    from pathlib import Path as _Path

    file_list: list[str] = list(args.files)
    file_list.extend(_read_file_list(getattr(args, "files_from", None)))
    # A directory is no source file: named outright, say so plainly rather
    # than let it fail as an "Encoding error ... Is a directory" (#737).
    for path in file_list:
        if _Path(path).is_dir():
            pattern = str(_Path(path) / "**" / "*.cbl")
            _fail(
                f"{path} is a directory; pass the files in it, e.g. "
                f"--glob '{pattern}'"
            )
    for pattern in args.glob:
        # ``**`` also matches the directories on the way down.
        expanded = sorted(
            p for p in _glob.glob(pattern, recursive=True) if not _Path(p).is_dir()
        )
        if not expanded:
            print(
                f"warning: glob pattern {pattern!r} matched no files", file=sys.stderr
            )
        file_list.extend(expanded)

    # Dedup on the resolved path so ./a.cbl, a.cbl and /abs/a.cbl are one file.
    seen: set[str] = set()
    unique: list[str] = []
    for path in file_list:
        key = str(_Path(path).resolve())
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def _read_file_list(source: str | None) -> list[str]:
    """Paths from a list file, one per line. ``-`` reads stdin.

    Blank lines and ``#`` comments are skipped so the file can be generated
    with a header, and each line is stripped -- a trailing ``\r`` from a
    list written on Windows would otherwise become part of the path and the
    file would be reported as unreadable with a confusing name.
    """
    if not source:
        return []
    if source == "-":
        text = sys.stdin.read()
    else:
        from pathlib import Path as _Path

        try:
            text = _Path(source).read_text(encoding="utf-8")
        except OSError as exc:
            _fail(f"--files-from could not be read: {exc}")
    out: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def _cmd_scan(args: argparse.Namespace) -> None:
    from ..scan import (
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
    )

    try:
        report = scan_files(files, options, workers=args.workers)
    except ValueError as exc:
        # An unknown --analyzer name. argparse `choices` would reject the
        # comma-separated spelling this flag accepts, so the check lives in
        # scan_files and its message is already the one to print.
        _fail(str(exc))

    if sarif:
        from ..analysis.sarif import (
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
        "is_ims_program": ast.has_ims() or ast.uses_ims_interface(),
        "entry_points": entry_points_out,
        "dli_call_count": len(calls_out),
        "all_segments": all_segments,
        "dli_calls": calls_out,
    }

    _emit_report(output, args, ast=ast)


# -- Subcommand: lint ---------------------------------------------------------


def _build_lint_parser(subparsers: argparse._SubParsersAction) -> None:
    from ..analysis.lint import ALL_RULES, SEVERITIES

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
            "  cobol-parser lint src/PAYMAIN.cbl --callee-path src/ --rule call-check\n"
            "\nMore than one file, --glob, --files-from or --changed-since lints\n"
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
    _add_copybook_args(p)
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
        "--min-severity",
        choices=list(SEVERITIES),
        default="info",
        help=(
            "Drop findings below this severity from the output (default: "
            "info, i.e. keep everything). Filtering happens after the rules "
            "run, so the summary counts describe what is shown."
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
        )
    return "\n".join(lines)


def _lint_copybook_item_names(args: argparse.Namespace, ast: Any) -> set[str] | None:
    """Names that reached *ast* through an expanded COPY, or None if unknown.

    Same set-difference provenance trick as ``_cmd_unused_variables`` (see
    ``_parse_without_copybook_expansion``), and for the same reason: it is
    what lets lint grade an unused copybook field as info rather than
    warning. Without --copybook-path there is nothing to diff against, so
    the answer is "unknown" -- which the analyzer reads as "none came from a
    copybook", the same as it does for the unused-variables subcommand.

    Both sides of the diff cover EVERY program unit, because lint does:
    ``collect_declared_items`` is program-scoped, so diffing the outermost
    unit alone would leave a contained program's copybook fields out of the
    set and grade them as the program's own -- warning instead of info --
    for exactly the multi-program file this covers in the first place.
    """
    from ..analysis.unused_variables import collect_declared_items

    if not getattr(args, "copybook_path", []):
        return None
    unexpanded_result = _parse_without_copybook_expansion(args)
    if unexpanded_result.ast is None:
        print(
            f"warning: {args.file} could not be parsed without copybook "
            "expansion; copybook-origin detection disabled",
            file=sys.stderr,
        )
        return None

    def declared_across_units(program: Any) -> set[str]:
        return {
            item.name.upper()
            for unit in program.program_units()
            for item in collect_declared_items(unit)
        }

    # Both sides must cover the same scope. `ast` is already narrowed when
    # --program named a unit, so narrow the unexpanded parse the same way --
    # otherwise another unit's own declaration of the same name would
    # subtract from this one's copybook set.
    local_root = unexpanded_result.ast
    wanted = getattr(args, "program", None)
    if wanted:
        local_root = local_root.find_program_unit(wanted) or local_root

    return declared_across_units(ast) - declared_across_units(local_root)


def _lint_column_offset(
    args: argparse.Namespace,
) -> Callable[[str, int], int | None]:
    """``(file, line) -> offset`` for lint (#301); see
    :func:`cobolparser.analysis.lint.source_column_offsets`."""
    from ..analysis.lint import source_column_offsets

    return source_column_offsets(
        args.file, _source_format_kwargs(args)["preprocess_fixed"]
    )


def _severity_at_least(severity: str, threshold: str) -> bool:
    """True when *severity* is as severe as *threshold*, or more so."""
    from ..analysis.lint import SEVERITIES

    return SEVERITIES.index(severity) <= SEVERITIES.index(threshold)


def _lint_one(args: argparse.Namespace) -> tuple[Any, Any, Any]:
    """Lint ``args.file``: ``(report, prof, ast)``, the report filtered by
    ``--min-severity`` and every finding placed on disk. Exits 1 through
    :func:`_fail` when the file cannot be read or parsed at all."""
    from ..analysis.lint import (
        CALL_CHECK_RULE,
        LINE_LENGTH_RULE,
        LintAnalyzer,
        add_call_check_findings,
        add_line_length_findings,
        add_parse_errors,
        apply_source_map,
        filter_by_severity,
    )

    result, prof = _parse_result_or_fail(args)
    ast = result.ast

    selected = getattr(args, "rules", None)
    try:
        analyzer = LintAnalyzer(selected)
    except (
        ValueError
    ) as e:  # unreachable via argparse choices; direct callers can hit it
        _fail(str(e))

    report = analyzer.analyze(
        ast,
        copybook_item_names=(
            _lint_copybook_item_names(args, ast) if analyzer.rules else None
        ),
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
    report.findings = filter_by_severity(report.findings, args.min_severity)

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
    from ..analysis.call_interface import CalleeResolver

    copybooks = tuple(getattr(args, "copybook_path", None) or [])
    key = (tuple(callee_paths), copybooks)
    if key not in _LINT_CALLEE_RESOLVERS:
        _LINT_CALLEE_RESOLVERS[key] = CalleeResolver(
            callee_paths,
            copybook_paths=list(copybooks),
            debug_lines=bool(getattr(args, "debug_lines", False)),
        )
    return _LINT_CALLEE_RESOLVERS[key]


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
    ):
        print(
            "error: lint needs a FILE, --glob, --files-from or --changed-since",
            file=sys.stderr,
        )
        sys.exit(2)
    _lint_many(args)


def _lint_single(args: argparse.Namespace) -> None:
    """One FILE: the report shapes ``lint`` has always printed."""
    report, prof, ast = _lint_one(args)

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
        from ..analysis.sarif import lint_notifications, lint_results, sarif_log

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
    from ._changed_files import (
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
        _fail(f"--changed-since: {exc}")
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
    """Lint one file of a multi-file run: ``(report, ast, None)``, or
    ``(None, None, why)`` when it could not be linted. Its diagnostics still
    reach stderr; a failure never stops the other files."""
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
    return report, ast, None


def _drop_repeated_layout_findings(linted: list[tuple[str, Any, Any]]) -> None:
    """Keep each ``line-length`` finding once per run.

    It is a fact about a line of a file, not about the program that read it:
    a copybook COPYed by twenty linted programs would otherwise print the
    same finding twenty times. The first program to report it keeps it.
    """
    from pathlib import Path

    from ..analysis.lint import LINE_LENGTH_RULE

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
    files, selection = _lint_selection(args)
    if not files and selection is None:
        _fail("No input files: the FILE arguments, --glob and --files-from named none.")
    if not files:
        print(
            f"note: no COBOL program changed since {args.changed_since}; "
            "nothing to lint",
            file=sys.stderr,
        )

    linted: list[tuple[str, Any, Any]] = []
    failures: list[tuple[str, str]] = []
    for path in files:
        report, ast, why = _lint_one_isolated(args, path)
        if report is None:
            failures.append((path, why or "could not be linted"))
        else:
            linted.append((path, report, ast))

    _drop_repeated_layout_findings(linted)

    fmt = args.output_format
    output = getattr(args, "output", None)
    totals = {
        "error": sum(r.error_count for _, r, _ in linted),
        "warning": sum(r.warning_count for _, r, _ in linted),
        "info": sum(r.info_count for _, r, _ in linted),
    }
    total = sum(totals.values())
    summary_line = (
        f"{total} finding(s) in {len(linted)} file(s): {totals['error']} error, "
        f"{totals['warning']} warning, {totals['info']} info"
        + (f"; {len(failures)} file(s) could not be linted" if failures else "")
    )

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
        from ..analysis.sarif import (
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
        for path, report, ast in linted:
            one = argparse.Namespace(file=path)
            entry = _identification(one, ast)
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
            },
        }
        if selection is not None:
            document["changed_since"] = {
                "ref": args.changed_since,
                "changed_files": selection.changed,
                "via_copybook": selection.via_copybook,
            }
        _json_out(document, args.compact, output)

    if fmt not in ("text", "github"):
        print(summary_line, file=sys.stderr)
    if failures:
        sys.exit(1)
    fail_on = getattr(args, "fail_on", "never")
    if any(_lint_fails(report, fail_on) for _, report, _ in linted):
        sys.exit(3)


# -- Subcommand: data-items ----------------------------------------------------


def _cmd_dclgen_check(args: argparse.Namespace) -> None:
    from ..analysis.dclgen_check import DclgenChecker

    ast, prof = _parse_or_fail(args)
    report = DclgenChecker().check(ast)
    _emit_report(report.to_dict(), args, prof, ast)


def _cmd_data_items(args: argparse.Namespace) -> None:
    from ..generators.data.layout_offsets import compute_program_data_items

    args._wrap_copybook_fragment = True
    ast, prof = _parse_or_fail(args)
    if ast.data_division is None:
        # Nothing to lay out: say so rather than print `"items": []` and
        # exit 0, which reads as "this file declares no data".
        _fail(f"{args.file}: no DATA DIVISION found; no data items to report")

    output = compute_program_data_items(ast)

    _emit_report(output, args, prof, ast)


# -- Subcommand: le-info ------------------------------------------------------


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
    from ..analysis.program_signature import extract_signatures

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
    from ..analysis.xref import XrefAnalyzer

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
    _add_copybook_args(p)
    _add_program_arg(p)
    _add_define_args(p)
    _add_output_arg(p)
    _add_profiling_args(p)
    p.set_defaults(func=_cmd_business_rules)


def _cmd_business_rules(args: argparse.Namespace) -> None:
    from ..analysis.business_rules import BusinessRuleExtractor

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
    _add_copybook_args(p)
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
    from ..analysis.field_lineage import FieldFlowAnalyzer, apply_source_map

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
        from ..analysis.lineage_graph import LineageGraph

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
) -> tuple[list[dict[str, Any]], list[str]]:
    """Every lineage report under *targets* and the problems (files that
    produced none); exits when there is no report at all."""
    from ..analysis.lineage_graph import reports_from_scan
    from ..scan import ScanOptions, scan_files

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
        ),
        workers=args.workers,
    )
    reports, problems = reports_from_scan(scan)
    if not reports:
        for problem in problems:
            print(problem, file=sys.stderr)
        _fail("no COBOL program under the given paths produced a lineage report")
    return reports, problems


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
        from ..analysis.lineage_jcl import bindings_from_jobs, load_jobs

        try:
            jobs, problems = load_jobs(args.jcl, proc_path=args.proc_path)
        except ImportError:
            _fail("--jcl needs jcl-parser: pip install jcl-parser")
        found, carried = bindings_from_jobs(jobs, caveats)
        bindings += found
        passthroughs += carried
    return bindings, passthroughs, problems, caveats


def _cmd_field_impact(args: argparse.Namespace) -> None:
    from ..analysis.lineage_graph import LineageGraph

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

    reports, problems = _lineage_reports(args, targets)
    bindings, passthroughs, jcl_problems, jcl_caveats = _load_bindings(args)
    graph = LineageGraph(reports, bindings, passthroughs, join_caveats=jcl_caveats)

    if args.table:
        result = graph.impact_table(args.table, args.direction, args.depth)
    elif args.dataset:
        result = graph.impact_dataset(args.dataset, args.direction, args.depth)
    else:
        assert field_name is not None
        result = graph.impact(field_name, args.program, args.direction, args.depth)

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
        _fail(f"{', '.join(result.start)}: no such field in any report")


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
    from ..analysis.field_widening import FieldWideningAnalyzer
    from ..analysis.lineage_graph import LineageGraph

    targets = list(args.targets)
    field_name = args.field
    if args.workers is not None and args.workers < 1:
        _fail("--workers must be >= 1")
    if args.depth is not None and args.depth < 0:
        _fail("--depth must be >= 0")
    reports, problems = _lineage_reports(args, targets)
    bindings, passthroughs, jcl_problems, jcl_caveats = _load_bindings(args)
    graph = LineageGraph(reports, bindings, passthroughs, join_caveats=jcl_caveats)
    report = FieldWideningAnalyzer(graph).analyze(
        field_name,
        args.new_picture,
        program=args.program,
        new_usage=args.new_usage,
        depth=args.depth,
    )
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
        _fail(f"{field_name.upper()}: no such field in any report")
    if not report.starts:
        _fail(f"{field_name.upper()}: nothing to check (see caveats)")
    worst = report.worst_severity()
    if (
        args.fail_on != "never"
        and worst is not None
        and _severity_at_least(worst, args.fail_on)
    ):
        sys.exit(3)


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
    from ..analysis.ast_diff import ProgramDiffer

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
    from ..analysis.codebase import CodebaseGraphBuilder

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
    from ..analysis.codebase import CopybookImpactAnalyzer

    graph = _build_graph(args)
    report = CopybookImpactAnalyzer(graph).analyze(args.member)

    _json_out(report.to_dict(), args.compact, getattr(args, "output", None))
    _exit_on_graph_errors(graph)


# -- Subcommand: call-check ---------------------------------------------------


def _build_call_check_parser(subparsers: argparse._SubParsersAction) -> None:
    from ..analysis.call_interface import SEVERITIES

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
    from ..analysis.codebase import DEFAULT_PROGRAM_EXTENSIONS

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
    from ..analysis.call_interface import SEVERITIES, CallInterfaceChecker

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
        from ..analysis.sarif import (
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


# -- Subcommand: sql-cics-check -----------------------------------------------


def _cmd_sql_cics_check(args: argparse.Namespace) -> None:
    from ..analysis.sql_cics_lint import SqlCicsAnalyzer

    ast, prof = _parse_or_fail(args)

    report = SqlCicsAnalyzer().analyze(ast)

    _emit_report(report.to_dict(), args, prof, ast)


# -- Subcommand: jcl ----------------------------------------------------------


def _build_jcl_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "jcl",
        help="Parse z/OS JCL: which program each step runs, and which dataset "
        "each DD name is bound to",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  cobol-parser jcl JOB.jcl\n"
            "  cobol-parser jcl JOB.jcl --dd-map\n"
            "  cobol-parser jcl JOB.jcl --bindings\n"
            "  cobol-parser jcl JOB.jcl --program INVUPDT\n"
            "  cobol-parser jcl JOB.jcl --proc-path proclib/ --bindings\n"
            "  cobol-parser jcl JOB.jcl --strict"
        ),
    )
    p.add_argument("file", help="Path to the JCL file")
    p.add_argument(
        "--dd-map",
        action="store_true",
        help="Emit only the DD name -> datasets mapping, which is what a "
        "COBOL SELECT ... ASSIGN TO ddname resolves through",
    )
    p.add_argument(
        "--bindings",
        action="store_true",
        help="Emit one row per DD binding (ddname, dataset, step, job, DISP, "
        "RECFM, LRECL, program) instead of the job structure; usable as "
        "field-impact --bindings input",
    )
    p.add_argument(
        "--program",
        metavar="NAME",
        help="Report only the steps that run this program",
    )
    p.add_argument(
        "--proc-path",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory holding cataloged procedures and INCLUDE members, one "
        "member per file named after it (repeatable, searched in order). "
        "Without it only in-stream procedures are expanded",
    )
    p.add_argument(
        "--strict",
        action="store_true",
        help="Exit 3 when any card could not be parsed (a CI gate, kept "
        "distinct from exit 1, which still means the run itself failed)",
    )
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_jcl)


def _cmd_jcl(args: argparse.Namespace) -> None:
    """Parse a JCL file.

    The only subcommand that reads a language other than COBOL, so it shares
    none of the COBOL parse flags -- there is no dialect, no source format
    and no copybook path to honour. What it exists for is the join: a COBOL
    ``SELECT INV-FILE ASSIGN TO INVFILE`` names a DD, and only the JCL says
    which dataset that DD is.
    """
    from ..jcl import parse_jcl, resolve_dd_bindings

    source = _read_source(args.file)
    try:
        result = parse_jcl(
            source, filename=args.file, proc_paths=getattr(args, "proc_path", None)
        )
    except ImportError as exc:
        # jcl-parser is the optional [jcl] extra: a plain install is a
        # configuration error to name on one line (the install hint), not a
        # traceback.
        _fail(str(exc))

    payload: dict[str, Any]
    if args.bindings:
        bindings = resolve_dd_bindings(result)
        if args.program:
            # Keyed by job as well as step name: in a deck of several jobs,
            # `S1` of another job runs another program, and its DDs are not
            # this program's.
            running = {id(s) for s in result.steps_running(args.program)}
            wanted = {
                (id(job), step.name)
                for job in result.jobs
                for step in job.steps
                if id(step) in running
            }
            bindings = [
                binding
                for binding, (job, _step, _dd) in zip(
                    bindings, result.all_dd_statements(), strict=True
                )
                if (id(job), binding.step) in wanted
            ]
        payload = {"bindings": [b.to_dict() for b in bindings]}
    elif args.dd_map:
        dd_map = result.dd_map()
        if args.program:
            # Only the DDs of the steps that run this program, exactly as
            # ``--bindings --program`` filters; ``--dd-map --program`` used
            # to return every step's DDs and silently ignore the program.
            # The datasets too come from those steps only: a DD name shared
            # with another step (SYSTSIN, SYSIN) must not bring its datasets.
            running = {id(s) for s in result.steps_running(args.program)}
            dd_map = {}
            for _job, owner, dd in result.all_dd_statements():
                if owner is None or id(owner) not in running:
                    continue
                bucket = dd_map.setdefault(dd.name.upper(), [])
                if dd.dataset is not None and dd.dataset not in bucket:
                    bucket.append(dd.dataset)
        payload = {"dd_map": dd_map}
    elif args.program:
        payload = {
            "program": args.program,
            "steps": [s.to_dict() for s in result.steps_running(args.program)],
        }
    else:
        payload = result.to_dict()

    # Errors and unresolved travel with every view, not just the default
    # one: a --dd-map that silently omitted the cards it could not read
    # would be the exact failure mode this repo's reports exist to avoid.
    payload.setdefault(
        "errors", [{"line": e["line"], "message": e["message"]} for e in result.errors]
    )
    payload.setdefault("unresolved", list(result.unresolved))

    _json_out(
        {"source_file": args.file, **payload},
        args.compact,
        getattr(args, "output", None),
    )

    if args.program and not result.steps_running(args.program):
        # Like every analyzer's --program: an empty answer for a name that
        # matches nothing must not read as "this JCL never runs it" quietly.
        _fail(f"--program {args.program}: no step in {args.file} runs it")
    if args.strict and result.errors:
        sys.exit(3)


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
    from ..dialects.le_signatures import (
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


# -- config subcommand --------------------------------------------------------


def _build_config_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "config",
        help="Show the effective cobol.yml project config and where it came from",
        description=(
            "Report which cobol.yml/cobol.yaml is in effect for the current "
            "directory and every setting it supplies. Settings the file does "
            "not mention are omitted rather than shown at their built-in "
            "default, so what is printed is exactly what the file changes."
        ),
        epilog=(
            "Examples:\n"
            "  cobol-parser config\n"
            "  cobol-parser config --json\n"
            "  cobol-parser --config ./other/cobol.yml config"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_config)


def _build_mcp_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "mcp",
        help="Serve COBOL analysis tools to AI agents over MCP (stdio)",
        description=(
            "Run a Model Context Protocol server on stdin/stdout, answering "
            "questions about the COBOL under --root: read_source, lint and "
            "explain_symbol. Every location in an answer is a file and line "
            "on disk, and every answer names what could not be checked. "
            "cobol.yml is read from --root itself (never from a parent "
            "directory). Under a copybook directory outside --root only "
            "copybook members are readable, and /, the home directory, their "
            "ancestors, hidden and system directories are refused as copybook "
            "directories. Needs the [mcp] extra."
        ),
        epilog=(
            "Examples:\n"
            "  cobol-parser mcp --root /path/to/checkout\n"
            "  claude mcp add cobol -- cobol-parser mcp --root /path/to/checkout"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--root",
        default=".",
        help="Directory the server answers about; files outside it (and its "
        "copybook directories) are refused (default: the current directory)",
    )
    p.add_argument(
        "--cache-size",
        type=int,
        default=32,
        metavar="N",
        help="Parsed programs to keep in memory (default: 32)",
    )
    p.add_argument(
        "--tools",
        default="auto",
        metavar="SPEC",
        help="Tools to offer: auto (default: core, plus the JCL tools when "
        "the root holds JCL), all, or a comma-separated list of groups "
        "(core, data, jcl) and tool names. Every tool's definition is sent "
        "to the model on every turn, so fewer tools cost fewer tokens",
    )
    p.add_argument(
        "--max-answer-bytes",
        type=int,
        default=None,
        metavar="N",
        help="Size budget of one tool result: longer lists are halved until "
        "it fits, each cut listed under truncated (default: 24000; 0: none)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Processes that parse programs for the cross-program indexes "
        "(default: the CPUs, at most 8; 1: parse in the server process)",
    )
    p.add_argument(
        "--cache-dir",
        default=None,
        metavar="DIR",
        help="Where per-file facts are kept between server starts, so a "
        "restarted server parses only what changed (default: "
        "$XDG_CACHE_HOME/cobol-parser/mcp, else ~/.cache/cobol-parser/mcp)",
    )
    p.add_argument(
        "--no-disk-cache",
        action="store_true",
        help="Keep facts in memory only: every start parses the whole root",
    )
    p.add_argument(
        "--no-warm-up",
        action="store_true",
        help="Do not parse the root in the background at start; the first "
        "cross-program question does it instead",
    )
    p.set_defaults(func=_cmd_mcp)


def _cmd_mcp(args: argparse.Namespace) -> None:
    try:
        from ..mcp.server import run_stdio
    except ImportError as exc:
        _fail(
            "the MCP server needs the [mcp] extra: "
            f"pip install 'cobol-parser[mcp]' ({exc})"
        )
    from ..mcp.envelope import ToolError
    from ..mcp.server import select_tools
    from ..mcp.workspace import Workspace

    config = args._project_config if getattr(args, "_config_explicit", False) else None
    try:
        workspace = Workspace(args.root, config, cache_size=args.cache_size)
    except (ToolError, ConfigError) as exc:
        _fail(str(exc))
    for directory, reason in workspace.refused_copybook_dirs:
        # stderr: over stdio, stdout is the protocol channel.
        print(
            f"warning: copybook directory {directory} (from "
            f"{workspace.config.source}) is refused, so it is not searched or "
            f"readable: {reason}",
            file=sys.stderr,
        )
    try:
        select_tools(args.tools, workspace)
    except ValueError as exc:
        _fail(str(exc))
    from ..mcp.envelope import DEFAULT_ANSWER_BYTES

    budget = (
        DEFAULT_ANSWER_BYTES if args.max_answer_bytes is None else args.max_answer_bytes
    )
    if budget < 0:
        _fail("--max-answer-bytes must be 0 or more")
    from ..mcp.facts import FactsStore, default_cache_dir

    if args.workers is not None and args.workers < 1:
        _fail("--workers must be 1 or more")
    workspace.facts_store = FactsStore(
        workspace,
        workers=args.workers,
        cache_dir=(
            None if args.no_disk_cache else (args.cache_dir or default_cache_dir())
        ),
    )
    run_stdio(workspace, args.tools, budget or None, warm_up=not args.no_warm_up)


def _config_to_dict(config: ProjectConfig) -> dict[str, Any]:
    """The loaded config as JSON, with unset keys left out entirely."""

    def prune(mapping: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in mapping.items() if v not in (None, (), [], {})}

    return {
        "config_file": str(config.source) if config.source else None,
        "version": config.version,
        "project": prune(
            {
                "copybook_path": list(config.copybook_path),
                "callee_path": list(config.callee_path),
                "proc_path": list(config.proc_path),
                "source_format": config.source_format,
                "debug_lines": config.debug_lines,
                "dialect": config.dialect,
                "error_recovery": config.error_recovery,
                "seed": config.seed,
                "extensions": list(config.extensions),
                "define": list(config.define),
            }
        ),
        "data": prune(
            {
                "charset": config.data.charset,
                "endian": config.data.endian,
                "record_format": config.data.record_format,
                "record_separator": config.data.record_separator,
                "rows": config.data.rows,
            }
        ),
        "lint": prune(
            {
                "rules": list(config.lint.rules),
                "min_severity": config.lint.min_severity,
                "fail_on": config.lint.fail_on,
            }
        ),
        "tools": dict(config.tools),
        # Present only when some path entry is not a directory (#550).
        **(
            {"missing_directories": [path for _, path in missing]}
            if (missing := config.missing_directories())
            else {}
        ),
    }


def _cmd_config(args: argparse.Namespace) -> None:
    config: ProjectConfig = getattr(args, "_project_config", None) or ProjectConfig()
    payload = _config_to_dict(config)

    if args.json:
        _json_out(payload, args.compact, args.output)
        return

    lines: list[str] = []
    if config.source is None:
        lines.append("No cobol.yml found (searched upward from the current directory).")
        lines.append("")
        lines.append("Create one to set copybook paths, source format, dialect and")
        lines.append("record encoding once for every tool that reads it.")
        _text_out("\n".join(lines), args.output)
        return

    lines.append(f"Config file: {config.source}")
    lines.append(f"Schema version: {config.version}")
    missing = set(payload.get("missing_directories", ()))
    for section in ("project", "data", "lint"):
        values = payload[section]
        if not values:
            continue
        lines.append("")
        lines.append(f"[{section}]")
        for key, value in values.items():
            if isinstance(value, list):
                lines.append(f"  {key}:")
                lines.extend(
                    f"    - {entry}"
                    + (
                        "  (not an existing directory)"
                        if key in ("copybook_path", "callee_path", "proc_path")
                        and entry in missing
                        else ""
                    )
                    for entry in value
                )
            elif isinstance(value, bool):
                # Spelled the way the file spells it, not Python's True.
                lines.append(f"  {key}: {'true' if value else 'false'}")
            else:
                lines.append(f"  {key}: {value}")
    for name, section_data in payload["tools"].items():
        lines.append("")
        lines.append(f"[{name}]  (read by that tool, not by cobol-parser)")
        for key, value in section_data.items():
            lines.append(f"  {key}: {value}")
    _text_out("\n".join(lines), args.output)


# -- Top-level parser with subcommands ----------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    from .. import __version__

    parser = _help.TopLevelParser(
        prog="cobol-parser",
        usage="cobol-parser <command> [options] FILE ...",
        description="Parse, tokenize, preprocess, and analyze COBOL source files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    # Declared for --help only. main() strips both out of argv before
    # argparse runs (see _project_config.extract_config_flags), so they work
    # on either side of the subcommand and cannot be mistaken for a source
    # file by the legacy "prepend parse" rewrite below.
    parser.add_argument(
        "--config", metavar="FILE", default=None, help=_project_config.CONFIG_FLAG_HELP
    )
    parser.add_argument(
        "--no-config",
        action="store_true",
        help=_project_config.NO_CONFIG_FLAG_HELP,
    )
    subparsers = parser.add_subparsers(
        dest="command", metavar="<command>", prog="cobol-parser"
    )

    _build_parse_parser(subparsers)
    _build_batch_parser(subparsers)
    _build_tokenize_parser(subparsers)
    _build_preprocess_parser(subparsers)
    _build_expand_parser(subparsers)
    _build_gen_data_parser(subparsers)
    _build_decode_parser(subparsers)
    _build_compare_parser(subparsers)
    _build_gen_fixtures_parser(subparsers)
    _build_analyzer_parser(
        subparsers,
        "analyze",
        "Analyze dynamic CALL targets in COBOL source",
        _cmd_analyze,
        profiling=True,
        examples="  cobol-parser analyze program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "dead-code",
        "Detect unreachable paragraphs/sections (dead code)",
        _cmd_dead_code,
        profiling=True,
        examples="  cobol-parser dead-code program.cbl",
    )
    _build_unused_variables_parser(subparsers)
    _build_program_flow_parser(subparsers)
    _build_analyzer_parser(
        subparsers,
        "recursion-check",
        "Detect PERFORM/GO TO cycles and self-recursive CALLs that risk an "
        "infinite loop",
        _cmd_recursion_check,
        profiling=True,
        examples="  cobol-parser recursion-check program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "complexity",
        "Compute per-paragraph cyclomatic complexity and maintainability metrics",
        _cmd_complexity,
        profiling=True,
        examples="  cobol-parser complexity program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "health",
        "Compute a composite technical-debt score (complexity, redundancy, "
        "control-flow smells, size) with a top-offenders breakdown",
        _cmd_health,
        profiling=True,
        examples="  cobol-parser health program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "io-sequence",
        "Validate file I/O operation ordering (OPEN/READ/WRITE/CLOSE lifecycle)",
        _cmd_io_sequence,
        examples="  cobol-parser io-sequence program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "move-type-check",
        "Check MOVE statement data category compatibility",
        _cmd_move_type_check,
        examples="  cobol-parser move-type-check program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "linkage-check",
        "Validate LINKAGE SECTION items against CALL/ENTRY USING clauses",
        _cmd_linkage_check,
        examples="  cobol-parser linkage-check program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "language-env",
        "Detect COBOL intrinsic functions and IBM Language Environment service calls",
        _cmd_language_env,
        examples="  cobol-parser language-env program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "ims-dli",
        "Extract IMS DLI segment references from CBLTDLI/AIBTDLI/CEETDLI calls",
        _cmd_ims_dli,
        examples="  cobol-parser ims-dli program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "dclgen-check",
        "Cross-check EXEC SQL host variables against the DCLGEN DECLARE TABLE "
        "columns they bind to (type, scale, precision, length, sign, null "
        "indicator)",
        _cmd_dclgen_check,
        profiling=True,
        examples="  cobol-parser dclgen-check program.cbl",
    )
    _build_redundancy_parser(subparsers)
    _build_scan_parser(subparsers)
    _build_lint_parser(subparsers)
    _build_analyzer_parser(
        subparsers,
        "data-items",
        "Compute byte offset, byte length, REDEFINES chains, and level-88 "
        "condition values for every data item in the program",
        _cmd_data_items,
        profiling=True,
        examples="  cobol-parser data-items program.cbl",
    )
    _build_analyzer_parser(
        subparsers,
        "program-signature",
        "Report a program's calling interface: every entry point's USING "
        "operands joined to their LINKAGE declarations, with the direction "
        "the callee uses each one in",
        _cmd_program_signature,
        profiling=True,
        examples=(
            "  cobol-parser program-signature SUBPGM.cbl\n"
            "  cobol-parser program-signature SUBPGM.cbl --copybook-path ./copybooks"
        ),
    )
    _build_analyzer_parser(
        subparsers,
        "xref",
        "Cross-reference listing: every symbol's definition and every "
        "reference to it, with the role each reference plays",
        _cmd_xref,
        profiling=True,
        examples="  cobol-parser xref program.cbl",
    )
    _build_diff_parser(subparsers)
    _build_codebase_graph_parser(subparsers)
    _build_copybook_impact_parser(subparsers)
    _build_call_check_parser(subparsers)
    _build_analyzer_parser(
        subparsers,
        "sql-cics-check",
        "Lint embedded SQL and CICS: unchecked SQLCODE, dynamic SQL built by "
        "concatenation, hardcoded credentials, CICS commands with no RESP or "
        "HANDLE CONDITION",
        _cmd_sql_cics_check,
        profiling=True,
        examples="  cobol-parser sql-cics-check program.cbl",
    )
    _build_business_rules_parser(subparsers)
    _build_lineage_parser(subparsers)
    _build_field_impact_parser(subparsers)
    _build_widen_check_parser(subparsers)
    _build_jcl_parser(subparsers)
    _build_le_info_parser(subparsers)
    _build_config_parser(subparsers)
    _build_mcp_parser(subparsers)

    return parser


def _config_fail(message: str, argv: list[str]) -> NoReturn:
    """A config error before the subcommand ran.

    Exit 1 like every other failure -- except for ``compare``, whose exit 1
    means "the files differ": a CI gate reading that status would report a
    missing or malformed ``cobol.yml`` as a data regression.
    """
    subcommand = next((arg for arg in argv if not arg.startswith("-")), None)
    if subcommand == "compare":
        _compare_fail(message)
    _fail(message)


def _warn_missing_search_dirs(args: argparse.Namespace, config: ProjectConfig) -> None:
    """Warn once per ``--copybook-path`` / ``--callee-path`` / ``--proc-path``
    entry typed on the command line that is not a directory.

    A typo there was silently accepted and only showed up later as COPY
    statements that were "not found". Entries that came from cobol.yml are
    already reported by name (with the file) in :func:`main`.
    """
    from_config = {
        entry
        for entries in (config.copybook_path, config.callee_path, config.proc_path)
        for entry in entries
    }
    for dest, flag in (
        ("copybook_path", "--copybook-path"),
        ("callee_path", "--callee-path"),
        ("proc_path", "--proc-path"),
    ):
        value = getattr(args, dest, None)
        entries = [value] if isinstance(value, str) else list(value or [])
        for entry in entries:
            if entry in from_config or os.path.isdir(entry):
                continue
            print(
                f"warning: {flag} {entry} is not an existing directory", file=sys.stderr
            )


def _reject_mistyped_command(word: str) -> None:
    """Exit 2 when *word* reads as a typo of a command, not a file name.

    The legacy ``cobol-parser FILE`` form means any unknown first word is
    taken as a source file, so ``cobol-parser dead-cod x.cbl`` used to say
    "File not found: dead-cod". A word that exists on disk, or has a path
    separator or an extension, is still a file.
    """
    if os.path.exists(word) or os.sep in word or "/" in word or "." in word:
        return
    suggestion = _help.suggest_command(word, _SUBCOMMANDS)
    if suggestion is None:
        return
    print(
        f"error: unknown command '{word}' (did you mean '{suggestion}'?)\n"
        "Run 'cobol-parser --help' to list every command.",
        file=sys.stderr,
    )
    sys.exit(2)


def main() -> None:
    argv = sys.argv[1:]

    # --config/--no-config are pulled out first so they may appear on either
    # side of the subcommand, and so the legacy rewrite below cannot mistake
    # a config path for a source file.
    try:
        argv, config_path, config_disabled = _project_config.extract_config_flags(argv)
    except ConfigError as exc:
        _config_fail(str(exc), argv)

    if not argv:
        # A bare `cobol-parser` used to fall through to `parse` and print
        # only "the following arguments are required: file". Show the grouped
        # command overview instead; still a usage error (exit 2).
        _build_parser().print_help()
        sys.exit(2)

    # Backward compatibility: if the first non-flag argument is not a known
    # subcommand, assume the user is using the legacy syntax and prepend "parse".
    first_positional = next((arg for arg in argv if not arg.startswith("-")), None)
    if first_positional is not None and first_positional not in _SUBCOMMANDS:
        _reject_mistyped_command(first_positional)
        argv = ["parse", *argv]
    elif first_positional is None and not {"-h", "--help", "--version"} & set(argv):
        argv = ["parse", *argv]

    parser = _build_parser()
    args = parser.parse_args(argv)

    # Loaded even when nothing is found (an all-default ProjectConfig), so
    # `cobol-parser config` can report the "no file anywhere" case, and so a
    # malformed file is an error naming it rather than a silent fallback.
    if config_disabled:
        config = ProjectConfig()
    else:
        try:
            config = load_project_config(path=config_path)
        except ConfigError as exc:
            _config_fail(str(exc), argv)
    args._project_config = config
    # `mcp` searches for cobol.yml from its --root, not the cwd, unless the
    # user named a file or turned config off.
    args._config_explicit = config_path is not None or config_disabled

    if config.source is not None:
        # The second parse (see cli/_project_config) is what separates a flag
        # the user typed from one that merely defaulted; it only runs when
        # there is a config file with something to say.
        args_provided = _project_config.provided_dests(_build_parser, argv)
        _project_config.apply_project_config(args, config, args_provided)
        for key in _project_config.unapplied_parse_settings(args, config):
            # Silently dropped before: the subcommand then analysed a
            # different program than the single-file ones do (#324).
            print(
                f"warning: {config.source} sets {key}, but "
                f"`{getattr(args, 'command', None) or 'parse'}` has no flag "
                "for it and parses without it",
                file=sys.stderr,
            )
        for key, missing in config.missing_directories():
            # Only for a path this run actually takes from the file: one the
            # subcommand reads and the user did not override (#550).
            dest = key.split(".", 1)[1]
            if hasattr(args, dest) and dest not in args_provided:
                print(
                    f"warning: {config.source} {key} entry {missing} is not "
                    "an existing directory",
                    file=sys.stderr,
                )

    _warn_missing_search_dirs(args, config)

    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(1)

    try:
        args.func(args)
    except BrokenPipeError:
        # The reader went away (`cobol-parser parse x.cbl | head`): stop
        # quietly, the way a shell tool killed by SIGPIPE does, instead of a
        # traceback -- and point stdout at devnull so the interpreter's own
        # final flush cannot raise the same error again at exit.
        try:
            devnull = os.open(os.devnull, os.O_WRONLY)
            os.dup2(devnull, sys.stdout.fileno())
        except (OSError, ValueError):
            pass
        sys.exit(141)  # 128 + SIGPIPE, what the shell reports for `yes | head`


if __name__ == "__main__":
    main()
