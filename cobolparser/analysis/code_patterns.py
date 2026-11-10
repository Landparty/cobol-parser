"""
Single-program code patterns that other COBOL linters check and lint did not.

The rules here were chosen by surveying other COBOL static analyzers
(SonarQube's COBOL rules, IBM Developer for z/OS code review, Code4z /
COBOL Language Support and several open-source linters) for checks that
find real defects. Only the ideas were taken; every check is written from
the COBOL language rules, on this package's AST.

Like :mod:`.bug_patterns`, the guiding rule is **exact by construction, or
absent**: a rule reports only what it can prove from the program text and
stays quiet when an operand cannot be resolved.

Rules (rule id, ``kind``, severity):

- ``constant-condition``
    - ``IDENTICAL_OPERANDS`` (warning): a relation condition with the same
      operand on both sides (``IF WS-A = WS-A``). It is always true (``=``,
      ``>=``, ``<=``) or always false (``NOT =``, ``>``, ``<``); usually a
      copy-paste slip where another field was meant. Intrinsic functions
      are left out (``FUNCTION RANDOM = FUNCTION RANDOM`` can differ).
    - ``CONTRADICTORY_AND`` (warning): two ``=`` tests of the same operand
      against different literals joined by AND (``WS-A = 'A' AND WS-A =
      'B'``, also the abbreviated ``WS-A = 'A' AND 'B'``), which can never
      both hold. The usual cause is AND written for OR.
- ``duplicate-branch``
    - ``DUPLICATE_WHEN`` (warning): an EVALUATE WHEN whose selectors (all
      plain literals or conditions, ALSO included) repeat an earlier WHEN of
      the same EVALUATE. The later branch can never run.
    - ``DUPLICATE_CONDITION`` (warning): an ``IF c ... ELSE IF c`` chain that
      tests the same condition again. The second branch can never run.
- ``self-assignment``
    - ``SELF_MOVE`` (warning): ``MOVE X TO X`` (same reference, same
      subscripts): it does nothing, so another field was meant.
- ``stop-run-in-subprogram``
    - ``STOP_RUN_IN_CALLED_PROGRAM`` (warning): STOP RUN in a program that is
      CALLed (its PROCEDURE DIVISION has USING, or it is a nested program).
      STOP RUN ends the whole run unit, so the caller never gets control
      back; GOBACK returns to it.
- ``string-pointer``
    - ``POINTER_BELOW_ONE`` (error): MOVE 0 / ZERO (or INITIALIZE) of a
      STRING or UNSTRING WITH POINTER item, followed in the same block by
      that STRING / UNSTRING with nothing in between naming the pointer. A
      pointer below 1 is an overflow condition at once: nothing is
      transferred.
    - ``POINTER_TOO_SMALL`` (warning): a pointer whose PICTURE holds fewer
      digits than the receiving (STRING) or sending (UNSTRING) field's
      length + 1, the value the pointer reaches at the end of the field.
      ``PIC 9`` on a 20-byte field wraps at 10.
- ``loop-variable``
    - ``VARYING_VARIABLE_STEPPED`` (warning): the body of a ``PERFORM ...
      VARYING`` (inline, or the PERFORMed paragraph or THRU range itself)
      ADDs to, SUBTRACTs from, SET UP / DOWN or COMPUTEs from itself the
      variable the VARYING / AFTER phrase steps. The loop then skips
      iterations or never ends.
    - ``VARYING_VARIABLE_ASSIGNED`` (info): the body MOVEs, SETs TO,
      INITIALIZEs or COMPUTEs a new value into it: often a deliberate early
      exit, but it hides the loop's real bound.
- ``evaluate-other``
    - ``EVALUATE_WITHOUT_OTHER`` (info): an EVALUATE with no WHEN OTHER, so a
      value no WHEN expects passes silently.
- ``nesting-depth``
    - ``NESTING_TOO_DEEP`` (info): IF / EVALUATE / SEARCH / inline PERFORM
      nested more than :data:`MAX_NESTING` deep (an ``ELSE IF`` chain counts
      as one level). Once per outermost statement.

Each rule is program-unit scoped; lint runs it on every unit.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from ..models.data_items import CobolDataItem
from ..models.program import CobolProgram
from ..models.statements.arithmetic import ArithmeticStatement, ComputeStatement
from ..models.statements.base import CobolExpression
from ..models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    StopStatement,
)
from ..models.statements.data import (
    InitializeStatement,
    MoveStatement,
    SetStatement,
    StringStatement,
    UnstringStatement,
)
from .bug_patterns import (
    BugFinding,
    _Context,
    _item_capacity,
    _nested_lists,
    _parse_operand,
    _receiving_capacity,
    walk_statements,
)
from .context import ProgramContext
from .program_flow import ProgramFlowReport

#: Every rule this module runs, in report order.
CODE_PATTERN_RULES: tuple[str, ...] = (
    "constant-condition",
    "duplicate-branch",
    "self-assignment",
    "stop-run-in-subprogram",
    "string-pointer",
    "loop-variable",
    "evaluate-other",
    "nesting-depth",
)

#: One-line description per rule (SARIF ``shortDescription``, ``--help``).
CODE_PATTERN_DESCRIPTIONS: dict[str, str] = {
    "constant-condition": "Condition that is always true or always false "
    "(same operand on both sides, contradictory AND)",
    "duplicate-branch": "EVALUATE WHEN or ELSE IF that repeats an earlier "
    "test and can never run",
    "self-assignment": "MOVE of a field to itself",
    "stop-run-in-subprogram": "STOP RUN in a CALLed program (GOBACK returns "
    "to the caller)",
    "string-pointer": "STRING/UNSTRING pointer set below 1 or too small for "
    "its field",
    "loop-variable": "PERFORM VARYING control variable changed inside the loop",
    "evaluate-other": "EVALUATE without WHEN OTHER",
    "nesting-depth": "IF/EVALUATE/PERFORM nested too deeply",
}

#: Deepest IF / EVALUATE / SEARCH / inline PERFORM nesting ``nesting-depth``
#: accepts.
MAX_NESTING = 5

_SEVERITY: dict[str, str] = {
    "IDENTICAL_OPERANDS": "warning",
    "CONTRADICTORY_AND": "warning",
    "DUPLICATE_WHEN": "warning",
    "DUPLICATE_CONDITION": "warning",
    "SELF_MOVE": "warning",
    "STOP_RUN_IN_CALLED_PROGRAM": "warning",
    "POINTER_BELOW_ONE": "error",
    "POINTER_TOO_SMALL": "warning",
    "VARYING_VARIABLE_STEPPED": "warning",
    "VARYING_VARIABLE_ASSIGNED": "info",
    "EVALUATE_WITHOUT_OTHER": "info",
    "NESTING_TOO_DEEP": "info",
}

_RELATIONS_ALWAYS_TRUE = frozenset(
    {"EQUAL", "GREATER_EQUAL", "LESS_EQUAL", "GREATER_OR_EQUAL", "LESS_OR_EQUAL"}
)
_RELATIONS_ALWAYS_FALSE = frozenset({"NOT_EQUAL", "GREATER", "LESS"})
_ZERO_WORDS = frozenset({"0", "ZERO", "ZEROS", "ZEROES"})
_SPACES_RE = re.compile(r"\s+")
_NUMERIC_RE = re.compile(r"^[+-]?(\d+(?:[.,]\d*)?|[.,]\d+)$")
_NAME_CHARS = r"A-Za-z0-9-"


def _finding(
    kind: str, rule: str, message: str, stmt: Any, symbol: str | None
) -> BugFinding:
    return BugFinding(
        rule=rule,
        kind=kind,
        message=message,
        location=getattr(stmt, "location", None),
        symbol=symbol,
        severity=_SEVERITY[kind],
    )


def _norm(text: Any) -> str:
    """An operand's text with spacing normalized and case folded (outside
    quoted literals, which keep their case)."""
    raw = str(text or "").strip()
    out: list[str] = []
    for i, part in enumerate(re.split(r"('(?:[^']|'')*'|\"(?:[^\"]|\"\")*\")", raw)):
        if i % 2:
            out.append(part)
        else:
            part = _SPACES_RE.sub(" ", part.upper())
            part = re.sub(r"\s*\(\s*", "(", part)
            part = re.sub(r"\s*\)", ")", part)
            out.append(part)
    return "".join(out).strip()


def _literal_value(text: str) -> tuple[str, Any] | None:
    """``(kind, value)`` of a literal operand, or None for anything else.

    Alphanumeric literals compare with trailing spaces ignored (COBOL pads
    the shorter operand with spaces); numeric ones by value (``1`` = ``01``).
    """
    text = (text or "").strip()
    if len(text) >= 2 and text[0] in "'\"" and text[-1] == text[0]:
        inner = text[1:-1].replace(text[0] * 2, text[0])
        return ("alnum", inner.rstrip(" "))
    if _NUMERIC_RE.match(text):
        try:
            return ("num", Decimal(text.replace(",", ".")))
        except InvalidOperation:  # pragma: no cover - the regex prevents it
            return None
    return None


def _shape(expr: Any) -> Any:
    """A condition's structure without locations, for equality tests."""
    if isinstance(expr, CobolExpression):
        expr = expr.to_dict()
    if isinstance(expr, dict):
        return {
            k: _shape(v)
            for k, v in sorted(expr.items())
            if k not in ("location", "metadata", "node_type")
        }
    if isinstance(expr, list):
        return [_shape(v) for v in expr]
    if isinstance(expr, str):
        return _norm(expr)
    return expr


