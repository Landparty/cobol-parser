# Specification: ibm-enterprise-dialect

## ADDED Requirements

### Requirement: StatementParserRegistry supports IBM EXEC SQL statements
The system SHALL parse IBM COBOL EXEC SQL embedded SQL blocks.

#### Scenario: Parse EXEC SQL...END-EXEC block
- **WHEN** parser encounters EXEC SQL ... END-EXEC
- **THEN** parser creates SQLStatement node with SQL content preserved

#### Scenario: Parse EXEC SQL with USING clause
- **WHEN** EXEC SQL references COBOL variables with USING host-var
- **THEN** parser creates parameter references to data definitions

#### Scenario: Parse multiple EXEC SQL statements
- **WHEN** program contains multiple EXEC SQL blocks
- **THEN** each block parsed as separate statement

### Requirement: StatementParserRegistry supports IBM EXEC CICS statements
The system SHALL parse IBM CICS transaction commands.

#### Scenario: Parse EXEC CICS RECEIVE MAP
- **WHEN** parser encounters EXEC CICS RECEIVE
- **THEN** parser creates CICSReceiveStatement with map and fields

#### Scenario: Parse EXEC CICS SEND MAP
- **WHEN** parser encounters EXEC CICS SEND
- **THEN** parser creates CICSSendStatement with response handling

#### Scenario: Parse EXEC CICS error handling
- **WHEN** EXEC CICS includes RESP or ERROR clauses
- **THEN** parser creates error handling references

### Requirement: DataDivisionParser recognizes IBM COMP usage types
The system SHALL support IBM packed decimal and binary usage types.

#### Scenario: Parse COMP-3 packed decimal
- **WHEN** data item specifies USAGE IS COMP-3
- **THEN** parser calculates storage size using packed decimal formula

#### Scenario: Parse COMP-1 floating point
- **WHEN** data item specifies USAGE IS COMP-1
- **THEN** parser marks as single-precision floating point

#### Scenario: Parse COMP-2 double precision
- **WHEN** data item specifies USAGE IS COMP-2
- **THEN** parser marks as double-precision floating point

### Requirement: DataDivisionParser recognizes IBM intrinsic functions
The system SHALL support IBM-specific functions in move/evaluate targets.

#### Scenario: Parse FUNCTION LENGTH
- **WHEN** procedure contains FUNCTION LENGTH(variable)
- **THEN** parser recognizes as built-in function call

#### Scenario: Parse FUNCTION NUMVAL
- **WHEN** procedure contains FUNCTION NUMVAL(string-variable)
- **THEN** parser recognizes as numeric conversion function

#### Scenario: Parse FUNCTION UPPER-CASE
- **WHEN** procedure contains FUNCTION UPPER-CASE(variable)
- **THEN** parser recognizes as case conversion function

### Requirement: Factory registration enables IBM dialect extension
The system SHALL allow registering IBM-specific parsers at runtime.

#### Scenario: Register IBM statement parser
- **WHEN** IBM dialect module registers custom EXEC SQL parser
- **THEN** StatementParserRegistry discovers and uses it

#### Scenario: Override standard parser with IBM version
- **WHEN** IBM dialect registers enhanced version of existing parser
- **THEN** registry prioritizes IBM implementation

#### Scenario: IBM dialect operates without core modification
- **WHEN** initializing IBM dialect module
- **THEN** no changes needed to core parser code

### Requirement: DataDivisionParser supports IBM file organization types
The system SHALL recognize IBM-specific file organizations.

#### Scenario: Parse ORGANIZATION IS INDEXED
- **WHEN** SELECT statement specifies INDEXED file
- **THEN** parser creates IndexedFileDescriptor with key information

#### Scenario: Parse ORGANIZATION IS RELATIVE
- **WHEN** SELECT statement specifies RELATIVE file
- **THEN** parser creates RelativeFileDescriptor with record numbering

### Requirement: Preserves existing COBOL 85 standard compatibility
The system SHALL continue supporting standard COBOL statements.

#### Scenario: Standard MOVE statement still parses correctly
- **WHEN** program uses standard COBOL MOVE
- **THEN** parser creates standard MoveStatement unchanged

#### Scenario: Standard data definitions still parse correctly  
- **WHEN** data items use standard COBOL USAGE clauses
- **THEN** parser processes standard types without interference
