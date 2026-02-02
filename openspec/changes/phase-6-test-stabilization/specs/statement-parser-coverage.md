# Spec: Statement Parser Coverage

## Overview

Statement parsers (display, move, if, perform, etc.) have 40-70% coverage, below 90% target. Comprehensive unit tests for each statement parser module with edge cases, error handling, and factory integration.

## Requirements

### R1: Coverage Target
- Individual statement parser coverage: >80% minimum, target 90%
- Statement parsers affected: DisplayStatementParser, MoveStatementParser, IfStatementParser, PerformStatementParser, EvaluateStatementParser, CallStatementParser, and all others
- Integration with AST factory validated

### R2: Test Categories Per Parser
- **Happy path:** Standard statement parsing with common variants
- **Edge cases:** Empty, minimal, maximal, boundary conditions
- **Error handling:** Malformed constructs, missing required clauses
- **Factory integration:** AST node creation, validation, hierarchy
- **Metadata tracking:** Location information, source tracking

### R3: Parser-Specific Coverage
- DisplayStatementParser: DISPLAY targets, expressions, line breaks
- MoveStatementParser: MOVE simple/complex, multiple targets, COMP-3
- IfStatementParser: IF conditions, nested IF, ELSE/END-IF
- PerformStatementParser: PERFORM variants, UNTIL, VARYING
- EvaluateStatementParser: WHEN clauses, ALSO, ANY, TRUE/FALSE
- CallStatementParser: CALL targets, parameters, return-value
- All arithmetic parsers: ADD, SUBTRACT, MULTIPLY, DIVIDE

### R4: Test Organization
- `tests/unit/test_display_parser_comprehensive.py` for DisplayStatementParser
- `tests/unit/test_move_parser_comprehensive.py` for MoveStatementParser
- Similar for all remaining statement parsers
- Organized by parser class

### R5: Test Infrastructure
- Use existing test fixtures and sample COBOL
- Factory mocking where needed
- Assertion helpers for AST node validation

## Acceptance Criteria

- [ ] New unit test files created for all statement parsers (12+ files)
- [ ] All new tests pass (450+ new tests)
- [ ] Individual parser coverage: 80%+ minimum
- [ ] Factory integration validated in each parser
- [ ] No regressions in existing statement tests
- [ ] Overall coverage increased by 10-15%

## Deliverables

- `tests/unit/test_*_parser_comprehensive.py` files (12+ new files)
- 450+ new unit tests
- Coverage report showing 80%+ for each parser

## Dependencies

- Phase 6.2: Critical fixes (error recovery, fixed-format, lexer, EVALUATE)
- Phase 5: Factory architecture and node definitions