def _condition_tree(expr: Any) -> Any:
    """The relation / logical tree of a condition (a CONDITION wrapper
    holds it in ``condition_tree``)."""
    while isinstance(expr, CobolExpression) and expr.condition_tree is not None:
        expr = expr.condition_tree
    return expr


def _conditions_of(stmt: Any) -> Iterator[Any]:
    if isinstance(stmt, IfStatement) and stmt.condition is not None:
        yield stmt.condition
    if isinstance(stmt, PerformStatement):
        if stmt.until_condition is not None:
            yield stmt.until_condition
        for clause in stmt.after_clauses or []:
            cond = clause.get("until_condition") if isinstance(clause, dict) else None
            if isinstance(cond, CobolExpression):
                yield cond


def _subtrees(expr: Any) -> Iterator[Any]:
    """Every node of a condition tree, the root included."""
    stack = [_condition_tree(expr)]
    while stack:
        node = stack.pop()
        if not isinstance(node, CobolExpression):
            continue
        yield node
        for attr in ("left_condition", "right_condition", "condition_tree"):
            child = getattr(node, attr, None)
            if isinstance(child, CobolExpression):
                stack.append(child)


def _and_conjuncts(node: Any) -> list[Any]:
    """The relations an AND chain joins (nested ANDs flattened)."""
    out: list[Any] = []
    stack = [node]
    while stack:
        current = _condition_tree(stack.pop())
        if (
            isinstance(current, CobolExpression)
            and getattr(current, "operator", None) == "AND"
            and current.expression_type == "LOGICAL"
        ):
            stack.append(getattr(current, "right_condition", None))
            stack.append(getattr(current, "left_condition", None))
        elif current is not None:
            out.append(current)
    return out


