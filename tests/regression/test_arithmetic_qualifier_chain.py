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

A `/code-review` pass on the fix caught two more call sites sharing the
same target/operand-consuming responsibility that were left unfixed:
``consume_keyword_and_operand`` (backs the ``GIVING`` clause shared by all
four verbs and DIVIDE's ``REMAINDER`` clause) still called only
``consume_optional_subscript``, and ``parse_arithmetic_operands`` (ADD's/
SUBTRACT's addend list before ``TO``/``FROM``) didn't fold a qualifier
chain into an addend at all -- it silently skipped the ``OF``/``IN``
keyword and appended the qualifier name as a spurious *separate* addend
(``ADD QUAL OF GROUP-A TO ...`` produced two addends, ``"QUAL"`` and
``"GROUP-A"``, instead of one qualified ``"QUAL OF GROUP-A"``). Both are
now wired to the same shared helper.

Further review passes on malformed (not well-formed) input found two more
issues in ``consume_optional_qualifiers``/``consume_optional_subscript``
themselves, both fixed here: (1) a dangling ``OF``/``IN`` with no
identifier following it was consumed and discarded unconditionally before
checking whether an identifier actually followed -- fixed by confirming an
identifier is present via non-destructive lookahead *before* consuming the
keyword, so a malformed qualifier leaves ``OF``/``IN`` untouched in the
stream instead of vanishing with no trace; (2) an unbalanced ``(`` in a
subscript (e.g. a typo dropping the closing paren) had no bound other than
end-of-stream, so it could run past the current statement's own period and
devour every following statement looking for a ``)`` that was never there
-- fixed by stopping the paren-depth loop at the first token that can never
legally appear inside a subscript (a period, scope terminator, or real
statement/control-flow keyword).
"""

from cobolparser import ErrorRecoveryMode, parse_cobol


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

    def test_divide_qualified_operand_with_subscript_before_qualifier(self):
        # Per COBOL's qualified-reference grammar (data-name [(subscript)]
        # [OF/IN data-name-2]...), a subscript binds to the identifier it
        # immediately trails -- so subscripting QUAL-TBL (the table) means
        # the subscript comes *before* the OF, not after: QUAL-TBL (IDX)
        # OF GROUP-A, not QUAL-TBL OF GROUP-A (IDX) (which would subscript
        # GROUP-A, not a table here).
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
           DIVIDE QUAL-TBL (IDX) OF GROUP-A BY 2 GIVING RESULT-FIELD.
           STOP RUN.
"""
        result = _parse(source)
        div = result.ast.find_all_by_type("DivideStatement")[0]
        assert div.operands[0] == "QUAL-TBL ( IDX ) OF GROUP-A"


class TestGivingAndRemainderQualifierChain:
    """``GIVING``/``REMAINDER`` route through the shared
    ``consume_keyword_and_operand`` helper -- a distinct call site from the
    TO/FROM targets and BY/INTO operands covered above, and one a
    /code-review pass on the original fix caught still dropping the
    qualifier chain (it called ``consume_optional_subscript`` directly
    instead of the new ``consume_optional_qualifiers``)."""

    def test_add_giving_qualifier_chain(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. GIVQUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 RESULT-F PIC 9(3).
       01 X PIC 9(3).
       01 Y PIC 9(3).
       PROCEDURE DIVISION.
           ADD X TO Y GIVING RESULT-F OF GROUP-A.
           STOP RUN.
"""
        result = _parse(source)
        add = result.ast.find_all_by_type("AddStatement")[0]
        assert add.giving == "RESULT-F OF GROUP-A"

    def test_divide_remainder_qualifier_chain(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. REMQUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 REM-F PIC 9(3).
       01 X PIC 9(3).
       01 Y PIC 9(3).
       01 Z PIC 9(3).
       PROCEDURE DIVISION.
           DIVIDE X INTO Y GIVING Z REMAINDER REM-F OF GROUP-A.
           STOP RUN.
"""
        result = _parse(source)
        div = result.ast.find_all_by_type("DivideStatement")[0]
        assert div.remainder == "REM-F OF GROUP-A"


class TestAddendListQualifierChain:
    """``parse_arithmetic_operands`` (ADD's/SUBTRACT's leading addend list
    before TO/FROM) is a third, distinct call site: unlike the target/
    operand helpers above, it didn't just drop a qualifier chain -- it
    split a qualified addend into two spurious separate addends (``ADD
    QUAL OF GROUP-A TO ...`` produced addends ``"QUAL"`` and ``"GROUP-A"``,
    since the ``OF`` token was silently skipped and the qualifier name
    tokenized as if it were its own addend)."""

    def test_add_addend_qualifier_chain(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. ADDENDQUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 QUAL PIC 9(3).
       01 GROUP-B.
          05 QUAL PIC 9(3).
       PROCEDURE DIVISION.
           ADD QUAL OF GROUP-B TO QUAL OF GROUP-A.
           STOP RUN.
"""
        result = _parse(source)
        add = result.ast.find_all_by_type("AddStatement")[0]
        assert add.operands == ["QUAL OF GROUP-B", "QUAL OF GROUP-A"]

    def test_subtract_addend_qualifier_chain(self):
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SUBADDENDQUALTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 GROUP-A.
          05 QUAL PIC 9(3).
       01 GROUP-B.
          05 QUAL PIC 9(3).
       PROCEDURE DIVISION.
           SUBTRACT QUAL OF GROUP-B FROM QUAL OF GROUP-A.
           STOP RUN.
"""
        result = _parse(source)
        sub = result.ast.find_all_by_type("SubtractStatement")[0]
        assert sub.operands == ["QUAL OF GROUP-B", "QUAL OF GROUP-A"]


class TestMalformedQualifierChainInput:
    """``consume_optional_qualifiers``/``consume_optional_subscript`` must
    stay well-behaved on malformed (not just well-formed) input: a dangling
    ``OF``/``IN`` with nothing valid after it, and an unbalanced ``(`` that
    never closes."""

    def test_target_side_dangling_of_leaves_token_unconsumed_not_corrupted(self):
        # 'OF 5' is malformed (OF must be followed by a data-name, not a
        # numeric literal). consume_optional_qualifiers must not consume
        # the OF token speculatively and then discard it -- the target
        # itself must come back as the clean base value, not a string
        # corrupted by a half-folded qualifier.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. DANGLEOFTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 Y PIC 9(3).
       PROCEDURE DIVISION.
           ADD 1 TO Y OF 5.
           STOP RUN.
"""
        result = parse_cobol(source, filename="dangleoftest.cbl")
        add = result.ast.find_all_by_type("AddStatement")[0]
        assert add.target == "Y"

    def test_unbalanced_paren_does_not_devour_following_statements(self):
        # A missing ')' in a subscript must not run past the malformed
        # statement's own period hunting for a close paren that was never
        # there -- STOP RUN must survive in the AST even though the ADD
        # itself fails to parse.
        source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. UNBALPARENTEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 TBL PIC 9(3) OCCURS 3 TIMES.
       01 IDX PIC 9 VALUE 1.
       01 C PIC 9(3).
       PROCEDURE DIVISION.
           ADD TBL (IDX TO C.
           STOP RUN.
"""
        result = parse_cobol(
            source,
            filename="unbalparentest.cbl",
            error_recovery=ErrorRecoveryMode.COLLECT_ALL,
        )
        assert len(result.ast.find_all_by_type("StopStatement")) == 1
