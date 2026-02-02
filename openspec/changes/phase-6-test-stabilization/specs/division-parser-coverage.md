# Spec: Division Parser Coverage

## Overview

Division parsers have 70-75% coverage, below 90% target. Comprehensive unit tests for IdentificationDivisionParser, EnvironmentDivisionParser, DataDivisionParser, and ProcedureDivisionParser with edge cases, section handling, and cross-division linking.

## Requirements

### R1: Coverage Target
- Individual division parser coverage: >80% minimum, target 90%
- Division parsers: Identification, Environment, Data, Procedure
- Integration with factory validated

### R2: Division-Specific Test Categories
- **Identification Division:** PROGRAM-ID, AUTHOR, INSTALLATION, metadata extraction
- **Environment Division:** FILE-CONTROL, SELECT, FILE SECTION, environmental configuration
- **Data Division:** Working-storage, sections, record structures, COMP-3, picture clauses, storage calculation
- **Procedure Division:** Section parsing, paragraph organization, statement orchestration

### R3: Test Coverage Per Division
- **Identification:** 8+ tests covering all metadata fields
- **Environment:** 12+ tests covering files, device control, special names
- **Data:** 15+ tests covering hierarchy, clauses, validation, storage
- **Procedure:** 12+ tests covering sections, paragraphs, delegation

### R4: Cross-Division Linking
- Data division to procedure division variable references
- File control definitions to opened/read statements
- Working-storage definitions validated in procedure statements

### R5: Error Recovery
- Division-level error handling without crashes
- Missing sections handled gracefully
- Malformed division headers recover properly

## Acceptance Criteria

- [ ] New unit test files created for all division parsers (4 files)
- [ ] All new tests pass (47+ new tests)
- [ ] Individual division parser coverage: 80%+ minimum
- [ ] Cross-division linking tests pass
- [ ] Error recovery validated
- [ ] No regressions in existing division tests
- [ ] Overall coverage increased

## Deliverables

- `tests/unit/test_identification_division_comprehensive.py` 
- `tests/unit/test_environment_division_comprehensive.py`
- `tests/unit/test_data_division_comprehensive.py`
- `tests/unit/test_procedure_division_comprehensive.py`
- 47+ new unit tests
- Coverage report showing 80%+ for each division parser

## Dependencies

- Phase 6.2: Critical fixes (error recovery integration)
- Phase 5: Division parser architecture
