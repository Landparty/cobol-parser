#!/usr/bin/env python3
"""
Basic COBOL Parser Examples

This file demonstrates the fundamental usage of the COBOL parser with simple examples.
"""

from cobolparser import parse_cobol, CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

def example_1_hello_world():
    """Parse a simple Hello World COBOL program."""
    print("=" * 60)
    print("EXAMPLE 1: Hello World Program")
    print("=" * 60)
    
    cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-WORLD.
       AUTHOR. COBOL PARSER DEMO.
       
       PROCEDURE DIVISION.
       DISPLAY "Hello, COBOL Parser!".
       STOP RUN.
    '''
    
    result = parse_cobol(cobol_source, "hello.cob")
    
    print(f"✅ Parse Success: {result.success}")
    print(f"📁 Program Name: {result.ast.program_name}")
    print(f"📊 Divisions: {len(result.ast.divisions)}")
    print(f"⚡ Parse Time: {result.statistics.total_time_ms:.2f}ms")
    
    if result.ast:
        for div_name, division in result.ast.divisions.items():
            print(f"  📂 {division.division_name} Division")


def example_2_data_definitions():
    """Parse a program with data definitions."""
    print("\n" + "=" * 60)
    print("EXAMPLE 2: Data Definitions")
    print("=" * 60)
    
    cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATA-DEMO.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-CUSTOMER-REC.
           05  WS-CUST-ID       PIC 9(6).
           05  WS-CUST-NAME     PIC X(30).
           05  WS-BALANCE       PIC 9(7)V99.
           05  WS-STATUS        PIC X.
       
       01  WS-COUNTERS.
           05  WS-RECORD-COUNT  PIC 9(5) VALUE ZERO.
           05  WS-ERROR-COUNT   PIC 9(3) VALUE ZERO.
       
       PROCEDURE DIVISION.
       MAIN-PROCESS.
           DISPLAY "Processing customer records...".
           STOP RUN.
    '''
    
    result = parse_cobol(cobol_source, "data_demo.cob")
    
    print(f"✅ Parse Success: {result.success}")
    print(f"📊 Statistics:")
    print(f"  Lines: {result.statistics.lines_parsed}")
    print(f"  Tokens: {result.statistics.tokens_processed}")
    
    if result.ast:
        # Find DATA DIVISION
        data_div = result.ast.get_division_by_name("DATA")
        if data_div:
            ws_section = data_div.get_section_by_name("WORKING-STORAGE")
            if ws_section:
                print(f"📁 Working Storage Items: {len(ws_section.children)}")
                
                for item in ws_section.children:
                    if hasattr(item, 'name'):
                        picture = item.picture_clause.pattern if item.picture_clause else "N/A"
                        value = getattr(item, 'initial_value', 'None')
                        print(f"  📄 {item.level:02d} {item.name} PIC {picture} VALUE {value}")


