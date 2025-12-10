"""
Unit tests for specific COBOL language features found in sample programs.
Tests lexer tokenization and parser AST node creation.
"""
import pytest
from pathlib import Path
from cobolparser.lexer import CobolLexer, TokenType
from cobolparser import CobolParser


SAMPLES_DIR = Path(__file__).parent.parent / "samples"


class TestFigurativeConstants:
    """Test tokenization and parsing of figurative constants."""
    
    def test_all_figurative_constant_tokenization(self):
        """Test that ALL is tokenized as FIGURATIVE_CONSTANT."""
        lexer = CobolLexer()
        source = "MOVE ALL 'X' TO WS-FIELD."
        
        tokens = list(lexer.tokenize(source))
        
        # Find ALL token
        all_token = next((t for t in tokens if t.value == 'ALL'), None)
        assert all_token is not None
        assert all_token.type == TokenType.FIGURATIVE_CONSTANT
        
    def test_zero_figurative_constant(self):
        """Test ZERO/ZEROS/ZEROES tokenization."""
        lexer = CobolLexer()
        
        for variant in ['ZERO', 'ZEROS', 'ZEROES']:
            source = f"MOVE {variant} TO WS-FIELD."
            tokens = list(lexer.tokenize(source))
            
            token = next((t for t in tokens if t.value == variant), None)
            assert token is not None
            assert token.type == TokenType.FIGURATIVE_CONSTANT
            
    def test_space_figurative_constant(self):
        """Test SPACE/SPACES tokenization."""
        lexer = CobolLexer()
        
        for variant in ['SPACE', 'SPACES']:
            source = f"MOVE {variant} TO WS-FIELD."
            tokens = list(lexer.tokenize(source))
            
            token = next((t for t in tokens if t.value == variant), None)
            assert token is not None
            assert token.type == TokenType.FIGURATIVE_CONSTANT
            
    def test_quote_figurative_constant(self):
        """Test QUOTE/QUOTES tokenization."""
        lexer = CobolLexer()
        
        for variant in ['QUOTE', 'QUOTES']:
            source = f"MOVE {variant} TO WS-FIELD."
            tokens = list(lexer.tokenize(source))
            
            token = next((t for t in tokens if t.value == variant), None)
            assert token is not None
            assert token.type == TokenType.FIGURATIVE_CONSTANT
            
    def test_high_low_value_constants(self):
        """Test HIGH-VALUE and LOW-VALUE tokenization."""
        lexer = CobolLexer()
        
        for variant in ['HIGH-VALUE', 'HIGH-VALUES', 'LOW-VALUE', 'LOW-VALUES']:
            source = f"MOVE {variant} TO WS-FIELD."
            tokens = list(lexer.tokenize(source))
            
            token = next((t for t in tokens if t.value == variant), None)
            assert token is not None
            assert token.type == TokenType.FIGURATIVE_CONSTANT


