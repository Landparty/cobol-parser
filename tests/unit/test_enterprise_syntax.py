"""Enterprise COBOL syntax the program-type corpus surfaced (2026-09-15).

Each class pins one construct: what the parser now produces for it, and
what it produced before (a warning, a dropped clause, no AST) so the
regression is recognizable if it returns.
"""

from __future__ import annotations

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol
from cobolparser.preprocess import preprocess_conditional_compilation
from cobolparser.preprocess.replace_statement import apply_replace_statements


def _program(data: str = "", proc: str = "           GOBACK.\n", head: str = "") -> str:
    return (
        head
        + "       IDENTIFICATION DIVISION.\n"
        + "       PROGRAM-ID. T.\n"
        + "       DATA DIVISION.\n"
        + "       WORKING-STORAGE SECTION.\n"
        + data
        + "       PROCEDURE DIVISION.\n"
        + "       A.\n"
        + proc
    )


def _parse(source: str, filename: str = "t.cbl"):
    result = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST).parse(
        source, filename
    )
    assert result.errors == [], result.errors
    assert result.ast is not None
    return result


def _item(ast, name):
    return next(i for i in ast.get_data_items() if i.name == name)


class TestProgramIdAttributes:
    def test_recursive_and_trailing_program_word(self):
        src = _program().replace(
            "PROGRAM-ID. T.", "PROGRAM-ID. T IS RECURSIVE PROGRAM."
        )
        result = _parse(src)
        assert result.warnings == []
        assert result.ast.program_attributes == ["RECURSIVE"]
        assert result.ast.is_recursive

    def test_initial_common_recursive_in_any_order(self):
        src = _program().replace("PROGRAM-ID. T.", "PROGRAM-ID. T COMMON INITIAL.")
        result = _parse(src)
        assert result.ast.program_attributes == ["COMMON", "INITIAL"]
        assert not result.ast.is_recursive

    def test_period_after_program_id_is_optional(self):
        src = _program().replace("PROGRAM-ID. T.", "PROGRAM-ID T.")
        result = _parse(src)
        assert result.warnings == []
        assert result.ast.program_name == "T"

    def test_plain_program_has_no_attributes(self):
        result = _parse(_program())
        assert result.ast.program_attributes == []
        assert result.ast.identification_division.get_metadata("unit_kind") == "PROGRAM"


