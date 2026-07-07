#!/usr/bin/env python
"""CLI entry point for IO coverage commands.

Provides commands for:
- status: Show IO coverage status filtered by verb/qualifier
- generate: Generate coverage artifact from pytest results
- validate: Validate coverage artifact against schema
- render: Render coverage artifact as Markdown/CSV

Usage:
    python -m cobolparser.cli.coverage status [--verb OPEN] [--format table|json]
    python -m cobolparser.cli.coverage generate --pytest-results results.json --output coverage.json
    python -m cobolparser.cli.coverage validate --artifact coverage.json
    python -m cobolparser.cli.coverage render --input coverage.json --output report.md --format markdown
"""

import argparse
import json
import sys
from pathlib import Path

from cobolparser.analysis.io_coverage_reporter import IOCoverageReporter


def cmd_status(args: argparse.Namespace) -> int:
    """Show IO coverage status."""
    # Find artifact
    artifact_path = Path(args.artifact)
    if not artifact_path.exists():
        # Try to find in current directory
        artifact_path = Path("io-coverage.json")
        if not artifact_path.exists():
            print("Error: io-coverage.json not found. Run 'generate' first.")
            return 1

    try:
        with open(artifact_path) as f:
            artifact = json.load(f)
    except json.JSONDecodeError as e:
        print(f"Error: {artifact_path} is not valid JSON: {e}")
        return 1
    except OSError as e:
        print(f"Error: cannot read {artifact_path}: {e}")
        return 1

    if not isinstance(artifact, dict):
        print(f"Error: {artifact_path} does not contain a coverage artifact object")
        return 1

    # Filter by verb if specified
    variations = artifact.get("variations", [])
    if args.verb:
        variations = [
            v for v in variations if v.get("verb", "").upper() == args.verb.upper()
        ]

    if args.qualifier:
        variations = [
            v
            for v in variations
            if args.qualifier.upper() in v.get("qualifiers", "").upper()
        ]

    # Output based on format
    if args.format == "json":
        output = {
            "filtered_variations": variations,
            "count": len(variations),
            "covered": len([v for v in variations if v.get("status") == "covered"]),
            "partial": len([v for v in variations if v.get("status") == "partial"]),
            "gap": len([v for v in variations if v.get("status") == "gap"]),
        }
        print(json.dumps(output, indent=2))
    else:
        # Table format
        print("IO Coverage Status")
        print(f"{'=' * 80}")
        print(f"Total variations: {len(variations)}")
        covered = len([v for v in variations if v.get("status") == "covered"])
        partial = len([v for v in variations if v.get("status") == "partial"])
        gap = len([v for v in variations if v.get("status") == "gap"])
        print(f"  Covered: {covered}")
        print(f"  Partial: {partial}")
        print(f"  Gaps:    {gap}")
        print()
        print(f"{'ID':<30} {'Verb':<8} {'Status':<10} {'Tests':<6} {'Notes'}")
        print("-" * 80)
        for v in sorted(variations, key=lambda x: (x.get("verb", ""), x.get("id", ""))):
            status = v.get("status", "")
            test_count = len(v.get("tests", []))
            notes = v.get("notes", "") or ""
            if len(notes) > 30:
                notes = notes[:27] + "..."
            status_icon = {
                "covered": "✓",
                "partial": "~",
                "gap": "✗",
                "unsupported": "?",
            }.get(status, "?")
            print(
                f"{v.get('id', ''):<30} {v.get('verb', ''):<8} {status_icon} {status:<8} {test_count:<6} {notes}"
            )

    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    """Generate coverage artifact from pytest results."""
    reporter = IOCoverageReporter(catalog_path=args.catalog, schema_path=args.schema)

    try:
        result = reporter.generate_report(args.pytest_results, args.output)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1

    if result["success"]:
        print(f"Coverage artifact generated: {args.output}")
        print(f"Coverage: {result['coverage_percent']}%")
        print(f"  Covered: {result['covered_variations']}/{result['total_variations']}")
        print(f"  Gaps: {result['gap_variations']}")
        return 0
    else:
        print("Error generating coverage artifact:")
        for error in result.get("validation_errors", []):
            print(f"  - {error}")
        return 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate coverage artifact against schema."""
    from scripts.validate_io_coverage import CoverageSchemaValidator

    validator = CoverageSchemaValidator(args.artifact)
    is_valid = validator.validate()

    if is_valid:
        print(f"✓ Artifact is valid: {args.artifact}")
        return 0
    else:
        print(f"✗ Validation errors in {args.artifact}:")
        for error in validator.errors:
            print(f"  - {error}")
        return 1


def cmd_render(args: argparse.Namespace) -> int:
    """Render coverage artifact as Markdown/CSV."""
    sys.path.insert(0, str(Path(__file__).parent.parent / "tools" / "io_coverage"))
    from render_markdown import CoverageRenderer  # type: ignore[import-not-found]

    try:
        renderer = CoverageRenderer(args.input)

        if args.format == "markdown":
            output = renderer.render_markdown()
        elif args.format == "csv":
            output = renderer.render_csv()
        else:
            output = renderer.render_summary()

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(output)
            print(f"Output written to: {args.output}")
        else:
            print(output)

        return 0
    except FileNotFoundError as e:
        print(f"Error: {e}")
        return 1
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {args.input}: {e}")
        return 1


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        description="COBOL Parser IO Coverage Tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show coverage status for all variations
  python -m cobolparser.cli.coverage status

  # Show coverage for OPEN statements only
  python -m cobolparser.cli.coverage status --verb OPEN

  # Generate coverage artifact
  python -m cobolparser.cli.coverage generate --pytest-results results.json

  # Validate coverage artifact
  python -m cobolparser.cli.coverage validate --artifact io-coverage.json

  # Render as Markdown
  python -m cobolparser.cli.coverage render --input io-coverage.json --output report.md
""",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # status command
    status_parser = subparsers.add_parser("status", help="Show IO coverage status")
    status_parser.add_argument(
        "--artifact",
        default="io-coverage.json",
        help="Path to coverage artifact (default: io-coverage.json)",
    )
    status_parser.add_argument(
        "--verb", help="Filter by verb (e.g., OPEN, READ, WRITE)"
    )
    status_parser.add_argument(
        "--qualifier", help="Filter by qualifier (e.g., AT END, INVALID KEY)"
    )
    status_parser.add_argument(
        "--format",
        choices=["table", "json"],
        default="table",
        help="Output format (default: table)",
    )

    # generate command
    generate_parser = subparsers.add_parser(
        "generate", help="Generate coverage artifact"
    )
    generate_parser.add_argument(
        "--pytest-results", required=True, help="Path to pytest results JSON file"
    )
    generate_parser.add_argument(
        "--output",
        default="io-coverage.json",
        help="Path for output artifact (default: io-coverage.json)",
    )
    generate_parser.add_argument("--catalog", help="Path to IO variation catalog CSV")
    generate_parser.add_argument("--schema", help="Path to coverage schema JSON")

    # validate command
    validate_parser = subparsers.add_parser(
        "validate", help="Validate coverage artifact"
    )
    validate_parser.add_argument(
        "--artifact", required=True, help="Path to coverage artifact JSON"
    )

    # render command
    render_parser = subparsers.add_parser("render", help="Render coverage artifact")
    render_parser.add_argument(
        "--input", required=True, help="Path to coverage artifact JSON"
    )
    render_parser.add_argument(
        "--output", help="Path for output file (default: stdout)"
    )
    render_parser.add_argument(
        "--format",
        choices=["markdown", "csv", "summary"],
        default="markdown",
        help="Output format (default: markdown)",
    )

    return parser


def main() -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "status": cmd_status,
        "generate": cmd_generate,
        "validate": cmd_validate,
        "render": cmd_render,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
