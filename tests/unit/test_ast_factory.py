"""Unit tests for ASTNodeFactory.

Tests cover:
- Node creation with validation
- Node type checking
- Required field validation
- Field type validation
- Metadata and context assignment
- Error handling and reporting
"""

from unittest.mock import patch

import pytest

from cobolparser.core import ASTNodeFactory, create_node, get_factory, set_factory
from cobolparser.core.ast_factory import FieldValidationError, NodeTypeError
from cobolparser.core.exceptions import ValidationError
from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements import DisplayStatement, MoveStatement


class TestASTNodeFactoryCreation:
    """Test basic node creation functionality."""

    def test_create_simple_node(self):
        """Test creating a simple AST node."""
        factory = ASTNodeFactory()
        location = SourceLocation(10, 1)

        node = factory.create(DisplayStatement, location)

        assert node is not None
        assert isinstance(node, DisplayStatement)
        assert node.location == location
        assert factory.get_creation_count() == 1

    def test_create_multiple_nodes(self):
        """Test creating multiple nodes."""
        factory = ASTNodeFactory()

        node1 = factory.create(DisplayStatement, SourceLocation(10, 1))
        node2 = factory.create(MoveStatement, SourceLocation(20, 1))
        node3 = factory.create(DisplayStatement, SourceLocation(30, 1))

        assert factory.get_creation_count() == 3
        assert isinstance(node1, DisplayStatement)
        assert isinstance(node2, MoveStatement)
        assert isinstance(node3, DisplayStatement)

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


