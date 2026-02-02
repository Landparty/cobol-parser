# IBM Enterprise COBOL Dialect: Registration Example

## Overview

This document demonstrates how the COBOL parser prioritizes and registers IBM Enterprise COBOL extensions, specifically EXEC SQL and EXEC CICS statements.

## IBM Enterprise COBOL Extensions Supported

### 1. EXEC SQL - Embedded SQL Statements

Allows embedding SQL directly in COBOL programs:

```cobol
IDENTIFICATION DIVISION.
PROGRAM-ID. DATABASE-QUERY.
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-CUSTOMER-NAME PIC X(50).
01 WS-CUSTOMER-ID PIC 9(10).

PROCEDURE DIVISION.
    EXEC SQL
        SELECT CUSTOMER_NAME INTO :WS-CUSTOMER-NAME
        FROM CUSTOMERS
        WHERE CUSTOMER_ID = :WS-CUSTOMER-ID
    END-EXEC.
    
    DISPLAY WS-CUSTOMER-NAME.
    STOP RUN.
```

### 2. EXEC CICS - CICS Transaction Server Commands

Allows CICS transaction management:

```cobol
IDENTIFICATION DIVISION.
PROGRAM-ID. CICS-TRANSACTION.
PROCEDURE DIVISION.
    EXEC CICS
        RECEIVE INTO CICS-DATA-BUFFER
        LENGTH WS-BUFFER-LENGTH
    END-EXEC.
    
    EXEC CICS
        SEND TEXT
        FROM OUTPUT-MESSAGE
        LENGTH WS-MESSAGE-LENGTH
    END-EXEC.
    
    STOP RUN.
```

## Architecture: How IBM Extensions Are Registered

### Registration Order (Priority)

The statement parser registry is built with specific priorities to ensure IBM extensions are recognized before standard COBOL statements:

```python
# In cobolparser/parsers/divisions/procedure.py
# Method: _create_statement_registry()

def _create_statement_registry(self) -> StatementParserRegistry:
    """Create and configure statement parser registry with IBM support."""
    registry = StatementParserRegistry()
    
    # Priority 1-2: IBM Extensions (checked first - most specific)
    # These are multi-token patterns requiring specific lookahead
    from cobolparser.parsers.statements.ibm_exec_statements import (
        ExecSqlStatementParser,
        ExecCicsStatementParser
    )
    registry.register(ExecSqlStatementParser(), 1)   # EXEC SQL...
    registry.register(ExecCicsStatementParser(), 2)  # EXEC CICS...
    
    # Priority 3-5: Control Flow (more complex multi-statement blocks)
    from cobolparser.parsers.statements.if_parser import IfStatementParser
    from cobolparser.parsers.statements.perform_parser import PerformStatementParser
    from cobolparser.parsers.statements.evaluate_parser import EvaluateStatementParser
    
    registry.register(IfStatementParser(), 3)
    registry.register(PerformStatementParser(), 4)
    registry.register(EvaluateStatementParser(), 5)
    
    # Priority 6-13: Standard Statements (simple single-statement types)
    from cobolparser.parsers.statements.display_parser import DisplayStatementParser
    from cobolparser.parsers.statements.move_parser import MoveStatementParser
    from cobolparser.parsers.statements.call_parser import CallStatementParser
    from cobolparser.parsers.statements.arithmetic_parsers import (
        ComputeStatementParser, AddStatementParser,
        SubtractStatementParser, MultiplyStatementParser, DivideStatementParser
    )
    
    registry.register(DisplayStatementParser(), 6)
    registry.register(MoveStatementParser(), 7)
    registry.register(CallStatementParser(), 8)
    registry.register(ComputeStatementParser(), 9)
    registry.register(AddStatementParser(), 10)
    registry.register(SubtractStatementParser(), 11)
    registry.register(MultiplyStatementParser(), 12)
    registry.register(DivideStatementParser(), 13)
    
    return registry
```

### Why This Priority Order?