class TestObjectOrientedUnits:
    CLASS = """       IDENTIFICATION DIVISION.
       CLASS-ID. ACCT INHERITS BASE.
       ENVIRONMENT DIVISION.
       CONFIGURATION SECTION.
       REPOSITORY.
           CLASS BASE IS 'java.lang.Object'.
       FACTORY.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  FACT-COUNT              PIC 9(4).
       PROCEDURE DIVISION.
       METHOD-ID. "make".
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-OUT                  OBJECT REFERENCE ACCT.
       PROCEDURE DIVISION RETURNING LK-OUT.
           INVOKE ACCT NEW RETURNING LK-OUT
           ADD 1 TO FACT-COUNT
           GOBACK.
       END METHOD "make".
       END FACTORY.
       OBJECT.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  OBJ-BAL                 PIC S9(9)V99 COMP-3.
       PROCEDURE DIVISION.
       METHOD-ID. "deposit".
       DATA DIVISION.
       LINKAGE SECTION.
       01  LK-AMT                  PIC S9(9)V99 COMP-3.
       PROCEDURE DIVISION USING BY VALUE LK-AMT.
           ADD LK-AMT TO OBJ-BAL
           GOBACK.
       END METHOD "deposit".
       END OBJECT.
       END CLASS ACCT.
"""

    def test_class_factory_object_methods_nest(self):
        result = _parse(self.CLASS, "acct.cbl")
        ast = result.ast
        assert ast.unit_kind == "CLASS" and ast.program_name == "ACCT"
        assert ast.identification_division.get_metadata("inherits") == "BASE"
        assert [(u.unit_kind, u.program_name) for u in ast.program_units()] == [
            ("CLASS", "ACCT"),
            ("FACTORY", "FACTORY"),
            ("METHOD", "make"),
            ("OBJECT", "OBJECT"),
            ("METHOD", "deposit"),
        ]
        factory, obj = ast.contained_programs
        assert [u.program_name for u in factory.contained_programs] == ["make"]
        assert [u.program_name for u in obj.contained_programs] == ["deposit"]
        assert {i.name for i in factory.get_data_items()} == {"FACT-COUNT"}
        assert {i.name for i in obj.get_data_items()} == {"OBJ-BAL"}
        make = ast.find_program_unit("make")
        assert make.procedure_division.get_metadata("returning_parameter") == "LK-OUT"
        deposit = ast.find_program_unit("deposit")
        assert deposit.procedure_division.get_metadata("using_parameters") == ["LK-AMT"]
        assert [
            w for w in result.warnings if not w.startswith("Compilation unit")
        ] == []

    def test_class_without_environment_division(self):
        src = self.CLASS.replace(
            "       ENVIRONMENT DIVISION.\n       CONFIGURATION SECTION.\n"
            "       REPOSITORY.\n           CLASS BASE IS 'java.lang.Object'.\n",
            "",
        )
        ast = _parse(src, "acct.cbl").ast
        assert [u.unit_kind for u in ast.program_units()] == [
            "CLASS",
            "FACTORY",
            "METHOD",
            "OBJECT",
            "METHOD",
        ]

    def test_method_with_its_own_identification_division_header(self):
        src = self.CLASS.replace(
            '       METHOD-ID. "deposit".',
            '       IDENTIFICATION DIVISION.\n       METHOD-ID. "deposit".',
        )
        ast = _parse(src, "acct.cbl").ast
        deposit = ast.find_program_unit("deposit")
        assert deposit is not None and deposit.unit_kind == "METHOD"
        assert deposit in ast.contained_programs[1].contained_programs

    def test_unit_kind_serialized_only_when_not_a_program(self):
        ast = _parse(self.CLASS, "acct.cbl").ast
        payload = ast.to_dict()
        assert payload["unit_kind"] == "CLASS"
        assert "unit_kind" not in _parse(_program()).ast.to_dict()

    def test_object_reference_usage(self):
        data = (
            "       01  A USAGE OBJECT REFERENCE ACCT.\n"
            "       01  B OBJECT REFERENCE.\n"
            "       01  C USAGE IS OBJECT REFERENCE FACTORY OF ACCT.\n"
        )
        result = _parse(_program(data))
        assert result.warnings == []
        assert (_item(result.ast, "A").usage, _item(result.ast, "A").object_class) == (
            "OBJECT REFERENCE",
            "ACCT",
        )
        assert _item(result.ast, "B").object_class is None
        assert _item(result.ast, "C").object_class == "ACCT"
        assert _item(result.ast, "A").to_dict()["object_class"] == "ACCT"


class TestDeclaratives:
    SRC = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. D.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F ASSIGN TO F.
       DATA DIVISION.
       FILE SECTION.
       FD  F.
       01  R                       PIC X(80).
       PROCEDURE DIVISION.
       DECLARATIVES.
       F-ERR SECTION.
           USE AFTER STANDARD ERROR PROCEDURE ON F.
       F-ERR-PARA.
           DISPLAY 'F ERROR'.
       END DECLARATIVES.
       MAIN SECTION.
       0000-MAIN.
           OPEN INPUT F
           READ F
           CLOSE F
           STOP RUN.
