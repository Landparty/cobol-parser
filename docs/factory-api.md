# ASTNodeFactory API Documentation

## Overview

`ASTNodeFactory` is a centralized, validated factory for creating AST nodes in the COBOL parser. It ensures all nodes are created consistently with proper validation and error handling.

## Quick Start

### Basic Usage

```python
from cobolparser.core.ast_factory import get_factory, create_node
from cobolparser.models.statements import DisplayStatement
from cobolparser.models.ast_base import SourceLocation

# Get the default factory
factory = get_factory()

# Create a node
location = SourceLocation(line=10, column=5)
display_stmt = factory.create(DisplayStatement, location)

# Or use the convenience function
display_stmt = create_node(DisplayStatement, location)
```

### With Metadata and Context

```python
factory = get_factory()
location = SourceLocation(line=10, column=5)

# Create and configure in one chain
node = (factory
    .create(DisplayStatement, location))

# Add metadata
factory.with_metadata(node, {
    'priority': 'high',
    'statement_type': 'IO'
})

# Set division context
factory.with_context(node, 'PROCEDURE', 'MAIN-SECTION')

print(f"Node: {node.node_type}")
print(f"Priority: {node.get_metadata('priority')}")
print(f"Division: {node.division_name}")
```

## Class Reference

### ASTNodeFactory

Main factory class for creating validated AST nodes.

#### Methods

##### create(node_class, location, **kwargs)

Create a new AST node with validation.

**Parameters:**
- `node_class` (Type[ASTNode]): The AST node class to instantiate
- `location` (SourceLocation): Source code location for the node
- `**kwargs`: Additional parameters for node initialization

**Returns:**
- ASTNode: Created and validated node

**Raises:**
- `TypeError`: If node_class is not an ASTNode subclass
- `ValidationError`: If post-creation validation fails

**Example:**
```python
factory = get_factory()
location = SourceLocation(line=5, column=1)
node = factory.create(DisplayStatement, location)
```

##### with_metadata(node, metadata)

Add metadata key-value pairs to a node.

**Parameters:**
- `node` (ASTNode): The node to add metadata to
- `metadata` (Dict[str, Any]): Metadata key-value pairs

**Returns:**
- ASTNode: The same node (for chaining)

**Example:**
```python
factory = get_factory()
node = factory.create(MoveStatement, location)

factory.with_metadata(node, {
    'statement_index': 5,
    'scope': 'paragraph',
    'has_conditions': True
})

# Check metadata
index = node.get_metadata('statement_index')  # 5
```

##### with_context(node, division_name, section_name=None)

Set the division and section context for a node.

**Parameters:**
- `node` (ASTNode): The node to set context on
- `division_name` (str): Name of the containing division
- `section_name` (Optional[str]): Name of the containing section

**Returns:**
- ASTNode: The same node (for chaining)

**Example:**
```python
factory = get_factory()
node = factory.create(DisplayStatement, location)

factory.with_context(node, 'PROCEDURE', 'MAIN-PARAGRAPH')

# Check context
print(node.division_name)   # 'PROCEDURE'
print(node.section_name)    # 'MAIN-PARAGRAPH'
```

##### validate_node_type(node, expected_type)

Validate that a node is the correct type.

**Parameters:**
- `node` (ASTNode): Node to validate
- `expected_type` (Type[ASTNode]): Expected node class

**Returns:**
- bool: True if validation passes

**Raises:**
- `NodeTypeError`: If node type doesn't match

**Example:**
```python
factory = get_factory()
node = factory.create(DisplayStatement, location)

# Validate type
assert factory.validate_node_type(node, DisplayStatement)

# This would raise NodeTypeError:
# factory.validate_node_type(node, MoveStatement)
```

##### validate_required_fields(node, required_fields, node_type_name="")

Validate that required fields are present on a node.

**Parameters:**
- `node` (ASTNode): Node to validate
- `required_fields` (List[str]): Required field names
- `node_type_name` (str): Optional node type for error context

**Returns:**
- bool: True if all fields are present and non-None

**Raises:**
- `FieldValidationError`: If required field is missing or None

**Example:**
```python
factory = get_factory()
node = factory.create(DisplayStatement, location)

# Validate fields exist
assert factory.validate_required_fields(
    node,
    ['location', 'node_type'],
    'DisplayStatement'
)
```

##### validate_field_types(node, field_types, node_type_name="")

Validate that field types match expectations.

**Parameters:**
- `node` (ASTNode): Node to validate
- `field_types` (Dict[str, type]): Field name to expected type mapping
- `node_type_name` (str): Optional node type for error context

**Returns:**
- bool: True if all field types are correct

**Raises:**
- `FieldValidationError`: If field type doesn't match

**Example:**
```python
factory = get_factory()
node = factory.create(DisplayStatement, location)

# Validate field types
assert factory.validate_field_types(
    node,
    {
        'location': SourceLocation,
        'node_type': str
    },
    'DisplayStatement'
)
```

##### register_validator(node_type, validator_config)

Register a custom validator for a node type.

**Parameters:**
- `node_type` (str): Name of the node type
- `validator_config` (Dict[str, Any]): Configuration with:
  - `"class"`: The node class
  - `"required_fields"`: List of required field names
  - `"field_types"`: Dict of field name to type

**Returns:**
- None

**Example:**
```python
factory = get_factory()

config = {
    "class": DisplayStatement,
    "required_fields": ["location", "node_type"],
    "field_types": {"location": SourceLocation}
}

factory.register_validator("DisplayStatement", config)
```

##### get_creation_count()

Get the total number of nodes created by this factory.

**Returns:**
- int: Number of nodes created

