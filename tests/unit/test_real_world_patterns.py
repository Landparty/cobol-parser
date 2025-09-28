"""
Unit tests for real-world COBOL patterns found in example programs.

This test module covers patterns and constructs discovered in the examples/cobol
directory that were not adequately covered in existing unit tests.

Key patterns tested:
1. Complex PICTURE clause variations (signed, decimal, packed, redefinition)
2. REDEFINES constructs with multiple levels
3. OCCURS clauses with DEPENDING ON and complex indexing  
4. Numeric literal patterns and computational fields
5. File control and record structures
6. Level number variations (77, 01-49)
7. CALL statement patterns with USING clauses
8. Complex working storage structures
"""

import pytest
from typing import Dict, Any, List, Optional
from cobolparser import CobolParser, parse_cobol, ErrorRecoveryMode


class TestComplexPictureClauses:
    """Test parsing of complex PICTURE clause patterns found in examples."""
    
    def test_signed_decimal_picture_clauses(self):
        """Test signed decimal PICTURE patterns like S9(5)V9(5), S999V999."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-PICTURES.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        77  WRK-DS-18V00                PICTURE S9(18).
        77  A06THREES-DS-03V03          PICTURE S999V999 VALUE 333.333.
        77  WRK-DS-06V06                PICTURE S9(6)V9(6).
        77  A08TWOS-DS-02V06            PICTURE S99V9(6) VALUE 22.222222.
        77  A05ONES-DS-00V05            PICTURE SV9(5) VALUE .11111.
        77  A01ONE-DS-P0801             PICTURE SP(8)9 VALUE .000000001.
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        # Should parse successfully
        assert result.success, f"Parsing failed: {result.errors}"
        assert result.ast is not None
        
        # Get working storage section
        data_division = result.ast.get_division("DATA")
        assert data_division is not None
        
        ws_section = data_division.get_section_by_name("WORKING-STORAGE") 
        assert ws_section is not None
        
        # Verify specific picture clause patterns
        data_items = ws_section.data_items
        assert len(data_items) >= 6
        
        # Test S9(18) pattern
        wrk_ds_18v00 = next((item for item in data_items if item.name == "WRK-DS-18V00"), None)
        assert wrk_ds_18v00 is not None
        assert wrk_ds_18v00.picture_clause.pattern == "S9(18)"
        assert wrk_ds_18v00.picture_clause.is_signed == True
        assert wrk_ds_18v00.picture_clause.integer_digits == 18
        assert wrk_ds_18v00.picture_clause.decimal_digits == 0
        
        # Test S999V999 pattern with VALUE
        a06threes = next((item for item in data_items if item.name == "A06THREES-DS-03V03"), None)
        assert a06threes is not None
        assert a06threes.picture_clause.pattern == "S999V999"
        assert a06threes.picture_clause.is_signed == True
        assert a06threes.picture_clause.integer_digits == 3
        assert a06threes.picture_clause.decimal_digits == 3
        assert a06threes.initial_value == "333.333"
        
        # Test SV9(5) pattern (leading decimal)
        a05ones = next((item for item in data_items if item.name == "A05ONES-DS-00V05"), None)
        assert a05ones is not None
        assert a05ones.picture_clause.pattern == "SV9(5)"
        assert a05ones.picture_clause.is_signed == True
        assert a05ones.picture_clause.integer_digits == 0
        assert a05ones.picture_clause.decimal_digits == 5
        
        # Test SP(8)9 pattern (scaling factor)
        a01one_p = next((item for item in data_items if item.name == "A01ONE-DS-P0801"), None)
        assert a01one_p is not None
        assert a01one_p.picture_clause.pattern == "SP(8)9"
        assert a01one_p.picture_clause.is_signed == True
        assert a01one_p.picture_clause.has_scaling_factor == True
        assert a01one_p.picture_clause.scaling_factor == 8

    def test_computational_fields_and_usage(self):
        """Test COMPUTATIONAL usage and COMP variations."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-COMP.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        77  WRK-CS-18V00                PICTURE S9(18) COMPUTATIONAL.
        77  A99-CS-02V00                PICTURE S99 COMPUTATIONAL VALUE 99.
        77  A01ONE-CS-00V01             PICTURE SV9 COMPUTATIONAL VALUE .1.
        77  WRK-CS-02V02                PICTURE S99V99 COMPUTATIONAL.
        01  COMP3-FIELD                 PIC S9(7)V99 COMP-3.
        01  BINARY-FIELD                PIC S9(8) COMP.
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        assert result.success, f"Parsing failed: {result.errors}"
        
        # Get data items and verify COMPUTATIONAL usage
        data_division = result.ast.get_division("DATA")
        ws_section = data_division.get_section_by_name("WORKING-STORAGE")
        data_items = ws_section.data_items
        
        # Test COMPUTATIONAL usage
        wrk_cs_18v00 = next((item for item in data_items if item.name == "WRK-CS-18V00"), None)
        assert wrk_cs_18v00 is not None
        assert wrk_cs_18v00.usage == "COMPUTATIONAL"
        assert wrk_cs_18v00.picture_clause.pattern == "S9(18)"
        
        # Test COMP-3 (packed decimal)
        comp3_field = next((item for item in data_items if item.name == "COMP3-FIELD"), None)
        assert comp3_field is not None
        assert comp3_field.usage == "COMP-3"
        assert comp3_field.picture_clause.pattern == "S9(7)V99"
        
        # Test COMP (binary)
        binary_field = next((item for item in data_items if item.name == "BINARY-FIELD"), None)
        assert binary_field is not None
        assert binary_field.usage == "COMP"
        assert binary_field.picture_clause.pattern == "S9(8)"


