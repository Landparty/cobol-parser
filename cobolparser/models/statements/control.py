"""
Control flow statement AST nodes (IF, EVALUATE, PERFORM, GO TO, STOP, SEARCH).
"""

from typing import Any, Union

from ..ast_base import ASTNode, SourceLocation
from .base import CobolExpression, CobolStatement


class WhenClause(ASTNode):
    """Represents a WHEN branch within an EVALUATE statement.

    A WhenClause contains one or more selectors that define matching conditions
    for an EVALUATE statement's subjects. Selectors are positionally aligned
    with subjects when using the ALSO keyword.

    **Attributes:**
        selectors: List of selector dictionaries. Each selector is a dict with
            keys depending on type:
            - type: Selector type ("Literal", "Identifier", "Any", "Range", "Condition")
            - value: For Literal/Identifier - the text value
            - start, end: For Range - inclusive bounds
            - operator: For Condition - "AND" or "OR"
            - text: For Condition - full condition text
        statements: List of CobolStatement nodes to execute when selectors match.

    **Selector Examples:**
        # Literal selector
        {"type": "Literal", "value": "1"}

        # Identifier selector
        {"type": "Identifier", "value": "WS-FLAG"}

        # ANY selector
        {"type": "Any"}

        # Range selector (THRU/THROUGH)
        {"type": "Range", "start": "1", "end": "10"}

        # Condition selector (EVALUATE TRUE with AND/OR)
        {"type": "Condition", "operator": "AND", "text": "WS-A = 1 AND WS-B = 2"}

    **Multi-Subject Alignment:**
        When EVALUATE has multiple subjects, selectors align positionally:
        EVALUATE WS-GRADE ALSO WS-STATUS
            WHEN 1 ALSO 'A'    -> selectors[0] matches subjects[0], selectors[1] matches subjects[1]
                ...

    **Serialization (to_dict):**
        {
            "node_type": "WhenClause",
            "selectors": [
                {"type": "Literal", "value": "1"}
            ],
            "statements": [
                {"statement_type": "DISPLAY", ...}
            ],
            "location": {"line": 10, "column": 12}
        }
    """

    def __init__(self, selectors: list, location: SourceLocation):
        super().__init__("WhenClause", location)
        self.selectors: list = selectors  # List of selector dicts
        # Per selector, the structural tree of a Condition selector (``WHEN
        # A > 1 AND B = 'X'`` in an EVALUATE TRUE) or None: the same
        # expression IF builds, which `selectors` holds only as text.
        self.condition_trees: list[CobolExpression | None] = []
        self.statements: list[CobolStatement] = []
        # True when the source has no imperative statement between this WHEN
        # and the next (non-OTHER) WHEN: the two are one stacked arm. Set by
        # the parser from the tokens, not inferred from an empty
        # `statements` -- a body that was in the source but never reached
        # the AST (an unexpanded COPY, a statement dropped by error
        # recovery) is not a stack. See `EvaluateStatement.when_groups`.
        self.stacked: bool = False

    def add_statement(self, statement: "CobolStatement") -> None:
        self.statements.append(statement)
        self.add_child(statement)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "selectors": self.selectors,
            "statements": [s.to_dict() for s in self.statements],
            "location": self.location.to_dict(),
            "metadata": self._metadata or {},
        }


