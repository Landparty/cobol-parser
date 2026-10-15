"""Parser-level tests for EXEC CICS and EXEC IMS statement parsing.

Prior to the fix:
- EXEC CICS produced a node with only node_type + location; command and options were lost.
- EXEC IMS had no parser at all; blocks were silently consumed token-by-token.
"""

import textwrap

from cobolparser import parse_cobol


def _minimal_program(procedure_body: str) -> str:
    return textwrap.dedent(f"""\
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TESTPROG.
        DATA DIVISION.
        WORKING-STORAGE SECTION.
        01  WS-RESP PIC S9(8) COMP.
        PROCEDURE DIVISION.
        MAIN-PARA.
        {procedure_body}
            STOP RUN.
        """)


def _find_nodes(result, node_type: str) -> list:
    return result.ast.find_all_by_type(node_type)


# ---------------------------------------------------------------------------
# EXEC CICS — command captured
# ---------------------------------------------------------------------------


def test_exec_cics_read_command_captured():
    src = _minimal_program("    EXEC CICS READ FILE('EMPFILE') INTO(WS-REC) END-EXEC.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    nodes = _find_nodes(result, "EXEC_CICS")
    assert nodes, "No EXEC_CICS node found"
    node = nodes[0]
    assert node.cics_command == "READ"


def test_exec_cics_send_map_command_captured():
    src = _minimal_program(
        "    EXEC CICS SEND MAP('EMPMAP') MAPSET('EMPSET') END-EXEC."
    )
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    nodes = _find_nodes(result, "EXEC_CICS")
    assert nodes
    assert nodes[0].cics_command == "SEND"


def test_exec_cics_return_command_captured():
    src = _minimal_program("    EXEC CICS RETURN TRANSID('EMP1') END-EXEC.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    nodes = _find_nodes(result, "EXEC_CICS")
    assert nodes
    assert nodes[0].cics_command == "RETURN"


def test_exec_cics_text_contains_options():
    src = _minimal_program("    EXEC CICS READ FILE('EMPFILE') INTO(WS-REC) END-EXEC.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    node = _find_nodes(result, "EXEC_CICS")[0]
    assert "EMPFILE" in node.cics_text or "FILE" in node.cics_text


def test_exec_cics_to_dict_has_command():
    src = _minimal_program("    EXEC CICS WRITE FILE('EMPFILE') FROM(WS-REC) END-EXEC.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    node = _find_nodes(result, "EXEC_CICS")[0]
    d = node.to_dict()
    assert d["cics_command"] == "WRITE"
    assert "cics_text" in d


def test_exec_cics_literal_options_tell_literal_from_data_name():
    # options holds both unquoted; literal_options is what tells a program
    # name (PROGRAM('X')) from a data-name holding one (PROGRAM(WS-X)).
    src = _minimal_program(
        "    EXEC CICS LINK PROGRAM('SUBPGM') COMMAREA(WS-RESP)\n"
        "        LENGTH(4) END-EXEC.\n"
        "            EXEC CICS XCTL PROGRAM(WS-RESP) END-EXEC."
    )
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    link, xctl = _find_nodes(result, "EXEC_CICS")
    assert link.options["PROGRAM"] == "SUBPGM"
    assert link.literal_options == {"PROGRAM"}
    assert xctl.options["PROGRAM"] == "WS-RESP"
    assert xctl.literal_options == set()
    # The text and the dict keep their historical, unquoted shape.
    assert "'" not in link.cics_text
    assert "literal_options" not in link.to_dict()


# ---------------------------------------------------------------------------
# EXEC IMS — new parser
# ---------------------------------------------------------------------------


def test_exec_ims_gu_creates_node():
    src = _minimal_program("    EXEC IMS GU EMPDB END-EXEC.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    nodes = _find_nodes(result, "EXEC_IMS")
    assert nodes, "No EXEC-IMS node found after fix"


def test_exec_ims_command_captured():
    src = _minimal_program("    EXEC IMS GU EMPDB END-EXEC.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    node = _find_nodes(result, "EXEC_IMS")[0]
    assert node.ims_command == "GU"
    assert node.ims_call_type == "GU"


def test_exec_ims_isrt_command():
    src = _minimal_program("    EXEC IMS ISRT EMPDB END-EXEC.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    node = _find_nodes(result, "EXEC_IMS")[0]
    assert node.ims_command == "ISRT"
    assert node.ims_call_type == "ISRT"


def test_exec_ims_dlet_command():
    src = _minimal_program("    EXEC IMS DLET EMPDB END-EXEC.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    node = _find_nodes(result, "EXEC_IMS")[0]
    assert node.ims_command == "DLET"


def test_exec_ims_to_dict():
    src = _minimal_program("    EXEC IMS GU EMPDB END-EXEC.")
    result = parse_cobol(src, filename="test.cbl")
    assert result.success

    node = _find_nodes(result, "EXEC_IMS")[0]
    d = node.to_dict()
    assert d["ims_command"] == "GU"
    assert d["ims_call_type"] == "GU"


def test_exec_ims_ibm_extensions_sample():
    """ibm_extensions.cbl has EXEC IMS GU, GN, ISRT, DLET, REPL blocks."""
    from pathlib import Path

    sample = Path(__file__).parent.parent / "samples" / "ibm_extensions.cbl"
    result = parse_cobol(
        sample.read_text(encoding="utf-8"), filename="ibm_extensions.cbl"
    )
    assert result.success

    nodes = _find_nodes(result, "EXEC_IMS")
    assert nodes, "Expected EXEC IMS nodes from ibm_extensions.cbl"
    commands = {n.ims_command for n in nodes}
    assert "GU" in commands
