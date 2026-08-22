"""Regression coverage for ADD/SUBTRACT/MULTIPLY/DIVIDE dropping a
qualified operand or target's ``OF``/``IN`` chain.

Found via a real corpus retry: ``ADD WS000-P-1 TO COS100ID-CMBAPA-PA``
continued on the next physical line with ``OF COS100ID-CMBAPA OF
COS100ID-01`` -- an ordinary qualifier chain wrapped onto a continuation
line, not a compiler-directing continuation. ``_consume_arithmetic_target``
(backs ADD's ``TO``/SUBTRACT's ``FROM`` target) never consumed a trailing
``OF``/``IN`` qualifier chain at all, leaving it unconsumed in the token
stream for whatever ran next to misinterpret.
``_consume_arithmetic_operand`` (backs MULTIPLY/DIVIDE's operands) had a
related but different bug: it consumed the qualifier chain from the token
stream but never folded it into the returned string, so the qualification
was silently dropped from the AST. Both are fixed by a shared
``consume_optional_qualifiers`` helper (``_utils.py``) that folds an
optional ``(subscript)`` group and/or an ``OF``/``IN`` chain -- of any
length, each hop optionally itself followed by a subscript, and tolerant
of a chain split across a continuation line -- into the caller's result
string.
"""

from cobolparser import parse_cobol


def _parse(source: str):
    result = parse_cobol(source, filename="qualtest.cbl")
    assert result.success, result.errors
    return result


class TestAddTargetQualifierChain:
    def test_single_of_qualifier_on_target(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. QUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 QUAL PIC 9(3).
       01 GROUP-B.
          05 QUAL PIC 9(3).
       PROCEDURE DIVISION.
           ADD 1 TO QUAL OF GROUP-A.
           STOP RUN.
"""
        result = _parse(source)
        add = result.ast.find_all_by_type("AddStatement")[0]
        assert add.target == "QUAL OF GROUP-A"
        assert add.operands == ["1", "QUAL OF GROUP-A"]

    def test_multi_hop_qualifier_chain_split_across_continuation_line(self):
        # Reconstructs the corpus repro shape: a two-hop OF chain wrapped
        # onto its own continuation line, ordinary free-form COBOL layout.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULTILINEQ.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 COS100ID-01.
          05 COS100ID-CMBAPA.
             10 COS100ID-CMBAPA-PA PIC 9(3).
       01 WS000-P-1 PIC 9(3).
       PROCEDURE DIVISION.
           ADD WS000-P-1 TO COS100ID-CMBAPA-PA
               OF COS100ID-CMBAPA
               OF COS100ID-01.
           STOP RUN.
"""
        result = _parse(source)
        add = result.ast.find_all_by_type("AddStatement")[0]
        assert add.target == "COS100ID-CMBAPA-PA OF COS100ID-CMBAPA OF COS100ID-01"

    def test_subtract_from_target_qualifier_chain(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBQUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 QUAL PIC 9(3).
       PROCEDURE DIVISION.
           SUBTRACT 1 FROM QUAL OF GROUP-A.
           STOP RUN.
"""
        result = _parse(source)
        sub = result.ast.find_all_by_type("SubtractStatement")[0]
        assert sub.target == "QUAL OF GROUP-A"


class TestMultiplyDivideOperandQualifierChain:
    def test_multiply_by_qualified_operand(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MULQUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 QUAL PIC 9(3).
       01 RESULT-FIELD PIC 9(3).
       PROCEDURE DIVISION.
           MULTIPLY QUAL OF GROUP-A BY 2 GIVING RESULT-FIELD.
           STOP RUN.
"""
        result = _parse(source)
        mul = result.ast.find_all_by_type("MultiplyStatement")[0]
        assert mul.operands[0] == "QUAL OF GROUP-A"

    def test_divide_qualified_operand_with_subscript_after_qualifier(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DIVQUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 QUAL-TBL PIC 9(3) OCCURS 3 TIMES.
       01 IDX PIC 9 VALUE 1.
       01 RESULT-FIELD PIC 9(3).
       PROCEDURE DIVISION.
           DIVIDE QUAL-TBL OF GROUP-A (IDX) BY 2 GIVING RESULT-FIELD.
           STOP RUN.
"""
        result = _parse(source)
        div = result.ast.find_all_by_type("DivideStatement")[0]
        assert div.operands[0] == "QUAL-TBL OF GROUP-A ( IDX )"
