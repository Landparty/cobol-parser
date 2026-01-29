# COBOL Parser Refactoring Implementation Plan

**Project Goal:** Transform parser.py (4,127 lines) into modular, maintainable, well-documented division-specific modules while maintaining 100% backward compatibility.

**Duration:** 3-4 weeks | **Phases:** 6 | **Risk Level:** Low (delegation pattern ensures no breaking changes)

---

## Executive Summary

This plan extracts the monolithic parser into modular components through 6 sequential phases:

1. **Foundation** - Create constants and error enums
2. **Helpers** - Extract reusable token matching decorators
3. **Division Modules** - Split parsing logic by COBOL division
4. **Coordination** - Create lightweight coordinator pattern
5. **Type Safety** - Add comprehensive type hints and docstrings
6. **Validation** - Comprehensive testing and performance verification

**Key Principle:** Each phase is independently valuable and can be reviewed/merged before proceeding to the next.

---

## Phase 1: Foundation & Constants Module (Week 1)

### Objectives
- Eliminate 50+ magic strings from codebase
- Establish ErrorCode enum for standardized error handling
- Create base infrastructure for phases 2-6

### Deliverables

#### 1.1 Create Constants Module
**File:** `cobolparser/parser/constants.py`

**Contents:**
```python
from enum import Enum

# Division/Section Keywords
class CobolKeywords(Enum):
    """All COBOL keywords used throughout parser"""
    IDENTIFICATION = "IDENTIFICATION"
    PROGRAM_ID = "PROGRAM-ID"
    AUTHOR = "AUTHOR"
    INSTALLATION = "INSTALLATION"
    DATE_WRITTEN = "DATE-WRITTEN"
    DATE_COMPILED = "DATE-COMPILED"
    SECURITY = "SECURITY"
    
    ENVIRONMENT = "ENVIRONMENT"
    CONFIGURATION = "CONFIGURATION"
    INPUT_OUTPUT = "INPUT-OUTPUT"
    FILE_CONTROL = "FILE-CONTROL"
    
    DATA = "DATA"
    FILE_SECTION = "FILE-SECTION"
    WORKING_STORAGE = "WORKING-STORAGE-SECTION"
    LINKAGE_SECTION = "LINKAGE-SECTION"
    SCREEN_SECTION = "SCREEN-SECTION"
    LOCAL_STORAGE = "LOCAL-STORAGE-SECTION"
    
    PROCEDURE = "PROCEDURE"
    DIVISION = "DIVISION"
    
    # File/FD keywords
    ASSIGN = "ASSIGN"
    ORGANIZATION = "ORGANIZATION"
    RECORD = "RECORD"
    FD = "FD"
    SD = "SD"
    
    # Data description keywords
    PIC = "PIC"
    PICTURE = "PICTURE"
    VALUE = "VALUE"
    COMP = "COMP"
    COMP_3 = "COMP-3"
    USAGE = "USAGE"
    
    # [... additional keywords ... ~40+ total]

class ErrorCode(Enum):
    """Standardized error codes with templated messages"""
    MISSING_IDENTIFICATION_DIVISION = "MISSING_IDENTIFICATION_DIVISION"
    MISSING_PROGRAM_ID = "MISSING_PROGRAM_ID"
    MISSING_ENVIRONMENT_DIVISION = "MISSING_ENVIRONMENT_DIVISION"
    MISSING_DATA_DIVISION = "MISSING_DATA_DIVISION"
    MISSING_PROCEDURE_DIVISION = "MISSING_PROCEDURE_DIVISION"
    INVALID_PICTURE_CLAUSE = "INVALID_PICTURE_CLAUSE"
    UNEXPECTED_TOKEN = "UNEXPECTED_TOKEN"
    MISSING_SECTION_HEADER = "MISSING_SECTION_HEADER"
    INVALID_NUMERIC_VALUE = "INVALID_NUMERIC_VALUE"
    FILE_CONTROL_PARSE_ERROR = "FILE_CONTROL_PARSE_ERROR"
    SELECT_STATEMENT_ERROR = "SELECT_STATEMENT_ERROR"
    # [... ~10+ additional error codes ... ]

# Error message templates
ERROR_MESSAGES: Dict[ErrorCode, str] = {
    ErrorCode.MISSING_IDENTIFICATION_DIVISION: 
        "Missing IDENTIFICATION DIVISION at line {line}",
    ErrorCode.MISSING_PROGRAM_ID: 
        "Missing PROGRAM-ID in IDENTIFICATION DIVISION at line {line}",
    ErrorCode.UNEXPECTED_TOKEN: 
        "Unexpected token '{token}' at line {line}. Expected: {expected}",
    # [... additional templates ... ]
}
```

**Metrics:**
- ~150-200 lines of code
- Eliminates ~50 magic string occurrences across parser.py
- Reduces parser.py complexity by ~3% (method length)

#### 1.2 Update Parser Imports
**File:** `cobolparser/parser/__init__.py`

```python
# Temporary bridge - existing code continues to work
from .constants import CobolKeywords, ErrorCode, ERROR_MESSAGES
from ..parser import CobolParser  # Existing parser still works

__all__ = ['CobolParser', 'CobolKeywords', 'ErrorCode']
```

### Testing
- Unit tests for each ErrorCode enum member
- Validation that all constants are referenced in parser.py
- No existing tests should break

### Success Criteria
✅ All 114 existing tests pass
✅ Constants module achieves 100% usage (ruff check)
✅ No circular import errors

---

## Phase 2: Token Matching Helpers & Decorators (Week 1)

### Objectives
- Extract repeated patterns from parser.py lines 500-620
- Create reusable decorators for common token matching
- Reduce code duplication by 20-30%

### Deliverables

