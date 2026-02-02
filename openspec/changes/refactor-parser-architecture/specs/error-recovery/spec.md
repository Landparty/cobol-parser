# Specification: error-recovery

## ADDED Requirements

### Requirement: Parser supports FAIL_FAST error recovery mode
The system SHALL raise exceptions immediately when errors occur in production mode.

#### Scenario: FAIL_FAST raises on first error
- **WHEN** parser configured with ErrorRecoveryMode.FAIL_FAST
- **THEN** parser raises ParseError on first parsing error

#### Scenario: FAIL_FAST includes full context
- **WHEN** error raised in FAIL_FAST mode
- **THEN** error includes file, line, column, and descriptive message

#### Scenario: FAIL_FAST prevents corruption of subsequent parses
- **WHEN** error causes state corruption
- **THEN** FAIL_FAST mode forces clean rollback

### Requirement: Parser supports COLLECT_ALL error recovery mode
The system SHALL accumulate errors and continue parsing in development mode.

#### Scenario: COLLECT_ALL logs errors and continues
- **WHEN** parser configured with ErrorRecoveryMode.COLLECT_ALL
- **THEN** parser logs error but attempts to continue parsing

#### Scenario: COLLECT_ALL recovery strategy
- **WHEN** parser encounters unrecognized statement
- **THEN** parser skips tokens until next known statement start

#### Scenario: COLLECT_ALL returns all errors at end
- **WHEN** parsing completes in COLLECT_ALL mode
- **THEN** parser provides complete error report with all locations

### Requirement: ParseError hierarchy enables targeted error handling
The system SHALL provide specific error types for different circumstances.

#### Scenario: Catch TokenMismatch specifically
- **WHEN** code catches TokenMismatch exception
- **THEN** error handler knows token expectation failure occurred

#### Scenario: Catch UnexpectedEndOfInput specifically
- **WHEN** code catches UnexpectedEndOfInput exception
- **THEN** error handler knows parsing ended prematurely

#### Scenario: Catch ValidationError specifically
- **WHEN** code catches ValidationError exception
- **THEN** error handler knows AST node constraint violated

### Requirement: Error recovery maintains AST consistency
The system SHALL preserve valid AST portions during error recovery.

#### Scenario: Partial parsing with COLLECT_ALL
- **WHEN** error occurs in PROCEDURE DIVISION
- **THEN** valid IDENTIFICATION, ENVIRONMENT, DATA divisions preserved in AST

#### Scenario: Invalid statement skipped, next statement parsed
- **WHEN** statement parser fails  and recovery enabled
- **THEN** statement marked as error, next statement parsed normally

#### Scenario: Data structure validation deferred
- **WHEN** error refers to undefined data item
- **THEN** error logged but statement structure preserved

### Requirement: Error context includes diagnostic information
The system SHALL provide structured error details for debugging.

#### Scenario: Error includes source location
- **WHEN** error raised
- **THEN** error object contains file name, line, column

#### Scenario: Error includes expected vs actual
- **WHEN** TokenMismatch raised
- **THEN** error shows expected token value and actual token value

#### Scenario: Error includes recovery suggestion
- **WHEN** error message formatted for display
- **THEN** message suggests corrective action if applicable

### Requirement: Error recovery modes are configurable
The system SHALL allow changing recovery mode per parser instance.

#### Scenario: Configure error recovery at parser creation
- **WHEN** creating CobolParser with ErrorRecoveryMode parameter
- **THEN** parser uses specified recovery mode

#### Scenario: Error recovery mode affects all child parsers
- **WHEN** CobolParser creates division parsers
- **THEN** division parsers inherit error recovery mode

#### Scenario: Static recovery mode for production
- **WHEN** CobolParser created without explicit mode
- **THEN** parser defaults to ErrorRecoveryMode.FAIL_FAST

### Requirement: Error reporting aggregates all errors
The system SHALL provide comprehensive error reports.

#### Scenario: Collect multiple errors from single parse
- **WHEN** parse completes with multiple errors
- **THEN** errors accessible via parse_result.errors list

#### Scenario: Error report includes error count
- **WHEN** error report generated
- **THEN** report indicates total errors found

#### Scenario: Error report sorted by location
- **WHEN** errors reported
- **THEN** errors listed in file order (line, then column)

### Requirement: Recovery modes impact testing strategy
The system SHALL enable comprehensive validation testing.

#### Scenario: COLLECT_ALL enables invalid input testing
- **WHEN** running tests with ErrorRecoveryMode.COLLECT_ALL
- **THEN** can verify parser behavior on malformed COBOL

#### Scenario: FAIL_FAST ensures clean error boundaries
- **WHEN** running unit tests with FAIL_FAST
- **THEN** tests can verify specific error conditions independently
