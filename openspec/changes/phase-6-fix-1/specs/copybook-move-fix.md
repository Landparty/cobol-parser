# Spec: Copybook MOVE Statement Expansion

**Component:** cobolparser/preprocess/copybook_expander.py  
**Status:** Feature broken - MOVE statements lost during expansion  
**Complexity:** Medium

## Problem Statement

When MOVE statements appear in copybooks and are expanded, they disappear from the final AST:

```cobol
COPY MY-COPYBOOK.

* Copybook contains:
*     01 WS-ITEM PIC 9.
*     PROCEDURE DIVISION.
*         MOVE 1 TO WS-ITEM.

* Expected: MOVE statement in AST
* Actual: MOVE missing from AST
```

## Root Cause

Copybook expansion pipeline breaks MOVE statements during expansion/reconstruction.

## Implementation Requirements

1. **Trace Expansion Pipeline**
   - Lexer processes copybook source
   - Tokens expanded to main stream
   - Tokens reconstructed to source
   - MOVE tokens may be lost

2. **Verify MOVE Token Handling**
   - Check token types during expansion
   - Ensure MOVE keyword preserved
   - Verify target/source preserved

3. **Test Single MOVE**
   - Copybook with one MOVE statement
   - Verify MOVE in expanded source
   - Verify MOVE in parsed AST

4. **Test Multiple MOVE**
   - Copybook with multiple statements
   - Verify all statements in AST
   - Verify order preserved

## Acceptance Criteria
- [ ] test_procedure_copybook_statements_in_ast passes
- [ ] test_procedure_copybook_preserves_order passes
- [ ] MOVE statements in copybooks appear in AST
- [ ] All 10 copybook expansion contract tests pass
- [ ] No regression in copybook non-MOVE tests

## Files to Modify
- cobolparser/preprocess/copybook_expander.py (primary investigation)
- cobolparser/preprocess/copy_statement_parser.py (if parsing issue)
- cobolparser/preprocess/path_resolver.py (if resolution issue)
