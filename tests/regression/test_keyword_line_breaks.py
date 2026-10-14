"""A line break between two keywords must not change the AST (issue #385).

Several lookaheads used a bare ``peek()`` / ``peek(1)`` that saw the NEWLINE
token instead of the next word, so ``STOP <newline> RUN.`` produced a
paragraph named RUN, ``WHEN <newline> OTHER`` a literal selector, ``EXEC
<newline> CICS`` an EXEC SQL statement, and so on. Each case below parses
the same program twice -- once with the gap on one line, once with a line
break in it -- and requires the two ASTs to be identical apart from
source locations.
"""

from __future__ import annotations

from typing import Any

import pytest

from cobolparser import parse_cobol

# Keys whose values legitimately differ when a token moves to a new line.
_LOCATION_KEYS = {"location", "line", "column", "end_line", "end_column", "total_lines"}


def _strip_locations(node: Any) -> Any:
    if isinstance(node, dict):
        return {
            k: _strip_locations(v) for k, v in node.items() if k not in _LOCATION_KEYS
        }
    if isinstance(node, list):
        return [_strip_locations(v) for v in node]
    return node


def _program(env: str = "", data: str = "", decl: str = "", proc: str = "") -> str:
    return (
        "IDENTIFICATION DIVISION.\n"
        "PROGRAM-ID. T1.\n"
        "ENVIRONMENT DIVISION.\n"
        f"{env}\n"
        "DATA DIVISION.\n"
        f"{data}\n"
        "PROCEDURE DIVISION.\n"
        f"{decl}\n"
        f"{proc}\n"
    )


# ``~`` marks the gap that is either joined (one line) or broken (two lines).
CASES: dict[str, dict[str, str]] = {
    "stop-run": {"proc": "MAIN-PARA.\n    DISPLAY 'A'\n    STOP ~ RUN."},
    "stop-literal": {
        "proc": "MAIN-PARA.\n    STOP ~ 'X'.\n    DISPLAY 'B'.\n    STOP RUN."
    },
    "when-other": {
        "data": "WORKING-STORAGE SECTION.\n01 X PIC 9.",
        "proc": (
            "MAIN-PARA.\n    EVALUATE X\n      WHEN 1 DISPLAY 'A'\n"
            "      WHEN ~ OTHER DISPLAY 'B'\n    END-EVALUATE\n    STOP RUN."
        ),
    },
    "88-name": {
        "data": "WORKING-STORAGE SECTION.\n01 X PIC 9.\n   88 ~ DONE VALUE 1.",
        "proc": "MAIN-PARA.\n    IF DONE DISPLAY 'A' END-IF\n    STOP RUN.",
    },
    "88-values-are": {
        "data": (
            "WORKING-STORAGE SECTION.\n01 X PIC X.\n"
            "   88 XV VALUES ~ ARE 'A' THRU 'C' FALSE 'Z'."
        ),
        "proc": "MAIN-PARA.\n    STOP RUN.",
    },
    "66-name": {
        "data": (
            "WORKING-STORAGE SECTION.\n01 R.\n   05 A PIC X.\n   05 B PIC X.\n"
            "66 ~ AB RENAMES A THRU B."
        ),
        "proc": "MAIN-PARA.\n    STOP RUN.",
    },
    "fd-name": {
        "env": "INPUT-OUTPUT SECTION.\nFILE-CONTROL.\n    SELECT F1 ASSIGN TO 'F1'.",
        "data": "FILE SECTION.\nFD ~ F1 RECORDING MODE F.\n01 R1 PIC X(10).",
        "proc": "MAIN-PARA.\n    OPEN INPUT F1 CLOSE F1\n    STOP RUN.",
    },
    "sd-name": {
        "env": (
            "INPUT-OUTPUT SECTION.\nFILE-CONTROL.\n    SELECT F1 ASSIGN TO 'F1'.\n"
            "    SELECT S1 ASSIGN TO 'S1'."
        ),
        "data": "FILE SECTION.\nFD F1.\n01 R1 PIC X(10).\nSD ~ S1.\n01 SR PIC X(10).",
        "proc": "MAIN-PARA.\n    STOP RUN.",
    },
    "call-on-exception": {
        "proc": (
            "MAIN-PARA.\n    CALL 'SUB' ON ~ EXCEPTION DISPLAY 'E' END-CALL\n"
            "    STOP RUN."
        )
    },
    "call-on-overflow": {
        "proc": (
            "MAIN-PARA.\n    CALL 'SUB' ON ~ OVERFLOW DISPLAY 'E' END-CALL\n"
            "    STOP RUN."
        )
    },
    "entry-name": {
        "data": "LINKAGE SECTION.\n01 L1 PIC X.",
        "proc": "MAIN-PARA.\n    ENTRY ~ 'E2' USING L1.\n    GOBACK.",
    },
    "exec-sql": {
        "data": "WORKING-STORAGE SECTION.\n01 HV PIC X(10).",
        "proc": (
            "MAIN-PARA.\n    EXEC ~ SQL SELECT A INTO :HV FROM T END-EXEC\n"
            "    STOP RUN."
        ),
    },
    "exec-sql-data-division": {
        "data": "WORKING-STORAGE SECTION.\n    EXEC ~ SQL INCLUDE SQLCA END-EXEC.",
        "proc": "MAIN-PARA.\n    STOP RUN.",
    },
    "exec-cics": {
        "proc": (
            "MAIN-PARA.\n    IF 1 = 1\n      EXEC ~ CICS ABEND ABCODE('X') END-EXEC\n"
            "    END-IF\n    EXEC ~ CICS RETURN END-EXEC."
        )
    },
    "exec-dli": {
        "proc": "MAIN-PARA.\n    EXEC ~ DLI GU USING PCB(1) END-EXEC\n    GOBACK."
    },
    "end-declaratives": {
        "decl": (
            "DECLARATIVES.\nERR-SEC SECTION.\n    USE AFTER ERROR PROCEDURE ON INPUT.\n"
            "ERR-PARA.\n    DISPLAY 'E'.\nEND ~ DECLARATIVES."
        ),
        "proc": "MAIN SECTION.\nMAIN-PARA.\n    STOP RUN.",
    },
    "special-names-mnemonic": {
        "env": "CONFIGURATION SECTION.\nSPECIAL-NAMES.\n    SYSOUT ~ IS SYSPRINT.",
        "proc": "MAIN-PARA.\n    STOP RUN.",
    },
    "currency-picture-symbol": {
        "env": (
            "CONFIGURATION SECTION.\nSPECIAL-NAMES.\n"
            "    CURRENCY SIGN IS 'EUR' WITH ~ PICTURE SYMBOL 'E'."
        ),
        "proc": "MAIN-PARA.\n    STOP RUN.",
    },
    "currency-picture-symbol-inner": {
        "env": (
            "CONFIGURATION SECTION.\nSPECIAL-NAMES.\n"
            "    CURRENCY SIGN IS 'EUR' WITH PICTURE ~ SYMBOL 'E'."
        ),
        "proc": "MAIN-PARA.\n    STOP RUN.",
    },
    "usage-object-reference": {
        "env": "CONFIGURATION SECTION.\nREPOSITORY.\n    CLASS ACCOUNT IS 'Account'.",
        "data": "WORKING-STORAGE SECTION.\n01 A USAGE OBJECT ~ REFERENCE ACCOUNT.",
        "proc": "MAIN-PARA.\n    STOP RUN.",
    },
}


