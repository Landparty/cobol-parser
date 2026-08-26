"""
Comprehensive unit tests for cobolparser.models.ast_base module.

This test module provides 100% test coverage for the AST base classes including:
- SourceLocation: Source code location tracking
- ASTNode: Abstract base class for all AST nodes
- ValidationResult: AST validation results container
- ASTValidator: Base AST validation logic

Test Coverage Goals:
- All public methods and properties
- Edge cases and error conditions
- Abstract method enforcement
- Node hierarchy operations
- Traversal algorithms
- Validation logic
"""

import json
from typing import Any

import pytest

from cobolparser.models.ast_base import (
    ASTNode,
    ASTValidator,
    SourceLocation,
    ValidationResult,
)


class TestSourceLocation:
    """Comprehensive tests for SourceLocation class."""

    def test_source_location_creation_basic(self):
        """Test basic SourceLocation creation."""
        location = SourceLocation(line=10, column=25)

        assert location.line == 10
        assert location.column == 25
        assert location.length is None

    def test_source_location_creation_with_length(self):
        """Test SourceLocation creation with length parameter."""
        location = SourceLocation(line=5, column=15, length=10)

        assert location.line == 5
        assert location.column == 15
        assert location.length == 10

    def test_source_location_to_dict_basic(self):
        """Test SourceLocation to_dict() method without length."""
        location = SourceLocation(line=1, column=1)
        result = location.to_dict()

        expected = {"line": 1, "column": 1}
        assert result == expected
        assert "length" not in result

    def test_source_location_to_dict_with_length(self):
        """Test SourceLocation to_dict() method with length."""
        location = SourceLocation(line=3, column=7, length=5)
        result = location.to_dict()

        expected = {"line": 3, "column": 7, "length": 5}
        assert result == expected

    def test_source_location_str_without_length(self):
        """Test SourceLocation __str__() method without length."""
        location = SourceLocation(line=2, column=8)
        result = str(location)

        expected = "Line 2, Column 8"
        assert result == expected

    def test_source_location_str_with_length(self):
        """Test SourceLocation __str__() method with length."""
        location = SourceLocation(line=4, column=12, length=7)
        result = str(location)

        expected = "Line 4, Column 12 (length 7)"
        assert result == expected

    def test_source_location_edge_cases(self):
        """Test SourceLocation with edge case values."""
        # Test zero values
        location_zero = SourceLocation(line=0, column=0, length=0)
        assert location_zero.line == 0
        assert location_zero.column == 0
        assert location_zero.length == 0

        # Test large values
        location_large = SourceLocation(line=999999, column=999999, length=999999)
        assert location_large.line == 999999
        assert location_large.column == 999999
        assert location_large.length == 999999


class ConcreteASTNode(ASTNode):
    """Concrete implementation of ASTNode for testing."""

    def __init__(self, node_type: str, location: SourceLocation, name: str = ""):
        super().__init__(node_type, location)
        self.name = name

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_type": self.node_type,
            "location": self.location.to_dict(),
            "name": getattr(self, "name", ""),
            "children": [child.to_dict() for child in self.children],
            "metadata": self._metadata,
        }


