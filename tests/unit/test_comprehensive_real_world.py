"""
Final comprehensive unit tests for real-world COBOL patterns with proper formatting.

This module tests all patterns found in the examples directory to ensure
proper coverage and documents what currently works vs. needs implementation.
"""

from cobolparser import ErrorRecoveryMode, parse_cobol


class TestRealWorldCobolPatterns:
    """Test real-world COBOL patterns found in examples directory."""

    def create_cobol_program(self, data_section="", procedure_section="STOP RUN."):
        """Helper to create properly formatted COBOL program."""
        return f"""       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST-PROG.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
{data_section}

       PROCEDURE DIVISION.
       {procedure_section}"""

    def test_basic_picture_clauses(self):
        """Test basic PICTURE clause patterns."""
        test_cases = [
            ("01  WS-FIELD    PIC X(20).", "Alphanumeric"),
            ("01  WS-NUM      PIC 9(5).", "Numeric"),
            ("01  WS-SIGNED   PIC S9(5).", "Signed numeric"),
            ("01  WS-DECIMAL  PIC 9(5)V99.", "Decimal"),
            ("01  WS-SIGNDEC  PIC S9(5)V9(5).", "Signed decimal"),
        ]

        for data_def, description in test_cases:
            cobol_source = self.create_cobol_program(data_section=f"       {data_def}")
            result = parse_cobol(cobol_source)

            assert result.success, f"{description} failed to parse: {result.errors[:3]}"
            assert result.ast is not None

    def test_complex_picture_patterns_from_examples(self):
        """Test complex PICTURE patterns found in NIST examples."""
        test_cases = [
            ("77  WRK-DS-18V00                PICTURE S9(18).", "18-digit signed"),
            (
                "77  A06THREES-DS-03V03          PICTURE S999V999 VALUE 333.333.",
                "Signed with decimal and VALUE",
            ),
            (
                "77  A05ONES-DS-00V05            PICTURE SV9(5) VALUE .11111.",
                "Leading decimal point",
            ),
            (
                "77  A01ONE-DS-P0801             PICTURE SP(8)9 VALUE .000000001.",
                "Scaling factor",
            ),
            ("01  PRINT-REC PICTURE X(120).", "Large alphanumeric"),
        ]

        for data_def, description in test_cases:
            cobol_source = self.create_cobol_program(data_section=f"       {data_def}")
            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert result.success, f"{description} failed to parse: {result.errors[:3]}"
            assert result.ast is not None

    def test_usage_clauses_from_examples(self):
        """Test USAGE clauses found in examples."""
        test_cases = [
            ("01  WS-COMP-FIELD              PIC 9(5) COMP.", "COMP usage"),
            ("01  WS-COMP3-FIELD             PIC 9(7)V99 COMP-3.", "COMP-3 usage"),
            (
                "77  WRK-CS-18V00               PICTURE S9(18) COMPUTATIONAL.",
                "Full COMPUTATIONAL",
            ),
        ]

        for data_def, description in test_cases:
            cobol_source = self.create_cobol_program(data_section=f"       {data_def}")
            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert result.success, f"{description} failed to parse: {result.errors[:3]}"
            assert result.ast is not None

    def test_level_number_variations(self):
        """Test level number patterns from examples."""
        test_cases = [
            ("77  INDEPENDENT-ITEM           PIC X(10).", "Level 77"),
            ("01  GROUP-ITEM.", "Level 01 group"),
            ("    05  SUB-ITEM               PIC X(5).", "Level 05"),
            ("    02  LEVEL-TWO               PIC 9(3).", "Level 02"),
            ("      03  LEVEL-THREE           PIC X(1).", "Level 03"),
        ]

        for data_def, description in test_cases:
            cobol_source = self.create_cobol_program(data_section=f"       {data_def}")
            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert result.success, f"{description} failed to parse: {result.errors[:3]}"
            assert result.ast is not None

    def test_value_clauses_from_examples(self):
        """Test VALUE clause patterns from examples."""
        test_cases = [
            ('01  WS-MESSAGE    PIC X(20) VALUE "Hello World".', "String literal"),
            ("01  WS-COUNTER    PIC 9(5) VALUE 123.", "Numeric literal"),
            ("01  WS-ZERO       PIC 9(5) VALUE ZERO.", "Figurative constant ZERO"),
            ("01  WS-SPACES     PIC X(10) VALUE SPACES.", "Figurative constant SPACES"),
            ("01  WS-DECIMAL    PIC 9(5)V99 VALUE 123.45.", "Decimal literal"),
        ]

        for data_def, description in test_cases:
            cobol_source = self.create_cobol_program(data_section=f"       {data_def}")
            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert result.success, f"{description} failed to parse: {result.errors[:3]}"
            assert result.ast is not None

    def test_redefines_patterns_from_examples(self):
        """Test REDEFINES patterns found in examples."""
        test_cases = [
            """       01  WRK-XN-18-1 PIC X(18).
       01  WRK-AN-X-18-1 REDEFINES WRK-XN-18-1 PIC A(18).""",
            """       77  WRK-DS-06V06                PICTURE S9(6)V9(6).
       77  WRK-DS-12V00-S REDEFINES WRK-DS-06V06 PICTURE S9(12).""",
        ]

        for data_section in test_cases:
            cobol_source = self.create_cobol_program(data_section=data_section)
            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert (
                result.success
            ), f"REDEFINES pattern failed to parse: {result.errors[:3]}"
            assert result.ast is not None

    def test_occurs_patterns_from_examples(self):
        """Test OCCURS patterns found in examples."""
        test_cases = [
            """       01  ARR                         VALUE "40537".
           02  IND OCCURS 5 TIMES PIC 9.""",
            """       01  COMPLEX-ARRAY.
           05  MONTH-DATA OCCURS 12 TIMES.
               10  MONTH-NAME          PIC X(9).
               10  DAYS-IN-MONTH       PIC 99.""",
        ]

        for data_section in test_cases:
            cobol_source = self.create_cobol_program(data_section=data_section)
            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert (
                result.success
            ), f"OCCURS pattern failed to parse: {result.errors[:3]}"
            assert result.ast is not None

    def test_procedure_statements_from_examples(self):
        """Test PROCEDURE DIVISION statements from examples."""
        test_cases = [
            ("DISPLAY WS-MESSAGE.", "DISPLAY statement"),
            ("MOVE 100 TO WS-COUNTER.", "MOVE statement"),
            ("ADD 1.5 TO WS-TOTAL.", "ADD statement"),
            ("SUBTRACT 1 FROM WS-COUNTER.", "SUBTRACT statement"),
            ('CALL "IC102A" USING DN1.', "CALL statement with USING"),
            ("PERFORM CALC-PARA UNTIL WS-COUNTER = 0.", "PERFORM with UNTIL"),
        ]

        data_section = """       01  WS-MESSAGE    PIC X(20).
       01  WS-COUNTER    PIC 9(5).
       01  WS-TOTAL      PIC 9(7)V99.
       01  DN1           PIC 9(5)."""

        for statement, description in test_cases:
            procedure_section = (
                f"{statement}\nCALC-PARA.\n    DISPLAY 'Test'.\nSTOP RUN."
            )
            cobol_source = self.create_cobol_program(
                data_section=data_section, procedure_section=procedure_section
            )
            result = parse_cobol(
                cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL
            )

            assert result.success, f"{description} failed to parse: {result.errors[:3]}"
            assert result.ast is not None

    def test_environment_division_patterns(self):
        """Test ENVIRONMENT DIVISION patterns from examples."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. ENV-TEST.

       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-3090.
       OBJECT-COMPUTER. IBM-3090.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO PRINTER.

       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-FIELD    PIC X(10).

       PROCEDURE DIVISION.
       STOP RUN."""

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert (
            result.success
        ), f"ENVIRONMENT DIVISION failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        assert result.ast.has_division("ENVIRONMENT")

    def test_file_section_patterns(self):
        """Test FILE SECTION patterns from examples."""
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILE-TEST.

       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO PRINTER.

       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE.
       01  PRINT-REC PICTURE X(120).
       01  DUMMY-RECORD PICTURE X(120).

       WORKING-STORAGE SECTION.
       01  WS-FIELD    PIC X(10).

       PROCEDURE DIVISION.
       STOP RUN."""

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        assert result.success, f"FILE SECTION failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        # The FD's records must be present in the AST.
        item_names = {
            getattr(item, "name", None)
            for item in result.ast.find_all_by_type("CobolDataItem")
        }
        assert "PRINT-REC" in item_names
        assert "DUMMY-RECORD" in item_names

    def test_actual_nist_program_structure(self):
        """Test parsing actual NIST program structure (simplified)."""
        # Simplified version of IC101A.CBL structure
        cobol_source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID.
           IC101A.

       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER.
           XXXXX082.
       OBJECT-COMPUTER.
           XXXXX083.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT PRINT-FILE ASSIGN TO
           XXXXX055.

       DATA DIVISION.
       FILE SECTION.
       FD  PRINT-FILE.
       01  PRINT-REC PICTURE X(120).
       01  DUMMY-RECORD PICTURE X(120).
       WORKING-STORAGE SECTION.
       77  DN1 PICTURE S9  VALUE ZERO.
       77  DN2 PICTURE S9  VALUE ZERO.

       PROCEDURE DIVISION.
       CALL-TEST-1.
           CALL "IC102A" USING DN1.
           IF DN1 IS EQUAL TO 1
               PERFORM PASS-ROUTINE.
       PASS-ROUTINE.
           DISPLAY "PASS".
       STOP RUN."""

        result = parse_cobol(cobol_source, error_recovery=ErrorRecoveryMode.COLLECT_ALL)

        # The goal: actual NIST-style programs must parse successfully.
        assert (
            result.success
        ), f"NIST program structure failed to parse: {result.errors[:5]}"
        assert result.ast is not None
        assert result.ast.program_name == "IC101A"
        # The CALL from the procedure division must survive into the AST.
        calls = result.ast.find_all_by_type("CallStatement")
        assert len(calls) >= 1, "Expected the CALL 'IC102A' statement in the AST"