**Priority 1-2 (IBM Extensions):**
- Most specific (multi-token patterns)
- Less common than standard statements
- Would be ambiguous if checked after standard statements
- EXEC is not a standard COBOL keyword, so no conflicts

**Priority 3-5 (Control Flow):**
- Complex nested structures
- Require statement-level resolution
- Can contain other statements inside

**Priority 6-13 (Standard Statements):**
- Single-operation statements
- Most common in typical programs
- Should be checked last (fallback)

## Implementation Details: ExecSqlStatementParser

The EXEC SQL parser demonstrates IBM extension implementation:

```python
# In cobolparser/parsers/statements/ibm_exec_statements.py

class ExecSqlStatementParser(IStatementParser):
    """Parser for EXEC SQL statements (embedded SQL in COBOL)."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """
        Check if next tokens are EXEC SQL.
        
        Uses multi-token lookahead to distinguish from other EXEC variants.
        """
        try:
            # Get first token
            token = token_stream.peek(0)
            if not token:
                return False
            
            # Check first token: EXEC
            if not (token.type == TokenType.IDENTIFIER and 
                   token.value and 
                   token.value.upper() == "EXEC"):
                return False
            
            # Peek at next token without consuming
            # This requires lookahead_size >= 2
            next_token = token_stream.peek(1)
            if not next_token:
                return False
            
            # Check second token: SQL (distinguishes from EXEC CICS)
            return (next_token.type == TokenType.IDENTIFIER and 
                   next_token.value and 
                   next_token.value.upper() == "SQL")
        
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> ASTNode:
        """
        Parse EXEC SQL statement.
        
        Structure:
            EXEC SQL
                <SQL statements>
            END-EXEC.
        
        Simplified implementation shows the concept.
        In production, would parse full SQL syntax.
        """
        # Consume EXEC keyword
        start_token = token_stream.consume()
        start_location = start_token.location if start_token else SourceLocation(0, 0)
        
        # Consume SQL keyword
        if not token_stream.is_empty():
            token_stream.consume()
        
        # Parse SQL content until END-EXEC
        sql_tokens = []
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token:
                break
            
            # Check for END-EXEC terminator
            if (token.type == TokenType.IDENTIFIER and 
                token.value and 
                token.value.upper() == "END-EXEC"):
                token_stream.consume()
                break
            
            # Collect SQL tokens
            sql_tokens.append(token)
            token_stream.consume()
        
        # Create AST node
        class ExecSqlStatement(ASTNode):
            def __init__(self, location):
                super().__init__("EXEC_SQL", location)
                self.sql_content = ""
            
            def to_dict(self):
                return {
                    "node_type": self.node_type,
                    "location": self.location.to_dict(),
                    "sql_content": self.sql_content
                }
        
        stmt = ExecSqlStatement(start_location)
        stmt.sql_content = " ".join([t.value for t in sql_tokens if t.value])
        
        return stmt
```

## Token Stream Multi-Token Lookahead

The TokenStream supports configurable lookahead depth:

```python
# Creating a token stream with multi-token lookahead

from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token

# Default lookahead_size=2 (supports EXEC SQL, EXEC CICS matching)
stream = TokenStream(tokens, lookahead_size=2)

# Access tokens without consuming
first = stream.peek(0)   # Current token
second = stream.peek(1)  # Next token
third = stream.peek(2)   # Will use remaining default lookahead

# Or create with custom lookahead for more complex patterns
stream = TokenStream(tokens, lookahead_size=4)
first = stream.peek(0)
second = stream.peek(1)
third = stream.peek(2)
fourth = stream.peek(3)
```

## Comparison: EXEC SQL vs EXEC CICS

Both use EXEC as first token, distinguished by second token:

```
EXEC SQL...        ← ExecSqlStatementParser matches
        ← Second token is "SQL"

EXEC CICS...       ← ExecCicsStatementParser matches
        ← Second token is "CICS"

EXEC...            ← Neither matches
        ← Second token is something else (would fail parse)
```

### Dispatch Mechanism

