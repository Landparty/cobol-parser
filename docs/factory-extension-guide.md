# Extension Guide: Creating Custom Statement Parsers

## Overview

This guide shows how to extend the COBOL parser with custom statement types using the registry-based architecture and ASTNodeFactory.

## The Three-Step Process

1. **Create a Statement AST Node** - Define the data structure
2. **Implement a Statement Parser** - Implement IStatementParser interface
3. **Register with the Registry** - Make parser available to procedure division

## Step 1: Create a Custom AST Node

First, define an AST node class for your custom statement:

```python
# In cobolparser/models/statements.py or custom file

from cobolparser.models.ast_base import ASTNode, SourceLocation
from typing import List, Optional, Dict, Any

class CustomStatement(ASTNode):
    """AST node for custom COBOL statement."""
    
    def __init__(self, location: SourceLocation):
        super().__init__("CUSTOM_STATEMENT", location)
        self.parameters: List[str] = []
        self.options: Dict[str, str] = {}
    
    def add_parameter(self, param: str) -> None:
        """Add a parameter to the statement."""
        self.parameters.append(param)
    
    def set_option(self, name: str, value: str) -> None:
        """Set an option for the statement."""
        self.options[name] = value
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "node_type": self.node_type,
            "location": self.location.to_dict(),
            "parameters": self.parameters,
            "options": self.options,
            "children": [child.to_dict() for child in self.children]
        }
```

### Node Structure Best Practices

1. **Always call `super().__init__()`** with proper node_type
2. **Implement `to_dict()`** for JSON serialization
3. **Use typed attributes** for clarity
4. **Add helper methods** for safe field updates
5. **Include location tracking** in all important data

## Step 2: Implement a Statement Parser

Create a parser implementing `IStatementParser`:

```python
# In cobolparser/parsers/statements/custom_parser.py

from cobolparser.core.interfaces import IStatementParser, ITokenStream
from cobolparser.core.ast_factory import get_factory
from cobolparser.models.statements import CustomStatement
from cobolparser.models.ast_base import SourceLocation, ASTNode
from cobolparser.lexer import TokenType

class CustomStatementParser(IStatementParser):
    """Parser for CUSTOM STATEMENT COBOL extension."""
    
    def matches(self, token_stream: ITokenStream) -> bool:
        """Check if next token starts a CUSTOM statement."""
        try:
            token = token_stream.peek(0)
            if not token:
                return False
            
            # Match CUSTOM keyword
            if (token.type == TokenType.IDENTIFIER and 
                token.value and 
                token.value.upper() == "CUSTOM"):
                return True
            
            # Could also match multi-token patterns:
            # next_token = token_stream.peek(1)
            # if (token.value.upper() == "SPECIAL" and 
            #     next_token.value.upper() == "CUSTOM"):
            #     return True
            
            return False
        except Exception:
            return False
    
    def parse(self, token_stream: ITokenStream) -> ASTNode:
        """Parse a CUSTOM statement."""
        # Get starting token for location tracking
        start_token = token_stream.consume()
        location = start_token.location if start_token else SourceLocation(0, 0)
        
        # Create node using factory
        factory = get_factory()
        stmt = factory.create(CustomStatement, location)
        
        # Skip whitespace
        self._skip_whitespace(token_stream)
        
        # Parse parameters (anything until period or END-CUSTOM)
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            
            if not token:
                break
            
            # Check for statement terminator
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            
            # Check for explicit terminator
            if self._is_keyword(token, "END-CUSTOM"):
                token_stream.consume()
                break
            
            # Collect parameter
            if token.type == TokenType.IDENTIFIER:
                stmt.add_parameter(token.value or "")
                token_stream.consume()
            elif token.type == TokenType.STRING_LITERAL:
                stmt.add_parameter(f'"{token.value}"')
                token_stream.consume()
            else:
                # Unknown token, stop parsing
                break
            
            self._skip_whitespace(token_stream)
        
        # Set context (optional but recommended)
        factory.with_context(stmt, 'PROCEDURE')
        
        # Add metadata (optional but useful for analysis)
        factory.with_metadata(stmt, {
            'custom_parser_version': '1.0',
            'parameters_count': len(stmt.parameters)
        })
        
        return stmt
    
    @staticmethod
    def _is_keyword(token, keyword: str) -> bool:
        """Check if token is a specific keyword (case-insensitive)."""
        if not token or not hasattr(token, 'value'):
            return False
        return (token.type == TokenType.IDENTIFIER and 
                token.value and 
                token.value.upper() == keyword.upper())
    
    @staticmethod
    def _skip_whitespace(token_stream: ITokenStream) -> None:
        """Skip whitespace tokens."""
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            if not token or token.type not in (TokenType.WHITESPACE,
                                              TokenType.NEWLINE):
                break
            token_stream.consume()
```

