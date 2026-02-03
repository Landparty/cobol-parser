# Spec: Error Diagnostic Reporting

**Component:** cobolparser/parser.py, all statement parsers  
**Status:** Infrastructure missing - errors not collected/reported  
**Complexity:** Medium

## Problem Statement

Parser encounters errors but doesn't report them to users:
- Missing WHEN in EVALUATE
- Missing END-EVALUATE terminator
- Missing PROGRAM for CALL
- Invalid MOVE structure
- But result.errors remains empty

## Implementation Requirements

1. **Use ParseContext Error Methods**
   - Call context.error(message, location) in parsers
   - ParseContext.error() adds to host (CobolParser) errors

2. **Statement Parser Integration**
   - All statement parsers receive ParseContext
   - Call context.error() for validation failures
   - Don't fail - collect error and continue (COLLECT_ALL mode)

3. **Parser Error Propagation**
   - Parse result includes all collected errors
   - Errors include location (line, column)
   - Errors categorized by severity

4. **Result Error Access**
   - result.errors contains list of ParseError objects
   - Each error has: message, location, statement_type

## Acceptance Criteria
- [ ] test_diagnostic_has_message passes
- [ ] test_missing_program_reports_error passes
- [ ] test_missing_when_reports_error passes
- [ ] All 15 diagnostic tests pass
- [ ] Errors propagate to ParseResult.errors
- [ ] No regression in FAIL_FAST mode

## Files to Modify
- cobolparser/parser.py (error initialization)
- cobolparser/parsers/statements/*.py (error collection)
- cobolparser/core/interfaces.py (ParseContext.error usage)
