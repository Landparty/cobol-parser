# Specification: data-division-parser

## ADDED Requirements

### Requirement: DataDivisionParser handles FILE SECTION
The system SHALL parse FILE SECTION with file descriptors (FD) and record descriptions.

#### Scenario: Parse FD clause
- **WHEN** parser encounters FD filename
- **THEN** parser creates FileDescriptor with file name and properties

#### Scenario: Parse record description under FD
- **WHEN** parser encounters data item structure following FD
- **THEN** parser creates hierarchical record structure

#### Scenario: Parse multiple records per file
- **WHEN** parser encounters multiple 01-level items under single FD
- **THEN** parser creates separate record structures for each

### Requirement: DataDivisionParser handles WORKING-STORAGE SECTION
The system SHALL parse WORKING-STORAGE data definitions with all levels and clauses.

#### Scenario: Parse elementary data items
- **WHEN** parser encounters "02 FIELD-NAME PIC X(10)"
- **THEN** parser creates DataItem with picture, level, and name

#### Scenario: Parse group data items
- **WHEN** parser encounters 01-level item containing 02-level subordinates
- **THEN** parser creates hierarchical group structure

#### Scenario: Parse OCCURS clause
- **WHEN** parser encounters "02 TABLE-ITEM OCCURS 100 TIMES PIC 9(5)"
- **THEN** parser creates array/table structure with occurrence count

### Requirement: DataDivisionParser handles picture clause variations
The system SHALL parse all COBOL picture clause formats including IBM extensions.

#### Scenario: Parse numeric picture
- **WHEN** parser encounters PIC 9(5)V99 (packed decimal)
- **THEN** parser correctly identifies numeric type and precision

#### Scenario: Parse alphanumeric picture
- **WHEN** parser encounters PIC X(15)
- **THEN** parser sets string type with length

#### Scenario: Parse COMP-3 packed decimal
- **WHEN** parser encounters "USAGE IS COMP-3"
- **THEN** parser marks as packed decimal with correct storage size

### Requirement: DataDivisionParser handles VALUE clauses
The system SHALL parse initialization values for data items.

#### Scenario: Parse literal value
- **WHEN** parser encounters VALUE IS "INITIAL"
- **THEN** parser captures initialization value

#### Scenario: Parse numeric value
- **WHEN** parser encounters VALUE IS 0 or VALUE IS +99.99
- **THEN** parser captures numeric value correctly

### Requirement: DataDivisionParser handles LINKAGE SECTION
The system SHALL parse LINKAGE SECTION data definitions for parameters.

#### Scenario: Parse LINKAGE SECTION items
- **WHEN** parser encounters LINKAGE SECTION with parameters
- **THEN** parser creates parameter definitions

### Requirement: DataDivisionParser validates hierarchical structure
The system SHALL validate level numbering and hierarchy consistency.

#### Scenario: Validate level numbers in sequence
- **WHEN** parser processes data items with levels 01, 02, 02, 03
- **THEN** parser creates correct hierarchical structure

#### Scenario: Raise error for invalid level jump
- **WHEN** data item level jumps from 02 to 05 skipping 03, 04
- **THEN** parser raises error or creates implicit groups depending on mode
