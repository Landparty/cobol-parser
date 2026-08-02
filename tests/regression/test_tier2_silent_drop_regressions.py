"""Regression tests for Tier 2 silently-dropped-syntax fixes.

Each test class documents exactly what was broken before the fix and locks
down the corrected behavior so future refactors cannot silently re-introduce
the same gaps.

Broken behaviors fixed (Tier 2):
    Group 1 — Data clauses SIGN, SYNCHRONIZED, JUSTIFIED, BLANK WHEN ZERO
              were silently consumed and lost; CobolDataItem had no fields for them.
    Group 2 — EXEC CICS command name and option text were discarded; the node
              had only node_type + location. Also: CICS was tokenized as
              TokenType.CICS (not IDENTIFIER), so matches() returned False
              and no EXEC_CICS node was created at all.
    Group 3 — No ExecImsStatementParser existed; EXEC IMS blocks produced
              zero AST nodes.
    Group 4 — _parse_configuration_section() skipped all content;
              SPECIAL-NAMES clauses were never stored.
    Group 5 — strip_compiler_directives() was only called from the CLI;
              programs with CBL/PROCESS lines failed via the library API.
    Group 6 — A MOVE (or SUBTRACT/MULTIPLY/DIVIDE) statement with no trailing
              period, immediately followed by another statement, silently
              swallowed that statement's leading tokens instead of stopping
              at the boundary:
                * MoveStatementParser's target-collection loop used a
                  hand-rolled stop-keyword list that didn't include
                  EXEC/EXECUTE (unlike the shared STATEMENT_TOKEN_TYPES /
                  STATEMENT_KEYWORDS every other statement parser uses), so
                  an EXEC SQL block right after a MOVE vanished from the AST
                  entirely and its leading tokens were misread as bogus MOVE
                  targets.
                * SUBTRACT/MULTIPLY/DIVIDE ended their parse by calling
                  skip_to_period(), which blindly consumed every token up to
                  the next period regardless of statement boundaries —
                  eating an entire following statement (or, worse, only part
                  of one, up to a coincidental period inside a qualified SQL
                  table name like BANK.ACCOUNT) whenever the SUBTRACT/
                  MULTIPLY/DIVIDE statement itself had no trailing period.
"""

import textwrap
from pathlib import Path

import pytest

from cobolparser import parse_cobol

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ws_program(items: str) -> str:
    """Wrap bare WORKING-STORAGE items in a minimal COBOL program."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-ROOT.
        {items}
        PROCEDURE DIVISION.
        STOP RUN.
        """)


