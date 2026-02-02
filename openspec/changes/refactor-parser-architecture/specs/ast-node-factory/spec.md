# Specification: ast-node-factory

## ADDED Requirements

### Requirement: ASTNodeFactory creates AST nodes with validation
The system SHALL provide centralized node creation through `ASTNodeFactory` with automatic validation.

#### Scenario: Create program node
- **WHEN** factory creates a Program node with name and location
- **THEN** factory validates node state and returns valid `ProgramNode`

#### Scenario: Create data item node
- **WHEN** factory creates a DataItem with picture clause and level
- **THEN** factory validates picture clause syntax before returning node

#### Scenario: Create statement node
- **WHEN** factory creates a statement (e.g., MoveStatement) with required fields
- **THEN** factory validates statement structure matches grammar rules

### Requirement: Factory enforces required node fields
The system SHALL raise validation error for missing required fields.

#### Scenario: Missing required field raises error
- **WHEN** factory attempts to create node without required field
- **THEN** factory raises `ValidationError` with field name

#### Scenario: Invalid field type raises error
- **WHEN** factory receives wrong type for node field
- **THEN** factory raises `ValidationError` with expected/actual types

### Requirement: Factory handles node inheritance and subtypes
The system SHALL correctly create specialized node types based on context.

#### Scenario: Create typed data item
- **WHEN** factory creates data item with COMP-3 clause
- **THEN** factory creates `PackedDecimalDataItem` subtype

#### Scenario: Create division node
- **WHEN** factory creates appropriate division node
- **THEN** factory returns correct division subtype (e.g., `ProcedureDivision`)

### Requirement: Factory sets source location metadata automatically
The system SHALL attach source location information to all created nodes.

#### Scenario: Node includes source location
- **WHEN** factory creates node with provided location
- **THEN** node's `location` field contains file, line, and column information

#### Scenario: Missing location handled gracefully
- **WHEN** factory creates node without explicit location
- **THEN** node receives default/inferred location value

### Requirement: Factory supports custom node types through registration
The system SHALL enable registering factory methods for new node types.

#### Scenario: Register custom node factory method
- **WHEN** user registers factory method for custom node type
- **THEN** factory can create instances of custom type

### Requirement: Factory ensures semantic consistency across nodes
The system SHALL validate relationships between related nodes.

#### Scenario: Validate data division before procedure division
- **WHEN** factory creates procedure division statements
- **THEN** factory can reference validated data definitions from data division
