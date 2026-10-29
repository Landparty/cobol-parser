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
from collections.abc import Iterable
from dataclasses import dataclass, field
from dataclasses import field as dataclass_field
from typing import TYPE_CHECKING, Any

from .._literals import is_quoted_literal, typed_literal_content, unquote_literal
from ..generators.data.layout import all_literal_operand, condition_values_exhaustive
from ..models.ast_base import SourceLocation
from ..models.data_items import ConditionNameItem
from ..models.program import CobolDivision, CobolParagraph, CobolProgram
from ..models.statements.base import (
    CobolExpression,
    ConditionalExpression,
    LogicalExpression,
)
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ..models.statements.data import MoveStatement
from ..models.statements.io import IOReadStatement
from .boundary_inventory import (
    BoundaryRef,
    BoundaryReport,
    _condition_field_names,
    call_argument_data_name,
)

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
# A logical connective in relational text, once quoted literals are masked
# (see _mask_quoted) so `= 'A AND B'` is not mistaken for one.
_LOGICAL_CONNECTIVE_RE = re.compile(r"(?:^|\s|\))(?:AND|OR)(?:\s|\(|$)", re.IGNORECASE)
_QUOTED_TEXT_RE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"")


def _mask_quoted(text: str) -> str:
    """*text* with every quoted literal replaced by an empty one."""
    return _QUOTED_TEXT_RE.sub("''", text)


# ``[IS] [NOT] GREATER|LESS [THAN] [OR EQUAL [TO]]`` and ``[IS] [NOT]
# EQUAL[S] [TO]``: the word spellings of the relational operators.
_RELATIONAL_WORDS_RE = re.compile(
    r"(?<![A-Za-z0-9-])(?:IS\s+)?(NOT\s+)?"
    r"(?:(GREATER|LESS)(?:\s+THAN)?(\s+OR\s+EQUAL(?:\s+TO)?)?|EQUALS?(?:\s+TO)?)"
    r"(?![A-Za-z0-9-])",
    re.IGNORECASE,
)
_NEGATED_SYMBOL = {">": "<=", "<": ">=", ">=": "<", "<=": ">", "=": "<>"}


def _symbolize_relational_words(text: str) -> str:
    """*text* with word-form relational operators spelled as symbols.

    ``X GREATER THAN OR EQUAL TO 1`` becomes ``X >= 1``, so the symbol-only
    text parser below reads it -- and its ``OR`` is no longer mistaken for a
    logical connective. Quoted literals are left as they are.
    """

    def repl(match: re.Match[str]) -> str:
        negated, word, or_equal = match.groups()
        if word is None:
            symbol = "="
        else:
            symbol = ">" if word.upper() == "GREATER" else "<"
            if or_equal:
                symbol += "="
        return f" {_NEGATED_SYMBOL[symbol] if negated else symbol} "

    pieces: list[str] = []
    last = 0
    for quoted in _QUOTED_TEXT_RE.finditer(text):
        pieces.append(_RELATIONAL_WORDS_RE.sub(repl, text[last : quoted.start()]))
        pieces.append(quoted.group(0))
        last = quoted.end()
    pieces.append(_RELATIONAL_WORDS_RE.sub(repl, text[last:]))
    return re.sub(r"\s+", " ", "".join(pieces)).strip()


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
    #: ``False`` when an ``in_set``'s `values` are only a *sample* of what
    #: the condition admits -- a level-88 ``THRU`` range the layout could not
    #: enumerate in full. Still sound for the positive test (any listed value
    #: satisfies it) but not negatable into a ``not_in_set``: a value outside
    #: the sample can still be inside the range. Not part of `to_dict()` or
    #: equality; it only steers what may be derived from this constraint.
    exhaustive: bool = dataclass_field(default=True, compare=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field.spec.qualified_name,
            "op": self.op,
            "values": list(self.values),
            "origin": self.origin,
            "negated": self.negated,
        }


