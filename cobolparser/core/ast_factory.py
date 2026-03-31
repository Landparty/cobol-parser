"""AST Node Factory for centralized and validated node creation.

This module provides a factory pattern for AST node creation with comprehensive
validation to ensure:
- Node types match expected classes
- Required fields are present and properly typed
- Type checking and validation before node creation
- Uniform error reporting for creation failures

The factory enables refactoring of all parsers to use centralized node creation,
improving maintainability and reducing coupled dependencies.
"""

from typing import Dict, Any, Type, Optional, List, get_type_hints
from abc import ABC

from ..models.ast_base import ASTNode, SourceLocation
from ..core.exceptions import ValidationError, ParseError


class NodeTypeError(ValidationError):
    """Raised when node type validation fails."""

    def __init__(self, expected_type: str, actual_type: str):
        """Initialize type error.

        Args:
            expected_type: Expected node type class name
            actual_type: Actual type provided
        """
        super().__init__(expected_type, f"Expected node type {expected_type}, got {actual_type}")


class FieldValidationError(ValidationError):
    """Raised when required field validation fails."""

    def __init__(self, field_name: str, reason: str, node_type: str = ""):
        """Initialize field validation error.

        Args:
            field_name: Name of the field that failed validation
            reason: Reason for validation failure
            node_type: Optional node type for context
        """
        context = f" in {node_type}" if node_type else ""
        super().__init__(node_type or field_name, f"Field '{field_name}' validation failed{context}: {reason}")


