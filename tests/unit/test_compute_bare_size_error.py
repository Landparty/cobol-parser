"""COMPUTE with ``SIZE ERROR`` written without the optional ``ON`` (#399).

The expression loop used to stop only at ``ON``/``NOT``/``END-COMPUTE``, so a
bare ``SIZE ERROR`` was folded into the expression string and the handler's
statements escaped the COMPUTE as unconditional statements.
"""

from cobolparser import parse_cobol


def _program(body: str) -> str:
    return f"""
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TESTCOMP.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-A PIC 9(3).
       01  WS-B PIC 9(3).
       01  WS-C PIC 9(3).
       PROCEDURE DIVISION.
       MAIN-PARA.
{body}
           STOP RUN.
"""


def _display_items(stmts):
    return [s.to_dict()["display_items"] for s in stmts]


def _top_level_verbs(result):
    para = result.ast.find_all_by_type("CobolParagraph")[0]
    return [s.to_dict().get("statement_type") for s in para.statements]


class TestComputeBareSizeError:
    def test_bare_size_error_is_handler_not_expression(self):
        result = parse_cobol(
            _program("           COMPUTE WS-C = WS-A + WS-B SIZE ERROR DISPLAY 'E'.")
        )
        assert result.errors == []
        assert result.warnings == []
        (compute,) = result.ast.find_statements("COMPUTE")
        assert compute.expression == "WS-A + WS-B"
        assert compute.expression_tree is not None
        assert _display_items(compute.on_size_error) == [['"E"']]
        # The handler's DISPLAY no longer runs as a free-standing statement.
        assert _top_level_verbs(result) == ["COMPUTE", "STOP"]

    def test_bare_size_error_inside_if_with_end_compute(self):
        result = parse_cobol(
            _program(
                "           IF WS-A > 1\n"
                "               COMPUTE WS-C = WS-A SIZE ERROR DISPLAY 'E'\n"
                "               END-COMPUTE\n"
                "           END-IF."
            )
        )
        assert result.errors == []
        assert result.warnings == []
        (compute,) = result.ast.find_statements("COMPUTE")
        assert compute.expression == "WS-A"
        assert _display_items(compute.on_size_error) == [['"E"']]

    def test_bare_size_error_with_bare_not_size_error(self):
        result = parse_cobol(
            _program(
                "           COMPUTE WS-C = WS-A SIZE ERROR DISPLAY 'X'\n"
                "               NOT SIZE ERROR DISPLAY 'Y'\n"
                "           END-COMPUTE."
            )
        )
        assert result.errors == []
        assert result.warnings == []
        (compute,) = result.ast.find_statements("COMPUTE")
        assert compute.expression == "WS-A"
        assert _display_items(compute.on_size_error) == [['"X"']]
        assert _display_items(compute.not_on_size_error) == [['"Y"']]

    def test_on_size_error_still_recognized(self):
        result = parse_cobol(
            _program("           COMPUTE WS-C = WS-A * 2 ON SIZE ERROR DISPLAY 'E'.")
        )
        (compute,) = result.ast.find_statements("COMPUTE")
        assert compute.expression == "WS-A * 2"
        assert _display_items(compute.on_size_error) == [['"E"']]
