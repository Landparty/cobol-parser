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
# TODO(known limitation): SCREEN SECTION / REPORT SECTION / COMMUNICATION
# SECTION items (screen fields, report groups, CD entries) are entirely
# invisible to this analyzer. Adding those names to this frozenset alone
# would be a no-op: the DATA DIVISION parser's _skip_section
# (parsers/divisions/data.py) discards those sections' content into
# always-empty section nodes, so the parser must first retain their data
# items before this set could expose them.
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


def _names_from_value(value: object) -> set[str]:
    """Identifiers referenced by one operand-position value, dispatching on
    shape: a ``CobolExpression`` is walked structurally, anything else is
    treated as operand text. The one shared form of a dispatch previously
    hand-rolled at three sites (``FunctionCall`` arguments,
    ``ConditionalExpression``/``ArithmeticExpression`` operands, and the
    ``EvaluateStatement`` subjects walk).
    """
    if isinstance(value, CobolExpression):
        return _walk_expression_operands(value)
    return _extract_identifiers(value)


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
            names |= _names_from_value(arg)
        return names

    if isinstance(expr, (ConditionalExpression, ArithmeticExpression)):
        for operand in (expr.left_operand, expr.right_operand):
            names |= _names_from_value(operand)
        return names

    # Unrecognized/opaque expression shape: fall back to the raw text this
    # codebase always keeps around for exactly this situation. Scan every
    # operand, not just the first -- a programmatically built expression may
    # carry several, and dropping operands[1:] falsely reported those names
    # unused.
    if expr.operands:
        for operand in expr.operands:
            names |= _extract_identifiers(str(operand))
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
    - SCREEN SECTION, REPORT SECTION, and COMMUNICATION SECTION headers
      are now recognized by the DATA DIVISION parser and their content
      discarded into distinctly-named, always-empty ``SCREEN``/``REPORT``/
      ``COMMUNICATION`` sections (a separate parser fix, landed after this
      analyzer was first written -- see ``parsers/divisions/data.py``'s
      ``_skip_section``). ``collect_declared_items`` only recognizes
      FILE/WORKING-STORAGE/LOCAL-STORAGE/LINKAGE, so these three sections
      contribute nothing to the declared-item set either way -- no
      analyzer-side change was needed once the parser stopped corrupting
      WORKING-STORAGE with their clause keywords. Their content (screen
      fields, report groups, CD entries) is simply invisible to this
      analyzer, same as any other construct outside its documented scope.

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
        # TODO(known limitation): resolved by uppercased *name* via
        # `by_name` below, not structural item identity -- two same-named
        # items at different qualification scopes (legal but rare in
        # COBOL) are not distinguished. Same caveat applies to the
        # OCCURS-DEPENDING-ON/RENAMES name lookups in
        # `_collect_data_division_references`.
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
                # EVALUATE subject-1 [ALSO subject-2]...: string subjects
                # now reach `.operands` too (evaluate_parser routes them
                # through `add_subject()`), so the base-case operand scan
                # already covers them -- the double-count here is a
                # harmless set union. This walk must stay regardless: a
                # `CobolExpression` subject goes to `add_child()`, never
                # `add_operand()` (see EvaluateStatement.add_subject), so
                # this is the ONLY coverage for expression-shaped subjects.
                for subject in stmt.subjects:
                    names |= _names_from_value(subject)
                clauses = list(stmt.when_clauses)
                if stmt.default_when is not None:
                    clauses.append(stmt.default_when)
                for clause in clauses:
                    for selector in clause.selectors:
                        names |= self._selector_identifiers(selector)
            elif isinstance(stmt, SearchStatement):
                # TODO(known limitation): SEARCH WHEN condition text is raw
                # joined text, not a structural tree -- best-effort regex
                # extraction only, not exact (same gap as EVALUATE TRUE
                # Condition-type selectors in `_selector_identifiers` below).
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

        # EXEC CICS (`ExecCicsStatement.options`: option keyword ->
        # parenthesized argument text, e.g. INTO(WS-BUFFER)) and EXEC
        # IMS/DLI (`ExecImsStatement.arguments`: a positional list, e.g.
        # ["PCB(1)", "SEGMENT(EMPLOYEE)"]) carry their operands as raw
        # joined text rather than a structural tree, the same shape as EXEC
        # SQL's host_variables above -- but unlike EXEC SQL, neither class
        # extends CobolStatement (they extend ASTNode directly -- see
        # parsers/statements/ibm_exec_statements.py), so neither ever
        # appears in ``ast.get_all_statements()`` and the loop above never
        # sees them at all. They're still real AST nodes reachable via
        # ``find_all_by_type``, so swept here separately via duck typing
        # (importing the classes would add an analysis -> parsers layering
        # dependency for no real type-safety benefit, since these fields are
        # untyped raw text either way). Previously a field referenced only
        # inside one of these was falsely reported unused.
        # One shared traversal for both node types (find_all_by_type would
        # walk the whole AST once per type -- two extra full walks on every
        # analysis run, for nodes most programs don't contain at all).
        for node in ast.traverse_depth_first():
            type_name = type(node).__name__
            if type_name == "ExecCicsStatement":
                for v in (getattr(node, "options", None) or {}).values():
                    names |= _extract_identifiers(v)
            elif type_name == "ExecImsStatement":
                for v in getattr(node, "arguments", None) or []:
                    names |= _extract_identifiers(v)

        return names

    @staticmethod
    def _selector_identifiers(selector: dict[str, Any]) -> set[str]:
        """Extract identifiers from a single EVALUATE WHEN selector dict
        (see ``WhenClause`` docstring for the selector shape vocabulary).

        ``Literal`` selectors are scanned too: ``_build_selector`` in
        evaluate_parser.py classifies a bare data-name (or level-88
        condition-name) selector as ``{"type": "Literal"}`` -- it never
        emits ``"Identifier"``, a fact constraints.py's EVALUATE handling
        also relies on -- so skipping ``Literal`` values falsely reported
        a variable referenced only as a WHEN selector unused. The
        ``Identifier`` arm is kept defensively for programmatically built
        selector dicts.

        TODO(known limitation): unlike subject/IF text (re-quoted via
        ``condition_token_text``), selector values arrive with string-
        literal quotes already stripped by the lexer (the unquoted shape
        is pinned by tests/regression/test_evaluate_space_literal_when.py
        and consumed by constraints.py), so ``_extract_identifiers``'
        quote-stripping cannot distinguish literal contents from
        identifiers here. Literal contents that coincidentally match a
        declared name mark it used -- the module's accepted over-inclusive
        direction -- and a truly-unused variable sharing its name with a
        WHEN literal's contents goes unreported.
        """
        names: set[str] = set()
        selector_type = selector.get("type")
        if selector_type in ("Identifier", "Literal"):
            names |= _extract_identifiers(selector.get("value"))
        elif selector_type == "Range":
            for key in ("start", "end"):
                names |= _extract_identifiers(selector.get(key))
        elif selector_type == "Condition":
            # TODO(known limitation): EVALUATE TRUE Condition-type
            # selectors carry only raw joined text, never a structural
            # tree (confirmed against evaluate_parser.py) -- best-effort
            # regex extraction only, not exact (same gap as SEARCH WHEN
            # condition text above), and quote-stripped like every other
            # selector value (see the docstring's TODO).
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
