"""
COBOL statement and expression AST nodes.

This module implements AST nodes for COBOL statements, expressions,
and control flow constructs with full functionality.
"""

from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass
from .ast_base import ASTNode, SourceLocation


class CobolStatement(ASTNode):
    """Base class for COBOL statement AST nodes."""

    def __init__(self, statement_type: str, location: SourceLocation):
        super().__init__("Statement", location)
        self.statement_type = statement_type
        self.operands: List[str] = []

    @property
    def sql_type(self) -> Optional[str]:
        """Return SQL type if this is an SQL statement, None otherwise."""
        return None

    @property
    def cics_command(self) -> Optional[str]:
        """Return CICS command if this is a CICS statement, None otherwise."""
        return None

    @property
    def ims_command(self) -> Optional[str]:
        """Return IMS command if this is an IMS statement, None otherwise."""
        return None

    def add_operand(self, operand: str) -> None:
        """Add an operand to the statement."""
        self.operands.append(operand)

    def to_dict(self) -> Dict[str, Any]:
        """Convert statement to dictionary representation."""
        return {
            "node_type": self.node_type,
            "statement_type": self.statement_type,
            "operands": self.operands,
            "location": self.location.to_dict(),
            "metadata": self._metadata,
        }


class MoveStatement(CobolStatement):
    """AST node for MOVE statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("MOVE", location)
        self.source: Optional[str] = None
        self.targets: List[str] = []
        self.is_corresponding: bool = False

    def set_source(self, source: str) -> None:
        """Set the source operand for the MOVE."""
        self.source = source
        if source not in self.operands:
            self.operands.insert(0, source)

    def add_target(self, target: str) -> None:
        """Add a target operand for the MOVE."""
        self.targets.append(target)
        if target not in self.operands:
            self.operands.append(target)

    def set_corresponding(self, is_corresponding: bool = True) -> None:
        """Set whether this is a MOVE CORRESPONDING statement."""
        self.is_corresponding = is_corresponding

    def to_dict(self) -> Dict[str, Any]:
        """Convert MOVE statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "source": self.source,
                "targets": self.targets,
                "is_corresponding": self.is_corresponding,
            }
        )
        return result


class DisplayStatement(CobolStatement):
    """AST node for DISPLAY statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("DISPLAY", location)
        self.display_items: List[str] = []
        self.output_device: Optional[str] = None

    def add_display_item(self, item: str) -> None:
        """Add an item to display."""
        self.display_items.append(item)
        self.operands.append(item)

    def set_output_device(self, device: str) -> None:
        """Set the output device (UPON clause)."""
        self.output_device = device

    def to_dict(self) -> Dict[str, Any]:
        """Convert DISPLAY statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {"display_items": self.display_items, "output_device": self.output_device}
        )
        return result


class PerformStatement(CobolStatement):
    """AST node for PERFORM statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("PERFORM", location)
        self.target_paragraph: Optional[str] = None
        self.thru_paragraph: Optional[str] = None  # Ending paragraph for PERFORM THRU
        self.perform_type: str = "SIMPLE"  # SIMPLE, TIMES, UNTIL, VARYING
        self.times_count: Optional[Union[int, str]] = (
            None  # Can be int literal or variable name
        )
        self.until_condition: Optional["CobolExpression"] = None
        self.test_timing: str = "BEFORE"  # BEFORE or AFTER for WITH TEST clause
        self.varying_clause: Optional[Dict[str, Any]] = None
        self.inline_statements: List["CobolStatement"] = []

    def set_target_paragraph(self, paragraph: str) -> None:
        """Set the target paragraph to perform."""
        self.target_paragraph = paragraph
        if paragraph not in self.operands:
            self.operands.insert(0, paragraph)

    def set_thru_paragraph(self, paragraph: str) -> None:
        """Set the ending paragraph for PERFORM THRU."""
        self.thru_paragraph = paragraph
        if paragraph not in self.operands:
            self.operands.append(paragraph)

    def set_times_clause(self, count: Union[int, str]) -> None:
        """Set TIMES clause for the PERFORM."""
        self.perform_type = "TIMES"
        self.times_count = count

    def set_until_clause(self, condition: "CobolExpression") -> None:
        """Set UNTIL clause for the PERFORM."""
        self.perform_type = "UNTIL"
        self.until_condition = condition
        self.add_child(condition)

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

    def to_dict(self) -> Dict[str, Any]:
        """Convert PERFORM statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "target_paragraph": self.target_paragraph,
                "thru_paragraph": self.thru_paragraph,
                "perform_type": self.perform_type,
                "times_count": self.times_count,
                "until_condition": self.until_condition.to_dict()
                if self.until_condition
                else None,
                "test_timing": self.test_timing,
                "varying_clause": self.varying_clause,
                "inline_statements": [
                    stmt.to_dict() for stmt in self.inline_statements
                ],
            }
        )
        return result


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
        self.statements: List["CobolStatement"] = []

    def add_statement(self, statement: "CobolStatement") -> None:
        self.statements.append(statement)
        self.add_child(statement)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": self.node_type,
            "selectors": self.selectors,
            "statements": [s.to_dict() for s in self.statements],
            "location": self.location.to_dict(),
            "metadata": self._metadata,
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
        self.subjects: List[Union[str, "CobolExpression"]] = []
        self.when_clauses: List[WhenClause] = []
        self.default_when: Optional[WhenClause] = None

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

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        subjects_serialized = []
        for subj in self.subjects:
            if isinstance(subj, CobolExpression):
                subjects_serialized.append(subj.to_dict())
            else:
                subjects_serialized.append(subj)

        result.update(
            {
                "subjects": subjects_serialized,
                "when_clauses": [wc.to_dict() for wc in self.when_clauses],
                "default_when": self.default_when.to_dict()
                if self.default_when
                else None,
            }
        )
        return result


class IfStatement(CobolStatement):
    """AST node for IF statements with conditional branches."""

    def __init__(self, location: SourceLocation):
        super().__init__("IF", location)
        self.condition: Optional["CobolExpression"] = None
        self.then_statements: List["CobolStatement"] = []
        self.else_statements: List["CobolStatement"] = []

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

    def to_dict(self) -> Dict[str, Any]:
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


