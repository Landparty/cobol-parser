"""Bug hunt round 10: PROCEDURE DIVISION statement parsers.

Each test pins one defect found by parsing a small, valid IBM Enterprise
COBOL program and reading the AST back:

* ``ROUNDED MODE IS mode`` stranded ``MODE`` in the stream (targets, SIZE
  ERROR handlers and COMPUTE's ``=`` lost).
* ``STOP RUN RETURNING 8`` / ``STOP 12``: a 1-49 literal lexes as
  LEVEL_NUMBER, was left behind, and ``8.`` became a phantom paragraph that
  took the rest of the real one with it.
* ``WRITE``/``REWRITE ... FROM`` a numeric literal or figurative constant.
* A statement nested in another's handler swallowed the enclosing
  statement's ``NOT AT END`` / ``NOT ON EXCEPTION`` / ``NOT INVALID KEY``.
* ``EVALUATE ... WHEN NOT 1 THRU 5`` recorded as the range ``"NOT 1"..5``.
* Qualified operands: ``PERFORM c OF g TIMES``, ``CALL ... RETURNING x OF
  g``, ``SEARCH t OF g VARYING i OF g``.
* ``SEARCH ... WHEN c stmt.`` did not end at the sentence period and folded
  every later statement of the paragraph into the WHEN body.
"""

from __future__ import annotations

from cobolparser import parse_cobol


def _parse(body: str):
    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. R10STMT.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 A PIC 9(4).\n"
        "       PROCEDURE DIVISION.\n"
        "       P1.\n" + body + "           STOP RUN.\n"
    )
    result = parse_cobol(source, filename="r10.cbl")
    assert result.errors == [], [str(e) for e in result.errors]
    return result


def _paragraphs(result) -> list:
    return list(result.ast.get_procedures())


def _statements(result) -> list:
    (paragraph,) = _paragraphs(result)
    return list(paragraph.statements)


def _types(statements) -> list[str]:
    return [s.statement_type for s in statements or []]


# -- ROUNDED MODE ---------------------------------------------------------------


def test_rounded_mode_keeps_later_targets_and_handlers():
    result = _parse(
        "           ADD A TO B ROUNDED MODE IS AWAY-FROM-ZERO C\n"
        "               ON SIZE ERROR DISPLAY 'E'\n"
        "           END-ADD.\n"
        "           COMPUTE X ROUNDED MODE NEAREST-EVEN Y = 1 / 3.\n"
        "           DIVIDE A BY 2 GIVING D ROUNDED MODE TRUNCATION.\n"
    )
    assert result.warnings == []
    add, compute, divide, _stop = _statements(result)
    assert add.targets == ["B", "C"]
    assert add.rounded is True
    assert _types(add.on_size_error) == ["DISPLAY"]
    assert compute.targets == ["X", "Y"]
    assert compute.expression == "1 / 3"
    assert divide.givings == ["D"]
    assert divide.rounded is True


# -- STOP with a level-number-shaped literal ------------------------------------


def test_stop_run_returning_small_integer_is_not_a_paragraph():
    result = _parse(
        "           STOP RUN RETURNING 8.\n"
        "           CONTINUE.\n"
        "           STOP 12.\n"
        "           CONTINUE.\n"
    )
    paragraphs = _paragraphs(result)
    assert len(paragraphs) == 1
    stop_rc, _c1, stop_lit, _c2, _stop = paragraphs[0].statements
    assert stop_rc.stop_type == "RUN"
    assert stop_rc.returning == "8"
    assert stop_lit.stop_type == "12"


# -- WRITE / REWRITE FROM a literal ------------------------------------------------


def test_write_and_rewrite_from_literals_and_figuratives():
    result = _parse(
        "           WRITE R1 FROM SPACES AFTER ADVANCING 1 LINE.\n"
        "           REWRITE R1 FROM ALL '*'.\n"
        "           WRITE R1 FROM 12.\n"
        "           REWRITE R1 FROM 'ABC'.\n"
        "           DISPLAY 'AFTER'.\n"
    )
    assert result.warnings == []
    assert len(_paragraphs(result)) == 1
    w1, rw1, w2, rw2, display, _stop = _statements(result)
    assert w1.from_clause == "SPACES"
    assert w1.advancing_mode == "AFTER"
    assert rw1.from_clause == 'ALL "*"'
    assert w2.from_clause == "12"
    # quoted, so it cannot be mistaken for a data name ABC
    assert rw2.from_clause == '"ABC"'
    assert display.statement_type == "DISPLAY"