class TestASTNode:
    """Comprehensive tests for ASTNode abstract base class."""

    def test_ast_node_creation(self):
        """Test basic ASTNode creation."""
        location = SourceLocation(1, 1)
        node = ConcreteASTNode("TestNode", location, "test-node")

        assert node.node_type == "TestNode"
        assert node.location == location
        assert node.parent is None
        assert len(node.children) == 0
        assert len(node._metadata) == 0
        assert node.name == "test-node"

    def test_ast_node_abstract_enforcement(self):
        """Test that ASTNode cannot be instantiated directly."""
        location = SourceLocation(1, 1)

        with pytest.raises(TypeError):
            ASTNode("TestNode", location)  # type: ignore[abstract]

    def test_add_child_basic(self):
        """Test adding child nodes."""
        parent = ConcreteASTNode("Parent", SourceLocation(1, 1))
        child = ConcreteASTNode("Child", SourceLocation(2, 1))

        parent.add_child(child)

        assert len(parent.children) == 1
        assert parent.children[0] == child
        assert child.parent == parent

    def test_add_child_multiple(self):
        """Test adding multiple child nodes."""
        parent = ConcreteASTNode("Parent", SourceLocation(1, 1))
        child1 = ConcreteASTNode("Child1", SourceLocation(2, 1))
        child2 = ConcreteASTNode("Child2", SourceLocation(3, 1))
        child3 = ConcreteASTNode("Child3", SourceLocation(4, 1))

        parent.add_child(child1)
        parent.add_child(child2)
        parent.add_child(child3)

        assert len(parent.children) == 3
        assert child1.parent == parent
        assert child2.parent == parent
        assert child3.parent == parent

    def test_add_child_reparenting(self):
        """Test that adding a child removes it from previous parent."""
        parent1 = ConcreteASTNode("Parent1", SourceLocation(1, 1))
        parent2 = ConcreteASTNode("Parent2", SourceLocation(2, 1))
        child = ConcreteASTNode("Child", SourceLocation(3, 1))

        # Add child to first parent
        parent1.add_child(child)
        assert len(parent1.children) == 1
        assert child.parent == parent1

        # Add child to second parent - should remove from first
        parent2.add_child(child)
        assert len(parent1.children) == 0
        assert len(parent2.children) == 1
        assert child.parent == parent2

    def test_remove_child_success(self):
        """Test successful child removal."""
        parent = ConcreteASTNode("Parent", SourceLocation(1, 1))
        child = ConcreteASTNode("Child", SourceLocation(2, 1))

        parent.add_child(child)
        result = parent.remove_child(child)

        assert result is True
        assert len(parent.children) == 0
        assert child.parent is None

    def test_remove_child_not_found(self):
        """Test removing child that isn't in children list."""
        parent = ConcreteASTNode("Parent", SourceLocation(1, 1))
        child = ConcreteASTNode("Child", SourceLocation(2, 1))
        other_child = ConcreteASTNode("OtherChild", SourceLocation(3, 1))

        parent.add_child(child)
        result = parent.remove_child(other_child)

        assert result is False
        assert len(parent.children) == 1
        assert child.parent == parent

    def test_get_child_at_valid_indices(self):
        """Test getting children at valid indices."""
        parent = ConcreteASTNode("Parent", SourceLocation(1, 1))
        child1 = ConcreteASTNode("Child1", SourceLocation(2, 1))
        child2 = ConcreteASTNode("Child2", SourceLocation(3, 1))
        child3 = ConcreteASTNode("Child3", SourceLocation(4, 1))

        parent.add_child(child1)
        parent.add_child(child2)
        parent.add_child(child3)

        assert parent.get_child_at(0) == child1
        assert parent.get_child_at(1) == child2
        assert parent.get_child_at(2) == child3

    def test_get_child_at_invalid_indices(self):
        """Test getting children at invalid indices."""
        parent = ConcreteASTNode("Parent", SourceLocation(1, 1))
        child = ConcreteASTNode("Child", SourceLocation(2, 1))
        parent.add_child(child)

        assert parent.get_child_at(-1) is None
        assert parent.get_child_at(1) is None
        assert parent.get_child_at(100) is None

    def test_get_children_by_type(self):
        """Test filtering children by node type."""
        parent = ConcreteASTNode("Parent", SourceLocation(1, 1))
        child1 = ConcreteASTNode("TypeA", SourceLocation(2, 1))
        child2 = ConcreteASTNode("TypeB", SourceLocation(3, 1))
        child3 = ConcreteASTNode("TypeA", SourceLocation(4, 1))
        child4 = ConcreteASTNode("TypeC", SourceLocation(5, 1))

        parent.add_child(child1)
        parent.add_child(child2)
        parent.add_child(child3)
        parent.add_child(child4)

        type_a_children = parent.get_children_by_type("TypeA")
        type_b_children = parent.get_children_by_type("TypeB")
        type_d_children = parent.get_children_by_type("TypeD")

        assert len(type_a_children) == 2
        assert child1 in type_a_children
        assert child3 in type_a_children
        assert len(type_b_children) == 1
        assert child2 in type_b_children
        assert len(type_d_children) == 0

    def test_traverse_depth_first(self):
        """Test depth-first traversal."""
        # Create tree structure:
        #       root
        #      /    \
        #   child1  child2
        #   /    \     |
        # gc1   gc2   gc3

        root = ConcreteASTNode("Root", SourceLocation(1, 1))
        child1 = ConcreteASTNode("Child1", SourceLocation(2, 1))
        child2 = ConcreteASTNode("Child2", SourceLocation(3, 1))
        gc1 = ConcreteASTNode("GrandChild1", SourceLocation(4, 1))
        gc2 = ConcreteASTNode("GrandChild2", SourceLocation(5, 1))
        gc3 = ConcreteASTNode("GrandChild3", SourceLocation(6, 1))

        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(gc1)
        child1.add_child(gc2)
        child2.add_child(gc3)

        nodes = list(root.traverse_depth_first())

        # Depth-first order: root, child1, gc1, gc2, child2, gc3
        expected_order = [root, child1, gc1, gc2, child2, gc3]
        assert nodes == expected_order

    def test_traverse_breadth_first(self):
        """Test breadth-first traversal."""
        # Same tree structure as depth-first test
        root = ConcreteASTNode("Root", SourceLocation(1, 1))
        child1 = ConcreteASTNode("Child1", SourceLocation(2, 1))
        child2 = ConcreteASTNode("Child2", SourceLocation(3, 1))
        gc1 = ConcreteASTNode("GrandChild1", SourceLocation(4, 1))
        gc2 = ConcreteASTNode("GrandChild2", SourceLocation(5, 1))
        gc3 = ConcreteASTNode("GrandChild3", SourceLocation(6, 1))

        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(gc1)
        child1.add_child(gc2)
        child2.add_child(gc3)

        nodes = list(root.traverse_breadth_first())

        # Breadth-first order: root, child1, child2, gc1, gc2, gc3
        expected_order = [root, child1, child2, gc1, gc2, gc3]
        assert nodes == expected_order

    def test_find_first_by_type_found(self):
        """Test finding first node by type when it exists."""
        root = ConcreteASTNode("Root", SourceLocation(1, 1))
        child1 = ConcreteASTNode("Target", SourceLocation(2, 1))
        child2 = ConcreteASTNode("Other", SourceLocation(3, 1))
        gc1 = ConcreteASTNode("Target", SourceLocation(4, 1))

        root.add_child(child1)
        root.add_child(child2)
        child2.add_child(gc1)

        result = root.find_first_by_type("Target")

        # Should find child1 first (depth-first traversal)
        assert result == child1

    def test_find_first_by_type_not_found(self):
        """Test finding first node by type when it doesn't exist."""
        root = ConcreteASTNode("Root", SourceLocation(1, 1))
        child = ConcreteASTNode("Child", SourceLocation(2, 1))
        root.add_child(child)

        result = root.find_first_by_type("NonExistent")

        assert result is None

    def test_find_all_by_type(self):
        """Test finding all nodes by type."""
        root = ConcreteASTNode("Root", SourceLocation(1, 1))
        child1 = ConcreteASTNode("Target", SourceLocation(2, 1))
        child2 = ConcreteASTNode("Other", SourceLocation(3, 1))
        gc1 = ConcreteASTNode("Target", SourceLocation(4, 1))
        gc2 = ConcreteASTNode("Target", SourceLocation(5, 1))

        root.add_child(child1)
        root.add_child(child2)
        child1.add_child(gc1)
        child2.add_child(gc2)

        results = root.find_all_by_type("Target")

        assert len(results) == 3
        assert child1 in results
        assert gc1 in results
        assert gc2 in results

    def test_find_all_by_type_mutation_does_not_corrupt_cache(self):
        """A caller mutating the returned list must not affect later calls.

        find_all_by_type() caches its result per node_type internally; it
        must hand back a copy of that cache, not the cache itself.
        """
        root = ConcreteASTNode("Root", SourceLocation(1, 1))
        child = ConcreteASTNode("Target", SourceLocation(2, 1))
        root.add_child(child)

        first = root.find_all_by_type("Target")
        assert len(first) == 1

        first.append(ConcreteASTNode("Poison", SourceLocation(9, 1)))

        second = root.find_all_by_type("Target")
        assert len(second) == 1
        assert second[0] == child

    def test_get_root_single_node(self):
        """Test getting root of single node."""
        node = ConcreteASTNode("Single", SourceLocation(1, 1))

        assert node.get_root() == node

    def test_get_root_with_hierarchy(self):
        """Test getting root with node hierarchy."""
        root = ConcreteASTNode("Root", SourceLocation(1, 1))
        child = ConcreteASTNode("Child", SourceLocation(2, 1))
        grandchild = ConcreteASTNode("GrandChild", SourceLocation(3, 1))

        root.add_child(child)
        child.add_child(grandchild)

        assert grandchild.get_root() == root
        assert child.get_root() == root
        assert root.get_root() == root

    def test_get_path_from_root_single_node(self):
        """Test path from root for single node."""
        node = ConcreteASTNode("Single", SourceLocation(1, 1))

        path = node.get_path_from_root()

        assert path == [node]

    def test_get_path_from_root_with_hierarchy(self):
        """Test path from root with node hierarchy."""
        root = ConcreteASTNode("Root", SourceLocation(1, 1))
        child = ConcreteASTNode("Child", SourceLocation(2, 1))
        grandchild = ConcreteASTNode("GrandChild", SourceLocation(3, 1))

        root.add_child(child)
        child.add_child(grandchild)

        path = grandchild.get_path_from_root()

        assert path == [root, child, grandchild]

    def test_metadata_operations(self):
        """Test metadata set, get, and has operations."""
        node = ConcreteASTNode("TestNode", SourceLocation(1, 1))

        # Test has_metadata on empty metadata
        assert not node.has_metadata("key1")

        # Test set_metadata and get_metadata
        node.set_metadata("key1", "value1")
        node.set_metadata("key2", 42)
        node.set_metadata("key3", {"nested": "dict"})

        assert node.get_metadata("key1") == "value1"
        assert node.get_metadata("key2") == 42
        assert node.get_metadata("key3") == {"nested": "dict"}

        # Test has_metadata after setting
        assert node.has_metadata("key1")
        assert node.has_metadata("key2")
        assert node.has_metadata("key3")

        # Test get_metadata with default value
        assert node.get_metadata("nonexistent") is None
        assert node.get_metadata("nonexistent", "default") == "default"

    def test_to_json(self):
        """Test JSON serialization."""
        node = ConcreteASTNode("TestNode", SourceLocation(1, 5), "test-name")
        node.set_metadata("test_key", "test_value")

        json_str = node.to_json()

        # Verify it's valid JSON
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert parsed["node_type"] == "TestNode"
        assert parsed["name"] == "test-name"

        # Test with indentation
        json_str_indented = node.to_json(indent=2)
        assert "\n" in json_str_indented  # Should have newlines due to indentation

    def test_equals_same_structure(self):
        """Test equals method with identical structures."""
        node1 = ConcreteASTNode("TestType", SourceLocation(1, 1))
        node2 = ConcreteASTNode("TestType", SourceLocation(1, 1))

        child1_1 = ConcreteASTNode("ChildType", SourceLocation(2, 1))
        child1_2 = ConcreteASTNode("ChildType", SourceLocation(3, 1))

        child2_1 = ConcreteASTNode("ChildType", SourceLocation(2, 1))
        child2_2 = ConcreteASTNode("ChildType", SourceLocation(3, 1))

        node1.add_child(child1_1)
        node1.add_child(child1_2)

        node2.add_child(child2_1)
        node2.add_child(child2_2)

        # This should force the method to check all children and return True
        assert node1.equals(node2)

        # Test with deeper hierarchy to ensure full traversal
        deep_child1 = ConcreteASTNode("DeepChild", SourceLocation(4, 1))
        deep_child2 = ConcreteASTNode("DeepChild", SourceLocation(4, 1))

        child1_1.add_child(deep_child1)
        child2_1.add_child(deep_child2)

        assert node1.equals(node2)

    def test_equals_empty_nodes(self):
        """Test equals method with empty nodes (no children)."""
        node1 = ConcreteASTNode("TestType", SourceLocation(1, 1))
        node2 = ConcreteASTNode("TestType", SourceLocation(2, 2))

        # Even with different locations, nodes should be equal if structure is same
        assert node1.equals(node2)

    def test_equals_different_type(self):
        """Test equals method with different node types."""
        node1 = ConcreteASTNode("Type1", SourceLocation(1, 1))
        node2 = ConcreteASTNode("Type2", SourceLocation(1, 1))

        assert not node1.equals(node2)

    def test_equals_different_child_count(self):
        """Test equals method with different child counts."""
        node1 = ConcreteASTNode("TestType", SourceLocation(1, 1))
        node2 = ConcreteASTNode("TestType", SourceLocation(1, 1))

        child = ConcreteASTNode("ChildType", SourceLocation(2, 1))
        node1.add_child(child)

        assert not node1.equals(node2)

        # Test reverse case - node2 has child, node1 doesn't
        node3 = ConcreteASTNode("TestType", SourceLocation(1, 1))
        node4 = ConcreteASTNode("TestType", SourceLocation(1, 1))
        child2 = ConcreteASTNode("ChildType", SourceLocation(2, 1))
        node4.add_child(child2)

        assert not node3.equals(node4)

    def test_equals_different_children(self):
        """Test equals method with different children structures."""
        node1 = ConcreteASTNode("TestType", SourceLocation(1, 1))
        node2 = ConcreteASTNode("TestType", SourceLocation(1, 1))

        # Same number of children but different child types
        child1_1 = ConcreteASTNode("ChildTypeA", SourceLocation(2, 1))
        child2_1 = ConcreteASTNode("ChildTypeB", SourceLocation(2, 1))

        node1.add_child(child1_1)
        node2.add_child(child2_1)

        assert not node1.equals(node2)

    def test_equals_non_ast_node(self):
        """Test equals method with non-ASTNode object."""
        node = ConcreteASTNode("TestType", SourceLocation(1, 1))

        assert not node.equals("not an ast node")  # type: ignore[arg-type]
        assert not node.equals(42)  # type: ignore[arg-type]
        assert not node.equals(None)  # type: ignore[arg-type]

    def test_str_representation(self):
        """Test string representation of node."""
        location = SourceLocation(5, 10)
        node = ConcreteASTNode("TestType", location)

        str_repr = str(node)

        assert "TestType" in str_repr
        assert "Line 5, Column 10" in str_repr

    def test_repr_representation(self):
        """Test detailed string representation of node."""
        location = SourceLocation(3, 7)
        node = ConcreteASTNode("TestType", location)
        child = ConcreteASTNode("ChildType", SourceLocation(4, 1))
        node.add_child(child)

        repr_str = repr(node)

        assert "ConcreteASTNode" in repr_str
        assert "TestType" in repr_str
        assert "children=1" in repr_str


