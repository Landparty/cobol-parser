"""
Unused variable detection for COBOL programs.

Analyzes the DATA DIVISION (WORKING-STORAGE, LINKAGE, FILE, and
LOCAL-STORAGE sections) to find declared data items that are never
referenced anywhere in the PROCEDURE DIVISION, and never structurally
depended on by another DATA DIVISION item (REDEFINES, OCCURS DEPENDING ON,
RENAMES). FILLER items are always excluded -- they are never nameable, so
"unused" is meaningless for them.

Single-program scope: like DeadCodeAnalyzer and ProgramFlowAnalyzer, this
analyzer only looks at *ast* itself, not ``ast.contained_programs``. Call
``analyze()`` separately on each contained program if needed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.data_items import CobolDataItem, ConditionNameItem
from ..models.program import CobolProgram, CobolSection
from ..models.statements.base import (
    ArithmeticExpression,
    CobolExpression,
    ConditionalExpression,
    FunctionCall,
    LogicalExpression,
)
from ..models.statements.control import (
    EvaluateStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ..models.statements.data import (
    InspectStatement,
    StringStatement,
    UnstringStatement,
)
from ..models.statements.misc import MergeStatement, SortStatement

# DATA DIVISION section names whose data items are in scope for this
# analysis. Matches the exact names the DATA DIVISION parser assigns (see
# parsers/divisions/data.py) -- the same convention LinkageChecker and
# CRUDMatrixGenerator rely on.
_DATA_SECTION_NAMES = frozenset({"FILE", "WORKING-STORAGE", "LOCAL-STORAGE", "LINKAGE"})

# Words that can appear as, or inside, an operand's text but are never
# themselves a data-name reference: figurative constants, connective/
# qualification keywords the parser leaves joined into an operand string
# instead of splitting out (``WS-A OF WS-GRP``, ``FUNCTION UPPER-CASE(X)``,
# ``LENGTH OF X`` -- confirmed empirically, none of these reach
# ``.operands`` pre-split), and common raw condition-text keywords (SEARCH
# WHEN / EVALUATE TRUE Condition selectors, which carry only joined text --
# see ``_extract_identifiers``).
_NON_IDENTIFIER_WORDS = frozenset(
    {
        # Figurative constants / reserved literals
        "SPACE",
        "SPACES",
        "ZERO",
        "ZEROS",
        "ZEROES",
        "HIGH-VALUE",
        "HIGH-VALUES",
        "LOW-VALUE",
        "LOW-VALUES",
        "QUOTE",
        "QUOTES",
        "NULL",
        "NULLS",
        "ALL",
        # Qualification / special-register / intrinsic-function keywords
        # that stay joined into an operand's raw text
        "OF",
        "IN",
        "FUNCTION",
        "LENGTH",
        "ADDRESS",
        # Condition-text keywords (raw, un-decomposed SEARCH/EVALUATE text)
        "AND",
        "OR",
        "NOT",
        "IS",
        "ARE",
        "NUMERIC",
        "ALPHABETIC",
        "ALPHABETIC-LOWER",
        "ALPHABETIC-UPPER",
        "POSITIVE",
        "NEGATIVE",
        "THRU",
        "THROUGH",
        "TRUE",
        "FALSE",
        "EQUAL",
        "GREATER",
        "LESS",
        "THAN",
        "TO",
    }
)

_QUOTED_TEXT_RE = re.compile(r"'[^']*'|\"[^\"]*\"")
_IDENTIFIER_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*")

# Statement attributes holding a single identifier string that isn't
# already folded into `.operands` by the statement's own setters -- found
# by auditing each statement model's setters for missing
# `_add_unique_operand`/`add_operand` calls.
_STR_ATTR_EXTRAS: dict[type, tuple[str, ...]] = {
    UnstringStatement: ("source_operand", "pointer_variable", "tallying_variable"),
    StringStatement: ("into_target", "pointer_variable"),
    InspectStatement: ("converting_from", "converting_to"),
    SearchStatement: ("table_name", "varying_variable"),
}

# Statement attributes holding a list of dicts with identifier-bearing
# keys, none of which reach `.operands`.
_DICT_LIST_EXTRAS: dict[type, tuple[tuple[str, tuple[str, ...]], ...]] = {
    UnstringStatement: (("into_targets", ("target", "delimiter_var", "count_var")),),
    InspectStatement: (
        ("tallying_clauses", ("counter", "value", "before", "after")),
        ("replacing_clauses", ("from_value", "to_value", "before", "after")),
    ),
    SortStatement: (("keys", ("field",)),),
    MergeStatement: (("keys", ("field",)),),
}


@dataclass
class UnusedVariableItem:
    """A DATA DIVISION item identified as unused (never referenced)."""

    name: str
    level: int
    section: str
    location: SourceLocation
    from_copybook: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "level": self.level,
            "section": self.section,
            "location": self.location.to_dict(),
            "from_copybook": self.from_copybook,
        }


@dataclass
class UnusedVariableReport:
    """Result of an unused-variable analysis."""

    unused_items: list[UnusedVariableItem] = field(default_factory=list)
    total_variables: int = 0
    referenced_variables: int = 0
    skipped_copybook_count: int = 0

    @property
    def unused_count(self) -> int:
        return len(self.unused_items)

    @property
    def has_unused_variables(self) -> bool:
        return len(self.unused_items) > 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "unused_variables": [item.to_dict() for item in self.unused_items],
            "summary": {
                "total_variables": self.total_variables,
                "referenced_variables": self.referenced_variables,
                "unused_variables": self.unused_count,
                "skipped_copybook_variables": self.skipped_copybook_count,
            },
        }


def collect_declared_items(ast: CobolProgram) -> list[CobolDataItem]:
    """Collect every non-FILLER, non-synthetic data item across the
    in-scope DATA DIVISION sections (FILE, WORKING-STORAGE, LOCAL-STORAGE,
    LINKAGE), including nested group children.

    Exposed as a standalone helper so callers (e.g. the CLI) can reuse the
    same declared-name walk to diff an unexpanded parse against an
    expanded one for copybook-provenance detection -- see
    ``UnusedVariableAnalyzer``'s docstring.

    Items named ``ANONYMOUS-<level>-<line>`` are excluded alongside FILLER:
    the DATA DIVISION parser (``data_clauses.py``) generates that name for
    any level-number entry with no real IDENTIFIER token, so it is never a
    name a program could reference -- same rationale as FILLER, and it
    also filters out the clause fragments SCREEN SECTION/REPORT SECTION
    entries get mis-parsed as (see module docstring's "known limitations").
    """
    data_div = ast.data_division
    if data_div is None:
        return []

    items: list[CobolDataItem] = []
    for section in data_div.sections:
        if not isinstance(section, CobolSection):
            continue
        if (section.section_name or "").upper() not in _DATA_SECTION_NAMES:
            continue
        for top_item in section.data_items:
            items.append(top_item)
            items.extend(top_item.get_all_children())

    return [
        item
        for item in items
        if not item.is_filler and not item.name.upper().startswith("ANONYMOUS-")
    ]


def _extract_identifiers(operand: Any) -> set[str]:
    """Extract every candidate data-name reference out of an operand's raw
    text.

    Statement parsers frequently join a whole qualified reference,
    subscript, reference-modification, special register, or intrinsic
    function call into a *single* operand string instead of splitting out
    the underlying data-name(s) -- confirmed empirically:
    ``MoveStatement.source`` for ``MOVE WS-A OF WS-GRP TO ...`` is the
    literal string ``"WS-A OF WS-GRP"``; ``"FUNCTION UPPER-CASE(WS-X)"``
    and ``"LENGTH OF WS-X"`` shapes are the same. Treating an operand as
    one opaque token (the previous approach) meant ``WS-A``/``WS-GRP``/
    ``WS-X`` never matched a declared item's bare name and were falsely
    reported unused -- caught by Copilot review on the PR that introduced
    this analyzer.

    Quoted substrings are stripped first so literal text is never mistaken
    for an identifier (also handles the plain-literal-operand case, e.g.
    ``"'HELLO'"`` reduces to nothing); every remaining letter-led token is
    a candidate, filtered against ``_NON_IDENTIFIER_WORDS`` (figurative
    constants, qualification/special-register/intrinsic-function keywords,
    raw condition-text keywords). A bare numeric literal (``"12345"``)
    never matches at all, since a token must start with a letter.

    Deliberately over-inclusive: a token that isn't really a data-name
    (e.g. an intrinsic function name like ``UPPER-CASE``) only risks
    coincidentally matching an unrelated declared item and marking it
    used -- the analyzer's stated bias throughout is that a missed
    truly-unused variable is safe, a falsely-flagged used one is not.
    """
    if not isinstance(operand, str) or not operand:
        return set()

    stripped = _QUOTED_TEXT_RE.sub(" ", operand)
    tokens: set[str] = set()
    for match in _IDENTIFIER_TOKEN_RE.findall(stripped):
        upper = match.upper()
        if upper in _NON_IDENTIFIER_WORDS:
            continue
        tokens.add(upper)
    return tokens


def _walk_expression_operands(expr: CobolExpression | None) -> set[str]:
    """Collect every leaf identifier referenced by a condition/arithmetic
    expression tree (IF conditions, PERFORM UNTIL guards, COMPUTE
    expressions). Falls back to best-effort raw-text extraction for a node
    shape that couldn't be structurally decomposed, mirroring
    ``program_flow/condition_text.py``'s ``render_condition_text`` fallback
    chain.
    """
    names: set[str] = set()
    if expr is None:
        return names

    if isinstance(expr, LogicalExpression):
        names |= _walk_expression_operands(expr.left_condition)
        names |= _walk_expression_operands(expr.right_condition)
        return names

    if isinstance(expr, FunctionCall):
        for arg in expr.arguments:
            if isinstance(arg, CobolExpression):
                names |= _walk_expression_operands(arg)
            else:
                names |= _extract_identifiers(arg)
        return names

    if isinstance(expr, (ConditionalExpression, ArithmeticExpression)):
        for operand in (expr.left_operand, expr.right_operand):
            if isinstance(operand, CobolExpression):
                names |= _walk_expression_operands(operand)
            else:
                names |= _extract_identifiers(operand)
        return names

    # Unrecognized/opaque expression shape: fall back to the raw text this
    # codebase always keeps around for exactly this situation.
    if expr.operands:
        names |= _extract_identifiers(str(expr.operands[0]))
        return names
    raw = expr.get_metadata("raw_condition")
    if raw:
        names |= _extract_identifiers(str(raw))
    return names


class UnusedVariableAnalyzer:
    """Analyzer for detecting unused (never-referenced) DATA DIVISION items.

    A data item is considered "used" if any of the following holds:

    - Its own name is referenced anywhere in the PROCEDURE DIVISION (as a
      MOVE/DISPLAY/arithmetic/CALL/SET/... operand, an IF/EVALUATE/SEARCH/
      PERFORM UNTIL condition operand, or similar).
    - It is a group item and any of its descendant fields is used.
    - It has a level-88 condition-name child that is itself referenced
      (e.g. ``IF ORDER-VALID`` where ``ORDER-VALID`` is a condition name
      on this item).
    - It is named by another item's REDEFINES, OCCURS ... DEPENDING ON, or
      a level-66 RENAMES, *and* that referencing item is itself used (for
      REDEFINES) or the reference is unconditional (OCCURS DEPENDING ON,
      RENAMES) -- these are real structural dependencies even when the
      name never appears in a procedural statement.

    FILLER items and level-88/level-66 items themselves are never reported
    (see module docstring and ``collect_declared_items``).

    Known limitations (documented rather than silently guessed, matching
    this package's convention -- see ``.okf/analysis.md``):

    - EXEC CICS and EXEC DLI statement arguments are not scanned for
      identifiers (no fixed argument-role shape to key off, same gap
      ``BoundaryInventoryAnalyzer`` documents for these two statement
      types). A field referenced *only* inside one of these may be
      falsely reported unused.
    - SEARCH WHEN and EVALUATE TRUE Condition-type selectors carry only
      raw joined text (never a structural tree -- confirmed against
      ``search_parser.py``/``evaluate_parser.py``); identifier extraction
      there is a best-effort regex, not exact.
    - REDEFINES/OCCURS DEPENDING ON/RENAMES cross-references are resolved
      by name, not by structural item identity -- two same-named items at
      different qualification scopes (legal but rare in COBOL) are not
      distinguished.
    - SCREEN SECTION, REPORT SECTION, and COMMUNICATION SECTION are not
      modeled as distinct constructs by the DATA DIVISION parser (only
      FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE are recognized section
      names -- see ``parsers/divisions/data.py``); their clauses can be
      mis-parsed as nested WORKING-STORAGE data items (e.g. a SCREEN
      SECTION's ``COLUMN 5`` clause showing up as an item literally named
      ``COLUMN``), which then reports as a spurious unused variable.
      Confirmed empirically against ``tests/samples/screen_section_io.cbl``
      and ``report_writer.cbl``. Real unnamed level-number entries
      (``ANONYMOUS-<level>-<line>``) are filtered by
      ``collect_declared_items``, but a mis-parsed *named* clause keyword
      is not distinguishable from a real data item at this layer -- a
      parser-level fix (recognizing and skipping SCREEN/REPORT/
      COMMUNICATION SECTION content) is out of scope here.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.unused_variables import UnusedVariableAnalyzer

        result = parse_cobol(source)
        report = UnusedVariableAnalyzer().analyze(result.ast)
        for item in report.unused_items:
            print(f"Unused: {item.name} at line {item.location.line}")
        ```
    """

    def analyze(
        self,
        ast: CobolProgram,
        *,
        include_copybook_variables: bool = True,
        copybook_item_names: set[str] | None = None,
    ) -> UnusedVariableReport:
        """Analyze *ast* for unused DATA DIVISION items.

        Args:
            ast: The parsed COBOL program AST.
            include_copybook_variables: When False, unused items whose
                name is in *copybook_item_names* are excluded from
                ``report.unused_items`` (counted instead in
                ``report.skipped_copybook_count``). Has no effect when
                *copybook_item_names* is None -- this analyzer has no way
                to know a data item's originating file on its own.
            copybook_item_names: Uppercased names of data items that came
                from an expanded COPY, as determined by the caller (e.g.
                by diffing ``collect_declared_items()`` on an unexpanded
                parse against the expanded one -- see the ``unused-variables``
                CLI subcommand for a worked example). None (default) means
                "no copybook-provenance information available".

        Returns:
            An UnusedVariableReport.
        """
        declared_items = collect_declared_items(ast)
        if not declared_items:
            return UnusedVariableReport()

        referenced = self._collect_referenced_names(ast)
        referenced |= self._collect_data_division_references(ast)

        by_name: dict[str, list[CobolDataItem]] = {}
        for item in declared_items:
            by_name.setdefault(item.name.upper(), []).append(item)

        group_used: dict[int, bool] = {}

        def is_used(item: CobolDataItem) -> bool:
            key = id(item)
            if key in group_used:
                return group_used[key]
            group_used[key] = False  # cycle guard
            result = item.name.upper() in referenced
            if not result:
                for child in item.children:
                    if isinstance(child, ConditionNameItem) and (
                        child.name.upper() in referenced
                    ):
                        result = True
                        break
            if not result:
                for child in item.children:
                    if isinstance(child, CobolDataItem) and is_used(child):
                        result = True
                        break
            group_used[key] = result
            return result

        for item in declared_items:
            is_used(item)

        # REDEFINES: when the redefining item is used, its target shares
        # the same physical storage and counts as used too. Iterated to a
        # fixpoint for REDEFINES chains (A REDEFINES B REDEFINES C).
        redefines_edges = [
            (item, item.redefines.upper()) for item in declared_items if item.redefines
        ]
        changed = True
        while changed:
            changed = False
            for redefining_item, redefined_name in redefines_edges:
                if not group_used.get(id(redefining_item)):
                    continue
                for target in by_name.get(redefined_name, []):
                    if not group_used.get(id(target)):
                        group_used[id(target)] = True
                        changed = True

        report = UnusedVariableReport()
        report.total_variables = len(declared_items)
        report.referenced_variables = sum(
            1 for item in declared_items if group_used.get(id(item))
        )

        for item in declared_items:
            if group_used.get(id(item)):
                continue
            from_copybook = bool(
                copybook_item_names and item.name.upper() in copybook_item_names
            )
            if from_copybook and not include_copybook_variables:
                report.skipped_copybook_count += 1
                continue
            report.unused_items.append(
                UnusedVariableItem(
                    name=item.name,
                    level=item.level,
                    section=self._section_of(item),
                    location=item.location,
                    from_copybook=from_copybook,
                )
            )

        return report

    # ------------------------------------------------------------------
    # PROCEDURE DIVISION reference collection
    # ------------------------------------------------------------------

    def _collect_referenced_names(self, ast: CobolProgram) -> set[str]:
        """Collect every identifier referenced anywhere in the PROCEDURE
        DIVISION: each statement's own ``.operands`` bag plus the
        statement-type-specific fields that don't reach ``.operands`` (see
        module-level ``_STR_ATTR_EXTRAS``/``_DICT_LIST_EXTRAS`` and the
        condition/expression-tree handling below).
        """
        names: set[str] = set()

        for stmt in ast.get_all_statements():
            for operand in stmt.operands:
                names |= _extract_identifiers(operand)

            # Walked by MRO, not exact type, so a (currently hypothetical)
            # subclass of a keyed statement type still gets its extras
            # collected instead of silently losing coverage.
            for klass in type(stmt).__mro__:
                for attr in _STR_ATTR_EXTRAS.get(klass, ()):
                    names |= _extract_identifiers(getattr(stmt, attr, None))

                for attr, keys in _DICT_LIST_EXTRAS.get(klass, ()):
                    for entry in getattr(stmt, attr, None) or []:
                        for key in keys:
                            names |= _extract_identifiers(entry.get(key))

            if isinstance(stmt, IfStatement):
                names |= _walk_expression_operands(stmt.condition)
            elif isinstance(stmt, PerformStatement):
                names |= _walk_expression_operands(stmt.until_condition)
                if stmt.varying_clause:
                    for key in ("variable", "from_value", "by_value"):
                        names |= _extract_identifiers(stmt.varying_clause.get(key))
                for after in stmt.after_clauses:
                    names |= _walk_expression_operands(after.get("until_condition"))
                    for key in ("variable", "from_value", "by_value"):
                        names |= _extract_identifiers(after.get(key))
            elif isinstance(stmt, EvaluateStatement):
                clauses = list(stmt.when_clauses)
                if stmt.default_when is not None:
                    clauses.append(stmt.default_when)
                for clause in clauses:
                    for selector in clause.selectors:
                        names |= self._selector_identifiers(selector)
            elif isinstance(stmt, SearchStatement):
                for search_clause in stmt.when_clauses:
                    condition_text = search_clause.get("condition")
                    if condition_text:
                        names |= _extract_identifiers(str(condition_text))

            expression_tree = getattr(stmt, "expression_tree", None)
            if expression_tree is not None:
                names |= _walk_expression_operands(expression_tree)

            host_variables = getattr(stmt, "host_variables", None)
            if host_variables:
                for v in host_variables:
                    names |= _extract_identifiers(v)
            null_indicators = getattr(stmt, "null_indicators", None)
            if null_indicators:
                for v in null_indicators:
                    names |= _extract_identifiers(v)

        return names

    @staticmethod
    def _selector_identifiers(selector: dict[str, Any]) -> set[str]:
        """Extract identifiers from a single EVALUATE WHEN selector dict
        (see ``WhenClause`` docstring for the selector shape vocabulary).
        """
        names: set[str] = set()
        selector_type = selector.get("type")
        if selector_type == "Identifier":
            names |= _extract_identifiers(selector.get("value"))
        elif selector_type == "Range":
            for key in ("start", "end"):
                names |= _extract_identifiers(selector.get(key))
        elif selector_type == "Condition":
            text = selector.get("text")
            if text:
                names |= _extract_identifiers(str(text))
        return names

    # ------------------------------------------------------------------
    # DATA DIVISION-internal reference collection
    # ------------------------------------------------------------------

    def _collect_data_division_references(self, ast: CobolProgram) -> set[str]:
        """Collect references that live entirely inside the DATA DIVISION:
        OCCURS ... DEPENDING ON variables and level-66 RENAMES targets.
        REDEFINES is handled separately in ``analyze()`` since it needs
        item-level (not just name-level) propagation.
        """
        names: set[str] = set()
        data_div = ast.data_division
        if data_div is None:
            return names

        for section in data_div.sections:
            if not isinstance(section, CobolSection):
                continue
            if (section.section_name or "").upper() not in _DATA_SECTION_NAMES:
                continue

            for item in section.data_items:
                for descendant in [item, *item.get_all_children()]:
                    occurs = descendant.occurs_clause
                    if occurs and occurs.depending_on:
                        names |= _extract_identifiers(occurs.depending_on)

            for child in section.children:
                if getattr(child, "node_type", None) == "RenamesItem":
                    names |= _extract_identifiers(getattr(child, "renames_from", None))
                    names |= _extract_identifiers(
                        getattr(child, "renames_through", None)
                    )

        return names

    @staticmethod
    def _section_of(item: CobolDataItem) -> str:
        """Walk up an item's parents to find its owning DATA DIVISION
        section name.
        """
        node = item.parent
        while node is not None:
            if isinstance(node, CobolSection):
                return node.section_name or "UNKNOWN"
            node = node.parent
        return "UNKNOWN"