#### 2.1 Create Common Utilities Module
**File:** `cobolparser/parser/common.py`

**Contents - Helper Functions:**
```python
from typing import Callable, Optional, List, Tuple
from ..lexer import Token, TokenType
from .constants import ErrorCode, ERROR_MESSAGES

def current_token_is(parser_instance, value: str, type_filter: Optional[TokenType] = None) -> bool:
    """Check if current token matches value and optional type"""
    token = parser_instance.current_token()
    if token is None:
        return False
    if type_filter and token.type != type_filter:
        return False
    return token.value == value

def current_token_type(parser_instance, token_type: TokenType) -> bool:
    """Check if current token is of specific type"""
    token = parser_instance.current_token()
    return token is not None and token.type == token_type

def match_identifier(parser_instance) -> Optional[str]:
    """Extract identifier from current position, advance if found"""
    if current_token_type(parser_instance, TokenType.IDENTIFIER):
        identifier = parser_instance.current_token().value
        parser_instance.advance()
        return identifier
    return None

def match_numeric_value(parser_instance) -> Optional[str]:
    """Extract numeric literal, advance if found"""
    if current_token_type(parser_instance, TokenType.NUMBER):
        value = parser_instance.current_token().value
        parser_instance.advance()
        return value
    return None

def expect_keyword(parser_instance, keyword: str) -> bool:
    """Consume expected keyword, raise if not found"""
    if not current_token_is(parser_instance, keyword):
        parser_instance.error(
            ErrorCode.UNEXPECTED_TOKEN,
            f"Expected '{keyword}'",
            parser_instance.current_token()
        )
        return False
    parser_instance.advance()
    return True

def skip_until_keyword(parser_instance, keyword: str) -> bool:
    """Skip tokens until keyword found (error recovery)"""
    while parser_instance.current_token() is not None:
        if current_token_is(parser_instance, keyword):
            return True
        parser_instance.advance()
    return False

def parse_clause_until(parser_instance, end_keywords: List[str]) -> List[Token]:
    """Collect tokens until one of end_keywords found"""
    tokens = []
    while parser_instance.current_token() is not None:
        if current_token_is(parser_instance, end_keywords[0]) or \
           any(current_token_is(parser_instance, kw) for kw in end_keywords):
            break
        tokens.append(parser_instance.current_token())
        parser_instance.advance()
    return tokens
```

**Contents - Decorators:**
```python
def expect_token_value(keyword: str):
    """Decorator: method expects current token to be 'keyword'"""
    def decorator(func: Callable) -> Callable:
        def wrapper(parser_instance, *args, **kwargs):
            if not current_token_is(parser_instance, keyword):
                parser_instance.error(
                    ErrorCode.UNEXPECTED_TOKEN,
                    f"Expected '{keyword}'",
                    parser_instance.current_token()
                )
                return None
            parser_instance.advance()  # Consume the keyword
            return func(parser_instance, *args, **kwargs)
        return wrapper
    return decorator

def skip_to_keyword(keyword: str):
    """Decorator: skip tokens until keyword if parsing failed"""
    def decorator(func: Callable) -> Callable:
        def wrapper(parser_instance, *args, **kwargs):
            try:
                return func(parser_instance, *args, **kwargs)
            except Exception:
                skip_until_keyword(parser_instance, keyword)
                return None
        return wrapper
    return decorator

def parse_optional_clause(end_keywords: List[str]):
    """Decorator: parse optional clause, stop at end_keywords"""
    def decorator(func: Callable) -> Callable:
        def wrapper(parser_instance, *args, **kwargs):
            start_pos = parser_instance.position
            try:
                return func(parser_instance, *args, **kwargs)
            except Exception:
                # Reset to start on failure
                parser_instance.position = start_pos
                return None
        return wrapper
    return decorator
```

### Implementation Guidelines

**In Phase 2, DO NOT:**
- Refactor existing parser methods' logic
- Change how parser.py is organized
- Modify AST output

**In Phase 2, DO:**
- Add `from cobolparser.parser.common import *` to parser.py
- Replace inline token matching with helper calls
- Example replacement:
  ```python
  # OLD (parser.py line 512)
  if self.current_token() and self.current_token().value == "FILE-CONTROL":
      self.advance()
  
  # NEW (using helpers)
  if not expect_keyword(self, "FILE-CONTROL"):
      return None
  ```

### Testing
- Unit tests for each helper function (8-10 tests)
- Decorator application tests (5-6 tests)
- No changes to integration tests; all should pass

### Success Criteria
✅ All 114 existing tests pass
✅ Code duplication in parser.py reduced by 20-30% (measured by ruff)
✅ Helper function coverage >90%

---

## Phase 3: Extract Division Modules (Week 1-2)

### Objectives
- Create 4 division-specific modules
- Move ~1000 lines per module from parser.py
- Maintain backward compatibility via delegation

### Deliverables

#### 3.1 Module Structure
Create modules in `cobolparser/parser/`:
- `identification.py` (200-250 lines)
- `environment.py` (300-400 lines)
- `data.py` (500-600 lines)
- `procedure.py` (400-500 lines)

#### 3.2 Identification Division Parser
**File:** `cobolparser/parser/identification.py`