def _mentions(stmt: Any, name: str) -> bool:
    """Whether *name* appears as a word anywhere in *stmt*'s serialized form."""
    try:
        text = json.dumps(stmt.to_dict(), default=str)
    except Exception:  # noqa: BLE001 - be conservative: assume it does
        return True
    return (
        re.search(
            rf"(?<![{_NAME_CHARS}]){re.escape(name)}(?![{_NAME_CHARS}])", text.upper()
        )
        is not None
    )


def _receivers(stmt: Any) -> list[str]:
    """The data references *stmt* stores into (for the statements the
    ``loop-variable`` rule judges)."""
    if isinstance(stmt, ArithmeticStatement):
        givings = list(getattr(stmt, "givings", None) or [])
        out = givings or list(getattr(stmt, "targets", None) or [])
        remainder = getattr(stmt, "remainder", None)
        if remainder:
            out.append(remainder)
        return out
    if isinstance(stmt, (ComputeStatement, MoveStatement, InitializeStatement)):
        return list(stmt.targets or [])
    if isinstance(stmt, SetStatement):
        if (stmt.set_type or "").upper() in ("TO", "UP_BY", "DOWN_BY"):
            return list(stmt.targets or [])
    return []


def _is_step(stmt: Any, name: str) -> bool:
    """Whether a store into *name* by *stmt* steps it rather than assigns
    it a fresh value."""
    if isinstance(stmt, ArithmeticStatement):
        return not getattr(stmt, "givings", None) or any(
            _norm(o) == name for o in (stmt.operands or [])[:-1]
        )
    if isinstance(stmt, SetStatement):
        return (stmt.set_type or "").upper() in ("UP_BY", "DOWN_BY")
    if isinstance(stmt, ComputeStatement):
        expression = _norm(getattr(stmt, "expression", "") or "")
        return (
            re.search(
                rf"(?<![{_NAME_CHARS}]){re.escape(name)}(?![{_NAME_CHARS}])", expression
            )
            is not None
        )
    return False


