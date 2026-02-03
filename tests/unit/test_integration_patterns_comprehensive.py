"""Integration test suite for cross-division and cross-statement patterns.

This module tests realistic COBOL programs with:
- Multiple statements interacting (CALL inside PERFORM inside IF)
- Cross-division references (DATA division items in PROCEDURE division)
- Complex control flow patterns
- Real-world COBOL idioms
- Large program fragments
- Copybook patterns (when applicable)
"""

import pytest
from cobolparser import parse_cobol


class TestCrossStatementPatterns:
    """Test patterns where statements contain other statements."""
    
    def test_call_inside_perform_inside_if(self):
        """Test CALL statement nested in PERFORM inside IF."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. COMPLEX-FLOW.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-COUNTER PIC 9(3) VALUE 0.
        01 WS-STATUS PIC X VALUE "Y".
        PROCEDURE DIVISION.
            IF WS-STATUS = "Y"
                PERFORM 5 TIMES
                    CALL "SUBPROGRAM"
                    ADD 1 TO WS-COUNTER
                END-PERFORM
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        # Verify all statement types are present
        ifs = result.ast.find_statements("IF")
        assert len(ifs) >= 1
        
        performs = result.ast.find_statements("PERFORM")
        assert len(performs) >= 1
        
        calls = result.ast.find_statements("CALL")
        assert len(calls) >= 1
    
    def test_evaluate_with_move_and_call(self):
        """Test EVALUATE with MOVE and CALL in WHEN clauses."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. EVAL-TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-MODE PIC 9 VALUE 1.
        01 WS-RESULT PIC X(20).
        PROCEDURE DIVISION.
            EVALUATE WS-MODE
                WHEN 1
                    MOVE "MODE-ONE" TO WS-RESULT
                    CALL "HANDLER-ONE" USING WS-RESULT
                WHEN 2
                    MOVE "MODE-TWO" TO WS-RESULT
                    CALL "HANDLER-TWO" USING WS-RESULT
                WHEN OTHER
                    MOVE "UNKNOWN" TO WS-RESULT
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        evaluates = result.ast.find_statements("EVALUATE")
        assert len(evaluates) >= 1
    
    def test_perform_varying_with_nested_if_and_call(self):
        """Test PERFORM VARYING with nested IF and CALL."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. VARYING-TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-IDX PIC 9(3) VALUE 1.
        01 WS-FLAG PIC X VALUE "Y".
        PROCEDURE DIVISION.
            PERFORM VARYING WS-IDX FROM 1 BY 1
                UNTIL WS-IDX > 10
                IF WS-FLAG = "Y"
                    CALL "PROCESS" USING WS-IDX
                    MOVE "N" TO WS-FLAG
                ELSE
                    DISPLAY WS-IDX
                END-IF
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_nested_if_with_perform_and_evaluate(self):
        """Test nested IF containing both PERFORM and EVALUATE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. NESTED-IF-TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-A PIC 9 VALUE 1.
        01 WS-B PIC 9 VALUE 2.
        PROCEDURE DIVISION.
            IF WS-A = 1
                IF WS-B = 2
                    PERFORM 3 TIMES
                        EVALUATE WS-A
                            WHEN 1
                                DISPLAY "A"
                        END-EVALUATE
                    END-PERFORM
                END-IF
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_multiple_statements_in_perform_until(self):
        """Test PERFORM UNTIL with multiple statement types."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. MULTI-STMT.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-COUNTER PIC 9(3) VALUE 0.
        01 WS-TOTAL PIC 9(5) VALUE 0.
        PROCEDURE DIVISION.
            PERFORM UNTIL WS-COUNTER >= 100
                MOVE 0 TO WS-TOTAL
                EVALUATE WS-COUNTER
                    WHEN 1
                        MOVE 10 TO WS-TOTAL
                    WHEN 50
                        MOVE 500 TO WS-TOTAL
                END-EVALUATE
                IF WS-COUNTER > 50
                    CALL "LARGE-COUNT" USING WS-COUNTER
                END-IF
                ADD 1 TO WS-COUNTER
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestCrossDivisionPatterns:
    """Test patterns spanning multiple divisions."""
    
    def test_data_division_with_redefines_used_in_procedure(self):
        """Test REDEFINES in DATA division used in PROCEDURE division."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REDEFINE-TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-ALPHA PIC X(10).
        01 WS-NUMERIC REDEFINES WS-ALPHA PIC 9(10).
        PROCEDURE DIVISION.
            MOVE "1234567890" TO WS-ALPHA.
            IF WS-NUMERIC > 1000000000
                DISPLAY "LARGE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_file_definitions_with_read_write(self):
        """Test FILE SECTION definitions with READ/WRITE in PROCEDURE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. FILE-TEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT DATA-FILE ASSIGN TO "DATA.TXT"
                ORGANIZATION IS LINE SEQUENTIAL.
        DATA DIVISION.
        FILE SECTION.
        FD DATA-FILE.
        01 DATA-RECORD PIC X(80).
        WORKING-STORAGE SECTION.
        01 WS-EOF PIC X VALUE "N".
        PROCEDURE DIVISION.
            OPEN INPUT DATA-FILE.
            PERFORM UNTIL WS-EOF = "Y"
                READ DATA-FILE
                    AT END MOVE "Y" TO WS-EOF
                    NOT AT END
                        DISPLAY DATA-RECORD
                END-READ
            END-PERFORM.
            CLOSE DATA-FILE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_working_storage_with_complex_usage(self):
        """Test WORKING-STORAGE items with COMP/COMP-3 used in statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. USAGE-TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-GROUP.
            05 WS-COUNTER PIC 9(5) COMP.
            05 WS-AMOUNT PIC S9(7)V99 COMP-3.
            05 WS-FLAG PIC X.
        PROCEDURE DIVISION.
            MOVE 1000 TO WS-COUNTER.
            MOVE 12345.67 TO WS-AMOUNT.
            MOVE "Y" TO WS-FLAG.
            IF WS-FLAG = "Y"
                PERFORM CALCULATE-TOTAL
            END-IF.
            CALCULATE-TOTAL.
                EVALUATE WS-COUNTER
                    WHEN 1000
                        DISPLAY "MATCH"
                END-EVALUATE.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_local_storage_used_in_nested_scope(self):
        """Test LOCAL-STORAGE SECTION with nested control structures."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. LOCAL-STORAGE-TEST.
        DATA DIVISION.
        LOCAL-STORAGE SECTION.
        01 LS-TEMP PIC 9(3).
        WORKING-STORAGE SECTION.
        01 WS-COUNTER PIC 9(3).
        PROCEDURE DIVISION.
            PERFORM 5 TIMES
                IF WS-COUNTER < 10
                    MOVE WS-COUNTER TO LS-TEMP
                    EVALUATE LS-TEMP
                        WHEN 1
                            CALL "HANDLER-ONE"
                    END-EVALUATE
                END-IF
                ADD 1 TO WS-COUNTER
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestRealWorldPatterns:
    """Test realistic COBOL program patterns."""
    
    def test_data_validation_pattern(self):
        """Test realistic data validation pattern."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. DATA-VALIDATOR.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-INPUT-DATA.
            05 WS-CUSTOMER-ID PIC 9(5).
            05 WS-AMOUNT PIC 9(7)V99.
            05 WS-STATUS PIC X.
        01 WS-VALIDATION-RESULT PIC X VALUE "N".
        PROCEDURE DIVISION.
            PERFORM VALIDATE-CUSTOMER.
            IF WS-VALIDATION-RESULT = "Y"
                PERFORM PROCESS-TRANSACTION
            ELSE
                DISPLAY "VALIDATION FAILED"
                STOP RUN
            END-IF.
            STOP RUN.
            
            VALIDATE-CUSTOMER.
                IF WS-CUSTOMER-ID = 0
                    MOVE "N" TO WS-VALIDATION-RESULT
                    EXIT PARAGRAPH
                END-IF.
                IF WS-AMOUNT <= 0
                    MOVE "N" TO WS-VALIDATION-RESULT
                    EXIT PARAGRAPH
                END-IF.
                MOVE "Y" TO WS-VALIDATION-RESULT.
            
            PROCESS-TRANSACTION.
                MOVE "PROCESSING" TO WS-STATUS.
                CALL "POST-TRANSACTION" USING WS-INPUT-DATA.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_table_processing_pattern(self):
        """Test realistic table/array processing pattern."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TABLE-PROCESSOR.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-DATA-TABLE.
            05 WS-DATA-ITEM OCCURS 100 TIMES.
                10 WS-ID PIC 9(5).
                10 WS-VALUE PIC 9(7).
                10 WS-PROCESSED PIC X VALUE "N".
        01 WS-INDEX PIC 9(3).
        PROCEDURE DIVISION.
            PERFORM VARYING WS-INDEX FROM 1 BY 1
                UNTIL WS-INDEX > 100
                IF WS-PROCESSED(WS-INDEX) = "N"
                    PERFORM PROCESS-ITEM
                END-IF
            END-PERFORM.
            STOP RUN.
            
            PROCESS-ITEM.
                MOVE "Y" TO WS-PROCESSED(WS-INDEX).
                CALL "ITEM-HANDLER"
                    USING WS-ID(WS-INDEX)
                          WS-VALUE(WS-INDEX).
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_error_handling_with_call_and_evaluate(self):
        """Test error handling with CALLs and EVALUATE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. ERROR-HANDLER.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-RETURN-CODE PIC 9(4).
        01 WS-ACTION PIC X.
        PROCEDURE DIVISION.
            CALL "RISKY-OPERATION" RETURNING WS-RETURN-CODE.
            EVALUATE WS-RETURN-CODE
                WHEN 0
                    MOVE "S" TO WS-ACTION
                    CALL "SUCCESS-HANDLER"
                WHEN 1
                    MOVE "E" TO WS-ACTION
                    CALL "ERROR-HANDLER-ONE"
                WHEN 2
                    MOVE "W" TO WS-ACTION
                    CALL "WARNING-HANDLER"
                WHEN OTHER
                    MOVE "U" TO WS-ACTION
                    CALL "UNKNOWN-HANDLER"
            END-EVALUATE.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestComplexNesting:
    """Test deeply nested control structures."""
    
    def test_triple_nested_if_statements(self):
        """Test deeply nested IF statements."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. DEEP-IF.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-A PIC 9 VALUE 1.
        01 WS-B PIC 9 VALUE 1.
        01 WS-C PIC 9 VALUE 1.
        PROCEDURE DIVISION.
            IF WS-A = 1
                IF WS-B = 1
                    IF WS-C = 1
                        DISPLAY "ALL ONE"
                    ELSE
                        DISPLAY "C NOT ONE"
                    END-IF
                ELSE
                    DISPLAY "B NOT ONE"
                END-IF
            ELSE
                DISPLAY "A NOT ONE"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        ifs = result.ast.find_statements("IF")
        assert len(ifs) >= 3
    
    def test_perform_with_nested_if_and_evaluate(self):
        """Test PERFORM containing nested IF and EVALUATE."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. PERFORM-NESTED.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-IDX PIC 9(3).
        01 WS-VAL PIC 9(2).
        PROCEDURE DIVISION.
            PERFORM VARYING WS-IDX FROM 1 BY 1
                UNTIL WS-IDX > 10
                IF WS-IDX > 5
                    EVALUATE WS-IDX
                        WHEN 6
                            MOVE 60 TO WS-VAL
                        WHEN 10
                            IF WS-VAL > 50
                                DISPLAY "HIGH"
                            END-IF
                    END-EVALUATE
                END-IF
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