class StopStatement(CobolStatement):
    """AST node for STOP RUN statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("STOP", location)
        self.stop_type: str = "RUN"  # RUN or literal

    def to_dict(self) -> Dict[str, Any]:
        """Convert STOP statement to dictionary representation."""
        result = super().to_dict()
        result.update({"stop_type": self.stop_type})
        return result


class ComputeStatement(CobolStatement):
    """AST node for COMPUTE statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("COMPUTE", location)
        self.targets: List[str] = []
        self.expression: Optional["CobolExpression"] = None
        self.on_size_error: Optional[List["CobolStatement"]] = None
        self.not_on_size_error: Optional[List["CobolStatement"]] = None

    def add_target(self, target: str) -> None:
        """Add a target variable for the computation."""
        self.targets.append(target)
        if target not in self.operands:
            self.operands.append(target)

    def set_expression(self, expression: "CobolExpression") -> None:
        """Set the arithmetic expression for the computation."""
        self.expression = expression
        self.add_child(expression)

    def set_on_size_error_clause(self, statements: List["CobolStatement"]) -> None:
        self.on_size_error = statements
        for stmt in statements:
            self.add_child(stmt)

    def set_not_on_size_error_clause(self, statements: List["CobolStatement"]) -> None:
        self.not_on_size_error = statements
        for stmt in statements:
            self.add_child(stmt)

    def to_dict(self) -> Dict[str, Any]:
        """Convert COMPUTE statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "targets": self.targets,
                "expression": self.expression.to_dict() if self.expression else None,
            }
        )
        if self.on_size_error:
            result["on_size_error"] = [s.to_dict() for s in self.on_size_error]
        if self.not_on_size_error:
            result["not_on_size_error"] = [s.to_dict() for s in self.not_on_size_error]
        return result


class ArithmeticStatement(CobolStatement):
    """Base AST node for arithmetic statements (ADD, SUBTRACT, MULTIPLY, DIVIDE)."""

    def __init__(self, statement_type: str, location: SourceLocation):
        super().__init__(statement_type, location)
        self.on_size_error: Optional[List["CobolStatement"]] = None
        self.not_on_size_error: Optional[List["CobolStatement"]] = None

    def set_on_size_error_clause(self, statements: List["CobolStatement"]) -> None:
        self.on_size_error = statements
        for stmt in statements:
            self.add_child(stmt)

    def set_not_on_size_error_clause(self, statements: List["CobolStatement"]) -> None:
        self.not_on_size_error = statements
        for stmt in statements:
            self.add_child(stmt)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.on_size_error:
            result["on_size_error"] = [s.to_dict() for s in self.on_size_error]
        if self.not_on_size_error:
            result["not_on_size_error"] = [s.to_dict() for s in self.not_on_size_error]
        return result


class AddStatement(ArithmeticStatement):
    """AST node for ADD statements."""
    def __init__(self, location: SourceLocation):
        super().__init__("ADD", location)


class SubtractStatement(ArithmeticStatement):
    """AST node for SUBTRACT statements."""
    def __init__(self, location: SourceLocation):
        super().__init__("SUBTRACT", location)


class MultiplyStatement(ArithmeticStatement):
    """AST node for MULTIPLY statements."""
    def __init__(self, location: SourceLocation):
        super().__init__("MULTIPLY", location)


class DivideStatement(ArithmeticStatement):
    """AST node for DIVIDE statements."""
    def __init__(self, location: SourceLocation):
        super().__init__("DIVIDE", location)


class SearchStatement(CobolStatement):
    """AST node for SEARCH statements."""
    def __init__(self, location: SourceLocation):
        super().__init__("SEARCH", location)
        self.at_end_clause: Optional[List["CobolStatement"]] = None

    def set_at_end_clause(self, statements: List["CobolStatement"]) -> None:
        self.at_end_clause = statements
        for stmt in statements:
            self.add_child(stmt)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.at_end_clause:
            result["at_end_clause"] = [s.to_dict() for s in self.at_end_clause]
        return result


class StringStatement(CobolStatement):
    """AST node for STRING statements."""
    def __init__(self, location: SourceLocation):
        super().__init__("STRING", location)
        self.on_overflow: Optional[List["CobolStatement"]] = None
        self.not_on_overflow: Optional[List["CobolStatement"]] = None

    def set_on_overflow_clause(self, statements: List["CobolStatement"]) -> None:
        self.on_overflow = statements
        for stmt in statements:
            self.add_child(stmt)

    def set_not_on_overflow_clause(self, statements: List["CobolStatement"]) -> None:
        self.not_on_overflow = statements
        for stmt in statements:
            self.add_child(stmt)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.on_overflow:
            result["on_overflow"] = [s.to_dict() for s in self.on_overflow]
        if self.not_on_overflow:
            result["not_on_overflow"] = [s.to_dict() for s in self.not_on_overflow]
        return result


class UnstringStatement(CobolStatement):
    """AST node for UNSTRING statements."""
    def __init__(self, location: SourceLocation):
        super().__init__("UNSTRING", location)
        self.on_overflow: Optional[List["CobolStatement"]] = None
        self.not_on_overflow: Optional[List["CobolStatement"]] = None

    def set_on_overflow_clause(self, statements: List["CobolStatement"]) -> None:
        self.on_overflow = statements
        for stmt in statements:
            self.add_child(stmt)

    def set_not_on_overflow_clause(self, statements: List["CobolStatement"]) -> None:
        self.not_on_overflow = statements
        for stmt in statements:
            self.add_child(stmt)

    def to_dict(self) -> Dict[str, Any]:
        result = super().to_dict()
        if self.on_overflow:
            result["on_overflow"] = [s.to_dict() for s in self.on_overflow]
        if self.not_on_overflow:
            result["not_on_overflow"] = [s.to_dict() for s in self.not_on_overflow]
        return result


@dataclass
class CallParameter:
    """Parameter passed to a CALL statement."""

    name: str
    passing_mode: str = "REFERENCE"  # REFERENCE, CONTENT, or VALUE


class CallStatement(CobolStatement):
    """AST node for CALL statements.

    Supports both static CALL statements (with literal program names) and
    dynamic CALL statements (using variables). For dynamic calls, the parser
    can track possible values through data flow analysis.
    """

    def __init__(self, location: SourceLocation):
        super().__init__("CALL", location)
        self.called_program: Optional[str] = None
        self.using_parameters: List[CallParameter] = []
        self.returning_parameter: Optional[str] = None
        self.giving_parameter: Optional[str] = None
        self.on_overflow: Optional[List["CobolStatement"]] = None
        self.on_exception: Optional[List["CobolStatement"]] = None
        self.not_on_exception: Optional[List["CobolStatement"]] = None
        self._is_dynamic: bool = False
        self._possible_values: List[str] = []

    def set_called_program(self, program_name: str, is_dynamic: bool = False):
        """Set the called program name and type."""
        self.called_program = program_name
        self._is_dynamic = is_dynamic
        if program_name not in self.operands:
            self.add_operand(program_name)

    def add_using_parameter(self, param_name: str, passing_mode: str = "REFERENCE"):
        """Add a parameter to the USING clause."""
        param = CallParameter(param_name, passing_mode)
        self.using_parameters.append(param)
        if param_name not in self.operands:
            self.add_operand(param_name)

    def set_giving_parameter(self, param_name: str):
        """Set the GIVING parameter."""
        self.giving_parameter = param_name
        if param_name not in self.operands:
            self.add_operand(param_name)

    def set_returning_parameter(self, param_name: str):
        """Set the RETURNING parameter."""
        self.returning_parameter = param_name
        if param_name not in self.operands:
            self.add_operand(param_name)

    @property
    def is_dynamic(self) -> bool:
        """Check if this is a dynamic CALL."""
        return self._is_dynamic

    @property
    def possible_values(self) -> List[str]:
        """Get possible values for dynamic call target."""
        return list(self._possible_values)

    def add_possible_value(self, value: str):
        """Add a possible value for dynamic call."""
        if value not in self._possible_values:
            self._possible_values.append(value)

    def set_possible_values(self, values: List[str]):
        """Set all possible values."""
        self._possible_values = list(set(values))  # Deduplicate

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        base = super().to_dict()
        base.update(
            {
                "called_program": self.called_program,
                "using_parameters": [
                    {"name": p.name, "mode": p.passing_mode}
                    for p in self.using_parameters
                ],
                "giving_parameter": self.giving_parameter,
                "returning_parameter": self.returning_parameter,
                "is_dynamic": self.is_dynamic,
                "possible_values": self.possible_values,
            }
        )
        # Add exception handlers if present
        if self.on_overflow:
            base["on_overflow"] = [s.to_dict() for s in self.on_overflow]
        if self.on_exception:
            base["on_exception"] = [s.to_dict() for s in self.on_exception]

        return base


class EntryStatement(CobolStatement):
    """AST node for ENTRY statements.

    ENTRY statements define alternate entry points into a program, commonly
    used in IMS programs. The syntax is:
        ENTRY literal-name [USING parameter-list]

    Example:
        ENTRY 'DLITCBL' USING LKPCB-IO LKPCB-ALT LKPCB-BPP100MA
    """

    def __init__(self, location: SourceLocation):
        super().__init__("ENTRY", location)
        self.entry_name: Optional[str] = None
        self.using_parameters: List[str] = []

    def set_entry_name(self, name: str) -> None:
        """Set the entry point name (literal)."""
        self.entry_name = name
        if name not in self.operands:
            self.add_operand(name)

    def add_using_parameter(self, param_name: str) -> None:
        """Add a parameter to the USING clause."""
        self.using_parameters.append(param_name)
        if param_name not in self.operands:
            self.add_operand(param_name)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        base = super().to_dict()
        base.update(
            {"entry_name": self.entry_name, "using_parameters": self.using_parameters}
        )
        return base


class SelectStatement(CobolStatement):
    """AST node for SELECT statements in FILE-CONTROL paragraph.

    Supports comprehensive SELECT clause variations:
    - ASSIGN TO with device types and assignment specifications
    - ORGANIZATION: SEQUENTIAL, INDEXED, RELATIVE, LINE SEQUENTIAL
    - ACCESS MODE: SEQUENTIAL, RANDOM, DYNAMIC
    - RECORD KEY and ALTERNATE RECORD KEY with duplicate handling
    - FILE STATUS variable assignments
    - RESERVE clause area allocations
    - PADDING CHARACTER and RECORD DELIMITER specifications
    - PASSWORD and LOCK MODE clauses for security and concurrency
    - SHARING clauses for multi-user access
    - OPTIONAL clause for file existence handling
    """

    def __init__(self, location: SourceLocation):
        super().__init__("SELECT", location)
        self.file_name: Optional[str] = None
        self.is_optional: bool = False

        # ASSIGN clause
        self.assign_to: Optional[str] = None
        self.assign_device_type: Optional[str] = None  # DISK, TAPE, PRINTER, etc.
        self.assign_external_name: Optional[str] = None

        # ORGANIZATION clause
        self.organization: Optional[str] = (
            None  # SEQUENTIAL, INDEXED, RELATIVE, LINE SEQUENTIAL
        )

        # ACCESS MODE clause
        self.access_mode: Optional[str] = None  # SEQUENTIAL, RANDOM, DYNAMIC

        # RECORD KEY clause
        self.record_key: Optional[str] = None
        self.record_key_source: Optional[str] = (
            None  # SOURCE IS data-name (IBM extension)
        )

        # ALTERNATE RECORD KEY clause(s)
        self.alternate_keys: List[
            Dict[str, Any]
        ] = []  # [{key, duplicates_allowed, password}]

        # FILE STATUS clause
        self.file_status: Optional[str] = None
        self.file_status_vsam: Optional[str] = None  # Second status variable for VSAM

        # RELATIVE KEY clause
        self.relative_key: Optional[str] = None

        # RESERVE clause
        self.reserve_areas: Optional[int] = None

        # PADDING CHARACTER clause
        self.padding_character: Optional[str] = None

        # RECORD DELIMITER clause
        self.record_delimiter: Optional[str] = None  # STANDARD-1 or identifier

        # PASSWORD clause
        self.password: Optional[str] = None

        # LOCK MODE clause
        self.lock_mode: Optional[str] = None  # MANUAL, AUTOMATIC, EXCLUSIVE
        self.lock_on: Optional[str] = None  # RECORD, MULTIPLE RECORDS
        self.lock_with_rollback: bool = False

        # SHARING clause
        self.sharing_mode: Optional[str] = None  # ALL, NO OTHER, READ ONLY

    def set_file_name(self, name: str, is_optional: bool = False) -> None:
        """Set the file name being selected."""
        self.file_name = name
        self.is_optional = is_optional
        if name not in self.operands:
            self.operands.insert(0, name)

    def set_assign_to(
        self,
        assign_value: str,
        device_type: Optional[str] = None,
        external_name: Optional[str] = None,
    ) -> None:
        """Set the ASSIGN TO clause value with optional device type."""
        self.assign_to = assign_value
        self.assign_device_type = device_type
        self.assign_external_name = external_name
        if assign_value not in self.operands:
            self.operands.append(assign_value)

    def set_organization(self, org: str) -> None:
        """Set the ORGANIZATION clause."""
        self.organization = org.upper()

    def set_access_mode(self, mode: str) -> None:
        """Set the ACCESS MODE clause."""
        self.access_mode = mode.upper()

    def set_record_key(self, key: str, source: Optional[str] = None) -> None:
        """Set the RECORD KEY clause."""
        self.record_key = key
        self.record_key_source = source

    def add_alternate_key(
        self, key: str, duplicates_allowed: bool = False, password: Optional[str] = None
    ) -> None:
        """Add an ALTERNATE RECORD KEY clause."""
        self.alternate_keys.append(
            {"key": key, "duplicates_allowed": duplicates_allowed, "password": password}
        )

    def set_file_status(self, status: str, vsam_status: Optional[str] = None) -> None:
        """Set the FILE STATUS clause."""
        self.file_status = status
        self.file_status_vsam = vsam_status

    def set_relative_key(self, key: str) -> None:
        """Set the RELATIVE KEY clause."""
        self.relative_key = key

    def set_reserve_areas(self, areas: int) -> None:
        """Set the RESERVE clause."""
        self.reserve_areas = areas

    def set_padding_character(self, character: str) -> None:
        """Set the PADDING CHARACTER clause."""
        self.padding_character = character

    def set_record_delimiter(self, delimiter: str) -> None:
        """Set the RECORD DELIMITER clause."""
        self.record_delimiter = delimiter

    def set_password(self, password: str) -> None:
        """Set the PASSWORD clause."""
        self.password = password

    def set_lock_mode(
        self, mode: str, lock_on: Optional[str] = None, with_rollback: bool = False
    ) -> None:
        """Set the LOCK MODE clause."""
        self.lock_mode = mode.upper()
        self.lock_on = lock_on
        self.lock_with_rollback = with_rollback

    def set_sharing_mode(self, mode: str) -> None:
        """Set the SHARING clause."""
        self.sharing_mode = mode.upper()

    def to_dict(self) -> Dict[str, Any]:
        """Convert SELECT statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "is_optional": self.is_optional,
                "assign_to": self.assign_to,
                "assign_device_type": self.assign_device_type,
                "assign_external_name": self.assign_external_name,
                "organization": self.organization,
                "access_mode": self.access_mode,
                "record_key": self.record_key,
                "record_key_source": self.record_key_source,
                "alternate_keys": self.alternate_keys,
                "file_status": self.file_status,
                "file_status_vsam": self.file_status_vsam,
                "relative_key": self.relative_key,
                "reserve_areas": self.reserve_areas,
                "padding_character": self.padding_character,
                "record_delimiter": self.record_delimiter,
                "password": self.password,
                "lock_mode": self.lock_mode,
                "lock_on": self.lock_on,
                "lock_with_rollback": self.lock_with_rollback,
                "sharing_mode": self.sharing_mode,
            }
        )
        return result


