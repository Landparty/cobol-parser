# Spec: Fixed-Format Auto-Detection

**Component:** cobolparser/lexer.py  
**Status:** Feature broken - sequence number detection not working  
**Complexity:** Low

## Problem Statement

Fixed-format COBOL programs should auto-detect based on sequence numbers in columns 1-6, but detection is broken:

```cobol
000100  IDENTIFICATION DIVISION.
000200  PROGRAM-ID. TEST.
000300  PROCEDURE DIVISION.
```

Lexer should recognize columns 1-6 as sequence numbers and adjust parsing accordingly.

## Implementation Requirements

1. **Verify Auto-Detection Logic**
   - Check if lexer detects numeric columns 1-6
   - Check if auto_detect_format flag works
   - Test with/without sequence numbers

2. **Check preprocess_fixed Parameter**
   - Parser accepts preprocess_fixed=True
   - Must propagate to lexer
   - Lexer must respect this flag

3. **Test Sequence Number Strip**
   - Read columns 1-6 as sequence
   - Skip these columns in content
   - Preserve columns 7+

4. **Test Format Switching**
   - Program without seq numbers = free-format
   - Program with seq numbers = fixed-format
   - Auto-detection should choose correctly

## Acceptance Criteria
- [ ] test_fixed_format_auto_detection passes
- [ ] Fixed-format files parsed correctly
- [ ] Sequence numbers stripped from content
- [ ] Column 7 continuation indicator respected
- [ ] All 12 fixed-format tests pass
- [ ] No regression in free-format parsing

## Files to Modify
- cobolparser/lexer.py (auto-detection logic)
- cobolparser/parser.py (parameter propagation)
