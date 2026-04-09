"""Command-line interface for parsing COBOL source files."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, NoReturn

from ..models.program import CobolDivision, CobolParagraph, CobolProgram, CobolSection
from ..parser import parse_cobol
from ..plugins.core import DialectType, ErrorRecoveryMode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cobol-parser",
        description="Parse COBOL source files and output AST as JSON.",
    )
    parser.add_argument("file", help="Path to the COBOL source file")
    parser.add_argument(
        "path",
        nargs="?",
        default=None,
        help="Dot-separated AST path (e.g., procedure.MAIN-LOGIC.display)",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Output compact (single-line) JSON instead of pretty-printed",
    )
    parser.add_argument(
        "--free-form",
        action="store_true",
        help="Treat source as free-form COBOL",
    )
    parser.add_argument(
        "--dialect",
        choices=["ibm-enterprise"],
        default="ibm-enterprise",
        help="COBOL dialect (default: ibm-enterprise)",
    )
    parser.add_argument(
        "--errors",
        action="store_true",
        help="Include parse errors and warnings in output",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        help="Include parse statistics in output",
    )
    return parser


def _resolve_path(
    program: CobolProgram, path: str
) -> dict[str, Any] | list[dict[str, Any]]:
    """Resolve a dot-separated path against the AST.

    Path forms:
      division                          -> division dict
      division.section_or_paragraph     -> section/paragraph dict
      division.paragraph.statement_type -> filtered statement list
    """
    parts = path.split(".")
    if len(parts) > 3:
        _fail(f"Path too deep: {path!r} (max 3 components: division.paragraph.statement)")

    # --- Level 1: division ---
    div_name = parts[0].upper()
    division = program.get_division(div_name)
    if division is None:
        available = [d.division_name for d in program.divisions]
        _fail(
            f"Division {parts[0]!r} not found. "
            f"Available: {', '.join(available)}"
        )

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

    # --- Level 3: statement type filter ---
    stmt_type = parts[2].upper()
    statements: list[Any] = []
    if isinstance(node, CobolParagraph):
        statements = node.statements
    elif isinstance(node, CobolSection):
        for para in node.paragraphs:
            statements.extend(para.statements)

    matched = [s for s in statements if s.statement_type.upper() == stmt_type]
    if not matched:
        available_types = sorted({s.statement_type for s in statements})
        _fail(
            f"No {parts[2]!r} statements found in {parts[1]!r}. "
            f"Available types: {', '.join(available_types) if available_types else '(none)'}"
        )
    return [s.to_dict() for s in matched]


def _list_section_and_paragraph_names(division: CobolDivision) -> list[str]:
    names: list[str] = []
    for section in division._sections.values():
        names.append(section.section_name or "(unnamed)")
    for para in division.paragraphs:
        names.append(para.paragraph_name)
    return names


def _fail(message: str) -> NoReturn:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Read source file
    try:
        with open(args.file, encoding="utf-8") as f:
            source = f.read()
    except FileNotFoundError:
        _fail(f"File not found: {args.file}")
    except OSError as e:
        _fail(f"Cannot read file: {e}")

    # Map dialect string to enum
    dialect_map = {"ibm-enterprise": DialectType.IBM_ENTERPRISE}
    dialect = dialect_map[args.dialect]

    # Parse
    result = parse_cobol(
        source,
        filename=args.file,
        dialect=dialect,
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        free_form=args.free_form,
    )

    if result.ast is None:
        error_lines = [str(e) for e in result.errors]
        _fail(
            f"Parse failed for {args.file}\n" + "\n".join(error_lines)
        )

    # Resolve path or output full AST
    if args.path:
        output = _resolve_path(result.ast, args.path)
    else:
        output = result.ast.to_dict()

    # Wrap with errors/stats if requested
    if args.errors or args.stats:
        wrapper: dict[str, Any] = {"ast": output}
        if args.errors:
            wrapper["errors"] = [str(e) for e in result.errors]
            wrapper["warnings"] = result.warnings
        if args.stats:
            wrapper["statistics"] = {
                "lines_processed": result.statistics.lines_processed,
                "tokens_processed": result.statistics.tokens_processed,
                "parse_time_seconds": result.statistics.parse_time_seconds,
                "memory_peak_mb": result.statistics.memory_peak_mb,
            }
        output = wrapper

    # Output JSON
    indent = None if args.compact else 2
    print(json.dumps(output, indent=indent))
