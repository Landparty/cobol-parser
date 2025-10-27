# Tasks: Nested Copybook Expansion

**Input**: Design documents from `/specs/002-copybook-expansion/`  
**Prerequisites**: plan.md (✅ complete), spec.md (✅ complete with 4 prioritized user stories)

**TDD Approach**: All tests written FIRST, ensure they FAIL before implementation (per project constitution)

**Organization**: Tasks are grouped by user story (P1 → P4) to enable independent implementation and testing

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization, base classes, and error handling infrastructure

- [X] T001 Create cobolparser/preprocess/ directory for copybook expansion module
- [X] T002 Create base exception types in cobolparser/preprocess/__init__.py (CircularReferenceError, CopybookNotFoundError, PathTraversalError, EncodingError, NestingDepthError)
- [X] T003 [P] Create cobolparser/preprocess/models.py with dataclasses: CopybookExpansion, CopyStatement, CopybookSearchPath, ExpansionContext, ExpansionStatistics
- [X] T004 [P] Create cobolparser/preprocess/copy_statement_parser.py module skeleton
- [X] T005 [P] Create cobolparser/preprocess/path_resolver.py module skeleton
- [X] T006 [P] Create cobolparser/preprocess/copybook_expander.py module skeleton
- [X] T007 Create tests/samples/copybook_programs/ directory for test COBOL programs
- [X] T008 Create tests/samples/copybooks/ directory for test copybook files
- [X] T009 Create tests/samples/mixed_encodings/ directory for encoding test cases
- [X] T010 [P] Create tests/unit/test_copybook_expansion.py test file skeleton
- [X] T011 [P] Create tests/integration/test_copybook_expansion_integration.py test file skeleton
- [X] T012 [P] Create tests/contracts/test_copybook_expansion_contracts.py test file skeleton
- [X] T013 Update cobolparser/__init__.py to export expand_copybooks() and parse_cobol_with_expansion()

**Checkpoint**: Project structure complete - Foundational tasks can begin

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST complete before any user story implementation

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Path Resolution & Validation Infrastructure

- [X] T014 [P] Implement path normalization (OS-native separators) in cobolparser/preprocess/path_resolver.py - normalize_path() function supporting Windows backslash and Unix forward slash
- [X] T015 [P] Implement path validation to prevent traversal attacks in cobolparser/preprocess/path_resolver.py - validate_path_within_directory() function that rejects ".." sequences
- [X] T016 [P] Implement copybook file search logic in cobolparser/preprocess/path_resolver.py - find_copybook_file() function supporting (.cpy, .CPY, .cbl, .CBL, .cob, .COB) extensions
- [X] T017 Implement path resolver integration in cobolparser/preprocess/path_resolver.py - PathResolver class wrapping above functions with CopybookSearchPath configuration

### Encoding Detection & Conversion

- [X] T018 [P] Implement pure-Python character encoding detection in cobolparser/preprocess/copybook_expander.py - detect_encoding() function using heuristic-based approach: check UTF-8 BOM (\\xef\\xbb\\xbf), test UTF-8 validity with encode/decode, detect EBCDIC indicators (0x40 for space), fallback to ASCII with errors='replace' (NO external dependencies per constitution)
- [X] T019 [P] Implement encoding conversion to UTF-8 in cobolparser/preprocess/copybook_expander.py - convert_to_utf8() function with fallback handling
- [X] T020 Implement file reading with automatic encoding detection in cobolparser/preprocess/copybook_expander.py - read_file_with_encoding() function

### COPY Statement Parsing

- [X] T021 Implement COPY statement regex patterns in cobolparser/preprocess/copy_statement_parser.py supporting: `COPY member`, `COPY "member"`, `COPY member IN library`, `COPY member OF library`
- [X] T022 Implement COPY statement extraction in cobolparser/preprocess/copy_statement_parser.py - extract_copy_statements() function returning list of CopyStatement objects
- [X] T023 Implement COPY statement parsing for REPLACING clause in cobolparser/preprocess/copy_statement_parser.py - parse_replacing_clause() function for text substitution pairs
- [X] T024 Implement line-by-line source location tracking in cobolparser/preprocess/copy_statement_parser.py - track_source_location() for mapping expanded lines to original files

### Error Handling & Validation

