"""
CALL Statement Coverage Validation Script

This script analyzes all CALL test programs and generates a detailed
coverage report showing parsing success rates and specific patterns.
"""
import sys
from pathlib import Path
from cobolparser.parser import CobolParser
from cobolparser.models.statements import CallStatement


def count_call_keywords(file_path):
    """Count CALL keywords in source file (simple text search)."""
    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()
    
    # Count CALL keywords (excluding comments)
    lines = content.split('\n')
    count = 0
    for line in lines:
        # Skip comment lines
        if line.strip().startswith('*'):
            continue
        # Count CALL occurrences
        if 'CALL ' in line.upper():
            count += 1
    
    return count


def count_call_statements_in_ast(node):
    """Recursively count CALL statements in AST."""
    count = 0
    
    if node is None:
        return count
    
    # Check if current node is a CALL statement
    if isinstance(node, CallStatement):
        count += 1
    
    # Recursively check children
    if hasattr(node, 'children') and node.children:
        for child in node.children:
            count += count_call_statements_in_ast(child)
    
    # Check divisions
    if hasattr(node, 'divisions'):
        for division in node.divisions:
            count += count_call_statements_in_ast(division)
    
    return count


def analyze_file(parser, file_path):
    """Analyze a single COBOL file for CALL coverage."""
    print(f"\nAnalyzing: {file_path.name}")
    print("-" * 70)
    
    # Count CALL keywords in source
    keyword_count = count_call_keywords(file_path)
    print(f"CALL keywords in source: {keyword_count}")
    
    # Parse file
    result = parser.parse_file(str(file_path))
    
    if not result.success:
        print(f"❌ Parse FAILED: {len(result.errors)} errors")
        for error in result.errors[:5]:  # Show first 5 errors
            print(f"   - {error}")
        return keyword_count, 0, False
    
    # Count CALL statements in AST
    ast_count = count_call_statements_in_ast(result.ast)
    print(f"CALL statements in AST: {ast_count}")
    
    # Calculate coverage
    if keyword_count > 0:
        coverage = (ast_count / keyword_count) * 100
        print(f"Coverage: {coverage:.1f}%")
        
        if coverage >= 95:
            print("✅ EXCELLENT coverage")
        elif coverage >= 80:
            print("✓ GOOD coverage")
        elif coverage >= 60:
            print("⚠ MODERATE coverage")
        else:
            print("❌ LOW coverage")
    else:
        coverage = 0
        print("No CALL keywords found")
    
    return keyword_count, ast_count, result.success


def main():
    """Main validation function."""
    print("=" * 70)
    print("CALL Statement Coverage Validation Report")
    print("=" * 70)
    
    # Get samples directory
    script_dir = Path(__file__).parent
    samples_dir = script_dir / "tests" / "samples"
    
    # Test files to analyze
    test_files = [
        "call_with_periods.cbl",
        "call_multiline_comprehensive.cbl",
        "call_with_comments.cbl",
        "call_exception_handlers_complete.cbl",
        "call_in_control_structures.cbl",
        "call_parameter_modes_complete.cbl",
        "call_returning_variations.cbl",
        "call_dynamic_programs.cbl",
        "call_real_world_banking.cbl",
        "call_real_world_insurance.cbl",
    ]
    
    parser = CobolParser()
    
    total_keywords = 0
    total_ast_calls = 0
    successful_files = 0
    
    results = []
    
    for filename in test_files:
        file_path = samples_dir / filename
        
        if not file_path.exists():
            print(f"\n⚠ File not found: {filename}")
            continue
        
        keywords, ast_calls, success = analyze_file(parser, file_path)
        
        total_keywords += keywords
        total_ast_calls += ast_calls
        if success:
            successful_files += 1
        
        coverage = (ast_calls / keywords * 100) if keywords > 0 else 0
        results.append({
            'file': filename,
            'keywords': keywords,
            'ast_calls': ast_calls,
            'coverage': coverage,
            'success': success
        })
    
    # Print summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"\nTotal files analyzed: {len(results)}")
    print(f"Successfully parsed: {successful_files}")
    print(f"Total CALL keywords: {total_keywords}")
    print(f"Total CALL statements in AST: {total_ast_calls}")
    
    if total_keywords > 0:
        overall_coverage = (total_ast_calls / total_keywords) * 100
        print(f"\n📊 Overall Coverage: {overall_coverage:.1f}%")
        
        if overall_coverage >= 95:
            print("✅ EXCELLENT - Target achieved!")
        elif overall_coverage >= 80:
            print("✓ GOOD - Close to target")
        elif overall_coverage >= 60:
            print("⚠ MODERATE - Needs improvement")
        else:
            print("❌ LOW - Significant work needed")
    
    # Print detailed table
    print("\n" + "=" * 70)
    print("DETAILED RESULTS")
    print("=" * 70)
    print(f"{'File':<40} {'Keywords':>10} {'AST':>10} {'Coverage':>10}")
    print("-" * 70)
    
    for r in results:
        status = "✅" if r['success'] else "❌"
        print(f"{r['file']:<40} {r['keywords']:>10} {r['ast_calls']:>10} {r['coverage']:>9.1f}% {status}")
    
    print("=" * 70)
    
    return 0 if overall_coverage >= 95 else 1


if __name__ == "__main__":
    sys.exit(main())
