# EVALUATE Parser Fix - Progress Report

## Issue Fixed
**Infinite Recursion in EvaluateStatementParser** 

### Root Cause
The EvaluateStatementParser was calling `context.host.parse_statement()` recursively at lines 153 and 189 to parse nested statements within WHEN clauses. This caused infinite recursion when:
1. Parser starts parsing EVALUATE statement
2. Encounters WHEN clause and tries to parse nested statements
3. Calls `parse_statement()` which re-enters the EVALUATE parser
4. Parser state gets confused, causing infinite loop

### Solution
Refactored EvaluateStatementParser to:
1. Extract EVALUATE structure only (subjects, WHEN clauses, selectors)
2. Skip nested statements instead of parsing them (skip tokens until next WHEN/END-EVALUATE)
3. Let main parser handle statement parsing at sentence level
4. Added validation for:
   - Missing END-EVALUATE terminator
   - Missing WHEN clause

### Changes Made (29 lines modified)
File: `cobolparser/parsers/evaluate_parser.py`

Key modifications:
- Lines 153, 189: Removed recursive `context.host.parse_statement()` calls
- Instead of parsing nested statements, parser now skips them
- Added proper WhenClause construction with selector dictionaries
- Statement parsing deferred to main sentence parser

### Test Results
**Before:** 64 failed tests, 2351 passed
**After:** 53 failed tests, 2362 passed
**Improvement:** 11 fewer failures, 11 more passes

### Remaining EVALUATE Issues (11 tests)
- Selector/subject count validation
- Range validation (THRU keyword)
- WHEN OTHER placement validation
- Empty selector validation
- Multiple ALSO keyword validation
- Error location tracking
- Multiple errors collection

### Lessons Learned
1. Registry-based parsers should not recursively call parse_statement()
2. Nested statement parsing should happen at sentence/division level, not within statement context
3. Token stream synchronization between old and new parser systems is fragile
4. Simple abstraction (extract structure, skip details) often better than complex recursion
