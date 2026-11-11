"""Helpers shared by the CLI subcommands.

The common flags, reading a source file, the parse-then-guard path every
analyzer goes through (``_parse_or_fail``), and the JSON / text output
functions (``_emit_report`` adds the identification header).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, NoReturn

from .._file_limits import timeout_problem
from ..models.program import CobolProgram
from ..parser import parse_cobol
from ..plugins.core import DialectType, ErrorRecoveryMode

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


def _add_copybook_args(
    parser: argparse.ArgumentParser, strict_flag: bool = False
) -> None:
    """``--copybook-path``; with *strict_flag* also ``--strict-copybooks``,
    for the subcommands that parse one file through :func:`_do_parse`."""
    parser.add_argument(
        "--copybook-path",
        action="append",
        default=[],
        metavar="DIR",
        help="Directory to search for copybooks (repeatable)",
    )
    if strict_flag:
        parser.add_argument(
            "--strict-copybooks",
            action="store_true",
            help=(
                "Fail (exit 1) when a COPY member cannot be found, instead of "
                "analyzing the program without that member and warning"
            ),
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


def _add_limit_args(parser: argparse.ArgumentParser) -> None:
    """``--timeout`` / ``--max-file-bytes``: per-file caps for multi-file runs.

    Both default to no limit; ``cobol.yml``'s ``limits:`` section fills them.
    """
    parser.add_argument(
        "--timeout",
        dest="timeout_seconds",
        type=float,
        default=None,
        metavar="SECONDS",
        help=(
            "Stop a file still being processed after SECONDS (its worker "
            "process is terminated) and report it as a failure; the other "
            "files carry on (default: no limit)"
        ),
    )
    parser.add_argument(
        "--max-file-bytes",
        dest="max_file_bytes",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Skip, and report as a failure, any program file larger than N "
            "bytes on disk (default: no limit)"
        ),
    )


def _limit_kwargs(args: argparse.Namespace) -> dict[str, Any]:
    """The validated ``timeout_seconds`` / ``max_file_bytes`` for a run."""
    timeout = getattr(args, "timeout_seconds", None)
    max_bytes = getattr(args, "max_file_bytes", None)
    if timeout is not None and (problem := timeout_problem(timeout)) is not None:
        _fail(f"--timeout {problem}")
    if max_bytes is not None and max_bytes < 1:
        _fail("--max-file-bytes must be >= 1")
    return {"timeout_seconds": timeout, "max_file_bytes": max_bytes}


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


# -- Output -------------------------------------------------------------------


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


# -- Parsing: the parse-then-guard path ---------------------------------------


def _do_parse(args: argparse.Namespace) -> tuple[Any, Any]:
    """Shared parse logic used by parse and analyze subcommands."""
    from ..profiling import ProfilerContext

    source = _read_source(args.file, getattr(args, "encoding", None))
    if getattr(args, "_wrap_copybook_fragment", False):
        # data-items on a bare copybook: parse it the way gen-data does,
        # inside a program skeleton, instead of as a program with no
        # divisions (an empty answer with exit 0, #536).
        from ..layout.copybook import wrap_copybook_fragment

        wrapped = wrap_copybook_fragment(source)
        if wrapped is not None:
            source = wrapped
    dialect = _DIALECT_MAP[args.dialect]
    error_recovery = _get_error_recovery(args)

    copybook_paths = getattr(args, "copybook_path", [])
    # Every single-file subcommand finishes what it can rather than failing
    # a file on one COPY: the IBM-supplied CICS members (DFHAID, DFHBMSCA)
    # come from stand-ins when the search path lacks them, and any other
    # missing member is left as written and named on stderr (lint also names
    # it in the report's caveats). `--strict-copybooks` keeps the old exit 1.
    lenient_copybooks = not getattr(args, "strict_copybooks", False)
    if lenient_copybooks:
        from ..preprocess._system_copybooks import with_system_copybooks

        copybook_paths = with_system_copybooks(list(copybook_paths))
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
            from ..parser import parse_cobol_with_expansion
            from ..preprocess import PreprocessingError

            try:
                return parse_cobol_with_expansion(
                    source,
                    filename=args.file,
                    copybook_paths=copybook_paths,
                    process_conditionals=True,
                    defined_symbols=defines,
                    skip_missing_copybooks=lenient_copybooks,
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
_UNEXPANDED_SQL_INCLUDE = re.compile(r"^EXEC SQL INCLUDE (\S+) was not expanded")


def _hint_unexpanded_copybooks(args: argparse.Namespace, result: Any) -> None:
    """Say on stderr when COPY statements were left out, for want of a
    copybook path or because the member is not on it.

    The parse still succeeds either way, so the only trace of the missing
    copybooks was a warning inside the JSON, and an analyzer report silently
    covered less of the program than the user expected.
    """
    _hint_unexpanded_sql_includes(args, result)
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
    if getattr(args, "copybook_path", None):
        advice = (
            "not found on the copybook path; the analysis covers the program "
            "without them (--strict-copybooks fails instead)"
        )
    else:
        advice = "pass --copybook-path DIR or set project.copybook_path in cobol.yml"
    print(
        f"warning: {args.file}: {len(names)} copybook(s) not expanded "
        f"({shown}); {advice}",
        file=sys.stderr,
    )


def _hint_unexpanded_sql_includes(args: argparse.Namespace, result: Any) -> None:
    """Say on stderr when an ``EXEC SQL INCLUDE`` member could not be found.

    Unlike a missing COPY member, a missing INCLUDE never fails the parse
    (``SQLCA`` / ``SQLDA`` come from the precompiler, so the expander leaves
    every unresolved INCLUDE as written), so this is the only sign that the
    program was analyzed without the declarations it pulls in -- with or
    without ``--copybook-path``.
    """
    names = []
    for warning in getattr(result, "warnings", None) or []:
        match = _UNEXPANDED_SQL_INCLUDE.match(str(warning))
        if match and match.group(1) not in names:
            names.append(match.group(1))
    if not names:
        return
    shown = ", ".join(names[:5]) + (
        f" and {len(names) - 5} more" if len(names) > 5 else ""
    )
    print(
        f"warning: {args.file}: {len(names)} EXEC SQL INCLUDE member(s) not "
        f"found ({shown}); their declarations are missing from the analysis",
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


# -- Used by more than one command module -------------------------------------


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


def _severity_at_least(severity: str, threshold: str) -> bool:
    """True when *severity* is as severe as *threshold*, or more so."""
    from ..analysis.lint import SEVERITIES

    return SEVERITIES.index(severity) <= SEVERITIES.index(threshold)


def _loc(loc: Any) -> dict[str, int] | None:
    """Render a source location as ``{"line": ..., "column": ...}`` or None."""
    if loc is None:
        return None
    return {"line": loc.line, "column": loc.column}


def _fail(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)
