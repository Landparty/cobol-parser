#!/usr/bin/env python3
"""Benchmark suite for the COBOL parser.

Measures and reports timing for each major stage of parsing:
  1. Fixed-format detection
  2. Preprocessing / normalization
  3. Lexing (tokenization)
  4. Parsing (AST construction)
  5. Full end-to-end pipeline

Also benchmarks individual hot-path components:
  - PictureClause pattern parsing
  - SQL statement parsing
  - Statement registry dispatch
  - String building in lexer

Usage:
    python -m benchmarks.bench_parser                  # run all benchmarks
    python -m benchmarks.bench_parser --iterations 50  # custom iteration count
    python -m benchmarks.bench_parser --profile         # run with cProfile
"""

import argparse
import cProfile
import io
import pstats
import sys
import time
from pathlib import Path
from statistics import mean, median, stdev

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from cobolparser.lexer import CobolLexer  # noqa: E402
from cobolparser.models.ast_base import SourceLocation  # noqa: E402
from cobolparser.models.data_items import PictureClause  # noqa: E402
from cobolparser.models.sql_statements import parse_exec_sql  # noqa: E402
from cobolparser.parser import (  # noqa: E402
    CobolParser,
    _detect_fixed_format,
    parse_cobol,
)
from cobolparser.plugins.core import ErrorRecoveryMode  # noqa: E402
from cobolparser.preprocess import normalize_fixed_format  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLES_DIR = PROJECT_ROOT / "tests" / "samples"


def _gather_sample_files() -> list[Path]:
    """Collect all .cbl/.cob sample files for benchmarking."""
    files = []
    for ext in ("*.cbl", "*.cob"):
        files.extend(SAMPLES_DIR.rglob(ext))
    return sorted(files)


def _read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _generate_large_cobol(n_records: int = 200, n_statements: int = 500) -> str:
    """Generate a synthetic large COBOL program for stress-testing."""
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. BENCHMARK-PROG.",
        "       DATA DIVISION.",
        "       WORKING-STORAGE SECTION.",
    ]
    # Generate data items
    for i in range(1, n_records + 1):
        lines.append(f"       01  WS-REC-{i:04d}.")
        lines.append(f"           05  WS-FIELD-A-{i:04d}  PIC X(20) VALUE SPACES.")
        lines.append(f"           05  WS-FIELD-B-{i:04d}  PIC 9(7)V99 COMP-3.")
        lines.append(f"           05  WS-FIELD-C-{i:04d}  PIC S9(5) VALUE ZERO.")
    lines.append("       PROCEDURE DIVISION.")
    lines.append("       MAIN-PARA.")
    # Generate statements
    for i in range(1, n_statements + 1):
        idx = ((i - 1) % n_records) + 1
        kind = i % 6
        if kind == 0:
            lines.append(
                f"           MOVE WS-FIELD-A-{idx:04d} TO WS-FIELD-C-{idx:04d}"
            )
        elif kind == 1:
            lines.append(f"           DISPLAY WS-FIELD-A-{idx:04d}")
        elif kind == 2:
            lines.append(f"           ADD 1 TO WS-FIELD-C-{idx:04d}")
        elif kind == 3:
            lines.append(f"           IF WS-FIELD-C-{idx:04d} > 0")
            lines.append("               DISPLAY 'POSITIVE'")
            lines.append("           END-IF")
        elif kind == 4:
            lines.append("           PERFORM MAIN-PARA")
        else:
            lines.append(f"           COMPUTE WS-FIELD-B-{idx:04d} =")
            lines.append(f"               WS-FIELD-C-{idx:04d} * 1.5")
    lines.append("           STOP RUN.")
    return "\n".join(lines) + "\n"


class Timer:
    """Simple context-manager timer returning elapsed seconds."""

    def __init__(self):
        self.elapsed = 0.0

    def __enter__(self):
        self._start = time.perf_counter()
        return self

    def __exit__(self, *exc):
        self.elapsed = time.perf_counter() - self._start


def _run_timed(func, iterations: int) -> list[float]:
    """Run *func* multiple times and return list of elapsed times in ms."""
    times = []
    for _ in range(iterations):
        with Timer() as t:
            func()
        times.append(t.elapsed * 1000)
    return times


def _print_stats(label: str, times_ms: list[float], indent: int = 2) -> None:
    """Pretty-print timing statistics."""
    prefix = " " * indent
    n = len(times_ms)
    avg = mean(times_ms)
    med = median(times_ms)
    mn = min(times_ms)
    mx = max(times_ms)
    sd = stdev(times_ms) if n > 1 else 0.0
    print(f"{prefix}{label}")
    print(f"{prefix}  iterations : {n}")
    print(f"{prefix}  mean       : {avg:>10.3f} ms")
    print(f"{prefix}  median     : {med:>10.3f} ms")
    print(f"{prefix}  min        : {mn:>10.3f} ms")
    print(f"{prefix}  max        : {mx:>10.3f} ms")
    print(f"{prefix}  stdev      : {sd:>10.3f} ms")
    print()


# ---------------------------------------------------------------------------
# Benchmark functions
# ---------------------------------------------------------------------------