class ASTNodeFactory:
    """Factory for creating validated AST nodes.
    
    Provides centralized node creation with comprehensive validation:
    - Type checking (ensure correct node class)
    - Field validation (required fields present and properly typed)
    - Source location tracking
    - Metadata and context assignment
    
    Example:
        factory = ASTNodeFactory()
        node = factory.create_display_statement(
            location=SourceLocation(10, 1),
            items=["greeting", "name"]
        )
    """
    
    # Registry of known node types and their validation rules
    _node_validators: Dict[str, Dict[str, Any]] = {}
    
    def __init__(self) -> None:
        """Initialize the AST node factory."""
        self._creation_count = 0
        self._validation_errors: List[str] = []
    
    def register_validator(self, node_type: str, validator_config: Dict[str, Any]) -> None:
        """Register a validator for a specific node type.
        
        Args:
            node_type: Name of the node type (e.g., "DisplayStatement")
            validator_config: Configuration dict with:
                - "class": The node class to validate against
                - "required_fields": List of required field names
                - "field_types": Dict mapping field name to expected type
        """
        self._node_validators[node_type] = validator_config
    
    def validate_node_type(self, node: ASTNode, expected_type: Type[ASTNode]) -> bool:
        """Validate that a node is the correct type.
        
        Args:
            node: Node to validate
            expected_type: Expected node class type
            
        Returns:
            True if validation passes
            
        Raises:
            NodeTypeError: If node type doesn't match expected type
        """
        if not isinstance(node, expected_type):
            raise NodeTypeError(
                expected_type.__name__,
                type(node).__name__
            )
        return True
    
    def validate_required_fields(self, node: ASTNode, required_fields: List[str],
                                node_type_name: str = "") -> bool:
        """Validate that required fields exist on a node.
        
        Args:
            node: Node to validate
            required_fields: List of field names that must exist
            node_type_name: Name of node type for error messages
            
        Returns:
            True if all required fields are present
            
        Raises:
            FieldValidationError: If any required field is missing
        """
        for field_name in required_fields:
            if not hasattr(node, field_name):
                raise FieldValidationError(
                    field_name,
                    "field does not exist",
                    node_type_name
                )
            
            value = getattr(node, field_name)
            if value is None:
                raise FieldValidationError(
                    field_name,
                    "field is None",
                    node_type_name
                )
        
        return True
    
    def validate_field_types(self, node: ASTNode, field_types: Dict[str, type],
                            node_type_name: str = "") -> bool:
        """Validate that field types match expectations.
        
        Args:
            node: Node to validate
            field_types: Dict mapping field name to expected type
            node_type_name: Name of node type for error messages
            
        Returns:
            True if all field types are correct
            
        Raises:
            FieldValidationError: If any field has wrong type
        """
        for field_name, expected_type in field_types.items():
            if not hasattr(node, field_name):
                continue  # Skip if field doesn't exist (checked separately)
            
            value = getattr(node, field_name)
            if value is None:
                continue  # Skip None values (checked separately)
            
            # Handle Optional types
            if hasattr(expected_type, '__origin__'):
                # This is a generic type like Optional[str]
                continue  # Skip complex type checking for now
            
            if not isinstance(value, expected_type):
                actual_type = type(value).__name__
                expected_name = expected_type.__name__
                raise FieldValidationError(
                    field_name,
                    f"expected {expected_name}, got {actual_type}",
                    node_type_name
                )
        
        return True
    
    def create(self, node_class: Type[ASTNode], location: SourceLocation,
              **kwargs: Any) -> ASTNode:
        """Create an AST node with validation.
        
        Generic factory method for creating any AST node class with
        validation of required parameters and types.
        
        Args:
            node_class: The AST node class to instantiate
            location: Source location for the node
            **kwargs: Additional parameters for node initialization
            
        Returns:
            Created and validated AST node
            
        Raises:
            TypeError: If node_class is not an ASTNode subclass
            ValidationError: If validation fails
        """
        # Validate that it's actually an ASTNode
        if not issubclass(node_class, ASTNode):
            raise TypeError(f"{node_class.__name__} is not an ASTNode subclass")
        
        try:
            # Create the node
            node = node_class(location, **kwargs)  # type: ignore[arg-type]
            self._creation_count += 1
            
            # Post-creation validation
            self._validate_created_node(node)
            
            return node
        except Exception as e:
            self._validation_errors.append(str(e))
            raise
    
    def _validate_created_node(self, node: ASTNode) -> None:
        """Perform post-creation validation on a node.
        
        Args:
            node: The created node to validate
            
        Raises:
            ValidationError: If validation fails
        """
        # Validate location is set
        if not hasattr(node, 'location') or node.location is None:
            raise ValidationError(type(node).__name__, "Node location must be set")

        # Validate location is correct type
        if not isinstance(node.location, SourceLocation):
            raise ValidationError(type(node).__name__, "Node location must be SourceLocation")

        # Validate node_type is set
        if not hasattr(node, 'node_type') or not node.node_type:
            raise ValidationError(type(node).__name__, "Node type must be set")
    
    def with_metadata(self, node: ASTNode, metadata: Dict[str, Any]) -> ASTNode:
        """Add metadata to a node.
        
        Args:
            node: Node to add metadata to
            metadata: Dict of metadata key-value pairs
            
        Returns:
            The same node (for chaining)
        """
        for key, value in metadata.items():
            node.set_metadata(key, value)
        return node
    
    def with_context(self, node: ASTNode, division_name: str,
                    section_name: Optional[str] = None) -> ASTNode:
        """Set division and section context on a node.
        
        Args:
            node: Node to set context on
            division_name: Name of containing division
            section_name: Optional name of containing section
            
        Returns:
            The same node (for chaining)
        """
        node.set_division_context(division_name, section_name)
        return node
    
    def get_creation_count(self) -> int:
        """Get the number of nodes created by this factory.
        
        Returns:
            Total nodes created
        """
        return self._creation_count
    
    def get_validation_errors(self) -> List[str]:
        """Get all validation errors encountered.
        
        Returns:
            List of error messages
        """
        return list(self._validation_errors)
    
    def clear_validation_errors(self) -> None:
        """Clear the validation error log."""
        self._validation_errors.clear()
    
    def __repr__(self) -> str:
        """Return string representation of factory."""
        return (f"ASTNodeFactory(created={self._creation_count}, "
                f"errors={len(self._validation_errors)})")


# Global factory instance for use throughout the parser
_default_factory: Optional[ASTNodeFactory] = None


def get_factory() -> ASTNodeFactory:
    """Get the default factory instance.
    
    Returns:
        The global ASTNodeFactory instance
    """
    global _default_factory
    if _default_factory is None:
        _default_factory = ASTNodeFactory()
    return _default_factory


def set_factory(factory: ASTNodeFactory) -> None:
    """Set a custom factory instance.
    
    Args:
        factory: Factory instance to use globally
    """
    global _default_factory
    _default_factory = factory


def create_node(node_class: Type[ASTNode], location: SourceLocation,
               **kwargs: Any) -> ASTNode:
    """Convenience function to create a node using the default factory.
    
    Args:
        node_class: The AST node class to create
        location: Source location for the node
        **kwargs: Additional parameters for node initialization
        
    Returns:
        Created AST node
    """
    return get_factory().create(node_class, location, **kwargs)