class EvaluateStatement(CobolStatement):
    """AST node for EVALUATE statements.

    The EVALUATE statement provides multi-way conditional branching, similar to
    a CASE or SWITCH statement in other languages.

    **Fixed-Format COBOL Syntax:**
        EVALUATE {subject-1 [ALSO subject-2]...}
            WHEN selector-1 [ALSO selector-2]...
                imperative-statement...
            [WHEN OTHER
                imperative-statement...]
        END-EVALUATE.

    **Attributes:**
        subjects: List of expressions to evaluate. Can be a single subject or
            multiple subjects joined with ALSO. Special subjects include TRUE
            and FALSE for condition-based branching.
        when_clauses: List of WhenClause nodes representing each WHEN branch.
        default_when: Optional WhenClause for WHEN OTHER branch.

    **Selector Types:**
        - Literal: String or numeric constant (WHEN 1, WHEN 'A')
        - Identifier: Data name reference (WHEN WS-FLAG)
        - Any: Wildcard match (WHEN ANY)
        - Range: Inclusive range (WHEN 1 THRU 10)
        - Condition: AND/OR expression for EVALUATE TRUE (WHEN A = 1 AND B = 2)

    **Example:**
        EVALUATE WS-GRADE ALSO WS-STATUS
            WHEN 1 ALSO 'A'
                DISPLAY 'ALPHA'
            WHEN ANY ALSO 'Z'
                DISPLAY 'Z-ANY'
            WHEN OTHER
                DISPLAY 'DEFAULT'
        END-EVALUATE.

    **Serialization (to_dict):**
        {
            "node_type": "Statement",
            "statement_type": "EVALUATE",
            "subjects": [{"expression": "WS-GRADE", "type": "Identifier"}],
            "when_clauses": [
                {
                    "selectors": [{"type": "Literal", "value": "1"}],
                    "statements": [...],
                    "location": {...}
                }
            ],
            "default_when": {...},
            "location": {...}
        }

    **Diagnostics (errors caught during parsing):**
        - Missing WHEN clause: "EVALUATE statement requires at least one WHEN clause"
        - Missing END-EVALUATE: "EVALUATE statement requires END-EVALUATE terminator"
        - Selector/subject mismatch: "WHEN clause has X selector(s) but EVALUATE has Y subject(s)"
        - Invalid THRU: "THRU/THROUGH requires both start and end values"
        - WHEN OTHER placement: "Conditional WHEN after WHEN OTHER is not allowed"

    **Coverage:** 51 tests (20 positive variants + 16 negative variants + 15 coverage gate)

    See Also:
        WhenClause: Individual WHEN branch representation
    """

    def __init__(self, location: SourceLocation):
        super().__init__("EVALUATE", location)
        self.subjects: list[str | CobolExpression] = []
        self.when_clauses: list[WhenClause] = []
        self.default_when: WhenClause | None = None

    def add_subject(self, subject: Union[str, "CobolExpression"]) -> None:
        self.subjects.append(subject)
        if isinstance(subject, CobolExpression):
            self.add_child(subject)
        else:
            self.add_operand(subject)

    def add_when_clause(self, clause: WhenClause) -> None:
        self.when_clauses.append(clause)
        self.add_child(clause)

    def set_default_when(self, clause: WhenClause) -> None:
        self.default_when = clause
        self.add_child(clause)

    def when_groups(self) -> list[list[WhenClause]]:
        """The WHEN arms as they execute: stacked WHEN phrases grouped.

        ``WHEN 'A' WHEN 'B' PERFORM X`` is one arm with two selector sets:
        the imperative statements after the last WHEN of a stack belong to
        every WHEN in it. The AST keeps one `WhenClause` per WHEN phrase (so
        the earlier ones have no statements); this joins each clause the
        parser marked `stacked` to the clause after it. The last clause of
        each group owns the shared body (``group[-1].statements``).

        A WHEN that is merely empty in the AST is not joined: only the
        parser can tell "no statement in the source" from "a statement that
        did not make it into the AST". WHEN OTHER (`default_when`) is never
        part of a group.
        """
        groups: list[list[WhenClause]] = []
        pending: list[WhenClause] = []
        for clause in self.when_clauses:
            pending.append(clause)
            if not clause.stacked:
                groups.append(pending)
                pending = []
        if pending:
            groups.append(pending)
        return groups

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        subjects_serialized: list[Any] = []
        for subj in self.subjects:
            if isinstance(subj, CobolExpression):
                subjects_serialized.append(subj.to_dict())
            else:
                subjects_serialized.append(subj)

        result.update(
            {
                "subjects": subjects_serialized,
                "when_clauses": [wc.to_dict() for wc in self.when_clauses],
                "default_when": (
                    self.default_when.to_dict() if self.default_when else None
                ),
            }
        )
        return result


