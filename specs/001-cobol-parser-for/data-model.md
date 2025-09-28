# Data Model: COBOL Parser Object Structure

**Feature**: COBOL Parser for Python  
**Date**: 2025-09-27  
**Context**: Entity definitions incorporating clarified requirements for configurable memory, JSON export, and IBM Enterprise COBOL focus

## Core Entities

### Program
Represents a complete COBOL program with all its divisions and metadata.

**Attributes**:
- `name: str` - Program identifier from PROGRAM-ID
- `identification_division: Optional[IdentificationDivision]` - Always present for valid programs
- `environment_division: Optional[EnvironmentDivision]` - IBM Enterprise COBOL specifics
- `data_division: Optional[DataDivision]` - Variable and file declarations
- `procedure_division: Optional[ProcedureDivision]` - Executable logic
- `source_lines: int` - Total line count for memory tracking
- `parse_metadata: ParseMetadata` - Parsing statistics including memory usage
- `dialect: str` - Detected/configured COBOL dialect (default: "IBM Enterprise COBOL")

**Key Methods**:
- `to_json(config: SerializationConfig = None) -> str` - **NEW**: JSON export capability
- `get_memory_usage() -> MemoryStats` - **NEW**: Memory tracking for configurable limits
- `validate_structure() -> List[ValidationError]` - **NEW**: Enhanced validation

**Relationships**:
- Contains 0-4 Division entities (all optional for error recovery)
- Has 1 ParseMetadata entity with memory tracking
- Supports lazy loading of divisions for memory efficiency

**Validation Rules**:
- Should have IDENTIFICATION division (warning if missing, not error in collection mode)
- Division order should follow COBOL standards (configurable error vs warning)
- Program name must be valid COBOL identifier when present

### Division
Represents one of the four standard COBOL divisions with its sections and content.

**Attributes**:
- `type: DivisionType` - Enum: IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE
- `name: str` - Full division name
- `sections: List[Section]` - Sections within this division
- `line_range: LineRange` - Source line numbers for this division

**Relationships**:
- Belongs to 1 Program
- Contains 0-many Section entities

**Validation Rules**:
- Division type must be valid COBOL division
- Sections must be appropriate for the division type
- Line ranges must not overlap with other divisions

### Section
Represents a section within a division (e.g., WORKING-STORAGE SECTION, INPUT-OUTPUT SECTION).

**Attributes**:
- `name: str` - Section name (e.g., "WORKING-STORAGE", "INPUT-OUTPUT")
- `type: SectionType` - Enum of valid section types per division
- `paragraphs: List[Paragraph]` - Paragraphs within this section
- `declarations: List[Declaration]` - Variable/file declarations (DATA division)
- `line_range: LineRange` - Source line numbers for this section

**Relationships**:
- Belongs to 1 Division
- Contains 0-many Paragraph entities
- Contains 0-many Declaration entities (for DATA division sections)

**Validation Rules**:
- Section type must be valid for parent division
- Declarations only allowed in DATA division sections
- Paragraphs only allowed in PROCEDURE division sections

### Paragraph
Represents a paragraph in the PROCEDURE division containing executable statements.

**Attributes**:
- `name: str` - Paragraph name/label
- `statements: List[Statement]` - COBOL statements in this paragraph
- `line_range: LineRange` - Source line numbers
- `is_labeled: bool` - Whether paragraph has an explicit label

**Relationships**:
- Belongs to 1 Section (PROCEDURE division only)
- Contains 0-many Statement entities

**Validation Rules**:
- Only allowed in PROCEDURE division sections
- Must contain at least one statement or be explicitly empty
- Statement order must be preserved from source

### Statement
Represents an individual COBOL statement with its type and parameters.

**Attributes**:
- `type: StatementType` - Enum of COBOL statement types (MOVE, IF, PERFORM, etc.)
- `raw_text: str` - Original COBOL statement text
- `parameters: Dict[str, Any]` - Parsed statement parameters
- `line_number: int` - Source line number
- `is_continuation: bool` - Whether statement spans multiple lines

**Relationships**:
- Belongs to 1 Paragraph

**Validation Rules**:
- Statement type must be valid COBOL verb
- Parameters must match statement type requirements
- Line numbers must be sequential within paragraph

### Declaration
Represents variable, file, or record declarations in the DATA division.

**Attributes**:
- `level_number: int` - COBOL level number (01-49, 66, 77, 88)
- `name: str` - Variable/record name
- `picture_clause: Optional[str]` - PIC clause for data type
- `value_clause: Optional[str]` - Initial value
- `usage_clause: Optional[str]` - USAGE specification
- `occurs_clause: Optional[str]` - OCCURS specification for arrays
- `line_number: int` - Source line number

**Relationships**:
- Belongs to 1 Section (DATA division only)
- May have child Declaration entities (for group items)
- May have parent Declaration entity (for subordinate items)

**Validation Rules**:
- Level numbers must follow COBOL hierarchy rules
- Picture clauses must be valid for the data type
- Group items (level 01-49) cannot have picture clauses
- Elementary items must have picture or usage clauses

## Supporting Entities

### SourceInfo
Metadata about the original COBOL source file.

**Attributes**:
- `filename: Optional[str]` - Original filename if available
- `total_lines: int` - Total lines in source
- `encoding: str` - Character encoding used
- `cobol_dialect: Optional[str]` - Detected COBOL dialect/compiler

### ParseMetadata
Information about the parsing process incorporating clarified performance and memory requirements.

