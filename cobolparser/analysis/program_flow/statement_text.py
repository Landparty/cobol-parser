"""Short human-readable summaries of PROCEDURE DIVISION statements.

Branch arms (IF THEN/ELSE, EVALUATE WHEN) used to render as bare
"THEN" / "ELSE" boxes in the flowchart generators -- the arm's actual
content was invisible. :func:`summarize_statement` reconstructs a compact
COBOL-like one-liner ("MOVE 8 TO RETURN-CODE") for the statement shapes
that commonly open an arm, falling back to ``statement_type`` plus the
raw operand list for everything else, so every statement yields
*something* displayable.
"""

from __future__ import annotations

from typing import Any

from ...models.statements.arithmetic import (
    AddStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from ...models.statements.base import CobolExpression
from ...models.statements.call import CallStatement
from ...models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    StopStatement,
)
from ...models.statements.data import DisplayStatement, MoveStatement, SetStatement
from ...models.statements.misc import ExitStatement, GobackStatement
from .condition_text import render_condition_text

# Arm boxes are small; longer summaries wrap badly and crowd the layout.
_MAX_SUMMARY_LEN = 48


def _truncate(text: str) -> str:
    if len(text) <= _MAX_SUMMARY_LEN:
        return text
    return text[: _MAX_SUMMARY_LEN - 3].rstrip() + "..."


def _join(items: list[str]) -> str:
    return ", ".join(items)


def _perform_loop_text(stmt: PerformStatement) -> str:
    """The `` VARYING v FROM x BY y`` / `` n TIMES`` part of a PERFORM.

    The UNTIL guard is left out: arm boxes have no room for it, and the
    diff renderer (``ast_diff._statement_text``) appends it itself.
    """
    varying = stmt.varying_clause
    if varying and varying.get("variable"):
        text = f" VARYING {varying['variable']}"
        if varying.get("from_value") is not None:
            text += f" FROM {varying['from_value']}"
        if varying.get("by_value") is not None:
            text += f" BY {varying['by_value']}"
        return text
    if stmt.perform_type == "TIMES" and stmt.times_count is not None:
        return f" {stmt.times_count} TIMES"
    return ""