def _proc_program(procedure_body: str) -> str:
    """Wrap bare PROCEDURE DIVISION statements in a minimal COBOL program."""
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC X.
        PROCEDURE DIVISION.
        MAIN-PARA.
        {procedure_body}
            STOP RUN.
        """)


def _find_item(result, name: str):
    items = result.ast.find_all_by_type("DataItem")
    for item in items:
        if hasattr(item, "name") and item.name.upper() == name.upper():
            return item
    return None


def _find_nodes(result, node_type: str) -> list:
    return result.ast.find_all_by_type(node_type)


# ===========================================================================
# Group 1 — Data clauses
# ===========================================================================


class TestSignClauseNotDropped:
    """Before the fix, SIGN fell to else: consume() and sign_clause stayed None."""

    def test_sign_is_leading_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC S9(9) COMP SIGN IS LEADING."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-A")
        assert item is not None
        assert (
            item.sign_clause == "LEADING"
        ), "sign_clause must not be None/empty — was silently dropped before fix"

    def test_sign_trailing_separate_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC S9(9) SIGN IS TRAILING SEPARATE."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-A")
        assert item.sign_clause == "TRAILING SEPARATE"

    def test_sign_leading_separate_character_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC S9(5) SIGN LEADING SEPARATE CHARACTER."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-A")
        assert item.sign_clause == "LEADING SEPARATE"

    def test_sign_in_to_dict(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC S9(9) SIGN IS TRAILING."),
            filename="reg.cbl",
        )
        d = _find_item(result, "WS-A").to_dict()
        assert "sign_clause" in d, "sign_clause must appear in to_dict() output"
        assert d["sign_clause"] == "TRAILING"

    def test_item_without_sign_has_none(self):
        """Items that have no SIGN clause must still default to None (no contamination)."""
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(9) COMP."),
            filename="reg.cbl",
        )
        item = _find_item(result, "WS-A")
        assert item.sign_clause is None

    def test_sign_in_to_dict_omitted_when_none(self):
        """to_dict() must NOT include sign_clause when it is None."""
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(9) COMP."),
            filename="reg.cbl",
        )
        d = _find_item(result, "WS-A").to_dict()
        assert "sign_clause" not in d

    def test_sibling_item_after_sign_parses_correctly(self):
        """SIGN parsing must not over-consume tokens — the next sibling must survive."""
        result = parse_cobol(
            _ws_program(
                "    05  WS-A  PIC S9(9) SIGN IS LEADING.\n" "    05  WS-B  PIC X(10)."
            ),
            filename="reg.cbl",
        )
        assert result.success
        assert (
            _find_item(result, "WS-B") is not None
        ), "Sibling after SIGN clause must not be lost"


class TestSynchronizedNotDropped:
    """Before the fix, SYNCHRONIZED/SYNC fell to else: consume() and was lost."""

    def test_synchronized_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(4) COMP SYNCHRONIZED."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-A")
        assert (
            item.synchronized is True
        ), "synchronized must be True — was silently dropped before fix"

    def test_sync_abbreviation_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(4) COMP SYNC."),
            filename="reg.cbl",
        )
        assert result.success
        assert _find_item(result, "WS-A").synchronized is True

    def test_sync_left_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(4) COMP SYNC LEFT."),
            filename="reg.cbl",
        )
        assert result.success
        assert _find_item(result, "WS-A").synchronized is True

    def test_synchronized_in_to_dict(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(4) COMP SYNCHRONIZED."),
            filename="reg.cbl",
        )
        d = _find_item(result, "WS-A").to_dict()
        assert d.get("synchronized") is True

    def test_item_without_sync_omits_key(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(4) COMP."),
            filename="reg.cbl",
        )
        d = _find_item(result, "WS-A").to_dict()
        assert "synchronized" not in d


class TestJustifiedNotDropped:
    """Before the fix, JUSTIFIED/JUST fell to else: consume() and was lost."""

    def test_justified_right_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC X(20) JUSTIFIED RIGHT."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-A")
        assert (
            item.justified is True
        ), "justified must be True — was silently dropped before fix"

    def test_just_abbreviation_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC X(20) JUST."),
            filename="reg.cbl",
        )
        assert result.success
        assert _find_item(result, "WS-A").justified is True

    def test_justified_in_to_dict(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC X(20) JUSTIFIED RIGHT."),
            filename="reg.cbl",
        )
        d = _find_item(result, "WS-A").to_dict()
        assert d.get("justified") is True

    def test_item_without_justified_omits_key(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC X(20)."),
            filename="reg.cbl",
        )
        d = _find_item(result, "WS-A").to_dict()
        assert "justified" not in d

    def test_sibling_after_justified_parses_correctly(self):
        result = parse_cobol(
            _ws_program(
                "    05  WS-A  PIC X(20) JUSTIFIED RIGHT.\n" "    05  WS-B  PIC 9(5)."
            ),
            filename="reg.cbl",
        )
        assert result.success
        assert _find_item(result, "WS-B") is not None


class TestBlankWhenZeroNotDropped:
    """Before the fix, BLANK fell to else: consume() and blank_when_zero stayed False."""

    def test_blank_when_zero_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(7)V99 BLANK WHEN ZERO."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-A")
        assert (
            item.blank_when_zero is True
        ), "blank_when_zero must be True — was silently dropped before fix"

    def test_blank_when_zeros_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(7) BLANK WHEN ZEROS."),
            filename="reg.cbl",
        )
        assert result.success
        assert _find_item(result, "WS-A").blank_when_zero is True

    def test_blank_when_zeroes_stored(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(7) BLANK WHEN ZEROES."),
            filename="reg.cbl",
        )
        assert result.success
        assert _find_item(result, "WS-A").blank_when_zero is True

    def test_blank_when_zero_in_to_dict(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(7)V99 BLANK WHEN ZERO."),
            filename="reg.cbl",
        )
        d = _find_item(result, "WS-A").to_dict()
        assert d.get("blank_when_zero") is True

    def test_item_without_blank_omits_key(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC 9(7)."),
            filename="reg.cbl",
        )
        d = _find_item(result, "WS-A").to_dict()
        assert "blank_when_zero" not in d


class TestMultipleDataClausesOnOneItem:
    """All four clause types must coexist on a single data item without interference."""

    def test_sign_and_sync_together(self):
        result = parse_cobol(
            _ws_program("    05  WS-A  PIC S9(9) COMP SIGN IS LEADING SYNCHRONIZED."),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-A")
        assert item.sign_clause == "LEADING"
        assert item.synchronized is True

    def test_all_four_clauses(self):
        result = parse_cobol(
            _ws_program(
                "    05  WS-A  PIC S9(9)V99\n"
                "              SIGN IS LEADING SEPARATE\n"
                "              SYNCHRONIZED\n"
                "              JUSTIFIED\n"
                "              BLANK WHEN ZERO."
            ),
            filename="reg.cbl",
        )
        assert result.success
        item = _find_item(result, "WS-A")
        assert item.sign_clause == "LEADING SEPARATE"
        assert item.synchronized is True
        assert item.justified is True
        assert item.blank_when_zero is True

    def test_no_clause_contamination_between_siblings(self):
        """Clauses on one item must never bleed into the next."""
        result = parse_cobol(
            _ws_program(
                "    05  WS-A  PIC S9(9) SIGN IS TRAILING SEPARATE SYNCHRONIZED.\n"
                "    05  WS-B  PIC X(10)."
            ),
            filename="reg.cbl",
        )
        assert result.success
        b = _find_item(result, "WS-B")
        assert b is not None
        assert b.sign_clause is None
        assert b.synchronized is False
        assert b.justified is False
        assert b.blank_when_zero is False


# ===========================================================================
# Group 2 — EXEC CICS
# ===========================================================================


class TestExecCicsCommandNotDropped:
    """Before the fix (TokenType.CICS detection), matches() returned False and
    no EXEC_CICS node was created at all; cics_command was always empty."""

    def test_exec_cics_node_exists(self):
        result = parse_cobol(
            _proc_program("    EXEC CICS READ FILE('F') INTO(WS-X) END-EXEC."),
            filename="reg.cbl",
        )
        assert result.success
        nodes = _find_nodes(result, "EXEC_CICS")
        assert nodes, "EXEC_CICS node must exist — was missing entirely before fix"

    def test_cics_command_not_empty(self):
        result = parse_cobol(
            _proc_program("    EXEC CICS READ FILE('F') INTO(WS-X) END-EXEC."),
            filename="reg.cbl",
        )
        node = _find_nodes(result, "EXEC_CICS")[0]
        assert (
            node.cics_command != ""
        ), "cics_command must not be empty string — was silently dropped before fix"
        assert node.cics_command == "READ"

    def test_cics_text_not_empty(self):
        result = parse_cobol(
            _proc_program("    EXEC CICS READ FILE('EMPFILE') INTO(WS-X) END-EXEC."),
            filename="reg.cbl",
        )
        node = _find_nodes(result, "EXEC_CICS")[0]
        assert (
            node.cics_text
        ), "cics_text must not be empty for a statement with options"
        assert "FILE" in node.cics_text or "EMPFILE" in node.cics_text

    def test_to_dict_has_cics_command_key(self):
        result = parse_cobol(
            _proc_program("    EXEC CICS SEND MAP('M') MAPSET('S') END-EXEC."),
            filename="reg.cbl",
        )
        d = _find_nodes(result, "EXEC_CICS")[0].to_dict()
        assert "cics_command" in d, "cics_command must be present in to_dict()"
        assert "cics_text" in d, "cics_text must be present in to_dict()"
        assert d["cics_command"] == "SEND"

    def test_multiple_cics_blocks_all_found(self):
        result = parse_cobol(
            _proc_program(
                "    EXEC CICS READ FILE('F') INTO(WS-X) END-EXEC.\n"
                "    EXEC CICS WRITE FILE('F') FROM(WS-X) END-EXEC."
            ),
            filename="reg.cbl",
        )
        assert result.success
        nodes = _find_nodes(result, "EXEC_CICS")
        assert len(nodes) >= 2, "Both EXEC CICS blocks must produce nodes"
        commands = {n.cics_command for n in nodes}
        assert "READ" in commands
        assert "WRITE" in commands

    def test_various_cics_commands(self):
        for command in ("READ", "WRITE", "SEND", "RECEIVE", "RETURN", "LINK", "XCTL"):
            result = parse_cobol(
                _proc_program(f"    EXEC CICS {command} END-EXEC."),
                filename="reg.cbl",
            )
            assert result.success
            nodes = _find_nodes(result, "EXEC_CICS")
            assert nodes, f"No EXEC_CICS node for command {command}"
            assert nodes[0].cics_command == command


# ===========================================================================
# Group 3 — EXEC IMS
# ===========================================================================


class TestExecImsNodeNotMissing:
    """Before the fix, no ExecImsStatementParser existed and EXEC IMS blocks
    produced zero AST nodes — the tokens were silently consumed one by one."""

    def test_exec_ims_node_created(self):
        result = parse_cobol(
            _proc_program("    EXEC IMS GU EMPDB END-EXEC."),
            filename="reg.cbl",
        )
        assert result.success
        nodes = _find_nodes(result, "EXEC_IMS")
        assert nodes, "EXEC_IMS node must exist — was missing entirely before fix"

    def test_ims_command_not_empty(self):
        result = parse_cobol(
            _proc_program("    EXEC IMS GU EMPDB END-EXEC."),
            filename="reg.cbl",
        )
        node = _find_nodes(result, "EXEC_IMS")[0]
        assert (
            node.ims_command == "GU"
        ), "ims_command must be 'GU' — was silently dropped before fix"

    def test_ims_call_type_defaults_unknown_for_unrecognized(self):
        result = parse_cobol(
            _proc_program("    EXEC IMS UNKNOWN-CMD EMPDB END-EXEC."),
            filename="reg.cbl",
        )
        assert result.success
        nodes = _find_nodes(result, "EXEC_IMS")
        assert nodes
        assert nodes[0].ims_call_type == "UNKNOWN"

    def test_known_ims_call_types_classified(self):
        for call_type in ("GU", "GN", "GNP", "ISRT", "REPL", "DLET"):
            result = parse_cobol(
                _proc_program(f"    EXEC IMS {call_type} EMPDB END-EXEC."),
                filename="reg.cbl",
            )
            assert result.success
            nodes = _find_nodes(result, "EXEC_IMS")
            assert nodes, f"No EXEC_IMS node for call type {call_type}"
            node = nodes[0]
            assert node.ims_command == call_type
            assert (
                node.ims_call_type == call_type
            ), f"ims_call_type should be '{call_type}' not 'UNKNOWN'"

    def test_exec_dli_alias_creates_node(self):
        result = parse_cobol(
            _proc_program("    EXEC DLI GU EMPDB END-EXEC."),
            filename="reg.cbl",
        )
        assert result.success
        nodes = _find_nodes(result, "EXEC_IMS")
        assert nodes, "EXEC DLI alias must produce an EXEC_IMS node"

    def test_to_dict_has_required_keys(self):
        result = parse_cobol(
            _proc_program("    EXEC IMS ISRT EMPDB END-EXEC."),
            filename="reg.cbl",
        )
        d = _find_nodes(result, "EXEC_IMS")[0].to_dict()
        for key in ("node_type", "ims_command", "ims_call_type", "location"):
            assert key in d, f"to_dict() must include '{key}'"
        assert d["node_type"] == "EXEC_IMS"
        assert d["ims_command"] == "ISRT"
        assert d["ims_call_type"] == "ISRT"

    def test_multiple_ims_blocks(self):
        result = parse_cobol(
            _proc_program(
                "    EXEC IMS GU EMPDB END-EXEC.\n"
                "    EXEC IMS ISRT EMPDB END-EXEC.\n"
                "    EXEC IMS DLET EMPDB END-EXEC."
            ),
            filename="reg.cbl",
        )
        assert result.success
        nodes = _find_nodes(result, "EXEC_IMS")
        assert len(nodes) >= 3, "All three EXEC IMS blocks must produce nodes"
        commands = {n.ims_command for n in nodes}
        assert commands >= {"GU", "ISRT", "DLET"}

    def test_ibm_extensions_sample(self):
        """The ibm_extensions.cbl sample must produce EXEC_IMS nodes for GU, etc."""
        sample = Path(__file__).parent.parent / "samples" / "ibm_extensions.cbl"
        result = parse_cobol(
            sample.read_text(encoding="utf-8"), filename="ibm_extensions.cbl"
        )
        assert result.success
        nodes = _find_nodes(result, "EXEC_IMS")
        assert (
            nodes
        ), "ibm_extensions.cbl must produce EXEC_IMS nodes — was zero before fix"
        assert "GU" in {n.ims_command for n in nodes}


# ===========================================================================
# Group 4 — SPECIAL-NAMES paragraph
# ===========================================================================


def _get_special_names(result) -> dict:
    for div in result.ast.children:
        if getattr(div, "division_name", None) == "ENVIRONMENT":
            config = div.get_section_by_name("CONFIGURATION")
            if config is not None:
                return config.get_metadata("special_names") or {}
    return {}


def _env_program(special_names_body: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. REGTEST.
        ENVIRONMENT DIVISION.
        CONFIGURATION SECTION.
        SPECIAL-NAMES.
        {special_names_body}
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01 WS-X PIC X.
        PROCEDURE DIVISION.
        STOP RUN.
        """)