class IfStatement(CobolStatement):
    """AST node for IF statements with conditional branches."""

    def __init__(self, location: SourceLocation):
        super().__init__("IF", location)
        self.condition: CobolExpression | None = None
        self.then_statements: list[CobolStatement] = []
        self.else_statements: list[CobolStatement] = []

    def set_condition(self, condition: "CobolExpression") -> None:
        """Set the IF condition."""
        self.condition = condition
        self.add_child(condition)

    def add_then_statement(self, statement: "CobolStatement") -> None:
        """Add a statement to the THEN branch."""
        self.then_statements.append(statement)
        self.add_child(statement)

    def add_else_statement(self, statement: "CobolStatement") -> None:
        """Add a statement to the ELSE branch."""
        self.else_statements.append(statement)
        self.add_child(statement)

    def to_dict(self) -> dict[str, Any]:
        """Convert IF statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "condition": self.condition.to_dict() if self.condition else None,
                "then_statements": [stmt.to_dict() for stmt in self.then_statements],
                "else_statements": [stmt.to_dict() for stmt in self.else_statements],
            }
        )
        return result


class PerformStatement(CobolStatement):
    """AST node for PERFORM statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("PERFORM", location)
        self.target_paragraph: str | None = None
        self.thru_paragraph: str | None = None  # Ending paragraph for PERFORM THRU
        self.perform_type: str = "SIMPLE"  # SIMPLE, TIMES, UNTIL, VARYING
        self.times_count: int | str | None = None  # Can be int literal or variable name
        self.until_condition: CobolExpression | None = None
        self.test_timing: str = "BEFORE"  # BEFORE or AFTER for WITH TEST clause
        self.varying_clause: dict[str, Any] | None = None
        # Additional dimensions of PERFORM VARYING ... AFTER ... (2-D/3-D
        # table loops). Each entry: {"variable", "from_value", "by_value",
        # "until_condition": CobolExpression | None}.
        self.after_clauses: list[dict[str, Any]] = []
        self.inline_statements: list[CobolStatement] = []

    def set_target_paragraph(self, paragraph: str) -> None:
        """Set the target paragraph to perform."""
        self.target_paragraph = paragraph
        self._add_unique_operand(paragraph, front=True)

    def set_thru_paragraph(self, paragraph: str) -> None:
        """Set the ending paragraph for PERFORM THRU."""
        self.thru_paragraph = paragraph
        self._add_unique_operand(paragraph)

    def set_times_clause(self, count: int | str) -> None:
        """Set TIMES clause for the PERFORM."""
        self.perform_type = "TIMES"
        self.times_count = count

    def set_until_clause(self, condition: "CobolExpression") -> None:
        """Set UNTIL clause for the PERFORM."""
        self.perform_type = "UNTIL"
        self.until_condition = condition
        self.add_child(condition)

    def mark_varying(self) -> None:
        """Tag this PERFORM as a VARYING-form loop.

        Called as soon as the VARYING keyword is recognized, *before* its
        FROM/BY/UNTIL sub-clause is known to parse successfully. Without
        this, perform_type only became "VARYING" via set_varying_clause(),
        which requires a fully-parsed until_condition -- so a malformed or
        partially-recognized VARYING clause left perform_type at the
        default "SIMPLE", indistinguishable from a genuine plain PERFORM to
        any caller keyed off perform_type. The keyword's presence is
        unambiguous proof of intent even when the rest of the clause isn't.
        """
        self.perform_type = "VARYING"

    def set_varying_clause(
        self,
        variable: str,
        from_value: str,
        by_value: str,
        until_condition: "CobolExpression",
    ) -> None:
        """Set VARYING clause for the PERFORM."""
        self.perform_type = "VARYING"
        self.varying_clause = {
            "variable": variable,
            "from_value": from_value,
            "by_value": by_value,
        }
        self.until_condition = until_condition
        self.add_child(until_condition)

    def add_after_clause(
        self,
        variable: str,
        from_value: str,
        by_value: str,
        until_condition: "CobolExpression | None" = None,
    ) -> None:
        """Add an AFTER dimension of a PERFORM VARYING ... AFTER ... loop."""
        self.after_clauses.append(
            {
                "variable": variable,
                "from_value": from_value,
                "by_value": by_value,
                "until_condition": until_condition,
            }
        )
        if until_condition is not None:
            self.add_child(until_condition)

    def set_test_timing(self, test_timing: str) -> "PerformStatement":
        """Set the test timing clause (BEFORE or AFTER)."""
        if test_timing.upper() not in ["BEFORE", "AFTER"]:
            raise ValueError(f"Invalid test timing: {test_timing}")
        self.test_timing = test_timing.upper()
        return self

    def add_inline_statement(self, statement: "CobolStatement") -> None:
        """Add a statement to the inline block of this PERFORM."""
        self.inline_statements.append(statement)
        self.add_child(statement)

    def to_dict(self) -> dict[str, Any]:
        """Convert PERFORM statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "target_paragraph": self.target_paragraph,
                "thru_paragraph": self.thru_paragraph,
                "perform_type": self.perform_type,
                "times_count": self.times_count,
                "until_condition": (
                    self.until_condition.to_dict() if self.until_condition else None
                ),
                "test_timing": self.test_timing,
                "varying_clause": self.varying_clause,
                "inline_statements": [
                    stmt.to_dict() for stmt in self.inline_statements
                ],
            }
        )
        if self.after_clauses:
            result["after_clauses"] = [
                {
                    **clause,
                    "until_condition": (
                        clause["until_condition"].to_dict()
                        if clause["until_condition"] is not None
                        else None
                    ),
                }
                for clause in self.after_clauses
            ]
        return result


class GoStatement(CobolStatement):
    """AST node for GO TO statements.

    GO TO statements transfer control to a labeled paragraph or section.
    Syntax: GO TO paragraph-name

    Example:
        GO TO PARA-1.
        GO TO PARA-1 DEPENDING ON var.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("GOTO", location)
        self.target_paragraph: str | None = None
        # All targets in order — a computed GO TO (DEPENDING ON) has several.
        self.target_paragraphs: list[str] = []
        self.depending_on_variable: str | None = None

    def set_target_paragraph(self, name: str) -> None:
        """Set the (first) target paragraph name."""
        self.target_paragraph = name
        if name not in self.target_paragraphs:
            self.target_paragraphs.append(name)
        self._add_unique_operand(name)

    def add_target_paragraph(self, name: str) -> None:
        """Append an additional target for computed GO TO ... DEPENDING ON.

        Targets are positional (the Nth is taken when the variable is N), so
        a repeated name is kept: ``GO TO A B A DEPENDING ON X`` has three
        targets, and deduplicating shifted every later one.
        """
        if self.target_paragraph is None:
            self.target_paragraph = name
        self.target_paragraphs.append(name)
        self._add_unique_operand(name)

    def set_depending_on_variable(self, var_name: str) -> None:
        """Set the DEPENDING ON variable for computed GO TO."""
        self.depending_on_variable = var_name
        self._add_unique_operand(var_name)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        base = super().to_dict()
        base.update(
            {
                "target_paragraph": self.target_paragraph,
                "target_paragraphs": self.target_paragraphs,
                "depending_on_variable": self.depending_on_variable,
            }
        )
        return base


