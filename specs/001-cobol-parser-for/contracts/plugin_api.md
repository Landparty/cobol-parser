# Plugin API Contract

## Plugin System Architecture

### Plugin Discovery
```python
# Automatic plugin discovery
cobolparser.discover_plugins()  # Finds plugins via entry points

# Manual plugin registration  
cobolparser.register_plugin(MyCustomPlugin())

# Plugin management
cobolparser.list_plugins() -> List[str]
cobolparser.get_plugin(name: str) -> Optional[ParserPlugin]
cobolparser.disable_plugin(name: str) -> None
```

### Plugin Lifecycle Contract

**Registration Phase**:
1. Plugin validates its dependencies and configuration
2. Plugin registers its hook handlers for specific events
3. Plugin declares supported COBOL dialects and versions
4. System validates plugin compatibility and loads it

**Execution Phase**:
1. Pre-parse hooks execute before any parsing begins
2. Parse hooks execute during specific parsing phases
3. Post-parse hooks execute after parsing completes
4. Error hooks execute when errors are encountered

**Cleanup Phase**:
1. Plugin releases any held resources
2. Plugin unregisters all hook handlers
3. System removes plugin from active registry

---

## Hook Point Contracts

### Pre-Parse Hook
```python
def pre_parse_hook(self, source: str, context: ParseContext) -> str:
    """
    Transform COBOL source before parsing begins.
    
    Use cases:
    - Normalize line endings and encoding
    - Handle vendor-specific preprocessing directives  
    - Convert between COBOL dialects
    - Inject standard boilerplate sections
    """
```

**Contract**:
- Input: Raw COBOL source text and parse context
- Output: Transformed COBOL source text
- MUST return valid COBOL source or raise PluginError
- MUST preserve line number mapping for error reporting
- MUST NOT modify context object

### Division Parse Hook  
```python
def division_parse_hook(self, division_type: DivisionType, 
                       content: str, context: ParseContext) -> Optional[Division]:
    """
    Custom parsing for entire divisions.
    
    Use cases:
    - Handle vendor-specific division types
    - Parse complex ENVIRONMENT configurations
    - Custom DATA division layouts
    - Specialized PROCEDURE division patterns
    """
```

**Contract**:
- Input: Division type, raw content, parse context
- Output: Parsed Division object or None (pass-through)
- MUST handle only declared division types
- MUST preserve all section and line information
- MUST validate division structure according to COBOL rules

### Statement Parse Hook
```python  
def statement_parse_hook(self, statement_text: str, 
                        context: ParseContext) -> Optional[Statement]:
    """
    Custom parsing for individual COBOL statements.
    
    Use cases:
    - Vendor-specific COBOL verbs
    - Extended syntax variations  
    - Custom embedded languages
    - Macro expansions
    """
```

**Contract**:
- Input: Raw statement text and parse context
- Output: Parsed Statement object or None (pass-through)  
- MUST handle only recognized statement patterns
- MUST preserve original statement text and line numbers
- MUST validate statement syntax according to COBOL rules

### Post-Parse Hook
```python
def post_parse_hook(self, program: Program, context: ParseContext) -> Program:
    """
    Post-processing and validation after parsing completes.
    
    Use cases:
    - Cross-reference validation
    - Data flow analysis
    - Code quality checks
    - Optimization analysis
    """
```

**Contract**:
- Input: Complete parsed Program and parse context
- Output: Enhanced or validated Program object
- MUST NOT break existing Program object contracts
- MUST preserve immutability unless specifically designed for transformation
- MUST handle Program objects that may contain parse errors

### Error Handler Hook
```python
def error_handler_hook(self, error: ParseError, context: ParseContext) -> Optional[ParseError]:
    """
    Custom error handling and recovery.
    
    Use cases:
    - Provide more specific error messages
    - Implement error recovery strategies
    - Convert errors to warnings for known issues
    - Log errors to external systems
    """
```

**Contract**:
- Input: Parse error and context
- Output: Modified error, None (suppress), or original error
- MUST NOT raise exceptions unless critical failure
- MUST preserve error location information
- MUST maintain error severity appropriately