@dataclass
class CodePatternReport:
    findings: list[BugFinding] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"findings": [f.to_dict() for f in self.findings]}


class CodePatternAnalyzer:
    """Run the code-pattern rules over one program unit.

    Usage::

        report = CodePatternAnalyzer().analyze(ast)
        report.findings   # list[BugFinding]
    """

    def __init__(self, rules: Iterable[str] | None = None) -> None:
        selected = list(CODE_PATTERN_RULES if rules is None else rules)
        unknown = set(selected) - set(CODE_PATTERN_RULES)
        if unknown:
            raise ValueError(f"unknown code-pattern rule(s): {sorted(unknown)}")
        self.rules = tuple(r for r in CODE_PATTERN_RULES if r in set(selected))

    def analyze(
        self,
        ast: CobolProgram | ProgramContext,
        *,
        flow_report: ProgramFlowReport | None = None,
    ) -> CodePatternReport:
        context = _Context(ProgramContext.of(ast, flow=flow_report))
        report = CodePatternReport()
        for rule in self.rules:
            report.findings.extend(run_code_pattern(context, rule))
        return report


def run_code_pattern(context: _Context, rule: str) -> list[BugFinding]:
    """The findings of one code-pattern *rule* on *context*'s unit (lint
    shares one :class:`bug_patterns._Context` between both modules)."""
    runners: dict[str, Callable[[_Context], list[BugFinding]]] = {
        "constant-condition": _constant_condition,
        "duplicate-branch": _duplicate_branch,
        "self-assignment": _self_assignment,
        "stop-run-in-subprogram": _stop_run_in_subprogram,
        "string-pointer": _string_pointer,
        "loop-variable": _loop_variable,
        "evaluate-other": _evaluate_other,
        "nesting-depth": _nesting_depth,
    }
    if context.ast.procedure_division is None:
        return []
    return runners[rule](context)


# ---------------------------------------------------------------------------
# constant-condition
# ---------------------------------------------------------------------------


def _constant_condition(ctx: _Context) -> list[BugFinding]:
    findings: list[BugFinding] = []
    for stmt in ctx.statements():
        seen: set[str] = set()
        for condition in _conditions_of(stmt):
            for node in _subtrees(condition):
                for finding in _identical(node, stmt) + _contradictory(node, stmt):
                    key = f"{finding.kind}:{finding.message}"
                    if key not in seen:
                        seen.add(key)
                        findings.append(finding)
    return findings


def _identical(node: Any, stmt: Any) -> list[BugFinding]:
    if getattr(node, "expression_type", None) != "COMPARISON":
        return []
    operator = str(getattr(node, "operator", "") or "")
    left = getattr(node, "left_operand", None)
    right = getattr(node, "right_operand", None)
    if not isinstance(left, str) or not isinstance(right, str):
        return []
    if operator not in _RELATIONS_ALWAYS_TRUE | _RELATIONS_ALWAYS_FALSE:
        return []
    a, b = _norm(left), _norm(right)
    if a != b or not a or "FUNCTION " in a or _literal_value(a) is not None:
        return []
    verdict = "true" if operator in _RELATIONS_ALWAYS_TRUE else "false"
    return [
        _finding(
            "IDENTICAL_OPERANDS",
            "constant-condition",
            f"{left.strip()} is compared with itself: the condition is always "
            f"{verdict}; another field was probably meant",
            stmt,
            a,
        )
    ]