@dataclass(frozen=True)
class CorrelationConstraint(FieldConstraint):
    """A comparison between two *rows* of one read sequence: `field` on
    row n against `source` on row n + `offset` (-1: the record before).

    ``IF F1-GUICHET = WS-PREV-GUICHET``, where the only write to
    `WS-PREV-GUICHET` is an unconditional ``MOVE F1-GUICHET TO
    WS-PREV-GUICHET`` later in the same paragraph, compares each record's
    `F1-GUICHET` with the previous record's: `carrier` names the
    working-storage item that holds the value from one record to the next
    (see `_Carriers`). `values` is empty: what the field is compared with is
    another row's value, which only the planner can pick
    (`ScenarioPlanner`, `PlannedScenario.row_witnesses`).
    """

    source: ResolvedField | None = None
    carrier: str = ""
    offset: int = -1

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field.spec.qualified_name,
            "op": self.op,
            "source": self.source.spec.qualified_name if self.source else None,
            "carrier": self.carrier,
            "offset": self.offset,
            "origin": self.origin,
        }

    def describe(self) -> str:
        source = self.source.spec.qualified_name if self.source else "?"
        symbol = {"eq": "=", "ne": "<>", "lt": "<", "le": "<=", "gt": ">"}.get(
            self.op, ">="
        )
        return (
            f"{self.field.spec.qualified_name} {symbol} the previous record's "
            f"{source} (carried in {self.carrier})"
        )


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
    #: The `(branch_id, arm_id)` chain -- outermost first -- whose arms must
    #: ALL be taken for this decision point to be reached at all. Empty for a
    #: branch at the top level of its paragraph.
    #:
    #: Without it a scenario targeting a nested arm pins only that arm's own
    #: conjuncts, leaving the enclosing condition to whatever the generator
    #: happened to produce -- so the scenario's own name can be a lie, which
    #: is exactly the "labels don't guarantee the data exercises that branch"
    #: problem. `ScenarioPlanner` joins on these pairs to accumulate the path
    #: condition; the ids match the arm keys registered in `arms` above, by
    #: construction (see `_nested_statement_lists`).
    enclosing: tuple[tuple[str, str], ...] = ()
    #: Arm ids registered in `arms` with an EMPTY conjunct list because their
    #: real precondition could not be modeled -- not because the arm is
    #: unconditional -- mapped to the reason. Today: a `WHEN_OTHER` whose
    #: negation of the earlier arms does not fit the vocabulary, and every
    #: SEARCH `AT_END` ("the table search found nothing" is not a field
    #: constraint). The arm stays in `arms` so a nested branch has an
    #: enclosing arm to join to (`path_gaps`), but a consumer must not solve
    #: its `[]` as "anything goes": that targets the arm with data that runs
    #: an earlier WHEN instead (#509). An unconditional empty arm (`WHEN
    #: OTHER` with no earlier WHEN at all) is NOT listed here.
    unmodeled_arms: dict[str, str] = field(default_factory=dict)
    #: Arm id -> its conjuncts that compare two records of one read
    #: sequence (`CorrelationConstraint`), kept apart from `arms` so a
    #: consumer that solves one row at a time never sees them as field
    #: constraints. An arm listed here is never unconditional, even when its
    #: `arms` entry is empty.
    correlations: dict[str, list[CorrelationConstraint]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        extra: dict[str, Any] = {}
        if self.correlations:
            extra["correlations"] = {
                arm: [c.to_dict() for c in constraints]
                for arm, constraints in self.correlations.items()
            }
        return {
            **extra,
            "branch_id": self.branch_id,
            "parent_proc": self.parent_proc,
            "line": self.line,
            "column": self.column,
            "enclosing": [list(pair) for pair in self.enclosing],
            "arms": {
                arm: [c.to_dict() for c in constraints]
                for arm, constraints in self.arms.items()
            },
            "unsupported": list(self.unsupported),
            "unmodeled_arms": dict(self.unmodeled_arms),
        }


@dataclass(frozen=True)
class TransferSite:
    """One out-of-line ``PERFORM p`` or ``GO TO p``, with the branch arms
    that must be taken for it to run (#310).

    `BranchConstraints.enclosing` only reaches the top of its own paragraph;
    a branch in a paragraph that another paragraph PERFORMs from inside an IF
    arm is reached only when that arm is taken too. `ScenarioPlanner` joins a
    branch's paragraph to the sites that transfer control to it to fold
    those arms into the scenario's path condition.
    """

    paragraph: str
    target: str
    kind: str  # "PERFORM" | "GOTO" | "GOTO_DEPENDING"
    enclosing: tuple[tuple[str, str], ...] = ()
    line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "paragraph": self.paragraph,
            "target": self.target,
            "kind": self.kind,
            "enclosing": [list(pair) for pair in self.enclosing],
            "line": self.line,
        }


