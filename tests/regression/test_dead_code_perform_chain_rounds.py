"""Dead-code: a long PERFORM chain is settled in a bounded number of
fall-through passes, not one per link.

The reachability worklist admitted one PERFORM target per round and re-ran
the whole fall-through pass each round, so ``P1 PERFORMs P2 PERFORMs P3 ...``
cost one full pass per paragraph: 3.8 s on a 40,000-line generated program
(``tests/performance/test_large_program.py``), quadrupling each time the
program doubled. Each round now admits the plain reference closure first.
"""

from __future__ import annotations

from cobolparser import CobolParser, DeadCodeAnalyzer, ErrorRecoveryMode


def _chain(length: int) -> str:
    lines = [
        "       IDENTIFICATION DIVISION.",
        "       PROGRAM-ID. CHAIN.",
        "       PROCEDURE DIVISION.",
        "       P0000.",
        "           PERFORM P0001",
        "           STOP RUN.",
    ]
    for i in range(1, length + 1):
        lines.append(f"       P{i:04d}.")
        if i < length:
            lines.append(f"           PERFORM P{i + 1:04d}.")
        else:
            lines.append("           CONTINUE.")
    lines += ["       ORPHAN.", "           DISPLAY 'NEVER'."]
    return "\n".join(lines) + "\n"


def test_chain_settles_in_few_passes(monkeypatch) -> None:
    ast = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST).parse(_chain(300)).ast
    calls = []
    original = DeadCodeAnalyzer._collect_fallthrough_refs

    def counting(self: DeadCodeAnalyzer) -> None:
        calls.append(1)
        original(self)

    monkeypatch.setattr(DeadCodeAnalyzer, "_collect_fallthrough_refs", counting)
    report = DeadCodeAnalyzer().analyze(ast)
    assert len(calls) <= 3
    assert [item.name for item in report.dead_items] == ["ORPHAN"]