class TestMixedStatementSequences:
    """Test sequences of different statement types."""
    
    def test_mixed_statement_sequence(self):
        """Test realistic mix of MOVE, IF, EVALUATE, PERFORM, CALL."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. MIXED-STATEMENTS.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-MODE PIC 9 VALUE 1.
        01 WS-COUNTER PIC 9(3) VALUE 0.
        01 WS-TOTAL PIC 9(5) VALUE 0.
        PROCEDURE DIVISION.
            MOVE 5 TO WS-COUNTER.
            
            IF WS-MODE = 1
                EVALUATE WS-COUNTER
                    WHEN 5
                        MOVE 100 TO WS-TOTAL
                        PERFORM 2 TIMES
                            CALL "HANDLER"
                        END-PERFORM
                    WHEN OTHER
                        MOVE 0 TO WS-TOTAL
                END-EVALUATE
            ELSE
                DISPLAY "MODE NOT SET"
            END-IF.
            
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_paragraph_with_multiple_statement_types(self):
        """Test paragraph containing various statement types."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. PARAGRAPH-TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC 9(3) VALUE 10.
        PROCEDURE DIVISION.
            PERFORM MAIN-PARAGRAPH.
            STOP RUN.
            
            MAIN-PARAGRAPH.
                MOVE 5 TO WS-X.
                IF WS-X > 0
                    EVALUATE WS-X
                        WHEN 5
                            DISPLAY "FIVE"
                    END-EVALUATE
                    PERFORM 3 TIMES
                        CALL "PROCESS"
                    END-PERFORM
                END-IF.
        """
        result = parse_cobol(source)
        assert result.success


class TestSerializationAcrossDivisions:
    """Test serialization of complex multi-division programs."""
    
    def test_complete_program_to_dict(self):
        """Test complete program serialization to dict."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. COMPLETE.
        AUTHOR. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-FIELD PIC X(10).
        PROCEDURE DIVISION.
            MOVE "TEST" TO WS-FIELD.
            IF WS-FIELD = "TEST"
                DISPLAY WS-FIELD
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        if hasattr(result.ast, 'to_dict'):
            ast_dict = result.ast.to_dict()
            assert isinstance(ast_dict, dict)
    
    def test_get_all_statements_across_complex_program(self):
        """Test get_all_statements on complex multi-statement program."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. COMPLEX.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC 9.
        PROCEDURE DIVISION.
            MOVE 1 TO WS-X.
            IF WS-X = 1
                PERFORM 2 TIMES
                    EVALUATE WS-X
                        WHEN 1
                            CALL "A"
                    END-EVALUATE
                END-PERFORM
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
        
        if hasattr(result.ast, 'get_all_statements'):
            stmts = result.ast.get_all_statements()
            # Should have multiple statement types
            assert len(stmts) >= 4


class TestLargeFragments:
    """Test parsing of larger program fragments."""
    
    def test_large_procedure_with_many_paragraphs(self):
        """Test large procedure division with multiple paragraphs."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. LARGE-PROGRAM.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-COUNTER PIC 9(5).
        PROCEDURE DIVISION.
            PERFORM PARA-ONE.
            PERFORM PARA-TWO.
            PERFORM PARA-THREE.
            STOP RUN.
            
            PARA-ONE.
                MOVE 1 TO WS-COUNTER.
                DISPLAY "PARA-ONE".
            
            PARA-TWO.
                PERFORM VARYING WS-COUNTER FROM 1 BY 1
                    UNTIL WS-COUNTER > 5
                    IF WS-COUNTER = 3
                        CALL "HANDLER"
                    END-IF
                END-PERFORM.
            
            PARA-THREE.
                EVALUATE WS-COUNTER
                    WHEN 5
                        DISPLAY "DONE"
                END-EVALUATE.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_large_data_division_with_complex_structures(self):
        """Test large DATA division with complex nested structures."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. LARGE-DATA.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-MAIN-GROUP.
            05 WS-HEADER.
                10 WS-VERSION PIC 9(2) VALUE 01.
                10 WS-DATE PIC 9(8).
            05 WS-BODY.
                10 WS-TYPE PIC X(10).
                10 WS-ITEMS.
                    15 WS-ITEM OCCURS 25 TIMES.
                        20 WS-ID PIC 9(5).
                        20 WS-VALUE PIC 9(7)V99.
                        20 WS-FLAG PIC X.
            05 WS-FOOTER.
                10 WS-CHECKSUM PIC 9(8).
                10 WS-STATUS PIC X.
        PROCEDURE DIVISION.
            MOVE "ACTIVE" TO WS-STATUS.
            PERFORM CHECK-STRUCTURE.
            STOP RUN.
            
            CHECK-STRUCTURE.
                IF WS-VERSION = 1
                    DISPLAY "VERSION OK"
                END-IF.
        """
        result = parse_cobol(source)
        assert result.success