**Attributes**:
- `parse_time: datetime` - When parsing occurred
- `parse_duration: float` - Time taken to parse (seconds) - best-effort tracking
- `memory_used_mb: float` - **NEW**: Peak memory usage during parsing
- `memory_limit_mb: Optional[float]` - **NEW**: Configured memory limit
- `error_recovery_mode: str` - **NEW**: "FAIL_FAST" or "COLLECT_ALL"
- `warnings: List[ParseWarning]` - Non-fatal parsing issues
- `syntax_errors: List[SyntaxError]` - Recoverable syntax errors in collection mode
- `dialect_used: str` - **NEW**: Actual dialect used for parsing
- `features_encountered: Set[str]` - **NEW**: COBOL features found in program
- `ibm_extensions_used: List[str]` - **NEW**: IBM-specific extensions detected

### LineRange
Represents a range of line numbers in the source file.

**Attributes**:
- `start_line: int` - First line number (1-based)
- `end_line: int` - Last line number (1-based)
- `column_start: Optional[int]` - Starting column (for precision)
- `column_end: Optional[int]` - Ending column (for precision)

### ParseError
Base class for all parsing errors with location information.

**Attributes**:
- `message: str` - Human-readable error description
- `line_number: int` - Line where error occurred
- `column_number: Optional[int]` - Column where error occurred
- `error_code: str` - Machine-readable error identifier
- `severity: ErrorSeverity` - ERROR, WARNING, INFO

**Subtypes**:
- `LexicalError` - Invalid tokens, malformed literals
- `SyntaxError` - Grammar violations, missing elements
- `StructuralError` - Invalid division order, missing sections
- `SemanticError` - Undefined variables, type mismatches

### SerializationConfig
**NEW**: Configuration for JSON export capability per clarifications.

**Attributes**:
- `max_depth: Optional[int]` - Limit object hierarchy depth to control output size
- `include_divisions: Set[str]` - Filter specific divisions ("DATA", "PROCEDURE", etc.)
- `include_source_lines: bool` - Include original COBOL source text
- `include_comments: bool` - Include comment entities
- `include_metadata: bool` - Include parsing metadata
- `pretty_print: bool` - Format JSON for readability
- `exclude_empty_sections: bool` - Skip sections with no content

**Preset Configurations**:
- `SerializationConfig.minimal()` - Structure only, no source text
- `SerializationConfig.full()` - All details including source and comments
- `SerializationConfig.data_only()` - Only DATA division for analysis tools
- `SerializationConfig.procedure_only()` - Only PROCEDURE division for logic analysis

### MemoryConfiguration
**NEW**: Memory management configuration per clarifications.

**Attributes**:
- `memory_limit_mb: float` - Maximum memory usage (64MB to 8GB range)
- `lazy_loading_enabled: bool` - Enable lazy loading of large sections
- `object_pooling_enabled: bool` - Reuse objects for memory efficiency
- `cache_parsed_statements: bool` - Cache statement parsing results
- `gc_threshold: float` - Trigger garbage collection at memory percentage

**Preset Configurations**:
- `MemoryConfiguration.conservative()` - 64MB limit, all optimizations enabled
- `MemoryConfiguration.default()` - 512MB limit, balanced settings
- `MemoryConfiguration.generous()` - 2GB limit, performance over memory
- `MemoryConfiguration.unlimited()` - No limits, maximum performance

## Enumeration Types

### DivisionType
- IDENTIFICATION
- ENVIRONMENT  
- DATA
- PROCEDURE

### DialectType
**NEW**: Supported COBOL dialects per clarifications.
- IBM_ENTERPRISE_COBOL (primary)
- MICRO_FOCUS_COBOL (basic support)
- GNU_COBOL (basic support)
- ANSI_COBOL (baseline)

### ErrorRecoveryMode
**NEW**: Configurable error handling per clarifications.
- FAIL_FAST - Stop on first error
- COLLECT_ALL - Continue parsing, collect all errors

### StatementType
- MOVE, ADD, SUBTRACT, MULTIPLY, DIVIDE
- IF, ELSE, END_IF
- PERFORM, END_PERFORM
- DISPLAY, ACCEPT
- OPEN, READ, WRITE, CLOSE
- STOP, EXIT
- And 50+ other COBOL verbs

### SectionType
**ENVIRONMENT Division**:
- CONFIGURATION
- INPUT_OUTPUT

**DATA Division**:
- FILE
- WORKING_STORAGE
- LOCAL_STORAGE  
- LINKAGE
- COMMUNICATION
- REPORT

**PROCEDURE Division**:
- DECLARATIVES (special case)

### ErrorSeverity
- INFO - Informational messages
- WARNING - Potential issues, parsing continues
- ERROR - Syntax errors, parsing continues with recovery
- FATAL - Cannot continue parsing

## State Transitions

### Program Parsing States
1. **Uninitialized** → **Lexical Analysis** → **Division Parsing** → **Validation** → **Complete**
2. Error states: **Lexical Error**, **Syntax Error**, **Structural Error**

### Division Processing Order
1. IDENTIFICATION (required)
2. ENVIRONMENT (optional)
3. DATA (optional) 
4. PROCEDURE (optional)

## Relationships Summary

```
Program (1) ──→ (1-4) Division
Division (1) ──→ (0-*) Section  
Section (1) ──→ (0-*) Paragraph (PROCEDURE only)
Section (1) ──→ (0-*) Declaration (DATA only)
Paragraph (1) ──→ (0-*) Statement
Declaration (1) ──→ (0-*) Declaration (hierarchical)
Program (1) ──→ (1) SourceInfo
Program (1) ──→ (1) ParseMetadata
```