def example_3_arithmetic_statements():
    """Parse a program with arithmetic statements."""
    print("\n" + "=" * 60)
    print("EXAMPLE 3: Arithmetic Operations")
    print("=" * 60)
    
    cobol_source = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALC-DEMO.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM1          PIC 9(5) VALUE 100.
       01  WS-NUM2          PIC 9(5) VALUE 50.
       01  WS-RESULT        PIC 9(6).
       01  WS-TOTAL         PIC 9(7)V99 VALUE ZERO.
       
       PROCEDURE DIVISION.
       CALCULATE-VALUES.
           MOVE WS-NUM1 TO WS-RESULT.
           ADD WS-NUM2 TO WS-RESULT.
           DISPLAY "Sum: " WS-RESULT.
           
           MULTIPLY WS-NUM1 BY WS-NUM2 GIVING WS-TOTAL.
           DISPLAY "Product: " WS-TOTAL.
           
           STOP RUN.
    '''
    
    result = parse_cobol(cobol_source, "calc_demo.cob")
    
    print(f"✅ Parse Success: {result.success}")
    
    if result.ast:
        proc_div = result.ast.get_division_by_name("PROCEDURE")
        if proc_div:
            statement_count = len(proc_div.children)
            print(f"📝 Procedure Statements: {statement_count}")
            
            for child in proc_div.children:
                if hasattr(child, 'statement_type'):
                    print(f"  🔧 {child.statement_type} statement")


def example_4_error_handling():
    """Demonstrate error handling capabilities."""
    print("\n" + "=" * 60)
    print("EXAMPLE 4: Error Handling")
    print("=" * 60)
    
    # Program with intentional errors
    buggy_cobol = '''
       IDENTIFICATION DIVISION.
       PROGRAM-ID. BUGGY-PROG.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATA          PIC X(10)  # Missing period
       01  WS-AMOUNT        # Missing PIC clause
       
       PROCEDURE DIVISION.
       DISPLAY WS-DATA
       MOVE "INVALID" TO WS-AMOUNT.
       STOP RUN.
    '''
    
    # Parse with error collection
    result = parse_cobol(
        buggy_cobol, 
        "buggy.cob", 
        error_recovery=ErrorRecoveryMode.COLLECT_ALL
    )
    
    print(f"✅ Parse Completed: {result.success}")
    print(f"❌ Errors Found: {len(result.errors)}")
    print(f"⚠️  Warnings: {len(result.warnings)}")
    
    if result.errors:
        print("\n📋 Error Details:")
        for i, error in enumerate(result.errors[:3], 1):
            print(f"  {i}. Line {error.line}: {error.message}")
    
    # Show that partial AST is still available
    if result.ast:
        print(f"\n🏗️  Partial AST Available:")
        print(f"  Program: {result.ast.program_name}")
        print(f"  Divisions: {len(result.ast.divisions)}")


def example_5_file_parsing():
    """Parse COBOL from an external file."""
    print("\n" + "=" * 60)
    print("EXAMPLE 5: File-Based Parsing")
    print("=" * 60)
    
    # Create a sample COBOL file
    sample_program = '''       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILE-DEMO.
       AUTHOR. COBOL PARSER TEAM.
       DATE-WRITTEN. SEPTEMBER 2025.
       
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       
       DATA DIVISION.
       FILE SECTION.
       FD  INPUT-FILE
           RECORD CONTAINS 80 CHARACTERS.
       01  INPUT-RECORD         PIC X(80).
       
       WORKING-STORAGE SECTION.
       01  WS-EOF-FLAG          PIC X VALUE 'N'.
       01  WS-RECORD-COUNT      PIC 9(5) VALUE ZERO.
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           OPEN INPUT INPUT-FILE.
           PERFORM READ-PROCESS UNTIL WS-EOF-FLAG = 'Y'.
           CLOSE INPUT-FILE.
           DISPLAY "Records processed: " WS-RECORD-COUNT.
           STOP RUN.
           
       READ-PROCESS.
           READ INPUT-FILE INTO INPUT-RECORD
               AT END MOVE 'Y' TO WS-EOF-FLAG
           END-READ.
           
           IF WS-EOF-FLAG NOT = 'Y'
               ADD 1 TO WS-RECORD-COUNT
           END-IF.
    '''
    
    # Write to file
    filename = "sample_program.cob"
    with open(filename, 'w') as f:
        f.write(sample_program)
    
    try:
        # Parse from file
        with open(filename, 'r') as f:
            cobol_source = f.read()
        
        result = parse_cobol(cobol_source, filename)
        
        print(f"✅ Parse Success: {result.success}")
        print(f"📁 File: {filename}")
        print(f"📊 Program Structure:")
        
        if result.ast:
            for div_name, division in result.ast.divisions.items():
                section_count = len(division.sections)
                print(f"  📂 {division.division_name}: {section_count} sections")
                
                for sec_name, section in division.sections.items():
                    item_count = len(section.children)
                    print(f"    📄 {section.section_name}: {item_count} items")
        
        print(f"\n📈 Performance:")
        print(f"  ⏱️  Parse Time: {result.statistics.total_time_ms:.2f}ms")
        print(f"  📏 Lines: {result.statistics.lines_parsed}")
        print(f"  🔢 Tokens: {result.statistics.tokens_processed}")
        
    except FileNotFoundError:
        print(f"❌ File not found: {filename}")
    
    # Clean up
    import os
    if os.path.exists(filename):
        os.remove(filename)


def main():
    """Run all basic examples."""
    print("🎯 COBOL Parser - Basic Examples")
    print("Run individual examples to see detailed output\n")
    
    try:
        example_1_hello_world()
        example_2_data_definitions()
        example_3_arithmetic_statements()
        example_4_error_handling()
        example_5_file_parsing()
        
        print("\n" + "=" * 60)
        print("✅ All basic examples completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n❌ Example failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()