```python
from typing import Optional
from ..models.program import IdentificationDivision, ProgramMetadata
from ..lexer import Token, TokenType
from .common import expect_keyword, match_identifier, current_token_is
from .constants import CobolKeywords, ErrorCode

class IdentificationDivisionParser:
    """Handles IDENTIFICATION DIVISION parsing"""
    
    def __init__(self, parser_instance):
        """Reference to parent parser for token management"""
        self.parser = parser_instance
    
    def parse(self) -> Optional[IdentificationDivision]:
        """
        Parse IDENTIFICATION DIVISION
        
        Returns:
            IdentificationDivision AST node or None on error
        
        Raises:
            ParserError: If division structure is invalid
        """
        if not expect_keyword(self.parser, "IDENTIFICATION"):
            return None
        
        if not expect_keyword(self.parser, "DIVISION"):
            return None
        
        # Parse optional metadata
        program_id = self._parse_program_id()
        author = self._parse_optional_metadata("AUTHOR")
        installation = self._parse_optional_metadata("INSTALLATION")
        date_written = self._parse_optional_metadata("DATE-WRITTEN")
        
        return IdentificationDivision(
            program_id=program_id,
            author=author,
            installation=installation,
            date_written=date_written,
            location=self.parser.current_location()
        )
    
    def _parse_program_id(self) -> Optional[str]:
        """
        Parse PROGRAM-ID clause
        
        Syntax: PROGRAM-ID. identifier [.].
        
        Returns:
            Program identifier or None
        """
        if not expect_keyword(self.parser, "PROGRAM-ID"):
            self.parser.error(
                ErrorCode.MISSING_PROGRAM_ID,
                "Expected PROGRAM-ID clause"
            )
            return None
        
        if not expect_keyword(self.parser, "."):
            return None
        
        program_id = match_identifier(self.parser)
        if program_id is None:
            return None
        
        # Optional trailing period
        if current_token_is(self.parser, "."):
            self.parser.advance()
        
        return program_id
    
    def _parse_optional_metadata(self, keyword: str) -> Optional[str]:
        """Parse optional metadata lines (AUTHOR, INSTALLATION, etc.)"""
        if not current_token_is(self.parser, keyword):
            return None
        
        self.parser.advance()
        
        # Collect text until next period or keyword
        text_parts = []
        while self.parser.current_token() and \
              self.parser.current_token().value not in ["ENVIRONMENT", "DATA", "PROCEDURE"]:
            if self.parser.current_token().value == ".":
                self.parser.advance()
                break
            text_parts.append(self.parser.current_token().value)
            self.parser.advance()
        
        return " ".join(text_parts)
```

#### 3.3 Environment Division Parser
**File:** `cobolparser/parser/environment.py`

```python
from typing import Optional, List
from ..models.program import EnvironmentDivision, FileDescription, SelectStatement
from .common import expect_keyword, match_identifier, current_token_is, skip_until_keyword
from .constants import CobolKeywords, ErrorCode

class EnvironmentDivisionParser:
    """Handles ENVIRONMENT DIVISION parsing"""
    
    def __init__(self, parser_instance):
        self.parser = parser_instance
    
    def parse(self) -> Optional[EnvironmentDivision]:
        """
        Parse ENVIRONMENT DIVISION
        
        Structure:
            ENVIRONMENT DIVISION.
            [CONFIGURATION SECTION. ...]
            [INPUT-OUTPUT SECTION. ...]
        """
        if not expect_keyword(self.parser, "ENVIRONMENT"):
            return None
        
        if not expect_keyword(self.parser, "DIVISION"):
            return None
        
        # Parse optional sections
        configuration = None
        input_output = None
        
        while self.parser.current_token():
            token = self.parser.current_token().value
            
            if token == "CONFIGURATION":
                configuration = self._parse_configuration_section()
            elif token == "INPUT-OUTPUT":
                input_output = self._parse_input_output_section()
            elif token in ["DATA", "PROCEDURE"]:
                break
            else:
                self.parser.advance()
        
        return EnvironmentDivision(
            configuration_section=configuration,
            input_output_section=input_output,
            location=self.parser.current_location()
        )
    
    def _parse_configuration_section(self) -> Optional[dict]:
        """Parse CONFIGURATION SECTION"""
        # [Implementation: parse SOURCE-COMPUTER, OBJECT-COMPUTER, etc.]
        pass
    
    def _parse_input_output_section(self) -> Optional[dict]:
        """Parse INPUT-OUTPUT SECTION with FILE-CONTROL and I-O-CONTROL"""
        if not expect_keyword(self.parser, "INPUT-OUTPUT"):
            return None
        
        if not expect_keyword(self.parser, "SECTION"):
            return None
        
        file_control_entries = []
        
        if current_token_is(self.parser, "FILE-CONTROL"):
            self.parser.advance()
            file_control_entries = self._parse_file_control()
        
        return {
            "file_control": file_control_entries
        }
    
    def _parse_file_control(self) -> List[SelectStatement]:
        """
        Parse FILE-CONTROL paragraph
        
        Handles SELECT statements until I-O-CONTROL found
        """
        select_statements = []
        
        while self.parser.current_token():
            token = self.parser.current_token().value
            
            if token == "SELECT":
                select_stmt = self._parse_select_statement()
                if select_stmt:
                    select_statements.append(select_stmt)
            elif token == "I-O-CONTROL":
                break
            else:
                self.parser.advance()
        
        return select_statements
    
    def _parse_select_statement(self) -> Optional[SelectStatement]:
        """
        Parse SELECT statement (complex, multi-line)
        
        Syntax:
            SELECT [OPTIONAL] file-name
            ASSIGN TO device ORGANIZATION ...
            [RECORD VARYING...]
        """
        # [Implementation: extract from parser.py's _parse_select_statement]
        pass
```

#### 3.4 Data Division Parser
**File:** `cobolparser/parser/data.py`

