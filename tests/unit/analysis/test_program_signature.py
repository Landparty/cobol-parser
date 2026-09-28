"""Tests for ProgramSignatureExtractor (program_signature.py).

Covers:
- PROCEDURE DIVISION USING as the primary entry point, operand order preserved
- ENTRY statements as additional entry points, each with its own operand list
- LINKAGE declarations joined onto each operand (level/PIC/USAGE/length/group)
- Direction classification, including a group taking its fields' directions
- The two mismatches only a cross-source view can see: an operand with no
  LINKAGE declaration, and a LINKAGE record no entry point names
- unchecked being populated rather than a direction being guessed
- Report serialization shape and the call_example rendering
- One signature per program unit in a multi-PROGRAM-ID file
"""

from cobolparser.analysis.program_signature import (
    EntryPoint,
    ProgramSignature,
    ProgramSignatureExtractor,
    SignatureParameter,
    extract_signatures,
)
from cobolparser.parser import parse_cobol


def _signature(source: str) -> ProgramSignature:
    result = parse_cobol(source, filename="TEST.cbl")
    assert result.ast is not None, result.errors
    return ProgramSignatureExtractor().analyze(result.ast)


TWO_PARAM = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TEMP PIC X(10).
       LINKAGE SECTION.
       01 LK-ACCT-ID PIC X(10).
       01 LK-RESULT  PIC 9(4).
       PROCEDURE DIVISION USING LK-ACCT-ID LK-RESULT.
       MAIN-PARA.
           MOVE LK-ACCT-ID TO WS-TEMP
           MOVE 42 TO LK-RESULT
           GOBACK.
"""


class TestPrimaryEntryPoint:
    def test_procedure_division_using_is_the_primary_entry(self):
        signature = _signature(TWO_PARAM)

        assert signature.program_id == "SUBPGM"
        primary = signature.primary
        assert primary is not None
        assert primary.kind == "procedure-division"
        assert primary.name == "SUBPGM"
        assert primary.parameter_count == 2

    def test_operand_order_is_the_calling_convention_and_is_preserved(self):
        primary = _signature(TWO_PARAM).primary
        assert primary is not None

        assert [p.name for p in primary.parameters] == ["LK-ACCT-ID", "LK-RESULT"]
        assert [p.position for p in primary.parameters] == [1, 2]

    def test_call_example_renders_a_usable_call_statement(self):
        primary = _signature(TWO_PARAM).primary
        assert primary is not None

        assert primary.call_example() == 'CALL "SUBPGM" USING LK-ACCT-ID, LK-RESULT'

    def test_a_program_with_no_interface_says_so_rather_than_staying_silent(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. NOARGS.
       PROCEDURE DIVISION.
       MAIN-PARA.
           GOBACK.
""")

        assert signature.entry_points == []
        assert any("declares no calling interface" in c for c in signature.unchecked)


class TestLinkageJoin:
    def test_each_operand_carries_its_linkage_declaration(self):
        primary = _signature(TWO_PARAM).primary
        assert primary is not None
        acct = primary.parameters[0]

        assert acct.declared is True
        assert acct.level == 1
        assert acct.picture == "X(10)"
        assert acct.usage == "DISPLAY"
        assert acct.byte_length == 10
        assert acct.is_group is False
        assert acct.declaration() == "01 LK-ACCT-ID PIC X(10)"

    def test_a_group_operand_is_described_by_its_length_not_a_fake_picture(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. GRPPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TEMP PIC X(10).
       LINKAGE SECTION.
       01 LK-REC.
          05 LK-ACCT PIC X(10).
          05 LK-AMT  PIC S9(7)V99 COMP-3.
       PROCEDURE DIVISION USING LK-REC.
       MAIN-PARA.
           MOVE LK-ACCT TO WS-TEMP
           GOBACK.
""")
        primary = signature.primary
        assert primary is not None
        rec = primary.parameters[0]

        assert rec.is_group is True
        assert rec.picture is None
        # 10 alphanumeric + 5 packed bytes for the 9-digit COMP-3.
        assert rec.byte_length == 15
        assert "group item (15 bytes)" in rec.declaration()

    def test_a_non_display_usage_is_shown_in_the_declaration(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. COMPPGM.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-N PIC S9(7)V99 COMP-3.
       LINKAGE SECTION.
       01 LK-AMT PIC S9(7)V99 COMP-3.
       PROCEDURE DIVISION USING LK-AMT.
       MAIN-PARA.
           MOVE LK-AMT TO WS-N
           GOBACK.
""")
        primary = signature.primary
        assert primary is not None

        assert "COMP-3" in primary.parameters[0].declaration()


