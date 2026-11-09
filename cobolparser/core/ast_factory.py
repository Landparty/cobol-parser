"""AST node factory: one place that constructs statement nodes.

``create()`` checks the class is an ``ASTNode`` whose ``__init__`` takes
``location`` first, builds it, and checks the location and node type were
set.
"""

import inspect
from typing import Any

from ..core.exceptions import ValidationError
from ..models.ast_base import ASTNode, SourceLocation


class ASTNodeFactory:
    """Factory for creating validated AST nodes.

    Example:
        factory = ASTNodeFactory()
        node = factory.create(
            DisplayStatement,
            SourceLocation(10, 1),
            items=["greeting", "name"],
        )
    """

    # node_class -> name of its __init__'s first argument after `self`,
    # memoized so the constructor-shape check in create() (guarding against
    # the location-mis-binding landmine) only introspects each class once
    # via `inspect.signature` instead of on every node creation -- create()
    # sits on the parsing hot path (every statement parser routes through
    # it via create_statement()).
    _first_init_param_cache: dict[type, str | None] = {}

    def create(
        self, node_class: type[ASTNode], location: SourceLocation, **kwargs: Any
    ) -> ASTNode:
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

        # Not every ASTNode subclass's __init__ takes `location` as its first
        # argument -- e.g. CobolDataItem(name, level, location) or
        # CobolSection(section_name, location). node_class(location, **kwargs)
        # below would silently bind `location` to the wrong parameter instead
        # of raising for one of those, since Python doesn't type-check
        # positional arguments. Catch that here with a clear error rather
        # than letting it corrupt the created node.
        if node_class not in self._first_init_param_cache:
            init_params = list(
                inspect.signature(node_class.__init__).parameters.values()
            )
            self._first_init_param_cache[node_class] = (
                init_params[1].name if len(init_params) > 1 else None
            )
        first_arg = self._first_init_param_cache[node_class]
        if first_arg != "location":
            raise TypeError(
                f"{node_class.__name__}.__init__ does not take `location` as "
                "its first argument (got "
                f"{first_arg!r}); ASTNodeFactory.create() cannot be used for "
                "this class without mis-binding location -- construct it "
                "directly instead"
            )

        node = node_class(location, **kwargs)  # type: ignore[arg-type]
        self._validate_created_node(node)
        return node

    def _validate_created_node(self, node: ASTNode) -> None:
        """Perform post-creation validation on a node.

        Args:
            node: The created node to validate

        Raises:
            ValidationError: If validation fails
        """
        # Validate location is set
        if not hasattr(node, "location") or node.location is None:
            raise ValidationError(type(node).__name__, "Node location must be set")

        # Validate location is correct type
        if not isinstance(node.location, SourceLocation):
            raise ValidationError(
                type(node).__name__, "Node location must be SourceLocation"
            )

        # Validate node_type is set
        if not hasattr(node, "node_type") or not node.node_type:
            raise ValidationError(type(node).__name__, "Node type must be set")

    def __repr__(self) -> str:
        """Return string representation of factory."""
        return "ASTNodeFactory()"


# Global factory instance for use throughout the parser
_default_factory: ASTNodeFactory | None = None


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


def create_node(
    node_class: type[ASTNode], location: SourceLocation, **kwargs: Any
) -> ASTNode:
    """Convenience function to create a node using the default factory.

    Args:
        node_class: The AST node class to create
        location: Source location for the node
        **kwargs: Additional parameters for node initialization

    Returns:
        Created AST node
    """
    return get_factory().create(node_class, location, **kwargs)