class TestValidationResult:
    """Comprehensive tests for ValidationResult class."""

    def test_validation_result_creation(self):
        """Test ValidationResult creation."""
        result = ValidationResult()

        assert len(result.errors) == 0
        assert len(result.warnings) == 0
        assert result.is_valid is True

    def test_add_error(self):
        """Test adding errors to validation result."""
        result = ValidationResult()

        result.add_error("First error")
        result.add_error("Second error")

        assert len(result.errors) == 2
        assert "First error" in result.errors
        assert "Second error" in result.errors
        assert result.is_valid is False

    def test_add_warning(self):
        """Test adding warnings to validation result."""
        result = ValidationResult()

        result.add_warning("First warning")
        result.add_warning("Second warning")

        assert len(result.warnings) == 2
        assert "First warning" in result.warnings
        assert "Second warning" in result.warnings
        assert result.is_valid is True  # Warnings don't affect validity

    def test_is_valid_property(self):
        """Test is_valid property with various states."""
        result = ValidationResult()

        # Initially valid
        assert result.is_valid is True

        # Still valid with warnings
        result.add_warning("A warning")
        assert result.is_valid is True

        # Invalid with errors
        result.add_error("An error")
        assert result.is_valid is False

        # Still invalid with more errors
        result.add_error("Another error")
        assert result.is_valid is False

    def test_to_dict(self):
        """Test ValidationResult to_dict() method."""
        result = ValidationResult()
        result.add_error("Test error")
        result.add_warning("Test warning")

        result_dict = result.to_dict()

        expected = {
            "is_valid": False,
            "errors": ["Test error"],
            "warnings": ["Test warning"],
        }

        assert result_dict == expected

    def test_to_dict_empty(self):
        """Test ValidationResult to_dict() method when empty."""
        result = ValidationResult()

        result_dict = result.to_dict()

        expected = {"is_valid": True, "errors": [], "warnings": []}

        assert result_dict == expected


