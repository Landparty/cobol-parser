# Specification: procedure-division-parser

## ADDED Requirements

### Requirement: ProcedureDivisionParser orchestrates statement parsing
The system SHALL parse PROCEDURE DIVISION and delegate statement parsing to registry.

#### Scenario: Parse paragraph structure
- **WHEN** parser encounters "MAIN-PROCEDURE."
- **THEN** parser creates Paragraph node for procedure

#### Scenario: Parse section structure
- **WHEN** parser encounters "SECTION-NAME SECTION."
- **THEN** parser creates Section node containing paragraphs

#### Scenario: Parse sequential statements
- **WHEN** parser encounters multiple statements in paragraph
- **THEN** parser creates list of Statement nodes in order

### Requirement: ProcedureDivisionParser delegates to StatementParserRegistry
The system SHALL use StatementParserRegistry to parse individual statements.

#### Scenario: Delegate MOVE statement to registry
- **WHEN** parser encounters MOVE statement
- **THEN** parser obtains MoveStatementParser from registry

#### Scenario: Delegate IF statement to registry
- **WHEN** parser encounters IF statement
- **THEN** parser obtains IfStatementParser from registry

#### Scenario: Handle nested statements
- **WHEN** parser encounters IF with nested MOVE statements
- **THEN** parser correctly parses nested statement structure

### Requirement: ProcedureDivisionParser handles control flow
The system SHALL correctly parse PERFORM, EVALUATE, and GO TO statements.

#### Scenario: Parse PERFORM UNTIL loop
- **WHEN** parser encounters "PERFORM UNTIL condition"
- **THEN** parser creates loop structure with termination condition

#### Scenario: Parse EVALUATE (CASE) statement
- **WHEN** parser encounters EVALUATE expression with WHEN clauses
- **THEN** parser creates case structure with branches

#### Scenario: Parse GO TO statement
- **WHEN** parser encounters GO TO paragraph-name
- **THEN** parser creates branch reference

### Requirement: ProcedureDivisionParser maintains execution context
The system SHALL track variable scope and available symbols from DATA DIVISION.

#### Scenario: Resolve variable references to DATA DIVISION
- **WHEN** parser encounters variable reference in MOVE statement
- **THEN** parser can resolve to data definition from working storage

#### Scenario: Track scope in nested performs
- **WHEN** parser enters nested PERFORM blocks
- **THEN** parser maintains scope stack for symbol resolution

### Requirement: ProcedureDivisionParser handles statement terminators
The system SHALL correctly identify statement boundaries and periods.

#### Scenario: Single statement ending with period
- **WHEN** parser encounters "DISPLAY 'Done'."
- **THEN** parser correctly terminates statement at period

#### Scenario: Implicit statement termination in nested structures
- **WHEN** parser encounters nested IF with separate periods
- **THEN** parser correctly manages period scope

### Requirement: ProcedureDivisionParser supports error recovery
The system SHALL continue parsing after encountering parse errors.

#### Scenario: Skip unrecognized statement and continue
- **WHEN** error recovery mode is COLLECT_ALL and unrecognized statement found
- **THEN** parser logs error and continues with next statement

#### Scenario: Report all accumulated errors after completion
- **WHEN** parsing completes with errors
- **THEN** parser reports complete list of errors with locations
