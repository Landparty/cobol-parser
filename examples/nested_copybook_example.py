"""
Nested Copybook Expansion Example

This example demonstrates how to:
1. Expand nested copybooks (LEVEL1 → LEVEL2 → LEVEL3)
2. Extract information about the copybook hierarchy
3. Analyze the expansion results
4. Handle errors gracefully
"""

from pathlib import Path

from cobolparser import (
    CircularReferenceError,
    CopybookNotFoundError,
    NestingDepthError,
    expand_copybooks,
    parse_cobol_with_expansion,
)


def main():
    # Example COBOL program with nested copybooks
    cobol_program = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. NESTED-EXAMPLE.
       AUTHOR. COBOL-PARSER-DEMO.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
      * This COPY includes nested copybooks
       COPY LEVEL1.

       01 WS-COUNTER         PIC 9(4) VALUE ZERO.
       01 WS-STATUS          PIC X(10) VALUE SPACES.

       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY "Processing nested copybook example".
           MOVE "COMPLETE" TO WS-STATUS.
           STOP RUN.
    """

    # Path to copybooks (relative to the script location)
    script_dir = Path(__file__).parent.parent
    copybook_paths = [str(script_dir / "tests" / "samples" / "copybooks")]

    print("=" * 70)
    print("NESTED COPYBOOK EXPANSION EXAMPLE")
    print("=" * 70)

    try:
        # Expand the copybooks
        print("\n1. Expanding copybooks...")
        result = expand_copybooks(
            source_code=cobol_program,
            copybook_paths=copybook_paths,
            max_nesting_depth=10,
        )

        # Display basic information
        print("   [OK] Expansion successful!")
        print(f"   - Total copybooks included: {len(result.included_copybooks)}")
        print(f"   - Maximum nesting depth: {result.max_depth_reached}")
        print(f"   - Processing time: {result.statistics.parse_time_ms:.2f}ms")

        # Show copybook hierarchy
        print("\n2. Copybook Hierarchy:")
        for idx, copybook_path in enumerate(result.included_copybooks, 1):
            copybook_name = Path(copybook_path).name
            # Estimate indentation based on order (simplified)
            indent = "  " * (idx - 1) if idx <= 3 else "  " * 2
            print(f"{indent}+- {idx}. {copybook_name}")

        # Show source code growth
        original_lines = len(cobol_program.strip().splitlines())
        expanded_lines = len(result.expanded_source.strip().splitlines())
        growth_percent = (expanded_lines - original_lines) / original_lines * 100

        print("\n3. Source Code Analysis:")
        print(f"   - Original lines:  {original_lines}")
        print(f"   - Expanded lines:  {expanded_lines}")
        print(f"   - Growth:          +{growth_percent:.1f}%")
        print(f"   - Files processed: {result.statistics.file_count}")
        print(f"   - Total lines:     {result.statistics.total_lines}")

        # Show expanded source (first 20 lines)
        print("\n4. Expanded Source (first 20 lines):")
        print("-" * 70)
        expanded_lines_list = result.expanded_source.splitlines()
        for i, line in enumerate(expanded_lines_list[:20], 1):
            print(f"{i:3}: {line}")
        if len(expanded_lines_list) > 20:
            print(f"     ... ({len(expanded_lines_list) - 20} more lines)")
        print("-" * 70)

        # Export to JSON
        print("\n5. JSON Export:")
        json_output = result.to_dict()
        # Print a formatted subset
        print("   {")
        print(f'     "max_depth_reached": {json_output["max_depth_reached"]},')
        print('     "included_copybooks": [')
        for i, cb in enumerate(json_output["included_copybooks"]):
            comma = "," if i < len(json_output["included_copybooks"]) - 1 else ""
            print(f'       "{Path(cb).name}"{comma}')
        print("     ],")
        print('     "statistics": {')
        stats = json_output["statistics"]
        print(f'       "parse_time_ms": {stats["parse_time_ms"]:.2f},')
        print(f'       "file_count": {stats["file_count"]},')
        print(f'       "total_lines": {stats["total_lines"]}')
        print("     }")
        print("   }")

        # Parse with expansion
        print("\n6. Parsing Expanded Code:")
        parse_result = parse_cobol_with_expansion(
            source_code=cobol_program,
            filename="NESTED-EXAMPLE.cbl",
            copybook_paths=copybook_paths,
        )
        print("   [OK] Parsing successful!")
        if hasattr(parse_result, "ast") and parse_result.ast:
            print("   - AST generated successfully")

        # Success summary
        print("\n" + "=" * 70)
        print("SUCCESS: NESTED COPYBOOK EXPANSION COMPLETED SUCCESSFULLY")
        print("=" * 70)

    except CircularReferenceError as e:
        print("\n[ERROR] Circular reference detected!")
        print(f"   Dependency chain: {' -> '.join(e.dependency_chain)}")
        return 1

    except CopybookNotFoundError as e:
        print("\n[ERROR] Copybook not found!")
        print(f"   Missing copybook: {e.copybook_name}")
        print(f"   Searched in: {', '.join(e.search_paths)}")
        return 1

    except NestingDepthError as e:
        print("\n[ERROR] Nesting depth exceeded!")
        print(f"   Current depth: {e.current_depth}")
        print(f"   Maximum depth: {e.max_depth}")
        return 1

    except Exception as e:
        print(f"\n[ERROR] {type(e).__name__}: {e}")
        return 1

    return 0


def analyze_specific_copybook(copybook_name: str, copybook_paths: list[str]):
    """
    Analyze a specific copybook and show its structure.
    """
    print("\n" + "=" * 70)
    print(f"ANALYZING COPYBOOK: {copybook_name}")
    print("=" * 70)

    # Create a minimal program that just includes this copybook
    minimal_program = f"       COPY {copybook_name}."

    try:
        result = expand_copybooks(minimal_program, copybook_paths)

        print("\nCopybook Information:")
        print(f"  - Nesting depth: {result.max_depth_reached}")
        print(f"  - Nested copybooks: {len(result.included_copybooks)}")

        if len(result.included_copybooks) > 1:
            print("\n  Nested copybooks included:")
            for idx, path in enumerate(result.included_copybooks, 1):
                name = Path(path).name
                indent = "    " + ("  " * (idx - 1))
                print(f"{indent}{idx}. {name}")

        print("\n  Expanded content:")
        print("  " + "-" * 66)
        for line in result.expanded_source.splitlines()[:15]:
            print(f"  {line}")
        if len(result.expanded_source.splitlines()) > 15:
            remaining = len(result.expanded_source.splitlines()) - 15
            print(f"  ... ({remaining} more lines)")
        print("  " + "-" * 66)

    except Exception as e:
        print(f"  [ERROR] {e}")


if __name__ == "__main__":
    import sys

    exit_code = main()

    # Optionally analyze specific copybooks
    if exit_code == 0:
        script_dir = Path(__file__).parent.parent
        copybook_paths = [str(script_dir / "tests" / "samples" / "copybooks")]

        # Analyze LEVEL1 copybook specifically
        analyze_specific_copybook("LEVEL1", copybook_paths)

        # Analyze EMPLOYEE copybook
        analyze_specific_copybook("EMPLOYEE", copybook_paths)

        # Show PROCEDURE DIVISION copybook usage
        print(f"\n{'=' * 70}")
        print("BONUS: COPY Statement in PROCEDURE DIVISION")
        print("=" * 70)
        print("\nCopybook expansion works in ANY division, including PROCEDURE!")
        print("\nExample:")
        print("""
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           DISPLAY "Starting".
           COPY STANDARD-PROCEDURES.
           STOP RUN.

Where STANDARD-PROCEDURES.cpy contains:
       MOVE "ACTIVE" TO WS-STATUS.
       PERFORM INITIALIZE-ROUTINE.
       PERFORM PROCESS-DATA.

This allows you to reuse common procedure code across programs!
""")

    sys.exit(exit_code)
