# Specification: solid-architecture

## ADDED Requirements

### Requirement: Single Responsibility Principle - each parser handles one division or statement
The system SHALL assign single responsibility to each parser class.

#### Scenario: EnvironmentDivisionParser handles only ENVIRONMENT division
- **WHEN** examining EnvironmentDivisionParser
- **THEN** class contains only logic for parsing ENVIRONMENT, not other divisions

#### Scenario: DisplayStatementParser handles only DISPLAY statements
- **WHEN** examining DisplayStatementParser
- **THEN** class contains logic specific to DISPLAY, not other statements

#### Scenario: TokenStream handles only token navigation
- **WHEN** examining TokenStream
- **THEN** class provides token access without parsing logic

### Requirement: Open/Closed Principle - open for extension, closed for modification
The system SHALL support adding new parsers without modifying core.

#### Scenario: Add new statement parser without modifying registry
- **WHEN** creating new statement parser implementing IStatementParser
- **THEN** parser can register with registry without modifying existing code

#### Scenario: Add new division parser via factory registration
- **WHEN** registering custom division parser
- **THEN** factory can instantiate without changes to factory code

#### Scenario: Add new error type extending ParseError
- **WHEN** creating new error class extending ParseError
- **THEN** error handling works without modifications to error handling code

### Requirement: Liskov Substitution Principle - all IDivisionParser implementations are substitutable
The system SHALL allow swapping parser implementations without changing caller.

#### Scenario: Substitute dialect-specific division parser
- **WHEN** dialect provides custom EnvironmentDivisionParser
- **THEN** can substitute without affecting CobolParser orchestration

#### Scenario: Substitute statement parser from registry
- **WHEN** registry returns different IStatementParser implementation
- **THEN** ProcedureDivisionParser handles seamlessly

### Requirement: Interface Segregation Principle - clients depend on minimal interfaces
The system SHALL define minimal, focused interfaces.

#### Scenario: IDivisionParser interface minimal
- **WHEN** examining IDivisionParser
- **THEN** interface contains only necessary methods (parse, can_parse)

#### Scenario: IStatementParser interface minimal
- **WHEN** examining IStatementParser
- **THEN** interface contains only necessary methods (parse, matches)

#### Scenario: ITokenStream interface minimal
- **WHEN** examining ITokenStream
- **THEN** interface contains only navigation methods (peek, consume, expect)

### Requirement: Dependency Inversion Principle - depend on abstractions, not concretions
The system SHALL have CobolParser depend on interfaces only.

#### Scenario: CobolParser uses DivisionParserFactory not concrete parsers
- **WHEN** examining CobolParser
- **THEN** does not directly instantiate IdentificationDivisionParser, etc.

#### Scenario: CobolParser uses StatementParserRegistry not concrete statement parsers
- **WHEN** ProcedureDivisionParser seeks statement parser
- **THEN** uses registry interface, not concrete parser classes

#### Scenario: All parsers depend on ITokenStream interface
- **WHEN** parsers access token stream
- **THEN** use TokenStream through ITokenStream interface contract

### Requirement: Clean code naming conventions
The system SHALL use clear, consistent naming throughout codebase.

#### Scenario: Parser classes have descriptive names
- **WHEN** examining parser classes
- **THEN** names clearly indicate purpose (e.g., EnvironmentDivisionParser)

#### Scenario: Method names use action verbs
- **WHEN** examining parser methods
- **THEN** methods named with verbs (parse, validate, extract)

#### Scenario: Variable names indicate purpose
- **WHEN** examining variable names
- **THEN** names are descriptive not abbreviated (token_stream not ts)

### Requirement: Directory organization reflects architecture
The system SHALL organize files by architectural component.

#### Scenario: Division parsers in divisions/ directory
- **WHEN** looking for division parser code
- **THEN** found in cobolparser/parsers/divisions/

#### Scenario: Statement parsers in statements/ directory
- **WHEN** looking for statement parser code
- **THEN** found in cobolparser/parsers/statements/

#### Scenario: Abstractions in core/ directory
- **WHEN** looking for interfaces
- **THEN** found in cobolparser/core/ with descriptive names
