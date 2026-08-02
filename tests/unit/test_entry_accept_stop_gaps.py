"""Regression tests for ENTRY / ACCEPT / STOP parsing gaps.

Covers three bugs previously found in the statement parsers:

1. ENTRY comma capture (``entry_parser.py``): the USING loop's trailing
   else consumed any token "as parameter anyway", so
   ``ENTRY "E" USING WS-A, WS-B`` recorded a literal ``","`` entry in
   ``using_parameters``, corrupting parameter arity.
2. ACCEPT FROM ENVIRONMENT name drop (``accept_parser.py``): the FROM
   collection loop only appended IDENTIFIER tokens, so the STRING_LITERAL
   naming the environment variable was dropped and
   ``IOAcceptStatement.environment_name`` was never populated.
3. STOP period leak (``stop_parser.py``): STOP never consumed its sentence
   period, so the procedure-division parser materialized a phantom empty
   paragraph named ``"."`` after every STOP that preceded a paragraph
   header.
"""

from cobolparser import parse_cobol


def _program(body: str) -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. DEMO.\n"
        "       PROCEDURE DIVISION.\n"
        "       MAIN-PARA.\n" + body
    )


def _paragraph_names(result):
    return [p.paragraph_name for p in result.ast.find_all_by_type("CobolParagraph")]


class TestEntryUsingComma:
    """ENTRY USING must treat commas as separators, not parameters."""

    def test_comma_separated_using_parameters(self):
        source = _program(
            '           ENTRY "ENTPT" USING WS-A, WS-B.\n           STOP RUN.\n'
        )
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        entries = result.ast.find_all_by_type("EntryStatement")
        assert len(entries) == 1
        params = entries[0].to_dict()["using_parameters"]
        assert params == ["WS-A", "WS-B"]
        assert "," not in params

    def test_space_separated_using_parameters_unchanged(self):
        """Non-regression: space-separated USING keeps working."""
        source = _program(
            '           ENTRY "ENTPT" USING WS-A WS-B.\n           STOP RUN.\n'
        )
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        entries = result.ast.find_all_by_type("EntryStatement")
        assert len(entries) == 1
        assert entries[0].to_dict()["using_parameters"] == ["WS-A", "WS-B"]


class TestAcceptFromEnvironment:
    """ACCEPT ... FROM ENVIRONMENT must capture the environment name."""

    def test_environment_name_string_literal(self):
        source = _program(
            '           ACCEPT WS-A FROM ENVIRONMENT "PATH".\n           STOP RUN.\n'
        )
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        accepts = result.ast.find_all_by_type("IOAcceptStatement")
        assert len(accepts) == 1
        d = accepts[0].to_dict()
        assert d["target"] == "WS-A"
        assert d["from_source"] == "ENVIRONMENT"
        assert d["environment_name"] == "PATH"

    def test_environment_name_identifier(self):
        source = _program(
            "           ACCEPT WS-B FROM ENVIRONMENT WS-ENV.\n           STOP RUN.\n"
        )
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        accepts = result.ast.find_all_by_type("IOAcceptStatement")
        assert len(accepts) == 1
        d = accepts[0].to_dict()
        assert d["target"] == "WS-B"
        assert d["from_source"] == "ENVIRONMENT"
        assert d["environment_name"] == "WS-ENV"

    def test_plain_accept_unchanged(self):
        """Non-regression: ACCEPT without FROM stays untouched."""
        source = _program("           ACCEPT WS-A.\n           STOP RUN.\n")
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        accepts = result.ast.find_all_by_type("IOAcceptStatement")
        assert len(accepts) == 1
        d = accepts[0].to_dict()
        assert d["target"] == "WS-A"
        assert d["from_source"] is None
        assert d["environment_name"] is None

    def test_accept_from_date_unchanged(self):
        """Non-regression: FROM DATE must not gain an environment name."""
        source = _program("           ACCEPT WS-D FROM DATE.\n           STOP RUN.\n")
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        accepts = result.ast.find_all_by_type("IOAcceptStatement")
        assert len(accepts) == 1
        d = accepts[0].to_dict()
        assert d["target"] == "WS-D"
        assert d["from_source"] == "DATE"
        assert d["environment_name"] is None


class TestStopPeriodConsumed:
    """STOP must consume its sentence period (no phantom "." paragraph)."""

    def test_stop_run_no_phantom_paragraph(self):
        source = _program(
            "           STOP RUN.\n" "       NEXT-PARA.\n" '           DISPLAY "X".\n'
        )
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        names = _paragraph_names(result)
        assert "." not in names
        assert names == ["MAIN-PARA", "NEXT-PARA"]

    def test_stop_literal_no_phantom_paragraph(self):
        source = _program(
            '           STOP "DONE".\n'
            "       NEXT-PARA.\n"
            '           DISPLAY "X".\n'
        )
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []

        names = _paragraph_names(result)
        assert "." not in names
        assert names == ["MAIN-PARA", "NEXT-PARA"]

    def test_stop_run_at_end_of_program(self):
        """Non-regression: STOP RUN as the final sentence still parses."""
        source = _program("           STOP RUN.\n")
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []
        assert _paragraph_names(result) == ["MAIN-PARA"]

        stops = result.ast.find_all_by_type("StopStatement")
        assert len(stops) == 1
        assert stops[0].stop_type == "RUN"

    def test_no_trailing_phantom_paragraph_without_named_paragraph(self):
        """A PROCEDURE DIVISION with no named paragraph header (only the
        implicit paragraph) must not gain a second, empty-named, trailing
        paragraph once the EOF sentinel token is reached.

        The EOF token's empty value isn't in the division parser's
        keyword-exclusion tuple, so without an explicit EOF check it used to
        fall through to the "unknown token -> paragraph name" branch and
        manufacture a spurious zero-statement paragraph, inflating both
        ``procedure_count`` and ``total_lines`` (get_statistics() takes the
        max AST node line, and the phantom paragraph's location trails the
        real content).
        """
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. DEMO.\n"
            "       PROCEDURE DIVISION.\n"
            '           DISPLAY "TEST"\n'
            "           STOP RUN.\n"
        )
        result = parse_cobol(source)
        assert result.success
        assert result.errors == []
        assert _paragraph_names(result) == [""]

        stats = result.ast.get_statistics()
        assert stats["procedure_count"] == 1
        assert stats["total_lines"] == 5