"""

    def test_markers_leave_no_paragraphs_and_flag_the_section(self):
        result = _parse(self.SRC, "d.cbl")
        assert result.warnings == []
        proc = result.ast.procedure_division
        assert proc.paragraphs == []
        assert {s.section_name: s.is_declarative for s in proc._sections.values()} == {
            "F-ERR": True,
            "MAIN": False,
        }
        assert proc._sections["F-ERR"].to_dict()["metadata"] == {"declarative": True}

    def test_use_before_reporting(self):
        src = self.SRC.replace(
            "           USE AFTER STANDARD ERROR PROCEDURE ON F.",
            "           USE GLOBAL BEFORE REPORTING PAGE-HEAD.",
        )
        use = _parse(src, "d.cbl").ast.find_all_by_type("UseStatement")[0]
        assert use.use_type == "REPORTING"
        assert use.is_global
        assert use.report_groups == ["PAGE-HEAD"]
        assert use.file_names == []
        assert use.to_dict()["report_groups"] == ["PAGE-HEAD"]


class TestData6x:
    def test_pic_u_sizes_in_bytes(self):
        # PIC U(n) is fixed character-length: 4 x n reserved bytes (#554).
        data = (
            "       01  A PIC U(40).\n"
            "       01  B PIC U BYTE-LENGTH 120.\n"
            "       01  C PIC U DYNAMIC LENGTH LIMIT 4000.\n"
            "       01  D PIC U DYNAMIC.\n"
        )
        result = _parse(_program(data))
        assert result.warnings == []
        ast = result.ast
        assert _item(ast, "A").picture_clause.size == 160
        assert _item(ast, "A").picture_clause.utf8_characters == 40
        assert _item(ast, "A").picture_clause.is_valid
        assert _item(ast, "B").byte_length == 120
        assert _item(ast, "B").picture_clause.size == 120
        assert _item(ast, "B").picture_clause.utf8_characters is None
        assert _item(ast, "B").to_dict()["byte_length"] == 120
        c = _item(ast, "C")
        assert c.is_dynamic_length and c.dynamic_length_limit == 4000
        assert c.to_dict()["is_dynamic_length"] is True
        assert c.to_dict()["dynamic_length_limit"] == 4000
        d = _item(ast, "D")
        assert d.is_dynamic_length and d.dynamic_length_limit is None

    def test_volatile_stops_the_picture_scan(self):
        result = _parse(_program("       01  V PIC X(8) VOLATILE.\n"))
        assert result.warnings == []
        v = _item(result.ast, "V")
        assert v.is_volatile
        assert v.picture_clause.pattern == "X(8)"
        assert v.picture_clause.size == 8
        assert v.to_dict()["is_volatile"] is True

    def test_occurs_unbounded_depending_on(self):
        data = (
            "       01  G.\n"
            "           05  N                   PIC 9(9) COMP.\n"
            "           05  ROW OCCURS UNBOUNDED DEPENDING ON N.\n"
            "               10  K               PIC X(8).\n"
        )
        result = _parse(_program(data))
        assert result.warnings == []
        occurs = _item(result.ast, "ROW").occurs_clause
        assert occurs.is_unbounded
        assert occurs.min_times == 1 and occurs.max_times is None
        assert occurs.depending_on == "N"
        assert occurs.to_dict()["is_unbounded"] is True

    def test_occurs_unbounded_count_on_next_line_stays_a_level_number(self):
        data = (
            "       01  G.\n"
            "           05  N                   PIC 9(9) COMP.\n"
            "           05  ROW OCCURS UNBOUNDED\n"
            "               DEPENDING ON N.\n"
            "               10  K               PIC X(8).\n"
            "       01  TAIL-ITEM               PIC X.\n"
        )
        ast = _parse(_program(data)).ast
        assert _item(ast, "ROW").occurs_clause.is_unbounded
        assert _item(ast, "TAIL-ITEM").level == 1

    def test_json_generate_converting(self):
        proc = (
            "           JSON GENERATE OUT FROM G\n"
            "               CONVERTING PRICE TO JSON DECIMAL\n"
            "           END-JSON\n"
            "           GOBACK.\n"
        )
        data = "       01  OUT PIC X(100).\n       01  G.\n           05  PRICE PIC 9(5).\n"
        result = _parse(_program(data, proc))
        assert result.warnings == []
        stmt = result.ast.find_all_by_type("XmlJsonStatement")[0]
        assert "CONVERTING PRICE TO JSON DECIMAL" in stmt.clause_text


class TestProcedureDivisionReturning:
    def test_returning_is_not_a_using_parameter(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. R.\n"
            "       DATA DIVISION.\n"
            "       LINKAGE SECTION.\n"
            "       01  A PIC X.\n"
            "       01  B PIC X.\n"
            "       01  RC PIC S9(4) COMP.\n"
            "       PROCEDURE DIVISION USING A BY VALUE B RETURNING RC.\n"
            "           GOBACK.\n"
        )
        proc = _parse(src, "r.cbl").ast.procedure_division
        assert proc.get_metadata("using_parameters") == ["A", "B"]
        assert proc.get_metadata("using_parameter_modes") == {
            "A": "REFERENCE",
            "B": "VALUE",
        }
        assert proc.get_metadata("returning_parameter") == "RC"


class TestSetAddressOf:
    def test_targets_flagged(self):
        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. S.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01  P USAGE POINTER.\n"
            "       LINKAGE SECTION.\n"
            "       01  LK PIC X(10).\n"
            "       PROCEDURE DIVISION.\n"
            "       A.\n"
            "           SET ADDRESS OF LK TO P\n"
            "           SET P TO ADDRESS OF LK\n"
            "           GOBACK.\n"
        )
        based, taken = _parse(src, "s.cbl").ast.find_all_by_type("SetStatement")
        assert based.targets_are_address_of and based.targets == ["LK"]
        assert not based.value_is_address_of
        assert not taken.targets_are_address_of and taken.value_is_address_of
        assert based.to_dict()["targets_are_address_of"] is True


class TestConditionalCompilationByDefault:
    def test_directives_are_applied_in_parse_cobol(self):
        head = "       >>DEFINE ENV AS 'PROD'\n       >>DEFINE MAX-ROWS AS 500\n"
        data = (
            "       >>IF ENV = 'PROD'\n"
            "       01  LIM PIC 9(3) VALUE 500.\n"
            "       >>ELSE\n"
            "       01  LIM PIC 9(3) VALUE 10.\n"
            "       >>END-IF\n"
            "       >>IF MAX-ROWS > 100\n"
            "       01  BIG PIC X.\n"
            "       >>END-IF\n"
        )
        proc = (
            "       >>EVALUATE ENV\n"
            "       >>WHEN 'TEST'\n"
            "           DISPLAY 'TEST'\n"
            "       >>WHEN OTHER\n"
            "           DISPLAY 'OTHER'\n"
            "       >>END-EVALUATE\n"
            "           GOBACK.\n"
        )
        result = parse_cobol(_program(data, proc, head), "c.cbl")
        assert result.errors == [] and result.warnings == []
        items = {i.name: i.value_clause for i in result.ast.get_data_items()}
        assert items == {"LIM": "500", "BIG": None}
        displays = [
            d.display_items for d in result.ast.find_all_by_type("DisplayStatement")
        ]
        assert displays == [['"OTHER"']]
        # Directive lines are blanked, not removed: later lines keep their numbers
        assert result.ast.find_all_by_type("DisplayStatement")[0].location.line == 21

    def test_hyphenated_define_symbol(self):
        warnings: list[str] = []
        out = preprocess_conditional_compilation(
            ">>DEFINE MAX-ROWS AS 500\n>>IF MAX-ROWS = 500\nX\n>>END-IF\n",
            warnings=warnings,
        )
        assert warnings == []
        assert out.splitlines() == ["", "", "X"]

    def test_unknown_directive_is_blanked_with_a_warning(self):
        warnings: list[str] = []
        out = preprocess_conditional_compilation(
            ">>CALLINTERFACE DYNAMIC\nDISPLAY 'X'.\n", warnings=warnings
        )
        assert out == "\nDISPLAY 'X'."
        assert any(
            "unknown compiler directive" in w and "ignored" in w for w in warnings
        )


class TestReplacePartialWord:
    def test_colon_delimited_pseudo_text_replaces_inside_a_word(self):
        src = (
            "       REPLACE ==:PFX:== BY ==WS== ==FOO== BY ==BAR==.\n"
            "           MOVE 0 TO :PFX:-ROWS FOO\n"
            "           IF :pfx:-ROWS = 0 DISPLAY ':PFX:' END-IF.\n"
            "       REPLACE OFF.\n"
        )
        out = apply_replace_statements(src)
        assert "MOVE 0 TO WS-ROWS BAR" in out
        assert "IF WS-ROWS = 0" in out
        assert "':PFX:'" in out  # a literal is never partially replaced
        assert out.count("\n") == src.count("\n")

    def test_partial_word_through_the_parser(self):
        proc = (
            "       REPLACE ==:PFX:== BY ==WS==.\n"
            "           MOVE 1 TO :PFX:-X\n"
            "       REPLACE OFF.\n"
            "           GOBACK.\n"
        )
        result = _parse(_program("       01  WS-X PIC 9.\n", proc))
        assert result.warnings == []
        move = result.ast.find_all_by_type("MoveStatement")[0]
        assert move.targets == ["WS-X"]

    def test_tag_is_replaced_every_time_it_appears_in_a_word(self):
        # Only the first occurrence used to be replaced: XX-A-:P:.
        src = "       REPLACE ==:P:== BY ==XX==.\n           MOVE :P:-A-:P: TO B.\n"
        out = apply_replace_statements(src)
        assert "MOVE XX-A-XX TO B." in out


class TestReplaceLeadingTrailing:
    """``REPLACE LEADING/TRAILING`` used to be skipped silently."""

    def test_leading_rewrites_the_start_of_each_word(self):
        src = (
            "       REPLACE LEADING ==XX-== BY ==WS-==.\n"
            "       01 XX-A PIC 9.\n"
            "           MOVE XX-A TO XX-B 'XX-LIT' AXX-C.\n"
        )
        warnings: list[str] = []
        out = apply_replace_statements(src, warnings)
        assert "01 WS-A PIC 9." in out
        assert "MOVE WS-A TO WS-B 'XX-LIT' AXX-C." in out
        assert out.count("\n") == src.count("\n")

    def test_trailing_and_plain_pairs_in_one_statement(self):
        src = (
            "       REPLACE TRAILING ==-IN== BY ==-OUT== ==FOO== BY ==BAR==.\n"
            "           MOVE REC-IN TO FOO IN-X.\n"
            "       REPLACE OFF.\n"
        )
        out = apply_replace_statements(src)
        assert "MOVE REC-OUT TO BAR IN-X." in out

    def test_leading_through_the_parser(self):
        data = (
            "       REPLACE LEADING ==XX-== BY ==WS-==.\n"
            "       01 XX-A PIC 9.\n"
            "       01 XX-B PIC 9.\n"
        )
        proc = (
            "           MOVE XX-A TO XX-B.\n       REPLACE OFF.\n           GOBACK.\n"
        )
        result = _parse(_program(data, proc))
        assert result.warnings == []
        assert {i.name for i in result.ast.get_data_items()} >= {"WS-A", "WS-B"}
        move = result.ast.find_all_by_type("MoveStatement")[0]
        assert move.targets == ["WS-B"]

    def test_unparseable_replace_warns_instead_of_vanishing(self):
        # LEADING takes a single text word, so this REPLACE is malformed.
        src = "       REPLACE LEADING ==A B== BY ==C==.\n           MOVE A B TO C.\n"
        warnings: list[str] = []
        out = apply_replace_statements(src, warnings)
        assert "MOVE A B TO C." in out
        assert any(
            "REPLACE statement could not be parsed" in w and "Line 1" in w
            for w in warnings
        ), warnings