1. **Procedure Division Parser** encounters EXEC token
2. **ProcedureDivisionParser._parse_paragraph_statements()** queries registry
3. **StatementParserRegistry.find_parser()** iterates in priority order:
   - Check ExecSqlStatementParser (priority 1)
     - `matches()` checks peek(0)=="EXEC" and peek(1)=="SQL" → TRUE
     - Returns ExecSqlStatementParser immediately (first-match strategy)
   - (ExecCicsStatementParser never checked since match found)
4. **ExecSqlStatementParser.parse()** handles full SQL statement
5. Returns ExecSqlStatement AST node

## IBM COBOL Features Supported

### 1. EXEC SQL

```cobol
EXEC SQL
    DECLARE CURSOR CURSOR1 FOR
        SELECT * FROM EMPLOYEES
        WHERE SALARY > 50000
END-EXEC.

EXEC SQL
    OPEN CURSOR1
END-EXEC.

EXEC SQL
    FETCH FROM CURSOR1 INTO :WS-EMPLOYEE
END-EXEC.
```

**Features:**
- Embedded SQL statements
- Host variable binding (`:variable`)
- Cursor operations
- Transaction control

### 2. EXEC CICS

```cobol
EXEC CICS
    RECEIVE INTO DATA-AREA
    LENGTH DATA-LENGTH
END-EXEC.

EXEC CICS
    SEND TEXT
    FROM OUTPUT-AREA
    LENGTH OUTPUT-LENGTH
    ERASE
END-EXEC.

EXEC CICS
    LINK PROGRAM('PROGRAM2')
    COMMAREA(COMMUNICATION-AREA)
    LENGTH 100
END-EXEC.
```

**Features:**
- Terminal communication
- Inter-program linking
- Resource management
- Task control

### 3. COMP-3 Data Items

Supported in Data Division:

```cobol
DATA DIVISION.
WORKING-STORAGE SECTION.
01 WS-PACKED-DECIMAL PIC 9(7)V99 COMP-3.
01 WS-BINARY-DATA PIC 9(4) COMP-2.
```

**Features:**
- Packed decimal storage
- Binary representation
- Memory-efficient numeric storage

## Testing IBM Extensions

### Unit Test Example

```python
# In tests/unit/test_ibm_extensions.py

import pytest
from cobolparser import CobolParser
from cobolparser.parsers.statements.ibm_exec_statements import ExecSqlStatementParser
from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation

def test_exec_sql_statement_matches():
    """Test that EXEC SQL pattern is recognized."""
    tokens = [
        Token(TokenType.IDENTIFIER, "EXEC", SourceLocation(1, 1)),
        Token(TokenType.IDENTIFIER, "SQL", SourceLocation(1, 6)),
    ]
    stream = TokenStream(tokens, lookahead_size=2)
    parser = ExecSqlStatementParser()
    
    assert parser.matches(stream)

def test_exec_cics_statement_not_matched_by_sql_parser():
    """Test that EXEC CICS is not matched by SQL parser."""
    tokens = [
        Token(TokenType.IDENTIFIER, "EXEC", SourceLocation(1, 1)),
        Token(TokenType.IDENTIFIER, "CICS", SourceLocation(1, 6)),  # Not SQL
    ]
    stream = TokenStream(tokens, lookahead_size=2)
    parser = ExecSqlStatementParser()
    
    assert not parser.matches(stream)

def test_exec_sql_integration():
    """Test EXEC SQL in complete COBOL program."""
    source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. SQL-TEST.
        PROCEDURE DIVISION.
            EXEC SQL
                SELECT * FROM TABLE
            END-EXEC.
            STOP RUN.
    """
    
    parser = CobolParser()
    result = parser.parse(source)
    
    assert result.success
    # Find EXEC SQL statement in AST
    proc = result.ast.get_division("PROCEDURE")
    found = False
    for para in proc.paragraphs:
        for stmt in para.statements:
            if stmt.node_type == "EXEC_SQL":
                found = True
    assert found, "EXEC SQL statement not found in AST"
```

### Integration Test Example