class TestPictureClausesParsing:
    """Test parsing of various PICTURE clause formats."""
    
    def test_simple_numeric_picture(self):
        """Test simple numeric PICTURE clause parsing."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-NUM  PIC 9(5).
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_signed_picture(self):
        """Test signed PICTURE clause parsing."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-SIGNED  PIC S9(5).
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_decimal_picture(self):
        """Test decimal PICTURE clause parsing."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-DECIMAL  PIC 9(5)V99.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_edited_picture(self):
        """Test edited PICTURE clause parsing."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-EDITED  PIC $$$,$$9.99.
        """
        
        result = parser.parse(source)
        assert result.ast is not None


class TestOccursClause:
    """Test OCCURS clause parsing."""
    
    def test_fixed_occurs(self):
        """Test fixed OCCURS clause."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-ARRAY.
            05  WS-ITEM OCCURS 10 TIMES PIC X(5).
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_occurs_depending_on(self):
        """Test OCCURS DEPENDING ON clause."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-COUNT PIC 9(3).
        01  WS-ARRAY.
            05  WS-ITEM OCCURS 1 TO 100 TIMES
                DEPENDING ON WS-COUNT PIC X(5).
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_occurs_indexed_by(self):
        """Test OCCURS INDEXED BY clause."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-ARRAY.
            05  WS-ITEM OCCURS 10 TIMES
                INDEXED BY WS-IDX PIC X(5).
        """
        
        result = parser.parse(source)
        assert result.ast is not None


class TestRedefinesClause:
    """Test REDEFINES clause parsing."""
    
    def test_simple_redefines(self):
        """Test simple REDEFINES clause."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-FIELD-A  PIC X(10).
        01  WS-FIELD-B  REDEFINES WS-FIELD-A PIC 9(10).
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_nested_redefines(self):
        """Test nested REDEFINES structures."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-DATE-AREA.
            05  WS-DATE-NUMERIC PIC 9(8).
            05  WS-DATE-ALPHA REDEFINES WS-DATE-NUMERIC.
                10  WS-YEAR  PIC X(4).
                10  WS-MONTH PIC X(2).
                10  WS-DAY   PIC X(2).
        """
        
        result = parser.parse(source)
        assert result.ast is not None


class TestFileControlParsing:
    """Test FILE-CONTROL section parsing."""
    
    def test_sequential_file_select(self):
        """Test sequential file SELECT statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INPUT-FILE ASSIGN TO 'INPUT.DAT'
                ORGANIZATION IS SEQUENTIAL.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_indexed_file_select(self):
        """Test indexed file SELECT statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INDEXED-FILE ASSIGN TO 'INDEX.DAT'
                ORGANIZATION IS INDEXED
                ACCESS MODE IS DYNAMIC
                RECORD KEY IS REC-KEY.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_relative_file_select(self):
        """Test relative file SELECT statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT RELATIVE-FILE ASSIGN TO 'REL.DAT'
                ORGANIZATION IS RELATIVE
                ACCESS MODE IS RANDOM
                RELATIVE KEY IS REL-KEY.
        """
        
        result = parser.parse(source)
        assert result.ast is not None


class TestArithmeticStatements:
    """Test arithmetic statement parsing."""
    
    def test_add_statement(self):
        """Test ADD statement variations."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-A PIC 9(5).
        01  WS-B PIC 9(5).
        01  WS-C PIC 9(5).
        PROCEDURE DIVISION.
            ADD WS-A TO WS-B.
            ADD WS-A WS-B GIVING WS-C.
            ADD WS-A TO WS-B ROUNDED.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_subtract_statement(self):
        """Test SUBTRACT statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-A PIC 9(5).
        01  WS-B PIC 9(5).
        PROCEDURE DIVISION.
            SUBTRACT WS-A FROM WS-B.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_multiply_statement(self):
        """Test MULTIPLY statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-A PIC 9(5).
        01  WS-B PIC 9(5).
        PROCEDURE DIVISION.
            MULTIPLY WS-A BY WS-B.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_divide_statement(self):
        """Test DIVIDE statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-A PIC 9(5).
        01  WS-B PIC 9(5).
        01  WS-C PIC 9(5).
        PROCEDURE DIVISION.
            DIVIDE WS-A BY WS-B GIVING WS-C.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_compute_statement(self):
        """Test COMPUTE statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-A PIC 9(5).
        01  WS-B PIC 9(5).
        01  WS-C PIC 9(5).
        PROCEDURE DIVISION.
            COMPUTE WS-C = WS-A + WS-B.
        """
        
        result = parser.parse(source)
        assert result.ast is not None


