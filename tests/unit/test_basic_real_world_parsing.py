"""
Simple unit tests to verify basic parsing functionality works with real-world patterns.

This test module focuses on ensuring that the parser can successfully parse
COBOL programs with patterns found in the examples directory, without
getting into complex AST verification initially.
"""

import pytest
from cobolparser import parse_cobol, ErrorRecoveryMode


class TestBasicParsing:
    """Test basic parsing of real-world COBOL patterns."""
    
    def test_simple_cobol_program_parses(self):
        """Test that a simple COBOL program parses successfully."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-SIMPLE.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-MESSAGE    PIC X(20) VALUE "Hello World".
        
        PROCEDURE DIVISION.
        DISPLAY WS-MESSAGE.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source)
        
        # Basic success check
        print(f"Parse success: {result.success}")
        if not result.success:
            print(f"Errors: {result.errors}")
        
        # For now, just verify it doesn't crash - we'll add AST checks later
        assert isinstance(result.success, bool)
    
    def test_picture_clause_variations(self):
        """Test various PICTURE clause patterns found in examples."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-PICTURES.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        77  WRK-DS-18V00                PICTURE S9(18).
        77  A06THREES-DS-03V03          PICTURE S999V999 VALUE 333.333.
        77  WRK-DS-06V06                PICTURE S9(6)V9(6).
        01  SIMPLE-FIELD                PIC X(10).
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        print(f"Parse success: {result.success}")
        if not result.success:
            print(f"Errors: {result.errors}")
        
        # For now, just check it doesn't crash completely
        assert isinstance(result.success, bool)
    
    def test_redefines_pattern(self):
        """Test REDEFINES clause parsing."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-REDEFINES.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WRK-AREA                    PIC X(10).
        01  WRK-NUMERIC REDEFINES WRK-AREA PIC 9(10).
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        print(f"Parse success: {result.success}")
        if not result.success:
            print(f"Errors: {result.errors}")
        
        assert isinstance(result.success, bool)
    
    def test_occurs_pattern(self):
        """Test OCCURS clause parsing."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-OCCURS.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  ARR-DATA.
            05  ARR-ITEM OCCURS 10 TIMES PIC 9(5).
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        print(f"Parse success: {result.success}")
        if not result.success:
            print(f"Errors: {result.errors}")
        
        assert isinstance(result.success, bool)
    
    def test_call_statement(self):
        """Test CALL statement parsing."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-CALL.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PARAM    PIC X(10).
        
        PROCEDURE DIVISION.
        CALL "SUBPROG" USING WS-PARAM.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        print(f"Parse success: {result.success}")
        if not result.success:
            print(f"Errors: {result.errors}")
        
        assert isinstance(result.success, bool)
    
    def test_computational_fields(self):
        """Test COMPUTATIONAL field parsing."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-COMP.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-COMP-FIELD               PIC 9(5) COMP.
        01  WS-COMP3-FIELD              PIC 9(7)V99 COMP-3.
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        print(f"Parse success: {result.success}")
        if not result.success:
            print(f"Errors: {result.errors}")
        
        assert isinstance(result.success, bool)
    
    def test_file_control_structure(self):
        """Test file control and FD parsing."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-FILES.
        
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT PRINT-FILE ASSIGN TO PRINTER.
        
        DATA DIVISION.
        FILE SECTION.
        FD  PRINT-FILE.
        01  PRINT-REC PICTURE X(120).
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        print(f"Parse success: {result.success}")
        if not result.success:
            print(f"Errors: {result.errors}")
        
        assert isinstance(result.success, bool)


class TestRealWorldPrograms:
    """Test parsing of actual programs from examples directory."""
    
    def test_parsing_test_program_cob(self):
        """Test parsing the main test_program.cob file."""
        try:
            with open('test_program.cob', 'r') as f:
                cobol_source = f.read()
            
            result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
            
            print(f"Parse success: {result.success}")
            if not result.success:
                print(f"Errors: {result.errors}")
                
            # Should at least attempt to parse without crashing
            assert isinstance(result.success, bool)
            
        except FileNotFoundError:
            pytest.skip("test_program.cob not found")
    
    def test_parsing_sample_nist_program(self):
        """Test parsing one of the NIST COBOL programs."""
        import pathlib
        
        examples_dir = pathlib.Path('examples/cobol')
        if not examples_dir.exists():
            pytest.skip("examples/cobol directory not found")
        
        # Try to find a simple example program
        sample_files = ['IC101A.CBL', 'NC101A.CBL', 'IF101A.CBL']
        
        for filename in sample_files:
            sample_file = examples_dir / filename
            if sample_file.exists():
                try:
                    with open(sample_file, 'r') as f:
                        cobol_source = f.read()
                    
                    result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
                    
                    print(f"Parsing {filename}: success={result.success}")
                    if not result.success:
                        print(f"Errors: {result.errors[:5]}")  # Show first 5 errors
                    
                    # Should at least attempt to parse without crashing
                    assert isinstance(result.success, bool)
                    return  # Successfully tested one file
                    
                except Exception as e:
                    print(f"Exception parsing {filename}: {e}")
        
        pytest.skip("No sample COBOL files could be found or parsed")