def _variants(case: dict[str, str]) -> tuple[str, str]:
    joined = _program(**{k: v.replace("~ ", "") for k, v in case.items()})
    broken = _program(**{k: v.replace(" ~ ", "\n    ") for k, v in case.items()})
    return joined, broken


def _parse(source: str) -> Any:
    result = parse_cobol(source)
    assert result.ast is not None
    return result


@pytest.mark.parametrize("name", sorted(CASES))
def test_line_break_between_keywords_keeps_ast(name: str) -> None:
    joined, broken = _variants(CASES[name])
    one_line = _parse(joined)
    two_lines = _parse(broken)
    assert _strip_locations(two_lines.ast.to_dict()) == _strip_locations(
        one_line.ast.to_dict()
    )
    assert two_lines.warnings == one_line.warnings
    assert len(two_lines.errors) == len(one_line.errors)


def _procedure(result: Any) -> Any:
    return result.ast.get_division("PROCEDURE")


def test_stop_newline_run_creates_no_paragraph() -> None:
    _, broken = _variants(CASES["stop-run"])
    paragraphs = _procedure(_parse(broken)).paragraphs
    assert [p.paragraph_name for p in paragraphs] == ["MAIN-PARA"]
    stop = paragraphs[0].statements[-1]
    assert stop.stop_type == "RUN"


def test_stop_newline_literal_keeps_literal() -> None:
    _, broken = _variants(CASES["stop-literal"])
    stop = _procedure(_parse(broken)).paragraphs[0].statements[0]
    assert stop.stop_type != "RUN"


def test_when_newline_other_is_the_default_clause() -> None:
    _, broken = _variants(CASES["when-other"])
    evaluate = _procedure(_parse(broken)).paragraphs[0].statements[0]
    assert evaluate.default_when is not None
    assert len(evaluate.when_clauses) == 1


def test_exec_newline_interface_dispatches_per_interface() -> None:
    # The dispatch cache was keyed on (EXEC, NEWLINE), so an EXEC <newline>
    # CICS after an EXEC <newline> SQL reused the SQL parser.
    source = _program(
        data="WORKING-STORAGE SECTION.\n01 HV PIC X(10).",
        proc=(
            "MAIN-PARA.\n"
            "    EXEC\n    SQL SELECT A INTO :HV FROM T END-EXEC\n"
            "    EXEC\n    CICS RETURN END-EXEC\n"
            "    EXEC\n    DLI GU USING PCB(1) END-EXEC\n"
            "    GOBACK."
        ),
    )
    statements = _procedure(_parse(source)).paragraphs[0].statements
    kinds = [s.to_dict().get("node_type") for s in statements]
    assert kinds[1:3] == ["EXEC_CICS", "EXEC_IMS"]
    assert statements[0].to_dict().get("host_variables")