class TestStringStatements:
    """Test string manipulation statement parsing."""
    
    def test_string_statement(self):
        """Test STRING statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-A PIC X(10).
        01  WS-B PIC X(10).
        01  WS-C PIC X(20).
        PROCEDURE DIVISION.
            STRING WS-A WS-B DELIMITED BY SIZE INTO WS-C.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_unstring_statement(self):
        """Test UNSTRING statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-SOURCE PIC X(30).
        01  WS-A PIC X(10).
        01  WS-B PIC X(10).
        PROCEDURE DIVISION.
            UNSTRING WS-SOURCE DELIMITED BY SPACE
                INTO WS-A WS-B.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_inspect_statement(self):
        """Test INSPECT statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-FIELD PIC X(20).
        PROCEDURE DIVISION.
            INSPECT WS-FIELD REPLACING ALL 'A' BY 'B'.
        """
        
        result = parser.parse(source)
        assert result.ast is not None


class TestControlFlowStatements:
    """Test control flow statement parsing."""
    
    def test_if_statement(self):
        """Test IF statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-A PIC 9(5).
        PROCEDURE DIVISION.
            IF WS-A > 10
                DISPLAY 'Greater'
            ELSE
                DISPLAY 'Less'
            END-IF.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_evaluate_statement(self):
        """Test EVALUATE statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-CHOICE PIC 9.
        PROCEDURE DIVISION.
            EVALUATE WS-CHOICE
                WHEN 1
                    DISPLAY 'One'
                WHEN 2
                    DISPLAY 'Two'
                WHEN OTHER
                    DISPLAY 'Other'
            END-EVALUATE.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_perform_statement(self):
        """Test PERFORM statement variations."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-I PIC 9(3).
        PROCEDURE DIVISION.
            PERFORM 100-PARA.
            PERFORM 100-PARA 5 TIMES.
            PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 10
                DISPLAY WS-I
            END-PERFORM.
        100-PARA.
            DISPLAY 'Paragraph'.
        """
        
        result = parser.parse(source)
        assert result.ast is not None


class TestIBMExtensionsParsing:
    """Test IBM Enterprise COBOL extension parsing."""
    
    def test_comp3_usage(self):
        """Test COMP-3 (packed decimal) usage."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-PACKED PIC S9(7)V99 COMP-3.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_exec_sql_block(self):
        """Test EXEC SQL embedded SQL."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-NAME PIC X(30).
        PROCEDURE DIVISION.
            EXEC SQL
                SELECT NAME INTO :WS-NAME
                FROM EMPLOYEE
                WHERE EMPNO = 123
            END-EXEC.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_exec_cics_block(self):
        """Test EXEC CICS transaction command."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-DATA PIC X(100).
        PROCEDURE DIVISION.
            EXEC CICS
                READ FILE('EMPLOYEE')
                INTO(WS-DATA)
                RIDFLD(WS-KEY)
            END-EXEC.
        """
        
        result = parser.parse(source)
        assert result.ast is not None


class TestSpecialFeatures:
    """Test special COBOL features parsing."""
    
    def test_accept_from_date(self):
        """Test ACCEPT FROM DATE."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-DATE PIC 9(8).
        PROCEDURE DIVISION.
            ACCEPT WS-DATE FROM DATE YYYYMMDD.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_display_upon_console(self):
        """Test DISPLAY UPON CONSOLE."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            DISPLAY 'Message' UPON CONSOLE.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
        
    def test_sort_statement(self):
        """Test SORT statement."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT INPUT-FILE ASSIGN TO 'INPUT.DAT'.
            SELECT OUTPUT-FILE ASSIGN TO 'OUTPUT.DAT'.
            SELECT SORT-FILE ASSIGN TO 'SORT.WRK'.
        DATA DIVISION.
        FILE SECTION.
        FD INPUT-FILE.
        01 INPUT-REC PIC X(80).
        FD OUTPUT-FILE.
        01 OUTPUT-REC PIC X(80).
        SD SORT-FILE.
        01 SORT-REC.
           05 SORT-KEY PIC X(10).
           05 SORT-DATA PIC X(70).
        PROCEDURE DIVISION.
            SORT SORT-FILE
                ON ASCENDING KEY SORT-KEY
                USING INPUT-FILE
                GIVING OUTPUT-FILE.
        """
        
        result = parser.parse(source)
        assert result.ast is not None