# -- enclosing handler phrases ----------------------------------------------------


def test_string_in_at_end_leaves_not_at_end_to_the_read():
    result = _parse(
        "           READ F1\n"
        "               AT END\n"
        "                   STRING A DELIMITED BY SIZE INTO B\n"
        "               NOT AT END\n"
        "                   MOVE 1 TO B\n"
        "           END-READ.\n"
    )
    read, _stop = _statements(result)
    assert _types(read.at_end_clause) == ["STRING"]
    assert read.at_end_clause[0].operands == ["A"]
    assert _types(read.not_at_end_clause) == ["MOVE"]


def test_unstring_in_on_exception_leaves_not_on_exception_to_the_call():
    result = _parse(
        "           CALL 'X'\n"
        "               ON EXCEPTION\n"
        "                   UNSTRING A DELIMITED BY ',' INTO B C\n"
        "               NOT ON EXCEPTION\n"
        "                   MOVE 1 TO B\n"
        "           END-CALL.\n"
    )
    call, _stop = _statements(result)
    assert _types(call.on_exception) == ["UNSTRING"]
    assert _types(call.not_on_exception) == ["MOVE"]


def test_string_own_overflow_phrases_still_parse():
    result = _parse(
        "           STRING A DELIMITED SIZE INTO B\n"
        "               ON OVERFLOW DISPLAY 'O'\n"
        "               NOT ON OVERFLOW DISPLAY 'N'\n"
        "           END-STRING.\n"
    )
    string, _stop = _statements(result)
    assert _types(string.on_overflow) == ["DISPLAY"]
    assert _types(string.not_on_overflow) == ["DISPLAY"]


def test_io_statement_in_call_handler_keeps_both_handlers():
    result = _parse(
        "           CALL 'Z'\n"
        "               ON EXCEPTION\n"
        "                   READ F3\n"
        "               NOT ON EXCEPTION\n"
        "                   DISPLAY 'OK'\n"
        "           END-CALL.\n"
        "           CALL 'Z'\n"
        "               ON EXCEPTION\n"
        "                   DELETE F3\n"
        "               NOT ON EXCEPTION\n"
        "                   DISPLAY 'OK'\n"
        "           END-CALL.\n"
    )
    read_call, delete_call, _stop = _statements(result)
    # the READ used to vanish: the CALL re-read ON EXCEPTION over it
    assert _types(read_call.on_exception) == ["READ"]
    assert _types(read_call.not_on_exception) == ["DISPLAY"]
    assert _types(delete_call.on_exception) == ["DELETE_STATEMENT"]
    assert _types(delete_call.not_on_exception) == ["DISPLAY"]


def test_write_in_at_end_is_not_given_the_reads_not_at_end():
    result = _parse(
        "           READ F1\n"
        "               AT END\n"
        "                   WRITE R1\n"
        "               NOT AT END\n"
        "                   DISPLAY 'NAE'\n"
        "           END-READ.\n"
        "           WRITE R1 AT EOP DISPLAY 'P'\n"
        "               NOT AT END-OF-PAGE DISPLAY 'Q'\n"
        "           END-WRITE.\n"
    )
    read, write, _stop = _statements(result)
    (inner_write,) = read.at_end_clause
    assert not inner_write.not_at_eop_clause
    assert _types(read.not_at_end_clause) == ["DISPLAY"]
    assert _types(write.at_eop_clause) == ["DISPLAY"]
    assert _types(write.not_at_eop_clause) == ["DISPLAY"]


def test_phrase_less_statements_stop_at_enclosing_not_phrase():
    nested = [
        "INSPECT A TALLYING C FOR ALL 'X'",
        "PERFORM P2 UNTIL A = 1",
        "SORT T ASCENDING K",
        "JSON GENERATE A FROM B",
    ]
    handlers = [
        ("READ F1", "AT END", "NOT AT END", "END-READ", "at_end_clause"),
        ("CALL 'Z'", "ON EXCEPTION", "NOT ON EXCEPTION", "END-CALL", "on_exception"),
        (
            "ADD 1 TO Q",
            "ON SIZE ERROR",
            "NOT ON SIZE ERROR",
            "END-ADD",
            "on_size_error",
        ),
    ]
    for inner in nested:
        for outer, phrase, not_phrase, end, attr in handlers:
            result = _parse(
                f"           {outer}\n"
                f"               {phrase}\n"
                f"                   {inner}\n"
                f"               {not_phrase}\n"
                "                   DISPLAY 'NEG'\n"
                f"           {end}.\n"
            )
            statement, _stop = _statements(result)
            assert len(getattr(statement, attr)) == 1, (inner, outer)
            not_attr = "not_" + attr
            assert _types(getattr(statement, not_attr)) == ["DISPLAY"], (inner, outer)