def bench_fixed_format_detection(source: str, iterations: int) -> list[float]:
    """Benchmark fixed-format detection."""
    return _run_timed(lambda: _detect_fixed_format(source), iterations)


def bench_normalize(source: str, iterations: int) -> list[float]:
    """Benchmark fixed-format normalization."""
    lines = source.splitlines()
    return _run_timed(lambda: normalize_fixed_format(lines), iterations)


def bench_lexer(source: str, iterations: int, free_form: bool = True) -> list[float]:
    """Benchmark lexer tokenization."""

    def run():
        lexer = CobolLexer(source, "<bench>", free_form=free_form)
        lexer.tokenize()

    return _run_timed(run, iterations)


def bench_parser(
    source: str, iterations: int, *, free_form: bool = True
) -> list[float]:
    """Benchmark full parser (tokenize + parse) for already-prepared source."""

    def run():
        parser = CobolParser(
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
            free_form=free_form,
        )
        result = parser.parse(source, "<bench>")
        if not result.success:
            raise RuntimeError("Benchmark parse failed")

    return _run_timed(run, iterations)


def bench_parse_cobol(source: str, iterations: int) -> list[float]:
    """Benchmark the convenience parse_cobol() end-to-end function."""

    def run():
        parse_cobol(source, "<bench>", error_recovery=ErrorRecoveryMode.COLLECT_ALL)

    return _run_timed(run, iterations)


def bench_picture_clause(iterations: int) -> list[float]:
    """Benchmark PictureClause pattern parsing."""
    patterns = [
        "X(20)",
        "9(7)V99",
        "S9(5)",
        "A(10)",
        "9999",
        "S9(7)V9(2)",
        "-9(5).99",
        "X",
        "9(3)V99",
        "S999V999",
    ]
    loc = SourceLocation(1, 1)

    def run():
        for p in patterns:
            PictureClause(p, loc)

    return _run_timed(run, iterations)


def bench_sql_parsing(iterations: int) -> list[float]:
    """Benchmark SQL statement parsing."""
    sql_stmts = [
        "SELECT EMP_NAME, EMP_SALARY FROM EMPLOYEE WHERE DEPT = :WS-DEPT",
        "INSERT INTO AUDIT_LOG (ACTION, TIMESTAMP) VALUES (:WS-ACTION, :WS-TS)",
        "UPDATE EMPLOYEE SET SALARY = :WS-NEW-SAL WHERE EMP_ID = :WS-ID",
        "DELETE FROM TEMP_TABLE WHERE CREATED < :WS-CUTOFF",
        "DECLARE EMP_CURSOR CURSOR FOR SELECT * FROM EMPLOYEE",
        "FETCH EMP_CURSOR INTO :WS-NAME, :WS-SALARY",
        "COMMIT WORK",
    ]
    loc = SourceLocation(1, 1)

    def run():
        for sql in sql_stmts:
            parse_exec_sql(sql, loc)

    return _run_timed(run, iterations)


