# Spec: CALL.is_dynamic Attribute

**Component:** cobolparser/models/statements.py, cobolparser/parsers/statements/call_parser.py  
**Status:** Feature missing - attribute not implemented  
**Complexity:** Low

## Problem Statement

CallStatement lacks is_dynamic attribute for tracking whether a CALL uses a dynamic target.

## Dynamic CALL Patterns

```cobol
* Dynamic - target is variable
MOVE "PROG-NAME" TO WS-PROG-NAME.
CALL WS-PROG-NAME.  <- is_dynamic = True

* Static - target is literal
CALL "MY-PROGRAM".  <- is_dynamic = False
```

## Implementation Requirements

1. **Add is_dynamic Attribute**
   - Add to CallStatement.__init__()
   - Default: False (static call)

2. **Detect Dynamic Patterns**
   - Identifier target (not quoted literal) = dynamic
   - Qualified data reference = dynamic
   - Literal string = static

3. **Set During Parsing**
   - CallStatementParser checks target type
   - Call stmt.set_is_dynamic(True/False)

4. **Track in AST**
   - Include in to_dict() output
   - Include in serialization

## Acceptance Criteria
- [ ] CallStatement has is_dynamic attribute
- [ ] Dynamic calls detected correctly (5+ test cases)
- [ ] Static calls marked as non-dynamic
- [ ] test_dynamic_call_is_detected passes
- [ ] test_tracks_initial_value_from_working_storage passes
- [ ] test_tracks_move_statement_values passes
- [ ] All 12 dynamic call contract tests pass

## Files to Modify
- cobolparser/models/statements.py (CallStatement class)
- cobolparser/parsers/statements/call_parser.py (detection logic)