class TestRedefinesAndComplexStructures:
    """Test REDEFINES clauses and complex data structures."""
    
    def test_multiple_redefines_patterns(self):
        """Test multiple REDEFINES on same data area."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-REDEFINES.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        77  WRK-DS-06V06                PICTURE S9(6)V9(6).
        77  WRK-DS-12V00-S REDEFINES WRK-DS-06V06 PICTURE S9(12).
        77  WRK-DS-09V09                PICTURE S9(9)V9(9).
        77  WRK-DS-18V00-S REDEFINES WRK-DS-09V09 PICTURE S9(18).
        01  WRK-XN-18-1 PIC X(18).
        01  WRK-AN-X-18-1 REDEFINES WRK-XN-18-1 PIC A(18).
        01  WRK-DU-X-18V0-1 REDEFINES WRK-XN-18-1 PIC 9(18).
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        assert result.success, f"Parsing failed: {result.errors}"
        
        data_division = result.ast.get_division_by_name("DATA")
        ws_section = data_division.get_section_by_name("WORKING-STORAGE")
        data_items = ws_section.data_items
        
        # Test first redefines pair
        wrk_ds_06v06 = next((item for item in data_items if item.name == "WRK-DS-06V06"), None)
        assert wrk_ds_06v06 is not None
        assert wrk_ds_06v06.picture_clause.pattern == "S9(6)V9(6)"
        
        wrk_ds_12v00_s = next((item for item in data_items if item.name == "WRK-DS-12V00-S"), None)
        assert wrk_ds_12v00_s is not None
        assert wrk_ds_12v00_s.redefines == "WRK-DS-06V06"
        assert wrk_ds_12v00_s.picture_clause.pattern == "S9(12)"
        
        # Test multiple redefines on same original field
        wrk_xn_18_1 = next((item for item in data_items if item.name == "WRK-XN-18-1"), None)
        assert wrk_xn_18_1 is not None
        assert wrk_xn_18_1.picture_clause.pattern == "X(18)"
        
        wrk_an_x_18_1 = next((item for item in data_items if item.name == "WRK-AN-X-18-1"), None)
        assert wrk_an_x_18_1 is not None
        assert wrk_an_x_18_1.redefines == "WRK-XN-18-1"
        assert wrk_an_x_18_1.picture_clause.pattern == "A(18)"
        
        wrk_du_x_18v0_1 = next((item for item in data_items if item.name == "WRK-DU-X-18V0-1"), None)
        assert wrk_du_x_18v0_1 is not None
        assert wrk_du_x_18v0_1.redefines == "WRK-XN-18-1"
        assert wrk_du_x_18v0_1.picture_clause.pattern == "9(18)"

    def test_complex_occurs_structures(self):
        """Test OCCURS clauses and array structures."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-OCCURS.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  ARR                         VALUE "40537".
            02  IND OCCURS 5 TIMES PIC 9.
        01  COMPLEX-ARRAY.
            05  MONTH-DATA OCCURS 12 TIMES.
                10  MONTH-NAME          PIC X(9).
                10  DAYS-IN-MONTH       PIC 99.
                10  MONTH-SALES OCCURS 4 TIMES PIC 9(7)V99.
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        assert result.success, f"Parsing failed: {result.errors}"
        
        data_division = result.ast.get_division_by_name("DATA")
        ws_section = data_division.get_section_by_name("WORKING-STORAGE")
        data_items = ws_section.data_items
        
        # Test simple OCCURS with VALUE
        arr = next((item for item in data_items if item.name == "ARR"), None)
        assert arr is not None
        assert arr.initial_value == '"40537"'
        
        # Find IND subordinate item
        ind_item = None
        for child in arr.children:
            if child.name == "IND":
                ind_item = child
                break
        assert ind_item is not None
        assert ind_item.occurs_clause is not None
        assert ind_item.occurs_clause.times == 5
        assert ind_item.picture_clause.pattern == "9"
        
        # Test nested OCCURS structure
        complex_array = next((item for item in data_items if item.name == "COMPLEX-ARRAY"), None)
        assert complex_array is not None
        
        # Find MONTH-DATA with OCCURS 12 TIMES
        month_data = None
        for child in complex_array.children:
            if child.name == "MONTH-DATA":
                month_data = child
                break
        assert month_data is not None
        assert month_data.occurs_clause is not None
        assert month_data.occurs_clause.times == 12
        
        # Verify nested OCCURS within MONTH-DATA
        month_sales = None
        for child in month_data.children:
            if child.name == "MONTH-SALES":
                month_sales = child
                break
        assert month_sales is not None
        assert month_sales.occurs_clause is not None
        assert month_sales.occurs_clause.times == 4
        assert month_sales.picture_clause.pattern == "9(7)V99"