### Parser Implementation Best Practices

1. **Always implement both `matches()` and `parse()`**
   - `matches()`: Should be fast and non-destructive
   - `parse()`: Consumes tokens and returns ASTNode

2. **Use factory for consistent node creation**
   ```python
   factory = get_factory()
   node = factory.create(YourStatement, location)
   ```

3. **Track source locations accurately**
   ```python
   start_token = token_stream.consume()
   location = start_token.location if start_token else SourceLocation(0, 0)
   ```

4. **Handle edge cases**
   - Empty token stream
   - Unexpected token types
   - Statement terminators (period, END-*)

5. **Return ASTNode from parse()**
   - Never return None
   - Return proper node type even if parsing incomplete

6. **Add metadata for debugging**
   ```python
   factory.with_metadata(node, {
       'parser_class': self.__class__.__name__,
       'tokens_consumed': token_count
   })
   ```

## Step 3: Register with the Statement Parser Registry

Now register your parser so the procedure division can find it:

```python
# In cobolparser/parsers/divisions/procedure.py
# In the _create_statement_registry() method

def _create_statement_registry(self) -> StatementParserRegistry:
    """Create and configure the statement parser registry."""
    registry = StatementParserRegistry()
    
    # ... existing registrations ...
    
    # Register custom parser (priority order matters!)
    from cobolparser.parsers.statements.custom_parser import CustomStatementParser
    
    # Register with appropriate priority
    # Higher priority = checked first
    registry.register(CustomStatementParser(), 14)  # After built-in parsers
    
    return registry
```

### Priority Guidelines

1. **Priority 1-3:** IBM extensions (EXEC SQL, EXEC CICS, etc.)
2. **Priority 4-10:** Control flow statements (IF, PERFORM, etc.)
3. **Priority 11-15:** Standard statements (MOVE, DISPLAY, etc.)
4. **Priority 16+:** Custom extensions

```python
# Built-in priority scheme:
registry.register(ExecSqlStatementParser(), 1)      # EXEC SQL
registry.register(ExecCicsStatementParser(), 2)     # EXEC CICS
registry.register(IfStatementParser(), 3)           # IF
registry.register(PerformStatementParser(), 4)      # PERFORM
registry.register(EvaluateStatementParser(), 5)     # EVALUATE
registry.register(DisplayStatementParser(), 6)      # DISPLAY
registry.register(MoveStatementParser(), 7)         # MOVE
registry.register(CallStatementParser(), 8)         # CALL
registry.register(ComputeStatementParser(), 9)      # COMPUTE
# ... more built-ins ...

# Custom extensions start here:
registry.register(CustomStatementParser(), 20)      # Custom statement
registry.register(YourOtherParser(), 21)            # Another custom
```

## Complete Example: CREATE TABLE Statement

Here's a full example for a custom CREATE TABLE statement:

```python
# 1. Define the node
class CreateTableStatement(ASTNode):
    def __init__(self, location: SourceLocation):
        super().__init__("CREATE_TABLE", location)
        self.table_name: Optional[str] = None
        self.columns: List[str] = []
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_type": self.node_type,
            "table_name": self.table_name,
            "columns": self.columns,
            "location": self.location.to_dict()
        }

# 2. Implement the parser
class CreateTableStatementParser(IStatementParser):
    def matches(self, token_stream: ITokenStream) -> bool:
        try:
            # Match: CREATE TABLE name (...)
            if (token_stream.peek(0).value.upper() == "CREATE" and
                token_stream.peek(1).value.upper() == "TABLE"):
                return True
        except:
            pass
        return False
    
    def parse(self, token_stream: ITokenStream) -> ASTNode:
        start_token = token_stream.consume()  # CREATE
        token_stream.consume()  # TABLE
        
        factory = get_factory()
        stmt = factory.create(CreateTableStatement, start_token.location)
        
        self._skip_whitespace(token_stream)
        
        # Parse table name
        name_token = token_stream.consume()
        stmt.table_name = name_token.value
        
        # Parse column list
        self._skip_whitespace(token_stream)
        
        while not token_stream.is_empty():
            token = token_stream.peek(0)
            
            if token.type == TokenType.PERIOD:
                token_stream.consume()
                break
            
            if token.type == TokenType.IDENTIFIER:
                stmt.columns.append(token.value)
                token_stream.consume()
            else:
                token_stream.consume()
            
            self._skip_whitespace(token_stream)
        
        return stmt
    
    @staticmethod
    def _skip_whitespace(ts: ITokenStream) -> None:
        while not ts.is_empty():
            t = ts.peek(0)
            if t and t.type in (TokenType.WHITESPACE, TokenType.NEWLINE):
                ts.consume()
            else:
                break

# 3. Register in procedure.py
registry.register(CreateTableStatementParser(), 25)
```

## Testing Custom Parsers

Write unit tests for your parser:

```python
# In tests/unit/test_custom_parser.py

import pytest
from cobolparser.core import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.custom_parser import CustomStatementParser
from cobolparser.models.statements import CustomStatement

def test_custom_statement_matches():
    """Test that parser recognizes CUSTOM keyword."""
    tokens = [
        Token(TokenType.IDENTIFIER, "CUSTOM", SourceLocation(1, 1))
    ]
    stream = TokenStream(tokens, lookahead_size=2)
    parser = CustomStatementParser()
    
    assert parser.matches(stream)

def test_custom_statement_parse():
    """Test parsing a CUSTOM statement."""
    tokens = [
        Token(TokenType.IDENTIFIER, "CUSTOM", SourceLocation(1, 1)),
        Token(TokenType.IDENTIFIER, "PARAM1", SourceLocation(1, 8)),
        Token(TokenType.IDENTIFIER, "PARAM2", SourceLocation(1, 15)),
        Token(TokenType.PERIOD, ".", SourceLocation(1, 22)),
    ]
    stream = TokenStream(tokens, lookahead_size=2)
    parser = CustomStatementParser()
    
    node = parser.parse(stream)
    
    assert isinstance(node, CustomStatement)
    assert node.parameters == ["PARAM1", "PARAM2"]
    assert stream.is_empty()

def test_custom_statement_in_procedure():
    """Test CUSTOM statement integration with procedure division."""
    source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        PROCEDURE DIVISION.
            CUSTOM PARAM1 PARAM2.
            STOP RUN.
    """
    
    from cobolparser import CobolParser
    parser = CobolParser()
    result = parser.parse(source)
    
    # Find the custom statement
    proc = result.ast.get_division("PROCEDURE")
    custom_found = False
    for para in proc.paragraphs:
        for stmt in para.statements:
            if isinstance(stmt, CustomStatement):
                custom_found = True
                assert "PARAM1" in stmt.parameters
    
    assert custom_found, "Custom statement not found in parsed AST"
```

## Common Patterns

### Pattern 1: Multi-line Statements

```python
def parse(self, token_stream: ITokenStream) -> ASTNode:
    start_token = token_stream.consume()
    factory = get_factory()
    stmt = factory.create(MultilineStatement, start_token.location)
    
    while not token_stream.is_empty():
        token = token_stream.peek(0)
        
        # Check for explicit terminator
        if self._is_keyword(token, "END-MULTILINE"):
            token_stream.consume()
            break
        
        # Handle continuation lines
        if token.type == TokenType.CONTINUATION:
            token_stream.consume()
            continue
        
        # Check for period (implicit terminator)
        if token.type == TokenType.PERIOD:
            token_stream.consume()
            break
        
        # Collect statement tokens
        stmt.add_token(token)
        token_stream.consume()
    
    return stmt
```

