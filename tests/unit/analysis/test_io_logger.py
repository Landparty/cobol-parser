"""Unit tests for IOLogger, IOLogReport, and IOOperation.

Tests the IO logging analyzer that extracts all input/output operations
from parsed COBOL programs, covering CALL linkage, EXEC SQL, file I/O,
and console I/O.
"""

import json

from cobolparser import parse_cobol
from cobolparser.analysis.io_logger import IOLogger, IOLogReport, IOOperation


class TestIOOperation:
    """Tests for the IOOperation dataclass."""

    def test_to_dict(self):
        op = IOOperation(
            category="CALL",
            operation="CALL SUBPROG",
            direction="INPUT",
            variables=["WS-PARAM"],
            target="SUBPROG",
            line=10,
            details={"passing_mode": "CONTENT"},
        )
        d = op.to_dict()
        assert d["category"] == "CALL"
        assert d["operation"] == "CALL SUBPROG"
        assert d["direction"] == "INPUT"
        assert d["variables"] == ["WS-PARAM"]
        assert d["target"] == "SUBPROG"
        assert d["line"] == 10
        assert d["details"]["passing_mode"] == "CONTENT"

    def test_defaults(self):
        op = IOOperation(category="SQL", operation="SELECT", direction="OUTPUT")
        assert op.variables == []
        assert op.target is None
        assert op.line is None
        assert op.details == {}


class TestIOLogReport:
    """Tests for the IOLogReport dataclass."""

    def test_empty_report(self):
        report = IOLogReport(program_name="TESTPROG", operations=[])
        assert report.inputs == []
        assert report.outputs == []
        assert report.bidirectional == []
        assert report.calls == []
        assert report.sql_operations == []
        assert report.file_operations == []
        assert report.console_operations == []

    def test_filter_properties(self):
        ops = [
            IOOperation("CALL", "CALL X", "INPUT", ["A"], "X"),
            IOOperation("CALL", "CALL X", "OUTPUT", ["B"], "X"),
            IOOperation("CALL", "CALL X", "BIDIRECTIONAL", ["C"], "X"),
            IOOperation("SQL", "SELECT", "OUTPUT", ["D"], "T1"),
            IOOperation("FILE-IO", "READ", "INPUT", ["E"], "F1"),
            IOOperation("CONSOLE-IO", "DISPLAY", "OUTPUT", ["F"]),
            IOOperation("ENTRY", "ENTRY Y", "BIDIRECTIONAL", ["G"], "Y"),
        ]
        report = IOLogReport(program_name="TEST", operations=ops)

        assert len(report.inputs) == 2  # CALL INPUT + FILE-IO READ
        assert len(report.outputs) == 3  # CALL OUTPUT + SQL + DISPLAY
        assert len(report.bidirectional) == 2  # CALL BIDIR + ENTRY
        assert len(report.calls) == 4  # 3 CALL + 1 ENTRY
        assert len(report.sql_operations) == 1
        assert len(report.file_operations) == 1
        assert len(report.console_operations) == 1

    def test_to_dict_structure(self):
        ops = [
            IOOperation("CALL", "CALL X", "INPUT", ["A"], "X", 10),
        ]
        report = IOLogReport(program_name="MYPROG", operations=ops)
        d = report.to_dict()

        assert d["program_name"] == "MYPROG"
        assert len(d["operations"]) == 1
        assert d["summary"]["total"] == 1
        assert d["summary"]["inputs"] == 1
        assert d["summary"]["outputs"] == 0
        assert d["summary"]["by_category"]["CALL"] == 1

    def test_to_json(self):
        report = IOLogReport(program_name="JSONTEST", operations=[])
        j = report.to_json()
        parsed = json.loads(j)
        assert parsed["program_name"] == "JSONTEST"
        assert parsed["summary"]["total"] == 0