class TestCurrentParserStatus:
    """Verify the parser handles every pattern category exercised above."""

    def test_parser_capability_sweep(self):
        """One representative source per capability category must parse."""
        capability_sources = {
            "Basic program structure": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAP-BASIC.
       PROCEDURE DIVISION.
           STOP RUN.""",
            "REDEFINES clause": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAP-REDEF.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A     PIC X(10).
       01  WS-B REDEFINES WS-A PIC 9(10).
       PROCEDURE DIVISION.
           STOP RUN.""",
            "OCCURS clause": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAP-OCCURS.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-TBL.
           05  WS-ITEM OCCURS 10 TIMES PIC 9(5).
       PROCEDURE DIVISION.
           STOP RUN.""",
            "USAGE clauses (COMP, COMP-3)": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAP-USAGE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-C     PIC 9(5) COMP.
       01  WS-C3    PIC 9(7)V99 COMP-3.
       PROCEDURE DIVISION.
           STOP RUN.""",
            "ENVIRONMENT DIVISION": """       IDENTIFICATION DIVISION.
       PROGRAM-ID. CAP-ENV.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       SOURCE-COMPUTER. IBM-3090.
       OBJECT-COMPUTER. IBM-3090.
       PROCEDURE DIVISION.
           STOP RUN.""",
        }

        failures = {}
        for capability, source in capability_sources.items():
            result = parse_cobol(source)
            if not (result.success and result.ast is not None):
                failures[capability] = result.errors[:3]

        assert not failures, f"Capability regressions: {failures}"