class StopStatement(CobolStatement):
    """AST node for STOP RUN statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("STOP", location)
        self.stop_type: str = "RUN"  # RUN or literal
        # STOP RUN [RETURNING|GIVING x] — the return/exit code, if given.
        self.returning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert STOP statement to dictionary representation."""
        result = super().to_dict()
        result.update({"stop_type": self.stop_type, "returning": self.returning})
        return result


class SearchStatement(CobolStatement):
    """AST node for SEARCH statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("SEARCH", location)
        self.at_end_clause: list[CobolStatement] | None = None
        self.table_name: str | None = None
        self.varying_variable: str | None = None
        self.when_clauses: list[dict[str, Any]] = []

    def set_table_name(self, name: str) -> None:
        """Set the table name being searched."""
        self.table_name = name

    def set_varying_variable(self, variable: str) -> None:
        """Set the VARYING variable."""
        self.varying_variable = variable

    def add_when_clause(
        self,
        condition: str,
        statements: list["CobolStatement"],
        condition_tree: CobolExpression | None = None,
    ) -> None:
        """Add a WHEN clause with condition and statements.

        *condition* stays the raw joined text every existing consumer reads;
        *condition_tree*, when the shared condition machinery could build
        one, is the structural ConditionalExpression / LogicalExpression
        tree -- the only form in which ``A = 1 AND B = 2`` is two
        comparisons rather than one string.
        """
        clause: dict[str, Any] = {"condition": condition, "statements": statements}
        if condition_tree is not None:
            clause["condition_tree"] = condition_tree
        self.when_clauses.append(clause)
        for stmt in statements:
            self.add_child(stmt)

    def set_at_end_clause(self, statements: list["CobolStatement"]) -> None:
        self.at_end_clause = statements
        for stmt in statements:
            self.add_child(stmt)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        if self.table_name:
            result["table_name"] = self.table_name
        if self.varying_variable:
            result["varying_variable"] = self.varying_variable
        if self.when_clauses:
            result["when_clauses"] = [
                {
                    "condition": clause["condition"],
                    **(
                        {"condition_tree": clause["condition_tree"].to_dict()}
                        if clause.get("condition_tree") is not None
                        else {}
                    ),
                    "statements": [s.to_dict() for s in clause["statements"]],
                }
                for clause in self.when_clauses
            ]
        result.update(self._serialize_clauses("at_end_clause", omit_empty=True))
        return result


class RaiseStatement(CobolStatement):
    """AST node for the COBOL 2002 ``RAISE`` statement.

    Syntax::

        RAISE EXCEPTION exception-name
        RAISE identifier

    ``raise_type`` is ``"EXCEPTION"`` for the first form and
    ``"IDENTIFIER"`` for the second; ``target`` holds the exception-name or
    the identifier respectively.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("RAISE", location)
        self.raise_type: str | None = None
        self.target: str | None = None

    def set_target(self, target: str, *, raise_type: str) -> None:
        self.target = target
        self.raise_type = raise_type.upper()
        if self.raise_type == "IDENTIFIER":
            self._add_unique_operand(target)

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update({"raise_type": self.raise_type, "target": self.target})
        return result


class ResumeStatement(CobolStatement):
    """AST node for the COBOL 2002 ``RESUME`` statement (exit a declarative
    exception handler).

    Syntax::

        RESUME [AT] NEXT STATEMENT
        RESUME [AT] procedure-name

    ``target`` is the literal string ``"NEXT STATEMENT"`` for the first form,
    otherwise the procedure name.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("RESUME", location)
        self.target: str | None = None

    @property
    def resumes_next_statement(self) -> bool:
        return self.target == "NEXT STATEMENT"

    def to_dict(self) -> dict[str, Any]:
        result = super().to_dict()
        result.update(
            {
                "target": self.target,
                "resumes_next_statement": self.resumes_next_statement,
            }
        )
        return result