class CopyStatement(CobolStatement):
    """AST node for COPY statements."""

    def __init__(self, location: SourceLocation):
        super().__init__("COPY", location)
        self.copybook_name: Optional[str] = None
        self.library_name: Optional[str] = None
        self.suppressions: List[str] = []
        self.replacements: List[Dict[str, str]] = []

    def set_copybook_name(self, name: str) -> None:
        """Set the copybook name."""
        self.copybook_name = name
        if name not in self.operands:
            self.operands.insert(0, name)

    def set_library_name(self, library: str) -> None:
        """Set the IN/OF library name."""
        self.library_name = library
        if library not in self.operands:
            self.operands.append(library)

    def add_suppression(self, suppression: str) -> None:
        """Add a SUPPRESS phrase."""
        self.suppressions.append(suppression)

    def add_replacement(self, old_text: str, new_text: str) -> None:
        """Add a REPLACING phrase."""
        self.replacements.append({"old_text": old_text, "new_text": new_text})

    def to_dict(self) -> Dict[str, Any]:
        """Convert COPY statement to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "copybook_name": self.copybook_name,
                "library_name": self.library_name,
                "suppressions": self.suppressions,
                "replacements": self.replacements,
            }
        )
        return result


class CobolExpression(ASTNode):
    """Base class for COBOL expression AST nodes."""

    def __init__(self, expression_type: str, location: SourceLocation):
        super().__init__("Expression", location)
        self.expression_type = expression_type

    def to_dict(self) -> Dict[str, Any]:
        """Convert expression to dictionary representation."""
        return {
            "node_type": self.node_type,
            "expression_type": self.expression_type,
            "location": self.location.to_dict(),
            "metadata": self._metadata,
        }


class ArithmeticExpression(CobolExpression):
    """AST node for arithmetic expressions."""

    def __init__(self, operator: str, location: SourceLocation):
        super().__init__("ARITHMETIC", location)
        self.operator = operator
        self.left_operand: Optional[Union[str, "CobolExpression"]] = None
        self.right_operand: Optional[Union[str, "CobolExpression"]] = None

    def set_left_operand(self, operand: Union[str, "CobolExpression"]) -> None:
        """Set the left operand of the expression."""
        self.left_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)

    def set_right_operand(self, operand: Union[str, "CobolExpression"]) -> None:
        """Set the right operand of the expression."""
        self.right_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)

    def to_dict(self) -> Dict[str, Any]:
        """Convert arithmetic expression to dictionary representation."""
        result = super().to_dict()

        left_dict = (
            self.left_operand.to_dict()
            if isinstance(self.left_operand, CobolExpression)
            else self.left_operand
        )
        right_dict = (
            self.right_operand.to_dict()
            if isinstance(self.right_operand, CobolExpression)
            else self.right_operand
        )

        result.update(
            {
                "operator": self.operator,
                "left_operand": left_dict,
                "right_operand": right_dict,
            }
        )
        return result


class ConditionalExpression(CobolExpression):
    """AST node for conditional expressions."""

    def __init__(self, operator: str, location: SourceLocation):
        super().__init__("COMPARISON", location)
        self.operator = operator
        self.left_operand: Optional[Union[str, "CobolExpression"]] = None
        self.right_operand: Optional[Union[str, "CobolExpression"]] = None

    @property
    def condition_type(self) -> str:
        """Return the condition type."""
        return self.expression_type

    def set_left_operand(self, operand: Union[str, "CobolExpression"]) -> None:
        """Set the left operand of the condition."""
        self.left_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)

    def set_right_operand(self, operand: Union[str, "CobolExpression"]) -> None:
        """Set the right operand of the condition."""
        self.right_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)

    def to_dict(self) -> Dict[str, Any]:
        """Convert conditional expression to dictionary representation."""
        result = super().to_dict()

        left_dict = (
            self.left_operand.to_dict()
            if isinstance(self.left_operand, CobolExpression)
            else self.left_operand
        )
        right_dict = (
            self.right_operand.to_dict()
            if isinstance(self.right_operand, CobolExpression)
            else self.right_operand
        )

        result.update(
            {
                "operator": self.operator,
                "left_operand": left_dict,
                "right_operand": right_dict,
                "condition_type": self.condition_type,
            }
        )
        return result


class LogicalExpression(CobolExpression):
    """AST node for logical expressions (AND, OR, NOT)."""

    def __init__(self, operator: str, location: SourceLocation):
        super().__init__("LOGICAL", location)
        self.operator = operator
        self.left_condition: Optional["CobolExpression"] = None
        self.right_condition: Optional["CobolExpression"] = None

    def set_left_condition(self, condition: "CobolExpression") -> None:
        """Set the left condition of the logical expression."""
        self.left_condition = condition
        self.add_child(condition)

    def set_right_condition(self, condition: "CobolExpression") -> None:
        """Set the right condition of the logical expression."""
        self.right_condition = condition
        self.add_child(condition)

    def to_dict(self) -> Dict[str, Any]:
        """Convert logical expression to dictionary representation."""
        result = super().to_dict()
        result.update(
            {
                "operator": self.operator,
                "left_condition": self.left_condition.to_dict()
                if self.left_condition
                else None,
                "right_condition": self.right_condition.to_dict()
                if self.right_condition
                else None,
            }
        )
        return result


class FunctionCall(CobolExpression):
    """AST node for COBOL function calls."""

    def __init__(self, function_name: str, location: SourceLocation):
        super().__init__("FUNCTION", location)
        self.function_name = function_name
        self.function_type = "INTRINSIC"  # INTRINSIC or USER_DEFINED
        self.arguments: List[Union[str, "CobolExpression"]] = []

    def add_argument(self, argument: Union[str, "CobolExpression"]) -> None:
        """Add an argument to the function call."""
        self.arguments.append(argument)
        if isinstance(argument, CobolExpression):
            self.add_child(argument)

    def set_function_type(self, func_type: str) -> None:
        """Set the function type (INTRINSIC or USER_DEFINED)."""
        self.function_type = func_type

    def to_dict(self) -> Dict[str, Any]:
        """Convert function call to dictionary representation."""
        result = super().to_dict()

        args_dict = []
        for arg in self.arguments:
            if isinstance(arg, CobolExpression):
                args_dict.append(arg.to_dict())
            else:
                args_dict.append(arg)

        result.update(
            {
                "function_name": self.function_name,
                "function_type": self.function_type,
                "arguments": args_dict,
            }
        )
        return result


class IOReadStatement(CobolStatement):
    """AST node for READ statements with comprehensive IBM Enterprise COBOL variation support.

    Contract: contracts/io-statement-ast.md

    Supports:
    - Sequential, indexed, and relative READ operations
    - Multiple access modes (NEXT, PREVIOUS, RANDOM, FIRST, LAST, CURRENT)
    - INTO clause for data transfer
    - KEY clause for indexed and relative files
    - AT END and NOT AT END clauses
    - INVALID KEY handling
    - Lock modes and file access controls
    - RETRY clause for automatic retries
    """

    def __init__(self, location: SourceLocation):
        super().__init__("READ", location)
        self.file_name: Optional[str] = None
        self.record_name: Optional[str] = None
        self.into_target: Optional[str] = None
        self.key_name: Optional[str] = None  # KEY IS value (contract field name)
        self.key_value: Optional[str] = None  # Backward compat alias
        self.access_mode: Optional[str] = (
            None  # NEXT, FIRST, LAST, PREVIOUS, CURRENT (contract field)
        )
        self.record_format: Optional[str] = None  # Legacy name, kept for compat
        self.lock_scope: Optional[str] = None  # record, file (contract field)
        self.with_lock: bool = False
        self.with_nowait: bool = False
        self.at_end_clause: Optional[List["CobolStatement"]] = None
        self.not_at_end_clause: Optional[List["CobolStatement"]] = None
        self.invalid_key_clause: Optional[List["CobolStatement"]] = None
        self.not_invalid_key_clause: Optional[List["CobolStatement"]] = None
        self.retry_count: Optional[int] = None
        # Metadata tracking
        self._metadata["has_invalid_key"] = False
        self._metadata["has_at_end"] = False
        self._metadata["uses_lock"] = False

    def set_file_name(self, name: str) -> None:
        """Set the file name to read from."""
        self.file_name = name
        if name not in self.operands:
            self.operands.append(name)

    def set_record_name(self, name: str) -> None:
        """Set the record being read."""
        self.record_name = name
        if name not in self.operands:
            self.operands.append(name)

    def set_into(self, target: str) -> None:
        """Set the INTO clause target."""
        self.into_target = target
        if target not in self.operands:
            self.operands.append(target)

    def set_key(self, value: str) -> None:
        """Set the KEY IS clause value."""
        self.key_value = value
        self.key_name = value  # Contract field

    def set_record_format(self, fmt: str) -> None:
        """Set the access mode (NEXT, FIRST, LAST, PREVIOUS, CURRENT)."""
        fmt_upper = fmt.upper()
        self.record_format = fmt_upper  # Legacy compat
        self.access_mode = fmt_upper  # Contract field

    def set_access_mode(self, mode: str) -> None:
        """Set the access mode per contract."""
        self.access_mode = mode.upper()
        self.record_format = self.access_mode  # Backward compat

    def set_lock_mode(self, with_lock: bool = False, with_nowait: bool = False) -> None:
        """Set the lock mode for the read."""
        self.with_lock = with_lock
        self.with_nowait = with_nowait
        if with_lock:
            self._metadata["uses_lock"] = True
            self.lock_scope = "record"

    def set_at_end_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the AT END clause."""
        self.at_end_clause = statements
        if statements:
            self._metadata["has_at_end"] = True

    def set_not_at_end_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the NOT AT END clause."""
        self.not_at_end_clause = statements

    def set_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self._metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def set_retry(self, count: int) -> None:
        """Set the RETRY clause count."""
        self.retry_count = count

    def to_dict(self) -> Dict[str, Any]:
        """Convert READ statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_name": self.record_name,
                "into_target": self.into_target,
                # Legacy field names (backward compatibility)
                "record_format": self.record_format,
                "key_value": self.key_value,
                # Contract field names
                "key_name": self.key_name,
                "access_mode": self.access_mode,
                "lock_scope": self.lock_scope,
                # Status flags
                "with_lock": self.with_lock,
                "with_nowait": self.with_nowait,
                # Clauses
                "at_end_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.at_end_clause or [])
                ],
                "not_at_end_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.not_at_end_clause or [])
                ],
                "invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.not_invalid_key_clause or [])
                ],
                "retry_count": self.retry_count,
            }
        )
        return result


