#!/usr/bin/env python3
"""
Advanced COBOL Parser Examples

This file demonstrates advanced features including memory management,
JSON serialization, error recovery, performance monitoring, and
complex program structures.
"""

import json
import time
from pathlib import Path

from cobolparser import CobolParser, parse_cobol
from cobolparser.plugins.core import (
    MemoryConfiguration, SerializationConfig, ErrorRecoveryMode,
    DialectType, ParseStatistics
)


def example_1_memory_management():
    """Demonstrate advanced memory management features."""
    print("=" * 60)
    print("ADVANCED EXAMPLE 1: Memory Management")
    print("=" * 60)
    
    # Create a large COBOL program to test memory handling
    large_cobol = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MEMORY-TEST.
       AUTHOR. MEMORY MANAGEMENT DEMO.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
    '''
    
    # Add many data items to simulate a large program
    for i in range(1000):
        large_cobol += f'''
       01  WS-DATA-ITEM-{i:04d}  PIC X(100) VALUE SPACES.
       01  WS-COUNTER-{i:04d}    PIC 9(7) COMP-3 VALUE ZERO.
        '''
    
    large_cobol += '''
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           DISPLAY "Processing large data structure...".
    '''
    
    # Add many statements
    for i in range(100):
        large_cobol += f'''
           MOVE {i:04d} TO WS-COUNTER-{i:04d}.
           DISPLAY "Counter " WS-COUNTER-{i:04d}.
        '''
    
    large_cobol += '''
           STOP RUN.
    '''
    
    # Test different memory configurations
    configs = [
        ("Small (128MB)", MemoryConfiguration(max_memory_mb=128, chunk_size_kb=256)),
        ("Medium (512MB)", MemoryConfiguration(max_memory_mb=512, chunk_size_kb=512)),
        ("Large (1GB)", MemoryConfiguration(max_memory_mb=1024, chunk_size_kb=1024, enable_streaming=True))
    ]
    
    for config_name, memory_config in configs:
        print(f"\n📊 Testing {config_name} Configuration:")
        print(f"   Max Memory: {memory_config.max_memory_mb}MB")
        print(f"   Chunk Size: {memory_config.chunk_size_kb}KB")
        print(f"   Streaming: {memory_config.enable_streaming}")
        
        parser = CobolParser(memory_config=memory_config)
        
        start_time = time.time()
        result = parser.parse(large_cobol, f"large_program_{config_name.lower().replace(' ', '_')}.cob")
        parse_time = time.time() - start_time
        
        print(f"   ✅ Parse Success: {result.success}")
        print(f"   ⏱️  Parse Time: {parse_time * 1000:.2f}ms")
        print(f"   📏 Lines Parsed: {result.statistics.lines_parsed}")
        print(f"   🔢 Tokens: {result.statistics.tokens_processed}")
        print(f"   💾 Peak Memory: {result.statistics.memory_peak_mb:.2f}MB")
        
        if result.ast:
            data_div = result.ast.get_division_by_name("DATA")
            if data_div:
                ws_section = data_div.get_section_by_name("WORKING-STORAGE")
                if ws_section:
                    print(f"   📁 Data Items: {len(ws_section.children)}")


def example_2_json_serialization():
    """Demonstrate comprehensive JSON serialization."""
    print("\n" + "=" * 60)
    print("ADVANCED EXAMPLE 2: JSON Serialization")
    print("=" * 60)
    
    cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. JSON-DEMO.
       AUTHOR. JSON SERIALIZATION DEMO.
       DATE-WRITTEN. SEPTEMBER 2025.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-390.
       OBJECT-COMPUTER. IBM-390.
       
       DATA DIVISION.
       FILE SECTION.
       FD  EMPLOYEE-FILE
           RECORD CONTAINS 150 CHARACTERS.
       01  EMPLOYEE-RECORD.
           05  EMP-ID           PIC 9(6).
           05  EMP-NAME         PIC X(30).
           05  EMP-DEPARTMENT   PIC X(20).
           05  EMP-SALARY       PIC 9(7)V99 COMP-3.
           05  EMP-HIRE-DATE    PIC 9(8).
       
       WORKING-STORAGE SECTION.
       01  WS-EMPLOYEE-TOTALS.
           05  WS-TOTAL-EMPLOYEES   PIC 9(5) VALUE ZERO.
           05  WS-TOTAL-SALARY      PIC 9(11)V99 COMP-3 VALUE ZERO.
           05  WS-AVERAGE-SALARY    PIC 9(7)V99 COMP-3.
       
       01  WS-DEPARTMENT-ARRAY.
           05  WS-DEPT-TABLE OCCURS 10 TIMES.
               10  WS-DEPT-NAME     PIC X(20).
               10  WS-DEPT-COUNT    PIC 9(3).
               10  WS-DEPT-TOTAL    PIC 9(9)V99 COMP-3.
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           OPEN INPUT EMPLOYEE-FILE.
           PERFORM READ-EMPLOYEES UNTIL END-OF-FILE.
           CLOSE EMPLOYEE-FILE.
           PERFORM CALCULATE-STATISTICS.
           PERFORM DISPLAY-RESULTS.
           STOP RUN.
           
       READ-EMPLOYEES.
           READ EMPLOYEE-FILE INTO EMPLOYEE-RECORD
               AT END SET END-OF-FILE TO TRUE
           END-READ.
           
           IF NOT END-OF-FILE
               ADD 1 TO WS-TOTAL-EMPLOYEES
               ADD EMP-SALARY TO WS-TOTAL-SALARY
           END-IF.
           
       CALCULATE-STATISTICS.
           IF WS-TOTAL-EMPLOYEES > ZERO
               COMPUTE WS-AVERAGE-SALARY = 
                   WS-TOTAL-SALARY / WS-TOTAL-EMPLOYEES
           END-IF.
           
       DISPLAY-RESULTS.
           DISPLAY "Total Employees: " WS-TOTAL-EMPLOYEES.
           DISPLAY "Average Salary: " WS-AVERAGE-SALARY.
    '''
    
    # Test different serialization configurations
    configs = [
        ("Minimal", SerializationConfig(
            include_metadata=False,
            include_source_locations=False,
            compact_format=True
        )),
        ("Standard", SerializationConfig(
            include_metadata=True,
            include_source_locations=True,
            compact_format=False
        )),
        ("Complete", SerializationConfig(
            include_metadata=True,
            include_source_locations=True,
            compact_format=False
        ))
    ]
    
    for config_name, serialization_config in configs:
        print(f"\n📤 {config_name} JSON Serialization:")
        
        parser = CobolParser(serialization_config=serialization_config)
        result = parser.parse(cobol_source, "json_demo.cob")
        
        if result.ast:
            # Serialize to JSON
            ast_json = result.ast.to_json(serialization_config)
            
            # Save to file
            filename = f"ast_{config_name.lower()}.json"
            with open(filename, 'w') as f:
                if serialization_config.compact_format:
                    json.dump(ast_json, f, separators=(',', ':'))
                else:
                    json.dump(ast_json, f, indent=2)
            
            # Show statistics
            file_size = Path(filename).stat().st_size
            print(f"   📁 File: {filename}")
            print(f"   📏 Size: {file_size:,} bytes")
            print(f"   🏗️  Metadata: {'✅' if serialization_config.include_metadata else '❌'}")
            print(f"   📍 Locations: {'✅' if serialization_config.include_source_locations else '❌'}")
            print(f"   📦 Compact: {'✅' if serialization_config.compact_format else '❌'}")
            
            # Show sample JSON structure
            if config_name == "Standard":
                print(f"\n📋 Sample JSON Structure:")
                sample = {
                    "program_name": ast_json.get("program_name"),
                    "divisions": list(ast_json.get("divisions", {}).keys()),
                    "statistics": {
                        "division_count": ast_json.get("division_count"),
                        "source_lines": ast_json.get("source_lines")
                    }
                }
                if serialization_config.include_metadata:
                    sample["metadata"] = ast_json.get("metadata", {})
                
                print(json.dumps(sample, indent=2))
            
            # Clean up
            Path(filename).unlink(missing_ok=True)


