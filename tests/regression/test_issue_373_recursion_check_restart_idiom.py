"""recursion-check is no longer cubic on the "GO TO restart" idiom (#373).

With N paragraphs that each may ``GO TO 0000-START``, ``cycle_details`` holds
one cycle per paragraph, each nearly N long. ``RecursionRiskAnalyzer``
rebuilt its edge maps and rescanned every edge per cycle, and compared every
pair of hops in each cycle: 17 s at 800 paragraphs, and ``lint`` / ``health``
with it. The maps are now built once per report, the per-cycle checks are
linear, and the escape test is answered once per strongly connected
component.
"""

from __future__ import annotations

import time

from cobolparser import ProgramFlowAnalyzer, RecursionRiskAnalyzer, parse_cobol
from cobolparser.analysis import recursion_risk


def _restart_program(paragraphs: int) -> str:
    lines = [
        "IDENTIFICATION DIVISION.",
        "PROGRAM-ID. R1.",
        "DATA DIVISION.",
        "WORKING-STORAGE SECTION.",
        "01 WS-A PIC 9(5).",
        "01 WS-ERR PIC X.",
        "PROCEDURE DIVISION.",
        "0000-START.",
        "    MOVE 0 TO WS-A.",
    ]
    for i in range(1, paragraphs):
        lines += [
            f"P{i:04d}.",
            "    ADD 1 TO WS-A",
            "    IF WS-ERR = 'Y' GO TO 0000-START END-IF.",
        ]
    lines += ["9999-END.", "    STOP RUN."]
    return "".join(f"       {line}\n" for line in lines)


def _counting(monkeypatch, owner, name):
    calls = [0]
    original = getattr(owner, name)

    def wrapper(*args, **kwargs):
        calls[0] += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(owner, name, wrapper)
    return calls


def test_restart_idiom_scans_the_edges_once_per_component(monkeypatch):
    ast = parse_cobol(_restart_program(120)).ast
    built = _counting(monkeypatch, recursion_risk._FlowIndex, "__init__")
    escapes = _counting(monkeypatch, recursion_risk._FlowIndex, "_has_escape")
    report = RecursionRiskAnalyzer().analyze(ast)
    # One GO TO loop per paragraph, all in one component that can leave
    # (fall through to 9999-END's STOP RUN): unchanged output.
    assert len(report.risks) == 119
    assert {(r.mechanism, r.severity, r.has_escape) for r in report.risks} == {
        ("MIXED", "MEDIUM", True)
    }
    assert built[0] == 1
    assert escapes[0] == 1


def test_restart_idiom_at_800_paragraphs_is_fast():
    # 17 s before the fix, ~0.4 s after; the ceiling only catches a return
    # to super-linear per-cycle work, not ordinary machine noise.
    ast = parse_cobol(_restart_program(800)).ast
    flow = ProgramFlowAnalyzer().analyze(ast)
    started = time.perf_counter()
    report = RecursionRiskAnalyzer().analyze(ast, flow_report=flow)
    assert time.perf_counter() - started < 8.0
    assert len(report.risks) == 799