- [X] T025 Implement comprehensive error messages for all exception types in cobolparser/preprocess/__init__.py - include copybook names, search paths, and dependency chains where applicable
- [X] T026 [P] Implement nesting depth tracking in cobolparser/preprocess/copybook_expander.py - NestingDepthError raised when exceeding max_nesting_depth parameter
- [X] T027 [P] Implement circular reference detection in cobolparser/preprocess/copybook_expander.py - ExpansionContext.expansion_stack tracking to detect cycles

**Checkpoint**: Foundation ready - User story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Basic Copybook Expansion (Priority: P1) 🎯 MVP

**Goal**: Implement basic expansion of COPY statements by inlining copybook content from files

**Independent Test**: Can be fully tested by providing a COBOL program with simple COPY statements and verifying expanded source contains copybook content inlined at each COPY location

### Contract Tests for User Story 1 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [X] T028 [P] [US1] Contract test expand_copybooks() basic signature in tests/contracts/test_copybook_expansion_contracts.py - verify function accepts source_code, copybook_paths, max_nesting_depth, preserve_source_locations parameters
- [X] T029 [P] [US1] Contract test expand_copybooks() return type in tests/contracts/test_copybook_expansion_contracts.py - verify function returns CopybookExpansion object with expanded_source, included_copybooks attributes
- [X] T030 [P] [US1] Contract test single COPY statement expansion in tests/contracts/test_copybook_expansion_contracts.py - COPY MEMBER1. replaced with MEMBER1.cpy content
- [X] T031 [P] [US1] Contract test multiple COPY statements in tests/contracts/test_copybook_expansion_contracts.py - multiple statements in different divisions all expanded
- [X] T032 [P] [US1] Contract test COPY syntax variants in tests/contracts/test_copybook_expansion_contracts.py - COPY "MEMBER", COPY MEMBER, COPY MEMBER IN LIBRARY all recognized and expanded
- [X] T033 [P] [US1] Contract test no-COPY passthrough in tests/contracts/test_copybook_expansion_contracts.py - program without COPY statements returns original source unchanged

### Unit Tests for User Story 1 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [X] T034 [P] [US1] Unit test path normalization for COPY member names in tests/unit/test_copybook_expansion.py - forward slash and backslash both handled
- [X] T035 [P] [US1] Unit test copybook file not found error in tests/unit/test_copybook_expansion.py - CopybookNotFoundError raised with member name and search paths
- [X] T036 [P] [US1] Unit test empty copybook handling in tests/unit/test_copybook_expansion.py - empty/whitespace files expand to empty content
- [X] T037 [P] [US1] Unit test COPY statement extraction in tests/unit/test_copybook_expansion.py - regex correctly identifies all COPY variants
- [X] T038 [P] [US1] Unit test path traversal rejection in tests/unit/test_copybook_expansion.py - "../" in member name raises PathTraversalError
- [X] T039 [P] [US1] Unit test encoding detection in tests/unit/test_copybook_expansion.py - ASCII, EBCDIC, UTF-8 files all detected correctly

### Integration Tests for User Story 1 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [X] T040 [P] [US1] Integration test basic expansion with real COBOL in tests/integration/test_copybook_expansion_integration.py - create test_programs/basic_copy.cbl with COPY statement, verify expansion
- [X] T041 [P] [US1] Integration test expansion preserves COBOL structure in tests/integration/test_copybook_expansion_integration.py - divisions, sections, paragraphs remain intact
- [X] T042 [P] [US1] Integration test expanded program parses with existing parser in tests/integration/test_copybook_expansion_integration.py - parse_cobol_with_expansion() end-to-end test

### Implementation for User Story 1

- [X] T043 [US1] Implement expand_copybooks() core function in cobolparser/preprocess/copybook_expander.py - accept source_code, copybook_paths, max_nesting_depth=100, preserve_source_locations=False parameters
- [X] T044 [US1] Implement COPY statement identification and replacement in cobolparser/preprocess/copybook_expander.py - extract COPY statements and replace with copybook content
- [X] T045 [US1] Implement copybook file resolution in cobolparser/preprocess/copybook_expander.py - use PathResolver to locate copybook files with extension searching
- [X] T046 [US1] Implement inline replacement logic in cobolparser/preprocess/copybook_expander.py - insert copybook content at exact COPY statement location
- [X] T047 [US1] Implement CopybookExpansion result object creation in cobolparser/preprocess/copybook_expander.py - populate expanded_source, included_copybooks, max_depth_reached
- [X] T048 [US1] Implement CopybookExpansion.to_dict() JSON serialization in cobolparser/preprocess/models.py - enable JSON export per constitution requirement
- [X] T049 [US1] Implement error handling for basic expansion in cobolparser/preprocess/copybook_expander.py - catch file I/O errors and convert to CopybookNotFoundError
- [X] T050 [US1] Add docstrings and type hints to expand_copybooks() in cobolparser/preprocess/copybook_expander.py - full compliance with Python 3.13+ standards