# Backward compatibility alias
ReadStatement = IOReadStatement


class IOWriteStatement(CobolStatement):
    """AST node for WRITE statements with comprehensive IBM Enterprise COBOL variation support.

    Contract: contracts/io-statement-ast.md

    Supports:
    - FROM clause for data source
    - BEFORE/AFTER ADVANCING for print files
    - AT END-OF-PAGE clause
    - INVALID KEY handling for indexed files
    - Record deletion for VSAM files
    - Multiple LINES specification
    - Lock modes and file access controls
    - RETRY clause for automatic retries
    """

    def __init__(self, location: SourceLocation):
        super().__init__("WRITE", location)
        self.file_name: Optional[str] = None  # Contract field (added)
        self.record_name: Optional[str] = None
        self.from_clause: Optional[str] = None  # Contract field name
        self.from_source: Optional[str] = None  # Legacy compat
        self.advancing_clause: Optional[Dict[str, Any]] = (
            None  # Contract field: {"type": "BEFORE"|"AFTER", "value": ..., "unit": "LINES"|"CHANNEL"}
        )
        self.advancing_mode: Optional[str] = None  # Legacy compat
        self.advancing_lines: Optional[int] = None  # Legacy compat
        self.advancing_page: bool = False  # Legacy compat
        self.delete_record: bool = False  # For VSAM DELETE
        self.at_eop_clause: Optional[List["CobolStatement"]] = None  # AT END-OF-PAGE
        self.invalid_key_clause: Optional[List["CobolStatement"]] = None
        self.not_invalid_key_clause: Optional[List["CobolStatement"]] = None
        self.retry_count: Optional[int] = None
        self.with_lock: bool = False
        self.lock_scope: Optional[str] = None  # Contract field
        # Metadata tracking
        self._metadata["has_invalid_key"] = False
        self._metadata["uses_advancing"] = False
        self._metadata["uses_lock"] = False

    def set_record_name(self, name: str) -> None:
        """Set the record being written."""
        self.record_name = name
        if name not in self.operands:
            self.operands.append(name)

    def set_from(self, source: str) -> None:
        """Set the FROM clause source."""
        self.from_source = source
        self.from_clause = source  # Contract field
        if source not in self.operands:
            self.operands.append(source)

    def set_advancing(
        self, mode: str, lines: Optional[int] = None, page: bool = False
    ) -> None:
        """Set the ADVANCING clause (legacy and contract)."""
        mode_upper = mode.upper()
        self.advancing_mode = mode_upper  # Legacy compat
        self.advancing_lines = lines  # Legacy compat
        self.advancing_page = page  # Legacy compat

        # Contract field: advancing_clause
        self.advancing_clause = {
            "type": mode_upper,  # BEFORE or AFTER
            "value": lines if lines else ("PAGE" if page else None),
            "unit": "CHANNEL" if page else ("LINES" if lines else None),
        }
        if self.advancing_clause:
            self._metadata["uses_advancing"] = True

    def set_delete(self, delete: bool = True) -> None:
        """Set the VSAM DELETE flag."""
        self.delete_record = delete

    def set_at_eop_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the AT END-OF-PAGE clause."""
        self.at_eop_clause = statements

    def set_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self._metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def set_retry(self, count: int) -> None:
        """Set the RETRY clause count."""
        self.retry_count = count

    def set_lock(self, with_lock: bool = True) -> None:
        """Set the LOCK flag."""
        self.with_lock = with_lock
        if with_lock:
            self._metadata["uses_lock"] = True
            self.lock_scope = "record"

    def to_dict(self) -> Dict[str, Any]:
        """Convert WRITE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_name": self.record_name,
                # Legacy field names (backward compatibility)
                "from_source": self.from_source,
                "advancing_mode": self.advancing_mode,
                "advancing_lines": self.advancing_lines,
                "advancing_page": self.advancing_page,
                # Contract field names
                "from_clause": self.from_clause,
                "advancing_clause": self.advancing_clause,
                "lock_scope": self.lock_scope,
                # Status flags
                "delete_record": self.delete_record,
                "with_lock": self.with_lock,
                # Clauses
                "at_eop_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.at_eop_clause or [])
                ],
                "invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.not_invalid_key_clause or [])
                ],
                "retry_count": self.retry_count,
            }
        )
        return result