def _contradictory(node: Any, stmt: Any) -> list[BugFinding]:
    if not (
        getattr(node, "expression_type", None) == "LOGICAL"
        and getattr(node, "operator", None) == "AND"
    ):
        return []
    parent = getattr(node, "parent", None)
    if (
        isinstance(parent, CobolExpression)
        and getattr(parent, "operator", None) == "AND"
        and parent.expression_type == "LOGICAL"
    ):
        return []  # judged once, from the top of the AND chain
    equals: dict[str, tuple[str, tuple[str, Any]]] = {}
    for relation in _and_conjuncts(node):
        if getattr(relation, "expression_type", None) != "COMPARISON":
            continue
        if getattr(relation, "operator", None) != "EQUAL":
            continue
        left = getattr(relation, "left_operand", None)
        right = getattr(relation, "right_operand", None)
        if not isinstance(left, str) or not isinstance(right, str):
            continue
        subject, literal = _norm(left), right.strip()
        value = _literal_value(literal)
        if value is None:
            subject, literal = _norm(right), left.strip()
            value = _literal_value(literal)
        if value is None or _literal_value(subject) is not None:
            continue
        if "FUNCTION " in subject:
            continue
        previous = equals.get(subject)
        if previous is None:
            equals[subject] = (literal, value)
            continue
        if previous[1][0] == value[0] and previous[1][1] != value[1]:
            return [
                _finding(
                    "CONTRADICTORY_AND",
                    "constant-condition",
                    f"{subject} = {previous[0]} AND {subject} = {literal} can "
                    "never both hold, so this part of the condition is "
                    "always false (OR meant?)",
                    stmt,
                    subject,
                )
            ]
    return []


# ---------------------------------------------------------------------------
# duplicate-branch
# ---------------------------------------------------------------------------


def _selector_key(selector: Any) -> str | None:
    """A comparable key for one WHEN selector, None when it is not a plain
    literal or condition (ranges, ANY, figuratives, data names are skipped:
    a data name's value can change between WHENs)."""
    if not isinstance(selector, dict):
        return None
    kind = selector.get("type")
    if kind == "Literal":
        value = str(selector.get("value", ""))
        if selector.get("quoted"):
            return f"A:{value.rstrip(' ')}"
        literal = _literal_value(value)
        if literal is None:
            return None
        return f"N:{literal[1]}"
    if kind == "Condition":
        text = _norm(selector.get("text", ""))
        return f"C:{text}" if text else None
    return None


def _duplicate_branch(ctx: _Context) -> list[BugFinding]:
    findings: list[BugFinding] = []
    for stmt in ctx.statements():
        if isinstance(stmt, EvaluateStatement):
            findings.extend(_duplicate_when(stmt))
        elif isinstance(stmt, IfStatement):
            findings.extend(_duplicate_else_if(stmt))
    return findings


def _duplicate_when(stmt: EvaluateStatement) -> list[BugFinding]:
    findings: list[BugFinding] = []
    # A WHEN with no statements of its own shares the next WHEN's
    # (``WHEN 'A' WHEN 'B' DISPLAY ...``): a value repeated inside one such
    # group is redundant but runs the same code, so only a repeat in a later
    # group -- whose statements can never run for it -- is reported.
    group = 0
    seen: dict[tuple[str, ...], int] = {}
    for clause in stmt.when_clauses:
        selectors = list(getattr(clause, "selectors", None) or [])
        keys = [_selector_key(s) for s in selectors]
        if selectors and not any(k is None for k in keys):
            key = tuple(k for k in keys if k is not None)
            if key in seen and seen[key] != group:
                shown = " ALSO ".join(k.split(":", 1)[1] for k in key)
                findings.append(
                    _finding(
                        "DUPLICATE_WHEN",
                        "duplicate-branch",
                        f"WHEN {shown} repeats an earlier WHEN of this EVALUATE: "
                        "the statements under it can never run for that value",
                        clause if getattr(clause, "location", None) else stmt,
                        None,
                    )
                )
            seen.setdefault(key, group)
        if clause.statements:
            group += 1
    return findings


def _duplicate_else_if(stmt: IfStatement) -> list[BugFinding]:
    parent = getattr(stmt, "parent", None)
    if isinstance(parent, IfStatement) and parent.else_statements == [stmt]:
        return []  # judged from the head of the chain
    findings: list[BugFinding] = []
    seen: set[str] = set()
    current: Any = stmt
    while isinstance(current, IfStatement) and current.condition is not None:
        key = json.dumps(
            _shape(_condition_tree(current.condition)), sort_keys=True, default=str
        )
        if key in seen:
            findings.append(
                _finding(
                    "DUPLICATE_CONDITION",
                    "duplicate-branch",
                    "ELSE IF repeats a condition already tested earlier in this "
                    "IF chain: this branch can never run",
                    current,
                    None,
                )
            )
        seen.add(key)
        else_block = current.else_statements or []
        current = else_block[0] if len(else_block) == 1 else None
    return findings