---

## Plugin Context Contract

### ParseContext Object
```python
@dataclass(frozen=True)
class ParseContext:
    filename: Optional[str]          # Source filename if available
    dialect: Optional[str]           # Detected/specified COBOL dialect  
    options: Dict[str, Any]         # Parser options and settings
    line_mapping: LineMapper        # Maps transformed lines to original
    symbol_table: SymbolTable       # Current parsing symbols/variables
    error_count: int                # Errors encountered so far
    warnings_count: int             # Warnings generated so far
```

**Contract**:
- Context is immutable during hook execution
- Context provides read-only access to parsing state  
- Context includes utilities for line number mapping
- Context maintains current symbol/variable scope
- Context tracks parsing statistics and error counts

### LineMapper Utility
```python  
class LineMapper:
    def map_to_original(self, transformed_line: int) -> int
    def map_from_original(self, original_line: int) -> int
    def add_mapping(self, original_line: int, transformed_line: int) -> None
```

**Contract**: Plugins that transform source MUST update line mappings

### SymbolTable Utility
```python
class SymbolTable:
    def define_variable(self, name: str, declaration: Declaration) -> None
    def lookup_variable(self, name: str) -> Optional[Declaration]  
    def enter_scope(self, scope_name: str) -> None
    def exit_scope() -> None
```

**Contract**: Plugins can read symbol table but should not modify without careful consideration

---

## Plugin Error Handling

### PluginError Exception Hierarchy
```python
PluginError (base)
├── PluginConfigurationError    # Invalid plugin configuration
├── PluginCompatibilityError    # Plugin incompatible with parser version
├── PluginExecutionError        # Runtime error during plugin execution
└── PluginDependencyError       # Missing plugin dependencies
```

**Contract Requirements**:
1. Plugin errors MUST NOT crash the main parser
2. Plugin errors SHOULD be logged with plugin name and context
3. Parser MUST continue with other plugins if one fails
4. Fatal plugin errors MAY disable the plugin automatically
5. Plugin error recovery MUST be documented

### Error Recovery Strategies
- **Graceful degradation**: Disable failing plugin, continue parsing
- **Fallback behavior**: Use default parser behavior when plugin fails
- **Error isolation**: Plugin errors don't affect other plugins
- **User notification**: Clear error messages for plugin failures

---

## Plugin Development Guidelines

### Plugin Metadata
```python
class ParserPlugin:
    # Required metadata
    name: str                           # Unique identifier
    version: str                        # Plugin version
    description: str                    # Human-readable description
    
    # Optional metadata  
    author: Optional[str] = None        # Plugin author
    license: Optional[str] = None       # Plugin license
    homepage: Optional[str] = None      # Documentation URL
    
    # Compatibility declarations
    min_parser_version: str             # Minimum required parser version
    max_parser_version: Optional[str]   # Maximum supported parser version
    supported_dialects: List[str]       # COBOL dialects supported
    
    # NEW: IBM Enterprise COBOL focus per clarifications
    ibm_enterprise_priority: bool = True    # Whether plugin prioritizes IBM Enterprise COBOL
    handles_sql_integration: bool = False   # Whether plugin handles SQL embedded in COBOL
    supports_modern_cobol: bool = False     # Whether plugin supports COBOL 2002+ features
    
    # Capability flags
    modifies_source: bool = False       # Plugin changes source text
    adds_metadata: bool = False         # Plugin adds custom metadata
    requires_symbols: bool = False      # Plugin needs symbol table access
```

### Plugin Testing Contract
1. Plugins MUST include unit tests for all hook methods
2. Plugins MUST test compatibility with supported COBOL dialects  
3. Plugins MUST test error handling and recovery scenarios
4. Plugins MUST document performance impact and limitations
5. Plugins MUST provide example usage and configuration

### Plugin Distribution
- Use standard Python packaging (setuptools, pip)
- Declare parser dependency with version constraints
- Use entry points for automatic plugin discovery
- Include comprehensive documentation and examples
- Follow semantic versioning for plugin releases