"""Regression tests for the 2026-07-07 audit's remaining HIGH/MEDIUM fixes.

Pins the fixes for reports/audit-2026-07-07.md findings left open after the
same-day C1-C8 remediation:

- H1: ON SIZE ERROR / NOT ON SIZE ERROR bodies keep every verb (PERFORM,
  CALL, IF, ...), not just DISPLAY and MOVE
- H2: PERFORM VARYING ... AFTER ... keeps the second (and third) dimension
  in after_clauses instead of garbling it into the UNTIL condition string
- H4: DECIMAL-POINT IS COMMA used to warn that the lexer ignored it; it is
  honoured now, so the warning is gone
- H5: SELECT clauses ALTERNATE RECORD KEY / PADDING / RESERVE / SHARING /
  LOCK MODE / PASSWORD / RECORD DELIMITER / second FILE STATUS variable are
  captured; unknown SELECT clause tokens warn; assign_device is populated
- H6a: a COPY without a terminating period produces an expansion warning
  instead of silently never being expanded
- H6c: an unterminated ==pseudo-text== REPLACING operand produces an
  expansion warning instead of silently aborting the clause
- H7: unknown >>IF conditions (and stray >>ELSE / >>END-IF, malformed
  >>DEFINE, unclosed >>IF) produce warnings instead of silently deleting
  the guarded block
- M10: `cobol-parser coverage status` reports malformed artifact JSON as an
  error instead of crashing with a traceback
"""

import json

import pytest

from cobolparser import CobolParser, ErrorRecoveryMode

PROG_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. PROBE.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-A PIC 9(3) VALUE 999.
       01 WS-B PIC 9(3) VALUE 1.
       01 WS-I PIC 9(2).
       01 WS-J PIC 9(2).
       PROCEDURE DIVISION.
       MAIN-PARA.
{proc}
           GOBACK.
       ERR-PARA.
           DISPLAY 'ERR'.