class TestASTValidator:
    """Comprehensive tests for ASTValidator class."""

    def test_validator_creation(self):
        """Test ASTValidator creation."""
        validator = ASTValidator()

        assert validator is not None
        assert hasattr(validator, "validate")
        assert hasattr(validator, "_validate_node")

    def test_validate_valid_node(self):
        """Test validating a valid node."""
        validator = ASTValidator()
        node = ConcreteASTNode("ValidNode", SourceLocation(1, 1))

        result = validator.validate(node)

        assert result.is_valid is True
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_validate_node_missing_node_type(self):
        """Test validating node missing node_type."""
        validator = ASTValidator()
        node = ConcreteASTNode("TestNode", SourceLocation(1, 1))

        # Remove node_type attribute
        delattr(node, "node_type")

        result = validator.validate(node)

        assert result.is_valid is False
        assert len(result.errors) >= 1
        assert any("node_type" in error for error in result.errors)

    def test_validate_node_empty_node_type(self):
        """Test validating node with empty node_type."""
        validator = ASTValidator()
        node = ConcreteASTNode("TestNode", SourceLocation(1, 1))

        # Set empty node_type
        node.node_type = ""

        result = validator.validate(node)

        assert result.is_valid is False
        assert len(result.errors) >= 1
        assert any("node_type" in error for error in result.errors)

    def test_validate_node_missing_location(self):
        """Test validating node missing location."""
        validator = ASTValidator()
        node = ConcreteASTNode("TestNode", SourceLocation(1, 1))

        # Remove location attribute
        delattr(node, "location")

        result = validator.validate(node)

        assert result.is_valid is False
        assert len(result.errors) >= 1
        assert any("location" in error for error in result.errors)

    def test_validate_node_with_children(self):
        """Test validating node hierarchy with valid and invalid children."""
        validator = ASTValidator()

        parent = ConcreteASTNode("Parent", SourceLocation(1, 1))
        valid_child = ConcreteASTNode("ValidChild", SourceLocation(2, 1))
        invalid_child = ConcreteASTNode("InvalidChild", SourceLocation(3, 1))

        # Make invalid_child actually invalid
        invalid_child.node_type = ""

        parent.add_child(valid_child)
        parent.add_child(invalid_child)

        result = validator.validate(parent)

        assert result.is_valid is False
        assert len(result.errors) >= 1  # Should have error from invalid child

    def test_validate_deep_hierarchy(self):
        """Test validating deep node hierarchy."""
        validator = ASTValidator()

        root = ConcreteASTNode("Root", SourceLocation(1, 1))
        child = ConcreteASTNode("Child", SourceLocation(2, 1))
        grandchild = ConcreteASTNode("GrandChild", SourceLocation(3, 1))

        root.add_child(child)
        child.add_child(grandchild)

        # Make grandchild invalid
        delattr(grandchild, "location")

        result = validator.validate(root)

        assert result.is_valid is False
        assert len(result.errors) >= 1
        assert any("location" in error for error in result.errors)