```python
from typing import Optional, List
from ..models.program import DataDivision, DataItem, FileDescription
from .common import expect_keyword, match_identifier, current_token_is
from .constants import ErrorCode

class DataDivisionParser:
    """Handles DATA DIVISION parsing"""
    
    def __init__(self, parser_instance):
        self.parser = parser_instance
    
    def parse(self) -> Optional[DataDivision]:
        """
        Parse DATA DIVISION with all sections
        
        Sections:
            - FILE-SECTION
            - WORKING-STORAGE-SECTION
            - LINKAGE-SECTION
            - LOCAL-STORAGE-SECTION
            - SCREEN-SECTION
        """
        if not expect_keyword(self.parser, "DATA"):
            return None
        
        if not expect_keyword(self.parser, "DIVISION"):
            return None
        
        file_section = None
        working_storage = None
        linkage_section = None
        local_storage = None
        screen_section = None
        
        while self.parser.current_token():
            token = self.parser.current_token().value
            
            if token == "FILE":
                file_section = self._parse_file_section()
            elif token == "WORKING-STORAGE":
                working_storage = self._parse_working_storage_section()
            elif token == "LINKAGE":
                linkage_section = self._parse_linkage_section()
            elif token == "LOCAL-STORAGE":
                local_storage = self._parse_local_storage_section()
            elif token == "SCREEN":
                screen_section = self._parse_screen_section()
            elif token == "PROCEDURE":
                break
            else:
                self.parser.advance()
        
        return DataDivision(
            file_section=file_section,
            working_storage=working_storage,
            linkage_section=linkage_section,
            local_storage=local_storage,
            screen_section=screen_section,
            location=self.parser.current_location()
        )
    
    def _parse_file_section(self) -> Optional[List[FileDescription]]:
        """Parse FILE-SECTION with FD/SD entries"""
        # [Implementation: extract FD/SD parsing from parser.py]
        pass
    
    def _parse_working_storage_section(self) -> Optional[List[DataItem]]:
        """Parse WORKING-STORAGE-SECTION"""
        # [Implementation: extract data item parsing from parser.py]
        pass
    
    # [Additional methods for other sections...]
```

#### 3.5 Procedure Division Parser
**File:** `cobolparser/parser/procedure.py`

```python
from typing import Optional, List
from ..models.program import ProcedureDivision, Statement, Paragraph, Section
from .common import expect_keyword, current_token_is
from .constants import ErrorCode

class ProcedureDivisionParser:
    """Handles PROCEDURE DIVISION parsing"""
    
    def __init__(self, parser_instance):
        self.parser = parser_instance
    
    def parse(self) -> Optional[ProcedureDivision]:
        """
        Parse PROCEDURE DIVISION
        
        Contains sections/paragraphs with various statements:
        - MOVE, DISPLAY, ACCEPT
        - PERFORM, IF, EVALUATE
        - PERFORM VARYING (inline and paragraphs)
        - CALL, GOBACK
        """
        if not expect_keyword(self.parser, "PROCEDURE"):
            return None
        
        if not expect_keyword(self.parser, "DIVISION"):
            return None
        
        # Optional USING clause for linkage
        using_items = []
        if current_token_is(self.parser, "USING"):
            using_items = self._parse_using_clause()
        
        # Parse sections/paragraphs
        sections = []
        paragraphs = []
        statements = []
        
        while self.parser.current_token():
            token = self.parser.current_token().value
            
            # Check for section definition (ends with SECTION keyword)
            if self._is_section_start():
                section = self._parse_section()
                if section:
                    sections.append(section)
            # Check for paragraph
            elif self._is_paragraph_start():
                paragraph = self._parse_paragraph()
                if paragraph:
                    paragraphs.append(paragraph)
            # Otherwise parse statement
            else:
                stmt = self._parse_statement()
                if stmt:
                    statements.append(stmt)
        
        return ProcedureDivision(
            using_items=using_items,
            sections=sections,
            paragraphs=paragraphs,
            statements=statements,
            location=self.parser.current_location()
        )
    
    def _parse_using_clause(self) -> List[str]:
        """Parse USING ... items"""
        # [Implementation]
        pass
    
    def _parse_section(self) -> Optional[Section]:
        """Parse SECTION with paragraphs"""
        # [Implementation]
        pass
    
    def _parse_paragraph(self) -> Optional[Paragraph]:
        """Parse paragraph-name with statements"""
        # [Implementation]
        pass
    
    def _parse_statement(self) -> Optional[Statement]:
        """Parse single COBOL statement"""
        # [Implementation: delegates to existing statement parsers]
        pass
```

### Implementation Process

**Step 1: Copy-Paste Extraction (90% done)**
- Identify methods in parser.py that belong to each division
- Copy those methods to appropriate module
- Example: `_parse_identification_division()` → `identification.py`

**Step 2: Create Parser Classes**
- Wrap each module's methods in a class (e.g., `IdentificationDivisionParser`)
- All methods receive `parser_instance` as parameter
- Maintain exact same logic (no refactoring)

**Step 3: Update parser.py**
- Import division parsers at top
- In main `parse()` method, instantiate and delegate:
  ```python
  from .parser.identification import IdentificationDivisionParser
  # ...
  
  identification = IdentificationDivisionParser(self).parse()
  environment = EnvironmentDivisionParser(self).parse()
  data = DataDivisionParser(self).parse()
  procedure = ProcedureDivisionParser(self).parse()
  ```

### Testing Strategy
- **NO new tests yet** - all existing tests should pass without modification
- Add one unit test per division module (4 basic tests)
- Verify integration tests still pass completely

### Success Criteria
✅ parser.py reduced to <1,000 lines
✅ All 114 existing tests pass
✅ Zero AST changes (output identical)
✅ New modules have 50%+ line-level code coverage

---

## Phase 4: Refactor Parser Coordinator (Week 2)

### Objectives
- Reduce parser.py to 150-200 lines (coordinator only)
- Create clean delegation pattern
- Prepare for type hints in Phase 5

### Deliverables

#### 4.1 Parser Coordinator Refactoring