@dataclass
class ConstraintReport:
    branches: list[BranchConstraints] = field(default_factory=list)
    sequence_constraints: list[SequenceConstraint] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    transfer_sites: list[TransferSite] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "branches": [b.to_dict() for b in self.branches],
            "sequence_constraints": [s.to_dict() for s in self.sequence_constraints],
            "unsupported": list(self.unsupported),
            "transfer_sites": [t.to_dict() for t in self.transfer_sites],
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
        *,
        extra_fed_names: Iterable[str] = (),
    ) -> ConstraintReport:
        """``extra_fed_names`` -- data names to treat as boundary-fed on top
        of what ``boundary_report`` feeds: a subprogram's own PROCEDURE
        DIVISION USING parameters, which its caller supplies
        (``ProgramFixtureGenerator(entry_parameters=True)``)."""
        report = ConstraintReport()
        procedure = ast.get_division("PROCEDURE")
        if procedure is None:
            return report

        fed_names = _boundary_fed_names(boundary_report)
        fed_names.update(name.upper() for name in extra_fed_names)
        eof_flags = _collect_eof_flags(ast)
        carriers = _Carriers(ast, procedure, index, fed_names)

        for paragraph_name, statement, enclosing in _walk_statements(procedure):
            _record_transfer_site(statement, paragraph_name, enclosing, report)
            if isinstance(statement, IfStatement) and statement.condition is not None:
                self._extract_if(
                    statement,
                    paragraph_name,
                    index,
                    fed_names,
                    report,
                    enclosing,
                    carriers,
                )
            elif isinstance(statement, EvaluateStatement):
                self._extract_evaluate(
                    statement, paragraph_name, index, fed_names, report, enclosing
                )
            elif isinstance(statement, SearchStatement):
                self._extract_search(
                    statement, paragraph_name, index, fed_names, report, enclosing
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
        _roll_up_branch_gaps(report)
        return report

    # -- IF ---------------------------------------------------------------

    @staticmethod
    def _extract_if(
        statement: IfStatement,
        paragraph_name: str,
        index: ProgramLayoutIndex,
        fed_names: set[str],
        report: ConstraintReport,
        enclosing: tuple[tuple[str, str], ...] = (),
        carriers: _Carriers | None = None,
    ) -> None:
        branch_id = _branch_id(paragraph_name, statement.location)
        line = statement.location.line if statement.location else None
        column = statement.location.column if statement.location else None
        arms: dict[str, list[FieldConstraint]] = {}
        correlations: dict[str, list[CorrelationConstraint]] = {}
        unsupported: list[str] = []
        site = (
            _CarrierSite(carriers, paragraph_name, line or 0, enclosing)
            if carriers is not None
            else None
        )

        then_variants = _extract_expr(
            statement.condition,
            False,
            index,
            fed_names,
            f"IF@{line}",
            unsupported,
            site,
        )
        _register_variants(arms, "THEN", then_variants, correlations)

        else_variants = _extract_expr(
            statement.condition,
            True,
            index,
            fed_names,
            f"IF@{line}/ELSE",
            unsupported,
            site,
        )
        _register_variants(arms, "ELSE", else_variants, correlations)

        if arms or unsupported:
            report.branches.append(
                BranchConstraints(
                    branch_id=branch_id,
                    parent_proc=paragraph_name,
                    line=line,
                    column=column,
                    arms=arms,
                    unsupported=unsupported,
                    enclosing=enclosing,
                    correlations=correlations,
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
        enclosing: tuple[tuple[str, str], ...] = (),
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
                    enclosing=enclosing,
                )
            )
            return

        subject = statement.subjects[0]
        is_true_form = isinstance(subject, str) and subject.strip().upper() == "TRUE"

        any_when_unsupported = False
        # Each WHEN arm's own selector constraints, before the earlier arms'
        # negations are conjoined -- what WHEN OTHER and later arms negate.
        own_arms: dict[str, list[FieldConstraint]] = {}
        # Stacked WHENs (``WHEN 'A' WHEN 'B' stmt``) are one arm, numbered
        # by group; each phrase of a stack is an OR-split disjunct of it
        # (``WHEN_1#1`` / ``WHEN_1#2``), a scenario of its own as for IF.
        for idx, group in enumerate(statement.when_groups(), start=1):
            arm_id = f"WHEN_{idx}"
            origin = f"EVALUATE@{line}/WHEN#{idx}"
            variants: list[list[FieldConstraint]] = []
            for member in group:
                constraints = _extract_evaluate_selector(
                    member.selectors,
                    subject,
                    is_true_form,
                    index,
                    fed_names,
                    origin,
                    unsupported,
                )
                if constraints is None:
                    break
                variants.append(constraints)
            if len(variants) == len(group):
                # EVALUATE is first-match: WHEN_n runs only when every earlier
                # WHEN failed, so its data must also falsify each of them. A
                # witness solved from WHEN_n's own selector alone could land in
                # an earlier arm (``WHEN A > 50 / WHEN A > 10`` witnessing 55
                # for the second) and the scenario named for WHEN_n would never
                # reach it.
                negations = _negate_earlier_whens(
                    own_arms, any_when_unsupported, origin, unsupported
                )
                _register_variants(
                    arms, arm_id, [variant + negations for variant in variants]
                )
                _register_variants(own_arms, arm_id, variants)
            else:
                any_when_unsupported = True

        unmodeled_arms: dict[str, str] = {}
        if statement.default_when is not None:
            other_origin = f"EVALUATE@{line}/WHEN_OTHER"
            if any_when_unsupported:
                # Left out of `arms`, exactly like the unsupported WHEN it
                # follows: the planner then reports it missed for that
                # sibling's own reason (`WHEN#1: field not boundary-fed:
                # WS-MODE`) -- not as an unmodeled arm that fails --strict
                # while the WHENs it shares a cause with do not.
                unsupported.append(
                    f"{other_origin}: not modeled -- a prior WHEN arm was "
                    "itself unsupported"
                )
            else:
                negation = _negate_prior_arms(own_arms, other_origin, unsupported)
                if negation is None:
                    arms["WHEN_OTHER"] = []
                    unmodeled_arms["WHEN_OTHER"] = unsupported[-1]
                else:
                    arms["WHEN_OTHER"] = negation

        if arms or unsupported:
            report.branches.append(
                BranchConstraints(
                    branch_id=branch_id,
                    parent_proc=paragraph_name,
                    line=line,
                    column=column,
                    arms=arms,
                    unsupported=unsupported,
                    enclosing=enclosing,
                    unmodeled_arms=unmodeled_arms,
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
        enclosing: tuple[tuple[str, str], ...] = (),
    ) -> None:
        branch_id = _branch_id(paragraph_name, statement.location)
        line = statement.location.line if statement.location else None
        column = statement.location.column if statement.location else None
        arms: dict[str, list[FieldConstraint]] = {}
        unsupported: list[str] = []

        for idx, when_dict in enumerate(statement.when_clauses, start=1):
            arm_id = f"WHEN_{idx}"
            origin = f"SEARCH@{line}/WHEN#{idx}"
            # The structural tree (see search_parser._condition_tree) is
            # the only form in which a compound WHEN is several comparisons:
            # the raw text, split on its first operator, turned
            # `A = 'K1' AND B = 'Z'` into one equality against the literal
            # "K1' AND B = 'Z". The text path stays for SEARCH nodes built
            # without a tree.
            tree = when_dict.get("condition_tree")
            if tree is not None:
                _register_variants(
                    arms,
                    arm_id,
                    _extract_expr(tree, False, index, fed_names, origin, unsupported),
                )
                continue
            constraint = _parse_relational_text(
                when_dict.get("condition", ""), index, fed_names, origin, unsupported
            )
            if constraint is not None:
                arms[arm_id] = [constraint]

        unmodeled_arms: dict[str, str] = {}
        if statement.at_end_clause:
            arms["AT_END"] = []
            unmodeled_arms["AT_END"] = (
                f"SEARCH@{line}/AT_END: not modeled -- 'the search found no "
                "matching entry' depends on the table's contents, not on a "
                "field constraint"
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
                    enclosing=enclosing,
                    unmodeled_arms=unmodeled_arms,
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


def _roll_up_branch_gaps(report: ConstraintReport) -> None:
    """Copy every branch-level gap into the report-level ``unsupported`` list.

    :attr:`ConstraintReport.unsupported` is documented -- here, in
    ``CLAUDE.md`` and in the public examples -- as the place gaps are never
    silently dropped.  It used to hold only the gaps appended to it directly
    (the PERFORM UNTIL paths), while everything a *branch* could not model
    lived on :attr:`BranchConstraints.unsupported` and nowhere else.  A
    caller following the documented API therefore saw a clean list for a
    program with unmodelled branches, which is the one thing this field
    exists to prevent.

    Branch entries stay on their branch as well: a caller that wants to know
    *which* decision point a gap belongs to still needs them there.  Ordering
    is source order (branches are appended as they are walked) after whatever
    was reported program-level, and duplicates are collapsed so a reason
    reported by several arms of one branch is listed once.
    """
    seen = set(report.unsupported)
    for branch in report.branches:
        for reason in branch.unsupported:
            if reason not in seen:
                seen.add(reason)
                report.unsupported.append(reason)


# -- expression-tree walk (IF / PERFORM UNTIL) --------------------------------


def _extract_expr(
    expr: CobolExpression | None,
    negate: bool,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
    site: _CarrierSite | None = None,
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
        if expr.operator == "NOT":
            # The parser's unary wrapper (see LogicalExpression): what it
            # builds for a negation it cannot fold into the operand itself --
            # `NOT FLAG-ON`, `NOT (A = 1 AND B = 2)`. The negated condition is
            # `left_condition`; negating it is just flipping `negate` for the
            # subtree, which De Morgan then carries through any AND/OR below.
            # Rejecting it left the commonest negated-88 idiom (`IF NOT
            # EOF-REACHED`) with both arms unmodeled.
            return _extract_expr(
                expr.left_condition,
                not negate,
                index,
                fed_names,
                origin,
                unsupported,
                site,
            )
        if expr.operator not in ("AND", "OR"):
            unsupported.append(
                f"{origin}: unsupported logical operator: {expr.operator}"
            )
            return []
        is_conjunction = (expr.operator == "AND") != negate
        left = _extract_expr(
            expr.left_condition, negate, index, fed_names, origin, unsupported, site
        )
        right = _extract_expr(
            expr.right_condition, negate, index, fed_names, origin, unsupported, site
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
            expr, negate, index, fed_names, origin, unsupported, site
        )
        return [[constraint]] if constraint is not None else []

    unsupported.append(f"{origin}: unsupported expression node: {type(expr).__name__}")
    return []


def _register_variants(
    arms: dict[str, list[FieldConstraint]],
    base_arm_id: str,
    variants: list[list[FieldConstraint]],
    correlations: dict[str, list[CorrelationConstraint]] | None = None,
) -> None:
    """Register each variant as an arm; a `CorrelationConstraint` conjunct
    goes to *correlations* under the same arm id (only `_extract_if` builds
    them, and it always passes the dict)."""
    if not variants:
        return
    ids = (
        [base_arm_id]
        if len(variants) == 1
        else [f"{base_arm_id}#{i}" for i in range(1, len(variants) + 1)]
    )
    for arm_id, variant in zip(ids, variants, strict=True):
        arms[arm_id] = [c for c in variant if not isinstance(c, CorrelationConstraint)]
        linked = [c for c in variant if isinstance(c, CorrelationConstraint)]
        if linked and correlations is not None:
            correlations[arm_id] = linked


def _extract_comparison(
    expr: ConditionalExpression,
    negate: bool,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
    site: _CarrierSite | None = None,
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
            site=site,
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
    if class_word == "OMITTED":
        # Decided by the caller's argument list, not by any data value.
        unsupported.append(
            f"{origin}: OMITTED test depends on the caller's argument list, "
            f"not on data: {name.strip()}"
        )
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

    if class_word in ("DBCS", "KANJI"):
        unsupported.append(
            f"{origin}: unsupported class condition: {class_word} "
            "(DBCS/KANJI double-byte tests are out of v1 scope)"
        )
        return None
    unsupported.append(
        f"{origin}: user-defined class condition (SPECIAL-NAMES CLASS) not "
        f"supported in v1: {class_word}"
    )
    return None


def _negate_constraint(constraint: FieldConstraint) -> FieldConstraint | None:
    """The single constraint meaning NOT `constraint`, or ``None``."""
    op = constraint.op
    if op in _NEGATED_RELATIONAL:
        new_op, negated = _NEGATED_RELATIONAL[op], constraint.negated
    elif op == "in_set" and constraint.exhaustive and not constraint.negated:
        new_op, negated = "not_in_set", False
    elif op == "not_in_set" and not constraint.negated:
        new_op, negated = "in_set", False
    elif op in ("class_numeric", "class_alphabetic", "figurative"):
        new_op, negated = op, not constraint.negated
    else:
        return None
    return FieldConstraint(
        constraint.field, new_op, constraint.values, constraint.origin, negated
    )


def _negate_earlier_whens(
    arms: dict[str, list[FieldConstraint]],
    any_earlier_unsupported: bool,
    origin: str,
    unsupported: list[str],
) -> list[FieldConstraint]:
    """The conjunction NOT(WHEN_1) AND ... AND NOT(WHEN_n-1), as far as it goes.

    Only a single-conjunct earlier arm negates into one FieldConstraint;
    NOT(a AND b) is a disjunction the vocabulary cannot express. Such an arm,
    or one that was itself unsupported, is left out and said so in
    `unsupported` -- the later arm's witness may then still be shadowed.
    """
    negations: list[FieldConstraint] = []
    skipped = any_earlier_unsupported
    for arm_id, conjuncts in arms.items():
        if not arm_id.startswith("WHEN_") or arm_id == "WHEN_OTHER":
            continue
        negated = _negate_constraint(conjuncts[0]) if len(conjuncts) == 1 else None
        if negated is None:
            skipped = True
            continue
        negations.append(negated)
    if skipped:
        unsupported.append(
            f"{origin}: not every earlier WHEN arm could be negated, so this "
            "arm's witness may satisfy an earlier arm and never reach it"
        )
    return negations


def _negate_prior_arms(
    arms: dict[str, list[FieldConstraint]],
    origin: str,
    unsupported: list[str],
) -> list[FieldConstraint] | None:
    """WHEN OTHER's real condition: the negation of every preceding arm.

    Modeled for the shape that actually dominates real COBOL -- an
    ``EVALUATE`` whose every arm is a single equality-or-membership test on
    the *same* field (``EVALUATE TYPE-P-BAL / WHEN "05" / WHEN "09" / WHEN
    OTHER``, or its ``EVALUATE TRUE / WHEN <88>`` spelling). There the
    negation is exactly one ``not_in_set`` over the union of every arm's
    values, which is both sound and solvable.

    Anything else (arms over different fields, conjunctions, relational or
    class tests) needs a real disjunction the FieldConstraint vocabulary
    cannot express: the reason goes into `unsupported` and the result is
    ``None`` -- distinct from ``[]`` ("no earlier arm, so nothing to
    negate"), so the caller can record the arm in
    `BranchConstraints.unmodeled_arms` rather than hand a planner an empty
    list it would solve as "anything goes" (#509).

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
            return None
        constraint = conjuncts[0]
        if not constraint.exhaustive:
            unsupported.append(
                f"{origin}: not modeled -- a prior arm tests a condition name "
                f"whose values on {constraint.field.spec.qualified_name} cannot "
                "be listed exhaustively (a THRU range or figurative constant), "
                "so its negation is not a not_in_set"
            )
            return None
        if constraint.op not in ("eq", "in_set") or constraint.negated:
            unsupported.append(
                f"{origin}: not modeled -- a prior arm uses {constraint.op}, "
                "which does not negate to a single not_in_set"
            )
            return None
        if field is None:
            field = constraint.field
        elif field.spec.qualified_name != constraint.field.spec.qualified_name:
            unsupported.append(
                f"{origin}: not modeled -- prior arms test different fields "
                f"({field.spec.qualified_name}, "
                f"{constraint.field.spec.qualified_name})"
            )
            return None
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
    raw_values = index.condition_raw_values(name.strip())
    if own_values is None or raw_values is None:
        values = tuple(resolved.spec.condition_values)
        op = "not_in_set" if negate else "in_set"
        return FieldConstraint(resolved, op, values, origin, False)

    upper_raw = [value.strip().upper() for value in raw_values]
    if "ALL" in upper_raw:
        # A bare ``ALL`` with nothing repeatable after it.
        unsupported.append(
            f"{origin}: condition name {name.strip()} has a VALUE ALL literal, "
            "which is not modeled in v1"
        )
        return None
    # ``VALUE ALL 'X'`` is the one value that fills the field with X (which
    # is what ``own_values`` already holds, expanded to the field's width);
    # ``VALUE ALL SPACES`` is the figurative constant SPACES.
    upper_raw = [
        (all_literal_operand(value) or value).strip().upper() for value in raw_values
    ]
    figuratives = [value for value in upper_raw if value in _FIGURATIVE_NAMES]
    if figuratives and len(upper_raw) == 1:
        # `88 BLANK-NAME VALUE SPACES` is the figurative comparison `IF
        # NAME = SPACES`, and gets exactly that constraint. Read as an
        # in_set, the word itself became the witness ("SPACES", rendered
        # "SPA" into a PIC X(3)), which satisfies neither arm.
        return FieldConstraint(
            resolved, "figurative", (figuratives[0],), origin, negated=negate
        )
    exhaustive = condition_values_exhaustive(
        list(raw_values), resolved.spec.decimal_digits
    )
    if negate and not exhaustive:
        # `NOT <88>` as a not_in_set over the listed values is only sound
        # when the list is the whole condition. For `VALUE 1 THRU 999999` it
        # is the first 65 values, and the solver's midpoint (499999) sat
        # squarely inside the range the arm excludes.
        unsupported.append(
            f"{origin}: NOT {name.strip()} is not modeled -- its values on "
            f"{resolved.spec.qualified_name} (a THRU range or figurative "
            "constant) cannot be listed exhaustively"
        )
        return None
    values = tuple(v for v in own_values if v.upper() not in _FIGURATIVE_NAMES)
    if not values:
        unsupported.append(
            f"{origin}: condition name {name.strip()} has no literal VALUE to " "model"
        )
        return None
    op = "not_in_set" if negate else "in_set"
    return FieldConstraint(resolved, op, values, origin, False, exhaustive=exhaustive)


def _build_relational_constraint(
    left_text: str,
    op: str,
    right_text: str,
    index: ProgramLayoutIndex,
    fed_names: set[str],
    origin: str,
    unsupported: list[str],
    *,
    quoted_operands: bool = True,
    site: _CarrierSite | None = None,
) -> FieldConstraint | None:
    if not left_text:
        unsupported.append(f"{origin}: comparison missing left operand")
        return None
    left_field = index.resolve(left_text)
    right_field = index.resolve(right_text) if right_text else None

    if left_field is not None and right_field is not None:
        if site is not None:
            correlation = site.correlation(left_field, op, right_field, origin)
            if correlation is not None:
                return correlation
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

    if not _is_literal_operand(value_text, quoted=quoted_operands):
        # A data item, a subscripted table element, an expression -- something
        # whose value only the running program knows. Treating the operand's
        # source text as the compared-against value fabricates a constraint
        # nothing can satisfy, and (worse) leaves the arm counted as targeted
        # with no gap recorded. Report it the same way a comparison between
        # two *resolvable* fields is reported above: this is the same case,
        # differing only in whether the layout index happened to resolve it.
        unsupported.append(
            f"{origin}: comparison against a non-literal operand not supported "
            f"in v1: {field_ref.spec.qualified_name} {op} {value_text!r}"
        )
        return None

    return FieldConstraint(
        field_ref, op, (_literal_value(value_text),), origin, negated=False
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

    # The lexer strips quotes before a selector dict is built, so `WHEN "AB"`
    # and `WHEN WS-OTHER` arrive here indistinguishable by value alone. The
    # only discriminator left is whether the value names a real data item:
    # if it resolves, it is an identifier and the comparison is against a
    # value only the running program knows -- the same fabrication
    # `_build_relational_constraint` refuses. A string literal that happens
    # to equal a data name is reported unsupported rather than modelled;
    # that is the rare case, and it errs toward the visible answer.
    if sel_type == "Literal":
        value = str(sel.get("value", ""))
        if sel.get("expression") or (
            not sel.get("quoted") and not _is_literal_operand(value, quoted=False)
        ):
            # ``WHEN WS-N + 1`` / ``WHEN WS-B (1:2)``: a value the running
            # program computes, not the literal text (#333).
            unsupported.append(
                f"{origin}: WHEN selector is a computed operand rather than a "
                f"literal, which is not supported in v1: {value}"
            )
            return None
        if sel.get("figurative"):
            # ``WHEN SPACES`` is the figurative constant, not the six
            # characters S-P-A-C-E-S: model it as the IF path does.
            figurative = _figurative_name(value)
            if figurative is None:
                unsupported.append(
                    f"{origin}: WHEN figurative constant not supported in v1: "
                    f"{value}"
                )
                return None
            return [
                FieldConstraint(resolved, "figurative", (figurative,), origin, False)
            ]
        if not sel.get("quoted") and index.resolve(value) is not None:
            unsupported.append(
                f"{origin}: WHEN selector names a data item rather than a "
                f"literal, which is not supported in v1: {value}"
            )
            return None
        return [
            FieldConstraint(resolved, "eq", (_literal_value(value),), origin, False)
        ]
    if sel_type == "Range":
        computed = [
            str(sel.get(key, ""))
            for key in ("start", "end")
            if not sel.get(f"{key}_quoted")
            and not _is_literal_operand(str(sel.get(key, "")), quoted=False)
        ]
        if computed:
            unsupported.append(
                f"{origin}: WHEN range bound is a computed operand rather than "
                f"a literal, which is not supported in v1: {', '.join(computed)}"
            )
            return None
        start = _literal_value(str(sel.get("start", "")))
        end = _literal_value(str(sel.get("end", "")))
        named = [bound for bound in (start, end) if index.resolve(bound) is not None]
        if named:
            unsupported.append(
                f"{origin}: WHEN range bound names a data item rather than a "
                f"literal, which is not supported in v1: {', '.join(named)}"
            )
            return None
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
    text = _symbolize_relational_words(text)

    if _LOGICAL_CONNECTIVE_RE.search(_mask_quoted(text)):
        # A compound condition: the regex below would take everything after
        # the first operator, AND/OR included, as the right-hand literal --
        # a made-up value no record can carry to reach the arm.
        unsupported.append(
            f"{origin}: compound condition text (AND/OR) not structurally "
            f"parseable in v1: {text!r}"
        )
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
                # SEARCH WHEN / EVALUATE TRUE selector text arrives already
                # unquoted from the lexer -- see _is_literal_operand.
                quoted_operands=False,
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


# -- cross-record carriers ------------------------------------------------------

#: Xref roles that may change an item's value.
_WRITING_ROLES = frozenset(
    {"write", "call-argument", "host-variable", "reference", "file-operation"}
)


@dataclass(frozen=True)
class _CarrierSite:
    """Where a comparison sits, for deciding whether a field it names
    carries a value from the previous record (`_Carriers.correlation`)."""

    carriers: _Carriers
    paragraph: str
    line: int
    enclosing: tuple[tuple[str, str], ...]

    def correlation(
        self,
        left: ResolvedField,
        op: str,
        right: ResolvedField,
        origin: str,
    ) -> CorrelationConstraint | None:
        return self.carriers.correlation(self, left, op, right, origin)


class _Carriers:
    """Working-storage items that hold a boundary-fed field's value from one
    record to the next: ``MOVE F1-KEY TO WS-PREV-KEY`` at the end of the
    paragraph that compares ``F1-KEY = WS-PREV-KEY``.

    "Exact by construction, or absent": an item is a carrier only when all
    of these hold, and a comparison naming anything else stays unsupported
    as before --

    * it is not boundary-fed itself, is declared once, and neither it nor a
      group above it REDEFINES or is REDEFINED;
    * the only statement that may change it, or any group above it, or set
      one of its level-88 names, is one ``MOVE source TO it`` (xref roles);
    * that MOVE is not CORRESPONDING, its source is a single boundary-fed
      field, and it sits unconditionally (no enclosing branch arm) in the
      comparison's own paragraph, *after* the comparison -- so when the
      comparison runs, the item still holds the value the previous run of the
      paragraph moved there.

    A MOVE before the comparison would carry the *current* record, which is
    not a cross-record correlation; it stays unsupported.
    """

    def __init__(
        self,
        ast: CobolProgram,
        procedure: CobolDivision,
        index: ProgramLayoutIndex,
        fed_names: set[str],
    ) -> None:
        self._ast = ast
        self._procedure = procedure
        self._index = index
        self._fed = fed_names
        self._moves: dict[str, list[tuple[str, MoveStatement, bool]]] | None = None
        self._xref: Any = None

    def _collect(self) -> dict[str, list[tuple[str, MoveStatement, bool]]]:
        if self._moves is None:
            self._moves = {}
            for paragraph, statement, enclosing in _walk_statements(self._procedure):
                if not isinstance(statement, MoveStatement):
                    continue
                for target in statement.targets:
                    resolved = self._index.resolve(str(target))
                    if resolved is not None:
                        self._moves.setdefault(
                            resolved.spec.qualified_name.upper(), []
                        ).append((paragraph or "", statement, bool(enclosing)))
        return self._moves

    def _references(self) -> Any:
        if self._xref is None:
            from .xref import XrefAnalyzer

            self._xref = XrefAnalyzer().analyze(self._ast)
        return self._xref

    def correlation(
        self,
        site: _CarrierSite,
        left: ResolvedField,
        op: str,
        right: ResolvedField,
        origin: str,
    ) -> CorrelationConstraint | None:
        left_fed = _is_boundary_fed(left, self._fed)
        right_fed = _is_boundary_fed(right, self._fed)
        if left_fed == right_fed:
            return None
        fed, carrier = (left, right) if left_fed else (right, left)
        if not left_fed:
            op = _FLIPPED_RELATIONAL[op]
        source = self._carried(site, carrier)
        if source is None:
            return None
        return CorrelationConstraint(
            fed,
            op,
            (),
            origin,
            source=source,
            carrier=carrier.spec.qualified_name,
        )

    def _carried(
        self, site: _CarrierSite, carrier: ResolvedField
    ) -> ResolvedField | None:
        """The boundary-fed field *carrier* holds from the previous record,
        or None when it is not a carrier at this site."""
        qname = carrier.spec.qualified_name.upper()
        moves = self._collect().get(qname, [])
        if len(moves) != 1:
            return None
        paragraph, move, guarded = moves[0]
        if (
            guarded
            or move.is_corresponding
            or paragraph.upper() != (site.paragraph or "").upper()
            or move.location is None
            or move.location.line <= site.line
            or not move.source
        ):
            return None
        source = self._index.resolve(str(move.source))
        if source is None or not _is_boundary_fed(source, self._fed):
            return None
        if not self._only_written_by(carrier, move.location.line):
            return None
        return source

    def _only_written_by(self, carrier: ResolvedField, line: int) -> bool:
        """True when the MOVE at *line* is the one statement that may change
        *carrier*'s value (through it, a group above it, or a level-88 name
        of it), and no REDEFINES touches it."""
        segments = carrier.spec.qualified_name.upper().split(".")
        chain = [carrier.record]
        node: Any = carrier.record
        for name in segments[1:]:
            node = next(
                (
                    child
                    for child in getattr(node, "children", [])
                    if str(getattr(child, "name", "")).upper() == name
                ),
                None,
            )
            if node is None:
                return False
            chain.append(node)
        names = {str(item.name).upper() for item in chain}
        if any(getattr(item, "redefines", None) for item in chain):
            return False
        for item in self._ast.traverse_depth_first():
            if str(getattr(item, "redefines", "") or "").upper() in names:
                return False
        report = self._references()
        writes = 0
        for depth, item in enumerate(chain):
            qualified = " OF ".join(reversed(segments[: depth + 1]))
            entries = report.entries_named(qualified)
            if len(entries) != 1:
                return False
            for ref in entries[0].references:
                if ref.role not in _WRITING_ROLES:
                    continue
                if item is chain[-1] and ref.location.line == line and writes == 0:
                    writes += 1
                    continue
                return False
        for child in getattr(chain[-1], "children", []):
            if isinstance(child, ConditionNameItem):
                for entry in report.entries_named(str(child.name)):
                    if any(r.role in _WRITING_ROLES for r in entry.references):
                        return False
        return writes == 1


def _boundary_fed_names(report: BoundaryReport) -> set[str]:
    fed: set[str] = set()
    for boundary in report.boundaries:
        if boundary.direction in ("IN", "BIDIRECTIONAL"):
            fed.update(name.upper() for name in boundary.record_names)
        for arg in boundary.call_args:
            if arg.direction in ("IN", "BIDIRECTIONAL"):
                # ``ADDRESS OF X`` feeds X; constants feed nothing (#582).
                data_name = call_argument_data_name(arg.name)
                if data_name is not None:
                    fed.add(data_name.upper())
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
    # Delimiters off and doubled delimiters collapsed: `IF X = '"'` reaches
    # here as `""""` (see `quote_literal`) and means the one character `"`.
    # A typed literal stands for its decoded characters: `X'0000'` is two
    # bytes, `X'C1'` one (#331).
    typed = typed_literal_content(text)
    if typed is not None:
        return typed
    return unquote_literal(text)


#: A sign the lexer emitted as its own token, so ``-5`` reaches us as
#: ``- 5``.  Collapsed before a value is stored on a constraint: the solver
#: parses it with ``Decimal``, which rejects the spaced form -- and used to
#: drop the whole constraint on the floor when it did.
_SIGN_SPACE_RE = re.compile(r"^([+-])\s+")


def _literal_value(text: str) -> str:
    """The comparison value to store for a literal operand: quotes stripped,
    a detached sign reattached (``- 5`` -> ``-5``)."""
    return _SIGN_SPACE_RE.sub(r"\1", _strip_quotes(text))


#: A numeric literal as the operand text actually reaches us.  The sign is
#: its own token upstream, so ``-45`` arrives as ``- 45`` -- the whitespace
#: is not optional politeness, it is the shape of the input.
_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?\s*\d+(?:\.\d+)?$")


def _is_literal_operand(text: str, *, quoted: bool = True) -> bool:
    """Whether *text* is a literal rather than a reference to a data item.

    The one thing standing between a comparison and a fabricated constraint.
    Everything that is not a literal here -- a bare data name, a subscripted
    table reference like ``WS-E ( IDX )``, an arithmetic expression -- names a
    *value the program computes*, which this extractor has no way to know.
    Using such text as though it were the compared-against value produces a
    constraint the program never expressed: a witness solved against it can
    never reach the branch, and the arm is nonetheless counted as targeted.

    *quoted* says whether the caller's operand text still carries its quotes,
    because that decides how much can be told about it:

    * ``True`` -- an ``IF``'s :class:`ConditionalExpression` operand, which
      reaches us as written (``'AB'``, ``123``, ``- 45``).  The test is a
      whitelist: quoted, or numeric.  A literal form not on it is reported as
      unsupported -- a visible, fixable gap rather than a silent value.
    * ``False`` -- ``SEARCH WHEN`` and ``EVALUATE TRUE`` selector *text*,
      which the lexer has already unquoted, so ``'Z'`` and a bare ``Z``
      are no longer distinguishable and a whitelist would reject every
      string literal in those constructs.  Only what cannot be a literal at
      all is rejected there: parentheses or internal whitespace, i.e. a
      subscript or an expression.  A bare word stays admissible, and the
      caller has already ruled out the ones that resolve to real data items.

    ``ALL 'X'`` is excluded either way, on purpose: it is a literal, but it
    denotes the character repeated to the receiving field's width, and
    modelling it as the one-character value ``X`` would be its own quiet
    wrong answer.
    """
    t = text.strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        return True
    if is_quoted_literal(t):
        # A typed literal: `X'00'`, `Z'AB'` (#331).
        return True
    if _NUMERIC_LITERAL_RE.match(t):
        return True
    if quoted:
        return False
    return not ("(" in t or ")" in t or any(ch.isspace() for ch in t))


# -- PERFORM UNTIL / EOF-flag pattern -----------------------------------------


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


def _nested_statement_lists(statement: Any) -> list[tuple[str | None, list[Any]]]:
    """Every nested statement list, paired with the ARM-ID it sits under when
    that nesting is a modeled branch arm (`None` otherwise).

    The arm id is what lets `_walk_list` build each statement's enclosing
    path, so a nested branch's scenario can carry the conditions that must
    hold for its own arm to be reached at all. The ids match the ones
    `_extract_if`/`_extract_evaluate`/`_extract_search` register in
    `BranchConstraints.arms`, since the path is joined back to those arms by
    `(branch_id, arm_id)`.

    A non-branch nesting (`AT END`, `ON EXCEPTION`, an inline `PERFORM`
    body) contributes no arm: it IS a path condition in the general sense,
    but this module does not model those as branch arms, and inventing an
    id for one would produce a path entry nothing could ever join to.
    """
    lists: list[tuple[str | None, list[Any]]] = []
    if isinstance(statement, IfStatement):
        if getattr(statement, "then_statements", None):
            lists.append(("THEN", statement.then_statements))
        if getattr(statement, "else_statements", None):
            lists.append(("ELSE", statement.else_statements))
    arm_bearing = next(
        (
            mapping
            for cls, mapping in _ARM_BEARING_ATTRS.items()
            if isinstance(statement, cls)
        ),
        {},
    )
    for attr in _NESTED_STATEMENT_ATTRS:
        if isinstance(statement, IfStatement) and attr in (
            "then_statements",
            "else_statements",
        ):
            continue  # already paired with their arm ids above
        value = getattr(statement, attr, None)
        if value:
            lists.append((arm_bearing.get(attr), value))
    if isinstance(statement, EvaluateStatement):
        for index, group in enumerate(statement.when_groups(), start=1):
            if group[-1].statements:
                lists.append((f"WHEN_{index}", group[-1].statements))
        if statement.default_when is not None and statement.default_when.statements:
            lists.append(("WHEN_OTHER", statement.default_when.statements))
    if isinstance(statement, SearchStatement):
        for index, when_dict in enumerate(statement.when_clauses, start=1):
            if when_dict.get("statements"):
                lists.append((f"WHEN_{index}", when_dict["statements"]))
    return lists


#: Nested statement lists that ARE a modeled branch arm despite living on a
#: `_NESTED_STATEMENT_ATTRS` attribute rather than in a `when_clauses` list.
#: Only SEARCH's `AT END` qualifies today: `_extract_search` registers an
#: `arms["AT_END"]` entry for it, so a statement nested under it does have an
#: enclosing path condition to join to. Without this, that statement's
#: `enclosing` chain silently omits the SEARCH -- and a scenario for a branch
#: inside it could be reported "verified" without its data establishing that
#: the table search found nothing.
_ARM_BEARING_ATTRS: dict[type, dict[str, str]] = {
    SearchStatement: {"at_end_clause": "AT_END"}
}


def _walk_statements(procedure_division: CobolDivision) -> Any:
    for paragraph in _all_paragraphs(procedure_division):
        yield from _walk_list(paragraph.paragraph_name, paragraph.statements, ())


def _walk_list(
    paragraph_name: str,
    statements: list[Any],
    enclosing: tuple[tuple[str, str], ...],
) -> Any:
    """Yield `(paragraph_name, statement, enclosing)`, where `enclosing` is
    the chain of `(branch_id, arm_id)` pairs -- outermost first -- whose arms
    must all be taken for `statement` to execute."""
    for statement in statements:
        yield paragraph_name, statement, enclosing
        is_branch = isinstance(
            statement, (IfStatement, EvaluateStatement, SearchStatement)
        )
        branch_id = (
            _branch_id(paragraph_name, statement.location) if is_branch else None
        )
        for arm_id, nested in _nested_statement_lists(statement):
            deeper = (
                enclosing + ((branch_id, arm_id),)
                if arm_id is not None and branch_id is not None
                else enclosing
            )
            yield from _walk_list(paragraph_name, nested, deeper)


def _record_transfer_site(
    statement: Any,
    paragraph_name: str,
    enclosing: tuple[tuple[str, str], ...],
    report: ConstraintReport,
) -> None:
    """Record *statement* as a `TransferSite` when it is an out-of-line
    ``PERFORM p [THRU q]`` (its first paragraph: the rest of a THRU range is
    reached by falling through) or a ``GO TO``."""
    line = statement.location.line if getattr(statement, "location", None) else None
    if isinstance(statement, PerformStatement) and statement.target_paragraph:
        targets, kind = [statement.target_paragraph], "PERFORM"
    elif isinstance(statement, GoStatement) and statement.target_paragraphs:
        targets = list(statement.target_paragraphs)
        kind = "GOTO_DEPENDING" if statement.depending_on_variable else "GOTO"
    else:
        return
    for target in targets:
        report.transfer_sites.append(
            TransferSite(paragraph_name, target, kind, enclosing, line)
        )


def _branch_id(paragraph_name: str | None, location: SourceLocation | None) -> str:
    line = location.line if location else "?"
    column = location.column if location else "?"
    return f"{paragraph_name or '?'}@{line}:{column}"


__all__ = [
    "FieldConstraint",
    "CorrelationConstraint",
    "SequenceConstraint",
    "BranchConstraints",
    "ConstraintReport",
    "TransferSite",
    "ConstraintExtractor",
]
