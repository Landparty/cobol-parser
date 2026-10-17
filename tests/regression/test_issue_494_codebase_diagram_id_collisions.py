"""Regression tests for #494: codebase-graph's DOT / Mermaid output merged
distinct programs whose sanitized ids collide (``PAY#01`` / ``PAY@01`` /
``PAY$01``, ``PAY-RTN`` / ``PAY_RTN``) into one node, drawing false
self-calls and edges to the wrong program."""

from __future__ import annotations

import re
from pathlib import Path

from cobolparser.analysis.codebase import CodebaseGraphBuilder

NATIONAL = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. MAINPGM.
       PROCEDURE DIVISION.
           CALL 'PAY#01'
           CALL 'PAY@01'
           CALL 'PAY$01'
           GOBACK.
"""

PAY_RTN = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. PAY-RTN.
       PROCEDURE DIVISION.
           CALL 'PAY_RTN'
           CALL 'TAX-CALC'
           GOBACK.
"""

TAX_CALC = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. TAX_CALC.
       PROCEDURE DIVISION.
           GOBACK.
"""


def _graph(tmp_path: Path, **sources: str):
    paths = []
    for name, text in sources.items():
        path = tmp_path / f"{name}.cbl"
        path.write_text(text)
        paths.append(str(path))
    return CodebaseGraphBuilder().build(paths)


def _mermaid_nodes(text: str) -> dict[str, str]:
    """Node id -> label, from Mermaid declarations."""
    found = {}
    for line in text.splitlines():
        match = re.match(r'\s+(\w+)\(?\[/?"([^"]*)"', line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def test_national_characters_get_one_node_each(tmp_path: Path) -> None:
    graph = _graph(tmp_path, MAINPGM=NATIONAL)
    nodes = _mermaid_nodes(graph.to_mermaid())
    labels = sorted(nodes.values())
    assert labels == [
        "MAINPGM",
        "PAY#01 (external)",
        "PAY$01 (external)",
        "PAY@01 (external)",
    ]
    targets = {
        line.split()[-1] for line in graph.to_mermaid().splitlines() if "-->" in line
    }
    assert len(targets) == 3


def test_hyphen_and_underscore_names_stay_apart(tmp_path: Path) -> None:
    graph = _graph(tmp_path, a=PAY_RTN, b=TAX_CALC)
    dot = graph.to_dot()
    declared = re.findall(r"^\s+(P_\w+) \[label=\"([^\"]+)\"", dot, re.M)
    ids = [node_id for node_id, _ in declared]
    assert len(ids) == len(set(ids)) == 4
    by_label = {label: node_id for node_id, label in declared}
    edges = re.findall(r"^\s+(P_\w+) -> (P_\w+)", dot, re.M)
    # No false self-call, and the TAX-CALC edge is not the TAX_CALC program.
    assert (by_label["PAY-RTN"], by_label["PAY_RTN"]) in edges
    assert (by_label["PAY-RTN"], by_label["TAX-CALC"]) in edges
    assert all(caller != callee for caller, callee in edges)
    assert by_label["TAX-CALC"] != by_label["TAX_CALC"]
