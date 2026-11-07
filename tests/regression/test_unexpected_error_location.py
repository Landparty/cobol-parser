"""An unexpected exception in parsing keeps its type, location and cause.

The division loop and ``_parse_core``'s safety net turned any non-ParseError
exception into ``ParseError("Division parsing error: <msg>", line 1, col 1)``
(or ``"Parser error: ..."``): the exception type was lost, every such error
pointed at line 1, and the division-loop path dropped the cause chain. They
now name the type, take the location from the exception when it carries one
(else from the token the stream is positioned at), and chain the original
exception through ``__cause__``.
"""

from unittest.mock import patch

from cobolparser.parser import CobolParser
from cobolparser.parsers.divisions.data import DataDivisionParser
from cobolparser.plugins.core import ErrorRecoveryMode

SOURCE = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. LOCERR.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-A PIC X.\n"
    "       PROCEDURE DIVISION.\n"
    "           STOP RUN.\n"
)


class _Located(Exception):
    """A non-ParseError exception that carries its own position."""

    def __init__(self, message: str, line_number: int, column: int) -> None:
        super().__init__(message)
        self.line_number = line_number
        self.column = column


def _division_errors(exc: Exception):
    # FAIL_FAST: under COLLECT_ALL a division parser that raises without
    # consuming anything is retried on the same token.
    parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
    with patch.object(DataDivisionParser, "parse", side_effect=exc):
        result = parser.parse(SOURCE)
    return [e for e in result.errors if "Division parsing error" in e.message]


def test_division_error_names_the_exception_type_and_chains_it():
    boom = RuntimeError("data division exploded")
    (err,) = _division_errors(boom)
    assert err.message == (
        "Division parsing error: RuntimeError: data division exploded"
    )
    assert err.__cause__ is boom


def test_division_error_takes_the_current_token_location():
    (err,) = _division_errors(KeyError("missing"))
    # The stream is still at the DATA DIVISION header (line 3; the parser
    # lexes normalized text, so Area A is column 1) when parse() raises.
    assert (err.line_number, err.column) == (3, 1)
    assert "KeyError" in err.message


def test_division_error_prefers_the_exceptions_own_location():
    (err,) = _division_errors(_Located("bad entry", line_number=5, column=12))
    assert (err.line_number, err.column) == (5, 12)
    assert "_Located: bad entry" in err.message


def test_top_level_safety_net_names_the_type_and_chains_it():
    parser = CobolParser()
    boom = ValueError("before tokenizing")
    with patch.object(parser, "_skip_to_identification_division", side_effect=boom):
        result = parser.parse(SOURCE)
    assert result.ast is None
    (err,) = result.errors
    assert err.message == "Parser error: ValueError: before tokenizing"
    assert err.__cause__ is boom
    # Nothing tokenized yet: no position to borrow, so the start of the file.
    assert (err.line_number, err.column) == (1, 1)


def test_top_level_safety_net_ignores_a_previous_parses_stream():
    parser = CobolParser()
    parser.parse(SOURCE)  # leaves a stream positioned at EOF
    with patch.object(
        parser, "_skip_to_identification_division", side_effect=OSError("x")
    ):
        result = parser.parse(SOURCE)
    (err,) = result.errors
    assert (err.line_number, err.column) == (1, 1)