**Test Validation**: Run tests/contracts/test_copybook_expansion_contracts.py, tests/unit/test_copybook_expansion.py (US1 only), tests/integration/test_copybook_expansion_integration.py (US1 only) - all should pass

**Checkpoint**: User Story 1 should be fully functional - MVP complete. Can deploy basic copybook expansion here.

---

## Phase 4: User Story 2 - Nested Copybook Resolution (Priority: P2)

**Goal**: Implement recursive resolution of nested COPY statements where copybooks reference other copybooks

**Independent Test**: Can be tested independently by providing a main program that copies copybook1, which copies copybook2, and verifying complete recursive expansion

### Contract Tests for User Story 2 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [ ] T051 [P] [US2] Contract test nested COPY expansion in tests/contracts/test_copybook_expansion_contracts.py - LEVEL1.cpy contains COPY LEVEL2., both are expanded
- [ ] T052 [P] [US2] Contract test 3-level nesting in tests/contracts/test_copybook_expansion_contracts.py - program → copybook1 → copybook2 → copybook3 all expanded
- [ ] T053 [P] [US2] Contract test multiple nested references in tests/contracts/test_copybook_expansion_contracts.py - single copybook references multiple others, all expanded

### Unit Tests for User Story 2 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [X] T054 [P] [US2] Unit test recursion base case in tests/unit/test_copybook_expansion.py - copybook with no COPY statements stops recursion
- [X] T055 [P] [US2] Unit test maximum nesting depth in tests/unit/test_copybook_expansion.py - NestingDepthError raised when exceeding max_nesting_depth parameter

### Integration Tests for User Story 2 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [X] T056 [P] [US2] Integration test real nested structure in tests/integration/test_copybook_expansion_integration.py - create nested copybook hierarchy, verify complete expansion
- [X] T057 [P] [US2] Integration test nested programs parse correctly in tests/integration/test_copybook_expansion_integration.py - expanded nested program passes existing parser validation

### Implementation for User Story 2

- [ ] T058 [US2] Implement recursive copybook processing in cobolparser/preprocess/copybook_expander.py - extract_and_expand_copybooks() recursive function
- [ ] T059 [US2] Implement ExpansionContext state tracking in cobolparser/preprocess/copybook_expander.py - maintain expansion_stack for each recursion level
- [ ] T060 [US2] Implement nesting depth limit enforcement in cobolparser/preprocess/copybook_expander.py - track current depth and raise NestingDepthError at limit
- [ ] T061 [US2] Implement recursive expansion integration into expand_copybooks() in cobolparser/preprocess/copybook_expander.py - call recursive function instead of simple replacement
- [ ] T062 [US2] Update CopybookExpansion.max_depth_reached in cobolparser/preprocess/copybook_expander.py - track maximum nesting depth encountered during expansion

**Test Validation**: Run tests/contracts/test_copybook_expansion_contracts.py (US2 tests), tests/unit/test_copybook_expansion.py (US2 tests), tests/integration/test_copybook_expansion_integration.py (US2 tests) - all should pass

**Checkpoint**: User Stories 1 AND 2 should work independently. Nested expansion now functional.

---

## Phase 5: User Story 3 - Circular Reference Detection (Priority: P3)

**Goal**: Detect and report circular reference cycles in copybook dependencies with clear error messages

**Independent Test**: Can be tested independently by creating copybooks with circular references (A → B → A) and verifying CircularReferenceError with dependency chain

### Contract Tests for User Story 3 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [ ] T063 [P] [US3] Contract test direct circular reference in tests/contracts/test_copybook_expansion_contracts.py - A copies B, B copies A → CircularReferenceError with chain (A → B → A)
- [ ] T064 [P] [US3] Contract test indirect circular reference in tests/contracts/test_copybook_expansion_contracts.py - A → B → C → A detected and reported with complete chain
- [ ] T065 [P] [US3] Contract test multiple independent copies with one circular in tests/contracts/test_copybook_expansion_contracts.py - error identifies specific COPY causing cycle