class TestIOLoggerCallStatements:
    """Tests for CALL statement I/O extraction."""

    def test_call_by_reference(self):
        """BY REFERENCE parameters are BIDIRECTIONAL."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PARAM PIC X(10).
       PROCEDURE DIVISION.
           CALL 'SUBPROG' USING BY REFERENCE WS-PARAM.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        call_ops = report.calls
        assert len(call_ops) >= 1
        ref_op = [o for o in call_ops if o.details.get("passing_mode") == "REFERENCE"]
        assert len(ref_op) >= 1
        assert ref_op[0].direction == "BIDIRECTIONAL"
        assert "WS-PARAM" in ref_op[0].variables

    def test_call_by_content(self):
        """BY CONTENT parameters are INPUT."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PARAM PIC X(10).
       PROCEDURE DIVISION.
           CALL 'SUBPROG' USING BY CONTENT WS-PARAM.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        call_ops = report.calls
        content_ops = [
            o for o in call_ops if o.details.get("passing_mode") == "CONTENT"
        ]
        assert len(content_ops) >= 1
        assert content_ops[0].direction == "INPUT"

    def test_call_by_value(self):
        """BY VALUE parameters are INPUT."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUM PIC 9(5).
       PROCEDURE DIVISION.
           CALL 'SUBPROG' USING BY VALUE WS-NUM.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        call_ops = report.calls
        value_ops = [o for o in call_ops if o.details.get("passing_mode") == "VALUE"]
        assert len(value_ops) >= 1
        assert value_ops[0].direction == "INPUT"

    def test_call_returning(self):
        """RETURNING parameter is OUTPUT."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PARAM PIC X(10).
       01  WS-RESULT PIC 9(5).
       PROCEDURE DIVISION.
           CALL 'SUBPROG' USING WS-PARAM
               RETURNING WS-RESULT.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        call_ops = report.calls
        ret_ops = [o for o in call_ops if o.details.get("passing_mode") == "RETURNING"]
        assert len(ret_ops) >= 1
        assert ret_ops[0].direction == "OUTPUT"
        assert "WS-RESULT" in ret_ops[0].variables

    def test_call_mixed_modes(self):
        """Multiple parameters with different passing modes."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X(10).
       01  WS-B PIC X(10).
       01  WS-C PIC 9(5).
       01  WS-RET PIC 9(5).
       PROCEDURE DIVISION.
           CALL 'MIXED' USING BY REFERENCE WS-A
                               BY CONTENT WS-B
                               BY VALUE WS-C
               RETURNING WS-RET.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        call_ops = [o for o in report.calls if o.category == "CALL"]
        assert len(call_ops) == 4  # 3 USING + 1 RETURNING

        modes = {o.details["passing_mode"]: o.direction for o in call_ops}
        assert modes["REFERENCE"] == "BIDIRECTIONAL"
        assert modes["CONTENT"] == "INPUT"
        assert modes["VALUE"] == "INPUT"
        assert modes["RETURNING"] == "OUTPUT"

    def test_call_target_program_name(self):
        """Target is set to the called program name."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCALL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X PIC X(10).
       PROCEDURE DIVISION.
           CALL 'MY-SUBPROG' USING WS-X.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        assert len(report.calls) >= 1
        assert report.calls[0].target == "MY-SUBPROG"
        assert "CALL MY-SUBPROG" in report.calls[0].operation


