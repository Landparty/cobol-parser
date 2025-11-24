"""
Value tracking analyzer for dynamic CALL statements.

This module provides analysis capabilities to track possible values for
variables used in dynamic CALL statements by analyzing MOVE statements
and initial VALUE clauses in data definitions.
"""

from typing import Dict, List, Set, Optional
from ..models.ast_base import ASTNode
from ..models.program import CobolProgram, CobolDivision, CobolSection
from ..models.statements import CallStatement, MoveStatement
from ..models.data_items import CobolDataItem


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
    
    def __init__(self):
        """Initialize the value tracker."""
        self._variable_values: Dict[str, Set[str]] = {}
        self._dynamic_calls: List[CallStatement] = []
    
    def analyze(self, ast: CobolProgram) -> None:
        """Analyze AST and populate possible values for dynamic CALL statements.
        
        Args:
            ast: The parsed COBOL program AST
        """
        # Reset state
        self._variable_values = {}
        self._dynamic_calls = []
        
        # First pass: collect initial values from data definitions
        self._collect_initial_values(ast)
        
        # Second pass: track MOVE statements
        self._track_move_statements(ast)
        
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
                    # Store the value (remove quotes if present)
                    value = str(node.value_clause).strip('"\'')
                    self._variable_values[var_name].add(value)
        
        # Recursively process children
        if hasattr(node, 'children'):
            for child in node.children:
                self._collect_initial_values(child)
    
    def _track_move_statements(self, node: ASTNode) -> None:
        """Track MOVE statements to collect possible values for variables."""
        if isinstance(node, MoveStatement):
            # Get source and target(s)
            source = node.source
            targets = node.targets
            
            if source and targets:
                # Extract literal value from source (handle strings, numbers)
                source_value = self._extract_literal_value(source)
                
                # If source is a literal, add it to all targets
                if source_value:
                    for target in targets:
                        target_name = target.upper()
                        if target_name not in self._variable_values:
                            self._variable_values[target_name] = set()
                        self._variable_values[target_name].add(source_value)
                
                # If source is a variable, propagate its possible values
                elif source.upper() in self._variable_values:
                    source_values = self._variable_values[source.upper()]
                    for target in targets:
                        target_name = target.upper()
                        if target_name not in self._variable_values:
                            self._variable_values[target_name] = set()
                        self._variable_values[target_name].update(source_values)
        
        # Recursively process children
        if hasattr(node, 'children'):
            for child in node.children:
                self._track_move_statements(child)
    
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
        
        # Recursively process children
        if hasattr(node, 'children'):
            for child in node.children:
                self._populate_dynamic_calls(child)
    
    def _extract_literal_value(self, source: str) -> Optional[str]:
        """Extract literal value from source string.
        
        Args:
            source: Source string that might be a literal
            
        Returns:
            The literal value without quotes, or None if not a literal
        """
        if not source:
            return None
        
        source = source.strip()
        
        # Check for string literals (quoted)
        if (source.startswith('"') and source.endswith('"')) or \
           (source.startswith("'") and source.endswith("'")):
            return source[1:-1]
        
        # Check for numeric literals
        if source.replace('-', '').replace('+', '').replace('.', '').isdigit():
            return source
        
        # Check for ZERO/ZEROS/ZEROES, SPACE/SPACES
        upper_source = source.upper()
        if upper_source in ('ZERO', 'ZEROS', 'ZEROES'):
            return '0'
        if upper_source in ('SPACE', 'SPACES'):
            return ' '
        if upper_source in ('LOW-VALUE', 'LOW-VALUES'):
            return '\x00'
        if upper_source in ('HIGH-VALUE', 'HIGH-VALUES'):
            return '\xff'
        
        # Not a literal
        return None
    
    def get_variable_values(self, variable_name: str) -> List[str]:
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
    
    def get_all_tracked_variables(self) -> List[str]:
        """Get names of all variables being tracked.
        
        Returns:
            List of variable names that have tracked values
        """
        return sorted(self._variable_values.keys())