def summarize_statement(stmt: Any) -> str:
    """Return a compact, COBOL-like one-line summary of *stmt*.

    Never raises on a partially-built statement: every branch falls back to
    the generic ``statement_type [operands]`` form when the fields it wants
    are missing.
    """
    if isinstance(stmt, MoveStatement) and stmt.source and stmt.targets:
        return _truncate(f"MOVE {stmt.source} TO {_join(stmt.targets)}")
    if isinstance(stmt, PerformStatement):
        text = "PERFORM"
        if stmt.target_paragraph:
            text += f" {stmt.target_paragraph}"
            if stmt.thru_paragraph:
                text += f" THRU {stmt.thru_paragraph}"
        text += _perform_loop_text(stmt)
        if stmt.target_paragraph:
            return _truncate(text)
        if stmt.inline_statements:
            return _truncate(f"{text} (inline)")
        return _truncate(text)
    if isinstance(stmt, GoStatement):
        targets = stmt.target_paragraphs or (
            [stmt.target_paragraph] if stmt.target_paragraph else []
        )
        if targets:
            text = f"GO TO {_join(targets)}"
            if stmt.depending_on_variable:
                text += f" DEPENDING ON {stmt.depending_on_variable}"
            return _truncate(text)
        return "GO TO"
    if isinstance(stmt, CallStatement) and stmt.called_program:
        return _truncate(f"CALL {stmt.called_program}")
    if isinstance(stmt, SetStatement) and stmt.targets:
        if stmt.set_type in ("TRUE", "FALSE"):
            return _truncate(f"SET {_join(stmt.targets)} TO {stmt.set_type}")
        if stmt.set_type in ("UP_BY", "DOWN_BY") and stmt.value is not None:
            direction = "UP" if stmt.set_type == "UP_BY" else "DOWN"
            return _truncate(f"SET {_join(stmt.targets)} {direction} BY {stmt.value}")
        if stmt.value is not None:
            return _truncate(f"SET {_join(stmt.targets)} TO {stmt.value}")
        return _truncate(f"SET {_join(stmt.targets)}")
    if isinstance(stmt, ComputeStatement) and stmt.targets:
        # Every target with its own rounding phrase (#517): ``COMPUTE B
        # ROUNDED C`` and ``COMPUTE B C ROUNDED`` are different statements.
        target = _join([_with_rounding(stmt, t) for t in stmt.targets])
        if stmt.expression:
            return _truncate(f"COMPUTE {target} = {stmt.expression}")
        return _truncate(f"COMPUTE {target}")
    if isinstance(stmt, (AddStatement, SubtractStatement)):
        # ``source_operands`` holds only the sending items; ``operands``
        # also lists the TO/FROM targets *and* the GIVING items, so
        # subtracting the targets from it turned GIVING items into sources.
        sources = list(stmt.source_operands or []) or [
            o for o in stmt.operands if o not in stmt.targets + stmt.givings
        ]
        if sources and (stmt.targets or stmt.givings):
            verb, prep = (
                ("ADD", "TO")
                if isinstance(stmt, AddStatement)
                else ("SUBTRACT", "FROM")
            )
            text = f"{verb} {_join(sources)}"
            if stmt.targets:
                receivers = [_with_rounding(stmt, t) for t in stmt.targets]
                text += f" {prep} {_join(receivers)}"
            if stmt.givings:
                givings = [_with_rounding(stmt, g) for g in stmt.givings]
                text += f" GIVING {_join(givings)}"
            return _truncate(text)
    if isinstance(stmt, MultiplyStatement) and stmt.operands and stmt.target:
        return _truncate(f"MULTIPLY {stmt.operands[0]} BY {stmt.target}")
    if isinstance(stmt, DivideStatement) and stmt.operands and stmt.target:
        mode = getattr(stmt, "division_mode", None) or "INTO"
        return _truncate(f"DIVIDE {stmt.operands[0]} {mode} {stmt.target}")
    if isinstance(stmt, DisplayStatement) and stmt.display_items:
        return _truncate(f"DISPLAY {' '.join(stmt.display_items)}")
    if isinstance(stmt, IfStatement):
        if stmt.condition is not None:
            return _truncate(f"IF {render_condition_text(stmt.condition)}")
        return "IF"
    if isinstance(stmt, EvaluateStatement):
        subj = ", ".join(
            render_condition_text(s) if isinstance(s, CobolExpression) else str(s)
            for s in stmt.subjects
        )
        return _truncate(f"EVALUATE {subj}") if subj else "EVALUATE"
    if isinstance(stmt, StopStatement):
        return "STOP RUN" if stmt.stop_type == "RUN" else "STOP"
    if isinstance(stmt, GobackStatement):
        return "GOBACK"
    if isinstance(stmt, ExitStatement):
        return f"EXIT {stmt.exit_type}" if stmt.exit_type else "EXIT"

    stype = getattr(stmt, "statement_type", None) or type(stmt).__name__
    operands = getattr(stmt, "operands", None) or []
    if operands:
        return _truncate(f"{stype} {' '.join(str(o) for o in operands)}")
    return _truncate(str(stype))


def summarize_arm(statements: list[Any]) -> str | None:
    """Summary for a branch arm: its first statement, or None when empty.

    Only the first statement is summarized -- the generators append their
    own "+N more" marker from the arm's ``statement_count``, keeping this
    model-level text presentation-agnostic.
    """
    if not statements:
        return None
    return summarize_statement(statements[0])


def _with_rounding(stmt: Any, receiver: str) -> str:
    """*receiver* followed by its own ``ROUNDED [MODE IS m]`` phrase."""
    phrase = stmt.rounding_of(receiver)
    return f"{receiver} {phrase}" if phrase else receiver