# Backward compatibility alias
WriteStatement = IOWriteStatement


class IOOpenStatement(CobolStatement):
    """AST node for OPEN statements with comprehensive IO variation support.

    Supports:
    - Multiple file opens in single statement
    - OPEN INPUT, OUTPUT, I-O, EXTEND modes
    - Error handling for file status issues
    - REPOSITION for VSAM files
    """

    def __init__(self, location: SourceLocation):
        super().__init__("OPEN", location)
        self.open_mode: Optional[str] = None  # INPUT, OUTPUT, I-O, EXTEND
        self.file_names: List[str] = []
        self.with_reposition: bool = False
        self.reel_unit_control: Optional[str] = None  # Contract field
        self._metadata = {
            "has_reel_unit": False,
        }

    def set_open_mode(self, mode: str) -> None:
        """Set the OPEN mode."""
        self.open_mode = mode.upper()  # INPUT, OUTPUT, I-O, EXTEND

    def add_file(self, file_name: str) -> None:
        """Add a file to open."""
        if file_name not in self.file_names:
            self.file_names.append(file_name)
            self.operands.append(file_name)

    def set_reposition(self, reposition: bool = True) -> None:
        """Set the REPOSITION flag for VSAM files."""
        self.with_reposition = reposition

    def set_reel_unit_control(self, control: str) -> None:
        """Set the REEL/UNIT control (contract field)."""
        self.reel_unit_control = control.upper()
        self._metadata["has_reel_unit"] = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert OPEN statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "open_mode": self.open_mode,
                "file_names": self.file_names,
                "with_reposition": self.with_reposition,
                "reel_unit_control": self.reel_unit_control,  # Contract field
            }
        )
        return result