def example_3_error_recovery_modes():
    """Demonstrate different error recovery strategies."""
    print("\n" + "=" * 60)
    print("ADVANCED EXAMPLE 3: Error Recovery Modes")
    print("=" * 60)
    
    # Program with multiple types of errors
    buggy_cobol = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ERROR-TEST.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-VALID-FIELD       PIC X(10) VALUE "VALID".
       01  WS-MISSING-PERIOD    PIC 9(5) VALUE 12345  # Missing period
       01  WS-INVALID-PIC       PIC Z(XX) VALUE ZERO.   # Invalid picture
       01  WS-ANOTHER-FIELD     PIC X(20).
       01                       PIC 9(3).              # Missing name
       01  WS-BAD-VALUE         PIC 9(5) VALUE "ABC".  # Type mismatch
       
       PROCEDURE DIVISION.
       MAIN-PARA.
           DISPLAY WS-VALID-FIELD.
           MOVE "TEST" TO WS-MISSING-PERIOD.          # Type mismatch
           INVALID-STATEMENT WS-ANOTHER-FIELD.         # Invalid statement
           DISPLAY WS-ANOTHER-FIELD
           STOP RUN.
    '''
    
    # Test both error recovery modes
    modes = [
        ("Fail Fast", ErrorRecoveryMode.FAIL_FAST),
        ("Collect All", ErrorRecoveryMode.COLLECT_ALL)
    ]
    
    for mode_name, error_mode in modes:
        print(f"\n🔧 Testing {mode_name} Mode:")
        
        parser = CobolParser(error_recovery=error_mode)
        result = parser.parse(buggy_cobol, f"error_test_{mode_name.lower().replace(' ', '_')}.cob")
        
        print(f"   ✅ Parse Completed: {result.success}")
        print(f"   ❌ Errors Found: {len(result.errors)}")
        print(f"   ⚠️  Warnings: {len(result.warnings)}")
        
        if result.errors:
            print(f"   📋 Error Details:")
            max_errors = len(result.errors) if error_mode == ErrorRecoveryMode.COLLECT_ALL else min(1, len(result.errors))
            for i, error in enumerate(result.errors[:max_errors], 1):
                print(f"      {i}. Line {error.line}: {error.message}")
            
            if len(result.errors) > max_errors:
                print(f"      ... and {len(result.errors) - max_errors} more errors")
        
        if result.warnings:
            print(f"   ⚠️  Sample Warnings:")
            for i, warning in enumerate(result.warnings[:3], 1):
                print(f"      {i}. {warning}")
        
        # Show partial AST availability
        if result.ast:
            print(f"   🏗️  Partial AST: Available")
            print(f"      Program: {result.ast.program_name}")
            print(f"      Divisions: {len(result.ast.divisions)}")
        else:
            print(f"   🏗️  Partial AST: Not available")
        
        print(f"   📈 Recovery Strategy: {mode_name}")


def example_4_performance_monitoring():
    """Demonstrate performance monitoring and statistics."""
    print("\n" + "=" * 60)
    print("ADVANCED EXAMPLE 4: Performance Monitoring")
    print("=" * 60)
    
    # Create programs of different sizes
    test_programs = []
    
    # Small program
    small_program = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SMALL-PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATA    PIC X(10).
       PROCEDURE DIVISION.
       DISPLAY "Small program".
       STOP RUN.
    '''
    test_programs.append(("Small (10 lines)", small_program))
    
    # Medium program
    medium_program = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MEDIUM-PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
    '''
    for i in range(50):
        medium_program += f'       01  WS-FIELD-{i:03d}     PIC X(20) VALUE SPACES.\n'
    
    medium_program += '''
       PROCEDURE DIVISION.
       MAIN-PROCESS.
    '''
    for i in range(25):
        medium_program += f'           MOVE "VALUE-{i:03d}" TO WS-FIELD-{i:03d}.\n'
    
    medium_program += '''
           STOP RUN.
    '''
    test_programs.append(("Medium (100+ lines)", medium_program))
    
    # Large program
    large_program = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. LARGE-PROG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
    '''
    for i in range(200):
        large_program += f'       01  WS-BIG-FIELD-{i:04d} PIC X(50) VALUE SPACES.\n'
        large_program += f'       01  WS-BIG-NUM-{i:04d}   PIC 9(10) COMP-3 VALUE ZERO.\n'
    
    large_program += '''
       PROCEDURE DIVISION.
       MAIN-LOGIC.
    '''
    for i in range(100):
        large_program += f'           MOVE {i:04d} TO WS-BIG-NUM-{i:04d}.\n'
        large_program += f'           DISPLAY WS-BIG-FIELD-{i:04d}.\n'
    
    large_program += '''
           STOP RUN.
    '''
    test_programs.append(("Large (600+ lines)", large_program))
    
    print(f"🚀 Performance Benchmarking:")
    print(f"{'Program Size':<20} {'Parse Time':<12} {'Tokens':<8} {'Memory':<10} {'Rate':<15}")
    print("-" * 70)
    
    for prog_name, prog_source in test_programs:
        # Performance monitoring
        parser = CobolParser()
        
        start_time = time.time()
        result = parser.parse(prog_source, f"{prog_name.lower().replace(' ', '_')}.cob")
        end_time = time.time()
        
        parse_time_ms = (end_time - start_time) * 1000
        lines_per_second = result.statistics.lines_parsed / ((end_time - start_time) or 0.001)
        tokens_per_ms = result.statistics.tokens_processed / (parse_time_ms or 0.001)
        
        print(f"{prog_name:<20} {parse_time_ms:>8.2f}ms {result.statistics.tokens_processed:>7d} "
              f"{result.statistics.memory_peak_mb:>6.1f}MB {lines_per_second:>10.0f} l/s")
        
        # Detailed statistics for largest program
        if "Large" in prog_name:
            print(f"\n📊 Detailed Statistics for {prog_name}:")
            stats = result.statistics
            print(f"   ⏱️  Total Time: {stats.total_time_ms:.2f}ms")
            print(f"   📏 Lines Processed: {stats.lines_parsed:,}")
            print(f"   🔢 Tokens Processed: {stats.tokens_processed:,}")
            print(f"   💾 Peak Memory: {stats.memory_peak_mb:.2f}MB")
            print(f"   ❌ Errors: {stats.error_count}")
            print(f"   ⚠️  Warnings: {stats.warning_count}")
            print(f"   📈 Processing Rate:")
            print(f"      Lines/second: {lines_per_second:,.0f}")
            print(f"      Tokens/millisecond: {tokens_per_ms:.1f}")
            
            if result.ast:
                print(f"   🏗️  AST Structure:")
                print(f"      Program: {result.ast.program_name}")
                print(f"      Divisions: {len(result.ast.divisions)}")
                
                total_nodes = 0
                for div_name, division in result.ast.divisions.items():
                    section_count = len(division.sections)
                    total_items = sum(len(section.children) for section in division.sections.values())
                    total_nodes += total_items
                    print(f"      {division.division_name}: {section_count} sections, {total_items} items")
                
                print(f"      Total AST nodes: {total_nodes:,}")