class TestCallStatements:
    """Test CALL statement patterns found in examples."""
    
    def test_call_with_using_clause(self):
        """Test CALL statements with USING data-names."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-CALL.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        77  DN1 PICTURE S9  VALUE ZERO.
        77  DN2 PICTURE S9  VALUE ZERO.
        
        PROCEDURE DIVISION.
        CALL-TEST-1.
            CALL "IC102A" USING DN1.
            IF DN1 IS EQUAL TO 1
                PERFORM PASS-ROUTINE.
        
        CALL-TEST-2.
            CALL "IC102A" USING DN2.
        
        PASS-ROUTINE.
            DISPLAY "PASS".
            
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        assert result.success, f"Parsing failed: {result.errors}"
        
        # Get procedure division
        proc_division = result.ast.get_division_by_name("PROCEDURE")
        assert proc_division is not None
        
        # Verify CALL statements are parsed
        call_statements = []
        for section in proc_division.sections.values():
            for child in section.children:
                if hasattr(child, 'statement_type') and child.statement_type == "CALL":
                    call_statements.append(child)
        
        assert len(call_statements) >= 2
        
        # Test first CALL statement
        call_1 = call_statements[0]
        assert call_1.called_program == '"IC102A"'
        assert "DN1" in call_1.using_parameters
        
        # Test second CALL statement  
        call_2 = call_statements[1]
        assert call_2.called_program == '"IC102A"'
        assert "DN2" in call_2.using_parameters


class TestComplexFileStructures:
    """Test file control and record structure patterns."""
    
    def test_file_control_and_fd_structures(self):
        """Test file control SELECT and FD definitions."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-FILES.
        
        ENVIRONMENT DIVISION.
        CONFIGURATION SECTION.
        SOURCE-COMPUTER. IBM-3090.
        OBJECT-COMPUTER. IBM-3090.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT PRINT-FILE ASSIGN TO PRINTER.
            SELECT INPUT-FILE ASSIGN TO "INFILE.DAT"
                   ORGANIZATION IS SEQUENTIAL
                   ACCESS MODE IS SEQUENTIAL.
        
        DATA DIVISION.
        FILE SECTION.
        FD  PRINT-FILE.
        01  PRINT-REC PICTURE X(120).
        01  DUMMY-RECORD PICTURE X(120).
        
        FD  INPUT-FILE.
        01  INPUT-REC.
            05  RECORD-KEY          PIC 9(8).
            05  RECORD-DATA         PIC X(72).
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        assert result.success, f"Parsing failed: {result.errors}"
        
        # Verify ENVIRONMENT DIVISION structure
        env_division = result.ast.get_division_by_name("ENVIRONMENT")
        assert env_division is not None
        
        # Check CONFIGURATION SECTION
        config_section = env_division.get_section_by_name("CONFIGURATION")
        assert config_section is not None
        
        # Check INPUT-OUTPUT SECTION  
        io_section = env_division.get_section_by_name("INPUT-OUTPUT")
        assert io_section is not None
        
        # Verify FILE-CONTROL paragraph contains SELECT statements
        file_control = io_section.get_paragraph_by_name("FILE-CONTROL")
        assert file_control is not None
        
        select_statements = [stmt for stmt in file_control.statements if stmt.statement_type == "SELECT"]
        assert len(select_statements) >= 2
        
        # Test PRINT-FILE SELECT
        print_select = next((stmt for stmt in select_statements if stmt.file_name == "PRINT-FILE"), None)
        assert print_select is not None
        assert print_select.assign_to == "PRINTER"
        
        # Test INPUT-FILE SELECT with organization
        input_select = next((stmt for stmt in select_statements if stmt.file_name == "INPUT-FILE"), None)
        assert input_select is not None
        assert input_select.assign_to == '"INFILE.DAT"'
        assert input_select.organization == "SEQUENTIAL"
        assert input_select.access_mode == "SEQUENTIAL"
        
        # Verify FILE SECTION with FD records
        data_division = result.ast.get_division_by_name("DATA")
        file_section = data_division.get_section_by_name("FILE")
        assert file_section is not None
        
        fd_records = [item for item in file_section.children if hasattr(item, 'record_type') and item.record_type == "FD"]
        assert len(fd_records) >= 2


