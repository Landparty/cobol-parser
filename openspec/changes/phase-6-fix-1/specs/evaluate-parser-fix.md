# Spec: EVALUATE Parser Population

**Component:** cobolparser/parsers/statements/evaluate_parser.py  
**Status:** Implementation blocked - parser not populating AST  
**Complexity:** Medium

## Problem Statement

EvaluateStatement objects are created but remain empty:
- subjects: [] (should contain EVALUATE expression)
- when_clauses: [] (should contain WHEN branches)
- default_when: None (should contain WHEN OTHER)

This breaks all EVALUATE variant tests.

## Root Cause

EvaluateStatementParser.parse() is either:
1. Not registered in StatementParserRegistry
2. Not being invoked by statement dispatcher
3. Returning before populating the statement

## Implementation Requirements

1. **Verify Parser Registration**
   - Check StatementParserRegistry contains 'EVALUATE' entry
   - Add debug logging to confirm dispatcher calls parser

2. **Verify Method Signature**
   - EvaluateStatementParser.parse(stream, context) must match StatementParser interface
   - Must have @compatible decorator or direct registry entry

3. **Implement Subject Population**
   - Call stmt.add_subject() for each EVALUATE expression
   - Handle single and multiple subjects (ALSO keyword)

4. **Implement WHEN Clause Population**
   - Call stmt.add_when_clause() for each WHEN
   - Parse selectors (literals, ranges, ANY, conditions)
   - Handle WHEN OTHER as default

5. **Test Verification**
   - EVALUATE creates non-empty EvaluateStatement
   - subjects list populated correctly
   - when_clauses list populated correctly
   - default_when set for WHEN OTHER

## Acceptance Criteria
- [ ] test_single_subject_literals_and_ranges passes
- [ ] test_multiple_subjects_any_and_also passes
- [ ] test_evaluate_true_with_conditions_and_or passes
- [ ] All EVALUATE variant tests pass (18+ tests)
- [ ] No regression in other statement parsers

## Files to Modify
- cobolparser/parsers/statements/evaluate_parser.py (primary)
- cobolparser/core/registry.py (if registration missing)
- cobolparser/parser.py (if dispatcher needs fix)