# Backward compatibility alias
OpenStatement = IOOpenStatement


class IOCloseStatement(CobolStatement):
    """AST node for CLOSE statements with comprehensive IO variation support.

    Supports:
    - Multiple file closes in single statement
    - REEL/UNIT for tape files
    - WITH NO REWIND for tape operations
    - WITH LOCK for exclusive close
    """

    def __init__(self, location: SourceLocation):
        super().__init__("CLOSE", location)
        self.file_names: List[str] = []
        self.close_options: Dict[str, Any] = {}  # reel, unit, no_rewind, with_lock
        self._metadata = {
            "has_lock": False,
            "has_reel_unit": False,
        }

    def add_file(
        self,
        file_name: str,
        reel: bool = False,
        unit: bool = False,
        no_rewind: bool = False,
        with_lock: bool = False,
    ) -> None:
        """Add a file to close with options."""
        if file_name not in self.file_names:
            self.file_names.append(file_name)
            self.operands.append(file_name)
            self.close_options[file_name] = {
                "reel": reel,
                "unit": unit,
                "no_rewind": no_rewind,
                "with_lock": with_lock,
            }
            if with_lock:
                self._metadata["has_lock"] = True
            if reel or unit:
                self._metadata["has_reel_unit"] = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert CLOSE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_names": self.file_names,
                "close_options": self.close_options,
            }
        )
        return result


