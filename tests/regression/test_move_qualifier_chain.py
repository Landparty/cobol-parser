"""Regression coverage for MOVE targets dropping a qualified target's
``OF``/``IN`` chain.

Found via a `/code-review` pass on the ADD/SUBTRACT/MULTIPLY/DIVIDE
qualifier-chain fix (see ``test_arithmetic_qualifier_chain.py`` and
``.okf/parser.md``): MOVE's target-collection loop only folded a trailing
``(subscript)`` group into a target via ``consume_optional_subscript``, the
same narrower helper the arithmetic verbs used before that fix, and had no
``OF``/``IN`` handling at all. A qualified MOVE target like ``MOVE X TO
QUAL OF GROUP-A`` fell into the loop's generic "skip anything unrecognized"
branch for the ``OF`` token, and the qualifier name (``GROUP-A``) then
looped back around and was collected as a spurious *separate* target
instead of completing the qualified one -- the identical bug class
``consume_optional_qualifiers`` was built to fix for the arithmetic verbs,
left live one file over. Fixed by wiring MOVE's target loop to the same
shared ``consume_optional_qualifiers`` helper (``_utils.py``).
"""

from cobolparser import parse_cobol


def _parse(source: str):
    result = parse_cobol(source, filename="movequaltest.cbl")
    assert result.success, result.errors
    return result


class TestMoveTargetQualifierChain:
    def test_single_of_qualifier_on_target(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVEQUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 QUAL PIC 9(3).
       01 GROUP-B.
          05 QUAL PIC 9(3).
       01 X PIC 9(3).
       PROCEDURE DIVISION.
           MOVE X TO QUAL OF GROUP-A.
           STOP RUN.
"""
        result = _parse(source)
        mv = result.ast.find_all_by_type("MoveStatement")[0]
        assert mv.targets == ["QUAL OF GROUP-A"]

    def test_multiple_qualified_targets(self):
        # A MOVE may name several targets; each is independently qualified
        # and must not be conflated with -- or absorb tokens from -- its
        # neighbor.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTIMOVEQUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 QUAL PIC 9(3).
       01 GROUP-B.
          05 QUAL PIC 9(3).
       01 X PIC 9(3).
       PROCEDURE DIVISION.
           MOVE X TO QUAL OF GROUP-A, QUAL OF GROUP-B.
           STOP RUN.
"""
        result = _parse(source)
        mv = result.ast.find_all_by_type("MoveStatement")[0]
        assert mv.targets == ["QUAL OF GROUP-A", "QUAL OF GROUP-B"]

    def test_qualifier_chain_split_across_continuation_line(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVEMULTILINEQUAL.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 COS100ID-01.
          05 COS100ID-CMBAPA.
             10 COS100ID-CMBAPA-PA PIC 9(3).
       01 WS000-P-1 PIC 9(3).
       PROCEDURE DIVISION.
           MOVE WS000-P-1 TO COS100ID-CMBAPA-PA
               OF COS100ID-CMBAPA
               OF COS100ID-01.
           STOP RUN.
"""
        result = _parse(source)
        mv = result.ast.find_all_by_type("MoveStatement")[0]
        assert mv.targets == ["COS100ID-CMBAPA-PA OF COS100ID-CMBAPA OF COS100ID-01"]

    def test_subscripted_target_still_folds_correctly(self):
        # Not new behavior, but a guard against the refactor regressing the
        # pre-existing subscript-folding MOVE targets already relied on.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MOVESUBSCRIPTTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TBL PIC 9(3) OCCURS 3 TIMES.
       01 X PIC 9(3).
       PROCEDURE DIVISION.
           MOVE X TO TBL (2).
           STOP RUN.
"""
        result = _parse(source)
        mv = result.ast.find_all_by_type("MoveStatement")[0]
        assert mv.targets == ["TBL ( 2 )"]
