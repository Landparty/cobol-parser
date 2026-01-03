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
            "metadata": self._metadata
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
        result.update({
            "source": self.source,
            "targets": self.targets,
            "is_corresponding": self.is_corresponding
        })
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
        result.update({
            "display_items": self.display_items,
            "output_device": self.output_device
        })
        return result


class PerformStatement(CobolStatement):
    """AST node for PERFORM statements."""
    
    def __init__(self, location: SourceLocation):
        super().__init__("PERFORM", location)
        self.target_paragraph: Optional[str] = None
        self.perform_type: str = "SIMPLE"  # SIMPLE, TIMES, UNTIL, VARYING
        self.times_count: Optional[int] = None
        self.until_condition: Optional['CobolExpression'] = None
        self.varying_clause: Optional[Dict[str, Any]] = None
        self.inline_statements: List['CobolStatement'] = []
    
    def set_target_paragraph(self, paragraph: str) -> None:
        """Set the target paragraph to perform."""
        self.target_paragraph = paragraph
        if paragraph not in self.operands:
            self.operands.insert(0, paragraph)
    
    def set_times_clause(self, count: int) -> None:
        """Set TIMES clause for the PERFORM."""
        self.perform_type = "TIMES"
        self.times_count = count
    
    def set_until_clause(self, condition: 'CobolExpression') -> None:
        """Set UNTIL clause for the PERFORM."""
        self.perform_type = "UNTIL"
        self.until_condition = condition
        self.add_child(condition)
    
    def set_varying_clause(self, variable: str, from_value: str, by_value: str, until_condition: 'CobolExpression') -> None:
        """Set VARYING clause for the PERFORM."""
        self.perform_type = "VARYING"
        self.varying_clause = {
            "variable": variable,
            "from_value": from_value,
            "by_value": by_value
        }
        self.until_condition = until_condition
        self.add_child(until_condition)
    
    def add_inline_statement(self, statement: 'CobolStatement') -> None:
        """Add a statement to the inline block of this PERFORM."""
        self.inline_statements.append(statement)
        self.add_child(statement)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert PERFORM statement to dictionary representation."""
        result = super().to_dict()
        result.update({
            "target_paragraph": self.target_paragraph,
            "perform_type": self.perform_type,
            "times_count": self.times_count,
            "until_condition": self.until_condition.to_dict() if self.until_condition else None,
            "varying_clause": self.varying_clause,
            "inline_statements": [stmt.to_dict() for stmt in self.inline_statements]
        })
        return result


class IfStatement(CobolStatement):
    """AST node for IF statements with conditional branches."""
    
    def __init__(self, location: SourceLocation):
        super().__init__("IF", location)
        self.condition: Optional['CobolExpression'] = None
        self.then_statements: List['CobolStatement'] = []
        self.else_statements: List['CobolStatement'] = []
    
    def set_condition(self, condition: 'CobolExpression') -> None:
        """Set the IF condition."""
        self.condition = condition
        self.add_child(condition)
    
    def add_then_statement(self, statement: 'CobolStatement') -> None:
        """Add a statement to the THEN branch."""
        self.then_statements.append(statement)
        self.add_child(statement)
    
    def add_else_statement(self, statement: 'CobolStatement') -> None:
        """Add a statement to the ELSE branch."""
        self.else_statements.append(statement)
        self.add_child(statement)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert IF statement to dictionary representation."""
        result = super().to_dict()
        result.update({
            "condition": self.condition.to_dict() if self.condition else None,
            "then_statements": [stmt.to_dict() for stmt in self.then_statements],
            "else_statements": [stmt.to_dict() for stmt in self.else_statements]
        })
        return result