# Backward compatibility alias
CloseStatement = IOCloseStatement


class IOAcceptStatement(CobolStatement):
    """AST node for ACCEPT statements with comprehensive IO variation support.

    Supports:
    - FROM keyword variations (CONSOLE, DISPLAY, COMMAND-LINE, etc.)
    - AT LINE/COLUMN positioning
    - WITH CURSOR positioning
    - COLOR specification
    - BEEP for audible alert
    - NO ECHO for password input
    - RETURN-CODE and ENVIRONMENT-NAME
    - DATE/TIME intrinsics
    """

    def __init__(self, location: SourceLocation):
        super().__init__("ACCEPT", location)
        self.target: Optional[str] = None
        self.from_source: Optional[str] = (
            None  # CONSOLE, DISPLAY, COMMAND-LINE, DATE, TIME, etc.
        )
        self.environment_name: Optional[str] = None  # Contract field
        self.at_line: Optional[int] = None
        self.at_column: Optional[int] = None
        self.with_cursor: bool = False
        self.color_attribute: Optional[str] = None
        self.with_beep: bool = False
        self.with_no_echo: bool = False
        self._metadata = {
            "has_environment_name": False,
            "has_position": False,
        }

    def set_target(self, name: str) -> None:
        """Set the accept target variable."""
        self.target = name
        if name not in self.operands:
            self.operands.append(name)

    def set_from(self, source: str) -> None:
        """Set the FROM source."""
        self.from_source = source.upper()

    def set_environment_name(self, name: str) -> None:
        """Set the ENVIRONMENT-NAME for FROM ENVIRONMENT clause (contract field)."""
        self.environment_name = name
        self._metadata["has_environment_name"] = True

    def set_position(
        self, line: Optional[int] = None, column: Optional[int] = None
    ) -> None:
        """Set the position (AT LINE/COLUMN)."""
        self.at_line = line
        self.at_column = column
        if line is not None or column is not None:
            self._metadata["has_position"] = True

    def set_cursor(self, with_cursor: bool = True) -> None:
        """Set the WITH CURSOR flag."""
        self.with_cursor = with_cursor

    def set_color(self, attribute: str) -> None:
        """Set the COLOR attribute."""
        self.color_attribute = attribute

    def set_beep(self, with_beep: bool = True) -> None:
        """Set the BEEP flag."""
        self.with_beep = with_beep

    def set_no_echo(self, with_no_echo: bool = True) -> None:
        """Set the NO ECHO flag."""
        self.with_no_echo = with_no_echo

    def to_dict(self) -> Dict[str, Any]:
        """Convert ACCEPT statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "target": self.target,
                "from_source": self.from_source,
                "environment_name": self.environment_name,  # Contract field
                "at_line": self.at_line,
                "at_column": self.at_column,
                "with_cursor": self.with_cursor,
                "color_attribute": self.color_attribute,
                "with_beep": self.with_beep,
                "with_no_echo": self.with_no_echo,
            }
        )
        return result


# Backward compatibility alias
AcceptStatement = IOAcceptStatement


class IORewriteStatement(CobolStatement):
    """IBM Enterprise COBOL REWRITE statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("REWRITE_STATEMENT", location)
        self.file_name: Optional[str] = None
        self.record_name: Optional[str] = None
        self.invalid_key_clause: List["CobolStatement"] = []
        self.not_invalid_key_clause: List["CobolStatement"] = []
        self.with_lock: bool = False
        self._metadata = {
            "has_invalid_key": False,
            "uses_lock": False,
        }

    def set_file_name(self, file_name: str) -> None:
        """Set the file name."""
        self.file_name = file_name

    def set_record_name(self, record_name: str) -> None:
        """Set the record name to rewrite."""
        self.record_name = record_name
        if record_name not in self.operands:
            self.operands.append(record_name)

    def set_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self._metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def set_lock(self, with_lock: bool = True) -> None:
        """Set the LOCK flag."""
        self.with_lock = with_lock
        if with_lock:
            self._metadata["uses_lock"] = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert REWRITE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_name": self.record_name,
                "invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.not_invalid_key_clause or [])
                ],
                "with_lock": self.with_lock,
            }
        )
        return result