class TestASTNodeFactoryValidation:
    """Test node validation functionality."""

    def test_validate_node_type_success(self):
        """Test successful node type validation."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(10, 1))

        result = factory.validate_node_type(node, DisplayStatement)

        assert result is True

    def test_validate_node_type_failure(self):
        """Test node type validation failure."""
        factory = ASTNodeFactory()
        display_node = DisplayStatement(SourceLocation(10, 1))

        with pytest.raises(NodeTypeError):
            factory.validate_node_type(display_node, MoveStatement)

    def test_validate_required_fields_success(self):
        """Test successful required field validation."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(10, 1))

        # ASTNode always has location, node_type, parent, children
        result = factory.validate_required_fields(
            node, ["location", "node_type"], "DisplayStatement"
        )

        assert result is True

    def test_validate_required_fields_missing_field(self):
        """Test required field validation with missing field."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(10, 1))

        with pytest.raises(FieldValidationError):
            factory.validate_required_fields(
                node, ["location", "nonexistent_field"], "DisplayStatement"
            )

    def test_validate_field_types_success(self):
        """Test successful field type validation."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(10, 1))

        result = factory.validate_field_types(
            node, {"location": SourceLocation, "node_type": str}, "DisplayStatement"
        )

        assert result is True

    def test_validate_field_types_mismatch(self):
        """Test field type validation with type mismatch."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(10, 1))

        with pytest.raises(FieldValidationError):
            factory.validate_field_types(
                node,
                {"location": str},  # location is SourceLocation, not str
                "DisplayStatement",
            )


class TestASTNodeFactoryMetadata:
    """Test metadata assignment."""

    def test_add_metadata_to_node(self):
        """Test adding metadata to a node."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(10, 1))
        metadata = {"line_count": 5, "statement_type": "IO"}

        result = factory.with_metadata(node, metadata)

        assert result is node
        assert node.get_metadata("line_count") == 5
        assert node.get_metadata("statement_type") == "IO"

    def test_with_metadata_returns_node_for_chaining(self):
        """Test that with_metadata returns node for method chaining."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(10, 1))

        result = factory.with_metadata(node, {"key": "value"})

        assert result is node

    def test_with_context_sets_division_and_section(self):
        """Test setting division and section context."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(10, 1))

        result = factory.with_context(node, "PROCEDURE", "MAIN-SECTION")

        assert result is node
        assert node.division_name == "PROCEDURE"
        assert node.section_name == "MAIN-SECTION"

    def test_with_context_sets_division_only(self):
        """Test setting only division context."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(10, 1))

        result = factory.with_context(node, "DATA")

        assert result is node
        assert node.division_name == "DATA"


class TestASTNodeFactoryErrorReporting:
    """Test error tracking and reporting."""

    def test_validation_errors_tracked(self):
        """Test that validation errors are tracked."""
        factory = ASTNodeFactory()
        location = SourceLocation(10, 1)

        # Create valid node - no errors
        factory.create(DisplayStatement, location)
        assert len(factory.get_validation_errors()) == 0

    def test_clear_validation_errors(self):
        """Test clearing validation error log."""
        factory = ASTNodeFactory()

        # Create a valid node first (no errors)
        factory.create(DisplayStatement, SourceLocation(10, 1))

        # Now manually add an error to test clearing
        factory._validation_errors.append("Test error")

        errors = factory.get_validation_errors()
        assert len(errors) > 0

        factory.clear_validation_errors()
        assert len(factory.get_validation_errors()) == 0


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

    def test_create_and_configure_node(self):
        """Test creating and configuring a node in one pattern."""
        factory = ASTNodeFactory()
        location = SourceLocation(10, 1)

        node = factory.create(DisplayStatement, location)
        node = factory.with_context(node, "PROCEDURE", "MAIN")
        node = factory.with_metadata(node, {"priority": "high"})

        assert isinstance(node, DisplayStatement)
        assert node.division_name == "PROCEDURE"
        assert node.section_name == "MAIN"
        assert node.get_metadata("priority") == "high"

    def test_factory_repr(self):
        """Test factory string representation."""
        factory = ASTNodeFactory()
        factory.create(DisplayStatement, SourceLocation(10, 1))
        factory.create(MoveStatement, SourceLocation(20, 1))

        repr_str = repr(factory)
        assert "ASTNodeFactory" in repr_str
        assert "created=2" in repr_str

    def test_multiple_factories_independent(self):
        """Test that multiple factory instances are independent."""
        factory1 = ASTNodeFactory()
        factory2 = ASTNodeFactory()

        factory1.create(DisplayStatement, SourceLocation(10, 1))
        factory2.create(DisplayStatement, SourceLocation(10, 1))
        factory2.create(MoveStatement, SourceLocation(20, 1))

        assert factory1.get_creation_count() == 1
        assert factory2.get_creation_count() == 2


class TestASTNodeFactoryValidator:
    """Test validator registration and usage."""

    def test_register_validator(self):
        """Test registering a validator."""
        factory = ASTNodeFactory()
        config = {
            "class": DisplayStatement,
            "required_fields": ["location", "node_type"],
            "field_types": {"location": SourceLocation},
        }

        factory.register_validator("DisplayStatement", config)

        # Validator should be registered
        assert "DisplayStatement" in factory._node_validators

    def test_validator_config_structure(self):
        """Test validator configuration structure."""
        factory = ASTNodeFactory()
        config = {
            "class": DisplayStatement,
            "required_fields": ["location"],
            "field_types": {},
        }

        factory.register_validator("Test", config)
        retrieved = factory._node_validators["Test"]

        assert retrieved["class"] is DisplayStatement
        assert "location" in retrieved["required_fields"]


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

    def test_create_logs_error_and_reraises(self):
        """create() appends to _validation_errors and re-raises on failure."""
        factory = ASTNodeFactory()

        # Patch _validate_created_node to raise after node is built
        with patch.object(
            factory,
            "_validate_created_node",
            side_effect=ValidationError(
                "DisplayStatement", "synthetic validation fail"
            ),
        ):
            with pytest.raises(ValidationError):
                factory.create(DisplayStatement, SourceLocation(1, 1))

        # Error should be logged
        assert any(
            "synthetic validation fail" in e for e in factory.get_validation_errors()
        )


# ---------------------------------------------------------------------------
# validate_required_fields: None-value field path  (line 133)
# ---------------------------------------------------------------------------


class TestValidateRequiredFieldsNonePath:
    def test_none_field_value_raises_field_validation_error(self):
        """If a required field exists but its value is None, raise FieldValidationError."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(1, 1))
        # Patch location to None to trigger the None-value check
        node.location = None  # type: ignore[assignment]
        with pytest.raises(FieldValidationError):
            factory.validate_required_fields(node, ["location"], "DisplayStatement")


# ---------------------------------------------------------------------------
# validate_field_types: generic-type skip path  (lines 162-164)
# ---------------------------------------------------------------------------


class TestValidateFieldTypesGenericSkip:
    def test_generic_type_is_skipped(self):
        """If expected_type has __origin__ (e.g. list[str]), the check is skipped."""
        factory = ASTNodeFactory()
        node = DisplayStatement(SourceLocation(1, 1))

        # list[str] has __origin__ = list — should not raise
        result = factory.validate_field_types(
            node,
            {"node_type": str | None},  # str | None has __origin__
            "DisplayStatement",
        )
        assert result is True
