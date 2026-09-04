"""Constraint extraction: what a program's branches require of boundary data.

Phase 4 of program-scoped test-data generation (the `gen-fixtures` initiative
-- see `docs/plans/2026-08-02-program-data-generation-design.md`). Walks
IF/EVALUATE/SEARCH conditions and PERFORM UNTIL loop guards, and -- for every
operand that resolves (via Phase 1's `ProgramLayoutIndex`) to a field a
boundary actually feeds (per Phase 2's `BoundaryReport`) -- emits a
:class:`FieldConstraint` a later phase's solver can satisfy. A READ's
``AT END`` flag tested by an enclosing ``PERFORM UNTIL`` becomes a
:class:`SequenceConstraint` instead: the knob there is how many records get
read before EOF, not any single field's value.

Nothing is silently dropped: a condition this module cannot structurally
model lands in :attr:`ConstraintReport.unsupported` (or a
:class:`BranchConstraints`' own ``unsupported`` list) with a reason, mirroring
the posture Phases 1-3 already established.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ..models.ast_base import SourceLocation
from ..models.program import CobolDivision, CobolParagraph, CobolProgram
from ..models.statements.base import (
    CobolExpression,
    ConditionalExpression,
    LogicalExpression,
)
from ..models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ..models.statements.data import MoveStatement
from ..models.statements.io import IOReadStatement
from .boundary_inventory import BoundaryRef, BoundaryReport

if TYPE_CHECKING:
    # Deferred: cobolparser.generators (reached via generators/__init__.py's
    # own import chain, e.g. program_fixtures.py genuinely constructs
    # ConstraintExtractor) imports this module back at runtime, so a
    # top-level import here would be circular -- the same shape as
    # boundary_inventory.py's own ProgramLayoutIndex import. Every use below
    # is a type annotation only; `from __future__ import annotations` keeps
    # it a lazy string at runtime.
    from ..generators.data.program_layout import ProgramLayoutIndex, ResolvedField

# -- statement-walk discipline ------------------------------------------------
#
# A local re-derivation of boundary_inventory.py's own walking discipline (in
# turn re-derived from mockymock's `mock_surface.py`) -- this module needs its
# own copy because it must also track each statement's *enclosing paragraph
# name* for `BranchConstraints.parent_proc`, which `CobolProgram.
# get_all_statements()`'s flat traversal does not preserve.

_NESTED_STATEMENT_ATTRS = (
    "then_statements",
    "else_statements",
    "inline_statements",
    "at_end_clause",
    "not_at_end_clause",
    "invalid_key_clause",
    "not_invalid_key_clause",
    "at_eop_clause",
    "not_at_eop_clause",
    "on_exception",
    "not_on_exception",
    "on_overflow",
    "not_on_overflow",
    "on_size_error",
    "not_on_size_error",
)

# Relational operator strings _conditions.py's build_condition_expression()
# assigns to a ConditionalExpression -- see that module for the full mapping
# (=, EQUAL -> "EQUAL"; NOT EQUAL/NOT = / <> -> "NOT_EQUAL"; etc.).
_RELATIONAL_OPS: dict[str, str] = {
    "EQUAL": "eq",
    "NOT_EQUAL": "ne",
    "GREATER": "gt",
    "LESS": "lt",
    "GREATER_OR_EQUAL": "ge",
    "LESS_OR_EQUAL": "le",
}
_NEGATED_RELATIONAL: dict[str, str] = {
    "eq": "ne",
    "ne": "eq",
    "gt": "le",
    "le": "gt",
    "lt": "ge",
    "ge": "lt",
}
# A reversed comparison ("42 > WS-X" means WS-X < 42) flips direction but not
# equality -- eq/ne read the same regardless of which side names the field.
_FLIPPED_RELATIONAL: dict[str, str] = {
    "eq": "eq",
    "ne": "ne",
    "gt": "lt",
    "lt": "gt",
    "ge": "le",
    "le": "ge",
}
_CLASS_WORD_OPS: dict[str, str] = {
    "NUMERIC": "class_numeric",
    "ALPHABETIC": "class_alphabetic",
    "ALPHABETIC-UPPER": "class_alphabetic",
    "ALPHABETIC-LOWER": "class_alphabetic",
}
# Sign/zero class tests have a clean numeric-interval equivalent, so they are
# folded directly into the relational solver path rather than given their own
# domain-handling branch.
_SIGN_WORD_RELATIONAL: dict[str, tuple[str, str]] = {
    "POSITIVE": ("gt", "0"),
    "NEGATIVE": ("lt", "0"),
    "ZERO": ("eq", "0"),
    "ZEROS": ("eq", "0"),
    "ZEROES": ("eq", "0"),
}
_FIGURATIVE_NAMES = frozenset(
    {
        "SPACE",
        "SPACES",
        "ZERO",
        "ZEROS",
        "ZEROES",
        "LOW-VALUE",
        "LOW-VALUES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
    }
)

# SEARCH ... WHEN conditions are stored as a single raw joined string (see
# SearchStatement.add_when_clause), not a structured expression tree; the
# EVALUATE parser's non-compound selectors (see evaluate_parser.py's
# _build_selector) are the same raw-text shape. This is a minimal
# relational-comparison parser shared by both, covering the same simple
# forms _conditions.py structurally recognises for IF/PERFORM.
_RELATIONAL_TEXT_RE = re.compile(
    r"^(.*?)\s*(NOT\s*=|<>|>=|<=|=|>|<)\s*(.*)$", re.IGNORECASE
)
_RELATIONAL_TEXT_OP_CANON: dict[str, str] = {
    "=": "eq",
    "<>": "ne",
    ">=": "ge",
    "<=": "le",
    ">": "gt",
    "<": "lt",
}
_BARE_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9-]*$")


@dataclass(frozen=True)
class FieldConstraint:
    """One conjunct: `field` must satisfy `op` against `values`.

    `op` is one of ``eq ne lt le gt ge in_set not_in_set class_numeric
    class_alphabetic figurative``. `negated` only matters for `class_numeric`
    /`class_alphabetic`/`figurative`, which have no separate "not" op name in
    the vocabulary above (unlike eq/ne or in_set/not_in_set, which absorb
    negation directly into the op choice).
    """

    field: ResolvedField
    op: str
    values: tuple[str, ...]
    origin: str
    negated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field.spec.qualified_name,
            "op": self.op,
            "values": list(self.values),
            "origin": self.origin,
            "negated": self.negated,
        }


@dataclass(frozen=True)
class SequenceConstraint:
    """The EOF/loop-flag idiom: a READ boundary's sequence length is the knob.

    `length` is `None` in v1 -- "the flag pattern exists, so a scenario
    planner can request a specific record count" -- rather than a solved
    integer; picking a concrete length is Phase 5's job.
    """

    boundary: BoundaryRef
    length: int | None
    origin: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "boundary": {
                "category": self.boundary.category,
                "key": self.boundary.key,
            },
            "length": self.length,
            "origin": self.origin,
        }


@dataclass
class BranchConstraints:
    """Every arm's constraints for one IF/EVALUATE/SEARCH decision point.

    `branch_id` is deliberately *not* `ProgramFlowAnalyzer`'s own opaque
    sequential `BranchNode.node_id` (replicating that counter would couple
    this module to the exact traversal order `program_flow/scanner.py`
    happens to use). Instead it encodes the same join key that scanner.py's
    node really is keyed by in substance -- `(parent_proc, location)` -- as a
    self-contained string. The actual join a later phase should perform is on
    `(line, column)` alone, via the dedicated fields below, not by
    string-matching `branch_id` to `node_id` or comparing `parent_proc`
    text: `program_flow/scanner.py` uppercases its own `parent_proc`
    (`pname.upper()`) while this module preserves the source's original
    casing, so the two are not directly comparable strings even when they
    name the same paragraph.
    """

    branch_id: str
    parent_proc: str | None
    line: int | None
    column: int | None = None
    arms: dict[str, list[FieldConstraint]] = field(default_factory=dict)
    unsupported: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branch_id": self.branch_id,
            "parent_proc": self.parent_proc,
            "line": self.line,
            "column": self.column,
            "arms": {
                arm: [c.to_dict() for c in constraints]
                for arm, constraints in self.arms.items()
            },
            "unsupported": list(self.unsupported),
        }


@dataclass
class ConstraintReport:
    branches: list[BranchConstraints] = field(default_factory=list)
    sequence_constraints: list[SequenceConstraint] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branches": [b.to_dict() for b in self.branches],
            "sequence_constraints": [s.to_dict() for s in self.sequence_constraints],
            "unsupported": list(self.unsupported),
        }


class ConstraintExtractor:
    """Extracts branch/loop constraints from a program's PROCEDURE DIVISION.

    ``extract(ast, index, boundary_report)`` -- `index` is the Phase 1
    :class:`ProgramLayoutIndex` built for the *same* program; `boundary_report`
    is Phase 2's :class:`BoundaryReport` for the same program, consulted for
    two things: which fields are "fed by a boundary" at all (an IF on a purely
    internal working variable is out of scope, not a gap), and which READ
    boundary a PERFORM UNTIL's EOF flag belongs to.
    """

    def extract(
        self,
        ast: CobolProgram,
        index: ProgramLayoutIndex,
        boundary_report: BoundaryReport,
    ) -> ConstraintReport:
        report = ConstraintReport()
        procedure = ast.get_division("PROCEDURE")
        if procedure is None:
            return report

        fed_names = _boundary_fed_names(boundary_report)
        eof_flags = _collect_eof_flags(ast)

        for paragraph_name, statement in _walk_statements(procedure):
            if isinstance(statement, IfStatement) and statement.condition is not None:
                self._extract_if(statement, paragraph_name, index, fed_names, report)
            elif isinstance(statement, EvaluateStatement):
                self._extract_evaluate(
                    statement, paragraph_name, index, fed_names, report
                )
            elif isinstance(statement, SearchStatement):
                self._extract_search(
                    statement, paragraph_name, index, fed_names, report
                )
            elif (
                isinstance(statement, PerformStatement)
                and statement.perform_type == "UNTIL"
                and statement.until_condition is not None
            ):
                self._extract_perform_until(
                    statement,
                    paragraph_name,
                    index,
                    fed_names,
                    eof_flags,
                    boundary_report,
                    report,
                )
        return report

    # -- IF ---------------------------------------------------------------

    @staticmethod
    def _extract_if(
        statement: IfStatement,
        paragraph_name: str,
        index: ProgramLayoutIndex,
        fed_names: set[str],
        report: ConstraintReport,
    ) -> None:
        branch_id = _branch_id(paragraph_name, statement.location)
        line = statement.location.line if statement.location else None
        column = statement.location.column if statement.location else None
        arms: dict[str, list[FieldConstraint]] = {}
        unsupported: list[str] = []

        then_variants = _extract_expr(
            statement.condition, False, index, fed_names, f"IF@{line}", unsupported
        )
        _register_variants(arms, "THEN", then_variants)

        else_variants = _extract_expr(
            statement.condition,
            True,
            index,
            fed_names,
            f"IF@{line}/ELSE",
            unsupported,
        )
        _register_variants(arms, "ELSE", else_variants)

        if arms or unsupported:
            report.branches.append(
                BranchConstraints(
                    branch_id=branch_id,
                    parent_proc=paragraph_name,
                    line=line,
                    column=column,
                    arms=arms,
                    unsupported=unsupported,
                )
            )

    # -- EVALUATE -----------------------------------------------------------

    @staticmethod
    def _extract_evaluate(
        statement: EvaluateStatement,
        paragraph_name: str,
        index: ProgramLayoutIndex,
        fed_names: set[str],
        report: ConstraintReport,
    ) -> None:
        branch_id = _branch_id(paragraph_name, statement.location)
        line = statement.location.line if statement.location else None
        column = statement.location.column if statement.location else None
        arms: dict[str, list[FieldConstraint]] = {}
        unsupported: list[str] = []

        if len(statement.subjects) != 1:
            unsupported.append("multi-subject EVALUATE (ALSO) not supported in v1")
            report.branches.append(
                BranchConstraints(
                    branch_id=branch_id,
                    parent_proc=paragraph_name,
                    line=line,
                    column=column,
                    arms=arms,
                    unsupported=unsupported,
                )
            )
            return

        subject = statement.subjects[0]
        is_true_form = isinstance(subject, str) and subject.strip().upper() == "TRUE"

        any_when_unsupported = False
        for idx, wc in enumerate(statement.when_clauses, start=1):
            arm_id = f"WHEN_{idx}"
            origin = f"EVALUATE@{line}/WHEN#{idx}"
            constraints = _extract_evaluate_selector(
                wc.selectors,
                subject,
                is_true_form,
                index,
                fed_names,
                origin,
                unsupported,
            )
            if constraints is not None:
                arms[arm_id] = constraints
            else:
                any_when_unsupported = True

        if statement.default_when is not None:
            if any_when_unsupported:
                unsupported.append(
                    "WHEN OTHER: not modeled because a prior WHEN arm was itself "
                    "unsupported"
                )
                arms["WHEN_OTHER"] = []
            else:
                arms["WHEN_OTHER"] = _negate_prior_arms(
                    arms, f"EVALUATE@{line}/WHEN_OTHER", unsupported
                )

        if arms or unsupported:
            report.branches.append(
                BranchConstraints(
                    branch_id=branch_id,
                    parent_proc=paragraph_name,
                    line=line,
                    column=column,
                    arms=arms,
                    unsupported=unsupported,
                )
            )

    # -- SEARCH ---------------------------------------------------------------

    @staticmethod
    def _extract_search(
        statement: SearchStatement,
        paragraph_name: str,
        index: ProgramLayoutIndex,
        fed_names: set[str],
        report: ConstraintReport,
    ) -> None:
        branch_id = _branch_id(paragraph_name, statement.location)
        line = statement.location.line if statement.location else None
        column = statement.location.column if statement.location else None
        arms: dict[str, list[FieldConstraint]] = {}
        unsupported: list[str] = []

        for idx, when_dict in enumerate(statement.when_clauses, start=1):
            arm_id = f"WHEN_{idx}"
            origin = f"SEARCH@{line}/WHEN#{idx}"
            condition_text = (
                when_dict.get("condition", "") if isinstance(when_dict, dict) else ""
            )
            constraint = _parse_relational_text(
                condition_text, index, fed_names, origin, unsupported
            )
            if constraint is not None:
                arms[arm_id] = [constraint]

        if statement.at_end_clause:
            arms["AT_END"] = []

        if arms or unsupported:
            report.branches.append(
                BranchConstraints(
                    branch_id=branch_id,
                    parent_proc=paragraph_name,
                    line=line,
                    column=column,
                    arms=arms,
                    unsupported=unsupported,
                )
            )

    # -- PERFORM UNTIL --------------------------------------------------------

    @staticmethod
    def _extract_perform_until(
        statement: PerformStatement,
        paragraph_name: str,
        index: ProgramLayoutIndex,
        fed_names: set[str],
        eof_flags: dict[str, list[str | None]],
        boundary_report: BoundaryReport,
        report: ConstraintReport,
    ) -> None:
        line = statement.location.line if statement.location else None
        origin = f"PERFORM-UNTIL@{line}"

        # PerformStatement.until_condition is always the historical
        # CobolExpression("CONDITION") wrapper carrying the raw joined
        # string in .operands -- the real ConditionalExpression/
        # LogicalExpression tree (when the shared _conditions.py machinery
        # could build one) lives on its .condition_tree attribute (M12; see
        # perform_parser.py's _make_until_condition_expression).
        condition_tree = (
            statement.until_condition.condition_tree
            if statement.until_condition
            else None
        )

        for name in _condition_field_names(condition_tree):
            hits = eof_flags.get(name.upper())
            if not hits:
                continue
            ref = _find_read_boundary_ref(boundary_report, hits[0])
            if ref is not None:
                report.sequence_constraints.append(
                    SequenceConstraint(boundary=ref, length=None, origin=origin)
                )
                return

        if condition_tree is None:
            if statement.until_condition and statement.until_condition.operands:
                report.unsupported.append(
                    f"{origin}: condition has no structural decomposition available"
                )
            return

        local_unsupported: list[str] = []
        variants = _extract_expr(
            condition_tree,
            False,
            index,
            fed_names,
            origin,
            local_unsupported,
        )
        if variants:
            report.unsupported.append(
                f"{origin}: condition touches a boundary-fed field but matches no "
                "recognized EOF/loop-flag pattern; not modeled as a sequence "
                "constraint in v1"
            )
            return

        # A pure internal counter (`PERFORM UNTIL I > 10`) is out of scope,
        # not a gap -- only surface reasons that are not just "nothing here
        # touches a boundary".
        out_of_scope_markers = ("field not boundary-fed", "unresolvable operand")
        genuine_gaps = [
            reason
            for reason in local_unsupported
            if not any(marker in reason for marker in out_of_scope_markers)
        ]
        report.unsupported.extend(genuine_gaps)


# -- expression-tree walk (IF / PERFORM UNTIL) --------------------------------


def _extract_expr(
    expr: CobolExpression | None,
    negate: bool,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
) -> list[list[FieldConstraint]]:
    """Recursively extract *expr* into a list of AND-conjunct variants.

    More than one variant means an OR was present (or an AND was negated via
    De Morgan into one) -- each variant is independently satisfiable and
    becomes its own arm via :func:`_register_variants`. A conjunction
    (AND, or a negated OR) drops the *whole* variant if either side fails --
    keeping only the extractable side would widen the modeled domain past
    what the source actually requires. A disjunction (OR, or a negated AND)
    safely keeps whichever side(s) did extract -- narrowing to fewer
    alternatives than the true condition is still sound for witness
    generation, just incomplete.
    """
    if expr is None:
        unsupported.append(f"{origin}: missing condition expression")
        return []

    if isinstance(expr, LogicalExpression):
        if expr.operator not in ("AND", "OR"):
            unsupported.append(
                f"{origin}: unsupported logical operator: {expr.operator}"
            )
            return []
        is_conjunction = (expr.operator == "AND") != negate
        left = _extract_expr(
            expr.left_condition, negate, index, fed_names, origin, unsupported
        )
        right = _extract_expr(
            expr.right_condition, negate, index, fed_names, origin, unsupported
        )
        if is_conjunction:
            if not left or not right:
                return []
            return [
                left_variant + right_variant
                for left_variant in left
                for right_variant in right
            ]
        return left + right

    if isinstance(expr, ConditionalExpression):
        constraint = _extract_comparison(
            expr, negate, index, fed_names, origin, unsupported
        )
        return [[constraint]] if constraint is not None else []

    unsupported.append(f"{origin}: unsupported expression node: {type(expr).__name__}")
    return []


def _register_variants(
    arms: dict[str, list[FieldConstraint]],
    base_arm_id: str,
    variants: list[list[FieldConstraint]],
) -> None:
    if not variants:
        return
    if len(variants) == 1:
        arms[base_arm_id] = variants[0]
        return
    for i, variant in enumerate(variants, start=1):
        arms[f"{base_arm_id}#{i}"] = variant


def _extract_comparison(
    expr: ConditionalExpression,
    negate: bool,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
) -> FieldConstraint | None:
    op_name = expr.operator
    if op_name in _RELATIONAL_OPS:
        op = _RELATIONAL_OPS[op_name]
        if negate:
            op = _NEGATED_RELATIONAL[op]
        left = expr.left_operand if isinstance(expr.left_operand, str) else None
        right = expr.right_operand if isinstance(expr.right_operand, str) else None
        if left is None:
            unsupported.append(f"{origin}: comparison operand is not a plain value")
            return None
        return _build_relational_constraint(
            left.strip(),
            op,
            (right or "").strip(),
            index,
            fed_names,
            origin,
            unsupported,
        )

    if op_name == "CONDITION_NAME":
        name = expr.left_operand if isinstance(expr.left_operand, str) else ""
        return _extract_condition_name_value(
            name, negate, index, fed_names, origin, unsupported
        )

    if op_name.startswith("IS NOT "):
        return _extract_class_or_sign(
            expr,
            op_name[len("IS NOT ") :],
            True,
            negate,
            index,
            fed_names,
            origin,
            unsupported,
        )
    if op_name.startswith("IS "):
        return _extract_class_or_sign(
            expr,
            op_name[len("IS ") :],
            False,
            negate,
            index,
            fed_names,
            origin,
            unsupported,
        )

    raw = expr.get_metadata("raw_condition")
    unsupported.append(f"{origin}: unparseable condition text: {raw or op_name}")
    return None


def _extract_class_or_sign(
    expr: ConditionalExpression,
    class_word: str,
    is_not: bool,
    negate: bool,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
) -> FieldConstraint | None:
    effective_negate = negate != is_not
    name = expr.left_operand if isinstance(expr.left_operand, str) else ""
    if not name.strip():
        unsupported.append(f"{origin}: class/sign condition missing operand")
        return None
    resolved = index.resolve(name.strip())
    if resolved is None:
        unsupported.append(f"{origin}: unresolvable operand: {name}")
        return None
    if not _is_boundary_fed(resolved, fed_names):
        unsupported.append(
            f"{origin}: field not boundary-fed: {resolved.spec.qualified_name}"
        )
        return None

    if class_word in _SIGN_WORD_RELATIONAL:
        op, zero = _SIGN_WORD_RELATIONAL[class_word]
        if effective_negate:
            op = _NEGATED_RELATIONAL[op]
        return FieldConstraint(resolved, op, (zero,), origin, negated=False)
    if class_word in _CLASS_WORD_OPS:
        return FieldConstraint(
            resolved,
            _CLASS_WORD_OPS[class_word],
            (class_word,),
            origin,
            negated=effective_negate,
        )

    unsupported.append(
        f"{origin}: unsupported class condition: {class_word} "
        "(DBCS/KANJI double-byte tests are out of v1 scope)"
    )
    return None


def _negate_prior_arms(
    arms: dict[str, list[FieldConstraint]],
    origin: str,
    unsupported: list[str],
) -> list[FieldConstraint]:
    """WHEN OTHER's real condition: the negation of every preceding arm.

    Modeled for the shape that actually dominates real COBOL -- an
    ``EVALUATE`` whose every arm is a single equality-or-membership test on
    the *same* field (``EVALUATE TYPE-P-BAL / WHEN "05" / WHEN "09" / WHEN
    OTHER``, or its ``EVALUATE TRUE / WHEN <88>`` spelling). There the
    negation is exactly one ``not_in_set`` over the union of every arm's
    values, which is both sound and solvable.

    Anything else (arms over different fields, conjunctions, relational or
    class tests) needs a real disjunction the FieldConstraint vocabulary
    cannot express, so the arm stays unconstrained -- but says so in
    `unsupported` rather than passing silently for a satisfiable one.

    Leaving it unconstrained unconditionally, as v1 did, was not the neutral
    choice it looks like: an unconstrained level-88 field is generated by
    drawing from ``spec.condition_values`` (see generators/data/values.py), so
    every row of the scenario named for the OTHER arm got one of the very
    values that arm excludes. The scenario could not reach its own branch --
    deterministically, not just often.
    """
    prior = [cs for arm_id, cs in arms.items() if arm_id != "WHEN_OTHER"]
    if not prior:
        return []

    field: ResolvedField | None = None
    values: list[str] = []
    for conjuncts in prior:
        if len(conjuncts) != 1:
            unsupported.append(
                f"{origin}: not modeled -- a prior arm is a conjunction of "
                "more than one constraint"
            )
            return []
        constraint = conjuncts[0]
        if constraint.op not in ("eq", "in_set") or constraint.negated:
            unsupported.append(
                f"{origin}: not modeled -- a prior arm uses {constraint.op}, "
                "which does not negate to a single not_in_set"
            )
            return []
        if field is None:
            field = constraint.field
        elif field.spec.qualified_name != constraint.field.spec.qualified_name:
            unsupported.append(
                f"{origin}: not modeled -- prior arms test different fields "
                f"({field.spec.qualified_name}, "
                f"{constraint.field.spec.qualified_name})"
            )
            return []
        values.extend(constraint.values)

    if field is None or not values:
        return []
    # Preserve first-seen order while removing duplicates, so the constraint
    # is stable for the same program (witness picking is deterministic).
    deduped = tuple(dict.fromkeys(values))
    return [FieldConstraint(field, "not_in_set", deduped, origin, False)]


def _extract_condition_name_value(
    name: str,
    negate: bool,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
) -> FieldConstraint | None:
    if not name.strip():
        unsupported.append(f"{origin}: condition-name test missing operand")
        return None
    resolved = index.resolve(name.strip())
    if resolved is None:
        unsupported.append(f"{origin}: unresolvable operand: {name}")
        return None
    if not resolved.spec.condition_values:
        unsupported.append(
            f"{origin}: bare condition name resolves to a non-condition field: "
            f"{resolved.spec.qualified_name}"
        )
        return None
    if not _is_boundary_fed(resolved, fed_names):
        unsupported.append(
            f"{origin}: field not boundary-fed: {resolved.spec.qualified_name}"
        )
        return None
    # THIS condition name's own VALUEs, not the union of every 88 under the
    # parent field. `resolve()` deliberately maps an 88 to its parent, and
    # `FieldSpec.condition_values` is deliberately that union ("any value that
    # could apply to this field" -- what the value factory wants), so reading
    # the union here made `WHEN TYPE-P-BAL-M` and `WHEN TYPE-P-BAL-F` produce
    # byte-identical `in_set ("05", "09")` constraints: the solver picked the
    # first for both, and the scenario named for the second arm was seeded
    # with the first arm's value and never reached the branch it was named
    # for. Falls back to the union only when the name did not resolve through
    # the condition index at all (a plain field that happens to own 88s),
    # preserving the previous behavior for that path.
    own_values = index.condition_values(name.strip())
    values = (
        own_values if own_values is not None else tuple(resolved.spec.condition_values)
    )
    op = "not_in_set" if negate else "in_set"
    return FieldConstraint(resolved, op, values, origin, False)


def _build_relational_constraint(
    left_text: str,
    op: str,
    right_text: str,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
) -> FieldConstraint | None:
    if not left_text:
        unsupported.append(f"{origin}: comparison missing left operand")
        return None
    left_field = index.resolve(left_text)
    right_field = index.resolve(right_text) if right_text else None

    if left_field is not None and right_field is not None:
        unsupported.append(
            f"{origin}: comparison between two resolved fields not supported in v1: "
            f"{left_field.spec.qualified_name} vs {right_field.spec.qualified_name}"
        )
        return None

    field_ref: ResolvedField
    value_text: str
    if left_field is not None:
        field_ref, value_text = left_field, right_text
    elif right_field is not None:
        field_ref, value_text = right_field, left_text
        op = _FLIPPED_RELATIONAL[op]
    else:
        unsupported.append(
            f"{origin}: unresolvable operand(s) in comparison: {left_text!r} / {right_text!r}"
        )
        return None

    if not _is_boundary_fed(field_ref, fed_names):
        unsupported.append(
            f"{origin}: field not boundary-fed: {field_ref.spec.qualified_name}"
        )
        return None
    if not value_text:
        unsupported.append(
            f"{origin}: comparison missing operand for field {field_ref.spec.qualified_name}"
        )
        return None

    figurative = _figurative_name(value_text)
    if figurative is not None:
        if op not in ("eq", "ne"):
            unsupported.append(
                f"{origin}: unsupported relational comparison against figurative constant"
            )
            return None
        return FieldConstraint(
            field_ref, "figurative", (figurative,), origin, negated=(op == "ne")
        )

    return FieldConstraint(
        field_ref, op, (_strip_quotes(value_text),), origin, negated=False
    )


# -- EVALUATE selector dispatch -----------------------------------------------


def _extract_evaluate_selector(
    selectors: list[Any],
    subject: str | CobolExpression,
    is_true_form: bool,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
) -> list[FieldConstraint] | None:
    if not selectors:
        unsupported.append(f"{origin}: WHEN clause has no selectors")
        return None
    sel = selectors[0]
    if not isinstance(sel, dict):
        unsupported.append(f"{origin}: malformed selector")
        return None
    sel_type = sel.get("type")

    if sel_type == "Any":
        return []

    if is_true_form:
        # The EVALUATE parser never emits an "Identifier" selector type (see
        # evaluate_parser.py's _build_selector): a bare condition-name like
        # `WHEN F1-VALID` arrives as {"type": "Literal", "value": ...}, same
        # as a data-driven literal selector -- only `is_true_form` tells
        # them apart.
        if sel_type == "Literal":
            constraint = _extract_condition_name_value(
                str(sel.get("value", "")), False, index, fed_names, origin, unsupported
            )
            return [constraint] if constraint is not None else None
        if sel_type == "Condition" and "operator" not in sel:
            # A single relational comparison with no AND/OR joins -- reuse
            # the same minimal text parser SEARCH WHEN conditions need,
            # since this selector is raw text here too.
            constraint = _parse_relational_text(
                str(sel.get("text", "")), index, fed_names, origin, unsupported
            )
            return [constraint] if constraint is not None else None
        unsupported.append(
            f"{origin}: EVALUATE TRUE selector type {sel_type!r} not supported in v1"
        )
        return None

    if sel_type == "Condition":
        unsupported.append(
            f"{origin}: compound WHEN condition text not structurally parseable in v1"
        )
        return None

    if not isinstance(subject, str):
        unsupported.append(
            f"{origin}: EVALUATE subject is a computed expression, not a bare field reference"
        )
        return None

    resolved = index.resolve(subject.strip())
    if resolved is None:
        unsupported.append(f"{origin}: unresolvable EVALUATE subject: {subject}")
        return None
    if not _is_boundary_fed(resolved, fed_names):
        unsupported.append(
            f"{origin}: field not boundary-fed: {resolved.spec.qualified_name}"
        )
        return None

    if sel_type == "Literal":
        return [
            FieldConstraint(resolved, "eq", (str(sel.get("value", "")),), origin, False)
        ]
    if sel_type == "Range":
        start = str(sel.get("start", ""))
        end = str(sel.get("end", ""))
        return [
            FieldConstraint(resolved, "ge", (start,), origin, False),
            FieldConstraint(resolved, "le", (end,), origin, False),
        ]

    unsupported.append(f"{origin}: unrecognized selector type: {sel_type!r}")
    return None


# -- SEARCH WHEN / EVALUATE TRUE relational text ------------------------------


def _parse_relational_text(
    text: str,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
) -> FieldConstraint | None:
    text = (text or "").strip()
    if not text:
        unsupported.append(f"{origin}: SEARCH WHEN has no condition text")
        return None

    match = _RELATIONAL_TEXT_RE.match(text)
    if match:
        left, op_token, right = match.groups()
        canon = _RELATIONAL_TEXT_OP_CANON.get(
            re.sub(r"\s+", "", op_token.strip().upper())
        )
        if canon and left.strip():
            return _build_relational_constraint(
                left.strip(),
                canon,
                right.strip(),
                index,
                fed_names,
                origin,
                unsupported,
            )

    if _BARE_IDENTIFIER_RE.match(text):
        return _extract_condition_name_value(
            text, False, index, fed_names, origin, unsupported
        )

    unsupported.append(
        f"{origin}: SEARCH WHEN condition text not structurally parseable in v1: {text!r}"
    )
    return None


# -- boundary-fed / figurative / literal helpers ------------------------------


def _boundary_fed_names(report: BoundaryReport) -> set[str]:
    fed: set[str] = set()
    for boundary in report.boundaries:
        if boundary.direction in ("IN", "BIDIRECTIONAL"):
            fed.update(name.upper() for name in boundary.record_names)
        for arg in boundary.call_args:
            if arg.direction in ("IN", "BIDIRECTIONAL"):
                fed.add(arg.name.upper())
    return fed


def _is_boundary_fed(resolved: ResolvedField, fed_names: set[str]) -> bool:
    return (
        resolved.record.name.upper() in fed_names
        or resolved.spec.name.upper() in fed_names
        or resolved.spec.qualified_name.upper() in fed_names
    )


def _figurative_name(text: str) -> str | None:
    upper = text.strip().upper()
    return upper if upper in _FIGURATIVE_NAMES else None


def _strip_quotes(text: str) -> str:
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return t[1:-1]
    return t


# -- PERFORM UNTIL / EOF-flag pattern -----------------------------------------


def _condition_field_names(expr: CobolExpression | None) -> list[str]:
    """Every bare operand string anywhere in *expr*'s tree (over-approximates
    -- a literal like ``"Y"`` is included too -- but the caller only ever
    looks these up against a name map, so a stray literal simply never
    matches anything real)."""
    if expr is None:
        return []
    if isinstance(expr, LogicalExpression):
        return _condition_field_names(expr.left_condition) + _condition_field_names(
            expr.right_condition
        )
    if isinstance(expr, ConditionalExpression):
        names = []
        for operand in (expr.left_operand, expr.right_operand):
            if isinstance(operand, str) and operand.strip():
                names.append(operand.strip())
        return names
    return []


def _collect_eof_flags(ast: CobolProgram) -> dict[str, list[str | None]]:
    """Map an UPPERCASED field name to the file name(s) of every READ whose
    ``AT END`` clause MOVEs to that field -- the idiom a ``PERFORM UNTIL``
    testing the same field relies on to know when to stop reading."""
    flags: dict[str, list[str | None]] = {}
    for statement in ast.get_all_statements():
        if not isinstance(statement, IOReadStatement) or not statement.at_end_clause:
            continue
        for body_stmt in statement.at_end_clause:
            if isinstance(body_stmt, MoveStatement):
                for target in body_stmt.targets:
                    flags.setdefault(target.upper(), []).append(statement.file_name)
    return flags


def _find_read_boundary_ref(
    report: BoundaryReport, file_name: str | None
) -> BoundaryRef | None:
    if not file_name:
        return None
    key = file_name.upper()
    for boundary in report.boundaries:
        if boundary.ref.category == "READ" and boundary.ref.key == key:
            return boundary.ref
    return None


# -- statement walk (paragraph-aware) -----------------------------------------


def _all_paragraphs(procedure_division: CobolDivision) -> list[CobolParagraph]:
    paragraphs = list(procedure_division.paragraphs)
    for section in procedure_division.sections:
        if isinstance(section, CobolParagraph):
            continue
        paragraphs.extend(section.paragraphs)
    return paragraphs


def _nested_statement_lists(statement: Any) -> list[list[Any]]:
    lists = [
        value
        for attr in _NESTED_STATEMENT_ATTRS
        if (value := getattr(statement, attr, None))
    ]
    if isinstance(statement, EvaluateStatement):
        for when in statement.when_clauses:
            if when.statements:
                lists.append(when.statements)
        if statement.default_when is not None and statement.default_when.statements:
            lists.append(statement.default_when.statements)
    if isinstance(statement, SearchStatement):
        for when_dict in statement.when_clauses:
            if when_dict.get("statements"):
                lists.append(when_dict["statements"])
    return lists


def _walk_statements(procedure_division: CobolDivision) -> Any:
    for paragraph in _all_paragraphs(procedure_division):
        yield from _walk_list(paragraph.paragraph_name, paragraph.statements)


def _walk_list(paragraph_name: str, statements: list[Any]) -> Any:
    for statement in statements:
        yield paragraph_name, statement
        for nested in _nested_statement_lists(statement):
            yield from _walk_list(paragraph_name, nested)


def _branch_id(paragraph_name: str | None, location: SourceLocation | None) -> str:
    line = location.line if location else "?"
    column = location.column if location else "?"
    return f"{paragraph_name or '?'}@{line}:{column}"


__all__ = [
    "FieldConstraint",
    "SequenceConstraint",
    "BranchConstraints",
    "ConstraintReport",
    "ConstraintExtractor",
]