class TestLevelNumberVariations:
    """Test various level number patterns (77, 01-49)."""
    
    def test_level_77_independent_items(self):
        """Test level 77 independent data items."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-LEVEL77.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        77  WRK-DS-18V00                PICTURE S9(18).
        77  WRK-XN-00001                PICTURE X.
        77  WRK-DS-02V00                PICTURE S99.
        77  AZERO-DS-05V05              PICTURE S9(5)V9(5) VALUE ZERO.
        77  XRAY                        PICTURE X.
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        assert result.success, f"Parsing failed: {result.errors}"
        
        data_division = result.ast.get_division_by_name("DATA")
        ws_section = data_division.get_section_by_name("WORKING-STORAGE")
        data_items = ws_section.data_items
        
        # Verify all items are level 77
        level_77_items = [item for item in data_items if item.level == 77]
        assert len(level_77_items) >= 5
        
        # Test specific level 77 items
        wrk_ds_18v00 = next((item for item in level_77_items if item.name == "WRK-DS-18V00"), None)
        assert wrk_ds_18v00 is not None
        assert wrk_ds_18v00.level == 77
        assert wrk_ds_18v00.picture_clause.pattern == "S9(18)"
        
        azero = next((item for item in level_77_items if item.name == "AZERO-DS-05V05"), None)
        assert azero is not None
        assert azero.level == 77
        assert azero.initial_value == "ZERO"

    def test_hierarchical_level_structures(self):
        """Test hierarchical structures with various level numbers."""
        cobol_source = '''
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-LEVELS.
        
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  TEST-RESULTS.
            02 FILLER                   PIC X      VALUE SPACE.
            02 FEATURE                  PIC X(20)  VALUE SPACE.
            02 FILLER                   PIC X      VALUE SPACE.
            02 P-OR-F                   PIC X(5)   VALUE SPACE.
            02 FILLER                   PIC X      VALUE SPACE.
            02  PAR-NAME.
              03 FILLER                 PIC X(19)  VALUE SPACE.
              03  PARDOT-X              PIC X      VALUE SPACE.
              03 DOTVALUE               PIC 99     VALUE ZERO.
            02 FILLER                   PIC X(8)   VALUE SPACE.
            02 RE-MARK                  PIC X(61).
        
        01  COMPUTED-RESULTS.
            05 COMPUTED-A               PIC X(20)  VALUE SPACE.
            05 COMPUTED-N               REDEFINES COMPUTED-A PIC -9(9).9(9).
            05 COMPUTED-0V18 REDEFINES COMPUTED-A   PIC -.9(18).
            05       CM-18V0 REDEFINES COMPUTED-A.
                10 COMPUTED-18V0        PIC -9(18).
                10 FILLER               PIC X.
        
        PROCEDURE DIVISION.
        STOP RUN.
        '''
        
        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        assert result.success, f"Parsing failed: {result.errors}"
        
        data_division = result.ast.get_division_by_name("DATA")
        ws_section = data_division.get_section_by_name("WORKING-STORAGE")
        data_items = ws_section.data_items
        
        # Test TEST-RESULTS structure (01, 02, 03 levels)
        test_results = next((item for item in data_items if item.name == "TEST-RESULTS"), None)
        assert test_results is not None
        assert test_results.level == 1
        assert len(test_results.children) >= 6  # Multiple 02 level items
        
        # Test PAR-NAME subordinate structure
        par_name = None
        for child in test_results.children:
            if child.name == "PAR-NAME":
                par_name = child
                break
        assert par_name is not None
        assert par_name.level == 2
        assert len(par_name.children) >= 3  # Three 03 level items
        
        # Test COMPUTED-RESULTS with REDEFINES and 05/10 levels
        computed_results = next((item for item in data_items if item.name == "COMPUTED-RESULTS"), None)
        assert computed_results is not None
        assert computed_results.level == 1
        
        # Verify REDEFINES at level 05
        computed_redefines = [child for child in computed_results.children if child.redefines is not None]
        assert len(computed_redefines) >= 2
        
        # Test CM-18V0 group with level 10 subordinates
        cm_18v0 = None
        for child in computed_results.children:
            if child.name == "CM-18V0":
                cm_18v0 = child
                break
        assert cm_18v0 is not None
        assert cm_18v0.level == 5
        assert cm_18v0.redefines == "COMPUTED-A"
        assert len(cm_18v0.children) >= 2  # Level 10 items