# Parser API Contract - Updated with Clarified Requirements

## Primary Parse Functions

### `CobolParser.parse_file(file_path: str, **options) -> Program`

**Purpose**: Parse COBOL source file and return structured Program object with enhanced configuration

**Input**:
- `file_path: str` - Path to COBOL source file
- `encoding: str = "utf-8"` - File encoding
- `memory_limit_mb: Optional[float]` - **NEW**: Configure memory usage limit
- `error_mode: str = "FAIL_FAST"` - **NEW**: "FAIL_FAST" or "COLLECT_ALL"
- `dialect: str = "IBM_ENTERPRISE"` - **NEW**: Primary dialect (IBM focus)
- `progress_callback: Optional[Callable]` - **NEW**: Progress reporting for large files

**Output**: 
- `Program` object with all divisions, sections, and statements parsed
- **NEW**: Includes memory usage statistics and error collection based on mode
- Raises `CobolParseError` for fatal parsing errors (fail-fast mode only)

**Contract Requirements** (Updated):
1. MUST handle all four COBOL divisions (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE)
2. MUST return immutable Program object with JSON export capability
3. MUST preserve original line numbers and source mapping
4. MUST handle comments and continuation lines correctly
5. MUST provide clear error messages with line/column information
6. **NEW**: MUST respect configurable memory limits (64MB to 8GB range)
7. **NEW**: MUST provide best-effort performance without specific time guarantees
8. **NEW**: MUST support IBM Enterprise COBOL as primary dialect
9. **NEW**: MUST support configurable error recovery modes

### `CobolParser.export_json(program: Program, config: SerializationConfig) -> str`

**Purpose**: **NEW**: Export parsed program to JSON for interoperability

**Input**:
- `program: Program` - Parsed COBOL program object
- `config: SerializationConfig` - Depth, filtering, and formatting options

**Output**:
- `str` - JSON representation of program structure
- Configurable depth and section filtering to manage output size

**Contract Requirements**:
1. MUST serialize complete object hierarchy to valid JSON
2. MUST support configurable depth limits for large programs
3. MUST support division filtering (DATA only, PROCEDURE only, etc.)
4. MUST handle circular references and complex object relationships
5. MUST provide preset configurations (minimal, full, data-only)

---

## Program Object API Contract

### `Program.name: str`
**Contract**: Returns program identifier from PROGRAM-ID statement
**Guarantee**: Never None, always valid COBOL identifier

### `Program.divisions: List[Division]`
**Contract**: Returns all parsed divisions in source order
**Guarantee**: At least IDENTIFICATION division present, order preserved

### `Program.get_division(type: DivisionType) -> Optional[Division]`
**Contract**: Returns specific division by type or None if not present
**Guarantee**: Type-safe lookup, handles missing divisions gracefully

### `Program.source_info: SourceInfo`  
**Contract**: Returns metadata about original source
**Guarantee**: Always present, includes line count and encoding info

### `Program.find_variables(pattern: str) -> List[Declaration]`
**Contract**: Search for variable declarations matching pattern
**Guarantee**: Returns empty list if no matches, supports regex patterns

---

## Division Object API Contract

### `Division.type: DivisionType`
**Contract**: Returns enum value for division type
**Guarantee**: Always one of the four standard COBOL divisions

### `Division.sections: List[Section]`
**Contract**: Returns sections within this division
**Guarantee**: Empty list if no sections, preserves source order

### `Division.line_range: LineRange`
**Contract**: Returns source line numbers spanned by this division  
**Guarantee**: Valid range, start <= end, 1-based line numbers

---

## Error Handling API Contract

### `COBOLParseError` Exception Hierarchy
```python
COBOLParseError (base)
├── LexicalError        # Invalid tokens, malformed literals
├── SyntaxError         # Grammar violations, missing elements  
├── StructuralError     # Invalid division order, missing sections
└── SemanticError       # Undefined variables, type mismatches
```

