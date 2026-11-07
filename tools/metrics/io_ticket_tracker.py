#!/usr/bin/env python3
"""IO ticket tracking for support issue measurement (SC-004).

Tracks IO-related support tickets to measure progress toward the 40% reduction goal.
Establishes a weekly baseline and provides utilities for comparing current counts.

Usage:
    # Capture baseline
    python io_ticket_tracker.py --mode baseline --output baseline.json

    # Check current status
    python io_ticket_tracker.py --mode current --baseline baseline.json
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def create_baseline_record() -> dict[str, Any]:
    """Create a baseline record for IO ticket tracking."""
    # Naive UTC, so the strings keep their historical (offset-free) format.
    now = datetime.now(UTC).replace(tzinfo=None)
    return {
        "timestamp": now.isoformat(),
        "week": now.strftime("%Y-W%W"),
        "baseline_io_tickets": 0,  # Placeholder for actual tracking
        "baseline_date": now.isoformat(),
        "description": "Baseline ticket count for IO-related parser issues",
        "notes": "This metric supports SC-004: achieve 40% reduction in IO parsing support tickets by end of feature",
        "tracking_enabled": True,
    }


def generate_baseline(output_path: Path) -> dict[str, Any]:
    """Generate and save a baseline ticket record."""
    record = create_baseline_record()
    output_path.write_text(json.dumps(record, indent=2))
    return record


def load_baseline(baseline_path: Path) -> dict[str, Any]:
    """Load a baseline record from file."""
    if not baseline_path.exists():
        raise FileNotFoundError(f"Baseline file not found: {baseline_path}")
    return json.loads(baseline_path.read_text())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=["baseline", "current", "compare"],
        default="baseline",
        help="Tracking mode: baseline (create), current (read), compare (diff)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output file for baseline record",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Path to baseline record for comparison",
    )
    parser.add_argument(
        "--current",
        type=int,
        help="Current ticket count for comparison",
    )

    args = parser.parse_args()

    if args.mode == "baseline":
        if not args.output:
            print(
                "Error: --output required for baseline mode",
                file=__import__("sys").stderr,
            )
            return 1
        record = generate_baseline(args.output)
        print(f"✅ Baseline created: {args.output}")
        print(json.dumps(record, indent=2))
        return 0

    elif args.mode == "current":
        if not args.baseline:
            print(
                "Error: --baseline required for current mode",
                file=__import__("sys").stderr,
            )
            return 1
        baseline = load_baseline(args.baseline)
        print(f"📊 Baseline record (from {baseline['baseline_date']}):")
        print(json.dumps(baseline, indent=2))
        return 0

    elif args.mode == "compare":
        if not args.baseline or args.current is None:
            print(
                "Error: --baseline and --current required for compare mode",
                file=__import__("sys").stderr,
            )
            return 1
        baseline = load_baseline(args.baseline)
        baseline_count = baseline.get("baseline_io_tickets", 0)
        reduction_pct = (
            ((baseline_count - args.current) / baseline_count * 100)
            if baseline_count > 0
            else 0
        )
        target_count = int(baseline_count * 0.6)  # 40% reduction = 60% of baseline
        status = (
            "✅ TARGET MET"
            if args.current <= target_count
            else f"⏳ Progress: {reduction_pct:.1f}% (need {target_count})"
        )

        print("📈 Ticket Tracking Report:")
        print(f"  Baseline: {baseline_count} tickets ({baseline['baseline_date']})")
        print(f"  Current:  {args.current} tickets")
        print(f"  Target:   {target_count} tickets (40% reduction)")
        print(f"  Status:   {status}")
        return 0

    return 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
