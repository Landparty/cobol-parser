from cobolparser.preprocess.copy_statement_parser import extract_copy_statements


def test_extract_simple_copy():
    source = "       COPY EMPLOYEE."
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].member_name == "EMPLOYEE"


def test_extract_copy_with_replacing():
    source = (
        "       COPY EMPLOYEE\n"
        "           REPLACING ==OLD== BY ==NEW==\n"
        "                     LEADING ==PREFIX== BY ==EMP-==."
    )
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].member_name == "EMPLOYEE"
    assert len(statements[0].replacing_clauses) == 2
    assert statements[0].replacing_clauses[0].find_text == "OLD"
    assert statements[0].replacing_clauses[0].replace_text == "NEW"
    assert statements[0].replacing_clauses[0].mode == "ALL"
    assert statements[0].replacing_clauses[1].find_text == "PREFIX"
    assert statements[0].replacing_clauses[1].replace_text == "EMP-"
    assert statements[0].replacing_clauses[1].mode == "LEADING"


def test_extract_copy_with_in_library():
    source = "       COPY EMP IN LIBA."
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].member_name == "EMP"
    assert statements[0].library_qualifier == "LIBA"


def test_extract_copy_with_suppress():
    source = "       COPY EMP SUPPRESS PRINTING."
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].member_name == "EMP"
    assert statements[0].is_suppressed is True


def test_nested_pseudo_text_with_period():
    # A period inside pseudo-text should not terminate the COPY statement
    source = "       COPY MYCOPY REPLACING ==A.B== BY ==C.D==."
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].member_name == "MYCOPY"
    assert statements[0].replacing_clauses[0].find_text == "A.B"
    assert statements[0].replacing_clauses[0].replace_text == "C.D"


def test_copy_in_literal_ignored():
    source = '       DISPLAY "COPY EMPLOYEE.".'
    statements = extract_copy_statements(source)
    assert len(statements) == 0


def test_copy_in_comment_ignored():
    source = """
      * COPY EMPLOYEE.
       MOVE A TO B.
    """
    statements = extract_copy_statements(source)
    assert len(statements) == 0


def test_malformed_copy_incomplete():
    source = "       COPY EMPLOYEE"  # Missing period
    statements = extract_copy_statements(source)
    assert len(statements) == 0


def test_multiple_copy_statements():
    source = """
       COPY M1.
       COPY M2 REPLACING ==X== BY ==Y==.
    """
    statements = extract_copy_statements(source)
    assert len(statements) == 2
    assert statements[0].member_name == "M1"
    assert statements[1].member_name == "M2"


def test_very_long_replacing_clause():
    # Test for performance/robustness without hitting column 72 limit
    lines = ["       COPY LONGBOOK REPLACING"]
    for i in range(100):
        lines.append(f"           ==OLD{i}== BY ==NEW{i}==")
    lines[-1] += "."
    source = "\n".join(lines)
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].member_name == "LONGBOOK"
    assert len(statements[0].replacing_clauses) == 100


def test_malformed_replacing_missing_by():
    # Malformed REPLACING should probably not be extracted as a valid statement
    source = "       COPY MYCOPY REPLACING ==A== ==B==."
    statements = extract_copy_statements(source)
    # Depending on implementation, it might fail to match or match partially.
    # A robust lexer should handle this gracefully.
    assert len(statements) == 0


def test_copy_with_continuation_and_quotes():
    # Copy statement continued with '-' in column 7
    source = "000100 COPY MYBOOK REPLACING           \n000200-    ==A== BY ==B==."
    # The current extract_copy_statements calls strip_sequence_area then normalize_continuation_lines
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].member_name == "MYBOOK"
    assert len(statements[0].replacing_clauses) == 1


def test_source_location_with_crlf_line_endings():
    # Windows \r\n EOLs must count as one line break, not two.
    source = "       PROCEDURE DIVISION.\r\n       COPY EMPLOYEE."
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].source_location is not None
    _file, line, _col = statements[0].source_location
    assert line == 2


def test_source_location_with_bare_cr_line_endings():
    # Bare \r EOLs (classic Mac / mainframe-transferred sources).
    source = "       PROCEDURE DIVISION.\r       COPY EMPLOYEE."
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].source_location is not None
    _file, line, _col = statements[0].source_location
    assert line == 2


def test_source_location_with_mixed_line_endings():
    source = (
        "       LINE ONE.\r\n"
        "       LINE TWO.\r"
        "       LINE THREE.\n"
        "       COPY EMPLOYEE."
    )
    statements = extract_copy_statements(source)
    assert len(statements) == 1
    assert statements[0].source_location is not None
    _file, line, _col = statements[0].source_location
    assert line == 4


class TestExtractCopyStatementsSqlInclude:
    """``extract_copy_statements(sql_include=True)`` reports INCLUDEs (#295)."""

    SOURCE = (
        "       WORKING-STORAGE SECTION.\n"
        "       COPY CUSTREC.\n"
        "           EXEC SQL INCLUDE SQLCA END-EXEC.\n"
    )

    def test_default_ignores_sql_include(self):
        names = [s.member_name for s in extract_copy_statements(self.SOURCE)]
        assert names == ["CUSTREC"]

    def test_flag_reports_sql_include_marked_as_such(self):
        found = extract_copy_statements(self.SOURCE, sql_include=True)
        assert [(s.member_name, s.sql_include) for s in found] == [
            ("CUSTREC", False),
            ("SQLCA", True),
        ]
