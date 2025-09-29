"""
COBOL statement and expression AST nodes.

This module implements AST nodes for COBOL statements, expressions,
and control flow constructs with full functionality.
"""

from typing import Dict, Any, List, Optional, Union
from .ast_base import ASTNode, SourceLocation


class CobolStatement(ASTNode):
    """Base class for COBOL statement AST nodes."""
    
    def __init__(self, statement_type: str, location: SourceLocation):
        super().__init__("Statement", location)
        self.statement_type = statement_type
        self.operands: List[str] = []
    
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
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert PERFORM statement to dictionary representation."""
        result = super().to_dict()
        result.update({
            "target_paragraph": self.target_paragraph,
            "perform_type": self.perform_type,
            "times_count": self.times_count,
            "until_condition": self.until_condition.to_dict() if self.until_condition else None,
            "varying_clause": self.varying_clause
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


class CallStatement(CobolStatement):
    """AST node for CALL statements."""
    
    def __init__(self, location: SourceLocation):
        super().__init__("CALL", location)
        self.called_program: Optional[str] = None
        self.using_parameters: List[str] = []
        self.giving_parameter: Optional[str] = None
        self.on_overflow: Optional[List['CobolStatement']] = None
        self.on_exception: Optional[List['CobolStatement']] = None
    
    def set_called_program(self, program: str) -> None:
        """Set the program name being called."""
        self.called_program = program
        if program not in self.operands:
            self.operands.insert(0, program)
    
    def add_using_parameter(self, parameter: str) -> None:
        """Add a parameter to the USING clause."""
        self.using_parameters.append(parameter)
        if parameter not in self.operands:
            self.operands.append(parameter)
    
    def set_giving_parameter(self, parameter: str) -> None:
        """Set the GIVING parameter."""
        self.giving_parameter = parameter
        if parameter not in self.operands:
            self.operands.append(parameter)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert CALL statement to dictionary representation."""
        result = super().to_dict()
        result.update({
            "called_program": self.called_program,
            "using_parameters": self.using_parameters,
            "giving_parameter": self.giving_parameter
        })
        return result


class SelectStatement(CobolStatement):
    """AST node for SELECT statements in FILE-CONTROL paragraph."""
    
    def __init__(self, location: SourceLocation):
        super().__init__("SELECT", location)
        self.file_name: Optional[str] = None
        self.assign_to: Optional[str] = None
        self.organization: Optional[str] = None
        self.access_mode: Optional[str] = None
        self.file_status: Optional[str] = None
    
    def set_file_name(self, name: str) -> None:
        """Set the file name being selected."""
        self.file_name = name
        if name not in self.operands:
            self.operands.insert(0, name)
    
    def set_assign_to(self, assign_value: str) -> None:
        """Set the ASSIGN TO clause value."""
        self.assign_to = assign_value
        if assign_value not in self.operands:
            self.operands.append(assign_value)
    
    def set_organization(self, org: str) -> None:
        """Set the ORGANIZATION clause."""
        self.organization = org
    
    def set_access_mode(self, mode: str) -> None:
        """Set the ACCESS MODE clause."""
        self.access_mode = mode
    
    def set_file_status(self, status: str) -> None:
        """Set the FILE STATUS clause."""
        self.file_status = status
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert SELECT statement to dictionary representation."""
        result = super().to_dict()
        result.update({
            "file_name": self.file_name,
            "assign_to": self.assign_to,
            "organization": self.organization,
            "access_mode": self.access_mode,
            "file_status": self.file_status
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
    "CallStatement",
    "ComputeStatement",
    "CobolExpression",
    "ArithmeticExpression",
    "ConditionalExpression",
    "ProcedureParagraph",
    "ProcedureSection",
]