# Specification: division-parser-factory

## ADDED Requirements

### Requirement: DivisionParserFactory instantiates division parsers
The system SHALL provide a `DivisionParserFactory` class that creates appropriate division parser instances based on division name.

#### Scenario: Create IDENTIFICATION division parser
- **WHEN** factory receives "IDENTIFICATION" division name
- **THEN** factory returns an `IdentificationDivisionParser` instance

#### Scenario: Create ENVIRONMENT division parser
- **WHEN** factory receives "ENVIRONMENT" division name
- **THEN** factory returns an `EnvironmentDivisionParser` instance

#### Scenario: Create DATA division parser
- **WHEN** factory receives "DATA" division name
- **THEN** factory returns a `DataDivisionParser` instance

#### Scenario: Create PROCEDURE division parser
- **WHEN** factory receives "PROCEDURE" division name
- **THEN** factory returns a `ProcedureDivisionParser` instance

### Requirement: Factory raises error for unknown division
The system SHALL raise `DivisionNotFoundError` when requesting a parser for an unknown division.

#### Scenario: Unknown division name
- **WHEN** factory receives "UNKNOWN" as division name
- **THEN** factory raises `DivisionNotFoundError` with descriptive message

#### Scenario: Case-insensitive division matching
- **WHEN** factory receives "identification" (lowercase)
- **THEN** factory normalizes to uppercase and returns correct parser

### Requirement: Factory supports extensibility for custom divisions
The system SHALL allow registering custom division parsers without modifying factory code.

#### Scenario: Register custom division parser
- **WHEN** user calls `DivisionParserFactory.register("CUSTOM", CustomDivisionParser)`
- **THEN** factory can create parser for "CUSTOM" division on subsequent calls

#### Scenario: Override existing division parser
- **WHEN** user registers a new parser for existing division "PROCEDURE"
- **THEN** factory uses the new parser instead of default `ProcedureDivisionParser`

### Requirement: Factory implements singleton pattern
The system SHALL maintain single instance of each parser type for efficiency.

#### Scenario: Parser instances are cached
- **WHEN** factory creates parser twice for same division
- **THEN** both calls return same instance (or equivalent state)
