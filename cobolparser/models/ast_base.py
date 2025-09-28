"""
Base AST node classes and source location tracking for COBOL parser.

This module provides the foundation for the Abstract Syntax Tree representation
of parsed COBOL programs, including node hierarchy and navigation.
"""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from typing import Dict, Any, List, Optional, Iterator, TypeVar, Type


@dataclass
class SourceLocation:
    """Source code location information with line and column tracking."""
    
    line: int
    column: int
    length: Optional[int] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {"line": self.line, "column": self.column}
        if self.length is not None:
            result["length"] = self.length
        return result
    
    def __str__(self) -> str:
        if self.length is not None:
            return f"Line {self.line}, Column {self.column} (length {self.length})"
        return f"Line {self.line}, Column {self.column}"


T = TypeVar('T', bound='ASTNode')


class ASTNode(ABC):
    """Base class for all AST nodes in the COBOL parser."""
    
    def __init__(self, node_type: str, location: SourceLocation):
        self.node_type = node_type
        self.location = location
        self.parent: Optional['ASTNode'] = None
        self.children: List['ASTNode'] = []
        self._metadata: Dict[str, Any] = {}
    
    def add_child(self, child: 'ASTNode') -> None:
        """Add a child node and set its parent reference."""
        if child.parent is not None:
            child.parent.remove_child(child)
        
        child.parent = self
        self.children.append(child)
    
    def remove_child(self, child: 'ASTNode') -> bool:
        """Remove a child node and clear its parent reference."""
        if child in self.children:
            child.parent = None
            self.children.remove(child)
            return True
        return False
    
    def get_child_at(self, index: int) -> Optional['ASTNode']:
        """Get child at specific index, or None if index is invalid."""
        if 0 <= index < len(self.children):
            return self.children[index]
        return None
    
    def get_children_by_type(self, node_type: str) -> List['ASTNode']:
        """Get all direct children of a specific node type."""
        return [child for child in self.children if child.node_type == node_type]
    
    def traverse_depth_first(self) -> Iterator['ASTNode']:
        """Traverse the AST in depth-first order starting from this node."""
        yield self
        for child in self.children:
            yield from child.traverse_depth_first()
    
    def traverse_breadth_first(self) -> Iterator['ASTNode']:
        """Traverse the AST in breadth-first order starting from this node.""" 
        queue = [self]
        while queue:
            node = queue.pop(0)
            yield node
            queue.extend(node.children)
    
    def find_first_by_type(self, node_type: str) -> Optional['ASTNode']:
        """Find the first node of a specific type in the subtree."""
        for node in self.traverse_depth_first():
            if node.node_type == node_type:
                return node
        return None
    
    def find_all_by_type(self, node_type: str) -> List['ASTNode']:
        """Find all nodes of a specific type in the subtree."""
        return [node for node in self.traverse_depth_first() if node.node_type == node_type]
    
    def get_root(self) -> 'ASTNode':
        """Get the root node of the AST."""
        node = self
        while node.parent is not None:
            node = node.parent
        return node
    
    def get_path_from_root(self) -> List['ASTNode']:
        """Get the path from the root to this node."""
        path = []
        node = self
        while node is not None:
            path.insert(0, node)
            node = node.parent
        return path
    
    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata for this node."""
        self._metadata[key] = value
    
    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata for this node."""
        return self._metadata.get(key, default)
    
    def has_metadata(self, key: str) -> bool:
        """Check if node has specific metadata."""
        return key in self._metadata
    
    @abstractmethod
    def to_dict(self) -> Dict[str, Any]:
        """Convert node to dictionary representation."""
        pass
    
    def to_json(self, indent: Optional[int] = None) -> str:
        """Convert node to JSON representation."""
        return json.dumps(self.to_dict(), indent=indent)
    
    def equals(self, other: 'ASTNode') -> bool:
        """Check if this node is structurally equal to another node."""
        if not isinstance(other, ASTNode):
            return False
        
        if (self.node_type != other.node_type or 
            len(self.children) != len(other.children)):
            return False
        
        # Compare children recursively
        for i in range(len(self.children)):
            if not self.children[i].equals(other.children[i]):
                return False
        
        return True
    
    def __str__(self) -> str:
        """String representation of the node."""
        return f"{self.node_type} at {self.location}"
    
    def __repr__(self) -> str:
        """Detailed string representation of the node."""
        return f"{self.__class__.__name__}(type={self.node_type}, location={self.location}, children={len(self.children)})"


class ValidationResult:
    """Result of AST validation with errors and warnings."""
    
    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []
    
    @property
    def is_valid(self) -> bool:
        """Return True if validation passed (no errors)."""
        return len(self.errors) == 0
    
    def add_error(self, message: str) -> None:
        """Add a validation error."""
        self.errors.append(message)
    
    def add_warning(self, message: str) -> None:
        """Add a validation warning.""" 
        self.warnings.append(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings
        }


class ASTValidator:
    """Base class for AST validation logic."""
    
    def validate(self, node: ASTNode) -> ValidationResult:
        """Validate an AST node and its children."""
        result = ValidationResult()
        self._validate_node(node, result)
        return result
    
    def _validate_node(self, node: ASTNode, result: ValidationResult) -> None:
        """Validate a single node (override in subclasses)."""
        # Default validation - check for basic node structure
        if not hasattr(node, 'node_type') or not node.node_type:
            result.add_error(f"Node missing node_type: {node}")
        
        if not hasattr(node, 'location'):
            result.add_error(f"Node missing location: {node}")
        
        # Validate children recursively
        for child in node.children:
            self._validate_node(child, result)


# Module exports
__all__ = [
    "SourceLocation",
    "ASTNode", 
    "ValidationResult",
    "ASTValidator",
]