### Unit Tests for User Story 3 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [X] T066 [P] [US3] Unit test circular detection in expansion_stack in tests/unit/test_copybook_expansion.py - stack tracking identifies duplicate entries
- [X] T067 [P] [US3] Unit test error message includes dependency chain in tests/unit/test_copybook_expansion.py - CircularReferenceError message shows "A → B → C → A" format

### Integration Tests for User Story 3 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [X] T068 [P] [US3] Integration test real circular copybook structure in tests/integration/test_copybook_expansion_integration.py - create circular dependency, verify error detection and reporting

### Implementation for User Story 3

- [ ] T069 [US3] Implement expansion_stack checking in cobolparser/preprocess/copybook_expander.py - before processing copybook, check if already in current stack
- [ ] T070 [US3] Implement circular reference detection logic in cobolparser/preprocess/copybook_expander.py - raise CircularReferenceError when duplicate found in stack
- [ ] T071 [US3] Implement dependency chain formatting in cobolparser/preprocess/copybook_expander.py - create human-readable error message showing "file1 → file2 → file3 → file1"
- [ ] T072 [US3] Implement error context preservation in cobolparser/preprocess/copybook_expander.py - include all context info (files, line numbers, search paths) in CircularReferenceError
- [ ] T073 [US3] Update ExpansionContext to preserve chain for error reporting in cobolparser/preprocess/copybook_expander.py - track full stack for display in error message

**Test Validation**: Run tests/contracts/test_copybook_expansion_contracts.py (US3 tests), tests/unit/test_copybook_expansion.py (US3 tests), tests/integration/test_copybook_expansion_integration.py (US3 tests) - all should pass

**Checkpoint**: User Stories 1, 2, AND 3 should work independently. Circular reference protection now in place.

---

## Phase 6: User Story 4 - Source Location Preservation (Priority: P4)

**Goal**: Preserve metadata mapping each line in expanded output back to original source file and line number

**Independent Test**: Can be tested independently by expanding a program with copybooks, verifying source location map contains correct file/line pairs

### Contract Tests for User Story 4 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [ ] T074 [P] [US4] Contract test source_location_map enabled in tests/contracts/test_copybook_expansion_contracts.py - expand with preserve_source_locations=True returns CopybookExpansion with populated source_location_map
- [ ] T075 [P] [US4] Contract test source location accuracy in tests/contracts/test_copybook_expansion_contracts.py - each expanded line maps to original file and line number
- [ ] T076 [P] [US4] Contract test nested source locations in tests/contracts/test_copybook_expansion_contracts.py - deeply nested copybook content traces back to original copybook file

### Unit Tests for User Story 4 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [ ] T077 [P] [US4] Unit test source location tracking during parsing in tests/unit/test_copybook_expansion.py - line numbers incremented correctly as content appended
- [ ] T078 [P] [US4] Unit test nested file references in tests/unit/test_copybook_expansion.py - nested content attributes to deepest source file

### Integration Tests for User Story 4 ⚠️

> **WRITE THESE TESTS FIRST - Ensure they FAIL before implementation**

- [ ] T079 [P] [US4] Integration test error tracing with source locations in tests/integration/test_copybook_expansion_integration.py - introduce syntax error in nested copybook, verify parser error message references original copybook
- [ ] T080 [P] [US4] Integration test source location map to_dict() serialization in tests/integration/test_copybook_expansion_integration.py - verify JSON export includes source location information

### Implementation for User Story 4

- [ ] T081 [US4] Implement SourceLocationMap data structure in cobolparser/preprocess/models.py - Dict[int, Tuple[str, int]] mapping line_number → (source_file, original_line_number)
- [ ] T082 [US4] Implement source location tracking in copy statement parser in cobolparser/preprocess/copy_statement_parser.py - track line numbers during COPY statement extraction
- [ ] T083 [US4] Implement source map accumulation during expansion in cobolparser/preprocess/copybook_expander.py - build source_location_map during recursive expansion
- [ ] T084 [US4] Update expand_copybooks() to return source_location_map in cobolparser/preprocess/copybook_expander.py - populate optional source_location_map in CopybookExpansion when preserve_source_locations=True
- [ ] T085 [US4] Implement SourceLocationMap.to_dict() JSON serialization in cobolparser/preprocess/models.py - enable JSON export of source location data
- [ ] T086 [US4] Integrate source locations with existing parser error messages in cobolparser/preprocess/copybook_expander.py - enable parse_cobol_with_expansion() to return errors with original source file references

