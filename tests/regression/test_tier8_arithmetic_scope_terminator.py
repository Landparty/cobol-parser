"""Regression tests for the arithmetic explicit-scope-terminator phantom-
paragraph fix.

``END-ADD``/``END-SUBTRACT``/``END-MULTIPLY``/``END-DIVIDE``/``END-COMPUTE``
have no dedicated ``TokenType`` (unlike ``END-IF``/``END-PERFORM``/
``END-EVALUATE``) -- they lex as plain ``IDENTIFIER`` tokens, distinguished
only by value via ``SCOPE_TERMINATORS``. The arithmetic statement parsers
(ADD/SUBTRACT/MULTIPLY/DIVIDE/COMPUTE) correctly stopped their operand and
expression collection loops at these terminators so they weren't swallowed
into the statement, but never went on to *consume* them: ``parse_size_error_
clauses()`` only handled ``ON``/``NOT ON SIZE ERROR`` and a bare period,
falling through to an unconditional ``break`` on anything else -- including
the statement's own explicit terminator.

Left in the token stream, the terminator (an ``IDENTIFIER`` immediately
followed by a period) was then misread by the procedure division's
paragraph-boundary lookahead as the start of a *new* paragraph, silently
reparenting every statement that followed it under a bogus paragraph named
e.g. ``END-ADD`` instead of the enclosing paragraph.
"""

from cobolparser import CobolParser, ErrorRecoveryMode

PROC_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-X PIC 9(4).
       01 WS-Y PIC 9(4).
       01 WS-Z PIC 9(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
{proc}
       NEXT-PARA.
           DISPLAY 'DONE'.
"""


def _parse_proc(proc: str, mode: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL):
    source = PROC_TEMPLATE.format(proc=proc)
    return CobolParser(error_recovery=mode).parse(source, filename="probe.cbl")


def _paragraph_names(result) -> list[str]:
    return [
        p.to_dict().get("paragraph_name")
        for p in result.ast.find_all_by_type("CobolParagraph")
    ]


class TestArithmeticExplicitScopeTerminators:
    def test_add_end_add_does_not_create_phantom_paragraph(self):
        result = _parse_proc(
            "           ADD 1 TO WS-X\n           END-ADD.\n           DISPLAY WS-X."
        )
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]
        assert len(result.ast.find_all_by_type("DisplayStatement")) == 2

    def test_subtract_end_subtract_does_not_create_phantom_paragraph(self):
        result = _parse_proc(
            "           SUBTRACT 1 FROM WS-X\n"
            "           END-SUBTRACT.\n"
            "           DISPLAY WS-X."
        )
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]

    def test_multiply_end_multiply_does_not_create_phantom_paragraph(self):
        result = _parse_proc(
            "           MULTIPLY WS-X BY 2 GIVING WS-Y\n"
            "           END-MULTIPLY.\n"
            "           DISPLAY WS-Y."
        )
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]

    def test_divide_end_divide_does_not_create_phantom_paragraph(self):
        result = _parse_proc(
            "           DIVIDE WS-Y BY 2 GIVING WS-Z\n"
            "           END-DIVIDE.\n"
            "           DISPLAY WS-Z."
        )
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]

    def test_compute_end_compute_does_not_create_phantom_paragraph(self):
        result = _parse_proc(
            "           COMPUTE WS-Z = WS-X + WS-Y\n"
            "           END-COMPUTE.\n"
            "           DISPLAY WS-Z."
        )
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]

    def test_end_add_without_trailing_period_is_also_consumed(self):
        # END-ADD is a valid statement terminator in its own right -- a
        # trailing period is optional COBOL style, not mandatory.
        result = _parse_proc(
            "           ADD 1 TO WS-X\n"
            "           END-ADD\n"
            "           DISPLAY WS-X."
        )
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]

    def test_on_size_error_clause_followed_by_end_add_is_consumed(self):
        result = _parse_proc(
            "           ADD 1 TO WS-X\n"
            "               ON SIZE ERROR DISPLAY 'ERR'\n"
            "           END-ADD.\n"
            "           DISPLAY WS-X."
        )
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]
        adds = result.ast.find_all_by_type("AddStatement")
        assert adds and adds[0].to_dict().get("on_size_error")

    def test_not_on_size_error_clause_followed_by_end_compute_is_consumed(self):
        result = _parse_proc(
            "           COMPUTE WS-Z = WS-X + WS-Y\n"
            "               NOT ON SIZE ERROR DISPLAY 'OK'\n"
            "           END-COMPUTE.\n"
            "           DISPLAY WS-Z."
        )
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]

    def test_period_only_termination_still_works(self):
        # No explicit scope terminator at all -- the pre-existing
        # period-consuming path must be unaffected.
        result = _parse_proc("           ADD 1 TO WS-X.\n           DISPLAY WS-X.")
        assert _paragraph_names(result) == ["MAIN-PARA", "NEXT-PARA"]
