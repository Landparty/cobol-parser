# Spec: Lexer Continuation Improvement

## Overview

Multi-line statements in COBOL use continuation indicators (hyphen in column 7 of free-format, or continuation marker in fixed-format). Proper handling requires maintaining string literal state across line boundaries, especially for doubled-quote escape sequences.

## Requirements

### R1: Continuation Line Handling
- Recognize continuation indicators (hyphen, or - in column 7)
- Logically join continued lines into single token
- Preserve line/column information for error reporting

### R2: String Literal Across Lines
- Multi-line strings continue across continuation lines
- Doubled-quote escape sequence (`''`) = literal quote
- Escape sequences must be preserved across continuation

### R3: State Management
- Lexer maintains state during continuation:
  - Are we inside a string literal?
  - What quote character started the string? (single or double)
  - Continuation count for error reporting

### R4: COBOL Convention
- COBOL uses doubled quotes for escaping: `'It''s a test'` = "It's a test"
- Doubled quotes must escape correctly across line boundaries
- Both `'` and `"` treated as quote delimiters (dialect-dependent)

### R5: Backward Compatibility
- Existing single-line string handling unchanged
- Continuation handling in existing code not modified
- Works with all COBOL dialects (IBM, ANSI, GnuCOBOL)

## Acceptance Criteria

- [ ] `test_doubled_quote_across_continuation` passes
- [ ] String literals spanning multiple lines parsed correctly
- [ ] Doubled-quote escapes preserved across continuation
- [ ] Line/column information accurate in error messages
- [ ] Existing tests still pass (no regressions)
- [ ] Performance not degraded

## Related Components

- `cobolparser/lexer.py` - Tokenization and string handling
- Token stream (position tracking)
- Error reporting (line/column accuracy)

## Test Coverage

- Multi-line string literals with continuation
- Doubled-quote escaping across lines
- Mixed continuation types (free-format, fixed-format)

## Dependencies

- Phase 6.1: Root cause analysis (diagnoses string/continuation issue)
- Lexer state machine (existing infrastructure)