**Test Validation**: Run tests/contracts/test_copybook_expansion_contracts.py (US4 tests), tests/unit/test_copybook_expansion.py (US4 tests), tests/integration/test_copybook_expansion_integration.py (US4 tests) - all should pass

**Checkpoint**: All user stories 1-4 should work independently. Source location tracking fully functional.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Advanced features, integration, and quality improvements affecting multiple user stories

### COPY REPLACING Clause Support

- [ ] T087 [P] Unit test COPY REPLACING parsing in tests/unit/test_copybook_expansion.py - parse `COPY member REPLACING == text1 == BY == text2 ==` syntax
- [ ] T088 [P] Integration test REPLACING text substitution in tests/integration/test_copybook_expansion_integration.py - text replacement occurs after copybook insertion
- [ ] T089 Implement COPY REPLACING text substitution in cobolparser/preprocess/copybook_expander.py - parse_replacing_clause() identifies substitution pairs and apply after expansion
- [ ] T090 Add REPLACING support to expand_copybooks() result in cobolparser/preprocess/copybook_expander.py - ensure CopybookExpansion reflects final text after replacements

### Parser Integration

- [ ] T091 [P] Unit test parse_cobol_with_expansion() function signature in tests/unit/test_copybook_expansion.py - verify accepts source_code, filename, copybook_paths
- [ ] T092 [P] Unit test parse_cobol_with_expansion() returns ParseResult in tests/unit/test_copybook_expansion.py - verify return type compatibility with existing parser
- [ ] T093 Integration test parse_cobol_with_expansion() end-to-end in tests/integration/test_copybook_expansion_integration.py - real COBOL with copybooks expands and parses successfully
- [ ] T094 Implement parse_cobol_with_expansion() convenience function in cobolparser/preprocess/copybook_expander.py - wrap expand_copybooks() + existing parse_cobol()
- [ ] T095 Export parse_cobol_with_expansion() in cobolparser/__init__.py - make function available as part of public API

### Documentation & Examples

- [ ] T096 Create quickstart examples in specs/002-copybook-expansion/quickstart.md - code examples for basic and advanced usage
- [ ] T097 [P] Add docstring examples to expand_copybooks() in cobolparser/preprocess/copybook_expander.py - demonstrate usage patterns
- [ ] T098 [P] Add docstring examples to parse_cobol_with_expansion() in cobolparser/preprocess/copybook_expander.py - demonstrate integration with parser
- [ ] T099 Create API documentation in specs/002-copybook-expansion/contracts/ - OpenAPI/Markdown documenting expand_copybooks and parse_cobol_with_expansion

### Code Quality & Hardening

- [ ] T100 [P] Add comprehensive docstrings to all functions in cobolparser/preprocess/ - module, function, parameter, and return documentation
- [ ] T101 [P] Verify type hints on all public APIs in cobolparser/preprocess/ - mandatory per Python 3.13+ standard
- [ ] T102 [P] Run mypy type checking in cobolparser/preprocess/ - zero type errors required
- [ ] T103 [P] Run ruff linting in cobolparser/preprocess/ - fix all style violations
- [ ] T104 [P] Run black formatting in cobolparser/preprocess/ - enforce consistent style
- [ ] T105 [P] Remove unused imports in cobolparser/preprocess/ - ruff-flagged cleanup
- [ ] T106 Add error message localization support in cobolparser/preprocess/__init__.py - prepare for multi-language error messages (stub for future)

### Performance Optimization

- [ ] T107 [P] Profile copybook expansion with large programs in tests/ - benchmark with 50+ copybooks, 10+ nesting levels
- [ ] T108 Optimize file I/O in cobolparser/preprocess/copybook_expander.py - cache open file operations where possible
- [ ] T109 Optimize regex patterns in cobolparser/preprocess/copy_statement_parser.py - verify performance on large programs (goal: <100ms for 5-15 copybooks)
- [ ] T110 Add memory usage monitoring in cobolparser/preprocess/copybook_expander.py - track peak memory during expansion