**File:** `cobolparser/parser.py` (after refactoring)

```python
"""
COBOL Parser - Main Entry Point
Coordinates parsing of COBOL programs through four divisions.
"""

from typing import Optional
from .lexer import Lexer, Token
from .models.program import Program
from .parser.identification import IdentificationDivisionParser
from .parser.environment import EnvironmentDivisionParser
from .parser.data import DataDivisionParser
from .parser.procedure import ProcedureDivisionParser
from .plugins.core import ErrorRecoveryMode, ParseStatistics


class CobolParser:
    """
    Main COBOL parser coordinator.
    
    Delegates division-specific parsing to specialized modules:
    - IdentificationDivisionParser
    - EnvironmentDivisionParser
    - DataDivisionParser
    - ProcedureDivisionParser
    
    Examples:
        >>> parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        >>> result = parser.parse(cobol_source)
        >>> if result.success:
        ...     print(result.ast.to_dict())
    """
    
    def __init__(self, error_recovery: ErrorRecoveryMode = ErrorRecoveryMode.FAIL_FAST):
        """
        Initialize parser with error recovery mode.
        
        Args:
            error_recovery: How to handle parsing errors
        """
        self.error_recovery = error_recovery
        self.errors = []
        self.tokens = []
        self.position = 0
        self.statistics = ParseStatistics()
    
    def parse(self, source_code: str) -> ParseResult:
        """
        Parse COBOL source code.
        
        Args:
            source_code: Complete COBOL program text
        
        Returns:
            ParseResult with AST and error information
        """
        # Lexical analysis
        lexer = Lexer(source_code)
        self.tokens = lexer.tokenize()
        self.position = 0
        self.errors = []
        
        # Syntactic analysis (delegation)
        identification = IdentificationDivisionParser(self).parse()
        environment = EnvironmentDivisionParser(self).parse()
        data = DataDivisionParser(self).parse()
        procedure = ProcedureDivisionParser(self).parse()
        
        # Construct AST
        program = Program(
            identification=identification,
            environment=environment,
            data=data,
            procedure=procedure
        )
        
        return ParseResult(
            program=program,
            errors=self.errors,
            statistics=self.statistics
        )
    
    # Token Management Methods (required by division parsers)
    
    def current_token(self) -> Optional[Token]:
        """Get current token without advancing"""
        if self.position < len(self.tokens):
            return self.tokens[self.position]
        return None
    
    def advance(self) -> None:
        """Move to next token"""
        self.position += 1
    
    def current_location(self) -> SourceLocation:
        """Get source location of current token"""
        token = self.current_token()
        if token:
            return SourceLocation(token.line, token.column, token.value)
        return SourceLocation(0, 0, "EOF")
    
    def error(self, code: ErrorCode, message: str, token: Optional[Token] = None) -> None:
        """
        Record parsing error.
        
        Args:
            code: Error code enum
            message: Descriptive message
            token: Associated token (for line/column)
        """
        error_obj = ParsingError(code, message, token)
        self.errors.append(error_obj)
        
        if self.error_recovery == ErrorRecoveryMode.FAIL_FAST:
            raise error_obj
        
        self.statistics.error_count += 1
```

### Key Changes
1. parser.py becomes **coordinator** (200 lines max)
2. All division-specific logic moved to modules
3. Backward-compatible API preserved
4. Existing imports still work via `__init__.py`

### Testing
- Ensure all 114 tests pass without modification
- Add 5-10 coordinator-level tests
- Verify error propagation still works

### Success Criteria
✅ parser.py <300 lines (target: 200-250)
✅ All tests pass
✅ Cyclomatic complexity reduced to <8 for all methods

---

## Phase 5: Type Hints & Documentation (Week 2-3)

### Objectives
- Add comprehensive return type hints to 80+ internal methods
- Add 50+ docstrings with parameter/return documentation
- Improve IDE autocomplete and static analysis

### Deliverables

#### 5.1 Type Hints Additions

**Priority Order:**
1. **High Impact** (do first):
   - `_parse_*_section()` methods → `Optional[SectionNode]`
   - `_parse_statement()` → `Optional[Statement]`
   - `_parse_data_item()` → `Optional[DataItem]`
   - `current_token()` → `Optional[Token]`
   - `advance()` → `None`

2. **Medium Impact**:
   - Helper functions in common.py (all ~20 functions)
   - Error handling methods (5-6 methods)
   - Location tracking methods (3-4 methods)

3. **Low Impact**:
   - Utility methods (<15 lines)
   - Private helper methods with obvious types

**Example - Before:**
```python
def _parse_data_item(self):
    """Parse a data item definition"""
    # ... 40 lines of implementation
```

**Example - After:**
```python
def _parse_data_item(self) -> Optional[DataItem]:
    """
    Parse a data item definition.
    
    Handles PIC clauses, VALUE clauses, USAGE clauses, etc.
    
    Returns:
        DataItem AST node if successful, None on error
    
    Raises:
        ParserError: If data item structure is invalid (FAIL_FAST mode only)
    """
    # ... 40 lines of implementation
```

#### 5.2 Docstring Additions

**Standard Format (Google Style):**
```python
def _parse_perform_statement(self, is_inline: bool = False) -> Optional[PerformStatement]:
    """
    Parse PERFORM statement (inline or paragraph-based).
    
    Handles both formats:
    - PERFORM paragraph-name [THRU paragraph-name]
    - PERFORM statement END-PERFORM
    
    Args:
        is_inline: Whether parsing inline PERFORM...END-PERFORM
    
    Returns:
        PerformStatement AST node containing:
        - target: Paragraph name or inline statements list
        - varying_clause: Optional VARYING specification
        - until_clause: Optional UNTIL condition
    
    Raises:
        ParserError: If PERFORM structure is malformed
    
    Examples:
        >>> parser.parse("PERFORM main-paragraph.")
        >>> parser.parse("PERFORM UNTIL done MOVE 1 TO x END-PERFORM")
    """
```

