"""WHEN clauses whose selector is a blank string literal must parse.

`EVALUATE <status-field> WHEN '  ' ... WHEN 'GB' ...` is the standard IMS
DL/I status-code idiom (blanks mean "call succeeded"). The lexer strips the
quotes off string literals, so a blank literal's token value is
whitespace-only; the selector builder used to filter it out as an empty
artifact and then reported "WHEN clause must have at least one selector" —
blocking otherwise-clean real-world IMS programs (observed on 5/17 programs
in the legacy-application corpus, 2-4 occurrences each).
"""

from cobolparser import parse_cobol


def _program(when_lines: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. EVALSPC.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-STATUS PIC XX.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n"
        "           EVALUATE WS-STATUS\n" + when_lines + "           END-EVALUATE.\n"
    )


def _first_evaluate(result):
    evaluates = result.ast.find_all_by_type("EvaluateStatement")
    assert evaluates, "EVALUATE statement missing from AST"
    return evaluates[0]


class TestBlankLiteralWhenSelector:
    def test_when_blank_literal_parses_without_errors(self):
        source = _program(
            "               WHEN '  '\n"
            "                   DISPLAY 'OK'\n"
            "               WHEN 'GB'\n"
            "                   DISPLAY 'EOF'\n"
        )
        result = parse_cobol(source, filename="evalspc.cbl")
        assert result.success, [str(e) for e in result.errors]
        assert not result.errors

    def test_blank_literal_selector_is_preserved(self):
        source = _program(
            "               WHEN '  '\n" "                   DISPLAY 'OK'\n"
        )
        result = parse_cobol(source, filename="evalspc.cbl")
        stmt = _first_evaluate(result)
        assert len(stmt.when_clauses) == 1
        (selector,) = stmt.when_clauses[0].selectors
        assert selector["type"] == "Literal"
        # Blank literals keep their quotes so the two-space value survives
        # tokenization (the lexer strips quotes, leaving whitespace-only text
        # that would otherwise be indistinguishable from an empty artifact).
        assert selector["value"] == "'  '"

    def test_single_space_literal_parses(self):
        source = _program(
            "               WHEN ' '\n" "                   DISPLAY 'OK'\n"
        )
        result = parse_cobol(source, filename="evalspc.cbl")
        assert result.success, [str(e) for e in result.errors]

    def test_blank_literal_with_also_parses(self):
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EVALSPC2.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       01 WS-A PIC XX.\n"
            "       01 WS-B PIC XX.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           EVALUATE WS-A ALSO WS-B\n"
            "               WHEN '  ' ALSO 'GB'\n"
            "                   DISPLAY 'OK'\n"
            "           END-EVALUATE.\n"
        )
        result = parse_cobol(source, filename="evalspc2.cbl")
        assert result.success, [str(e) for e in result.errors]

    def test_nonblank_literal_selector_value_unchanged(self):
        """Guard: ordinary literals must keep their existing (unquoted)
        selector representation."""
        source = _program(
            "               WHEN 'GB'\n" "                   DISPLAY 'EOF'\n"
        )
        result = parse_cobol(source, filename="evalspc.cbl")
        stmt = _first_evaluate(result)
        (selector,) = stmt.when_clauses[0].selectors
        assert selector == {"type": "Literal", "value": "GB", "quoted": True}