class TestSpecialNamesNotDropped:
    """Before the fix, _parse_configuration_section() returned {"type": "configuration"}
    with no further content; all SPECIAL-NAMES clauses were discarded."""

    def test_currency_sign_not_dropped(self):
        result = parse_cobol(
            _env_program("    CURRENCY SIGN IS 'E'."), filename="reg.cbl"
        )
        assert result.success
        sn = _get_special_names(result)
        assert sn, "special_names metadata must not be empty — was discarded before fix"
        assert (
            sn.get("currency_sign") == "E"
        ), "currency_sign must be captured — was silently dropped before fix"

    def test_decimal_point_is_comma_not_dropped(self):
        result = parse_cobol(
            _env_program("    DECIMAL-POINT IS COMMA."), filename="reg.cbl"
        )
        assert result.success
        sn = _get_special_names(result)
        assert (
            sn.get("decimal_point_is_comma") is True
        ), "decimal_point_is_comma must be True — was silently dropped before fix"

    def test_special_names_does_not_prevent_input_output_section(self):
        """SPECIAL-NAMES must not consume tokens from INPUT-OUTPUT SECTION."""
        src = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            ENVIRONMENT DIVISION.
            CONFIGURATION SECTION.
            SPECIAL-NAMES.
                CURRENCY SIGN IS '$'.
            INPUT-OUTPUT SECTION.
            FILE-CONTROL.
                SELECT EMPFILE ASSIGN TO 'EMP.DAT'.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 WS-X PIC X.
            PROCEDURE DIVISION.
            STOP RUN.
            """)
        result = parse_cobol(src, filename="reg.cbl")
        assert result.success
        env_div = next(
            (
                d
                for d in result.ast.children
                if getattr(d, "division_name", None) == "ENVIRONMENT"
            ),
            None,
        )
        assert env_div is not None
        assert env_div.has_section(
            "CONFIGURATION"
        ), "CONFIGURATION section must still exist"
        assert env_div.has_section(
            "INPUT-OUTPUT"
        ), "INPUT-OUTPUT section must not be consumed by SPECIAL-NAMES parser"

    def test_special_names_metadata_key_present(self):
        """The special_names metadata key must be accessible via get_metadata()."""
        result = parse_cobol(
            _env_program("    CURRENCY SIGN IS '$'."), filename="reg.cbl"
        )
        for div in result.ast.children:
            if getattr(div, "division_name", None) == "ENVIRONMENT":
                config = div.get_section_by_name("CONFIGURATION")
                assert config is not None
                assert (
                    config.get_metadata("special_names") is not None
                ), "get_metadata('special_names') must not return None"
                return
        pytest.fail("ENVIRONMENT division not found")

    def test_program_without_special_names_still_parses(self):
        """Removing SPECIAL-NAMES must not break programs that never had it."""
        src = textwrap.dedent("""\
            IDENTIFICATION DIVISION.
            PROGRAM-ID. REGTEST.
            DATA DIVISION.
            WORKING-STORAGE SECTION.
            01 WS-X PIC X.
            PROCEDURE DIVISION.
            STOP RUN.
            """)
        result = parse_cobol(src, filename="reg.cbl")
        assert result.success


# ===========================================================================
# Group 5 — CBL/PROCESS directives in API path
# ===========================================================================

_PROGRAM_BODY = textwrap.dedent("""\
    IDENTIFICATION DIVISION.
    PROGRAM-ID. REGTEST.
    DATA DIVISION.
    WORKING-STORAGE SECTION.
    01 WS-X PIC X.
    PROCEDURE DIVISION.
    STOP RUN.
    """)


class TestCblProcessDirectivesInApiPath:
    """Before the fix, strip_compiler_directives() was only called from the CLI.
    Calling parse_cobol() directly with CBL/PROCESS lines failed with parse errors."""

    def test_cbl_directive_via_api_succeeds(self):
        src = "       CBL RENT,APOST\n" + _PROGRAM_BODY
        result = parse_cobol(src, filename="reg.cbl")
        assert result.success, (
            f"parse_cobol() must succeed with CBL directive — was broken before fix. "
            f"Errors: {result.errors}"
        )

    def test_cbl_directive_via_api_no_errors(self):
        src = "       CBL RENT,APOST\n" + _PROGRAM_BODY
        result = parse_cobol(src, filename="reg.cbl")
        assert not result.errors, (
            f"parse_cobol() must produce zero errors with CBL directive. "
            f"Got: {result.errors}"
        )

    def test_process_directive_via_api_succeeds(self):
        src = "       PROCESS RENT,APOST\n" + _PROGRAM_BODY
        result = parse_cobol(src, filename="reg.cbl")
        assert result.success, (
            f"parse_cobol() must succeed with PROCESS directive — was broken before fix. "
            f"Errors: {result.errors}"
        )

    def test_multiple_cbl_directives_via_api(self):
        src = "       CBL RENT\n       CBL APOST\n" + _PROGRAM_BODY
        result = parse_cobol(src, filename="reg.cbl")
        assert result.success

    def test_cbl_directive_ast_is_not_none(self):
        """The AST must be populated, not just result.success=True with a None ast."""
        src = "       CBL RENT,APOST\n" + _PROGRAM_BODY
        result = parse_cobol(src, filename="reg.cbl")
        assert (
            result.ast is not None
        ), "ast must not be None when CBL directive is stripped"

    def test_program_without_directive_unaffected(self):
        """The fix must not break programs that have no CBL/PROCESS lines."""
        result = parse_cobol(_PROGRAM_BODY, filename="reg.cbl")
        assert result.success


# ===========================================================================
# Group 6 — MOVE / SUBTRACT swallowing a following un-punctuated statement
# ===========================================================================


def _statement_type_names(result) -> list:
    return [type(s).__name__ for s in result.ast.get_all_statements()]


def _first_of_type(result, type_name: str):
    return next(
        s for s in result.ast.get_all_statements() if type(s).__name__ == type_name
    )


class TestMoveDoesNotSwallowFollowingExecSql:
    """Before the fix, MoveStatementParser's target-collection loop used a
    hand-rolled stop-keyword list that didn't include EXEC/EXECUTE (unlike
    the shared STATEMENT_TOKEN_TYPES/STATEMENT_KEYWORDS every other
    statement parser uses). A MOVE with no trailing period, immediately
    followed by EXEC SQL, had the EXEC/SQL tokens silently swallowed as
    bogus MOVE targets — the whole EXEC SQL...END-EXEC block vanished from
    the AST with no error reported."""

    _SRC = (
        "    MOVE WS-X TO WS-X\n"
        "    EXEC SQL\n"
        "        UPDATE T SET COL = :WS-X\n"
        "        WHERE ID = :WS-X\n"
        "    END-EXEC\n"
    )

    def test_exec_sql_statement_exists(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert result.success
        names = _statement_type_names(result)
        assert "ExecSQLStatement" in names, (
            "EXEC SQL statement must exist — was dropped before fix. "
            f"Statements found: {names}"
        )

    def test_no_bogus_set_statement(self):
        """The SQL SET clause must not be misparsed as a COBOL SET statement."""
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert "SetStatement" not in _statement_type_names(result)

    def test_move_targets_not_contaminated(self):
        """The MOVE's own targets must be exactly what was written — no
        leaked EXEC SQL tokens."""
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        move_stmts = [
            s
            for s in result.ast.get_all_statements()
            if type(s).__name__ == "MoveStatement"
        ]
        assert len(move_stmts) == 1
        assert move_stmts[0].targets == ["WS-X"]


class TestSubtractDoesNotSwallowFollowingExecSql:
    """Before the fix, SUBTRACT (and MULTIPLY/DIVIDE, which share the same
    helper) ended their parse with skip_to_period(), which blindly consumed
    every token up to the next period regardless of statement boundaries.
    A SUBTRACT with no trailing period, immediately followed by EXEC SQL,
    had the entire EXEC SQL block eaten — stopping only at a coincidental
    period inside a qualified SQL table name (e.g. BANK.ACCOUNT) — after
    which the remaining SQL SET clause was misparsed as a COBOL SET
    statement."""

    _SRC = (
        "    SUBTRACT WS-X FROM WS-X\n"
        "    EXEC SQL\n"
        "        UPDATE BANK.ACCOUNT\n"
        "        SET COL = :WS-X\n"
        "        WHERE ID = :WS-X\n"
        "    END-EXEC\n"
    )

    def test_exec_sql_statement_exists(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert result.success
        names = _statement_type_names(result)
        assert "ExecSQLStatement" in names, (
            "EXEC SQL statement must exist — was dropped before fix. "
            f"Statements found: {names}"
        )

    def test_no_bogus_set_statement(self):
        """The SQL SET clause must not be misparsed as a COBOL SET statement."""
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert "SetStatement" not in _statement_type_names(result)


class TestArithmeticSizeErrorClausesNowCaptured:
    """SUBTRACT/MULTIPLY/DIVIDE now call parse_size_error_clauses (as
    ADD/COMPUTE already did) instead of the deleted skip_to_period(), so
    they correctly populate on_size_error/not_on_size_error instead of
    silently discarding the clause content."""

    def test_subtract_on_size_error_and_not_on_size_error_both_captured(self):
        """Regression for the _parse_size_error_stmts DISPLAY-boundary bug:
        before the fix, a DISPLAY inside ON SIZE ERROR swallowed the
        following NOT ON SIZE ERROR keywords as bogus display items, so the
        NOT ON SIZE ERROR clause was never recognized as a separate clause."""
        result = parse_cobol(
            _proc_program(
                "    SUBTRACT WS-X FROM WS-X\n"
                "        ON SIZE ERROR\n"
                "            DISPLAY 'OVERFLOW'\n"
                "        NOT ON SIZE ERROR\n"
                "            DISPLAY 'OK'\n"
                "    END-SUBTRACT\n"
            ),
            filename="reg.cbl",
        )
        assert result.success, f"Errors: {result.errors}"
        stmt = next(
            s
            for s in result.ast.get_all_statements()
            if type(s).__name__ == "SubtractStatement"
        )
        assert stmt.on_size_error is not None
        assert stmt.not_on_size_error is not None

    def test_multiply_on_size_error_captured(self):
        result = parse_cobol(
            _proc_program(
                "    MULTIPLY WS-X BY WS-X GIVING WS-X\n"
                "        ON SIZE ERROR\n"
                "            DISPLAY 'OVERFLOW'\n"
                "    END-MULTIPLY\n"
            ),
            filename="reg.cbl",
        )
        assert result.success, f"Errors: {result.errors}"
        stmt = next(
            s
            for s in result.ast.get_all_statements()
            if type(s).__name__ == "MultiplyStatement"
        )
        assert stmt.on_size_error is not None

    def test_divide_by_zero_figurative_constant_parses(self):
        """Regression for ARITHMETIC_OPERAND_TOKEN_TYPES missing
        FIGURATIVE_CONSTANT — DIVIDE ... BY ZERO previously failed with
        'DIVIDE BY requires a second operand' (only ever reached once the
        swallow-bug fixes above stopped an earlier statement from silently
        eating past it)."""
        result = parse_cobol(
            _proc_program("    DIVIDE WS-X BY ZERO GIVING WS-X\n"),
            filename="reg.cbl",
        )
        assert result.success, f"Errors: {result.errors}"


class TestComputeDoesNotSwallowFollowingCall:
    """ComputeStatementParser's expression-collection loop only stopped at a
    period or at ON/NOT/END-COMPUTE (paren_depth == 0) — unlike the shared
    parse_arithmetic_operands() helper used by ADD/SUBTRACT/MULTIPLY/DIVIDE,
    it never checked STATEMENT_KEYWORDS/CONTROL_FLOW_BOUNDARIES. A COMPUTE
    with no trailing period, immediately followed by another statement
    (e.g. a multi-line CALL), had that statement's tokens silently
    swallowed into the COMPUTE expression string — the following statement
    vanished from the AST entirely."""

    _SRC = (
        "    COMPUTE WS-X = WS-X + WS-X\n"
        "    CALL 'MQOPEN' USING\n"
        "        WS-X\n"
        "        WS-X\n"
        "    END-CALL\n"
    )

    def test_call_statement_exists(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert result.success, f"Errors: {result.errors}"
        names = _statement_type_names(result)
        assert "CallStatement" in names, (
            "CALL statement must exist — was swallowed into the COMPUTE "
            f"expression before fix. Statements found: {names}"
        )

    def test_compute_expression_not_contaminated(self):
        """The COMPUTE's own expression must be exactly what was written —
        no leaked CALL tokens."""
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        stmt = next(
            s
            for s in result.ast.get_all_statements()
            if type(s).__name__ == "ComputeStatement"
        )
        assert "CALL" not in stmt.expression.upper()


class TestComputeDoesNotSwallowEnclosingScopeTerminator:
    """Same bug class as above, different trigger: a COMPUTE nested inside a
    clause body (e.g. READ ... AT END) with no trailing period before the
    enclosing scope terminator had that terminator (and the fact that the
    clause ever ended) silently swallowed into the expression string,
    because the expression loop checked STATEMENT_KEYWORDS/
    CONTROL_FLOW_BOUNDARIES but not SCOPE_TERMINATORS."""

    _SRC = (
        "    READ WS-X\n"
        "        AT END\n"
        "            COMPUTE WS-X = WS-X + WS-X\n"
        "    END-READ\n"
    )

    def test_read_statement_exists(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert result.success, f"Errors: {result.errors}"
        names = _statement_type_names(result)
        assert "IOReadStatement" in names, (
            "READ statement must exist. " f"Statements found: {names}"
        )

    def test_compute_expression_not_contaminated_by_end_read(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        stmt = next(
            s
            for s in result.ast.get_all_statements()
            if type(s).__name__ == "ComputeStatement"
        )
        assert "END-READ" not in stmt.expression.upper()


# ===========================================================================
# Group 7 — INSPECT / STRING / UNSTRING swallowing a following statement
# ===========================================================================
#
# When these statements are not terminated by a period (a legal COBOL
# sentence may contain several statements with no separating period), the
# parser consumed the *following* statement instead of stopping at its
# boundary — INSPECT's trailing "consume to period" loop, and the STRING /
# UNSTRING main-loop `else: consume()` fall-through, never consulted the
# STATEMENT_KEYWORDS / SCOPE_TERMINATORS / CONTROL_FLOW_BOUNDARIES guards
# that MOVE / arithmetic parsers already use. Audit 2026-07-06 H2.


class TestInspectDoesNotSwallowFollowingStatement:
    """INSPECT with no trailing period, immediately followed by another
    statement, previously ran its trailing "consume to period" loop straight
    through the following statement (and every statement up to the next
    period), so both the DISPLAY and the STOP RUN vanished from the AST with
    errors=0."""

    _SRC = "    INSPECT WS-X TALLYING WS-X FOR ALL 'A'\n" "    DISPLAY 'SENTINEL'\n"

    def test_following_display_survives(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert result.success, f"Errors: {result.errors}"
        names = _statement_type_names(result)
        assert "DisplayStatement" in names, (
            "DISPLAY after an un-punctuated INSPECT must survive — was "
            f"swallowed before fix. Statements found: {names}"
        )

    def test_stop_run_after_it_also_survives(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert "StopStatement" in _statement_type_names(result)

    def test_inspect_still_parsed(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert "InspectStatement" in _statement_type_names(result)

    def test_inspect_content_not_contaminated(self):
        """The INSPECT must not have absorbed any fragment of the following
        DISPLAY (it breaks *before* consuming the boundary token)."""
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        stmt = _first_of_type(result, "InspectStatement")
        blob = str(stmt.to_dict()).upper()
        assert "SENTINEL" not in blob
        assert "DISPLAY" not in blob

    def test_tallying_replacing_combined_form_stops_at_boundary(self):
        """The combined TALLYING ... REPLACING form (which re-enters
        _parse_replacing via the trailing loop's `continue`) must still stop
        at a following statement rather than swallow it."""
        src = (
            "    INSPECT WS-X TALLYING WS-X FOR ALL 'A' "
            "REPLACING ALL 'B' BY 'C'\n"
            "    DISPLAY 'SENTINEL'\n"
        )
        result = parse_cobol(_proc_program(src), filename="reg.cbl")
        assert result.success, f"Errors: {result.errors}"
        names = _statement_type_names(result)
        assert "InspectStatement" in names
        assert "DisplayStatement" in names, (
            "DISPLAY after a combined TALLYING/REPLACING INSPECT must survive. "
            f"Found: {names}"
        )
        stmt = _first_of_type(result, "InspectStatement")
        assert "SENTINEL" not in str(stmt.to_dict()).upper()


class TestStringDoesNotSwallowFollowingStatement:
    """STRING with no trailing period / END-STRING, immediately followed by
    another statement, previously fell to the main loop's `else: consume()`
    and ate the following statement's tokens up to the next period."""

    _SRC = "    STRING WS-X DELIMITED BY SIZE INTO WS-X\n" "    DISPLAY 'SENTINEL'\n"

    def test_following_display_survives(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert result.success, f"Errors: {result.errors}"
        names = _statement_type_names(result)
        assert "DisplayStatement" in names, (
            "DISPLAY after an un-punctuated STRING must survive — was "
            f"swallowed before fix. Statements found: {names}"
        )

    def test_string_still_parsed(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert "StringStatement" in _statement_type_names(result)

    def test_string_content_not_contaminated(self):
        """The STRING must not have absorbed any fragment of the following
        DISPLAY as a bogus operand / target."""
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        stmt = _first_of_type(result, "StringStatement")
        blob = str(stmt.to_dict()).upper()
        assert "SENTINEL" not in blob
        assert "DISPLAY" not in blob

    def test_string_does_not_swallow_enclosing_end_if(self):
        """A STRING as the last statement of an IF THEN branch (no period)
        must not swallow the END-IF that closes the IF."""
        src = (
            "    IF WS-X = 'Y'\n"
            "        STRING WS-X DELIMITED BY SIZE INTO WS-X\n"
            "    END-IF\n"
            "    DISPLAY 'AFTER'\n"
        )
        result = parse_cobol(_proc_program(src), filename="reg.cbl")
        assert result.success, f"Errors: {result.errors}"
        names = _statement_type_names(result)
        assert "IfStatement" in names
        assert "DisplayStatement" in names, (
            "DISPLAY after the END-IF must survive — the STRING swallowed "
            f"END-IF and everything after it before fix. Found: {names}"
        )


class TestUnstringDoesNotSwallowFollowingStatement:
    """UNSTRING with no trailing period / END-UNSTRING, immediately followed
    by another statement, previously ate it via the main loop's
    `else: consume()` fall-through."""

    _SRC = "    UNSTRING WS-X DELIMITED BY ',' INTO WS-X\n" "    DISPLAY 'SENTINEL'\n"

    def test_following_display_survives(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert result.success, f"Errors: {result.errors}"
        names = _statement_type_names(result)
        assert "DisplayStatement" in names, (
            "DISPLAY after an un-punctuated UNSTRING must survive — was "
            f"swallowed before fix. Statements found: {names}"
        )

    def test_unstring_still_parsed(self):
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        assert "UnstringStatement" in _statement_type_names(result)

    def test_unstring_content_not_contaminated(self):
        """The UNSTRING must not have absorbed any fragment of the following
        DISPLAY as a bogus INTO target."""
        result = parse_cobol(_proc_program(self._SRC), filename="reg.cbl")
        stmt = _first_of_type(result, "UnstringStatement")
        blob = str(stmt.to_dict()).upper()
        assert "SENTINEL" not in blob
        assert "DISPLAY" not in blob


# ===========================================================================
# Group 8 — EXEC SQL/CICS/IMS missing END-EXEC now reports an error
# ===========================================================================
#
# END-EXEC is the mandatory delimiter of an embedded EXEC block. Without it,
# collect_exec_sql_text() consumed the entire rest of the program as SQL text
# and returned errors=0 (silent, catastrophic data loss). Embedded SQL text
# legitimately contains COBOL statement keywords (SET / DELETE / UPDATE /
# CALL / OPEN / CLOSE), so the block cannot be bounded by a content heuristic
# the way INSPECT/STRING/UNSTRING are — the correct behavior for the
# malformed case is to surface a parse error. Well-formed blocks (with
# END-EXEC) are unaffected. Audit 2026-07-06 H2.


class TestExecMissingEndExecReportsError:
    def test_exec_sql_missing_end_exec_reports_error(self):
        src = "    EXEC SQL SELECT COL INTO :WS-X FROM T\n" "    DISPLAY 'AFTER'.\n"
        result = parse_cobol(_proc_program(src), filename="reg.cbl")
        assert not result.success, "missing END-EXEC must not report success"
        assert result.errors, "missing END-EXEC must produce a parse error"
        assert any(
            "END-EXEC" in str(e) for e in result.errors
        ), f"error must name END-EXEC; got {[str(e) for e in result.errors]}"

    def test_exec_cics_missing_end_exec_reports_error(self):
        src = "    EXEC CICS READ FILE('F') INTO(WS-X)\n" "    DISPLAY 'AFTER'.\n"
        result = parse_cobol(_proc_program(src), filename="reg.cbl")
        assert not result.success
        assert result.errors

    def test_exec_ims_missing_end_exec_reports_error(self):
        src = "    EXEC IMS GU EMPDB\n" "    DISPLAY 'AFTER'.\n"
        result = parse_cobol(_proc_program(src), filename="reg.cbl")
        assert not result.success
        assert result.errors

    def test_well_formed_exec_sql_still_succeeds(self):
        """The fix must not flag correctly-terminated EXEC blocks."""
        src = (
            "    EXEC SQL SELECT COL INTO :WS-X FROM T END-EXEC\n"
            "    DISPLAY 'AFTER'\n"
        )
        result = parse_cobol(_proc_program(src), filename="reg.cbl")
        assert result.success, f"well-formed EXEC must not error: {result.errors}"

    def test_well_formed_exec_sql_with_sql_keywords_survives(self):
        """A terminated block whose SQL contains COBOL-keyword-like words
        (SET/UPDATE) must be collected in full and report no error."""
        src = (
            "    EXEC SQL UPDATE BANK.ACCOUNT SET COL = 1 END-EXEC\n"
            "    DISPLAY 'AFTER'\n"
        )
        result = parse_cobol(_proc_program(src), filename="reg.cbl")
        assert result.success, f"Errors: {result.errors}"
        exec_nodes = result.ast.find_all_by_type("ExecSQLStatement")
        assert exec_nodes, "EXEC SQL node must exist"


# ===========================================================================
# Group 9 — ROUNDED after GIVING on MULTIPLY/DIVIDE was silently dropped
# ===========================================================================
#
# _parse_binary_arithmetic() (shared by MultiplyStatementParser and
# DivideStatementParser) called parse_size_error_clauses() right after the
# optional GIVING clause. That helper only recognizes ON SIZE ERROR / NOT ON
# SIZE ERROR / PERIOD / NEWLINE -- any other token (including ROUNDED) hits
# its `else: break` and is left UNCONSUMED in the stream, with no error or
# warning. The leftover ROUNDED token (followed by the statement's own
# trailing period) then gets misread by the paragraph-boundary lookahead as
# a new paragraph header ("ROUNDED."), silently reparenting every subsequent
# statement in the real paragraph under this phantom "ROUNDED" paragraph
# until the next genuine paragraph/section header. mocky-mock's own
# reachability BFS depends on correct paragraph attribution, so this isn't
# cosmetic: a MOCK'd CALL placed after a ROUNDED DIVIDE in the same
# paragraph becomes unreachable from that paragraph's real name.


class TestDivideRoundedClauseCaptured:
    def test_divide_giving_rounded_does_not_create_phantom_paragraph(self):
        """Before the fix, the statement after DIVIDE ... GIVING ... ROUNDED
        in the same paragraph was silently reparented under a phantom
        paragraph literally named "ROUNDED"."""
        result = parse_cobol(
            _proc_program(
                "    DIVIDE WS-X BY WS-X GIVING WS-X ROUNDED.\n" "    DISPLAY 'AFTER'\n"
            ),
            filename="reg.cbl",
        )
        assert result.success, f"Errors: {result.errors}"
        proc = result.ast.get_division("PROCEDURE")
        names = [p.paragraph_name for p in proc.paragraphs]
        assert (
            "ROUNDED" not in names
        ), f"ROUNDED must not be parsed as its own paragraph; got {names}"
        main_para = next(p for p in proc.paragraphs if p.paragraph_name == "MAIN-PARA")
        stmt_types = [type(s).__name__ for s in main_para.statements]
        assert "DisplayStatement" in stmt_types, (
            "DISPLAY must stay attributed to MAIN-PARA, not swallowed into "
            f"a phantom paragraph; MAIN-PARA statements were {stmt_types}"
        )

    def test_divide_giving_rounded_sets_rounded_flag(self):
        result = parse_cobol(
            _proc_program("    DIVIDE WS-X BY WS-X GIVING WS-X ROUNDED.\n"),
            filename="reg.cbl",
        )
        assert result.success, f"Errors: {result.errors}"
        stmt = _first_of_type(result, "DivideStatement")
        assert stmt.rounded is True

    def test_divide_giving_without_rounded_leaves_flag_false(self):
        result = parse_cobol(
            _proc_program("    DIVIDE WS-X BY WS-X GIVING WS-X.\n"),
            filename="reg.cbl",
        )
        assert result.success, f"Errors: {result.errors}"
        stmt = _first_of_type(result, "DivideStatement")
        assert stmt.rounded is False

    def test_divide_into_rounded_without_giving_sets_rounded_flag(self):
        """ROUNDED is also legal directly after the INTO target with no
        GIVING clause at all (DIVIDE x INTO y ROUNDED)."""
        result = parse_cobol(
            _proc_program("    DIVIDE WS-X INTO WS-X ROUNDED.\n"),
            filename="reg.cbl",
        )
        assert result.success, f"Errors: {result.errors}"
        stmt = _first_of_type(result, "DivideStatement")
        assert stmt.rounded is True

    def test_multiply_giving_rounded_sets_rounded_flag(self):
        """MULTIPLY shares _parse_binary_arithmetic with DIVIDE, so it has
        the exact same bug and fix."""
        result = parse_cobol(
            _proc_program("    MULTIPLY WS-X BY WS-X GIVING WS-X ROUNDED.\n"),
            filename="reg.cbl",
        )
        assert result.success, f"Errors: {result.errors}"
        stmt = _first_of_type(result, "MultiplyStatement")
        assert stmt.rounded is True