# ---------------------------------------------------------------------------
# self-assignment
# ---------------------------------------------------------------------------


def _self_assignment(ctx: _Context) -> list[BugFinding]:
    findings: list[BugFinding] = []
    for stmt in ctx.statements():
        if not isinstance(stmt, MoveStatement) or not stmt.source:
            continue
        source = _norm(stmt.source)
        if _literal_value(source) is not None or _parse_operand(source) is None:
            continue
        for target in stmt.targets or []:
            if _norm(target) == source:
                findings.append(
                    _finding(
                        "SELF_MOVE",
                        "self-assignment",
                        f"MOVE {stmt.source.strip()} TO itself does nothing; "
                        "another field was probably meant",
                        stmt,
                        source,
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# stop-run-in-subprogram
# ---------------------------------------------------------------------------


def _stop_run_in_subprogram(ctx: _Context) -> list[BugFinding]:
    division = ctx.ast.procedure_division
    using = list(
        (division.get_metadata("using_parameters") if division else None) or []
    )
    nested = getattr(ctx.ast, "enclosing_program", None) is not None
    if not using and not nested:
        return []
    if not nested and _is_jcl_parm_using(ctx, using):
        # A batch main program receiving its EXEC PARM= (#852): there is no
        # COBOL caller, and STOP RUN is the right way to end it.
        return []
    why = "its PROCEDURE DIVISION has USING" if using else "it is a nested program"
    findings: list[BugFinding] = []
    for stmt in ctx.statements():
        if (
            isinstance(stmt, StopStatement)
            and (stmt.stop_type or "RUN").upper() == "RUN"
        ):
            findings.append(
                _finding(
                    "STOP_RUN_IN_CALLED_PROGRAM",
                    "stop-run-in-subprogram",
                    f"STOP RUN in {ctx.ast.program_name or 'this program'}, which is "
                    f"CALLed ({why}): it ends the whole run unit and the caller "
                    "never gets control back; use GOBACK",
                    stmt,
                    ctx.ast.program_name,
                )
            )
    return findings


_HALFWORD_USAGES = frozenset(
    {
        "COMP",
        "COMP-4",
        "COMP-5",
        "BINARY",
        "COMPUTATIONAL",
        "COMPUTATIONAL-4",
        "COMPUTATIONAL-5",
    }
)


def _is_jcl_parm_using(ctx: _Context, using: list[Any]) -> bool:
    """True for the z/OS ``EXEC PGM=...,PARM=`` linkage shape: one USING
    item whose first elementary item is a binary halfword length
    (``PIC S9(4) COMP`` / ``COMP-5`` / ``BINARY``)."""
    if len(using) != 1:
        return False
    operand = _parse_operand(str(using[0]))
    if operand is None:
        return False
    candidates = [
        item for item in ctx.data.by_name.get(operand.name, []) if item.level == 1
    ]
    if len(candidates) != 1:
        return False
    first = candidates[0]
    while True:
        children = [
            c
            for c in first.children
            if isinstance(c, CobolDataItem) and c.level not in (66, 88)
        ]
        if not children:
            break
        first = children[0]
    if first is candidates[0]:
        return False
    if str(first.usage or "").upper() not in _HALFWORD_USAGES:
        return False
    capacity = _item_capacity(first)
    return (
        capacity is not None
        and capacity.numeric
        and capacity.decimal_digits == 0
        and 1 <= capacity.integer_digits <= 4
    )


# ---------------------------------------------------------------------------
# string-pointer
# ---------------------------------------------------------------------------


def _string_pointer(ctx: _Context) -> list[BugFinding]:
    findings: list[BugFinding] = []
    findings.extend(_pointer_below_one(ctx))
    findings.extend(_pointer_too_small(ctx))
    return findings


def _statement_blocks(ctx: _Context) -> Iterator[list[Any]]:
    """Every statement list of the unit: paragraph bodies and nested blocks."""
    division = ctx.ast.procedure_division
    if division is None:
        return
    from ..models.walk import all_paragraphs

    for para in all_paragraphs(division):
        yield list(para.statements)
    for stmt in ctx.statements():
        yield from _nested_lists(stmt)


def _zeroes(stmt: Any) -> list[str]:
    """The references *stmt* sets to zero (MOVE 0 / ZERO, INITIALIZE)."""
    if isinstance(stmt, MoveStatement) and _norm(stmt.source) in _ZERO_WORDS:
        return [_norm(t) for t in stmt.targets or []]
    if isinstance(stmt, InitializeStatement) and not stmt.replacing_clauses:
        return [_norm(t) for t in stmt.targets or []]
    return []


def _pointer_below_one(ctx: _Context) -> list[BugFinding]:
    findings: list[BugFinding] = []
    for block in _statement_blocks(ctx):
        for i, stmt in enumerate(block):
            for pointer in _zeroes(stmt):
                for later in block[i + 1 :]:
                    if isinstance(later, (StringStatement, UnstringStatement)) and (
                        _norm(later.pointer_variable) == pointer
                    ):
                        verb = (
                            "STRING"
                            if isinstance(later, StringStatement)
                            else "UNSTRING"
                        )
                        findings.append(
                            _finding(
                                "POINTER_BELOW_ONE",
                                "string-pointer",
                                f"{pointer} is set to zero just before and then "
                                f"used as the {verb} POINTER: a pointer below 1 "
                                "is an overflow at once and nothing is "
                                "transferred; start it at 1",
                                later,
                                pointer,
                            )
                        )
                        break
                    if _mentions(later, pointer):
                        break
    return findings


def _pointer_too_small(ctx: _Context) -> list[BugFinding]:
    findings: list[BugFinding] = []
    for stmt in ctx.statements():
        if isinstance(stmt, StringStatement):
            field_text, verb, role = stmt.into_target, "STRING", "receiving"
        elif isinstance(stmt, UnstringStatement):
            field_text, verb, role = stmt.source_operand, "UNSTRING", "sending"
        else:
            continue
        if not stmt.pointer_variable or not field_text:
            continue
        pointer_ref = _parse_operand(stmt.pointer_variable)
        field_ref = _parse_operand(field_text)
        if pointer_ref is None or field_ref is None or field_ref.reference_modified:
            continue
        pointer = ctx.data.resolve(pointer_ref)
        target = ctx.data.resolve(field_ref)
        if pointer is None or target is None:
            continue
        # The runtime stores into the pointer: a COMP-5 pointer holds its
        # native binary range, not its PICTURE digits (#853).
        pointer_cap = _receiving_capacity(pointer)
        if pointer_cap is None or not pointer_cap.numeric:
            continue
        length = _field_length(target)
        if length is None:
            continue
        needed = len(str(length + 1))
        if pointer_cap.integer_digits >= needed:
            continue
        findings.append(
            _finding(
                "POINTER_TOO_SMALL",
                "string-pointer",
                f"{verb} POINTER {pointer.name} holds {pointer_cap.integer_digits} "
                f"digit(s) but the {role} field {target.name} is {length} bytes: the "
                f"pointer must reach {length + 1}",
                stmt,
                pointer.name,
            )
        )
    return findings


def _field_length(item: Any) -> int | None:
    """The length in characters of an alphanumeric field, None when unknown."""
    capacity = _item_capacity(item)
    if capacity is not None:
        return capacity.chars if not capacity.numeric and capacity.chars else None
    if getattr(item, "occurs_clause", None) is not None:
        return None
    if not any(
        getattr(c, "level", 0) not in (66, 88) for c in getattr(item, "children", [])
    ):
        return None
    # A group: its bytes, from the layout walker program_signature uses too.
    from .program_signature import _byte_length

    return _byte_length(item) or None


# ---------------------------------------------------------------------------
# loop-variable
# ---------------------------------------------------------------------------


def _loop_bodies(ctx: _Context, stmt: PerformStatement) -> list[Any] | None:
    """The statements the loop body runs directly (no further PERFORMs)."""
    if stmt.inline_statements:
        return list(walk_statements(stmt.inline_statements))
    index = ctx.procedures
    if index is None or not stmt.target_paragraph:
        return None
    from .bug_patterns import _procedure_statements

    start = index.resolve_one(stmt.target_paragraph)
    end = index.resolve_one(stmt.thru_paragraph) if stmt.thru_paragraph else start
    keys = [e.key for e in index.entries]
    if start not in keys or end not in keys:
        return None
    first, last = keys.index(start), keys.index(end)
    if last < first:
        return None
    in_range = keys[first : last + 1]
    statements: list[Any] = []
    for key in in_range:
        entry = index.by_key[key]
        if entry.procedure_type == "PARAGRAPH" and entry.section in in_range:
            continue  # its section's statements already hold it
        statements.extend(walk_statements(_procedure_statements(entry.node)))
    return statements


def _loop_variable(ctx: _Context) -> list[BugFinding]:
    findings: list[BugFinding] = []
    for stmt in ctx.statements():
        if not isinstance(stmt, PerformStatement) or not stmt.varying_clause:
            continue
        variables = [stmt.varying_clause.get("variable")]
        variables += [
            c.get("variable") for c in stmt.after_clauses or [] if isinstance(c, dict)
        ]
        names = {_norm(v) for v in variables if v}
        if not names:
            continue
        body = _loop_bodies(ctx, stmt)
        if not body:
            continue
        for inner in body:
            if inner is stmt:
                continue
            for receiver in _receivers(inner):
                name = _norm(receiver)
                if name not in names:
                    continue
                stepped = _is_step(inner, name)
                kind = (
                    "VARYING_VARIABLE_STEPPED"
                    if stepped
                    else "VARYING_VARIABLE_ASSIGNED"
                )
                what = (
                    "steps it again: the loop skips iterations or never ends"
                    if stepped
                    else "assigns it inside the loop, which hides the loop's "
                    "real bound"
                )
                findings.append(
                    _finding(
                        kind,
                        "loop-variable",
                        f"{name} is the control variable of the PERFORM VARYING "
                        f"that runs this statement, which {what}",
                        inner,
                        name,
                    )
                )
    return findings


# ---------------------------------------------------------------------------
# evaluate-other / nesting-depth
# ---------------------------------------------------------------------------


def _evaluate_other(ctx: _Context) -> list[BugFinding]:
    return [
        _finding(
            "EVALUATE_WITHOUT_OTHER",
            "evaluate-other",
            "EVALUATE has no WHEN OTHER: a value no WHEN expects passes silently",
            stmt,
            None,
        )
        for stmt in ctx.statements()
        if isinstance(stmt, EvaluateStatement) and stmt.default_when is None
    ]


def _is_nesting(stmt: Any) -> bool:
    if isinstance(stmt, (IfStatement, EvaluateStatement, SearchStatement)):
        return True
    return isinstance(stmt, PerformStatement) and bool(stmt.inline_statements)


def _depth(stmt: Any) -> int:
    """How deep IF / EVALUATE / SEARCH / inline PERFORM nest from *stmt*
    (an ELSE IF chain counts once). Iterative: deep chains must not hit
    the recursion limit."""
    best = 0
    stack: list[tuple[Any, int]] = [(stmt, 1 if _is_nesting(stmt) else 0)]
    while stack:
        node, depth = stack.pop()
        best = max(best, depth)
        for block in _nested_lists(node):
            else_if = (
                isinstance(node, IfStatement)
                and block is node.else_statements
                and len(block) == 1
                and isinstance(block[0], IfStatement)
            )
            for child in block:
                step = 0 if else_if or not _is_nesting(child) else 1
                stack.append((child, depth + step))
    return best


def _nesting_depth(ctx: _Context) -> list[BugFinding]:
    findings: list[BugFinding] = []
    for stmt in ctx.top_statements():
        if not _is_nesting(stmt):
            continue
        depth = _depth(stmt)
        if depth > MAX_NESTING:
            findings.append(
                _finding(
                    "NESTING_TOO_DEEP",
                    "nesting-depth",
                    f"IF / EVALUATE / PERFORM nested {depth} levels deep (more "
                    f"than {MAX_NESTING}): hard to follow; move inner levels "
                    "to their own paragraph",
                    stmt,
                    None,
                )
            )
    return findings


__all__ = [
    "CODE_PATTERN_DESCRIPTIONS",
    "CODE_PATTERN_RULES",
    "MAX_NESTING",
    "CodePatternAnalyzer",
    "CodePatternReport",
    "run_code_pattern",
]