### Final Testing & Validation

- [ ] T111 [P] Run all unit tests for coverage analysis in tests/unit/ - verify 81%+ coverage of preprocess module
- [ ] T112 [P] Run all integration tests in tests/integration/ - validate end-to-end workflows
- [ ] T113 [P] Run all contract tests in tests/contracts/ - verify API stability
- [ ] T114 Run full test suite with pytest --cov in tests/ - ensure overall project coverage maintained
- [ ] T115 Validate existing parser tests still pass in tests/ - ensure no regressions to existing functionality
- [ ] T116 Create summary report in specs/002-copybook-expansion/IMPLEMENTATION_REPORT.md - document completed features, test results, known issues

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies - can start immediately ✅
- **Phase 2 (Foundational)**: Depends on Phase 1 completion - BLOCKS all user stories ⚠️ CRITICAL
- **Phase 3 (US1)**: Can start after Phase 2 - MVP enabled
- **Phase 4 (US2)**: Can start after Phase 2 - independent of US1
- **Phase 5 (US3)**: Can start after Phase 2 - independent of US1/US2
- **Phase 6 (US4)**: Can start after Phase 2 - independent of US1/US2/US3
- **Phase 7 (Polish)**: Can start after Phase 6 - depends on all user stories complete for integration

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Phase 2 - No dependencies on other stories - **MVP**
- **User Story 2 (P2)**: Can start after Phase 2 - Independent of US1, builds on Phase 2 foundation
- **User Story 3 (P3)**: Can start after Phase 2 - Independent of US1/US2, builds on Phase 2 foundation
- **User Story 4 (P4)**: Can start after Phase 2 - Independent of US1/US2/US3, builds on Phase 2 foundation

### Critical Path Analysis

1. **Phase 1** (Setup): Sequential, ~2 hours → completes project structure
2. **Phase 2** (Foundation): Can parallelize path/encoding/parsing components → ~4 hours, critical blocking phase
3. **Phase 3+** (Stories): All 4 user stories can proceed in parallel after Phase 2 → ~3 hours each in parallel
4. **Phase 7** (Polish): Sequential, depends on all stories → ~2 hours

**Minimum Sequential Time**: Phase 1 (2h) + Phase 2 (4h) + US1 (3h) = 9 hours  
**With Parallel Team**: Phase 1 (2h) + Phase 2 (4h) + max(US1, US2, US3, US4) parallel (3h) + Phase 7 (2h) = 11 hours with 4 developers

### Parallel Opportunities

#### Within Phase 1
```
T003, T004, T005, T006 can run in parallel (different modules)
T010, T011, T012 can run in parallel (different test files)
```

#### Within Phase 2
```
T014, T015, T016, T017 path work in sequence (each builds on previous)
T018, T019, T020 encoding work in sequence (interdependent)
T021, T022, T023, T024 COPY parsing in sequence (interdependent)
T025, T026, T027 error handling can run in parallel
```

#### Within Phase 3 (User Story 1)
```
Contract tests (T028-T033) can run in parallel
Unit tests (T034-T039) can run in parallel
Then implementation (T043-T050) in sequence (T043 is base for T044+)
```

#### Between Phase 3-6
```
Once Phase 2 complete:
  - Developer A: Complete US1 (Phase 3) → 3 hours
  - Developer B: Complete US2 (Phase 4) → 3 hours
  - Developer C: Complete US3 (Phase 5) → 2 hours
  - Developer D: Complete US4 (Phase 6) → 3 hours
All in parallel (different modules, no conflicts)
```

#### Within Phase 7
```
T087-T092 can run in parallel (REPLACING implementation, parser integration prep)
T096-T099 documentation can run in parallel (different files)
T100-T106 code quality can run in parallel (different analysis tools)
T107-T110 performance work in sequence (profiles, then optimizes)
T111-T116 final validation in sequence (coverage → summary)
```

---

## Implementation Strategy

### MVP First (User Story 1 Only) ⭐ RECOMMENDED START

**Timeline**: ~6-8 hours  
**Deliverable**: Basic copybook expansion without dependencies