"""


def _parse(source: str, mode: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL):
    return CobolParser(error_recovery=mode).parse(source, filename="probe.cbl")


def _parse_proc(proc: str, mode: ErrorRecoveryMode = ErrorRecoveryMode.COLLECT_ALL):
    return _parse(PROG_TEMPLATE.format(proc=proc), mode)


class TestH1SizeErrorBodiesKeepAllVerbs:
    """H1: handler bodies dispatch through the statement registry."""

    def test_on_size_error_perform_is_kept(self):
        result = _parse_proc(
            "           ADD WS-A TO WS-B\n"
            "               ON SIZE ERROR\n"
            "                   PERFORM ERR-PARA\n"
            "           END-ADD."
        )
        assert result.errors == []
        add = result.ast.find_all_by_type("AddStatement")[0]
        assert add.on_size_error is not None
        types = [s.statement_type for s in add.on_size_error]
        assert "PERFORM" in types
        # The handler statements are AST children -> visible to traversal
        assert len(result.ast.find_all_by_type("PerformStatement")) == 1

    def test_on_size_error_call_and_if_are_kept(self):
        result = _parse_proc(
            "           ADD WS-A TO WS-B\n"
            "               ON SIZE ERROR\n"
            "                   CALL 'ERRPGM' USING WS-A\n"
            "               NOT ON SIZE ERROR\n"
            "                   IF WS-B > 100\n"
            "                       DISPLAY 'BIG'\n"
            "                   END-IF\n"
            "           END-ADD."
        )
        assert result.errors == []
        add = result.ast.find_all_by_type("AddStatement")[0]
        assert [s.statement_type for s in (add.on_size_error or [])] == ["CALL"]
        assert [s.statement_type for s in (add.not_on_size_error or [])] == ["IF"]
        assert len(result.ast.find_all_by_type("CallStatement")) == 1

    def test_handler_bodies_serialize(self):
        result = _parse_proc(
            "           COMPUTE WS-B = WS-A + 1\n"
            "               ON SIZE ERROR\n"
            "                   PERFORM ERR-PARA\n"
            "           END-COMPUTE."
        )
        compute = result.ast.find_all_by_type("ComputeStatement")[0]
        d = compute.to_dict()
        assert d["on_size_error"], "handler body missing from to_dict()"
        assert d["on_size_error"][0]["statement_type"] == "PERFORM"

    def test_following_statement_survives(self):
        result = _parse_proc(
            "           SUBTRACT WS-A FROM WS-B\n"
            "               ON SIZE ERROR\n"
            "                   PERFORM ERR-PARA\n"
            "           END-SUBTRACT.\n"
            "           DISPLAY 'AFTER'."
        )
        displays = result.ast.find_all_by_type("DisplayStatement")
        assert any(
            "AFTER" in (d.display_items or [""])[0] for d in displays if d.display_items
        )


class TestH2PerformVaryingAfter:
    """H2: the AFTER dimension of PERFORM VARYING is captured."""

    def test_two_dimensional_varying(self):
        result = _parse_proc(
            "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5\n"
            "                   AFTER WS-J FROM 1 BY 1 UNTIL WS-J > 3\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM."
        )
        assert result.errors == []
        perform = result.ast.find_all_by_type("PerformStatement")[0]
        assert perform.varying_clause == {
            "variable": "WS-I",
            "from_value": "1",
            "by_value": "1",
        }
        assert perform.until_condition.operands == ["WS-I > 5"]
        assert len(perform.after_clauses) == 1
        after = perform.after_clauses[0]
        assert after["variable"] == "WS-J"
        assert after["from_value"] == "1"
        assert after["by_value"] == "1"
        assert after["until_condition"].operands == ["WS-J > 3"]
        # Inline body still parsed
        assert [s.statement_type for s in perform.inline_statements] == ["DISPLAY"]

    def test_after_clause_serializes(self):
        result = _parse_proc(
            "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5\n"
            "                   AFTER WS-J FROM 1 BY 1 UNTIL WS-J > 3\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM."
        )
        d = result.ast.find_all_by_type("PerformStatement")[0].to_dict()
        assert "after_clauses" in d
        assert d["after_clauses"][0]["variable"] == "WS-J"
        assert d["after_clauses"][0]["until_condition"]["operands"] == ["WS-J > 3"]
        # And the whole AST is JSON-serializable
        json.dumps(d)

    def test_until_condition_not_polluted_by_after(self):
        result = _parse_proc(
            "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5\n"
            "                   AFTER WS-J FROM 1 BY 1 UNTIL WS-J > 3\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM."
        )
        perform = result.ast.find_all_by_type("PerformStatement")[0]
        condition = perform.until_condition.operands[0]
        assert "AFTER" not in condition.upper()
        assert "TokenType" not in condition

    def test_single_dimension_unchanged(self):
        result = _parse_proc(
            "           PERFORM VARYING WS-I FROM 1 BY 1 UNTIL WS-I > 5\n"
            "               DISPLAY WS-I\n"
            "           END-PERFORM."
        )
        perform = result.ast.find_all_by_type("PerformStatement")[0]
        assert perform.after_clauses == []
        assert "after_clauses" not in perform.to_dict()

    def test_non_varying_until_condition_does_not_stop_at_after_token(self):
        """A plain (non-VARYING) PERFORM UNTIL has no AFTER clause of its
        own, so the AFTER-stop guard added for the AFTER-dimension fix must
        only apply in the VARYING context (Copilot review on PR #79) --
        otherwise a condition/expression containing an AFTER token is
        truncated and the remainder misparsed as inline statements."""
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import Token, TokenType
        from cobolparser.models.ast_base import SourceLocation
        from cobolparser.parsers.statements.perform_parser import (
            PerformStatementParser,
        )

        loc = SourceLocation(1, 1)
        # UNTIL WS-A = 1 AFTER . -- "AFTER" appearing as an operand token in
        # a non-VARYING UNTIL condition must be collected, not treated as
        # the start of a VARYING AFTER dimension.
        tokens = [
            Token(TokenType.IDENTIFIER, "WS-A", loc),
            Token(TokenType.EQUAL, "=", loc),
            Token(TokenType.NUMERIC_LITERAL, "1", loc),
            Token(TokenType.AFTER, "AFTER", loc),
            Token(TokenType.PERIOD, ".", loc),
        ]
        stream = TokenStream(tokens)
        parser = PerformStatementParser()
        condition_tokens = parser._collect_until_condition_tokens(
            stream, for_varying=False
        )
        assert condition_tokens == ["WS-A", "=", "1", "AFTER"]

    def test_varying_until_condition_still_stops_at_after(self):
        from cobolparser.core.token_stream import TokenStream
        from cobolparser.lexer import Token, TokenType
        from cobolparser.models.ast_base import SourceLocation
        from cobolparser.parsers.statements.perform_parser import (
            PerformStatementParser,
        )

        loc = SourceLocation(1, 1)
        tokens = [
            Token(TokenType.IDENTIFIER, "WS-I", loc),
            Token(TokenType.GREATER, ">", loc),
            Token(TokenType.NUMERIC_LITERAL, "5", loc),
            Token(TokenType.AFTER, "AFTER", loc),
            Token(TokenType.IDENTIFIER, "WS-J", loc),
        ]
        stream = TokenStream(tokens)
        parser = PerformStatementParser()
        condition_tokens = parser._collect_until_condition_tokens(
            stream, for_varying=True
        )
        assert condition_tokens == ["WS-I", ">", "5"]
        # AFTER (and what follows) is left unconsumed for the caller
        assert stream.peek().value == "AFTER"


class TestH4DecimalPointIsCommaWarns:
    """H4: the clause is honoured now (see
    test_decimal_point_is_comma.py), so no "not honored" warning."""

    def test_decimal_point_is_comma_no_longer_warns(self):
        result = _parse(
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. EURO.\n"
            "       ENVIRONMENT DIVISION.\n"
            "       CONFIGURATION SECTION.\n"
            "       SPECIAL-NAMES.\n"
            "           DECIMAL-POINT IS COMMA.\n"
            "       DATA DIVISION.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        assert not any("DECIMAL-POINT" in w for w in result.warnings)

    def test_no_warning_without_the_clause(self):
        result = _parse_proc("           DISPLAY 'HI'.")
        assert not any("DECIMAL-POINT" in w for w in result.warnings)


SELECT_TEMPLATE = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. SEL.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
{selects}
       DATA DIVISION.
       PROCEDURE DIVISION.
           STOP RUN.
"""


class TestH5SelectClauseCapture:
    """H5: previously-dropped SELECT clauses are captured and serialized."""

    def _select(self, clauses: str):
        result = _parse(SELECT_TEMPLATE.format(selects=clauses))
        assert result.ast is not None
        selects = result.ast.find_all_by_type("SelectStatement")
        assert selects, "no SelectStatement in AST"
        return result, selects[0]

    def test_alternate_record_keys(self):
        _, sel = self._select(
            "           SELECT F1 ASSIGN TO DISK\n"
            "               ORGANIZATION IS INDEXED\n"
            "               RECORD KEY IS K1\n"
            "               ALTERNATE RECORD KEY IS K2 WITH DUPLICATES\n"
            "               ALTERNATE RECORD KEY IS K3.\n"
        )
        assert sel.alternate_keys == [
            {
                "key": "K2",
                "duplicates_allowed": True,
                "password": None,
                "qualifiers": [],
            },
            {
                "key": "K3",
                "duplicates_allowed": False,
                "password": None,
                "qualifiers": [],
            },
        ]
        d = sel.to_dict()
        assert d["alternate_keys"][0]["key"] == "K2"

    def test_second_file_status_variable(self):
        _, sel = self._select(
            "           SELECT F1 ASSIGN TO DISK\n"
            "               FILE STATUS IS WS-STAT WS-VSAM-STAT.\n"
        )
        assert sel.file_status == "WS-STAT"
        assert sel.file_status_vsam == "WS-VSAM-STAT"

    def test_file_status_single_variable_not_greedy(self):
        _, sel = self._select(
            "           SELECT F1 ASSIGN TO DISK\n"
            "               FILE STATUS IS WS-STAT\n"
            "               ORGANIZATION IS SEQUENTIAL.\n"
        )
        assert sel.file_status == "WS-STAT"
        assert sel.file_status_vsam is None
        assert sel.organization == "SEQUENTIAL"

    def test_padding_reserve_sharing_lock_password(self):
        _, sel = self._select(
            "           SELECT F1 ASSIGN TO DISK\n"
            "               PADDING CHARACTER IS 'X'\n"
            "               RESERVE 3 AREAS\n"
            "               SHARING WITH READ ONLY\n"
            "               LOCK MODE IS AUTOMATIC WITH LOCK ON RECORD\n"
            "               PASSWORD IS WS-PASS.\n"
        )
        assert sel.padding_character == "X"
        assert sel.reserve_areas == 3
        assert sel.sharing_mode == "READ ONLY"
        assert sel.lock_mode == "AUTOMATIC"
        assert sel.lock_on == "RECORD"
        assert sel.password == "WS-PASS"

    def test_record_delimiter_not_misparsed_as_record_key(self):
        _, sel = self._select(
            "           SELECT F1 ASSIGN TO DISK\n"
            "               RECORD DELIMITER IS STANDARD-1.\n"
        )
        assert sel.record_delimiter == "STANDARD-1"
        assert sel.record_key is None

    def test_assign_device_populated(self):
        _, sel = self._select("           SELECT F1 ASSIGN TO PRINTER.\n")
        assert sel.assign_device_type == "PRINTER"
        _, sel2 = self._select("           SELECT F2 ASSIGN TO UT-S-CUSTDD.\n")
        assert sel2.assign_device_type == "UT-S"

    def test_unknown_select_clause_warns(self):
        result, _ = self._select(
            "           SELECT F1 ASSIGN TO DISK\n"
            "               ORGANIZATION IS INDEXED\n"
            "               NONSENSE-CLAUSE FOO.\n"
        )
        assert any("NONSENSE-CLAUSE" in w and "SELECT" in w for w in result.warnings)


class TestH6CopybookSilentChannels:
    """H6a/H6c: dropped COPY statements are reported via warnings."""

    @pytest.fixture()
    def copybook_dir(self, tmp_path):
        (tmp_path / "GOODBK.CPY").write_text("       01  WS-FROM-COPY PIC X(10).\n")
        return str(tmp_path)

    def test_copy_without_period_warns(self, copybook_dir):
        from cobolparser import expand_copybooks

        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NOPERIOD.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY GOODBK\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = expand_copybooks(src, copybook_paths=[copybook_dir])
        assert any(
            "COPY GOODBK" in w and "NOT expanded" in w
            for w in result.statistics.warnings
        )

    def test_copy_without_period_warns_through_parse(self, copybook_dir):
        from cobolparser import parse_cobol_with_expansion

        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. NOPERIOD.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY GOODBK\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = parse_cobol_with_expansion(
            src, "noperiod.cbl", copybook_paths=[copybook_dir]
        )
        assert any("NOT expanded" in w for w in result.warnings)

    def test_unterminated_pseudo_text_warns(self, copybook_dir):
        from cobolparser import expand_copybooks

        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. BADPSEUDO.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY GOODBK REPLACING ==WS-FROM== BY ==WS-TO.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = expand_copybooks(src, copybook_paths=[copybook_dir])
        assert any(
            "unterminated ==pseudo-text==" in w for w in result.statistics.warnings
        )

    def test_wellformed_copy_produces_no_new_warnings(self, copybook_dir):
        from cobolparser import expand_copybooks

        src = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. GOODCOPY.\n"
            "       DATA DIVISION.\n"
            "       WORKING-STORAGE SECTION.\n"
            "       COPY GOODBK.\n"
            "       PROCEDURE DIVISION.\n"
            "           STOP RUN.\n"
        )
        result = expand_copybooks(src, copybook_paths=[copybook_dir])
        # No drop-diagnostics from the COPY lexer (content-validation
        # warnings from validate_copybook_content are a separate channel)
        assert not any(
            "NOT expanded" in w or "pseudo-text" in w or "ignored" in w
            for w in result.statistics.warnings
        )
        assert "WS-FROM-COPY" in result.expanded_source


