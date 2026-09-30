"""
Value tracking analyzer for dynamic CALL statements.

This module provides analysis capabilities to track possible values for
variables used in dynamic CALL statements by analyzing MOVE statements
and initial VALUE clauses in data definitions.
"""

from ..models.ast_base import ASTNode
from ..models.data_items import CobolDataItem
from ..models.program import CobolDivision, CobolProgram
from ..models.statements import CallStatement, MoveStatement
from ._names import base_data_name


class DynamicCallAnalyzer:
    """Analyzer for tracking possible values in dynamic CALL statements.

    This analyzer traverses the AST to:
    1. Find all dynamic CALL statements (using variables)
    2. Track MOVE statements that assign values to those variables
    3. Track initial VALUE clauses in data definitions
    4. Populate the possible_values list for each dynamic CALL

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis import DynamicCallAnalyzer

        result = parse_cobol(cobol_source)
        analyzer = DynamicCallAnalyzer()
        analyzer.analyze(result.ast)

        # Now CallStatement nodes have populated possible_values
        for call in result.ast.find_statements("CALL"):
            if call.is_dynamic:
                print(f"Dynamic call to {call.called_program}")
                print(f"Possible values: {call.possible_values}")
        ```
    """

    def __init__(self) -> None:
        """Initialize the value tracker."""
        self._variable_values: dict[str, set[str]] = {}
        # Variables whose tracked value set is known to be INCOMPLETE: they
        # received a MOVE from an identifier-shaped source this analyzer does
        # not track (e.g. `MOVE WS-INPUT-PROG TO WS-TARGET` where
        # WS-INPUT-PROG has no VALUE clause and no tracked MOVE). Recording
        # the source's own *name* as a possible value -- the old behavior --
        # polluted the value set with a data-name that is not a value at all.
        self._incomplete_variables: set[str] = set()
        self._dynamic_calls: list[CallStatement] = []

    def analyze(self, ast: CobolProgram) -> None:
        """Analyze AST and populate possible values for dynamic CALL statements.

        Args:
            ast: The parsed COBOL program AST
        """
        # Reset state
        self._variable_values = {}
        self._incomplete_variables = set()
        self._dynamic_calls = []

        # First pass: collect initial values from data definitions
        self._collect_initial_values(ast)

        # Second pass: track MOVE statements
        self._track_move_statements(ast)

        # Every other way a CALL variable's storage can change (ACCEPT,
        # STRING/UNSTRING INTO, INITIALIZE, READ INTO, CALL ... USING, a
        # MOVE to its group or a subordinate item) supplies a value this
        # analyzer cannot know -- the value set is incomplete, not exact.
        self._mark_untracked_writes(ast)

        # Third pass: find dynamic CALL statements and populate values
        self._populate_dynamic_calls(ast)

    def _collect_initial_values(self, node: ASTNode) -> None:
        """Collect initial values from VALUE clauses in data items."""
        if isinstance(node, CobolDataItem):
            # Check if this data item has an initial value
            if node.value_clause is not None:
                var_name = node.name.upper() if node.name else None
                if var_name:
                    if var_name not in self._variable_values:
                        self._variable_values[var_name] = set()
                    # Route through the same literal-resolution path as MOVE
                    # sources so a figurative constant (VALUE SPACES, VALUE
                    # ZERO, ...) collapses to one canonical value instead of
                    # surviving as its own raw keyword text alongside the
                    # resolved value a MOVE of the same constant would add
                    # (e.g. both "SPACES" and " " for the same variable).
                    value = self._extract_literal_value(str(node.value_clause))
                    if value is None:
                        value = str(node.value_clause).strip("\"'")
                    self._variable_values[var_name].add(value)

        # Recursively process children
        if hasattr(node, "children"):
            for child in node.children:
                self._collect_initial_values(child)

    def _track_move_statements(self, node: ASTNode) -> None:
        """Track MOVE statements to collect possible values for variables."""
        if isinstance(node, MoveStatement):
            # Get source and target(s)
            source = node.source
            targets = node.targets

            # A reference-modified receiver (``WS-PROG(1:4)``) only
            # overwrites part of the item: the MOVE's value is not the
            # item's value, and what the rest holds is not known here.
            partial = [t for t in targets if ":" in t]
            for target in partial:
                self._incomplete_variables.add(base_data_name(target).upper())
            targets = [t for t in targets if ":" not in t]

            if source and targets:
                # A qualified/subscripted reference string ("WS-PROG OF
                # GRP-1") is keyed by its base data name -- a later bare
                # `CALL WS-PROG` looks the variable up by that bare name,
                # so keying the folded string would silently miss it.
                source_upper = base_data_name(source).upper()

                # Check if source is a known variable (propagate its values)
                if source_upper in self._variable_values:
                    source_values = self._variable_values[source_upper]
                    source_incomplete = source_upper in self._incomplete_variables
                    for target in targets:
                        target_name = base_data_name(target).upper()
                        if target_name not in self._variable_values:
                            self._variable_values[target_name] = set()
                        self._variable_values[target_name].update(source_values)
                        if source_incomplete:
                            self._incomplete_variables.add(target_name)
                elif self._is_definite_literal(source):
                    # A quoted string, numeric literal, or figurative
                    # constant: an actual value, safe to record.
                    source_value = self._extract_literal_value(source)

                    if source_value:
                        for target in targets:
                            target_name = base_data_name(target).upper()
                            if target_name not in self._variable_values:
                                self._variable_values[target_name] = set()
                            self._variable_values[target_name].add(source_value)
                else:
                    # Identifier-shaped source with no tracked values: the
                    # target now holds a value this analyzer cannot know.
                    # Recording the source's NAME as a value would pollute
                    # the set (`MOVE WS-INPUT-PROG TO WS-TARGET` is not a
                    # MOVE of the literal "WS-INPUT-PROG") -- instead the
                    # target's value set is marked incomplete, surfaced on
                    # dynamic CALL nodes via the
                    # "possible_values_incomplete" metadata flag.
                    for target in targets:
                        self._incomplete_variables.add(base_data_name(target).upper())

        # Recursively process children
        if hasattr(node, "children"):
            for child in node.children:
                self._track_move_statements(child)

    def _mark_untracked_writes(self, ast: CobolProgram) -> None:
        """Mark a dynamic CALL variable incomplete when anything but a MOVE
        to the item itself writes its storage."""
        nodes = self._walk(ast)
        call_vars = {
            call.called_program.upper()
            for call in nodes
            if isinstance(call, CallStatement)
            and call.is_dynamic
            and call.called_program
        }
        if not call_vars:
            return
        # Imported here: xref imports the analysis package's siblings.
        from .xref import ROLE_CALL_ARGUMENT, ROLE_WRITE, XrefAnalyzer

        overlapping = self._overlapping_names(
            [node for node in nodes if isinstance(node, CobolDataItem)]
        )
        # The cross-reference needs a parsed PROCEDURE DIVISION to walk; a
        # hand-built node tree without one has only the MOVEs below.
        has_procedure = isinstance(
            getattr(ast, "procedure_division", None), CobolDivision
        )
        report = XrefAnalyzer().analyze(ast) if has_procedure else None
        for var in call_vars:
            for name in {var} | overlapping.get(var, set()):
                entry = report.entry_for(name) if report is not None else None
                if entry is None:
                    continue
                for ref in entry.references:
                    if ref.role not in (ROLE_WRITE, ROLE_CALL_ARGUMENT):
                        continue
                    if ref.statement == "MoveStatement":
                        # Read off the MOVE itself below: xref also records
                        # an OF/IN qualifier as written, which is not a
                        # write to the group.
                        continue
                    self._incomplete_variables.add(var)
        for move in nodes:
            if not isinstance(move, MoveStatement):
                continue
            for target in move.targets:
                written = base_data_name(target).upper()
                for var in call_vars:
                    if written in overlapping.get(var, ()):
                        self._incomplete_variables.add(var)

    @staticmethod
    def _walk(root: ASTNode) -> list[ASTNode]:
        """Every node under *root* (the same ``children`` walk the other
        passes make)."""
        found: list[ASTNode] = []
        stack = [root]
        while stack:
            node = stack.pop()
            found.append(node)
            stack.extend(reversed(list(getattr(node, "children", None) or [])))
        return found

    @staticmethod
    def _overlapping_names(items: list[CobolDataItem]) -> dict[str, set[str]]:
        """Item name -> names of the items sharing its storage: its group
        ancestors and subordinate items."""
        overlapping: dict[str, set[str]] = {}

        def walk(item: CobolDataItem, ancestors: list[str]) -> None:
            name = (item.name or "").upper()
            for child in item.children:
                if isinstance(child, CobolDataItem):
                    walk(child, [*ancestors, name] if name else ancestors)
            if not name:
                return
            related = overlapping.setdefault(name, set())
            related.update(ancestors)
            for ancestor in ancestors:
                overlapping.setdefault(ancestor, set()).add(name)

        for item in items:
            if item.level in (1, 77):
                walk(item, [])
        for name, related in overlapping.items():
            related.discard(name)
        return overlapping

    def _populate_dynamic_calls(self, node: ASTNode) -> None:
        """Find dynamic CALL statements and populate their possible values."""
        if isinstance(node, CallStatement):
            if node.is_dynamic and node.called_program:
                # Look up the variable name in our tracked values
                var_name = node.called_program.upper()
                if var_name in self._variable_values:
                    # Populate the possible values
                    values = sorted(self._variable_values[var_name])
                    node.set_possible_values(values)
                if var_name in self._incomplete_variables:
                    # The variable also received at least one value this
                    # analyzer could not resolve, so possible_values (even
                    # when populated) is not exhaustive.
                    node.set_metadata("possible_values_incomplete", True)

        # Recursively process children
        if hasattr(node, "children"):
            for child in node.children:
                self._populate_dynamic_calls(child)

    @staticmethod
    def _is_definite_literal(source: str) -> bool:
        """True only for a source that is certainly a VALUE, never a name:
        a quoted string literal, a numeric literal, or a figurative constant.

        An identifier-shaped source (``PROGRAM-A``, ``WS-INPUT-PROG``) is NOT
        definite -- the parser keeps quotes on ``MoveStatement.source``, so an
        unquoted hyphenated token is a data-name reference, not a literal.
        ``_track_move_statements`` uses this gate before recording a value;
        sources failing it mark the target's value set incomplete instead.
        """
        if not source:
            return False
        s = source.strip()
        if len(s) >= 2 and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
            return True
        if s and s.replace("-", "").replace("+", "").replace(".", "").isdigit():
            return True
        return s.upper() in (
            "ZERO",
            "ZEROS",
            "ZEROES",
            "SPACE",
            "SPACES",
            "LOW-VALUE",
            "LOW-VALUES",
            "HIGH-VALUE",
            "HIGH-VALUES",
        )

    def _extract_literal_value(self, source: str) -> str | None:
        """Extract literal value from source string.

        Note: the trailing identifier-shaped fallback below is deliberately
        permissive (it echoes back any name-shaped token); callers recording
        values must first gate on :meth:`_is_definite_literal` so a bare
        data-name is never recorded as if it were a value.

        Args:
            source: Source string that might be a literal

        Returns:
            The literal value without quotes, or None if not a literal
        """
        if not source:
            return None

        source = source.strip()

        # Check for string literals (quoted)
        if (source.startswith('"') and source.endswith('"')) or (
            source.startswith("'") and source.endswith("'")
        ):
            return source[1:-1]

        # Check for numeric literals
        if source.replace("-", "").replace("+", "").replace(".", "").isdigit():
            return source

        # Check for ZERO/ZEROS/ZEROES, SPACE/SPACES
        upper_source = source.upper()
        if upper_source in ("ZERO", "ZEROS", "ZEROES"):
            return "0"
        if upper_source in ("SPACE", "SPACES"):
            return " "
        if upper_source in ("LOW-VALUE", "LOW-VALUES"):
            return "\x00"
        if upper_source in ("HIGH-VALUE", "HIGH-VALUES"):
            return "\xff"

        # If the source contains a hyphen and doesn't match a known figurative constant,
        # it's likely an unquoted string literal (parser strips quotes from STRING_LITERAL tokens)
        # Examples: PROGRAM-A, SUB-PROG, MY-VALUE
        # We treat any alphanumeric string with hyphens as a potential literal value
        if "-" in source or source.replace("-", "").isalnum():
            # Only treat it as a literal if it's not already tracked as a variable
            # (this check happens in the caller)
            return source

        # Not a literal
        return None

    def get_variable_values(self, variable_name: str) -> list[str]:
        """Get all tracked values for a specific variable.

        Args:
            variable_name: Name of the variable to look up

        Returns:
            List of possible values for the variable
        """
        var_name = variable_name.upper()
        if var_name in self._variable_values:
            return sorted(self._variable_values[var_name])
        return []

    def get_all_tracked_variables(self) -> list[str]:
        """Get names of all variables being tracked.

        Returns:
            List of variable names that have tracked values
        """
        return sorted(self._variable_values.keys())
