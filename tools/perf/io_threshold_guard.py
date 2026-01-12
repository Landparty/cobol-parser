#!/usr/bin/env python3
"""
Performance threshold guard for IO variation tests.

Enforces SC-002: IO suites must complete in ≤90 seconds with ≤256 MB peak memory.
Called post-test to validate that performance targets were met.

Usage:
    python io_threshold_guard.py --runtime <seconds> --memory <mb> [--fail-on-breach]
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, Tuple

# Thresholds per spec.md SC-002
RUNTIME_THRESHOLD_SECONDS = 90
MEMORY_THRESHOLD_MB = 256


def check_thresholds(
    runtime_seconds: float, memory_mb: float, fail_on_breach: bool = False
) -> Tuple[bool, str]:
    """
    Validate runtime and memory against thresholds.

    Args:
        runtime_seconds: Total test suite execution time
        memory_mb: Peak memory usage
        fail_on_breach: If True, raise SystemExit on breach

    Returns:
        (all_pass, message) tuple
    """
    passed = True
    messages = []

    if runtime_seconds > RUNTIME_THRESHOLD_SECONDS:
        passed = False
        messages.append(
            f"❌ RUNTIME BREACH: {runtime_seconds:.2f}s > {RUNTIME_THRESHOLD_SECONDS}s limit"
        )
    else:
        messages.append(f"✅ Runtime OK: {runtime_seconds:.2f}s ≤ {RUNTIME_THRESHOLD_SECONDS}s")

    if memory_mb > MEMORY_THRESHOLD_MB:
        passed = False
        messages.append(
            f"❌ MEMORY BREACH: {memory_mb:.1f} MB > {MEMORY_THRESHOLD_MB} MB limit"
        )
    else:
        messages.append(f"✅ Memory OK: {memory_mb:.1f} MB ≤ {MEMORY_THRESHOLD_MB} MB")

    message = "\n".join(messages)

    if not passed and fail_on_breach:
        print(message, file=sys.stderr)
        sys.exit(1)

    return passed, message


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=float, required=True, help="Runtime in seconds")
    parser.add_argument("--memory", type=float, required=True, help="Peak memory in MB")
    parser.add_argument(
        "--fail-on-breach",
        action="store_true",
        help="Exit with code 1 if thresholds are breached",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        help="Write results to JSON file for CI artifact tracking",
    )

    args = parser.parse_args()

    passed, message = check_thresholds(args.runtime, args.memory, args.fail_on_breach)

    print(message)

    if args.output_json:
        result = {
            "runtime_seconds": args.runtime,
            "runtime_threshold": RUNTIME_THRESHOLD_SECONDS,
            "runtime_passed": args.runtime <= RUNTIME_THRESHOLD_SECONDS,
            "memory_mb": args.memory,
            "memory_threshold_mb": MEMORY_THRESHOLD_MB,
            "memory_passed": args.memory <= MEMORY_THRESHOLD_MB,
            "all_passed": passed,
        }
        args.output_json.write_text(json.dumps(result, indent=2))

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())


if __name__ == "__main__":
    sys.exit(main())
