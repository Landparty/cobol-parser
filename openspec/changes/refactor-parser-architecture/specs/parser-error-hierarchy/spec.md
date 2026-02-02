# Specification: parser-error-hierarchy

## ADDED Requirements

### Requirement: ParseError base class provides structured errors
The system SHALL provide `ParseError` base class with consistent error information.

#### Scenario: ParseError includes message
- **WHEN** parser raises ParseError
- **THEN** error contains descriptive message

#### Scenario: ParseError includes source location
- **WHEN** parser raises ParseError
- **THEN** error contains file, line, and column of error

#### Scenario: ParseError formatting for display
- **WHEN** error formatted for console/log output
- **THEN** format includes location and message in readable form

### Requirement: TokenMismatch error for token validation failures
The system SHALL provide `TokenMismatch` exception for expect() failures.

#### Scenario: TokenMismatch includes expected and actual values
- **WHEN** parser expects "PROCEDURE" but gets "DATA"
- **THEN** error shows both expected and actual token values

#### Scenario: TokenMismatch includes position context
- **WHEN** token mismatch occurs
- **THEN** error indicates token position in stream

### Requirement: UnexpectedEndOfInput error for stream exhaustion
The system SHALL provide `UnexpectedEndOfInput` exception.

#### Scenario: UnexpectedEndOfInput on peek after end
- **WHEN** parser peeks beyond stream end
- **THEN** error indicates unexpected stream exhaustion

#### Scenario: UnexpectedEndOfInput context
- **WHEN** error occurs
- **THEN** error indicates what was expected before exhaustion

### Requirement: DivisionNotFoundError for unknown divisions
The system SHALL provide `DivisionNotFoundError` for invalid division names.

#### Scenario: Unknown division in factory
- **WHEN** factory requests parser for "UNKNOWN" division
- **THEN** `DivisionNotFoundError` raised with division name

### Requirement: UnknownStatementError for unrecognized statements
The system SHALL provide `UnknownStatementError` when registry cannot match statement.

#### Scenario: Unrecognized statement keyword
- **WHEN** registry processes unknown statement keyword
- **THEN** `UnknownStatementError` raised with token details

### Requirement: ValidationError for model validation failures
The system SHALL provide `ValidationError` for AST node constraint violations.

#### Scenario: Missing required field
- **WHEN** factory creates node without required field
- **THEN** `ValidationError` raised with field name and reason

#### Scenario: Invalid field value
- **WHEN** factory receives invalid value type
- **THEN** `ValidationError` raised with expected/actual types

### Requirement: ParseError supports error recovery modes
The system SHALL handle errors differently based on recovery mode.

#### Scenario: FAIL_FAST mode raises immediately
- **WHEN** error recovery mode is FAIL_FAST and error occurs
- **THEN** parser raises exception immediately

#### Scenario: COLLECT_ALL mode accumulates errors
- **WHEN** error recovery mode is COLLECT_ALL and error occurs
- **THEN** parser logs error and continues parsing

#### Scenario: Error collection provides diagnostic report
- **WHEN** parsing completes with errors
- **THEN** parser provides complete error list with all locations
