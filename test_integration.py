#!/usr/bin/env python3
"""Comprehensive integration test for the COBOL parser on all example programs."""

import os
import glob
import time
from collections import defaultdict, Counter
from pathlib import Path

from cobolparser import (
    CobolParser, IBMEnterpriseCobol, MemoryConfiguration, 
    parse_cobol, ErrorRecoveryMode
)


def test_single_program(file_path):
    """Test a single COBOL program and return results."""
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            cobol_source = f.read()
        
        start_time = time.time()
        result = parse_cobol(cobol_source, file_path)
        parse_time = time.time() - start_time
        
        # Count statements and divisions
        perform_count = 0
        move_count = 0
        total_statements = 0
        divisions = 0
        
        if result.ast and hasattr(result.ast, 'divisions'):
            divisions = len(result.ast.divisions)
            for division in result.ast.divisions:
                if hasattr(division, 'sections'):
                    for section in division.sections:
                        # Get statements from all paragraphs in the section
                        section_statements = []
                        if hasattr(section, 'paragraphs'):
                            for paragraph in section.paragraphs:
                                if hasattr(paragraph, 'statements'):
                                    section_statements.extend(paragraph.statements)
                        
                        total_statements += len(section_statements)
                        for stmt in section_statements:
                            if hasattr(stmt, 'node_type'):
                                stmt_type = str(stmt.node_type)
                                if 'PERFORM' in stmt_type:
                                    perform_count += 1
                                elif 'MOVE' in stmt_type:
                                    move_count += 1
        
        return {
            'filename': os.path.basename(file_path),
            'success': result.success,
            'program_name': result.ast.program_name if result.ast else None,
            'divisions': divisions,
            'total_statements': total_statements,
            'perform_count': perform_count,
            'move_count': move_count,
            'error_count': len(result.errors),
            'errors': result.errors,
            'parse_time': parse_time,
            'file_size': os.path.getsize(file_path)
        }
        
    except Exception as e:
        return {
            'filename': os.path.basename(file_path),
            'success': False,
            'program_name': None,
            'divisions': 0,
            'total_statements': 0,
            'perform_count': 0,
            'move_count': 0,
            'error_count': 1,
            'errors': [f"Exception: {str(e)}"],
            'parse_time': 0,
            'file_size': os.path.getsize(file_path) if os.path.exists(file_path) else 0
        }


def test_comprehensive():
    """Test all COBOL programs in examples/cobol directory."""
    print("=== Comprehensive COBOL Parser Test Suite ===")
    
    # Find all .CBL files
    cobol_dir = "examples/cobol"
    if not os.path.exists(cobol_dir):
        print(f"Error: Directory '{cobol_dir}' not found!")
        return
    
    cobol_files = glob.glob(os.path.join(cobol_dir, "*.CBL"))
    cobol_files.sort()  # Sort for consistent output
    
    print(f"Found {len(cobol_files)} COBOL programs to test")
    print("=" * 80)
    
    # Statistics tracking
    results = []
    successful_parses = 0
    total_errors = 0
    error_patterns = Counter()
    total_parse_time = 0
    total_file_size = 0
    
    # Test each program
    for i, file_path in enumerate(cobol_files, 1):
        print(f"[{i:3d}/{len(cobol_files)}] Testing {os.path.basename(file_path)}...", end=" ")
        
        result = test_single_program(file_path)
        results.append(result)
        
        # Update statistics
        if result['success']:
            successful_parses += 1
            print("SUCCESS")
        else:
            print("FAILED")
            if result['errors']:
                # Show first error briefly
                first_error = str(result['errors'][0])[:60]
                print(f"    Error: {first_error}{'...' if len(str(result['errors'][0])) > 60 else ''}")
        
        total_errors += result['error_count']
        total_parse_time += result['parse_time']
        total_file_size += result['file_size']
        
        # Collect error patterns
        for error in result['errors']:
            error_str = str(error)
            # Extract error type/pattern
            if "Lexer error:" in error_str:
                error_patterns["Lexer Error"] += 1
            elif "Expected" in error_str:
                error_patterns["Parser Expectation Error"] += 1
            elif "Invalid character:" in error_str:
                error_patterns["Invalid Character"] += 1
            elif "Unterminated" in error_str:
                error_patterns["Unterminated Literal"] += 1
            else:
                error_patterns["Other Error"] += 1
    
    # Print comprehensive summary
    print("\n" + "=" * 80)
    print("=== COMPREHENSIVE TEST RESULTS ===")
    print(f"Total programs tested: {len(cobol_files)}")
    print(f"Successful parses: {successful_parses} ({successful_parses/len(cobol_files)*100:.1f}%)")
    print(f"Failed parses: {len(cobol_files) - successful_parses} ({(len(cobol_files) - successful_parses)/len(cobol_files)*100:.1f}%)")
    print(f"Total errors: {total_errors}")
    print(f"Total parse time: {total_parse_time:.2f} seconds")
    print(f"Average parse time: {total_parse_time/len(cobol_files)*1000:.1f} ms per file")
    print(f"Total file size: {total_file_size/1024:.1f} KB")
    
    if error_patterns:
        print("\n=== ERROR PATTERNS ===")
        for error_type, count in error_patterns.most_common():
            print(f"  {error_type}: {count}")
    
    # Show top performers
    successful_results = [r for r in results if r['success']]
    if successful_results:
        print(f"\n=== SUCCESSFUL PROGRAMS ({len(successful_results)}) ===")
        
        # Group by characteristics
        programs_by_divisions = defaultdict(list)
        for result in successful_results:
            programs_by_divisions[result['divisions']].append(result['filename'])
        
        for div_count in sorted(programs_by_divisions.keys()):
            programs = programs_by_divisions[div_count]
            print(f"  {div_count} divisions: {len(programs)} programs")
            if len(programs) <= 5:
                print(f"    {', '.join(programs)}")
            else:
                print(f"    {', '.join(programs[:3])}, ... and {len(programs)-3} more")
        
        # Show programs with most statements
        top_statement_programs = sorted(successful_results, key=lambda x: x['total_statements'], reverse=True)[:5]
        print(f"\n=== LARGEST SUCCESSFULLY PARSED PROGRAMS ===")
        for result in top_statement_programs:
            print(f"  {result['filename']}: {result['total_statements']} statements, {result['divisions']} divisions")
    
    # Show failures if any
    failed_results = [r for r in results if not r['success']]
    if failed_results:
        print(f"\n=== FAILED PROGRAMS ({len(failed_results)}) ===")
        for result in failed_results[:10]:  # Show first 10 failures
            print(f"  {result['filename']}: {len(result['errors'])} errors")
            if result['errors']:
                print(f"    └─ {str(result['errors'][0])[:80]}{'...' if len(str(result['errors'][0])) > 80 else ''}")
        
        if len(failed_results) > 10:
            print(f"  ... and {len(failed_results) - 10} more failed programs")
    
    print("=" * 80)
    return results


if __name__ == "__main__":
    test_comprehensive()