class TestDirection:
    def test_a_parameter_only_read_is_input(self):
        primary = _signature(TWO_PARAM).primary
        assert primary is not None

        assert primary.parameters[0].direction == "input"

    def test_a_parameter_only_written_is_output(self):
        primary = _signature(TWO_PARAM).primary
        assert primary is not None

        assert primary.parameters[1].direction == "output"

    def test_a_parameter_both_read_and_written_is_input_output(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. BIDIR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TEMP PIC 9(4).
       LINKAGE SECTION.
       01 LK-COUNT PIC 9(4).
       PROCEDURE DIVISION USING LK-COUNT.
       MAIN-PARA.
           MOVE LK-COUNT TO WS-TEMP
           MOVE 7 TO LK-COUNT
           GOBACK.
""")
        primary = signature.primary
        assert primary is not None

        assert primary.parameters[0].direction == "input-output"

    def test_a_group_takes_the_union_of_its_fields_directions(self):
        # The record is passed whole but referenced only through its fields:
        # one read, one written, so the record is read and written.
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. GRPDIR.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-TEMP PIC X(10).
       LINKAGE SECTION.
       01 LK-REC.
          05 LK-IN  PIC X(10).
          05 LK-OUT PIC X(10).
       PROCEDURE DIVISION USING LK-REC.
       MAIN-PARA.
           MOVE LK-IN TO WS-TEMP
           MOVE WS-TEMP TO LK-OUT
           GOBACK.
""")
        primary = signature.primary
        assert primary is not None

        assert primary.parameters[0].direction == "input-output"

    def test_an_unreferenced_operand_is_unknown_and_recorded_not_guessed(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNREF.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-NEVER PIC X(10).
       PROCEDURE DIVISION USING LK-NEVER.
       MAIN-PARA.
           GOBACK.
""")
        primary = signature.primary
        assert primary is not None

        assert primary.parameters[0].direction == "unknown"
        assert any("LK-NEVER" in c for c in signature.unchecked)


class TestMismatches:
    def test_an_operand_with_no_linkage_declaration_is_reported(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. MISSING.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-DECLARED PIC X(10).
       PROCEDURE DIVISION USING LK-DECLARED LK-GHOST.
       MAIN-PARA.
           GOBACK.
""")
        primary = signature.primary
        assert primary is not None
        ghost = primary.parameters[1]

        assert ghost.declared is False
        assert "LK-GHOST" in signature.undeclared_parameters
        assert "not declared in LINKAGE SECTION" in ghost.declaration()

    def test_a_linkage_record_no_entry_point_names_is_reported(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. EXTRA.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-USED   PIC X(10).
       01 LK-SPARE  PIC X(10).
       PROCEDURE DIVISION USING LK-USED.
       MAIN-PARA.
           GOBACK.
""")

        assert signature.unreferenced_linkage == ["LK-SPARE"]


class TestEntryStatements:
    def test_an_entry_statement_is_its_own_entry_point(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIENT.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-A PIC X(4).
       01 LK-B PIC X(4).
       PROCEDURE DIVISION USING LK-A.
       MAIN-PARA.
           GOBACK.
       ALT-PARA.
           ENTRY "ALTENT" USING LK-B.
           GOBACK.
""")

        alt = signature.entry("ALTENT")
        assert alt is not None
        assert alt.kind == "entry-statement"
        assert [p.name for p in alt.parameters] == ["LK-B"]
        assert alt.call_example() == 'CALL "ALTENT" USING LK-B'

    def test_entry_lookup_is_case_insensitive(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. CASEENT.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-A PIC X(4).
       PROCEDURE DIVISION USING LK-A.
       MAIN-PARA.
           ENTRY "ALTENT" USING LK-A.
           GOBACK.
""")

        assert signature.entry("altent") is not None
        assert signature.entry("NOSUCH") is None


class TestSerialization:
    def test_to_dict_shape(self):
        payload = _signature(TWO_PARAM).to_dict()

        assert set(payload) == {
            "program_id",
            "entry_points",
            "unreferenced_linkage",
            "undeclared_parameters",
            "unchecked",
        }
        entry = payload["entry_points"][0]
        assert set(entry) == {
            "name",
            "kind",
            "parameter_count",
            "parameters",
            "returning",
            "call_example",
            "location",
        }
        assert set(entry["parameters"][0]) == {
            "name",
            "position",
            "declared",
            "level",
            "picture",
            "usage",
            "byte_length",
            "is_group",
            "occurs",
            "direction",
            "by_clause",
            "declaration",
            "location",
        }

    def test_a_parameter_with_no_location_serializes_as_null(self):
        parameter = SignatureParameter(name="LK-X", position=1)

        assert parameter.to_dict()["location"] is None

    def test_an_entry_with_no_parameters_renders_a_bare_call(self):
        entry = EntryPoint(name="NOARGS", kind="entry-statement")

        assert entry.call_example() == 'CALL "NOARGS"'
        assert entry.to_dict()["parameter_count"] == 0


class TestMultipleProgramUnits:
    def test_one_signature_per_program_unit(self):
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTERP.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-OUT PIC X(4).
       PROCEDURE DIVISION USING LK-OUT.
       OUTER-MAIN.
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNERP.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-IN PIC X(4).
       PROCEDURE DIVISION USING LK-IN.
       INNER-MAIN.
           GOBACK.
       END PROGRAM INNERP.
       END PROGRAM OUTERP.
"""
        result = parse_cobol(source, filename="NESTED.cbl")
        assert result.ast is not None

        signatures = extract_signatures(result.ast)
        by_name = {s.program_id: s for s in signatures}

        assert "OUTERP" in by_name
        # A contained program is callable too, so it gets its own signature
        # rather than being invisible behind the outermost one.
        assert "INNERP" in by_name
        inner = by_name["INNERP"].primary
        assert inner is not None
        assert [p.name for p in inner.parameters] == ["LK-IN"]


class TestReviewFollowUps:
    """Review follow-ups on PR #212."""

    def test_returning_operand_is_not_a_fourth_using_parameter(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. BYV.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-A PIC X.
       01 LK-B PIC X.
       01 LK-RET PIC 9.
       PROCEDURE DIVISION USING LK-A LK-B RETURNING LK-RET.
       MAIN.
           MOVE LK-A TO LK-B
           MOVE 1 TO LK-RET
           GOBACK.
""")
        entry = signature.entry_points[0]
        assert [p.name for p in entry.parameters] == ["LK-A", "LK-B"]
        assert entry.returning == "LK-RET"
        assert entry.call_example() == 'CALL "BYV" USING LK-A, LK-B RETURNING LK-RET'
        assert "RETURNING" not in signature.undeclared_parameters

    def test_contained_programs_entry_is_not_the_outer_units(self):
        result = parse_cobol(
            """       IDENTIFICATION DIVISION.
       PROGRAM-ID. OUTERP.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-OUT PIC X.
       PROCEDURE DIVISION USING LK-OUT.
       MAIN.
           GOBACK.
       IDENTIFICATION DIVISION.
       PROGRAM-ID. INNERP.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-IN PIC X.
       PROCEDURE DIVISION.
       INNER-MAIN.
           ENTRY 'INNERALT' USING LK-IN
           GOBACK.
       END PROGRAM INNERP.
       END PROGRAM OUTERP.
""",
            filename="NEST.cbl",
        )
        assert result.ast is not None, result.errors
        outer = ProgramSignatureExtractor().analyze(result.ast)
        assert [e.name for e in outer.entry_points] == ["OUTERP"]
        assert outer.undeclared_parameters == []

    def test_host_variable_and_call_argument_roles_are_unknown_not_input(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. AMBIG.
       DATA DIVISION.
       LINKAGE SECTION.
       01 LK-NAME PIC X(20).
       01 LK-REC PIC X(80).
       PROCEDURE DIVISION USING LK-NAME LK-REC.
       MAIN.
           EXEC SQL SELECT NAME INTO :LK-NAME FROM T END-EXEC
           CALL 'X' USING LK-REC
           GOBACK.
""")
        directions = {p.name: p.direction for p in signature.entry_points[0].parameters}
        assert directions == {"LK-NAME": "unknown", "LK-REC": "unknown"}
        assert any("LK-NAME" in note for note in signature.unchecked)
        assert any("LK-REC" in note for note in signature.unchecked)

    def test_group_with_fields_declared_twice_is_unknown(self):
        signature = _signature("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. DUPG.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-CUST.
          05 CUST-ID PIC X(5).
       LINKAGE SECTION.
       01 LK-CUST.
          05 CUST-ID PIC X(5).
       PROCEDURE DIVISION USING LK-CUST.
       MAIN.
           MOVE 'ABC' TO CUST-ID OF WS-CUST
           GOBACK.
""")
        parameter = signature.entry_points[0].parameters[0]
        assert parameter.direction == "unknown"
        assert any("declared more than once" in note for note in signature.unchecked)


def test_accumulated_and_giving_operands_get_the_right_direction():
    # `ADD 1 TO LK-COUNT` reads the caller's value before writing it back
    # (input-output, not output); the FROM operand of `SUBTRACT ... GIVING`
    # is only read (input, not output).
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SUB.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-C PIC 9(3).\n"
        "       LINKAGE SECTION.\n"
        "       01 LK-COUNT PIC 9(3).\n"
        "       01 LK-A PIC 9(3).\n"
        "       01 LK-B PIC 9(3).\n"
        "       PROCEDURE DIVISION USING LK-COUNT LK-A LK-B.\n"
        "           ADD 1 TO LK-COUNT.\n"
        "           SUBTRACT LK-A FROM LK-B GIVING WS-C.\n"
        "           GOBACK.\n"
    )
    signature = ProgramSignatureExtractor().analyze(parse_cobol(source).ast)
    params = signature.to_dict()["entry_points"][0]["parameters"]
    assert {p["name"]: p["direction"] for p in params} == {
        "LK-COUNT": "input-output",
        "LK-A": "input",
        "LK-B": "input",
    }


BY_VALUE_ENTRY = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. E1.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC X(4).
       LINKAGE SECTION.
       01 LK-A PIC X(4).
       01 LK-B PIC S9(9) COMP-5.
       01 LK-C PIC X(4).
       01 LK-R PIC S9(4) COMP.
       PROCEDURE DIVISION USING LK-A BY VALUE LK-B BY REFERENCE LK-C
           RETURNING LK-R.
       MAIN-PARA.
           MOVE LK-A TO WS-X
           MOVE LK-B TO LK-R
           MOVE WS-X TO LK-C
           GOBACK.
       ALT-PARA.
           ENTRY 'E1ALT' USING LK-A.
           MOVE LK-A TO WS-X
           GOBACK.
"""


class TestEntryUsingAndPassingModes:
    def test_entry_using_is_not_an_ambiguous_call_argument(self):
        signature = _signature(BY_VALUE_ENTRY)

        alt = signature.entry("E1ALT")
        assert alt is not None
        assert [(p.name, p.direction) for p in alt.parameters] == [("LK-A", "input")]
        assert not any(c.startswith("LK-A:") for c in signature.unchecked)

    def test_by_clause_is_set_and_rendered_where_the_mode_changes(self):
        signature = _signature(BY_VALUE_ENTRY)

        primary = signature.primary
        assert primary is not None
        assert [p.by_clause for p in primary.parameters] == [
            "REFERENCE",
            "VALUE",
            "REFERENCE",
        ]
        assert primary.call_example() == (
            'CALL "E1" USING LK-A, BY VALUE LK-B, BY REFERENCE LK-C RETURNING LK-R'
        )
        # ENTRY's own USING phrase carries no mode: rendered bare.
        alt = signature.entry("E1ALT")
        assert alt is not None
        assert alt.parameters[0].by_clause is None
        assert alt.call_example() == 'CALL "E1ALT" USING LK-A'

    def test_returning_item_is_not_unreferenced_linkage(self):
        signature = _signature(BY_VALUE_ENTRY)

        assert "LK-R" not in signature.unreferenced_linkage
        assert signature.unreferenced_linkage == []


def test_by_content_and_by_value_call_arguments_are_input():
    # A sub-CALL BY CONTENT / BY VALUE hands the callee a copy, so the
    # parameter cannot be written back through it; only BY REFERENCE is
    # ambiguous.
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SUB.\n"
        "       DATA DIVISION.\n"
        "       LINKAGE SECTION.\n"
        "       01 LK-A PIC X(4).\n"
        "       01 LK-B PIC S9(9) COMP-5.\n"
        "       01 LK-C PIC X(4).\n"
        "       PROCEDURE DIVISION USING LK-A LK-B LK-C.\n"
        "           CALL 'OTHER' USING BY CONTENT LK-A BY VALUE LK-B\n"
        "                              BY REFERENCE LK-C.\n"
        "           GOBACK.\n"
    )
    signature = ProgramSignatureExtractor().analyze(parse_cobol(source).ast)
    params = signature.to_dict()["entry_points"][0]["parameters"]
    assert {p["name"]: p["direction"] for p in params} == {
        "LK-A": "input",
        "LK-B": "input",
        "LK-C": "unknown",
    }
    assert [note.split(":")[0] for note in signature.unchecked] == ["LK-C"]
