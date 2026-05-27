"""
Base AST node classes and source location tracking for COBOL parser.

This module provides the foundation for the Abstract Syntax Tree representation
of parsed COBOL programs, including node hierarchy and navigation.
"""

import json
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any, Optional, TypeVar


@dataclass(slots=True)
class SourceLocation:
    """Source code location information with line and column tracking."""

    line: int
    column: int
    length: int | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        result = {"line": self.line, "column": self.column}
        if self.length is not None:
            result["length"] = self.length
        return result

    def __str__(self) -> str:
        if self.length is not None:
            return f"Line {self.line}, Column {self.column} (length {self.length})"
        return f"Line {self.line}, Column {self.column}"


T = TypeVar("T", bound="ASTNode")


class ASTNode(ABC):
    """Base class for all AST nodes in the COBOL parser."""

    def __init__(self, node_type: str, location: SourceLocation):
        self.node_type = node_type
        self.location = location
        self.parent: ASTNode | None = None
        self.children: list[ASTNode] = []
        self._metadata: dict[str, Any] = {}
        self._division_name: str | None = None  # Track division context
        self._section_name: str | None = None  # Track section context
        self._type_cache: dict[str, list[ASTNode]] | None = None

    def set_division_context(
        self, division_name: str | None, section_name: str | None = None
    ) -> None:
        """Set the division and section context for this node."""
        self._division_name = division_name
        self._section_name = section_name

    @property
    def division_name(self) -> str | None:
        """Get the division this node belongs to.

        Returns the division name if set directly, otherwise traverses
        up the parent chain to find it.
        """
        # Check if this node has its own division_name attribute (like CobolDivision)
        if hasattr(self, "_own_division_name"):
            return str(self._own_division_name)

        if self._division_name:
            return self._division_name
        # Fallback: traverse up to find division
        if self.parent:
            return self.parent.division_name
        return None

    @property
    def section_name(self) -> str | None:
        """Get the section this node belongs to.

        Returns the section name if set directly, otherwise traverses
        up the parent chain to find it.
        """
        # Check if this node has its own section_name attribute (like CobolSection)
        if hasattr(self, "_own_section_name"):
            return str(self._own_section_name)

        if self._section_name:
            return self._section_name
        # Fallback: traverse up to find section
        if self.parent:
            return self.parent.section_name
        return None

    def get_division_context(self) -> dict[str, str | None]:
        """Get both division and section context."""
        return {"division": self.division_name, "section": self.section_name}

    @property
    def metadata(self) -> dict[str, Any]:
        """Get metadata dictionary for this node (lazily initialized)."""
        return self._metadata

    def _invalidate_type_cache(self) -> None:
        """Invalidate the type-index cache on this node and all ancestors."""
        node: ASTNode | None = self
        while node is not None:
            node._type_cache = None
            node = node.parent

    def add_child(self, child: "ASTNode") -> None:
        """Add a child node and set its parent reference."""
        if child.parent is not None:
            child.parent.remove_child(child)

        child.parent = self
        self.children.append(child)
        self._invalidate_type_cache()

    def remove_child(self, child: "ASTNode") -> bool:
        """Remove a child node and clear its parent reference."""
        if child in self.children:
            child.parent = None
            self.children.remove(child)
            self._invalidate_type_cache()
            return True
        return False

    def get_child_at(self, index: int) -> Optional["ASTNode"]:
        """Get child at specific index, or None if index is invalid."""
        if 0 <= index < len(self.children):
            return self.children[index]
        return None

    def get_children_by_type(self, node_type: str) -> list["ASTNode"]:
        """Get all direct children of a specific node type."""
        return [child for child in self.children if child.node_type == node_type]

    def traverse_depth_first(self) -> Iterator["ASTNode"]:
        """Traverse the AST in depth-first order starting from this node."""
        yield self
        for child in self.children:
            yield from child.traverse_depth_first()

    def traverse_breadth_first(self) -> Iterator["ASTNode"]:
        """Traverse the AST in breadth-first order starting from this node."""
        queue: deque[ASTNode] = deque([self])
        while queue:
            node = queue.popleft()
            yield node
            queue.extend(node.children)

    def find_first_by_type(self, node_type: str) -> Optional["ASTNode"]:
        """Find the first node of a specific type in the subtree."""
        for node in self.traverse_depth_first():
            if node.node_type == node_type:
                return node
        return None

    def find_all_by_type(self, node_type: str) -> list["ASTNode"]:
        """Find all nodes of a specific type in the subtree.

        Results are cached per node_type; the cache is invalidated automatically
        when children are added or removed.
        """
        if self._type_cache is None:
            self._type_cache = {}
        if node_type not in self._type_cache:
            self._type_cache[node_type] = [
                node
                for node in self.traverse_depth_first()
                if node.node_type == node_type
            ]
        return self._type_cache[node_type]

    def get_root(self) -> "ASTNode":
        """Get the root node of the AST."""
        node = self
        while node.parent is not None:
            node = node.parent
        return node

    def get_path_from_root(self) -> list["ASTNode"]:
        """Get the path from the root to this node."""
        path: list[ASTNode] = []
        node: ASTNode | None = self
        while node is not None:
            path.insert(0, node)
            node = node.parent
        return path

    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata for this node."""
        self.metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata for this node."""
        return self._metadata.get(key, default)

    def has_metadata(self, key: str) -> bool:
        """Check if node has specific metadata."""
        return key in self._metadata

    @abstractmethod
    def to_dict(self) -> dict[str, Any]:
        """Convert node to dictionary representation."""
        pass

    def to_json(self, indent: int | None = None) -> str:
        """Convert node to JSON representation."""
        return json.dumps(self.to_dict(), indent=indent)

    def equals(self, other: object) -> bool:
        """Check if this node is structurally equal to another node."""
        if not isinstance(other, ASTNode):
            return False
        if self.node_type != other.node_type or len(self.children) != len(
            other.children
        ):
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

    def __getstate__(self) -> dict[str, Any]:
        # Drop the parent back-reference and the type-index cache so pickle
        # doesn't traverse cycles or persist derived data. Parents are rebuilt
        # by relink_parents() after unpickling; _type_cache repopulates lazily.
        # The live node is not modified — __getstate__ returns a shallow copy.
        state = self.__dict__.copy()
        state["parent"] = None
        state["_type_cache"] = None
        return state

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.__dict__.update(state)


def relink_parents(root: "ASTNode") -> None:
    """Rebuild parent back-references for an AST loaded from pickle.

    Walks the tree depth-first and sets ``child.parent = node`` for every
    edge. The root's own parent is left untouched (caller's responsibility
    if the root is being grafted into a larger tree).
    """
    stack: list[ASTNode] = [root]
    while stack:
        node = stack.pop()
        for child in node.children:
            child.parent = node
            stack.append(child)


class ValidationResult:
    """Result of AST validation with errors and warnings."""

    def __init__(self) -> None:
        self.errors: list[str] = []
        self.warnings: list[str] = []

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

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "is_valid": self.is_valid,
            "errors": self.errors,
            "warnings": self.warnings,
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
        if not hasattr(node, "node_type") or not node.node_type:
            node_id = f"{type(node).__name__}@{id(node)}"
            result.add_error(f"Node missing node_type: {node_id}")

        if not hasattr(node, "location"):
            node_id = f"{type(node).__name__}@{id(node)}"
            result.add_error(f"Node missing location: {node_id}")

        # Validate children recursively
        for child in node.children:
            self._validate_node(child, result)


# Module exports
__all__ = [
    "SourceLocation",
    "ASTNode",
    "ValidationResult",
    "ASTValidator",
    "relink_parents",
]