class TestH7ConditionalCompilationWarnings:
    """H7: >>IF/>>DEFINE degradations are reported via the warnings list."""

    def _preprocess(self, source, defines=None):
        from cobolparser.preprocess import preprocess_conditional_compilation

        warnings: list[str] = []
        out = preprocess_conditional_compilation(source, defines or {}, warnings)
        return out, warnings

    def test_undefined_symbol_comparison_warns_and_skips(self):
        """M10 update: `FOO > 3` is now a *supported* comparison; with FOO
        undefined it warns about the undefined symbol and evaluates FALSE
        (block skipped)."""
        out, warnings = self._preprocess(
            ">>IF FOO > 3\nDISPLAY 'HIDDEN'.\n>>END-IF\nDISPLAY 'KEPT'.\n"
        )
        assert "HIDDEN" not in out
        assert "KEPT" in out
        assert any("undefined symbol 'FOO'" in w for w in warnings)

    def test_unparseable_if_condition_warns_and_skips(self):
        out, warnings = self._preprocess(
            ">>IF FOO > > 3\nDISPLAY 'HIDDEN'.\n>>END-IF\nDISPLAY 'KEPT'.\n"
        )
        assert "HIDDEN" not in out
        assert "KEPT" in out
        assert any("unsupported >>IF condition" in w for w in warnings)

    def test_stray_else_and_end_if_warn(self):
        _, warnings = self._preprocess(">>ELSE\n>>END-IF\nDISPLAY 'X'.\n")
        assert any(">>ELSE without a matching >>IF" in w for w in warnings)
        assert any(">>END-IF without a matching >>IF" in w for w in warnings)

    def test_malformed_define_warns(self):
        _, warnings = self._preprocess(">>DEFINE\nDISPLAY 'X'.\n")
        assert any("malformed >>DEFINE" in w for w in warnings)

    def test_unclosed_if_warns(self):
        _, warnings = self._preprocess(
            ">>IF DEBUG IS DEFINED\nDISPLAY 'X'.\n", {"DEBUG": "TRUE"}
        )
        assert any("unclosed >>IF" in w for w in warnings)

    def test_unknown_directive_warns_and_is_blanked(self):
        """2026-09-15: an unknown ``>>`` directive is a compiler directive,
        never program text, so it is blanked out (line count kept) with a
        warning rather than passed to the lexer as a stray ``>>`` pair --
        which the parser then reported as unparsed content."""
        out, warnings = self._preprocess(">>CALLINTERFACE DYNAMIC\nDISPLAY 'X'.\n")
        assert ">>CALLINTERFACE DYNAMIC" not in out
        assert out == "\nDISPLAY 'X'."
        assert any("unknown compiler directive" in w for w in warnings)

    def test_evaluate_directive_is_now_supported(self):
        """M10 update: >>EVALUATE is now implemented as a real directive
        (it used to fall through the unknown-directive path). A well-formed
        block selects the matching >>WHEN branch silently; an unclosed
        >>EVALUATE at end of input warns."""
        out, warnings = self._preprocess(
            ">>EVALUATE TRUE\n"
            ">>WHEN 1 = 1\n"
            "DISPLAY 'PICKED'.\n"
            ">>END-EVALUATE\n"
        )
        assert ">>EVALUATE" not in out
        assert "PICKED" in out
        assert warnings == []

        _, warnings = self._preprocess(">>EVALUATE TRUE\nDISPLAY 'X'.\n")
        assert any("unclosed >>EVALUATE" in w for w in warnings)

    def test_supported_directives_stay_silent(self):
        out, warnings = self._preprocess(
            ">>DEFINE DEBUG\n>>IF DEBUG IS DEFINED\nDISPLAY 'D'.\n>>END-IF\n"
        )
        assert "DISPLAY 'D'." in out
        assert warnings == []


class TestM10CoverageStatusMalformedJson:
    """M10: coverage status handles malformed artifact JSON gracefully."""

    def test_malformed_json_returns_error_not_traceback(self, tmp_path, capsys):
        import argparse

        from cobolparser.cli.coverage import cmd_status

        artifact = tmp_path / "io-coverage.json"
        artifact.write_text("{ not valid json !!!")
        args = argparse.Namespace(
            artifact=str(artifact), verb=None, qualifier=None, format="table"
        )
        rc = cmd_status(args)
        assert rc == 1
        out = capsys.readouterr().out
        assert "not valid JSON" in out

    def test_non_object_json_returns_error(self, tmp_path, capsys):
        import argparse

        from cobolparser.cli.coverage import cmd_status

        artifact = tmp_path / "io-coverage.json"
        artifact.write_text("[1, 2, 3]")
        args = argparse.Namespace(
            artifact=str(artifact), verb=None, qualifier=None, format="table"
        )
        rc = cmd_status(args)
        assert rc == 1
        assert "coverage artifact" in capsys.readouterr().out