```python
# In tests/integration/test_ibm_extensions_integration.py

def test_sql_and_cics_mixed_program():
    """Test program with both EXEC SQL and EXEC CICS."""
    source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. MIXED-IBM.
        PROCEDURE DIVISION.
            EXEC SQL
                SELECT NAME FROM EMPLOYEES
            END-EXEC.
            
            EXEC CICS
                SEND TEXT FROM OUTPUT-AREA
            END-EXEC.
            
            STOP RUN.
    """
    
    parser = CobolParser()
    result = parser.parse(source)
    
    assert result.success
    
    # Find both statement types
    proc = result.ast.get_division("PROCEDURE")
    sql_found = False
    cics_found = False
    
    for para in proc.paragraphs:
        for stmt in para.statements:
            if stmt.node_type == "EXEC_SQL":
                sql_found = True
            elif stmt.node_type == "EXEC_CICS":
                cics_found = True
    
    assert sql_found, "EXEC SQL not found"
    assert cics_found, "EXEC CICS not found"
```

## Performance Characteristics of IBM Extensions

### Parsing Overhead

- **EXEC SQL/CICS detection:** O(1) - just peek(0) and peek(1)
- **Registry lookup:** O(n) where n = number of registered parsers
- **Statement parsing:** O(m) where m = tokens in statement

Typical overhead is negligible since:
1. Multi-token lookahead is minimal (2 tokens)
2. Registry first-match strategy exits early
3. EXEC statements are typically <1% of program content

### Memory Usage

- TokenStream lookahead buffer: ~1KB for 2-token lookahead
- ExecSqlStatementParser instance: ~500 bytes
- ExecCicsStatementParser instance: ~500 bytes

## Extending IBM Support

To add new IBM extensions:

```python
# 1. Create parser implementing IStatementParser
class ExecImsStatementParser(IStatementParser):
    def matches(self, token_stream):
        # Check for EXEC IMS pattern
        return (token_stream.peek(0).value.upper() == "EXEC" and
                token_stream.peek(1).value.upper() == "IMS")
    
    def parse(self, token_stream):
        # Parse EXEC IMS...END-EXEC block
        pass

# 2. Register in registry (high priority for IBM extensions)
registry.register(ExecImsStatementParser(), 1)  # IBM extensions go first

# Note: You may need to adjust existing priorities if adding
# EXEC variants with different second tokens
```

## Troubleshooting

### Problem: EXEC SQL not recognized

**Cause:** Registry priority issue or lookahead size too small

**Solution:**
```python
# Ensure registry is created with IBM parsers
def _create_statement_registry(self):
    registry = StatementParserRegistry()
    # Make sure ExecSqlStatementParser is registered
    registry.register(ExecSqlStatementParser(), 1)
    return registry

# Ensure lookahead size >= 2
stream = TokenStream(tokens, lookahead_size=2)
```

### Problem: EXEC CICS matches SQL parser

**Cause:** Parser matches too loosely, doesn't check second token

**Solution:**
```python
def matches(self, token_stream):
    # ALWAYS check both tokens, not just first
    first = token_stream.peek(0)
    second = token_stream.peek(1)
    return (first.value.upper() == "EXEC" and
            second.value.upper() == "SQL")  # Not just checking EXEC
```

## References

- **IBM COBOL SQL Support:** [IBM Enterprise COBOL Docs](ibm-enterprise.md)
- **Statement Parser Architecture:** [Extension Guide](factory-extension-guide.md)
- **TokenStream Multi-Token Lookahead:** [Parser Internals](PARSER_INVOCATION_GUIDE.md)
- **Registry First-Match Strategy:** [Registry Documentation](../cobolparser/core/registry.py)

## Summary

IBM Enterprise COBOL extensions (EXEC SQL, EXEC CICS) are registered with highest priority in the statement parser registry, allowing multi-token pattern matching to distinguish different EXEC variants. The architecture supports easy addition of new IBM extensions by:

1. Implementing `IStatementParser` with multi-token lookahead
2. Registering with appropriate priority
3. Ensuring TokenStream has sufficient lookahead depth

This design maintains performance and simplicity while providing extensibility for IBM COBOL dialects.