**Contract Requirements**:
1. All errors MUST include line number where error occurred
2. All errors MUST include descriptive message for end users
3. All errors MUST include machine-readable error code
4. Parsing MUST attempt recovery and continue when possible
5. Multiple errors MUST be collected and reported together

### Error Object Properties
- `message: str` - Human-readable description
- `line_number: int` - 1-based line number  
- `column_number: Optional[int]` - 1-based column if available
- `error_code: str` - Machine-readable identifier (e.g., 'MISSING_PROGRAM_ID')
- `severity: ErrorSeverity` - INFO, WARNING, ERROR, FATAL

---

## Plugin API Contract

### Plugin Registration
```python
def register_plugin(plugin: ParserPlugin) -> None
def unregister_plugin(plugin_name: str) -> None
```

**Contract**: Plugins can extend parser behavior at defined hook points

### Plugin Interface
```python
class ParserPlugin:
    name: str  # Unique plugin identifier
    
    def pre_parse_hook(self, source: str) -> str:
        """Transform source before parsing"""
        
    def division_parse_hook(self, division_type: DivisionType, content: str) -> Optional[Division]:
        """Custom division parsing"""
        
    def statement_parse_hook(self, statement_text: str) -> Optional[Statement]:
        """Custom statement parsing"""
        
    def post_parse_hook(self, program: Program) -> Program:
        """Post-processing and validation"""
        
    def error_handler_hook(self, error: ParseError) -> Optional[ParseError]:
        """Custom error handling"""
```

**Contract Requirements**:
1. Plugins MUST not modify parser core behavior unless explicitly designed to
2. Plugin hooks MUST return None to indicate "no handling" for pass-through
3. Plugin errors MUST not crash the main parser
4. Plugin registration MUST be idempotent
5. Plugins MUST declare their supported COBOL dialects

---

## Performance Contract (Updated per Clarifications)

### Response Time Expectations
**CHANGED**: Best-effort performance without specific time guarantees
- **NEW**: Progress callbacks for files > 1MB to show parsing status
- **NEW**: Configurable lazy loading for memory efficiency over speed
- **REMOVED**: Specific time targets (replaced with best-effort approach)

### Memory Usage Guarantees (Enhanced)
- **NEW**: User-configurable memory limits (64MB to 8GB range)
- **NEW**: Default memory limit: 512MB with conservative/generous presets
- **NEW**: Memory monitoring with MemoryLimitExceeded exception
- **NEW**: Lazy loading of divisions and sections when enabled
- No memory leaks during repeated parsing (unchanged)

### Memory Configuration Options
- `MemoryConfiguration.conservative()`: 64MB limit, all optimizations enabled
- `MemoryConfiguration.default()`: 512MB limit, balanced performance/memory
- `MemoryConfiguration.generous()`: 2GB limit, performance over memory optimization

### Concurrency Contract
- Parser instances MUST be thread-safe for read operations
- Multiple parsers can run concurrently without interference
- Plugin registration/unregistration requires synchronization

---

## Compatibility Contract

### Python Version Support
- Minimum: Python 3.13+
- Standard library only for core functionality
- Optional dependencies clearly documented

### COBOL Dialect Support (Updated Priorities)
- **PRIMARY**: IBM Enterprise COBOL (comprehensive syntax support, SQL integration, modern features)
- **BASIC**: Micro Focus COBOL (common enterprise extensions)
- **BASIC**: GnuCOBOL (ANSI standard compliance)
- **NEW**: Dialect detection and plugin-based extension support
- **NEW**: IBM-specific validation rules in strict mode

### JSON Export Capability (NEW)
- **Interoperability**: Export parsed structure to JSON for external tools
- **Configurable serialization**: Control depth, filtering, and formatting
- **Preset configurations**: Minimal, full, data-only, procedure-only options
- **Large program support**: Memory-efficient serialization with depth limits

### Output Format Stability
- Program object API stable across minor versions  
- New properties may be added but never removed
- Deprecation warnings for API changes