# Specification: environment-division-parser

## ADDED Requirements

### Requirement: EnvironmentDivisionParser handles FILE-CONTROL section
The system SHALL parse FILE-CONTROL sections with SELECT and file descriptions.

#### Scenario: Parse SELECT statement for input file
- **WHEN** parser encounters SELECT INPUT-FILE ASSIGN TO "input.txt"
- **THEN** parser creates FileControlEntry with file name and organization

#### Scenario: Parse file organization clause
- **WHEN** parser encounters ORGANIZATION IS SEQUENTIAL
- **THEN** parser sets file organization to SEQUENTIAL

#### Scenario: Parse multiple SELECT statements
- **WHEN** parser encounters multiple SELECT statements in FILE-CONTROL
- **THEN** parser creates separate FileControlEntry for each file

### Requirement: EnvironmentDivisionParser handles CONFIGURATION SECTION
The system SHALL parse configuration paragraph settings.

#### Scenario: Parse OBJECT-COMPUTER sentence
- **WHEN** parser encounters OBJECT-COMPUTER.
- **THEN** parser captures computer type or source system information

#### Scenario: Parse SOURCE-COMPUTER sentence
- **WHEN** parser encounters SOURCE-COMPUTER.
- **THEN** parser captures source compilation environment

### Requirement: EnvironmentDivisionParser handles INPUT-OUTPUT SECTION
The system SHALL parse INPUT-OUTPUT section declarations.

#### Scenario: Parse FILE-CONTROL subsection
- **WHEN** parser encounters FILE-CONTROL section
- **THEN** parser delegates to file control parser

#### Scenario: Parse I-O-CONTROL subsection
- **WHEN** parser encounters I-O-CONTROL section
- **THEN** parser handles SAME AREA, MULTIPLE FILE, and rerun clauses

### Requirement: EnvironmentDivisionParser validates file references
The system SHALL validate SELECT clauses reference declared files.

#### Scenario: Validate file name references
- **WHEN** parser completes ENVIRONMENT DIVISION
- **THEN** parser validates all SELECT statements reference existing files

#### Scenario: Raise error for undefined file reference
- **WHEN** SELECT references undefined file
- **THEN** parser raises error or warning depending on error recovery mode

### Requirement: EnvironmentDivisionParser handles optional sections
The system SHALL gracefully handle optional CONFIGURATION and INPUT-OUTPUT sections.

#### Scenario: ENVIRONMENT DIVISION with only INPUT-OUTPUT
- **WHEN** parser encounters ENVIRONMENT DIVISION with only INPUT-OUTPUT SECTION
- **THEN** parser creates valid EnvironmentDivision node

#### Scenario: Empty ENVIRONMENT DIVISION
- **WHEN** ENVIRONMENT DIVISION contains no sections
- **THEN** parser creates empty EnvironmentDivision node