class TestIOLoggerEntryStatements:
    """Tests for ENTRY statement I/O extraction."""

    def test_entry_parameters_bidirectional(self):
        """ENTRY parameters are BIDIRECTIONAL (linkage section)."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTENTRY.
       PROCEDURE DIVISION.
           ENTRY 'DLITCBL' USING WS-PCB1 WS-PCB2.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        entry_ops = [o for o in report.calls if o.category == "ENTRY"]
        assert len(entry_ops) >= 1
        for op in entry_ops:
            assert op.direction == "BIDIRECTIONAL"
            assert op.target == "DLITCBL"


class TestIOLoggerSQLStatements:
    """Tests for EXEC SQL I/O extraction."""

    def test_sql_select_into(self):
        """SELECT INTO extracts output variables and input host variables."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME PIC X(30).
       01  WS-ID   PIC 9(5).
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT NAME INTO :WS-NAME
               FROM EMPLOYEE
               WHERE EMP-ID = :WS-ID
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        sql_ops = report.sql_operations
        assert len(sql_ops) >= 1

        output_ops = [o for o in sql_ops if o.direction == "OUTPUT"]
        assert len(output_ops) >= 1
        assert "WS-NAME" in output_ops[0].variables

        input_ops = [o for o in sql_ops if o.direction == "INPUT"]
        assert len(input_ops) >= 1
        assert "WS-ID" in input_ops[0].variables

    def test_sql_insert(self):
        """INSERT with host variables extracts inputs."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NAME PIC X(30).
       01  WS-DEPT PIC X(10).
       PROCEDURE DIVISION.
           EXEC SQL
               INSERT INTO EMPLOYEE (NAME, DEPT)
               VALUES (:WS-NAME, :WS-DEPT)
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        sql_ops = report.sql_operations
        input_ops = [o for o in sql_ops if o.direction == "INPUT"]
        assert len(input_ops) >= 1
        vars_found = input_ops[0].variables
        assert "WS-NAME" in vars_found
        assert "WS-DEPT" in vars_found

    def test_sql_details_include_type_and_tables(self):
        """SQL operations include sql_type and tables in details."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SQLTEST.
       PROCEDURE DIVISION.
           EXEC SQL
               SELECT NAME INTO :WS-NAME
               FROM EMPLOYEE
               WHERE ID = :WS-ID
           END-EXEC.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        sql_ops = report.sql_operations
        assert len(sql_ops) >= 1
        details = sql_ops[0].details
        assert details["sql_type"] == "SELECT"
        assert "EMPLOYEE" in details.get("tables", [])


class TestIOLoggerFileIO:
    """Tests for file I/O extraction."""

    def test_read_statement(self):
        """READ is INPUT from file."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILETEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT CUSTOMER-FILE ASSIGN TO 'CUST.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  CUSTOMER-FILE.
       01  CUST-RECORD PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-RECORD PIC X(80).
       PROCEDURE DIVISION.
           OPEN INPUT CUSTOMER-FILE.
           READ CUSTOMER-FILE INTO WS-RECORD
               AT END DISPLAY 'END OF FILE'
           END-READ.
           CLOSE CUSTOMER-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        file_ops = report.file_operations
        read_ops = [o for o in file_ops if o.operation == "READ"]
        assert len(read_ops) >= 1
        assert read_ops[0].direction == "INPUT"
        assert read_ops[0].target == "CUSTOMER-FILE"

    def test_write_statement(self):
        """WRITE is OUTPUT to file."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILETEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT OUT-FILE ASSIGN TO 'OUT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  OUT-FILE.
       01  OUT-RECORD PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-DATA PIC X(80).
       PROCEDURE DIVISION.
           OPEN OUTPUT OUT-FILE.
           WRITE OUT-RECORD FROM WS-DATA.
           CLOSE OUT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        file_ops = report.file_operations
        write_ops = [o for o in file_ops if o.operation == "WRITE"]
        assert len(write_ops) >= 1
        assert write_ops[0].direction == "OUTPUT"

    def test_open_modes(self):
        """OPEN modes map to correct directions."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILETEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO 'IN.DAT'.
           SELECT OUT-FILE ASSIGN TO 'OUT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(80).
       FD  OUT-FILE.
       01  OUT-REC PIC X(80).
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE.
           OPEN OUTPUT OUT-FILE.
           CLOSE IN-FILE.
           CLOSE OUT-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        file_ops = report.file_operations
        open_ops = [o for o in file_ops if o.operation.startswith("OPEN")]

        open_input = [o for o in open_ops if "INPUT" in o.operation]
        open_output = [o for o in open_ops if "OUTPUT" in o.operation]

        if open_input:
            assert open_input[0].direction == "INPUT"
        if open_output:
            assert open_output[0].direction == "OUTPUT"

    def test_close_statement(self):
        """CLOSE is BIDIRECTIONAL."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. FILETEST.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT MY-FILE ASSIGN TO 'DATA.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  MY-FILE.
       01  MY-REC PIC X(80).
       PROCEDURE DIVISION.
           OPEN INPUT MY-FILE.
           CLOSE MY-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        file_ops = report.file_operations
        close_ops = [o for o in file_ops if o.operation == "CLOSE"]
        assert len(close_ops) >= 1
        assert close_ops[0].direction == "BIDIRECTIONAL"


