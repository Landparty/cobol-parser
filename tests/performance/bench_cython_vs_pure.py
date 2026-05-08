"""Benchmark: Cython-accelerated lexer vs pure-Python lexer.

Runs both implementations on a 20-file sample from examples/cobol/ and
prints a comparison table showing wall-clock times and speedup ratios.

Usage:
    python tests/performance/bench_cython_vs_pure.py          # 20-file sample
    python tests/performance/bench_cython_vs_pure.py --all    # full corpus
    python tests/performance/bench_cython_vs_pure.py --files N

Asserts median speedup >= 3x when the Cython extension is compiled.
Exits with code 0 on success, 1 on failure or if extension is not compiled.
"""

import argparse
import pathlib
import statistics
import sys
import time

REPO_ROOT = pathlib.Path(__file__).parent.parent.parent
CORPUS_DIR = REPO_ROOT / "examples" / "cobol"

# Reproducible 20-file sample (spread across modules in the NIST suite)
DEFAULT_SAMPLE = [
    "CM101M.CBL", "CM201M.CBL", "DB101A.CBL", "DB201A.CBL", "DB301M.CBL",
    "EXEC85.CBL", "IC101A.CBL", "IF101A.CBL", "IX101A.CBL", "NC101A.CBL",
    "OB101A.CBL", "PC101A.CBL", "RL101A.CBL", "SC101A.CBL", "SQ101A.CBL",
    "ST101A.CBL", "TA101A.CBL", "TF101A.CBL", "XI101A.CBL", "SM101A.CBL",
]


def _timeit(fn, source: str, repetitions: int = 5) -> float:
    """Return median wall-clock time (seconds) over *repetitions* runs."""
    times = []
    for _ in range(repetitions):
        t0 = time.perf_counter()
        fn(source)
        times.append(time.perf_counter() - t0)
    return statistics.median(times)


def _run_lexer(lexer_cls, source: str) -> None:
    lexer_cls(source).tokenize()


def main() -> int:
    parser = argparse.ArgumentParser(description="Cython vs pure-Python lexer benchmark")
    parser.add_argument("--all", action="store_true", help="Use full NIST corpus")
    parser.add_argument("--files", type=int, default=20, help="Number of files to sample")
    parser.add_argument("--reps", type=int, default=5, help="Repetitions per file")
    args = parser.parse_args()

    # Import pure-Python lexer (always available)
    sys.path.insert(0, str(REPO_ROOT))
    try:
        from cobolparser.lexer import _CobolLexerPure as PureLexer
    except ImportError as e:
        print(f"ERROR: Could not import pure-Python lexer: {e}", file=sys.stderr)
        return 1

    # Import Cython lexer (optional)
    try:
        from cobolparser._lexer_fast import CobolLexer as FastLexer
        has_fast = True
    except ImportError:
        FastLexer = None
        has_fast = False
        print("WARNING: _lexer_fast extension not compiled — skipping Cython timings.\n")

    # Collect corpus files
    all_files = sorted(CORPUS_DIR.glob("*.CBL"))
    if not all_files:
        print(f"ERROR: No .CBL files found in {CORPUS_DIR}", file=sys.stderr)
        return 1

    if args.all:
        files = all_files
    else:
        n = min(args.files, len(all_files))
        # Use the predefined sample; fall back to first N files if any are missing
        sample_paths = [CORPUS_DIR / name for name in DEFAULT_SAMPLE if (CORPUS_DIR / name).exists()]
        if len(sample_paths) < n:
            extras = [f for f in all_files if f not in sample_paths]
            sample_paths.extend(extras[: n - len(sample_paths)])
        files = sample_paths[:n]

    print(f"Benchmarking {len(files)} files, {args.reps} repetitions each\n")

    col_w = [36, 12, 12, 10]
    header = (
        f"{'File':<{col_w[0]}} {'Pure (ms)':>{col_w[1]}} "
        f"{'Fast (ms)':>{col_w[2]}} {'Speedup':>{col_w[3]}}"
    )
    sep = "-" * sum(col_w)
    print(header)
    print(sep)

    pure_times: list[float] = []
    fast_times: list[float] = []
    speedups: list[float] = []
    errors: list[str] = []

    for path in files:
        try:
            source = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            errors.append(f"{path.name}: read error — {e}")
            continue

        pure_ms = _timeit(lambda s: _run_lexer(PureLexer, s), source, args.reps) * 1000
        pure_times.append(pure_ms)

        if has_fast:
            fast_ms = _timeit(lambda s: _run_lexer(FastLexer, s), source, args.reps) * 1000
            fast_times.append(fast_ms)
            ratio = pure_ms / fast_ms if fast_ms > 0 else float("inf")
            speedups.append(ratio)
            print(
                f"{path.name:<{col_w[0]}} {pure_ms:>{col_w[1]}.2f} "
                f"{fast_ms:>{col_w[2]}.2f} {ratio:>{col_w[3]}.2f}x"
            )
        else:
            print(f"{path.name:<{col_w[0]}} {pure_ms:>{col_w[1]}.2f} {'N/A':>{col_w[2]}} {'N/A':>{col_w[3]}}")

    print(sep)

    if errors:
        print(f"\nSkipped {len(errors)} files due to errors:")
        for msg in errors:
            print(f"  {msg}")

    median_pure = statistics.median(pure_times) if pure_times else 0.0
    print(f"\n{'Median pure-Python (ms):':<30} {median_pure:.2f}")

    if has_fast and fast_times:
        median_fast = statistics.median(fast_times)
        median_speedup = statistics.median(speedups)
        print(f"{'Median Cython (ms):':<30} {median_fast:.2f}")
        print(f"{'Median speedup:':<30} {median_speedup:.2f}x")

        if median_speedup >= 3.0:
            print(f"\nPASS: median speedup {median_speedup:.2f}x >= 3.0x target")
            return 0
        else:
            print(f"\nFAIL: median speedup {median_speedup:.2f}x < 3.0x target", file=sys.stderr)
            return 1
    else:
        print("\nCython extension not compiled — compile with:")
        print("    python setup.py build_ext --inplace")
        return 1


if __name__ == "__main__":
    sys.exit(main())