1. ✅ **Complete Phase 1** (Setup): Create structure and base classes
2. ✅ **Complete Phase 2** (Foundation): Implement path validation, encoding, COPY parsing
3. ✅ **Complete Phase 3** (US1): Implement basic expand_copybooks() function
4. 🛑 **STOP and TEST**: Validate US1 works independently with real COBOL programs
5. 📦 **Deploy/Demo**: Users can now expand simple copybooks

**Value Delivered**: Users can parse COBOL programs with copybook dependencies (eliminating manual preprocessing step)

**Next Steps**: Add nested (US2), circular detection (US3), source tracking (US4) incrementally

### Incremental Delivery (All Features)

**Timeline**: ~18-24 hours sequential, ~11-13 hours with 4-person team

1. Phase 1 + Phase 2 (shared foundation) → 6 hours
2. US1 (basic expansion) → 3 hours
3. US2 (nested resolution) → 3 hours
4. US3 (circular detection) → 2 hours
5. US4 (source tracking) → 3 hours
6. Phase 7 (polish + integration) → 2 hours

**Can Demo After Each Step**: Each user story is independently valuable

### Parallel Team Strategy (Recommended for Full Feature)

**Timeline**: ~13-15 hours with 4 developers

1. **All Together** (6 hours): Complete Phase 1 + Phase 2
2. **Split Up** (3 hours parallel):
   - Developer A: US1 (Basic Expansion)
   - Developer B: US2 (Nested Resolution)
   - Developer C: US3 (Circular Detection)
   - Developer D: US4 (Source Tracking)
3. **All Together** (2 hours): Polish, integration, documentation

**Advantages**: Features ship in parallel, faster time-to-complete, independent testing

---

## Task Execution Notes

### Testing Requirements (TDD Mandatory per Constitution)

1. **Contract tests** verify API stability and compatibility
2. **Unit tests** focus on individual components (parsing, validation, recursion)
3. **Integration tests** validate end-to-end workflows with real COBOL

**All tests MUST be written BEFORE implementation and FAIL initially** (Red-Green-Refactor cycle)

### File Path Conventions

- `cobolparser/preprocess/` - Core expansion module (NEW)
- `cobolparser/preprocess/models.py` - Data classes for expansion
- `cobolparser/preprocess/copy_statement_parser.py` - COPY statement parsing
- `cobolparser/preprocess/path_resolver.py` - Path resolution/validation
- `cobolparser/preprocess/copybook_expander.py` - Main expansion logic
- `tests/unit/test_copybook_expansion.py` - Unit tests
- `tests/integration/test_copybook_expansion_integration.py` - Integration tests
- `tests/contracts/test_copybook_expansion_contracts.py` - Contract tests
- `tests/samples/copybooks/` - Test copybook files
- `tests/samples/copybook_programs/` - Test COBOL programs
- `tests/samples/mixed_encodings/` - Encoding test cases

### Dependency Tracking

- **[P] marker**: Task can run in parallel (different files, no blocking dependencies)
- **No [P]**: Task depends on previous tasks in same phase or prior phases
- **[Story label**: Identifies which user story task belongs to (US1, US2, etc.)

### Code Quality Standards (Non-Negotiable per Constitution)

- ✅ Type hints on all public functions
- ✅ Docstrings for modules, classes, functions
- ✅ 81%+ code coverage (pytest --cov-fail-under=81)
- ✅ Ruff linting passes (E, W, F, I, B, C4, UP rules)
- ✅ Black formatting (line-length=88)
- ✅ Mypy type checking (strict mode)
- ✅ No unused imports or variables

### Checkpoint Validation

After each phase checkpoint:
1. Run relevant test suite (unit/integration/contract)
2. Verify 81%+ coverage for implemented code
3. Confirm all quality checks pass (mypy, ruff, black)
4. Test independently testable story is actually independent

---

## Summary

**Total Tasks**: 116  
**Phases**: 7 (Setup + Foundation + 4 User Stories + Polish)  
**User Stories**: 4 (P1 MVP, P2 Nested, P3 Circular, P4 Source Tracking)  
**Estimated Effort**:
- **Sequential Single Developer**: 18-24 hours
- **With 2 Developers**: 12-15 hours (parallel on US stories)
- **With 4 Developers**: 11-13 hours (full parallelization)

**MVP Scope** (User Story 1 only): 6-8 hours for basic copybook expansion

**Next Phase**: Execute in order: Phase 1 → Phase 2 → (Phase 3-6 in parallel or sequence) → Phase 7
