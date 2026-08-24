"""Regression pins for the /code-review diff-scan findings (2026-08-24).

Three verified regressions the corpus-hardening series introduced:

1. The H9 dedent guard's strict ``col < reference_column`` never treated a
   paragraph header at the SAME column as the statement's verb as a
   boundary, silently swallowing the next paragraph out of the AST (real
   decks do write statements flush in Area A alongside their headers).
2. ``parse_arithmetic_operands`` (ADD/SUBTRACT addend lists) dropped a
   unary MINUS via its fall-through consume, recording a sign-inverted
   operand -- while MULTIPLY/DIVIDE/SET/PERFORM recomposed it via the
   shared ``consume_signed_numeric``.
3. ``strip_sequence_area``'s short-line tag-blanking excluded only
   EJECT/SKIP1-3, so a flush-left ``GOBACK``/``EXIT``/``STOP`` line (a
   sub-7-character reserved word with its period elsewhere) was silently
   deleted during copybook expansion.
"""

from cobolparser import parse_cobol
from cobolparser.preprocess.copy_statement_parser import strip_sequence_area


class TestSameColumnParagraphBoundary:
    SOURCE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. AREAA.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC X.
       01  WS-B PIC X.
       PROCEDURE DIVISION.
       MAIN-PARA.
       MOVE WS-A TO WS-B
       NEXT-PARA.
       DISPLAY WS-A.
"""

    def test_header_at_verb_column_is_a_boundary_not_an_operand(self):
        result = parse_cobol(self.SOURCE, filename="AREAA.cbl")
        assert result.success, result.errors
        paras = {
            p.paragraph_name: [type(s).__name__ for s in p.statements]
            for p in result.ast.traverse_depth_first()
            if type(p).__name__ == "CobolParagraph"
        }
        assert paras == {
            "MAIN-PARA": ["MoveStatement"],
            "NEXT-PARA": ["DisplayStatement"],
        }
        moves = result.ast.find_all_by_type("MoveStatement")
        assert moves[0].targets == ["WS-B"]
        # The truncation is never silent: the missing-period warning fires.
        assert any("NEXT-PARA" in w for w in result.warnings)


class TestSignedArithmeticAddends:
    def test_add_and_subtract_keep_the_unary_sign(self):
        result = parse_cobol("""       IDENTIFICATION DIVISION.
       PROGRAM-ID. SGN.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-X PIC S9(4) VALUE 5.
       PROCEDURE DIVISION.
       M.
           ADD -1 TO WS-X
           SUBTRACT -2 FROM WS-X
           MULTIPLY -3 BY WS-X
           STOP RUN.
""")
        assert result.success, result.errors
        (add,) = result.ast.find_all_by_type("AddStatement")
        (sub,) = result.ast.find_all_by_type("SubtractStatement")
        (mul,) = result.ast.find_all_by_type("MultiplyStatement")
        assert add.operands[0] == "-1"
        assert sub.operands[0] == "-2"
        assert mul.operands[0] == "-3"


class TestShortReservedWordLinesSurviveStripSequenceArea:
    def test_flush_left_short_verbs_pass_through(self):
        for verb in ("GOBACK", "EXIT", "STOP", "MOVE"):
            assert strip_sequence_area(verb) == verb, verb

    def test_change_tags_still_blanked(self):
        for tag in ("P2P", "M1005", "E1A"):
            assert strip_sequence_area(tag) == "", tag