# Backward compatibility alias
RewriteStatement = IORewriteStatement


class IODeleteStatement(CobolStatement):
    """IBM Enterprise COBOL DELETE statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("DELETE_STATEMENT", location)
        self.file_name: Optional[str] = None
        self.invalid_key_clause: List["CobolStatement"] = []
        self.not_invalid_key_clause: List["CobolStatement"] = []
        self.with_lock: bool = False
        self._metadata = {
            "has_invalid_key": False,
            "uses_lock": False,
        }

    def set_file_name(self, file_name: str) -> None:
        """Set the file name."""
        self.file_name = file_name

    def set_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self._metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def set_lock(self, with_lock: bool = True) -> None:
        """Set the LOCK flag."""
        self.with_lock = with_lock
        if with_lock:
            self._metadata["uses_lock"] = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert DELETE statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.not_invalid_key_clause or [])
                ],
                "with_lock": self.with_lock,
            }
        )
        return result


# Backward compatibility alias
DeleteStatement = IODeleteStatement


class IOStartStatement(CobolStatement):
    """IBM Enterprise COBOL START statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("START_STATEMENT", location)
        self.file_name: Optional[str] = None
        self.key_condition: Optional[str] = (
            None  # EQUAL, GREATER, LESS, GREATER THAN, etc.
        )
        self.invalid_key_clause: List["CobolStatement"] = []
        self.not_invalid_key_clause: List["CobolStatement"] = []
        self._metadata = {
            "has_invalid_key": False,
        }

    def set_file_name(self, file_name: str) -> None:
        """Set the file name."""
        self.file_name = file_name

    def set_key_condition(self, condition: str) -> None:
        """Set the key condition (EQUAL, GREATER, LESS, etc.)."""
        self.key_condition = condition.upper()

    def set_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the INVALID KEY clause."""
        self.invalid_key_clause = statements
        if statements:
            self._metadata["has_invalid_key"] = True

    def set_not_invalid_key_clause(self, statements: List["CobolStatement"]) -> None:
        """Set the NOT INVALID KEY clause."""
        self.not_invalid_key_clause = statements

    def to_dict(self) -> Dict[str, Any]:
        """Convert START statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "key_condition": self.key_condition,
                "invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.invalid_key_clause or [])
                ],
                "not_invalid_key_clause": [
                    s.to_dict() if hasattr(s, "to_dict") else s
                    for s in (self.not_invalid_key_clause or [])
                ],
            }
        )
        return result


# Backward compatibility alias
StartStatement = IOStartStatement


class IOUnlockStatement(CobolStatement):
    """IBM Enterprise COBOL UNLOCK statement AST node."""

    def __init__(self, location: SourceLocation):
        super().__init__("UNLOCK_STATEMENT", location)
        self.file_name: Optional[str] = None
        self.record_scope: Optional[str] = None  # 'record' or 'file'
        self._metadata = {
            "has_record_scope": False,
        }

    def set_file_name(self, file_name: str) -> None:
        """Set the file name."""
        self.file_name = file_name

    def set_record_scope(self, scope: str) -> None:
        """Set the record scope (RECORD or FILE)."""
        self.record_scope = scope.upper()
        self._metadata["has_record_scope"] = True

    def to_dict(self) -> Dict[str, Any]:
        """Convert UNLOCK statement to dictionary representation per contract."""
        result = super().to_dict()
        result.update(
            {
                "file_name": self.file_name,
                "record_scope": self.record_scope,
            }
        )
        return result


# Backward compatibility alias
UnlockStatement = IOUnlockStatement


# Import the base classes for procedure elements
from .program import CobolParagraph, CobolSection

# Aliases for procedure-specific elements
ProcedureParagraph = CobolParagraph
ProcedureSection = CobolSection

# Module exports
__all__ = [
    "CobolStatement",
    "MoveStatement",
    "DisplayStatement",
    "PerformStatement",
    "IfStatement",
    "CallStatement",
    "EntryStatement",
    "ComputeStatement",
    "CopyStatement",
    "SelectStatement",
    # IO Statement Classes (Contract-based names)
    "IOReadStatement",
    "IOWriteStatement",
    "IOOpenStatement",
    "IOCloseStatement",
    "IOAcceptStatement",
    "IORewriteStatement",
    "IODeleteStatement",
    "IOStartStatement",
    "IOUnlockStatement",
    # Backward compatibility aliases
    "ReadStatement",
    "WriteStatement",
    "OpenStatement",
    "CloseStatement",
    "AcceptStatement",
    "RewriteStatement",
    "DeleteStatement",
    "StartStatement",
    "UnlockStatement",
    # Other exports
    "CobolExpression",
    "ArithmeticExpression",
    "ConditionalExpression",
    "ProcedureParagraph",
    "ProcedureSection",
]