**Example:**
```python
factory = get_factory()
initial = factory.get_creation_count()

for _ in range(100):
    factory.create(DisplayStatement, location)

created = factory.get_creation_count() - initial
print(f"Created {created} nodes")  # 100
```

##### get_validation_errors()

Get all validation errors encountered.

**Returns:**
- List[str]: List of error messages

**Example:**
```python
factory = get_factory()

errors = factory.get_validation_errors()
if errors:
    for error in errors:
        print(f"Error: {error}")
```

##### clear_validation_errors()

Clear the validation error log.

**Returns:**
- None

**Example:**
```python
factory = get_factory()
factory.clear_validation_errors()
```

## Global Factory Functions

### get_factory()

Get the default global factory instance.

**Returns:**
- ASTNodeFactory: The singleton factory instance

**Example:**
```python
from cobolparser.core.ast_factory import get_factory

factory = get_factory()
# Returns the same instance every time
assert factory is get_factory()
```

### set_factory(factory)

Replace the default global factory instance.

**Parameters:**
- `factory` (ASTNodeFactory): New factory instance to use globally

**Returns:**
- None

**Example:**
```python
from cobolparser.core.ast_factory import set_factory, ASTNodeFactory

# Create custom factory
custom = ASTNodeFactory()
set_factory(custom)

# Now get_factory() returns custom instance
```

### create_node(node_class, location, **kwargs)

Convenience function to create a node using the default factory.

**Parameters:**
- `node_class` (Type[ASTNode]): AST node class to create
- `location` (SourceLocation): Source location
- `**kwargs`: Additional node parameters

**Returns:**
- ASTNode: Created and validated node

**Example:**
```python
from cobolparser.core.ast_factory import create_node
from cobolparser.models.statements import DisplayStatement

location = SourceLocation(line=10, column=5)
node = create_node(DisplayStatement, location)
```

## Exception Reference

### NodeTypeError

Raised when node type validation fails.

**Attributes:**
- `message` (str): Error message with expected and actual types

**Example:**
```python
from cobolparser.core.ast_factory import NodeTypeError

try:
    factory.validate_node_type(node, MoveStatement)
except NodeTypeError as e:
    print(f"Type mismatch: {e}")
```

### FieldValidationError

Raised when field validation fails.

**Attributes:**
- `message` (str): Error message with field name and reason

**Example:**
```python
from cobolparser.core.ast_factory import FieldValidationError

try:
    factory.validate_required_fields(node, ['location', 'invalid_field'])
except FieldValidationError as e:
    print(f"Field missing: {e}")
```

## Best Practices

### 1. Always Use Factory for Node Creation

**Good:**
```python
factory = get_factory()
node = factory.create(DisplayStatement, location)
```

**Avoid:**
```python
# Don't create directly - loses validation
node = DisplayStatement(location)
```

### 2. Set Context Early

```python
# Do this right after creation
factory = get_factory()
node = factory.create(DisplayStatement, location)
factory.with_context(node, 'PROCEDURE', 'MAIN')
```

### 3. Add Metadata for Analysis Tools

```python
# Metadata helps debuggers and analysis tools
factory.with_metadata(node, {
    'line_in_source': 42,
    'statement_type': 'IO',
    'nested_level': 3
})
```

### 4. Handle Validation Errors

```python
try:
    node = factory.create(DisplayStatement, location)
except (NodeTypeError, FieldValidationError) as e:
    # Handle creation errors
    logger.error(f"Failed to create node: {e}")
    raise
```

### 5. Check Factory Statistics

```python
# Monitor creation activity
count = factory.get_creation_count()
errors = factory.get_validation_errors()

if len(errors) > 0:
    logger.warning(f"Factory errors: {errors}")
```

## Integration with Custom Parsers

When implementing custom statement parsers:

```python
from cobolparser.core.interfaces import IStatementParser
from cobolparser.core.ast_factory import get_factory

class CustomStatementParser(IStatementParser):
    def parse(self, token_stream):
        start_token = token_stream.consume()
        location = start_token.location
        
        # Use factory for node creation
        factory = get_factory()
        node = factory.create(CustomStatement, location)
        
        # Add context
        factory.with_context(node, 'PROCEDURE')
        
        # Add metadata
        factory.with_metadata(node, {
            'custom_type': 'specialized'
        })
        
        # Parse statement...
        # (rest of parsing logic)
        
        return node
```

## Performance Characteristics

- **Creation speed:** ~0.74 microseconds per node (with validation)
- **Throughput:** ~1.4 million nodes per second
- **Memory:** Minimal overhead (~200 bytes per factory instance)

See [Factory Performance Benchmarks](factory-performance.md) for detailed performance analysis.

## Thread Safety

The default factory is a singleton. For multi-threaded applications:

```python
# Option 1: Use thread-local factory
import threading

_thread_factories = threading.local()

def get_thread_factory():
    if not hasattr(_thread_factories, 'factory'):
        _thread_factories.factory = ASTNodeFactory()
    return _thread_factories.factory

# Option 2: Create separate factories per thread
factory = ASTNodeFactory()  # Thread-safe to create multiple
```

## Extending the Factory

To add custom validation:

```python
factory = get_factory()

# Register custom validator
validator_config = {
    "class": CustomStatement,
    "required_fields": ["location", "custom_field"],
    "field_types": {"location": SourceLocation, "custom_field": str}
}

factory.register_validator("CustomStatement", validator_config)

# Now validation includes custom rules
node = factory.create(CustomStatement, location)
```

## See Also

- [Parser Architecture Guide](PARSER_INVOCATION_GUIDE.md)
- [Factory Performance Benchmarks](factory-performance.md)
- [Extension Guide for New Statement Parsers](factory-extension-guide.md)

