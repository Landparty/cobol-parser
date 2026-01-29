# Quick Reference - Exception Handler Fix

## What Was Fixed?

COBOL CALL statements with both ON EXCEPTION and NOT ON EXCEPTION were merging both paths into a single list. Now they're properly separated.

## Key Changes

### 1. CallStatement Model
**File**: `cobolparser/models/statements.py`

```python
# NEW FIELD ADDED:
self.not_on_exception: Optional[List['CobolStatement']] = None
```

### 2. Parser Logic
**File**: `cobolparser/parser.py`, Method: `_parse_call_exception_handlers()`

**Before**: `continue` after finding NOT ON EXCEPTION (BUG)  
**After**: Dedicated NOT ON EXCEPTION parsing block (FIXED)

### 3. AST Traversal
**File**: `cobolparser/models/program.py`, Method: `get_all_statements()`

**Added**: Traversal of `not_on_exception` field to include success path statements

## Usage

### Accessing Exception Handlers

```python
from cobolparser import CobolParser
from cobolparser.models.statements import CallStatement

parser = CobolParser()
result = parser.parse(cobol_code)

# Get all statements
all_stmts = result.ast.get_all_statements()

# Find CALL statements with handlers
for stmt in all_stmts:
    if isinstance(stmt, CallStatement):
        if stmt.on_exception:
            print("Exception handler statements:")
            for ex_stmt in stmt.on_exception:
                print(f"  - {type(ex_stmt).__name__}")
        
        if stmt.not_on_exception:
            print("Success handler statements:")
            for nox_stmt in stmt.not_on_exception:
                print(f"  - {type(nox_stmt).__name__}")
```

## Test Files

Run these to verify the fix:

```bash
# Comprehensive exception handler tests
python test_exception_handlers.py

# Validate real-world COBOL files
python validate_call_parsing.py

# Check exception handler structure
python check_exception_structure.py

# Full test suite
python -m pytest tests/ -q
```

## Backward Compatibility

✅ 100% backward compatible
- Existing `on_exception` field works as before
- New `not_on_exception` field is optional
- No breaking changes to public APIs

## Example

**COBOL Code**:
```cobol
CALL WS-PROG USING WS-VAR
    ON EXCEPTION
        DISPLAY 'Error occurred'
    NOT ON EXCEPTION
        DISPLAY 'Success'
END-CALL.
```

**AST After Fix**:
```python
CallStatement {
    called_program: "WS-PROG",
    using_parameters: [...],
    on_exception: [DisplayStatement('Error occurred')],     # ✅ Only error path
    not_on_exception: [DisplayStatement('Success')]         # ✅ Only success path
}
```

## Questions?

See detailed documentation:
- `EXCEPTION_HANDLER_FIX_REPORT.md` - Technical details
- `SESSION_SUMMARY.md` - Complete overview
- `test_exception_handlers.py` - Test examples