class TestIntegrationEdgeCases:
    """Test edge cases in integration scenarios."""
    
    def test_multiple_calls_in_sequence(self):
        """Test multiple CALL statements in sequence."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. MULTI-CALL.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-RESULT1 PIC 9(5).
        01 WS-RESULT2 PIC 9(5).
        PROCEDURE DIVISION.
            CALL "PROC-ONE" RETURNING WS-RESULT1.
            CALL "PROC-TWO" USING WS-RESULT1
                RETURNING WS-RESULT2.
            IF WS-RESULT2 > 100
                CALL "SUCCESS-HANDLER"
            END-IF.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success
    
    def test_perform_with_call_returning(self):
        """Test PERFORM containing CALL with RETURNING."""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. PERFORM-CALL-RET.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-IDX PIC 9(3).
        01 WS-RESULT PIC X.
        PROCEDURE DIVISION.
            PERFORM VARYING WS-IDX FROM 1 BY 1
                UNTIL WS-IDX > 10
                CALL "CHECK-ITEM"
                    USING WS-IDX
                    RETURNING WS-RESULT
                IF WS-RESULT = "Y"
                    DISPLAY "FOUND"
                END-IF
            END-PERFORM.
            STOP RUN.
        """
        result = parse_cobol(source)
        assert result.success


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