class TestIOLoggerConsoleIO:
    """Tests for ACCEPT and DISPLAY I/O extraction."""

    def test_accept_is_input(self):
        """ACCEPT is INPUT."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONSTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-INPUT PIC X(20).
       PROCEDURE DIVISION.
           ACCEPT WS-INPUT.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        console_ops = report.console_operations
        accept_ops = [o for o in console_ops if o.operation == "ACCEPT"]
        assert len(accept_ops) >= 1
        assert accept_ops[0].direction == "INPUT"

    def test_display_is_output(self):
        """DISPLAY is OUTPUT."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CONSTEST.
       PROCEDURE DIVISION.
           DISPLAY 'HELLO WORLD'.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        console_ops = report.console_operations
        display_ops = [o for o in console_ops if o.operation == "DISPLAY"]
        assert len(display_ops) >= 1
        assert display_ops[0].direction == "OUTPUT"


class TestIOLoggerCombined:
    """Tests for programs with multiple I/O types."""

    def test_combined_program(self):
        """A program with CALL, SQL, file I/O, and DISPLAY."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMBINED.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT IN-FILE ASSIGN TO 'INPUT.DAT'.
       DATA DIVISION.
       FILE SECTION.
       FD  IN-FILE.
       01  IN-REC PIC X(80).
       WORKING-STORAGE SECTION.
       01  WS-DATA PIC X(80).
       01  WS-NAME PIC X(30).
       01  WS-ID   PIC 9(5).
       PROCEDURE DIVISION.
           OPEN INPUT IN-FILE.
           READ IN-FILE INTO WS-DATA
               AT END DISPLAY 'EOF'
           END-READ.
           CALL 'PROCESS' USING BY REFERENCE WS-DATA.
           EXEC SQL
               SELECT NAME INTO :WS-NAME
               FROM CUSTOMER
               WHERE CUST-ID = :WS-ID
           END-EXEC.
           DISPLAY WS-NAME.
           CLOSE IN-FILE.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        assert len(report.operations) >= 4
        assert len(report.file_operations) >= 2  # OPEN + READ + CLOSE
        assert len(report.calls) >= 1
        assert len(report.sql_operations) >= 1
        assert len(report.console_operations) >= 1

    def test_report_program_name(self):
        """Report captures the program name."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MYPROG.
       PROCEDURE DIVISION.
           DISPLAY 'HI'.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)
        assert report.program_name == "MYPROG"

    def test_to_json_roundtrip(self):
        """to_json produces valid JSON that can be parsed back."""
        result = parse_cobol("""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. JSONTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X PIC X(10).
       PROCEDURE DIVISION.
           CALL 'SUB1' USING WS-X.
           DISPLAY 'DONE'.
           STOP RUN.
        """)
        assert result.ast is not None
        logger = IOLogger()
        report = logger.analyze(result.ast)

        j = report.to_json()
        parsed = json.loads(j)
        assert parsed["program_name"] == "JSONTEST"
        assert isinstance(parsed["operations"], list)
        assert isinstance(parsed["summary"], dict)


class TestIOLoggerReuse:
    """Tests that the analyzer can be reused across multiple programs."""

    def test_reuse_analyzer(self):
        """Calling analyze() twice resets state."""
        src1 = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG1.
       PROCEDURE DIVISION.
           DISPLAY 'A'.
           STOP RUN.
        """
        src2 = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROG2.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X PIC X(10).
       PROCEDURE DIVISION.
           CALL 'SUB' USING WS-X.
           STOP RUN.
        """
        logger = IOLogger()

        r1 = parse_cobol(src1)
        assert r1.ast is not None
        report1 = logger.analyze(r1.ast)

        r2 = parse_cobol(src2)
        assert r2.ast is not None
        report2 = logger.analyze(r2.ast)

        assert report1.program_name == "PROG1"
        assert report2.program_name == "PROG2"
        # report2 should not contain operations from report1
        assert all(o.category != "CONSOLE-IO" for o in report2.operations)