def bench_statement_registry(source: str, iterations: int) -> list[float]:
    """Benchmark statement registry dispatch (parser initialization + lookup)."""
    from cobolparser.parsers.statements.arithmetic_parsers import (
        AddStatementParser,
        ComputeStatementParser,
        DivideStatementParser,
        MultiplyStatementParser,
        SubtractStatementParser,
    )
    from cobolparser.parsers.statements.call_parser import CallStatementParser
    from cobolparser.parsers.statements.display_parser import DisplayStatementParser
    from cobolparser.parsers.statements.evaluate_parser import EvaluateStatementParser
    from cobolparser.parsers.statements.if_parser import IfStatementParser
    from cobolparser.parsers.statements.move_parser import MoveStatementParser
    from cobolparser.parsers.statements.perform_parser import PerformStatementParser

    from cobolparser.core.registry import StatementParserRegistry
    from cobolparser.core.token_stream import TokenStream

    # Pre-tokenize
    lexer = CobolLexer(source, "<bench>", free_form=True)
    tokens = lexer.tokenize()

    def run():
        registry = StatementParserRegistry()
        registry.register(DisplayStatementParser())
        registry.register(MoveStatementParser())
        registry.register(CallStatementParser())
        registry.register(IfStatementParser())
        registry.register(PerformStatementParser())
        registry.register(EvaluateStatementParser())
        registry.register(AddStatementParser())
        registry.register(SubtractStatementParser())
        registry.register(MultiplyStatementParser())
        registry.register(DivideStatementParser())
        registry.register(ComputeStatementParser())

        stream = TokenStream(tokens)
        lookups = 0
        while not stream.is_empty():
            registry.find_parser(stream)
            lookups += 1
            stream.consume()

    return _run_timed(run, iterations)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def run_benchmarks(iterations: int = 10, do_profile: bool = False) -> None:
    """Execute all benchmarks and print results."""
    separator = "=" * 72

    print(separator)
    print("  COBOL PARSER BENCHMARK SUITE")
    print(separator)
    print()

    # ---- Gather sample files ----
    sample_files = _gather_sample_files()
    print(f"Found {len(sample_files)} sample files in {SAMPLES_DIR}")

    # Pick a representative medium-sized file
    medium_source = ""
    medium_name = ""
    for f in sample_files:
        src = _read_file(f)
        if len(src) > len(medium_source):
            medium_source = src
            medium_name = f.name
    if not medium_source:
        medium_source = _generate_large_cobol(50, 100)
        medium_name = "<generated-small>"

    # Generate a large synthetic program
    large_source = _generate_large_cobol(200, 500)

    print(
        f"Medium sample  : {medium_name} ({len(medium_source):,} chars, {len(medium_source.splitlines()):,} lines)"
    )
    print(
        f"Large synthetic: <generated> ({len(large_source):,} chars, {len(large_source.splitlines()):,} lines)"
    )
    print(f"Iterations     : {iterations}")
    print()

    # ---- Stage benchmarks (medium file) ----
    print(separator)
    print("  STAGE-BY-STAGE TIMING (medium sample)")
    print(separator)
    print()

    _print_stats(
        "1. Fixed-format detection",
        bench_fixed_format_detection(medium_source, iterations),
    )

    _print_stats(
        "2. Normalization (fixed -> free-form)",
        bench_normalize(medium_source, iterations),
    )

    # Normalize once for lexer/parser stages
    normalized_medium = normalize_fixed_format(medium_source.splitlines())

    _print_stats("3. Lexer (tokenization)", bench_lexer(normalized_medium, iterations))

    _print_stats(
        "4. Full parser (tokenize + parse)", bench_parser(normalized_medium, iterations)
    )

    _print_stats(
        "5. End-to-end parse_cobol()", bench_parse_cobol(medium_source, iterations)
    )

    # ---- Stage benchmarks (large synthetic) ----
    print(separator)
    print("  STAGE-BY-STAGE TIMING (large synthetic)")
    print(separator)
    print()

    _print_stats(
        "1. Fixed-format detection",
        bench_fixed_format_detection(large_source, iterations),
    )

    _print_stats("2. Normalization", bench_normalize(large_source, iterations))

    normalized_large = normalize_fixed_format(large_source.splitlines())

    _print_stats("3. Lexer (tokenization)", bench_lexer(normalized_large, iterations))

    _print_stats(
        "4. Full parser (tokenize + parse)", bench_parser(normalized_large, iterations)
    )

    _print_stats(
        "5. End-to-end parse_cobol()", bench_parse_cobol(large_source, iterations)
    )

    # ---- Component benchmarks ----
    print(separator)
    print("  COMPONENT BENCHMARKS")
    print(separator)
    print()

    component_iters = iterations * 10

    _print_stats(
        "PictureClause pattern parsing (10 patterns x N)",
        bench_picture_clause(component_iters),
    )

    _print_stats(
        "SQL statement parsing (7 statements x N)", bench_sql_parsing(component_iters)
    )

    _print_stats(
        "Statement registry dispatch (full token stream scan)",
        bench_statement_registry(normalized_medium, iterations),
    )

    # ---- Across all sample files ----
    print(separator)
    print("  ALL SAMPLE FILES (1 iteration each)")
    print(separator)
    print()

    file_times: list[tuple[str, float, int, int]] = []
    for fpath in sample_files:
        src = _read_file(fpath)
        t = _run_timed(
            lambda s=src, fp=fpath: parse_cobol(
                s, str(fp), error_recovery=ErrorRecoveryMode.COLLECT_ALL
            ),
            1,
        )
        n_lines = len(src.splitlines())
        n_chars = len(src)
        file_times.append((fpath.name, t[0], n_lines, n_chars))

    # Sort by time descending
    file_times.sort(key=lambda x: x[1], reverse=True)

    print(f"  {'File':<45s} {'Time (ms)':>10s}  {'Lines':>6s}  {'Chars':>8s}")
    print(f"  {'-'*45} {'-'*10}  {'-'*6}  {'-'*8}")
    for name, ms, lines, chars in file_times:
        print(f"  {name:<45s} {ms:>10.3f}  {lines:>6d}  {chars:>8d}")
    print()

    total_ms = sum(t[1] for t in file_times)
    print(f"  Total across all files: {total_ms:.3f} ms")
    print()

    # ---- Optional cProfile ----
    if do_profile:
        print(separator)
        print("  cProfile OUTPUT (large synthetic, 1 run)")
        print(separator)
        print()

        profiler = cProfile.Profile()
        profiler.enable()
        parse_cobol(
            large_source, "<profile>", error_recovery=ErrorRecoveryMode.COLLECT_ALL
        )
        profiler.disable()

        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats("cumulative")
        stats.print_stats(40)
        print(stream.getvalue())

    print(separator)
    print("  BENCHMARK COMPLETE")
    print(separator)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="COBOL parser benchmarks")
    parser.add_argument(
        "--iterations",
        "-n",
        type=int,
        default=10,
        help="Number of iterations per benchmark (default: 10)",
    )
    parser.add_argument(
        "--profile",
        "-p",
        action="store_true",
        help="Run cProfile on large synthetic program",
    )
    args = parser.parse_args()

    run_benchmarks(iterations=args.iterations, do_profile=args.profile)