**Docstring Checklist for 50+ Methods:**
- [ ] 1-line summary
- [ ] Multi-line description of what it does
- [ ] Args: section with parameter types and meanings
- [ ] Returns: section with return type and content description
- [ ] Raises: section listing exceptions
- [ ] Examples: 1-2 code snippets showing usage

### Implementation Guidelines

**Use Union types for flexibility:**
```python
# BAD: Too specific, breaks on dialect variations
def parse_file_description(self) -> FileDescription:
    ...

# GOOD: Explicit about optional nature
def parse_file_description(self) -> Optional[FileDescription]:
    ...

# BETTER: Shows alternatives
from typing import Union
def parse_item(self) -> Union[DataItem, FileDescription, None]:
    ...
```

**Avoid `Any` type where possible:**
```python
# BAD
def parse_clause(self) -> Any:
    ...

# GOOD
def parse_clause(self) -> Union[str, int, List[Token], None]:
    ...
```

**Type hints for complex return values:**
```python
# Return tuple with (node, remaining_tokens)
def parse_select_statement(self) -> Tuple[Optional[SelectStatement], List[Token]]:
    ...

# Return dict with specific keys
def parse_metadata(self) -> Dict[str, Union[str, int]]:
    ...

# Return list of specific types
def parse_paragraphs(self) -> List[Paragraph]:
    ...
```

### File-by-File Type Hint Plan

| File | Methods | Est. Lines | Priority |
|------|---------|-----------|----------|
| parser.py | 12 coordinator | +30 | High |
| identification.py | 6 methods | +20 | High |
| environment.py | 8 methods | +30 | High |
| data.py | 12 methods | +50 | High |
| procedure.py | 15 methods | +60 | High |
| common.py | 20 helpers | +25 | Medium |
| **Total** | **73** | **+215** | |

### Testing
- mypy type checking: 0 errors in strict mode
- pyright validation for VSCode integration
- No runtime behavior changes

### Success Criteria
✅ mypy `--strict` mode: 0 errors
✅ All public/protected methods have return types
✅ All parameters have type hints (except `self`)
✅ 50+ docstrings added
✅ All tests pass
✅ Docstring coverage >85% for public API

---

## Phase 6: Testing & Validation (Week 3-4)

### Objectives
- Comprehensive testing of modular architecture
- Zero breaking changes validation
- Performance benchmarking
- Documentation of module boundaries

### Deliverables

#### 6.1 Contract Tests (Module Boundaries)
**File:** `tests/contracts/test_division_parsers.py`

```python
import pytest
from cobolparser.parser.identification import IdentificationDivisionParser
from cobolparser.parser.environment import EnvironmentDivisionParser
from cobolparser.parser.data import DataDivisionParser
from cobolparser.parser.procedure import ProcedureDivisionParser

class TestIdentificationDivisionParser:
    """Contract tests for IdentificationDivisionParser"""
    
    def test_parser_accepts_parser_instance(self):
        """Parser must accept parser_instance in constructor"""
        mock_parser = MockParser()
        parser = IdentificationDivisionParser(mock_parser)
        assert parser.parser is mock_parser
    
    def test_parse_returns_ast_node(self):
        """parse() must return IdentificationDivision or None"""
        # [5-10 additional contract tests per division parser]

class TestModuleBoundaries:
    """Verify modules don't depend on each other inappropriately"""
    
    def test_identification_parser_imports(self):
        """Identification parser only imports from base/common"""
        # Ensure no circular imports
        from cobolparser.parser import identification
        imported_modules = get_imported_modules(identification)
        assert 'environment' not in imported_modules
        assert 'data' not in imported_modules
    
    def test_no_cross_division_parsing_calls(self):
        """Division parsers don't call each other's parse methods"""
        # Static analysis: scan module for cross-calls
        pass

class TestBackwardCompatibility:
    """Ensure existing parser API unchanged"""
    
    def test_cobol_parser_parse_signature(self):
        """CobolParser.parse(source) signature unchanged"""
        from cobolparser import CobolParser
        import inspect
        sig = inspect.signature(CobolParser.parse)
        assert 'source_code' in sig.parameters
    
    def test_ast_structure_unchanged(self):
        """AST output identical to pre-refactoring"""
        # Run on 10 sample programs, compare JSON output
        pass
```

#### 6.2 Integration Tests
**File:** `tests/integration/test_division_integration.py`

```python
class TestDivisionIntegration:
    """End-to-end division parsing"""
    
    def test_full_program_parsing(self):
        """Parse complete program with all divisions"""
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-PROGRAM.
        
        ENVIRONMENT DIVISION.
        INPUT-OUTPUT SECTION.
        FILE-CONTROL.
            SELECT input-file ...
        
        DATA DIVISION.
        FILE SECTION.
        FD input-file.
        01 input-record PIC X(80).
        
        PROCEDURE DIVISION.
            DISPLAY "Hello"
            GOBACK.
        """
        result = parse(source)
        assert result.success
        assert result.ast.identification.program_id == "TEST-PROGRAM"
        assert len(result.ast.data.file_section) == 1
        assert len(result.ast.procedure.statements) == 2
    
    def test_division_ordering_enforcement(self):
        """Divisions must appear in correct order"""
        # Data before Procedure should fail
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        
        DATA DIVISION.
        PROCEDURE DIVISION.
        IDENTIFICATION DIVISION.
        """
        result = parse(source)
        assert not result.success
    
    def test_complex_nested_statements(self):
        """Parse deeply nested PERFORM/IF/EVALUATE"""
        # Load complex_program.cob and verify all 200+ statements parsed
        pass
```