### Pattern 2: Nested Block Statements

```python
def parse(self, token_stream: ITokenStream) -> ASTNode:
    start_token = token_stream.consume()
    factory = get_factory()
    stmt = factory.create(BlockStatement, start_token.location)
    
    # Parse block content
    depth = 1
    while depth > 0 and not token_stream.is_empty():
        token = token_stream.peek(0)
        
        if self._is_keyword(token, "BEGIN-BLOCK"):
            depth += 1
        elif self._is_keyword(token, "END-BLOCK"):
            depth -= 1
            if depth == 0:
                token_stream.consume()
                break
        
        # Parse nested statements
        # (could recursively call parser or handle inline)
        token_stream.consume()
    
    return stmt
```

### Pattern 3: Conditional Syntax

```python
def parse(self, token_stream: ITokenStream) -> ASTNode:
    start_token = token_stream.consume()
    factory = get_factory()
    stmt = factory.create(ConditionalStatement, start_token.location)
    
    # CONDITION clause is required
    if not self._is_keyword(token_stream.peek(0), "WHEN"):
        raise ParseError("Expected WHEN clause")
    
    token_stream.consume()  # WHEN
    
    # Collect condition tokens until THEN
    while not self._is_keyword(token_stream.peek(0), "THEN"):
        stmt.add_condition_token(token_stream.consume())
    
    token_stream.consume()  # THEN
    
    # Collect action tokens until period or END-CONDITIONAL
    while not token_stream.is_empty():
        token = token_stream.peek(0)
        
        if token.type == TokenType.PERIOD:
            token_stream.consume()
            break
        
        if self._is_keyword(token, "END-CONDITIONAL"):
            token_stream.consume()
            break
        
        stmt.add_action_token(token_stream.consume())
    
    return stmt
```

## Debugging Tips

### Enable Detailed Parsing Logs

```python
import logging

logging.basicConfig(level=logging.DEBUG)

# In your parser
logger = logging.getLogger(__name__)

def parse(self, token_stream):
    logger.debug(f"Starting parse, current token: {token_stream.peek(0)}")
    # ... parsing code ...
    logger.debug(f"Parse complete, remaining tokens: {token_stream.is_empty()}")
```

### Validate Parser Integration

```python
from cobolparser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode

parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
result = parser.parse(source_code)

# Check results
print(f"Success: {result.success}")
print(f"Errors: {result.errors}")
print(f"AST: {result.ast}")

# Find your custom statement
proc = result.ast.get_division("PROCEDURE")
for para in proc.paragraphs:
    for stmt in para.statements:
        if isinstance(stmt, CustomStatement):
            print(f"Found custom statement: {stmt.to_dict()}")
```

## Performance Considerations

1. **Keep `matches()` fast** - It's called for every statement
   - Avoid expensive regex or complex logic
   - Use token.type checks first

2. **Minimize token lookahead**
   - Default lookahead is 2 tokens (EXEC SQL, EXEC CICS)
   - More lookahead increases memory usage

3. **Cache token processing**
   ```python
   _KEYWORDS = {"CUSTOM", "BEGIN", "END"}
   
   def _is_keyword(self, token, keyword):
       return (token.type == TokenType.IDENTIFIER and
               token.value and
               token.value.upper() in _KEYWORDS)
   ```

## Version Compatibility

- **Phase 4+**: StatementParserRegistry available
- **Phase 5+**: ASTNodeFactory available (required)
- **Phase 6+**: Performance optimizations may change priorities

## Support and Resources

- [Factory API Documentation](factory-api.md)
- [Parser Architecture Overview](PARSER_INVOCATION_GUIDE.md)
- [IBM Enterprise COBOL Support](ibm-enterprise.md)
- [Statement Parser Examples](../cobolparser/parsers/statements/)
