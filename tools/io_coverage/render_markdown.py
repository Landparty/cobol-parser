#!/usr/bin/env python
"""
Render IO coverage summary as Markdown/CSV.

This script reads the io-coverage.json artifact and produces
human-readable reports for maintainers.

Usage:
    python tools/io_coverage/render_markdown.py --input io-coverage.json --output io-coverage-report.md
    python tools/io_coverage/render_markdown.py --input io-coverage.json --format csv --output io-coverage-report.csv
"""

import argparse
import csv
import json
import os
import sys


class CoverageRenderer:
    """Renders IO coverage artifacts in various formats."""

    def __init__(self, artifact_path: str):
        """Initialize renderer with artifact path."""
        with open(artifact_path, encoding="utf-8") as f:
            self.artifact = json.load(f)

        self.variations = self.artifact.get("variations", [])
        self.summary = self.artifact.get("summary", {})

    def render_markdown(self) -> str:
        """Render coverage as Markdown table."""
        lines = []

        # Header
        lines.append("# IO Coverage Report\n")
        lines.append(f"**Generated:** {self.artifact.get('generated_at', 'N/A')}")
        lines.append(
            f"**Parser Version:** {self.artifact.get('parser_version', 'N/A')}"
        )
        lines.append(f"**Coverage:** {self.artifact.get('coverage_percent', 0)}%\n")

        # Summary by verb
        lines.append("## Summary by Verb\n")
        lines.append("| Verb | Variations | Covered | Gaps |")
        lines.append("|------|------------|---------|------|")

        total_covered = self.artifact.get("covered_variations", 0)
        total_gaps = self.artifact.get("gap_variations", 0)

        for verb in sorted(self.summary.keys()):
            count = self.summary[verb]
            verb_variations = [v for v in self.variations if v.get("verb") == verb]
            verb_covered = len(
                [v for v in verb_variations if v.get("status") == "covered"]
            )
            verb_gaps = len([v for v in verb_variations if v.get("status") == "gap"])

            lines.append(f"| {verb} | {count} | {verb_covered} | {verb_gaps} |")

        lines.append(
            f"| **Total** | {self.artifact.get('total_variations', 0)} | {total_covered} | {total_gaps} |"
        )
        lines.append("")

        # Detailed variation table
        lines.append("## Detailed Variation Coverage\n")
        lines.append("| ID | Verb | Organization | Access | Status | Tests | Notes |")
        lines.append("|----|------|--------------|--------|--------|-------|-------|")

        for variation in sorted(
            self.variations, key=lambda v: (v.get("verb", ""), v.get("id", ""))
        ):
            var_id = variation.get("id", "")
            verb = variation.get("verb", "")
            org = variation.get("organization", "")
            access = variation.get("access_mode", "")
            status = variation.get("status", "")
            tests_count = len(variation.get("tests", []))
            notes = variation.get("notes", "") or ""

            # Truncate long notes
            if len(notes) > 50:
                notes = notes[:47] + "..."

            # Status badge
            status_badge = self._status_badge(status)

            lines.append(
                f"| {var_id} | {verb} | {org} | {access} | {status_badge} | {tests_count} | {notes} |"
            )

        lines.append("")
        lines.append("---\n")
        lines.append("## Status Legend\n")
        lines.append("- **covered**: All tests for this variation pass")
        lines.append("- **partial**: Some tests pass, others fail")
        lines.append("- **gap**: No tests exist for this variation")
        lines.append("- **unsupported**: Parser does not support this variation\n")

        # Test links section
        lines.append("## Test References\n")
        lines.append("This section lists tests that cover each variation.\n")

        for verb in sorted({v.get("verb") for v in self.variations}):
            verb_variations = [v for v in self.variations if v.get("verb") == verb]

            if any(v.get("tests") for v in verb_variations):
                lines.append(f"### {verb}\n")

                for variation in verb_variations:
                    if variation.get("tests"):
                        lines.append(f"**{variation.get('id')}**")
                        for test in variation.get("tests", []):
                            test_id = test.get("test_id", "")
                            status = test.get("status", "")
                            lines.append(f"  - `{test_id}` ({status})")
                        lines.append("")

        return "\n".join(lines)

    def render_csv(self) -> str:
        """Render coverage as CSV."""
        import io

        output = io.StringIO()
        fieldnames = [
            "id",
            "verb",
            "organization",
            "access_mode",
            "qualifiers",
            "status",
            "requires_fd",
            "ibm_reference",
            "test_count",
            "last_tested",
            "notes",
        ]

        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()

        for variation in sorted(
            self.variations, key=lambda v: (v.get("verb", ""), v.get("id", ""))
        ):
            row = {
                "id": variation.get("id", ""),
                "verb": variation.get("verb", ""),
                "organization": variation.get("organization", ""),
                "access_mode": variation.get("access_mode", ""),
                "qualifiers": variation.get("qualifiers", ""),
                "status": variation.get("status", ""),
                "requires_fd": variation.get("requires_fd", False),
                "ibm_reference": variation.get("ibm_reference", ""),
                "test_count": len(variation.get("tests", [])),
                "last_tested": variation.get("last_tested", ""),
                "notes": variation.get("notes", ""),
            }
            writer.writerow(row)

        return output.getvalue()

    def render_summary(self) -> str:
        """Render brief summary for CLI output."""
        lines = []

        lines.append("IO Coverage Summary")
        lines.append("=" * 40)
        lines.append(f"Coverage: {self.artifact.get('coverage_percent', 0)}%")
        lines.append(f"Total Variations: {self.artifact.get('total_variations', 0)}")
        lines.append(f"  Covered: {self.artifact.get('covered_variations', 0)}")
        lines.append(f"  Partial: {self.artifact.get('partial_variations', 0)}")
        lines.append(f"  Gaps: {self.artifact.get('gap_variations', 0)}")
        lines.append("")

        lines.append("By Verb:")
        for verb in sorted(self.summary.keys()):
            count = self.summary[verb]
            verb_variations = [v for v in self.variations if v.get("verb") == verb]
            verb_covered = len(
                [v for v in verb_variations if v.get("status") == "covered"]
            )
            verb_gaps = len([v for v in verb_variations if v.get("status") == "gap"])
            lines.append(f"  {verb}: {verb_covered}/{count} covered, {verb_gaps} gaps")

        return "\n".join(lines)

    def _status_badge(self, status: str) -> str:
        """Create a status badge for Markdown."""
        badges = {
            "covered": "✅ covered",
            "partial": "⚠️ partial",
            "gap": "❌ gap",
            "unsupported": "🚫 unsupported",
        }
        return badges.get(status, status)


def main():
    parser = argparse.ArgumentParser(
        description="Render IO coverage artifact as Markdown or CSV"
    )
    parser.add_argument(
        "--input", "-i", required=True, help="Path to io-coverage.json artifact"
    )
    parser.add_argument("--output", "-o", required=True, help="Path for output file")
    parser.add_argument(
        "--format",
        "-f",
        choices=["markdown", "csv", "summary"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    args = parser.parse_args()

    if not os.path.exists(args.input):
        print(f"Error: Input file not found: {args.input}")
        return 1

    try:
        renderer = CoverageRenderer(args.input)

        if args.format == "markdown":
            output = renderer.render_markdown()
        elif args.format == "csv":
            output = renderer.render_csv()
        else:
            output = renderer.render_summary()

        # Ensure output directory exists
        output_dir = os.path.dirname(args.output)
        if output_dir and not os.path.exists(output_dir):
            os.makedirs(output_dir)

        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)

        print(f"Coverage report written to: {args.output}")

        # For summary format, also print to stdout
        if args.format == "summary":
            print("\n" + output)

    except Exception as e:
        print(f"Error: {e}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
