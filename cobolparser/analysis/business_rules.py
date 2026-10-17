"""
Business rule extraction for a COBOL program.

Turns a program's PROCEDURE DIVISION into a catalogue of the rules it
enforces, in the shape a modernization or documentation effort needs: *under
what condition* does the program *do what* to *which data*.

Three kinds of rule are reported:

- ``decision`` -- every IF, EVALUATE and SEARCH, as a small decision table:
  one :class:`RuleBranch` per arm (THEN / ELSE, each WHEN, WHEN OTHER, a
  SEARCH's AT END), each carrying the condition that selects it and the
  actions it runs.
- ``validation`` -- a decision one of whose arms signals a rejection: it
  moves an error-like literal ("INVALID ...", "... NOT FOUND") or writes an
  item named like an error/reject field, PERFORMs or GOes TO an error/reject/
  abend procedure, CALLs an abend service; or whose condition is a class
  test (``IS NOT NUMERIC``). The reason is kept on the rule
  (``classification``), because this is a heuristic and a reader must be able
  to check it.
- ``calculation`` -- a COMPUTE / ADD / SUBTRACT / MULTIPLY / DIVIDE that is
  *not* already an action of a decision arm (one that is appears there, not
  twice), with its formula normalized to ``target = expression``. Plain
  counters (``ADD 1 TO WS-COUNT``, ``COMPUTE IX = IX + 1``) are not rules.

Plumbing is not business logic. A decision whose condition reads only
*technical* items -- FILE STATUS fields, the EOF flag a READ's AT END sets,
SQLCODE / SQLSTATE / EIBRESP / RETURN-CODE and friends, names like
``WS-EOF`` / ``END-OF-FILE`` -- and a calculation that only writes one, is
marked ``technical``. Technical rules are left out of the report by default
and counted in ``technical_rules_excluded``, so a short catalogue is never
mistaken for a complete one; ``BusinessRuleExtractor(include_technical=True)``
keeps them.

Every rule also carries:

- ``guards`` -- the conditions of the decision arms it is nested in, inside
  its own paragraph (an ELSE arm contributes ``NOT (condition)``), so a
  nested rule can be read on its own;
- ``reached_via`` -- the decision arms elsewhere in the program that PERFORM
  or GO TO the rule's paragraph (``"BR-001 ELSE"``), which is how the
  intra-paragraph guards connect across paragraphs;
- ``inputs`` / ``outputs`` -- the data items read and written by the rule's
  own condition and direct actions, resolved with the same per-statement
  role mapping :class:`~.xref.XrefAnalyzer` uses (nothing re-derived);
- ``condition_names`` -- the level-88 names it tests or sets; the report's
  ``condition_names`` table spells each one out (``POL-AUTO`` means
  ``POL-TYPE = 'A'``), which is usually the most business-readable part of a
  COBOL program;
- ``in_dead_code`` -- whether its paragraph is unreachable according to
  :class:`~.dead_code.DeadCodeAnalyzer`; a rule nobody can run is still
  listed, but flagged.

The report's ``data_lineage`` inverts inputs/outputs: for every data item,
which rules read it and which write it.

Single-program scope, like the other analyzers: only *ast*'s own PROCEDURE
DIVISION is walked, never ``ast.contained_programs``.

Actions are rendered in full by this module rather than through
``program_flow/statement_text.py``, whose summaries are truncated to fit a
flowchart box and leave out GIVING / REMAINDER / ROUNDED.

Conditions are rendered from the AST, not copied from the source listing:
spacing and the spelling of relational operators are normalized (``NOT =``
reads ``<>``). EVALUATE TRUE and SEARCH WHEN conditions are raw text in the
AST; their data names are extracted best-effort (see ``caveats``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .._literals import is_quoted_literal
from ..models.ast_base import SourceLocation
from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolParagraph, CobolProgram
from ..models.statements.arithmetic import (
    AddStatement,
    ArithmeticStatement,
    ComputeStatement,
    DivideStatement,
    MultiplyStatement,
    SubtractStatement,
)
from ..models.statements.base import (
    ArithmeticExpression,
    CobolExpression,
    CobolStatement,
    FunctionCall,
)
from ..models.statements.call import CallStatement
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
    StopStatement,
    WhenClause,
)
from ..models.statements.data import (
    DisplayStatement,
    MoveStatement,
    SetStatement,
    StringStatement,
    UnstringStatement,
)
from ..models.statements.io import IOReadStatement
from ..models.statements.misc import ReturnStatement, SelectStatement
from ._procedures import ProcedureEntry, ProcedureIndex
from .dead_code import DeadCodeAnalyzer
from .program_flow.condition_text import render_condition_text
from .unused_variables import collect_declared_items
from .xref import (
    _SPECIAL_REGISTERS,
    ROLE_CALL_ARGUMENT,
    ROLE_CONDITION,
    ROLE_READ,
    ROLE_SUBSCRIPT,
    ROLE_WRITE,
    XrefAnalyzer,
    _contained_node_ids,
)

# --------------------------------------------------------------------------
# Vocabulary
# --------------------------------------------------------------------------

RULE_DECISION = "decision"
RULE_VALIDATION = "validation"
RULE_CALCULATION = "calculation"

#: Every rule kind this analyzer emits, in report order.
RULE_KINDS: tuple[str, ...] = (RULE_DECISION, RULE_VALIDATION, RULE_CALCULATION)

#: Roles (from the xref vocabulary) that count as the rule *reading* a name.
_INPUT_ROLES = frozenset({ROLE_READ, ROLE_CONDITION, ROLE_SUBSCRIPT, "reference"})
#: Roles that count as the rule *writing* a name. A BY REFERENCE CALL
#: argument may be either, so it is counted as both.
_OUTPUT_ROLES = frozenset({ROLE_WRITE, ROLE_CALL_ARGUMENT})

# Nested statement lists guarded by an exception/end-of-data condition, with
# the label a guard reads as. Same attribute set ``complexity.py`` and
# ``program_flow/scanner.py`` walk (re-derived per module, per the OKF).
_CLAUSE_LABELS: tuple[tuple[str, str], ...] = (
    ("at_end_clause", "AT END"),
    ("not_at_end_clause", "NOT AT END"),
    ("invalid_key_clause", "INVALID KEY"),
    ("not_invalid_key_clause", "NOT INVALID KEY"),
    ("at_eop_clause", "AT END-OF-PAGE"),
    ("not_at_eop_clause", "NOT AT END-OF-PAGE"),
    ("on_size_error", "ON SIZE ERROR"),
    ("not_on_size_error", "NOT ON SIZE ERROR"),
    ("on_overflow", "ON OVERFLOW"),
    ("not_on_overflow", "NOT ON OVERFLOW"),
    ("on_exception", "ON EXCEPTION"),
    ("not_on_exception", "NOT ON EXCEPTION"),
)

#: Names that are plumbing by convention even when nothing else marks them.
_TECHNICAL_NAME_RE = re.compile(
    r"(^|-)(EOF|EOJ|FS|FSTAT|SQLCODE|SQLSTATE)(-|$)"
    r"|END-OF-FILE|FILE-STAT|(^|-)(EIB[A-Z0-9]*|DFH[A-Z0-9]*)(-|$)",
    re.IGNORECASE,
)

#: Words in a MOVEd literal that make the arm an error path.
_ERROR_LITERAL_RE = re.compile(
    r"\b(ERROR|ERR|INVALID|REJECT(ED)?|MISSING|NOT\s+FOUND|EXCEED(S|ED)?|"
    r"FAIL(ED|URE)?|ILLEGAL|OVERLIMIT|OVER\s+LIMIT|UNKNOWN|BAD|NOT\s+NUMERIC|"
    r"REQUIRED|MANDATORY)\b",
    re.IGNORECASE,
)

#: Hyphen-separated words that make a data or procedure name an error one.
_ERROR_NAME_WORDS = frozenset(
    {"ERR", "ERROR", "ERRORS", "INVALID", "REJECT", "REJECTED", "REJ", "ABEND"}
)
#: Words that make a PERFORM / GO TO target an error path.
_ERROR_PROCEDURE_WORDS = _ERROR_NAME_WORDS | {"ABORT", "FAIL", "FAILURE", "CANCEL"}

#: Programs whose CALL is an abend.
_ABEND_PROGRAMS = frozenset({"CEE3ABD", "ILBOABN0", "ABEND", "CKRABEND"})

_CLASS_TEST_RE = re.compile(
    r"\bIS\s+(NOT\s+)?(NUMERIC|ALPHABETIC(-LOWER|-UPPER)?|DBCS|KANJI)\b|"
    r"\bNOT\s+(NUMERIC|ALPHABETIC(-LOWER|-UPPER)?)\b",
    re.IGNORECASE,
)

_FIGURATIVES = frozenset(
    {
        "ZERO",
        "ZEROS",
        "ZEROES",
        "SPACE",
        "SPACES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
    }
)
_NUMERIC_LITERAL_RE = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$")
_THROUGH_PREFIX = "THROUGH:"
#: Special registers that are functions or operators, never data a rule reads.
_NOT_DATA = frozenset({"DFHRESP", "DFHVALUE", "ADDRESS", "LENGTH"})
_SPACED_CALL_RE = re.compile(r"^(FUNCTION )?[A-Za-z0-9-]+ \( .* \)$", re.IGNORECASE)

_WS_RE = re.compile(r"\s+")
# AND / OR as words, not as part of a hyphenated name like ``WS-OR-CODE``.
_BOOL_WORD_RE = re.compile(r"(?<![A-Za-z0-9-])(AND|OR)(?![A-Za-z0-9-])")


def _tidy(text: str) -> str:
    """Collapse whitespace and the ``( X )`` spacing the parser joins with."""
    text = _WS_RE.sub(" ", text).strip()
    text = re.sub(r"\(\s+", "(", text)
    text = re.sub(r"\s+\)", ")", text)
    # ``T-K (IX)`` -> ``T-K(IX)``: a subscript hugs its data name. A keyword
    # before a parenthesis (``NOT (``, ``AND (``) keeps its space.
    return re.sub(
        r"([A-Za-z0-9][A-Za-z0-9-]*) \(",
        lambda m: (
            m.group(0)
            if m.group(1).upper() in {"NOT", "AND", "OR", "OF", "IN"}
            else f"{m.group(1)}("
        ),
        text,
    )


def _words(name: str) -> set[str]:
    return {w for w in name.upper().split("-") if w}


# --------------------------------------------------------------------------
# Report shapes
# --------------------------------------------------------------------------


@dataclass
class RuleAction:
    """One statement an arm (or a calculation) runs."""

    statement: str
    text: str
    location: SourceLocation
    #: The nested rule this action *is*, when it is itself a decision.
    rule: BusinessRule | None = field(default=None, repr=False)
    #: The statement itself (not serialized).
    node: CobolStatement | None = field(default=None, repr=False, compare=False)

    @property
    def rule_id(self) -> str | None:
        """Id of the nested rule, or None (also when that rule was excluded)."""
        return self.rule.rule_id if self.rule is not None else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "statement": self.statement,
            "text": self.text,
            "location": self.location.to_dict(),
            "rule_id": self.rule_id,
        }


@dataclass
class RuleBranch:
    """One arm of a decision: the condition selecting it and what it does."""

    label: str
    condition: str
    actions: list[RuleAction] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "condition": self.condition,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass
class ConditionNameDefinition:
    """What a level-88 condition name means, spelled out."""

    name: str
    data_item: str
    values: list[str]
    condition: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "data_item": self.data_item,
            "values": list(self.values),
            "condition": self.condition,
        }


@dataclass
class BusinessRule:
    """One extracted rule."""

    kind: str
    statement: str
    procedure: str
    section: str | None
    location: SourceLocation
    #: The decision's own condition (IF), subject list (EVALUATE) or table
    #: (SEARCH); for a calculation, its formula.
    condition: str
    branches: list[RuleBranch] = field(default_factory=list)
    formula: str | None = None
    guards: list[str] = field(default_factory=list)
    reached_via: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    condition_names: list[str] = field(default_factory=list)
    technical: bool = False
    classification: list[str] = field(default_factory=list)
    in_dead_code: bool = False
    rule_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "kind": self.kind,
            "statement": self.statement,
            "procedure": self.procedure,
            "section": self.section,
            "location": self.location.to_dict(),
            "condition": self.condition,
            "formula": self.formula,
            "branches": [branch.to_dict() for branch in self.branches],
            "guards": list(self.guards),
            "reached_via": list(self.reached_via),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "condition_names": list(self.condition_names),
            "technical": self.technical,
            "classification": list(self.classification),
            "in_dead_code": self.in_dead_code,
        }

    def to_text(self) -> str:
        """A readable IF/THEN/ELSE-shaped rendering of this one rule."""
        where = f"{self.procedure}"
        if self.section:
            where = f"{self.section} / {where}"
        header = f"{self.rule_id}  {self.kind}  {where}  line {self.location.line}"
        flags = [
            flag
            for flag, on in (
                ("technical", self.technical),
                ("in dead code", self.in_dead_code),
            )
            if on
        ]
        if flags:
            header += f"  [{', '.join(flags)}]"
        lines = [header]
        for guard in self.guards:
            lines.append(f"  given     {guard}")
        if self.reached_via:
            lines.append(f"  reached   via {', '.join(self.reached_via)}")
        if self.formula is not None:
            lines.append(f"  compute   {self.formula}")
        else:
            lines.append(f"  {self.statement:<9} {self.condition}")
            for branch in self.branches:
                label = branch.label
                if branch.condition and label not in ("THEN", "ELSE"):
                    label = f"{label} {branch.condition}"
                lines.append(f"  {label}")
                if not branch.actions:
                    lines.append("            (no action)")
                for action in branch.actions:
                    suffix = f"  -> {action.rule_id}" if action.rule_id else ""
                    lines.append(f"            {action.text}{suffix}")
        if self.inputs:
            lines.append(f"  inputs    {', '.join(self.inputs)}")
        if self.outputs:
            lines.append(f"  outputs   {', '.join(self.outputs)}")
        for reason in self.classification:
            lines.append(f"  because   {reason}")
        return "\n".join(lines)


@dataclass
class BusinessRuleReport:
    """Result of a business rule extraction."""

    program_name: str = ""
    rules: list[BusinessRule] = field(default_factory=list)
    #: Technical rules found but left out (0 when ``include_technical``).
    technical_rules_excluded: int = 0
    #: Every level-88 name any reported rule tests or sets, spelled out.
    condition_names: list[ConditionNameDefinition] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)

    def rules_of_kind(self, kind: str) -> list[BusinessRule]:
        return [rule for rule in self.rules if rule.kind == kind]

    def rule(self, rule_id: str) -> BusinessRule | None:
        for rule in self.rules:
            if rule.rule_id == rule_id:
                return rule
        return None

    @property
    def data_lineage(self) -> dict[str, dict[str, list[str]]]:
        """For every data item a rule touches: which rules read / write it."""
        lineage: dict[str, dict[str, list[str]]] = {}
        for rule in self.rules:
            for name in rule.inputs:
                entry = lineage.setdefault(name, {"read_by": [], "written_by": []})
                entry["read_by"].append(rule.rule_id)
            for name in rule.outputs:
                entry = lineage.setdefault(name, {"read_by": [], "written_by": []})
                entry["written_by"].append(rule.rule_id)
        return dict(sorted(lineage.items()))

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "rules": [rule.to_dict() for rule in self.rules],
            "condition_names": [c.to_dict() for c in self.condition_names],
            "data_lineage": self.data_lineage,
            "caveats": list(self.caveats),
            "summary": {
                "rule_count": len(self.rules),
                **{
                    f"{kind}_count": len(self.rules_of_kind(kind))
                    for kind in RULE_KINDS
                },
                "technical_rules_excluded": self.technical_rules_excluded,
                "rules_in_dead_code": sum(1 for r in self.rules if r.in_dead_code),
            },
        }

    def to_text(self) -> str:
        counts = ", ".join(
            f"{len(self.rules_of_kind(kind))} {kind}" for kind in RULE_KINDS
        )
        title = (
            f"Business rules for {self.program_name or '(unnamed program)'}: "
            f"{len(self.rules)} rule(s) ({counts})"
        )
        if self.technical_rules_excluded:
            title += (
                f"; {self.technical_rules_excluded} technical rule(s) excluded "
                "(file status, EOF, SQLCODE, ...)"
            )
        blocks = [title]
        blocks.extend(rule.to_text() for rule in self.rules)
        if self.condition_names:
            glossary = ["Condition names"]
            width = max(len(c.name) for c in self.condition_names)
            glossary.extend(
                f"  {c.name:<{width}}  {c.condition}" for c in self.condition_names
            )
            blocks.append("\n".join(glossary))
        if self.caveats:
            blocks.append("\n".join(["Caveats", *(f"  - {c}" for c in self.caveats)]))
        return "\n\n".join(blocks) + "\n"


# --------------------------------------------------------------------------
# Analyzer
# --------------------------------------------------------------------------


class BusinessRuleExtractor:
    """Extracts decision, validation and calculation rules from one program.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.business_rules import BusinessRuleExtractor

        report = BusinessRuleExtractor().analyze(parse_cobol(source).ast)
        for rule in report.rules:
            print(rule.rule_id, rule.kind, rule.condition)
            for branch in rule.branches:
                print("   ", branch.label, branch.condition)
        print(report.to_text())
        ```
    """

    def __init__(self, *, include_technical: bool = False) -> None:
        self._include_technical = include_technical
        self._xref = XrefAnalyzer()
        self._declared: set[str] = set()
        self._condition_names: dict[str, tuple[ConditionNameItem, CobolDataItem]] = {}
        self._technical: set[str] = set()
        self._rules: list[BusinessRule] = []
        self._visited: set[int] = set()
        self._raw_conditions = False
        #: (paragraph, rule, branch label) for every PERFORM / GO TO in an arm.
        self._invocations: list[tuple[str, BusinessRule, str]] = []
        #: Every procedure of the PROCEDURE DIVISION, in source order.
        self._procedures: list[ProcedureEntry] = []

    def analyze(self, ast: CobolProgram) -> BusinessRuleReport:
        """Extract the business rules of *ast* (one program unit)."""
        self._declared = set()
        self._condition_names = {}
        self._technical = set()
        self._rules = []
        self._visited = set()
        self._raw_conditions = False
        self._invocations = []
        self._procedures = []

        report = BusinessRuleReport(program_name=ast.program_name or "")
        if ast.procedure_division is None:
            return report
        self._procedures = ProcedureIndex.build(ast.procedure_division).entries

        self._collect_declarations(ast)
        self._collect_technical_items(ast)

        for section_name, para in self._ordered_paragraphs(ast):
            name = (para.paragraph_name or "").upper()
            self._walk(para.statements, name, section_name, guards=[], owner=None)

        dead = {
            item.name.upper() for item in DeadCodeAnalyzer().analyze(ast).dead_items
        }
        for rule in self._rules:
            rule.in_dead_code = rule.procedure in dead or (
                rule.section is not None and rule.section in dead
            )

        kept = [r for r in self._rules if self._include_technical or not r.technical]
        report.technical_rules_excluded = len(self._rules) - len(kept)
        for index, rule in enumerate(kept, start=1):
            rule.rule_id = f"BR-{index:03d}"
        kept_ids = {id(rule) for rule in kept}
        # A reference to an excluded rule would dangle: the action stays, the
        # link goes.
        for rule in kept:
            for branch in rule.branches:
                for action in branch.actions:
                    if action.rule is not None and id(action.rule) not in kept_ids:
                        action.rule = None

        for paragraph, source, label in self._invocations:
            if id(source) not in kept_ids:
                continue
            for rule in kept:
                if paragraph in (rule.procedure, rule.section):
                    via = f"{source.rule_id} {label}"
                    if via not in rule.reached_via:
                        rule.reached_via.append(via)

        report.rules = kept
        used = sorted({name for rule in kept for name in rule.condition_names})
        report.condition_names = [self._define_condition(name) for name in used]
        if self._raw_conditions:
            report.caveats.append(
                "EVALUATE TRUE and SEARCH WHEN conditions are raw text in the AST; "
                "the data names read from them were extracted best-effort"
            )
        report.caveats.append(
            "rule kinds and the technical/business split are heuristics; each "
            "rule's 'classification' says which signal decided it"
        )
        return report

    # ------------------------------------------------------------------
    # Declarations and technical items
    # ------------------------------------------------------------------

    def _collect_declarations(self, ast: CobolProgram) -> None:
        # The names a rule may report: the same declared set xref resolves
        # against, plus level-88 and INDEXED BY names.
        for item in collect_declared_items(ast):
            self._declared.add(item.name.upper())
            for child in item.children:
                if isinstance(child, ConditionNameItem):
                    upper = child.name.upper()
                    self._declared.add(upper)
                    self._condition_names.setdefault(upper, (child, item))
            occurs = item.occurs_clause
            if occurs is not None:
                for index_name in [*occurs.index_names, occurs.indexed_by]:
                    if index_name:
                        self._declared.add(index_name.upper())

    def _collect_technical_items(self, ast: CobolProgram) -> None:
        technical: set[str] = {
            name for name in self._declared if _TECHNICAL_NAME_RE.search(name)
        }
        inner = _contained_node_ids(ast)
        for node in ast.traverse_depth_first():
            if id(node) in inner:
                continue
            if isinstance(node, SelectStatement):
                for status in (node.file_status, node.file_status_vsam):
                    if status:
                        technical.add(status.upper())
            elif isinstance(node, (IOReadStatement, ReturnStatement)):
                # Whatever a READ's AT END writes is its end-of-data flag.
                for stmt in getattr(node, "at_end_clause", None) or []:
                    for name, role in self._statement_names(stmt):
                        if role in _OUTPUT_ROLES:
                            technical.add(name)
        # A technical item's condition names are technical, and a technical
        # condition name's item (and its sibling names) are too.
        for name, (_cond, parent) in self._condition_names.items():
            if name in technical or parent.name.upper() in technical:
                technical.add(parent.name.upper())
        for name, (_cond, parent) in self._condition_names.items():
            if parent.name.upper() in technical:
                technical.add(name)
        self._technical = technical | set(_SPECIAL_REGISTERS)

    # ------------------------------------------------------------------
    # Procedure walk
    # ------------------------------------------------------------------

    @staticmethod
    def _ordered_paragraphs(
        ast: CobolProgram,
    ) -> list[tuple[str | None, CobolParagraph]]:
        proc = ast.procedure_division
        assert proc is not None
        found: list[tuple[str | None, CobolParagraph]] = []
        for section in proc._sections.values():
            section_name = (section.section_name or "").upper() or None
            for para in section.paragraphs:
                found.append((section_name, para))
        for para in proc.paragraphs:
            found.append((None, para))
        return sorted(found, key=lambda pair: pair[1].location.line)

    def _walk(
        self,
        statements: list[CobolStatement],
        procedure: str,
        section: str | None,
        guards: list[str],
        owner: tuple[BusinessRule, str] | None,
    ) -> list[RuleAction]:
        """Visit *statements*; return them as actions of the enclosing arm.

        *owner* is the (rule, branch label) whose arm these statements are,
        or None at paragraph level.
        """
        actions: list[RuleAction] = []
        for stmt in statements:
            if id(stmt) in self._visited:
                continue
            self._visited.add(id(stmt))
            action = RuleAction(
                statement=stmt.statement_type,
                text=self._statement_text(stmt),
                location=stmt.location,
                node=stmt,
            )
            actions.append(action)

            if isinstance(stmt, (IfStatement, EvaluateStatement, SearchStatement)):
                action.rule = self._decision(stmt, procedure, section, guards)
            elif (
                owner is None
                and isinstance(stmt, (ComputeStatement, ArithmeticStatement))
                and not self._is_counter(stmt)
            ):
                self._calculation(stmt, procedure, section, guards)

            if owner is not None:
                for target in self._invoked_procedures(stmt):
                    self._invocations.append((target, owner[0], owner[1]))

            if isinstance(stmt, PerformStatement):
                inline = getattr(stmt, "inline_statements", None) or []
                self._walk(inline, procedure, section, guards, owner)
            for attr, label in _CLAUSE_LABELS:
                clause = getattr(stmt, attr, None)
                if clause and not isinstance(stmt, SearchStatement):
                    self._walk(
                        clause,
                        procedure,
                        section,
                        [*guards, f"{label} ({self._statement_text(stmt)})"],
                        owner,
                    )
            # Anything nested some other way is still walked, unguarded.
            nested = [
                child
                for child in stmt.children
                if isinstance(child, CobolStatement) and id(child) not in self._visited
            ]
            if nested and not isinstance(
                stmt, (IfStatement, EvaluateStatement, SearchStatement)
            ):
                self._walk(nested, procedure, section, guards, owner)
        return actions

    def _decision(
        self,
        stmt: IfStatement | EvaluateStatement | SearchStatement,
        procedure: str,
        section: str | None,
        guards: list[str],
    ) -> BusinessRule:
        rule = BusinessRule(
            kind=RULE_DECISION,
            statement=stmt.statement_type,
            procedure=procedure,
            section=section,
            location=stmt.location,
            condition="",
            guards=list(guards),
        )
        self._rules.append(rule)
        arms: list[tuple[str, str, list[CobolStatement]]] = []

        if isinstance(stmt, IfStatement):
            condition = _tidy(render_condition_text(stmt.condition))
            rule.condition = condition
            arms.append(("THEN", condition, stmt.then_statements))
            if stmt.else_statements:
                arms.append(("ELSE", _negate(condition), stmt.else_statements))
        elif isinstance(stmt, EvaluateStatement):
            subjects = [self._subject_text(s) for s in stmt.subjects]
            rule.condition = " ALSO ".join(subjects)
            seen: list[str] = []
            # Stacked WHENs (``WHEN 'A' WHEN 'B' stmt``) are one arm whose
            # condition is either phrase's, not an empty 'A' arm.
            for group in stmt.when_groups():
                texts = [self._when_text(subjects, clause) for clause in group]
                seen.extend(texts)
                text = " OR ".join(
                    f"({t})" if len(texts) > 1 and _BOOL_WORD_RE.search(t) else t
                    for t in texts
                )
                arms.append(("WHEN", text, group[-1].statements))
            if stmt.default_when is not None:
                other = " AND ".join(_negate(text) for text in seen) or "TRUE"
                arms.append(("WHEN OTHER", other, stmt.default_when.statements))
        else:
            rule.condition = stmt.table_name or ""
            seen = []
            for when in stmt.when_clauses:
                self._raw_conditions = True
                text = _tidy(str(when.get("condition") or ""))
                seen.append(text)
                arms.append(("WHEN", text, list(when.get("statements") or [])))
            if stmt.at_end_clause:
                other = " AND ".join(_negate(text) for text in seen) or "TRUE"
                arms.append(("AT END", other, stmt.at_end_clause))

        own = self._statement_names(stmt)
        for label, condition, body in arms:
            branch = RuleBranch(label=label, condition=condition)
            rule.branches.append(branch)
            # THEN / ELSE / WHEN OTHER name their arm; a WHEN needs its
            # condition to say which one.
            arm = f"{label} {condition}" if label in ("WHEN",) else label
            branch.actions = self._walk(
                body,
                procedure,
                section,
                [*guards, condition] if condition else list(guards),
                (rule, arm),
            )

        inputs = {name for name, role in own if role in _INPUT_ROLES}
        outputs = {name for name, role in own if role in _OUTPUT_ROLES}
        tested = set(inputs)
        for branch in rule.branches:
            for action in branch.actions:
                if action.rule is not None:
                    continue
                for name, role in self._action_names(action):
                    if role in _INPUT_ROLES:
                        inputs.add(name)
                    if role in _OUTPUT_ROLES:
                        outputs.add(name)
        self._finish(rule, inputs, outputs)

        if (
            tested
            and tested <= self._technical
            and not isinstance(stmt, SearchStatement)
        ):
            rule.technical = True
            rule.classification.append(
                "technical: its condition reads only technical items ("
                + ", ".join(sorted(tested))
                + ")"
            )
        reasons = self._validation_reasons(rule, stmt)
        if reasons:
            rule.kind = RULE_VALIDATION
            rule.classification.extend(reasons)
        elif not rule.technical:
            rule.classification.append(
                "decision: branches on business data"
                if tested
                else "decision: branches on a condition naming no data item"
            )
        return rule

    def _calculation(
        self,
        stmt: CobolStatement,
        procedure: str,
        section: str | None,
        guards: list[str],
    ) -> None:
        formula = self._formula(stmt)
        rule = BusinessRule(
            kind=RULE_CALCULATION,
            statement=stmt.statement_type,
            procedure=procedure,
            section=section,
            location=stmt.location,
            condition=formula,
            formula=formula,
            guards=list(guards),
        )
        self._rules.append(rule)
        names = self._statement_names(stmt)
        outputs = {name for name, role in names if role in _OUTPUT_ROLES}
        inputs = {name for name, role in names if role in _INPUT_ROLES}
        self._finish(rule, inputs, outputs)
        if outputs and outputs <= self._technical:
            rule.technical = True
            rule.classification.append(
                "technical: it only writes technical items ("
                + ", ".join(sorted(outputs))
                + ")"
            )
        else:
            rule.classification.append("calculation: arithmetic on business data")

    def _finish(self, rule: BusinessRule, inputs: set[str], outputs: set[str]) -> None:
        """Fill inputs/outputs, adding each condition name's own data item."""
        for names in (inputs, outputs):
            for name in list(names):
                entry = self._condition_names.get(name)
                if entry is not None:
                    names.add(entry[1].name.upper())
        rule.inputs = sorted(inputs)
        rule.outputs = sorted(outputs)
        rule.condition_names = sorted(
            name for name in inputs | outputs if name in self._condition_names
        )

    # ------------------------------------------------------------------
    # Classification
    # ------------------------------------------------------------------

    def _validation_reasons(
        self,
        rule: BusinessRule,
        stmt: IfStatement | EvaluateStatement | SearchStatement,
    ) -> list[str]:
        reasons: list[str] = []
        if _CLASS_TEST_RE.search(rule.condition) or any(
            _CLASS_TEST_RE.search(branch.condition) for branch in rule.branches
        ):
            reasons.append("validation: its condition is a class test")
        for branch in rule.branches:
            for action in branch.actions:
                reason = self._error_signal(action, branch.label)
                if reason and reason not in reasons:
                    reasons.append(reason)
        return reasons

    def _error_signal(self, action: RuleAction, label: str) -> str | None:
        stmt = action.node
        if stmt is None:
            return None
        if isinstance(stmt, MoveStatement):
            source = stmt.source or ""
            if source[:1] in ("'", '"') and _ERROR_LITERAL_RE.search(source):
                return f"validation: {label} moves an error message ({source})"
            for target in stmt.targets:
                if _words(target.split("(")[0]) & _ERROR_NAME_WORDS:
                    return f"validation: {label} writes {target.upper()}"
        if isinstance(stmt, SetStatement):
            for target in stmt.targets:
                if _words(target.split("(")[0]) & _ERROR_NAME_WORDS:
                    return f"validation: {label} sets {target.upper()}"
        if isinstance(stmt, (PerformStatement, GoStatement)):
            procedure = self._invoked_procedure(stmt)
            if procedure and _words(procedure) & _ERROR_PROCEDURE_WORDS:
                verb = "performs" if isinstance(stmt, PerformStatement) else "goes to"
                return f"validation: {label} {verb} {procedure}"
        if isinstance(stmt, CallStatement):
            program = (stmt.called_program or "").strip("'\"").upper()
            if program in _ABEND_PROGRAMS:
                return f"validation: {label} calls {program}"
        if isinstance(stmt, DisplayStatement):
            for item in stmt.display_items:
                if item[:1] in ("'", '"') and _ERROR_LITERAL_RE.search(item):
                    return f"validation: {label} displays an error ({item})"
        return None

    @staticmethod
    def _is_counter(stmt: CobolStatement) -> bool:
        """``ADD 1 TO X`` / ``SUBTRACT 1 FROM X`` / ``COMPUTE X = X + 1``."""
        if isinstance(stmt, (AddStatement, SubtractStatement)):
            sources = stmt.source_operands or []
            return (
                not stmt.givings
                and len(stmt.targets) == 1
                and len(sources) == 1
                and re.fullmatch(r"[+]?\d+", sources[0].strip()) is not None
            )
        if isinstance(stmt, ComputeStatement) and len(stmt.targets) == 1:
            target = re.escape(stmt.targets[0].strip())
            expression = _tidy(_expression_text(stmt.expression))
            return (
                re.fullmatch(rf"{target} [+-] \d+", expression, re.IGNORECASE)
                is not None
            )
        return False

    # ------------------------------------------------------------------
    # Names
    # ------------------------------------------------------------------

    def _statement_names(self, stmt: CobolStatement) -> list[tuple[str, str]]:
        """(declared name, role) pairs one statement itself names."""
        pairs: list[tuple[str, str]] = []
        recorded: set[str] = set()
        for value, role, _exact in self._xref._role_assignments(stmt):
            for name, resolved_role, _ in self._xref._names_for(value, role):
                upper = name.upper()
                recorded.add(upper)
                if upper in self._declared or (
                    upper in _SPECIAL_REGISTERS and upper not in _NOT_DATA
                ):
                    pairs.append((upper, resolved_role))
        for name in self._xref._residual_names(stmt):
            upper = name.upper()
            if upper not in recorded and upper in self._declared:
                pairs.append((upper, "reference"))
        return pairs

    def _action_names(self, action: RuleAction) -> list[tuple[str, str]]:
        return self._statement_names(action.node) if action.node is not None else []

    @staticmethod
    def _invoked_procedure(stmt: CobolStatement) -> str | None:
        if isinstance(stmt, PerformStatement) and stmt.target_paragraph:
            return stmt.target_paragraph.upper()
        if isinstance(stmt, GoStatement) and stmt.target_paragraph:
            return stmt.target_paragraph.upper()
        return None

    def _invoked_procedures(self, stmt: CobolStatement) -> list[str]:
        """Every procedure *stmt* transfers control into.

        A ``PERFORM A THRU C`` runs every procedure from A through C in
        source order, and a ``GO TO A B DEPENDING ON N`` may land on any of
        its targets.
        """
        if isinstance(stmt, GoStatement):
            names = stmt.target_paragraphs or (
                [stmt.target_paragraph] if stmt.target_paragraph else []
            )
            return list(dict.fromkeys(name.upper() for name in names))
        target = self._invoked_procedure(stmt)
        if target is None:
            return []
        if isinstance(stmt, PerformStatement) and stmt.thru_paragraph:
            return self._thru_range(target, stmt.thru_paragraph.upper())
        return [target]

    def _thru_range(self, start: str, end: str) -> list[str]:
        """The procedures a ``start THRU end`` range spans, in source order.

        Like ``ProgramFlowAnalyzer``'s ``range_members``, but on the bare
        names this extractor matches rules by. A section header crossed on
        the way to a paragraph *inside* that section is left out: only that
        section's paragraphs up to *end* run, not all of it. Unknown or
        out-of-order endpoints give just the two endpoints.
        """
        if start == end:
            return [start]
        names = [entry.name for entry in self._procedures]
        if start not in names or end not in names:
            return [start, end]
        i = names.index(start)
        j = names.index(end)
        if j < i:
            return [start, end]
        end_entry = self._procedures[j]
        members: list[str] = []
        for entry in self._procedures[i : j + 1]:
            if (
                entry.procedure_type == "SECTION"
                and entry is not end_entry
                and entry.name == end_entry.section
            ):
                continue
            if entry.name not in members:
                members.append(entry.name)
        return members

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _define_condition(self, name: str) -> ConditionNameDefinition:
        cond, parent = self._condition_names[name]
        values = _condition_values(cond.values, parent)
        item = parent.name.upper()
        parts = []
        for value in values:
            if " THRU " in value:
                low, high = value.split(" THRU ", 1)
                parts.append(f"{item} >= {low} AND {item} <= {high}")
            else:
                parts.append(f"{item} = {value}")
        condition = " OR ".join(parts) if parts else item
        return ConditionNameDefinition(
            name=name, data_item=item, values=values, condition=condition
        )

    def _subject_text(self, subject: Any) -> str:
        if isinstance(subject, CobolExpression):
            return _tidy(render_condition_text(subject))
        return _tidy(str(subject))

    def _when_text(self, subjects: list[str], clause: WhenClause) -> str:
        parts: list[str] = []
        for index, selector in enumerate(clause.selectors):
            subject = subjects[index] if index < len(subjects) else "TRUE"
            text = self._selector_text(subject, selector)
            if text:
                parts.append(text)
        if not parts:
            return "TRUE"
        if len(parts) == 1:
            return parts[0]
        return " AND ".join(
            f"({part})" if _BOOL_WORD_RE.search(part) else part for part in parts
        )

    def _selector_text(self, subject: str, selector: Any) -> str:
        if not isinstance(selector, dict):
            return _tidy(str(selector))
        kind = selector.get("type")
        subject_upper = subject.upper()
        if kind == "Any":
            return ""
        if kind == "Condition":
            self._raw_conditions = True
            text = _tidy(str(selector.get("text") or ""))
            if subject_upper == "TRUE":
                return text
            if subject_upper == "FALSE":
                return _negate(text)
            # ``WHEN NOT 0 THRU 17``: the parser supplies the bounds, so
            # render the negated range rather than the raw ``THRU`` text.
            if (
                selector.get("negated")
                and selector.get("start") is not None
                and selector.get("end") is not None
            ):
                low = self._literal(selector.get("start"), False)
                high = self._literal(selector.get("end"), False)
                return f"NOT ({subject} >= {low} AND {subject} <= {high})"
            # ``WHEN NOT 6`` against a data subject.
            if text.upper().startswith("NOT "):
                return f"{subject} <> {text[4:].strip()}"
            return f"{subject} = {text}"
        if kind == "Range":
            low = self._literal(selector.get("start"), False)
            high = self._literal(selector.get("end"), False)
            return f"{subject} >= {low} AND {subject} <= {high}"
        value = self._literal(
            selector.get("value"),
            bool(selector.get("identifier")) or kind == "Identifier",
            quoted=bool(selector.get("quoted")),
        )
        if subject_upper == "TRUE":
            return value
        if subject_upper == "FALSE":
            return _negate(value)
        return f"{subject} = {value}"

    @staticmethod
    def _literal(value: Any, identifier: bool, quoted: bool = False) -> str:
        """An EVALUATE selector value; selector literals arrive unquoted.

        ``quoted`` is the parser's word that the value was a string literal:
        ``WHEN 'SPACES'`` must not render as the figurative ``SPACES``.
        """
        text = str(value or "")
        if quoted:
            # A blank literal reaches us already re-quoted by the parser.
            if len(text) >= 2 and text[0] in "'\"" and text[-1] == text[0]:
                if not text[1:-1].strip():
                    return text
            return "'" + text.replace("'", "''") + "'"
        text = text.strip()
        if identifier or not text:
            return text
        if _NUMERIC_LITERAL_RE.match(text) or text.upper() in _FIGURATIVES:
            return text
        if text[:1] in ("'", '"') or is_quoted_literal(text):
            # Already source spelling, a typed literal (``X'00'``) included.
            return text
        # The parser joins a multi-token selector with spaces
        # (``DFHRESP ( NORMAL )``); a quoted literal it unquoted never has
        # that shape, so this one is an expression, not text.
        if _SPACED_CALL_RE.match(text):
            return _tidy(text)
        return "'" + text.replace("'", "''") + "'"

    def _statement_text(self, stmt: CobolStatement) -> str:
        return _tidy(self._raw_statement_text(stmt))

    def _raw_statement_text(self, stmt: CobolStatement) -> str:
        if isinstance(stmt, MoveStatement):
            corr = "CORRESPONDING " if stmt.is_corresponding else ""
            return f"MOVE {corr}{stmt.source or ''} TO {', '.join(stmt.targets)}"
        if isinstance(stmt, ComputeStatement):
            return f"COMPUTE {self._formula(stmt)}"
        if isinstance(stmt, ArithmeticStatement):
            return _arithmetic_cobol_text(stmt)
        if isinstance(stmt, SetStatement):
            return _set_text(stmt)
        if isinstance(stmt, IfStatement):
            return f"IF {render_condition_text(stmt.condition)}"
        if isinstance(stmt, EvaluateStatement):
            subjects = " ALSO ".join(self._subject_text(s) for s in stmt.subjects)
            return f"EVALUATE {subjects}"
        if isinstance(stmt, SearchStatement):
            return f"SEARCH {stmt.table_name or ''}"
        if isinstance(stmt, PerformStatement):
            return _perform_text(stmt)
        if isinstance(stmt, GoStatement):
            targets = " ".join(stmt.target_paragraphs) or (stmt.target_paragraph or "")
            text = f"GO TO {targets}"
            if stmt.depending_on_variable:
                text += f" DEPENDING ON {stmt.depending_on_variable}"
            return text
        if isinstance(stmt, CallStatement):
            program = stmt.called_program or ""
            if not stmt.is_dynamic and program[:1] not in ("'", '"'):
                program = f"'{program}'"
            text = f"CALL {program}"
            names = [p.name for p in stmt.using_parameters if p.name]
            if names:
                text += f" USING {', '.join(names)}"
            if stmt.returning_parameter:
                text += f" RETURNING {stmt.returning_parameter}"
            return text
        if isinstance(stmt, DisplayStatement):
            return f"DISPLAY {' '.join(stmt.display_items)}"
        if isinstance(stmt, StopStatement):
            stop_type = getattr(stmt, "stop_type", None) or ""
            return f"STOP {stop_type}"
        if isinstance(stmt, StringStatement):
            # A literal source arrives quoted, as DISPLAY's items do.
            return f"STRING {' '.join(stmt.operands)} INTO {stmt.into_target or ''}"
        if isinstance(stmt, UnstringStatement):
            receivers = [str(t.get("target", "")) for t in stmt.into_targets]
            return f"UNSTRING {stmt.source_operand or ''} INTO {' '.join(receivers)}"
        sql_text = getattr(stmt, "sql_text", None)
        if isinstance(sql_text, str) and sql_text.strip():
            return f"EXEC SQL {sql_text}"
        if stmt.cics_command:
            options = getattr(stmt, "options", None) or {}
            rendered = " ".join(
                f"{key}({value})" if value not in (None, "", True) else str(key)
                for key, value in options.items()
            )
            return f"EXEC CICS {stmt.cics_command} {rendered}"
        if stmt.ims_command:
            return f"EXEC DLI {stmt.ims_command}"
        operands = " ".join(str(op) for op in stmt.operands)
        return f"{stmt.statement_type.replace('_', ' ')} {operands}"

    def _formula(self, stmt: CobolStatement) -> str:
        if isinstance(stmt, ComputeStatement):
            rounded = " ROUNDED" if stmt.rounded else ""
            expression = _expression_text(stmt.expression)
            if not expression and stmt.expression_tree is not None:
                expression = _expression_text(stmt.expression_tree)
            return _tidy(f"{', '.join(stmt.targets)}{rounded} = {expression}")
        if isinstance(stmt, ArithmeticStatement):
            return _tidy(_arithmetic_formula(stmt))
        return self._statement_text(stmt)


# --------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------


def _negate(condition: str) -> str:
    """``NOT (condition)``, unwrapping a condition that is already negated."""
    match = re.fullmatch(r"NOT \((.*)\)", condition)
    if match and _balanced(match.group(1)):
        return match.group(1)
    return f"NOT ({condition})"


def _balanced(text: str) -> bool:
    depth = 0
    for char in text:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _expression_text(expression: Any) -> str:
    """An arithmetic expression, from its raw string or its tree."""
    if expression is None:
        return ""
    if isinstance(expression, str):
        return expression
    if isinstance(expression, ArithmeticExpression):
        left = _operand_text(expression.left_operand)
        right = _operand_text(expression.right_operand)
        if expression.right_operand is None:
            return f"{expression.operator}{left}"
        return f"{left} {expression.operator} {right}"
    if isinstance(expression, FunctionCall):
        args = ", ".join(_operand_text(arg) for arg in expression.arguments)
        return f"FUNCTION {expression.function_name}({args})"
    if isinstance(expression, CobolExpression):
        return render_condition_text(expression)
    return str(expression)


def _operand_text(operand: Any) -> str:
    if isinstance(operand, ArithmeticExpression):
        return f"({_expression_text(operand)})"
    return _expression_text(operand)


def _arithmetic_sources(stmt: ArithmeticStatement) -> list[str]:
    """The operands before TO / FROM / BY / INTO / GIVING, in source order."""
    if stmt.source_operands is not None:
        return list(stmt.source_operands)
    results = {name.upper() for name in stmt.givings}
    if isinstance(stmt, DivideStatement) and stmt.remainder:
        results.add(stmt.remainder.upper())
    return [op for op in stmt.operands if op.upper() not in results]


def _arithmetic_formula(stmt: ArithmeticStatement) -> str:
    """``target = expression`` for an ADD / SUBTRACT / MULTIPLY / DIVIDE."""
    rounded = " ROUNDED" if stmt.rounded else ""
    sources = _arithmetic_sources(stmt)
    if stmt.is_corresponding or not sources:
        return _arithmetic_cobol_text(stmt)
    givings = ", ".join(stmt.givings)
    if isinstance(stmt, AddStatement):
        if stmt.givings:
            terms = sources + [t for t in stmt.targets if t not in sources]
            return f"{givings}{rounded} = {' + '.join(terms)}"
        return "; ".join(
            f"{t}{rounded} = {' + '.join([t, *sources])}" for t in stmt.targets
        )
    if isinstance(stmt, SubtractStatement):
        subtrahend = " - ".join(sources)
        if stmt.givings:
            minuend = stmt.targets[0] if stmt.targets else "?"
            return f"{givings}{rounded} = {minuend} - {subtrahend}"
        return "; ".join(f"{t}{rounded} = {t} - {subtrahend}" for t in stmt.targets)
    if isinstance(stmt, MultiplyStatement):
        if stmt.givings and len(sources) == 2:
            return f"{givings}{rounded} = {sources[0]} * {sources[1]}"
        if not stmt.givings and stmt.targets:
            first = sources[0]
            return "; ".join(
                f"{t}{rounded} = {t} * {first}" for t in stmt.targets if t != first
            ) or _arithmetic_cobol_text(stmt)
    if isinstance(stmt, DivideStatement):
        into = (stmt.division_mode or "").upper() == "INTO"
        remainder = f"; REMAINDER {stmt.remainder}" if stmt.remainder else ""
        if stmt.givings and len(sources) == 2:
            dividend, divisor = (sources[1], sources[0]) if into else sources
            return f"{givings}{rounded} = {dividend} / {divisor}{remainder}"
        if not stmt.givings and into and stmt.targets:
            first = sources[0]
            return "; ".join(
                f"{t}{rounded} = {t} / {first}" for t in stmt.targets if t != first
            ) or _arithmetic_cobol_text(stmt)
    return _arithmetic_cobol_text(stmt)


def _arithmetic_cobol_text(stmt: ArithmeticStatement) -> str:
    """The statement as COBOL: ``ADD A TO B``, ``DIVIDE A INTO B GIVING C``."""
    sources = _arithmetic_sources(stmt)
    corr = "CORRESPONDING " if stmt.is_corresponding else ""
    verb = stmt.statement_type
    joiner = {
        "ADD": "TO",
        "SUBTRACT": "FROM",
        "MULTIPLY": "BY",
        "DIVIDE": (
            stmt.division_mode or "INTO"
            if isinstance(stmt, DivideStatement)
            else "INTO"
        ),
    }.get(verb, "")
    if isinstance(stmt, (MultiplyStatement, DivideStatement)):
        head, rest = sources[:1], sources[1:]
    else:
        head = [s for s in sources if s not in stmt.targets]
        rest = list(stmt.targets)
    text = f"{verb} {corr}{' '.join(head)}"
    if rest:
        text += f" {joiner} {' '.join(rest)}"
    if stmt.givings:
        text += f" GIVING {' '.join(stmt.givings)}"
    if stmt.rounded:
        text += " ROUNDED"
    if isinstance(stmt, DivideStatement) and stmt.remainder:
        text += f" REMAINDER {stmt.remainder}"
    return text


def _set_text(stmt: SetStatement) -> str:
    targets = ", ".join(stmt.targets)
    set_type = (stmt.set_type or "").upper()
    if set_type in ("TRUE", "FALSE"):
        return f"SET {targets} TO {set_type}"
    if set_type == "UP_BY":
        return f"SET {targets} UP BY {stmt.value or ''}"
    if set_type == "DOWN_BY":
        return f"SET {targets} DOWN BY {stmt.value or ''}"
    return f"SET {targets} TO {stmt.value or ''}"


def _perform_text(stmt: PerformStatement) -> str:
    text = "PERFORM"
    if stmt.target_paragraph:
        text += f" {stmt.target_paragraph}"
        if stmt.thru_paragraph:
            text += f" THRU {stmt.thru_paragraph}"
    perform_type = (stmt.perform_type or "").upper()
    if perform_type == "TIMES" and stmt.times_count is not None:
        text += f" {stmt.times_count} TIMES"
    elif perform_type == "VARYING" and stmt.varying_clause:
        clause = stmt.varying_clause
        text += (
            f" VARYING {clause.get('variable', '')} FROM "
            f"{clause.get('from_value', '')} BY {clause.get('by_value', '')}"
        )
    if perform_type in ("UNTIL", "VARYING") and stmt.until_condition is not None:
        text += f" UNTIL {render_condition_text(stmt.until_condition)}"
    return text


def _condition_values(raw_values: list[str], parent: CobolDataItem) -> list[str]:
    """A level-88's VALUE list as COBOL literals, THRU ranges kept as ranges.

    The parser stores ``VALUE 'A' THRU 'F'`` as ``["A", "THROUGH:F"]`` with
    string quotes stripped, so whether to quote is decided from the parent's
    PICTURE: a numeric item's values are numbers, anything else is text.
    """
    picture = getattr(getattr(parent, "picture_clause", None), "pattern", "") or ""
    numeric = bool(picture) and not re.search(r"[XAN]", picture, re.IGNORECASE)
    usage = (getattr(parent, "usage", "") or "").upper()
    if usage.startswith("COMP") or usage in ("BINARY", "PACKED-DECIMAL"):
        numeric = True

    def literal(value: str) -> str:
        text = value.strip()
        if (
            numeric
            or text.upper() in _FIGURATIVES
            or text[:1] in ("'", '"')
            or re.match(r"^[XNGZ]['\"]", text, re.IGNORECASE)
            or text.upper().startswith("ALL ")
        ):
            return text
        return "'" + text.replace("'", "''") + "'"

    values: list[str] = []
    for raw in raw_values:
        if raw.upper().startswith(_THROUGH_PREFIX) and values:
            values[-1] = f"{values[-1]} THRU {literal(raw[len(_THROUGH_PREFIX):])}"
        else:
            values.append(literal(raw))
    return values