def test_perform_until_condition_does_not_absorb_not_at_end():
    result = _parse(
        "           READ F1 AT END\n"
        "                   PERFORM P2 UNTIL A = 1\n"
        "               NOT AT END\n"
        "                   DISPLAY 1\n"
        "           END-READ.\n"
    )
    read, _stop = _statements(result)
    (perform,) = read.at_end_clause
    assert perform.until_condition.operands == ["A = 1"]


def test_return_in_invalid_key_leaves_not_invalid_key_to_the_read():
    result = _parse(
        "           READ F1 KEY IS K\n"
        "               INVALID KEY\n"
        "                   RETURN SF\n"
        "               NOT INVALID KEY\n"
        "                   DISPLAY 'V'\n"
        "           END-READ.\n"
    )
    read, _stop = _statements(result)
    assert _types(read.invalid_key_clause) == ["RETURN"]
    assert _types(read.not_invalid_key_clause) == ["DISPLAY"]


# -- EVALUATE WHEN NOT x THRU y --------------------------------------------------


def test_negated_range_selector_is_not_a_plain_range():
    result = _parse(
        "           EVALUATE A\n"
        "               WHEN NOT 1 THRU 5\n"
        "                   DISPLAY 'OUT'\n"
        "               WHEN 1 THRU 5\n"
        "                   DISPLAY 'IN'\n"
        "           END-EVALUATE.\n"
    )
    evaluate, _stop = _statements(result)
    negated, plain = (clause.selectors for clause in evaluate.when_clauses)
    assert negated == [
        {
            "type": "Condition",
            "text": "NOT 1 THRU 5",
            "negated": True,
            "start": "1",
            "end": "5",
        }
    ]
    assert plain == [{"type": "Range", "start": "1", "end": "5"}]


# -- qualified operands -------------------------------------------------------------


def test_perform_times_with_qualified_count():
    result = _parse(
        "           PERFORM P2 WS-CNT OF GRP TIMES.\n"
        "           PERFORM WS-CNT OF GRP TIMES\n"
        "               DISPLAY 'Q'\n"
        "           END-PERFORM.\n"
    )
    assert result.warnings == []
    out_of_line, inline, _stop = _statements(result)
    assert out_of_line.target_paragraph == "P2"
    assert out_of_line.perform_type == "TIMES"
    assert out_of_line.times_count == "WS-CNT OF GRP"
    assert inline.target_paragraph is None
    assert inline.times_count == "WS-CNT OF GRP"
    assert _types(inline.inline_statements) == ["DISPLAY"]


def test_call_returning_qualified_item():
    result = _parse(
        "           CALL 'SUB' USING A RETURNING WS-RC OF GRP\n"
        "               ON EXCEPTION DISPLAY 'X'\n"
        "           END-CALL.\n"
    )
    assert result.warnings == []
    call, _stop = _statements(result)
    assert call.returning_parameter == "WS-RC OF GRP"
    assert _types(call.on_exception) == ["DISPLAY"]


def test_search_qualified_table_and_varying_index():
    result = _parse(
        "           SEARCH T OF G VARYING IX OF G2\n"
        "               AT END DISPLAY 1\n"
        "               WHEN K (IX) = 1 DISPLAY 2\n"
        "           END-SEARCH.\n"
    )
    assert result.warnings == []
    search, _stop = _statements(result)
    assert search.table_name == "T OF G"
    assert search.varying_variable == "IX OF G2"
    assert _types(search.at_end_clause) == ["DISPLAY"]
    assert len(search.when_clauses) == 1


# -- SEARCH ends at the sentence period -------------------------------------------


def test_search_when_body_ends_at_sentence_period():
    result = _parse(
        "           SEARCH T AT END DISPLAY 1\n"
        "               WHEN K (IX) = 1 DISPLAY 2.\n"
        "           DISPLAY 3.\n"
        "           SEARCH T AT END DISPLAY 4.\n"
        "           DISPLAY 5.\n"
    )
    statements = _statements(result)
    assert _types(statements) == ["SEARCH", "DISPLAY", "SEARCH", "DISPLAY", "STOP"]
    first, _d3, second, _d5, _stop = statements
    (when,) = first.when_clauses
    assert _types(when["statements"]) == ["DISPLAY"]
    assert _types(second.at_end_clause) == ["DISPLAY"]
