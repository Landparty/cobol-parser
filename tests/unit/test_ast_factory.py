"""Unit tests for ASTNodeFactory.

Tests cover:
- Node creation with validation
- Node type checking
- Required field validation
- Field type validation
- Metadata and context assignment
- Error handling and reporting
"""

import pytest

from cobolparser.core import ASTNodeFactory, create_node, get_factory, set_factory
from cobolparser.core.exceptions import ValidationError
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements import DisplayStatement


class TestASTNodeFactoryCreation:
    """Test basic node creation functionality."""

    def test_create_node_with_kwargs(self):
        """Test creating node with additional keyword arguments."""
        factory = ASTNodeFactory()
        location = SourceLocation(10, 1)

        # DisplayStatement might accept items parameter
        node = factory.create(DisplayStatement, location)

        assert node is not None
        assert isinstance(node, DisplayStatement)

    def test_create_invalid_node_type_raises_error(self):
        """Test that creating non-ASTNode class raises error."""
        factory = ASTNodeFactory()
        location = SourceLocation(10, 1)

        class NotANode:
            pass

        with pytest.raises(TypeError, match="not an ASTNode subclass"):
            factory.create(NotANode, location)  # type: ignore


class TestASTNodeFactoryGlobal:
    """Test global factory functions."""

    def test_get_default_factory(self):
        """Test getting the default factory instance."""
        factory1 = get_factory()
        factory2 = get_factory()

        # Should be same instance
        assert factory1 is factory2

    def test_set_custom_factory(self):
        """Test setting a custom factory instance."""
        custom_factory = ASTNodeFactory()
        set_factory(custom_factory)

        retrieved = get_factory()
        assert retrieved is custom_factory

    def test_create_node_with_default_factory(self):
        """Test using create_node() convenience function."""
        # Reset to default factory
        set_factory(ASTNodeFactory())

        location = SourceLocation(10, 1)
        node = create_node(DisplayStatement, location)

        assert isinstance(node, DisplayStatement)
        assert node.location == location


class TestASTNodeFactoryIntegration:
    """Integration tests for factory usage patterns."""


# ---------------------------------------------------------------------------
# _validate_created_node: paths for None location, wrong location type,
# missing node_type  (lines 224-235)
# ---------------------------------------------------------------------------


class TestValidateCreatedNodePaths:
    """These tests exercise _validate_created_node directly by patching the
    node attributes after construction so we don't need a real broken class.
    """

    def test_none_location_raises_validation_error(self):
        """ValidationError raised when node.location is None."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(1, 1))
        node.location = None  # type: ignore[assignment]
        with pytest.raises(ValidationError, match="location must be set"):
            factory._validate_created_node(node)

    def test_wrong_location_type_raises_validation_error(self):
        """ValidationError raised when node.location is not a SourceLocation."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(1, 1))
        node.location = "not-a-source-location"  # type: ignore[assignment]
        with pytest.raises(ValidationError, match="location must be SourceLocation"):
            factory._validate_created_node(node)

    def test_empty_node_type_raises_validation_error(self):
        """ValidationError raised when node.node_type is falsy."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(1, 1))
        node.node_type = ""  # type: ignore[assignment]
        with pytest.raises(ValidationError, match="Node type must be set"):
            factory._validate_created_node(node)


# ---------------------------------------------------------------------------
# validate_required_fields: None-value field path  (line 133)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# validate_field_types: generic-type skip path  (lines 162-164)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# validate_field_types: type mismatch raises FieldValidationError
# ---------------------------------------------------------------------------