class StopStatement(CobolStatement):
    """AST node for STOP RUN statements."""
    
    def __init__(self, location: SourceLocation):
        super().__init__("STOP", location)
        self.stop_type: str = "RUN"  # RUN or literal
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert STOP statement to dictionary representation."""
        result = super().to_dict()
        result.update({
            "stop_type": self.stop_type
        })
        return result


class ComputeStatement(CobolStatement):
    """AST node for COMPUTE statements."""
    
    def __init__(self, location: SourceLocation):
        super().__init__("COMPUTE", location)
        self.targets: List[str] = []
        self.expression: Optional['CobolExpression'] = None
    
    def add_target(self, target: str) -> None:
        """Add a target variable for the computation."""
        self.targets.append(target)
        if target not in self.operands:
            self.operands.append(target)
    
    def set_expression(self, expression: 'CobolExpression') -> None:
        """Set the arithmetic expression for the computation."""
        self.expression = expression
        self.add_child(expression)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert COMPUTE statement to dictionary representation."""
        result = super().to_dict()
        result.update({
            "targets": self.targets,
            "expression": self.expression.to_dict() if self.expression else None
        })
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
        self.on_overflow: Optional[List['CobolStatement']] = None
        self.on_exception: Optional[List['CobolStatement']] = None
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
        base.update({
            "called_program": self.called_program,
            "using_parameters": [
                {"name": p.name, "mode": p.passing_mode} 
                for p in self.using_parameters
            ],
            "giving_parameter": self.giving_parameter,
            "returning_parameter": self.returning_parameter,
            "is_dynamic": self.is_dynamic,
            "possible_values": self.possible_values
        })
        # Add exception handlers if present
        if self.on_overflow:
            base["on_overflow"] = [s.to_dict() for s in self.on_overflow]
        if self.on_exception:
            base["on_exception"] = [s.to_dict() for s in self.on_exception]
            
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
        self.organization: Optional[str] = None  # SEQUENTIAL, INDEXED, RELATIVE, LINE SEQUENTIAL
        
        # ACCESS MODE clause
        self.access_mode: Optional[str] = None  # SEQUENTIAL, RANDOM, DYNAMIC
        
        # RECORD KEY clause
        self.record_key: Optional[str] = None
        self.record_key_source: Optional[str] = None  # SOURCE IS data-name (IBM extension)
        
        # ALTERNATE RECORD KEY clause(s)
        self.alternate_keys: List[Dict[str, Any]] = []  # [{key, duplicates_allowed, password}]
        
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
    
    def set_assign_to(self, assign_value: str, device_type: Optional[str] = None,
                      external_name: Optional[str] = None) -> None:
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
    
    def add_alternate_key(self, key: str, duplicates_allowed: bool = False,
                          password: Optional[str] = None) -> None:
        """Add an ALTERNATE RECORD KEY clause."""
        self.alternate_keys.append({
            'key': key,
            'duplicates_allowed': duplicates_allowed,
            'password': password
        })
    
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
    
    def set_lock_mode(self, mode: str, lock_on: Optional[str] = None,
                      with_rollback: bool = False) -> None:
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
        result.update({
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
            "sharing_mode": self.sharing_mode
        })
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
        self.replacements.append({
            "old_text": old_text,
            "new_text": new_text
        })
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert COPY statement to dictionary representation."""
        result = super().to_dict()
        result.update({
            "copybook_name": self.copybook_name,
            "library_name": self.library_name,
            "suppressions": self.suppressions,
            "replacements": self.replacements
        })
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
            "metadata": self._metadata
        }


class ArithmeticExpression(CobolExpression):
    """AST node for arithmetic expressions."""
    
    def __init__(self, operator: str, location: SourceLocation):
        super().__init__("ARITHMETIC", location)
        self.operator = operator
        self.left_operand: Optional[Union[str, 'CobolExpression']] = None
        self.right_operand: Optional[Union[str, 'CobolExpression']] = None
    
    def set_left_operand(self, operand: Union[str, 'CobolExpression']) -> None:
        """Set the left operand of the expression."""
        self.left_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)
    
    def set_right_operand(self, operand: Union[str, 'CobolExpression']) -> None:
        """Set the right operand of the expression."""
        self.right_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert arithmetic expression to dictionary representation."""
        result = super().to_dict()
        
        left_dict = self.left_operand.to_dict() if isinstance(self.left_operand, CobolExpression) else self.left_operand
        right_dict = self.right_operand.to_dict() if isinstance(self.right_operand, CobolExpression) else self.right_operand
        
        result.update({
            "operator": self.operator,
            "left_operand": left_dict,
            "right_operand": right_dict
        })
        return result


class ConditionalExpression(CobolExpression):
    """AST node for conditional expressions."""
    
    def __init__(self, operator: str, location: SourceLocation):
        super().__init__("COMPARISON", location)
        self.operator = operator
        self.left_operand: Optional[Union[str, 'CobolExpression']] = None
        self.right_operand: Optional[Union[str, 'CobolExpression']] = None
    
    @property
    def condition_type(self) -> str:
        """Return the condition type."""
        return self.expression_type
    
    def set_left_operand(self, operand: Union[str, 'CobolExpression']) -> None:
        """Set the left operand of the condition."""
        self.left_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)
    
    def set_right_operand(self, operand: Union[str, 'CobolExpression']) -> None:
        """Set the right operand of the condition."""
        self.right_operand = operand
        if isinstance(operand, CobolExpression):
            self.add_child(operand)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert conditional expression to dictionary representation."""
        result = super().to_dict()
        
        left_dict = self.left_operand.to_dict() if isinstance(self.left_operand, CobolExpression) else self.left_operand
        right_dict = self.right_operand.to_dict() if isinstance(self.right_operand, CobolExpression) else self.right_operand
        
        result.update({
            "operator": self.operator,
            "left_operand": left_dict,
            "right_operand": right_dict,
            "condition_type": self.condition_type
        })
        return result


class LogicalExpression(CobolExpression):
    """AST node for logical expressions (AND, OR, NOT)."""
    
    def __init__(self, operator: str, location: SourceLocation):
        super().__init__("LOGICAL", location)
        self.operator = operator
        self.left_condition: Optional['CobolExpression'] = None
        self.right_condition: Optional['CobolExpression'] = None
    
    def set_left_condition(self, condition: 'CobolExpression') -> None:
        """Set the left condition of the logical expression."""
        self.left_condition = condition
        self.add_child(condition)
    
    def set_right_condition(self, condition: 'CobolExpression') -> None:
        """Set the right condition of the logical expression."""
        self.right_condition = condition
        self.add_child(condition)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert logical expression to dictionary representation."""
        result = super().to_dict()
        result.update({
            "operator": self.operator,
            "left_condition": self.left_condition.to_dict() if self.left_condition else None,
            "right_condition": self.right_condition.to_dict() if self.right_condition else None
        })
        return result


class FunctionCall(CobolExpression):
    """AST node for COBOL function calls."""
    
    def __init__(self, function_name: str, location: SourceLocation):
        super().__init__("FUNCTION", location)
        self.function_name = function_name
        self.function_type = "INTRINSIC"  # INTRINSIC or USER_DEFINED
        self.arguments: List[Union[str, 'CobolExpression']] = []
    
    def add_argument(self, argument: Union[str, 'CobolExpression']) -> None:
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
        
        result.update({
            "function_name": self.function_name,
            "function_type": self.function_type,
            "arguments": args_dict
        })
        return result


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
    "ComputeStatement",
    "CopyStatement",
    "SelectStatement",
    "CobolExpression",
    "ArithmeticExpression",
    "ConditionalExpression",
    "ProcedureParagraph",
    "ProcedureSection",
]