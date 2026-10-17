"""Regression tests for #593: ``SET proc-ptr TO ENTRY 'SUBPGM'`` followed by
``CALL proc-ptr`` was never resolved -- DynamicCallAnalyzer tracked only MOVE
and VALUE, so the CALL had no possible target and codebase-graph drew no
edge to SUBPGM."""

from pathlib import Path

from cobolparser import parse_cobol
from cobolparser.analysis import DynamicCallAnalyzer
from cobolparser.analysis.codebase import CodebaseGraphBuilder


def _program(procedure: str, name: str = "MAINP") -> str:
    return (
        "       IDENTIFICATION DIVISION.\n"
        f"       PROGRAM-ID. {name}.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-PP USAGE PROCEDURE-POINTER.\n"
        "       01 WS-FP USAGE FUNCTION-POINTER.\n"
        "       01 WS-P2 USAGE PROCEDURE-POINTER.\n"
        "       01 WS-NM PIC X(8) VALUE 'OTHERP'.\n"
        "       01 WS-IN PIC X(8).\n"
        "       PROCEDURE DIVISION.\n" + procedure + "           GOBACK.\n"
    )


def _calls(source: str) -> dict:
    result = parse_cobol(source)
    assert result.errors == []
    DynamicCallAnalyzer().analyze(result.ast)
    calls: dict = {}
    for call in result.ast.find_all_by_type("CallStatement"):
        calls.setdefault(call.called_program, call)
    return calls


def _incomplete(call) -> bool:
    return call.get_metadata("possible_values_incomplete") is True


def test_set_to_entry_literal_resolves_the_call() -> None:
    calls = _calls(
        _program(
            "           SET WS-PP TO ENTRY 'SUBPGM'\n"
            "           CALL WS-PP\n"
            "           SET WS-FP TO ENTRY 'SUBFN'\n"
            "           CALL WS-FP\n"
        )
    )
    assert calls["WS-PP"].possible_values == ["SUBPGM"]
    assert not _incomplete(calls["WS-PP"])
    assert calls["WS-FP"].possible_values == ["SUBFN"]
    assert not _incomplete(calls["WS-FP"])


def test_set_pointer_to_pointer_copies_the_value_set() -> None:
    calls = _calls(
        _program(
            "           SET WS-PP TO ENTRY 'SUBPGM'\n"
            "           SET WS-P2 TO WS-PP\n"
            "           CALL WS-P2\n"
        )
    )
    assert calls["WS-P2"].possible_values == ["SUBPGM"]
    assert not _incomplete(calls["WS-P2"])


def test_set_to_entry_identifier_reads_the_identifier() -> None:
    calls = _calls(
        _program("           SET WS-PP TO ENTRY WS-NM\n" "           CALL WS-PP\n")
    )
    assert calls["WS-PP"].possible_values == ["OTHERP"]
    assert not _incomplete(calls["WS-PP"])


def test_set_to_entry_unknown_identifier_is_incomplete() -> None:
    calls = _calls(
        _program(
            "           ACCEPT WS-IN\n"
            "           SET WS-PP TO ENTRY WS-IN\n"
            "           CALL WS-PP\n"
        )
    )
    assert _incomplete(calls["WS-PP"])


def test_unresolvable_set_keeps_the_incomplete_flag() -> None:
    calls = _calls(
        _program(
            "           SET WS-PP TO ENTRY 'SUBPGM'\n"
            "           SET WS-PP TO ADDRESS OF WS-NM\n"
            "           CALL WS-PP\n"
        )
    )
    assert calls["WS-PP"].possible_values == ["SUBPGM"]
    assert _incomplete(calls["WS-PP"])


def test_set_to_null_adds_no_target() -> None:
    calls = _calls(
        _program(
            "           SET WS-PP TO ENTRY 'SUBPGM'\n"
            "           SET WS-PP TO NULL\n"
            "           CALL WS-PP\n"
        )
    )
    assert calls["WS-PP"].possible_values == ["SUBPGM"]
    assert not _incomplete(calls["WS-PP"])


def test_codebase_graph_draws_the_edge(tmp_path: Path) -> None:
    (tmp_path / "MAINP.cbl").write_text(
        _program("           SET WS-PP TO ENTRY 'SUBPGM'\n           CALL WS-PP\n")
    )
    (tmp_path / "SUBPGM.cbl").write_text(
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. SUBPGM.\n"
        "       PROCEDURE DIVISION.\n"
        "           GOBACK.\n"
    )
    graph = CodebaseGraphBuilder().build(
        [str(tmp_path / "MAINP.cbl"), str(tmp_path / "SUBPGM.cbl")]
    )
    edges = {(e.caller, e.callee) for e in graph.call_edges}
    assert ("MAINP", "SUBPGM") in edges
    assert not any("WS-PP" in u for u in graph.unresolved)