def example_5_complex_program_analysis():
    """Analyze a complex COBOL program structure."""
    print("\n" + "=" * 60)
    print("ADVANCED EXAMPLE 5: Complex Program Analysis")
    print("=" * 60)
    
    complex_cobol = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPLEX-ANALYSIS.
       AUTHOR. COBOL PARSER TEAM.
       DATE-WRITTEN. SEPTEMBER 2025.
       DATE-COMPILED. SEPTEMBER 2025.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-390.
       OBJECT-COMPUTER. IBM-390.
       SPECIAL-NAMES.
           DECIMAL-POINT IS COMMA.
       
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MASTER-FILE ASSIGN TO MASTFILE
               ORGANIZATION IS INDEXED
               ACCESS MODE IS DYNAMIC
               RECORD KEY IS MASTER-KEY
               FILE STATUS IS WS-MASTER-STATUS.
           
           SELECT TRANSACTION-FILE ASSIGN TO TRANFILE
               ORGANIZATION IS SEQUENTIAL
               FILE STATUS IS WS-TRANS-STATUS.
               
           SELECT REPORT-FILE ASSIGN TO REPTFILE
               ORGANIZATION IS SEQUENTIAL.
       
       DATA DIVISION.
       FILE SECTION.
       FD  MASTER-FILE
           RECORD CONTAINS 200 CHARACTERS.
       01  MASTER-RECORD.
           05  MASTER-KEY           PIC X(10).
           05  MASTER-DATA.
               10  CUST-NAME        PIC X(30).
               10  CUST-ADDRESS     PIC X(50).
               10  CUST-BALANCE     PIC S9(9)V99 COMP-3.
               10  CUST-CREDIT      PIC 9(7)V99 COMP-3.
               10  CUST-STATUS      PIC X.
                   88  ACTIVE-CUST     VALUE 'A'.
                   88  INACTIVE-CUST   VALUE 'I'.
               10  LAST-TRANS-DATE  PIC 9(8).
       
       FD  TRANSACTION-FILE
           RECORD CONTAINS 100 CHARACTERS.
       01  TRANSACTION-RECORD.
           05  TRANS-KEY            PIC X(10).
           05  TRANS-TYPE           PIC X.
               88  PAYMENT-TRANS       VALUE 'P'.
               88  CHARGE-TRANS        VALUE 'C'.
               88  ADJUSTMENT-TRANS    VALUE 'A'.
           05  TRANS-AMOUNT         PIC S9(7)V99 COMP-3.
           05  TRANS-DATE           PIC 9(8).
           05  TRANS-REFERENCE      PIC X(20).
       
       FD  REPORT-FILE
           RECORD CONTAINS 132 CHARACTERS.
       01  REPORT-RECORD            PIC X(132).
       
       WORKING-STORAGE SECTION.
       01  WS-FILE-STATUS-CODES.
           05  WS-MASTER-STATUS     PIC XX.
               88  MASTER-OK           VALUE '00'.
               88  MASTER-NOT-FOUND    VALUE '23'.
           05  WS-TRANS-STATUS      PIC XX.
               88  TRANS-OK            VALUE '00'.
               88  TRANS-EOF           VALUE '10'.
       
       01  WS-COUNTERS.
           05  WS-RECORDS-READ      PIC 9(7) COMP-3 VALUE ZERO.
           05  WS-RECORDS-UPDATED   PIC 9(7) COMP-3 VALUE ZERO.
           05  WS-RECORDS-ADDED     PIC 9(7) COMP-3 VALUE ZERO.
           05  WS-RECORDS-DELETED   PIC 9(7) COMP-3 VALUE ZERO.
           05  WS-ERROR-COUNT       PIC 9(5) COMP-3 VALUE ZERO.
       
       01  WS-TOTALS.
           05  WS-TOTAL-PAYMENTS    PIC S9(11)V99 COMP-3 VALUE ZERO.
           05  WS-TOTAL-CHARGES     PIC S9(11)V99 COMP-3 VALUE ZERO.
           05  WS-NET-CHANGE        PIC S9(11)V99 COMP-3 VALUE ZERO.
       
       01  WS-WORK-AREAS.
           05  WS-CURRENT-DATE      PIC 9(8).
           05  WS-REPORT-LINE       PIC X(132).
           05  WS-PAGE-NUMBER       PIC 9(3) VALUE 1.
           05  WS-LINE-COUNT        PIC 9(2) VALUE 99.
       
       PROCEDURE DIVISION.
       MAIN-CONTROL SECTION.
       000-MAIN-PROCESS.
           PERFORM 100-INITIALIZATION.
           PERFORM 200-PROCESS-TRANSACTIONS.
           PERFORM 300-FINALIZATION.
           STOP RUN.
           
       INITIALIZATION SECTION.
       100-INITIALIZATION.
           ACCEPT WS-CURRENT-DATE FROM DATE YYYYMMDD.
           OPEN INPUT TRANSACTION-FILE.
           OPEN I-O MASTER-FILE.
           OPEN OUTPUT REPORT-FILE.
           PERFORM 150-PRINT-HEADERS.
           
       150-PRINT-HEADERS.
           MOVE SPACES TO WS-REPORT-LINE.
           STRING "TRANSACTION PROCESSING REPORT - " 
                  WS-CURRENT-DATE
                  DELIMITED BY SIZE
                  INTO WS-REPORT-LINE.
           WRITE REPORT-RECORD FROM WS-REPORT-LINE.
           
       PROCESS SECTION.
       200-PROCESS-TRANSACTIONS.
           PERFORM 210-READ-TRANSACTION.
           PERFORM 220-PROCESS-RECORD 
               UNTIL TRANS-EOF.
           
       210-READ-TRANSACTION.
           READ TRANSACTION-FILE
               AT END SET TRANS-EOF TO TRUE
           END-READ.
           
       220-PROCESS-RECORD.
           ADD 1 TO WS-RECORDS-READ.
           
           EVALUATE TRUE
               WHEN PAYMENT-TRANS
                   PERFORM 230-PROCESS-PAYMENT
               WHEN CHARGE-TRANS
                   PERFORM 240-PROCESS-CHARGE
               WHEN ADJUSTMENT-TRANS
                   PERFORM 250-PROCESS-ADJUSTMENT
               WHEN OTHER
                   PERFORM 260-PROCESS-ERROR
           END-EVALUATE.
           
           PERFORM 210-READ-TRANSACTION.
           
       230-PROCESS-PAYMENT.
           PERFORM 270-READ-MASTER.
           IF MASTER-OK
               SUBTRACT TRANS-AMOUNT FROM CUST-BALANCE
               ADD TRANS-AMOUNT TO WS-TOTAL-PAYMENTS
               PERFORM 280-UPDATE-MASTER
           END-IF.
           
       240-PROCESS-CHARGE.
           PERFORM 270-READ-MASTER.
           IF MASTER-OK
               ADD TRANS-AMOUNT TO CUST-BALANCE
               ADD TRANS-AMOUNT TO WS-TOTAL-CHARGES
               PERFORM 280-UPDATE-MASTER
           END-IF.
           
       250-PROCESS-ADJUSTMENT.
           PERFORM 270-READ-MASTER.
           IF MASTER-OK
               ADD TRANS-AMOUNT TO CUST-BALANCE
               PERFORM 280-UPDATE-MASTER
           END-IF.
           
       260-PROCESS-ERROR.
           ADD 1 TO WS-ERROR-COUNT.
           MOVE SPACES TO WS-REPORT-LINE.
           STRING "ERROR: Invalid transaction type for key "
                  TRANS-KEY
                  DELIMITED BY SIZE
                  INTO WS-REPORT-LINE.
           WRITE REPORT-RECORD FROM WS-REPORT-LINE.
           
       270-READ-MASTER.
           MOVE TRANS-KEY TO MASTER-KEY.
           READ MASTER-FILE
               INVALID KEY SET MASTER-NOT-FOUND TO TRUE
           END-READ.
           
       280-UPDATE-MASTER.
           MOVE WS-CURRENT-DATE TO LAST-TRANS-DATE.
           REWRITE MASTER-RECORD
               INVALID KEY ADD 1 TO WS-ERROR-COUNT
           END-REWRITE.
           IF MASTER-OK
               ADD 1 TO WS-RECORDS-UPDATED
           END-IF.
           
       FINALIZATION SECTION.
       300-FINALIZATION.
           PERFORM 310-PRINT-TOTALS.
           CLOSE TRANSACTION-FILE.
           CLOSE MASTER-FILE.
           CLOSE REPORT-FILE.
           
       310-PRINT-TOTALS.
           COMPUTE WS-NET-CHANGE = WS-TOTAL-CHARGES - WS-TOTAL-PAYMENTS.
           
           MOVE SPACES TO WS-REPORT-LINE.
           WRITE REPORT-RECORD FROM WS-REPORT-LINE.
           
           STRING "PROCESSING TOTALS:" 
                  DELIMITED BY SIZE 
                  INTO WS-REPORT-LINE.
           WRITE REPORT-RECORD FROM WS-REPORT-LINE.
           
           STRING "Records Read: " WS-RECORDS-READ
                  DELIMITED BY SIZE 
                  INTO WS-REPORT-LINE.
           WRITE REPORT-RECORD FROM WS-REPORT-LINE.
           
           STRING "Records Updated: " WS-RECORDS-UPDATED
                  DELIMITED BY SIZE 
                  INTO WS-REPORT-LINE.
           WRITE REPORT-RECORD FROM WS-REPORT-LINE.
    '''
    
    # Parse with comprehensive analysis
    parser = CobolParser(
        error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        memory_config=MemoryConfiguration(max_memory_mb=256)
    )
    
    result = parser.parse(complex_cobol, "complex_analysis.cob")
    
    print(f"✅ Parse Success: {result.success}")
    print(f"📊 Comprehensive Program Analysis:")
    
    if result.ast:
        # Program-level analysis
        print(f"\n🏗️  Program Structure:")
        print(f"   Program ID: {result.ast.program_name}")
        print(f"   Total Divisions: {len(result.ast.divisions)}")
        
        # Division-by-division analysis
        for div_name, division in result.ast.divisions.items():
            print(f"\n📂 {division.division_name} Division:")
            print(f"   Sections: {len(division.sections)}")
            
            total_items = 0
            for sec_name, section in division.sections.items():
                item_count = len(section.children)
                total_items += item_count
                print(f"      📄 {section.section_name}: {item_count} items")
            
            print(f"   Total Items: {total_items}")
        
        # Data structure analysis
        data_div = result.ast.get_division_by_name("DATA")
        if data_div:
            print(f"\n📊 Data Structure Analysis:")
            
            # File definitions
            file_section = data_div.get_section_by_name("FILE")
            if file_section:
                print(f"   📁 File Definitions: {len(file_section.children)}")
            
            # Working storage analysis
            ws_section = data_div.get_section_by_name("WORKING-STORAGE")
            if ws_section:
                print(f"   💾 Working Storage Items: {len(ws_section.children)}")
                
                # Count different data types
                comp3_count = 0
                display_count = 0
                level_88_count = 0
                
                def count_data_types(items):
                    nonlocal comp3_count, display_count, level_88_count
                    for item in items:
                        if hasattr(item, 'level'):
                            if item.level == 88:
                                level_88_count += 1
                            elif hasattr(item, 'usage'):
                                if 'COMP-3' in str(item.usage):
                                    comp3_count += 1
                                else:
                                    display_count += 1
                        
                        if hasattr(item, 'children'):
                            count_data_types(item.children)
                
                count_data_types(ws_section.children)
                
                print(f"      💰 COMP-3 Fields: {comp3_count}")
                print(f"      📝 Display Fields: {display_count}")
                print(f"      🎯 Condition Names (88): {level_88_count}")
        
        # Procedure analysis
        proc_div = result.ast.get_division_by_name("PROCEDURE")
        if proc_div:
            print(f"\n🔧 Procedure Analysis:")
            total_statements = len(proc_div.children)
            print(f"   Total Statements/Paragraphs: {total_statements}")
            
            # Count sections if any
            section_count = len(proc_div.sections)
            if section_count > 0:
                print(f"   Sections: {section_count}")
                for sec_name, section in proc_div.sections.items():
                    print(f"      📋 {section.section_name}: {len(section.children)} paragraphs")
    
    # Performance metrics
    print(f"\n📈 Performance Metrics:")
    print(f"   ⏱️  Parse Time: {result.statistics.total_time_ms:.2f}ms")
    print(f"   📏 Source Lines: {result.statistics.lines_parsed}")
    print(f"   🔢 Tokens: {result.statistics.tokens_processed:,}")
    print(f"   💾 Peak Memory: {result.statistics.memory_peak_mb:.2f}MB")
    
    if result.statistics.lines_parsed > 0:
        processing_rate = result.statistics.tokens_processed / (result.statistics.total_time_ms or 1)
        print(f"   📊 Processing Rate: {processing_rate:.0f} tokens/ms")
    
    # Error summary
    if result.errors or result.warnings:
        print(f"\n⚠️  Issues Found:")
        print(f"   ❌ Errors: {len(result.errors)}")
        print(f"   ⚠️  Warnings: {len(result.warnings)}")
    else:
        print(f"\n✅ No errors or warnings found!")


def main():
    """Run all advanced examples."""
    print("🚀 COBOL Parser - Advanced Examples")
    print("Demonstrating advanced features and capabilities\n")
    
    try:
        example_1_memory_management()
        example_2_json_serialization()
        example_3_error_recovery_modes()
        example_4_performance_monitoring()
        example_5_complex_program_analysis()
        
        print("\n" + "=" * 60)
        print("✅ All advanced examples completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Advanced example failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()