#### 6.3 Unit Tests for Each Module

| Module | Tests | Focus |
|--------|-------|-------|
| identification.py | 8 tests | Program ID, metadata, edge cases |
| environment.py | 12 tests | SELECT, FILE-CONTROL, I-O-CONTROL |
| data.py | 15 tests | FD, WORKING-STORAGE, nested items, COMP-3 |
| procedure.py | 12 tests | Statements, PERFORM, nested structures |
| common.py | 10 tests | Helper functions, decorators |
| **Total** | **57** | |

**Example Test - common.py:**
```python
def test_expect_keyword_advances_on_match():
    """expect_keyword advances position when token matches"""
    parser = MockParser(tokens=[Token("SELECT"), Token("filename")])
    assert expect_keyword(parser, "SELECT") is True
    assert parser.position == 1

def test_expect_keyword_errors_on_mismatch():
    """expect_keyword raises error when token doesn't match"""
    parser = MockParser(tokens=[Token("FILE")])
    with pytest.raises(ParserError):
        expect_keyword(parser, "SELECT")
```

#### 6.4 Performance Benchmarking

**File:** `tests/performance/benchmark_refactoring.py`

```python
import timeit
import psutil
from cobolparser import CobolParser

class TestPerformance:
    """Verify refactoring didn't regress performance"""
    
    def test_parse_speed_maintained(self):
        """Refactored parser parses test programs in similar time"""
        test_programs = [
            "samples/small_program.cob",      # ~100 lines
            "samples/medium_program.cob",     # ~500 lines
            "samples/large_program.cob",      # ~2000 lines
            "samples/complex_program.cob",    # ~5000 lines, nested
        ]
        
        parser = CobolParser()
        baseline = {
            "small": 0.005,    # seconds (pre-refactoring measured)
            "medium": 0.025,
            "large": 0.15,
            "complex": 0.35,
        }
        
        for size, prog_file in zip(["small", "medium", "large", "complex"], test_programs):
            with open(prog_file) as f:
                source = f.read()
            
            start = time.time()
            for _ in range(10):
                result = parser.parse(source)
            elapsed = (time.time() - start) / 10
            
            # Allow 10% slowdown (acceptable for modularization)
            assert elapsed < baseline[size] * 1.1, \
                f"{size} program: {elapsed:.3f}s (baseline: {baseline[size]:.3f}s)"
    
    def test_memory_usage_stable(self):
        """Memory usage remains within bounds on large programs"""
        with open("samples/large_5mb.cob") as f:
            source = f.read()
        
        parser = CobolParser()
        process = psutil.Process()
        
        mem_before = process.memory_info().rss / 1024 / 1024  # MB
        result = parser.parse(source)
        mem_after = process.memory_info().rss / 1024 / 1024
        
        mem_increase = mem_after - mem_before
        assert mem_increase < 500, f"Memory increased by {mem_increase:.1f}MB"
```

#### 6.5 Code Quality Validation

```bash
# Type checking (Phase 5 output)
mypy cobolparser/ --strict --show-error-codes

# Linting
ruff check cobolparser/
  - C901: complexity
  - E501: line length (100 chars)
  - D100-D103: docstrings

# Code coverage
pytest --cov=cobolparser --cov-fail-under=90

# Metrics
wc -l cobolparser/*.py cobolparser/parser/*.py
pylint cobolparser/ --max-line-length=100
```

#### 6.6 Module Documentation

**File:** `docs/PARSER_ARCHITECTURE.md`

```markdown
# Parser Architecture After Refactoring

## Module Hierarchy

```
CobolParser (coordinator)
├── IdentificationDivisionParser
│   └── parse() → IdentificationDivision
├── EnvironmentDivisionParser
│   └── parse() → EnvironmentDivision
├── DataDivisionParser
│   └── parse() → DataDivision
├── ProcedureDivisionParser
│   └── parse() → ProcedureDivision
└── common (utilities)
    ├── expect_keyword()
    ├── match_identifier()
    ├── @expect_token_value decorator
    └── ...
```

## Data Flow

```
Source Code
    ↓ (Lexer)
Tokens
    ↓ (CobolParser)
    ├→ IdentificationDivisionParser.parse()
    ├→ EnvironmentDivisionParser.parse()
    ├→ DataDivisionParser.parse()
    └→ ProcedureDivisionParser.parse()
    ↓
Program AST
    ↓ (to_dict())
JSON
```

## Module Responsibilities

### IdentificationDivisionParser
- PROGRAM-ID, AUTHOR, INSTALLATION
- ~250 lines, minimal complexity

### EnvironmentDivisionParser
- FILE-CONTROL (SELECT statements)
- I-O-CONTROL, CONFIGURATION SECTION
- ~400 lines, medium complexity (SELECT is complex)

### DataDivisionParser
- FD/SD parsing
- Data item hierarchies
- PIC clause parsing, COMP-3 support
- ~600 lines, high complexity

### ProcedureDivisionParser
- Statements: MOVE, DISPLAY, PERFORM, etc.
- Paragraph/section definitions
- Statement nesting (IF, PERFORM)
- ~500 lines, high complexity

### common.py
- Shared token matching: `expect_keyword()`, `match_identifier()`
- Decorators: `@expect_token_value()`, `@skip_to_keyword()`
- ~200 lines utility code

## No Breaking Changes

All changes maintain backward compatibility:
- `CobolParser.parse()` signature unchanged
- AST output structure identical
- Error reporting unchanged
- All existing tests pass
```

### Testing Execution Plan

