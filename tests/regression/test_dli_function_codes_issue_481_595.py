"""Regression tests for issues #481 and #595: one DL/I vocabulary.

#481: the parser's ``_IMS_CALL_TYPES`` disagreed with the dialect's
``IMS_COMMANDS``: ``EXEC DLI ROLB`` / ``LOAD`` / ``SCHD`` got
``ims_call_type == "UNKNOWN"`` while the non-command ``XDLT`` was accepted.

#595: ``IMSSegmentAnalyzer`` kept a third, incomplete list and dropped every
candidate value outside it, so a function variable set to ``'GU'`` and later
to ``'CHNG'`` / ``'ROLB'`` was reported as plain ``GU`` at every CALL; with
``VALUE SPACES`` the figurative was kept as the word ``SPACES``.
"""

import pytest

from cobolparser import parse_cobol
from cobolparser.analysis import IMSSegmentAnalyzer, ims_segment_analyzer
from cobolparser.dialects.ibm_enterprise import IBMEnterpriseCobol
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements import ibm_exec_statements

# ── #481: EXEC DLI command words ─────────────────────────────────────────────


def _exec_dli_call_type(command: str) -> str:
    source = f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. T.
       PROCEDURE DIVISION.
           EXEC DLI {command} END-EXEC.
           GOBACK.
"""
    result = parse_cobol(source)
    assert result.errors == []
    (stmt,) = result.ast.find_all_by_type("ExecImsStatement")
    return stmt.ims_call_type


@pytest.mark.parametrize(
    "command",
    [
        "GU",
        "GN",
        "GNP",
        "ISRT",
        "REPL",
        "DLET",
        "LOAD",
        "SCHD",
        "TERM",
        "ROLB",
        "ROLS",
        "SYMCHKP",
        "CHKP",
        "XRST",
        "QUERY",
        "RETRIEVE",
        "DEQ",
    ],
)
def test_exec_dli_commands_are_recognised(command):
    assert _exec_dli_call_type(command) == command


@pytest.mark.parametrize("command", ["XDLT", "XRPL", "ROLLB"])
def test_non_commands_stay_unknown(command):
    assert _exec_dli_call_type(command) == "UNKNOWN"


def test_exec_dli_has_no_hold_forms():
    # Holds are implicit in EXEC DLI; GHU is a CALL function code only.
    assert _exec_dli_call_type("GHU") == "UNKNOWN"
    assert "GHU" in IBMEnterpriseCobol.IMS_COMMANDS


@pytest.mark.parametrize(
    "command", ["GU", "ISRT", "LOAD", "SCHD", "SYMCHKP", "GHU", "CHNG", "XDLT"]
)
def test_dialect_exec_ims_node_agrees_with_the_parser_node(command):
    # The dialect's EXEC-IMS node classified against the CALL function codes,
    # so it called GHU known and LOAD unknown -- the opposite of the parser's
    # node for the same EXEC DLI text (#481).
    dialect_node = IBMEnterpriseCobol().parse_exec_ims(command, SourceLocation(1, 1))
    assert dialect_node.ims_call_type == _exec_dli_call_type(command)


def test_dialect_exec_ims_node_uses_the_exec_dli_vocabulary():
    dialect = IBMEnterpriseCobol()
    assert dialect.parse_exec_ims("LOAD", SourceLocation(1, 1)).ims_call_type == (
        "LOAD"
    )
    assert dialect.parse_exec_ims("GHU", SourceLocation(1, 1)).ims_call_type == (
        "UNKNOWN"
    )


def test_parser_and_analyzer_read_the_dialect_lists():
    assert ibm_exec_statements._IMS_CALL_TYPES is IBMEnterpriseCobol.EXEC_DLI_COMMANDS
    assert ims_segment_analyzer._IMS_FUNCTION_CODES is IBMEnterpriseCobol.IMS_COMMANDS


@pytest.mark.parametrize(
    "code",
    [
        "ROLB",
        "ROLL",
        "ROLS",
        "CHNG",
        "CMD",
        "GCMD",
        "INQY",
        "LOG",
        "SETS",
        "SETU",
        "STAT",
        "SYNC",
        "AUTH",
        "INIT",
        "ICAL",
        "PURG",
        "GHNP",
    ],
)
def test_dli_call_function_codes_are_complete(code):
    assert IBMEnterpriseCobol().is_ims_command(code) is True


def test_rollb_is_not_a_dli_call():
    assert IBMEnterpriseCobol().is_ims_command("ROLLB") is False


# ── #595: CALL 'CBLTDLI' function-code resolution ────────────────────────────


def _function_codes(value_clause: str, *moves: str) -> list[str | None]:
    calls = "".join(
        f"           MOVE '{code}' TO FUNC.\n"
        "           CALL 'CBLTDLI' USING FUNC IOPCB IOA.\n"
        for code in moves
    )
    source = f"""\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMS3.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 FUNC PIC X(4) {value_clause}.
       01 IOA PIC X(100).
       LINKAGE SECTION.
       01 IOPCB PIC X(40).
       PROCEDURE DIVISION.
           ENTRY 'DLITCBL' USING IOPCB.
           CALL 'CBLTDLI' USING FUNC IOPCB IOA.
{calls}           GOBACK.
"""
    result = parse_cobol(source)
    assert result.errors == []
    return [call.function_code for call in IMSSegmentAnalyzer().analyze(result.ast)]


def test_no_valid_code_is_filtered_out():
    assert _function_codes("VALUE 'GU  '", "CHNG", "ROLB") == ["CHNG/GU/ROLB"] * 3


def test_value_spaces_is_not_the_word_spaces():
    assert _function_codes("VALUE SPACES", "CHNG", "ROLB") == ["CHNG/ROLB"] * 3


def test_only_blank_values_resolve_to_nothing():
    assert _function_codes("VALUE SPACES") == [None]


def test_single_value_still_resolves_to_itself():
    assert _function_codes("VALUE 'ISRT'") == ["ISRT"]


def test_inline_literal_of_a_newly_listed_code():
    source = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. IMS4.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 IOA PIC X(100).
       LINKAGE SECTION.
       01 IOPCB PIC X(40).
       PROCEDURE DIVISION.
           ENTRY 'DLITCBL' USING IOPCB.
           CALL 'CBLTDLI' USING 'ROLB' IOPCB IOA.
           GOBACK.
"""
    result = parse_cobol(source)
    assert result.errors == []
    (call,) = IMSSegmentAnalyzer().analyze(result.ast)
    assert call.function_code == "ROLB"
