# Specification: token-stream-abstraction

## ADDED Requirements

### Requirement: TokenStream provides peek operation
The system SHALL allow examining tokens without consuming them.

#### Scenario: Peek at next token
- **WHEN** parser calls `peek()` on token stream
- **THEN** token stream returns next token without advancing position

#### Scenario: Peek with offset for lookahead
- **WHEN** parser calls `peek(offset=2)` 
- **THEN** token stream returns token at position+2 without consuming

#### Scenario: Peek behavior is repeatable
- **WHEN** parser calls `peek()` twice in succession
- **THEN** both calls return identical token

### Requirement: TokenStream provides consume operation
The system SHALL advance stream position and return current token.

#### Scenario: Consume advances position
- **WHEN** parser calls `consume()`
- **THEN** next `peek()` returns different token

#### Scenario: Consume return value matches previous peek
- **WHEN** parser peeks then consumes
- **THEN** consume returns identical token to previous peek

### Requirement: TokenStream provides expect operation
The system SHALL validate token value before consuming.

#### Scenario: Expect matching token
- **WHEN** parser calls `expect("PROCEDURE")`  and next token is "PROCEDURE"
- **THEN** stream consumes and returns token

#### Scenario: Expect non-matching token raises error
- **WHEN** parser calls `expect("DATA")` and next token is "PROCEDURE"
- **THEN** stream raises `TokenMismatch` error

#### Scenario: Expect is case-insensitive
- **WHEN** parser calls `expect("procedure")` and next token is "PROCEDURE"
- **THEN** stream matches successfully

### Requirement: TokenStream provides end detection
The system SHALL indicate when stream is exhausted.

#### Scenario: Check if stream is empty
- **WHEN** parser calls `is_empty()`
- **THEN** stream returns true when all tokens consumed, false otherwise

#### Scenario: Peek on empty stream raises error
- **WHEN** parser calls `peek()` on exhausted stream
- **THEN** stream raises `UnexpectedEndOfInput` error

### Requirement: TokenStream supports lookahead optimization
The system SHALL maintain efficient lookahead buffer.

#### Scenario: Lookahead buffer improves performance
- **WHEN** parser repeatedly peeks with offsets 0-2
- **THEN** tokens accessed from buffer without list traversal

#### Scenario: Buffer size is configurable
- **WHEN** TokenStream created with `lookahead=5`
- **THEN** stream maintains 5-token lookahead buffer

### Requirement: TokenStream includes source location tracking
The system SHALL track file, line, and column information.

#### Scenario: Token includes source location
- **WHEN** parser examines token from stream
- **THEN** token contains file path, line number, column

#### Scenario: Stream provides current location
- **WHEN** parser calls `current_location()`
- **THEN** stream returns location of next unconsumed token
