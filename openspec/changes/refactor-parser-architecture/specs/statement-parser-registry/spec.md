# Specification: statement-parser-registry

## ADDED Requirements

### Requirement: StatementParserRegistry dispatches statement parsing
The system SHALL provide a `StatementParserRegistry` that maintains and discovers statement-specific parsers.

#### Scenario: Registry finds parser for MOVE statement
- **WHEN** registry requests parser for MOVE statement
- **THEN** registry returns a `MoveStatementParser` instance

#### Scenario: Registry finds parser for DISPLAY statement
- **WHEN** registry requests parser for DISPLAY statement
- **THEN** registry returns a `DisplayStatementParser` instance

#### Scenario: Registry finds parser for IF statement
- **WHEN** registry requests parser for IF statement
- **THEN** registry returns an `IfStatementParser` instance

### Requirement: Registry supports dynamic parser registration
The system SHALL allow registering new statement parsers at runtime.

#### Scenario: Register custom statement parser
- **WHEN** user calls `StatementParserRegistry.register(CustomStatementParser())`
- **THEN** registry can discover parser for custom statement type

#### Scenario: Parser matching respects registration order
- **WHEN** multiple parsers could match ambiguous token sequence
- **THEN** registry uses first registered parser that matches

### Requirement: Registry raises error for unknown statements
The system SHALL raise `UnknownStatementError` when no parser matches token stream.

#### Scenario: Unrecognized statement keyword
- **WHEN** registry processes token stream starting with unrecognized keyword
- **THEN** registry raises `UnknownStatementError` with context information

#### Scenario: Error includes current token position
- **WHEN** registry fails to find parser
- **THEN** error message includes line number and token value

### Requirement: Registry supports IBM Enterprise COBOL extensions
The system SHALL discover parsers for IBM-specific statements (EXEC SQL, EXEC CICS).

#### Scenario: Parser for EXEC SQL statement
- **WHEN** registry requests parser for EXEC SQL
- **THEN** registry returns appropriate SQL statement parser

#### Scenario: Parser for EXEC CICS statement
- **WHEN** registry requests parser for EXEC CICS
- **THEN** registry returns appropriate CICS transaction parser

### Requirement: Registry provides parser discovery without consuming tokens
The system SHALL allow checking if a parser exists without modifying token stream.

#### Scenario: Check parser existence before consumption
- **WHEN** registry checks for parser match
- **THEN** token stream position remains unchanged