**Week 3:**
```bash
# Add contract tests
pytest tests/contracts/ -v

# Add unit tests per module
pytest tests/unit/parser/ -v

# Coverage check
pytest --cov=cobolparser.parser --cov-fail-under=90
```

**Week 4:**
```bash
# Integration tests
pytest tests/integration/ -v

# Performance benchmarks
python tests/performance/benchmark_refactoring.py

# Final validation
mypy cobolparser/ --strict
ruff check cobolparser/
pytest  # All 114 original + 57 new tests
```

### Success Criteria
✅ All 114 existing tests pass
✅ 57+ new tests added (50%+ coverage of new modules)
✅ mypy strict: 0 errors
✅ Coverage ≥90%
✅ Performance regression <10%
✅ Zero breaking changes (backward compatibility verified)
✅ All docstrings present (100%)

---

## Timeline Summary

| Phase | Duration | Deliverables | Risk |
|-------|----------|--------------|------|
| 1: Constants | 2-3 days | constants.py, ErrorCode enum | Low |
| 2: Helpers | 2-3 days | common.py decorators/functions | Low |
| 3: Division Modules | 4-5 days | 4 parsers, 1000+ lines extracted | Low |
| 4: Coordinator | 1-2 days | Refactored parser.py (200 lines) | Low |
| 5: Types/Docs | 3-4 days | Type hints, 50+ docstrings | Low |
| 6: Testing | 3-4 days | Contract/unit/integration tests | Low |
| **Total** | **16-21 days** | **Fully modular, typed, documented** | **Low** |

---

## Rollback Strategy

Each phase is independently reversible:

1. **Phase 1-2:** Delete constants.py and common.py, remove imports ✅ Old parser.py unchanged
2. **Phase 3:** Delete division modules, restore parser.py from git ✅ Full revert in seconds
3. **Phase 4-6:** Test/doc changes have zero impact on functionality ✅ Can delete without effect

---

## Success Metrics

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| parser.py size | 4,127 lines | 250 lines | ✅ |
| Max method length | 180 lines | <60 lines | ✅ |
| Code duplication | 20% | <5% | ✅ |
| Type coverage | 10% | 100% | ✅ |
| Docstring coverage | 20% | 100% | ✅ |
| Test coverage | 87% | 92%+ | ✅ |
| Cyclomatic complexity | avg 12 | avg <8 | ✅ |
| Module count | 3 (lexer, parser, models) | 10 (+ division modules) | ✅ |

---

## Risk Mitigation

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|-----------|
| Breaking AST changes | Low | Critical | Zero logic changes in Phases 1-4; comprehensive contract tests |
| Performance regression | Low | Medium | Benchmarking in Phase 6; <10% tolerance |
| Type hint conflicts | Medium | Low | Use `Union[]` and `Optional[]` liberally; gradual adoption |
| Circular imports | Medium | High | Careful layer design (common→division→coordinator); imports audit |
| Test failures mid-phase | Low | Medium | Run 114 tests after each phase; halt if any fail |

---

## Dependencies & Sequencing

**Hard Dependencies:**
- Phase 1 → Phases 2-3 (need constants for imports)
- Phase 3 → Phase 4 (need division modules to extract)
- Phases 1-4 → Phases 5-6 (testing/docs depend on architecture)

**Can Overlap:**
- Phase 1 and 2 (independent utilities)
- Phase 2 and 3 (helpers don't block extraction)
- Phase 5 and 6 (can add types while writing tests)

---

## Execution Checklist

### Pre-Refactoring
- [ ] All 114 tests passing
- [ ] Git branch created (`refactor/modularize-parser`)
- [ ] Baseline metrics recorded (code complexity, speed, memory)

### Phase 1
- [ ] constants.py created with 50+ keyword definitions
- [ ] ErrorCode enum finalized
- [ ] All parser.py magic strings replaced with constants
- [ ] Tests passing

### Phase 2
- [ ] common.py created with 20+ helper functions
- [ ] 5-6 decorator patterns implemented
- [ ] Parser.py methods refactored to use helpers
- [ ] Tests passing

### Phase 3
- [ ] identification.py (200 lines)
- [ ] environment.py (400 lines)
- [ ] data.py (600 lines)
- [ ] procedure.py (500 lines)
- [ ] Tests passing

### Phase 4
- [ ] Parser.py reduced to coordinator (~200 lines)
- [ ] Delegation pattern implemented
- [ ] All imports updated
- [ ] Tests passing

### Phase 5
- [ ] mypy --strict: 0 errors
- [ ] 50+ docstrings added
- [ ] 80+ type hints added
- [ ] Tests passing

### Phase 6
- [ ] 57+ new tests added
- [ ] Performance benchmark complete (<10% regression)
- [ ] All 171 tests passing
- [ ] Coverage ≥90%
- [ ] Documentation updated

### Post-Refactoring
- [ ] Code review approved
- [ ] Branch merged to main
- [ ] Release notes updated
- [ ] v2.0.0 published

---

## Questions for Team

1. **Decorator Complexity:** Use full decorators (Phase 2) or simple helper functions? Decorators add sophistication but may complicate testing.

2. **Type Hint Strictness:** Target mypy `--strict` (harder, more time) or `--standard` (easier, more flexible)?

3. **Docstring Format:** Google-style (used above) or NumPy-style or Sphinx-style?

4. **Test Organization:** Keep tests/unit/parser tests together or reorganize by feature (tests/features/)?

5. **Phase 3 Order:** Extract which division first? Recommend: identification (simplest) → environment → data (hardest) → procedure

---

## Next Steps

1. **Review & Feedback** on this plan (2 days)
2. **Create feature branch:** `git checkout -b refactor/modularize-parser`
3. **Begin Phase 1** once approved

---

**Plan Status:** Ready for approval and execution ✅
