# Feature Specification: Comprehensive CALL Statement Coverage for COBOL Fixed Format

**Feature Branch**: `001-call-statements-coverage`  
**Created**: January 11, 2026  
**Status**: Draft  
**Input**: User description: "Ensure all variations of CALL statements are covered and tested by the parser for COBOL fixed format"

## Clarifications

### Session 2026-01-11

- Q: How should the parser handle CALL statements with both RETURNING and GIVING clauses present? → A: Parser should treat RETURNING and GIVING as mutually exclusive (error if both present)
- Q: What continuation indicator should be recognized in column 7 for multi-line CALL statements? → A: Hyphen `-` in column 7 (ANSI COBOL-85 standard)
- Q: Should dynamic CALL value tracking analyze all assignment types or just MOVE statements? → A: Track MOVE statements only as MVP; document future extensions clearly
- Q: What counts as a "variation" for success criterion SC-001? → A: Define 6 explicit variation categories (one per user story) as the success metric
- Q: How deeply should nested statements within exception handlers be parsed? → A: Use same recursion depth limits as main parser (consistent with existing infrastructure)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Basic CALL Statement Parsing (Priority: P1)

**User Journey**: As a COBOL parser user, I need to parse basic CALL statements with program names (both literal strings and variables) so that I can analyze program dependencies and call hierarchies.

**Why this priority**: Basic CALL statements are fundamental to every COBOL program that uses modular programming. Without this, no call analysis is possible.

**Independent Test**: Parse a simple COBOL program containing `CALL "SUBPROG"` and verify the AST contains a CallStatement node with called_program="SUBPROG". This validates the parser can handle the most common CALL pattern.

**Acceptance Scenarios**:

1. **Given** a COBOL program with `CALL "PROGRAM-NAME"`, **When** the parser processes the statement, **Then** the AST contains a CallStatement with called_program="PROGRAM-NAME" and is_dynamic=false
2. **Given** a COBOL program with `CALL WS-PROGRAM-VAR`, **When** the parser processes the statement, **Then** the AST contains a CallStatement with called_program="WS-PROGRAM-VAR" and is_dynamic=true
3. **Given** a CALL statement with no parameters, **When** the parser processes it, **Then** using_parameters is an empty array

---

### User Story 2 - Parameter Passing Modes (Priority: P1)

**User Journey**: As a developer analyzing COBOL code, I need the parser to capture all parameter passing modes (BY REFERENCE, BY CONTENT, BY VALUE) so that I can understand how data flows between calling and called programs.

**Why this priority**: Parameter passing modes affect how data is shared and modified across program boundaries. Incorrect analysis here leads to incorrect data flow analysis.

**Independent Test**: Parse `CALL "SUB" USING BY REFERENCE P1 BY CONTENT P2 BY VALUE P3` and verify each parameter has the correct passing mode. This is independent of other CALL features.

**Acceptance Scenarios**:

1. **Given** `CALL "SUB" USING BY REFERENCE PARAM1`, **When** parsed, **Then** parameter PARAM1 has passing_mode="REFERENCE"
2. **Given** `CALL "SUB" USING BY CONTENT PARAM2`, **When** parsed, **Then** parameter PARAM2 has passing_mode="CONTENT"
3. **Given** `CALL "SUB" USING BY VALUE PARAM3`, **When** parsed, **Then** parameter PARAM3 has passing_mode="VALUE"
4. **Given** `CALL "SUB" USING PARAM1 PARAM2` (no explicit mode), **When** parsed, **Then** both parameters default to passing_mode="REFERENCE"
5. **Given** multiple parameters with mixed modes, **When** parsed, **Then** each parameter retains its specified mode independently

---

### User Story 3 - RETURNING/GIVING Clause (Priority: P2)

**User Journey**: As a code analyst, I need to identify which CALL statements return values to understand function-like program calls and track result variables.

**Why this priority**: RETURNING/GIVING clauses indicate functional programming patterns in COBOL. Missing these prevents proper return value tracking.

**Independent Test**: Parse `CALL "CALCULATOR" RETURNING RESULT-VAR` and verify the CallStatement has returning_parameter="RESULT-VAR" or giving_parameter="RESULT-VAR". Independent of exception handling and parameter passing.

**Acceptance Scenarios**:

1. **Given** `CALL "FUNC" RETURNING WS-RESULT`, **When** parsed, **Then** CallStatement has returning_parameter="WS-RESULT" and giving_parameter is null
2. **Given** `CALL "FUNC" GIVING WS-OUTPUT`, **When** parsed, **Then** CallStatement has giving_parameter="WS-OUTPUT" and returning_parameter is null
3. **Given** CALL with both USING and RETURNING clauses, **When** parsed, **Then** both using_parameters and returning_parameter are populated correctly
4. **Given** CALL with neither RETURNING nor GIVING, **When** parsed, **Then** both returning_parameter and giving_parameter are null
5. **Given** CALL with both RETURNING and GIVING clauses, **When** parsed, **Then** parser raises an error indicating mutually exclusive clauses

---

### User Story 4 - Exception Handling Clauses (Priority: P2)

**User Journey**: As a developer reviewing error handling logic, I need to see ON EXCEPTION, NOT ON EXCEPTION, and ON OVERFLOW clauses parsed into the AST so I can verify error handling completeness.

**Why this priority**: Exception handling clauses contain critical error recovery logic. Losing this information prevents complete control flow analysis.

**Independent Test**: Parse a CALL statement with `ON EXCEPTION DISPLAY "ERROR" NOT ON EXCEPTION DISPLAY "SUCCESS"` and verify both clause bodies are captured in the AST with their respective statements.

**Acceptance Scenarios**:

1. **Given** `CALL "SUB" ON EXCEPTION MOVE "ERROR" TO STATUS`, **When** parsed, **Then** on_exception contains a MoveStatement
2. **Given** `CALL "SUB" NOT ON EXCEPTION MOVE "OK" TO STATUS`, **When** parsed, **Then** not_on_exception contains a MoveStatement
3. **Given** CALL with both ON EXCEPTION and NOT ON EXCEPTION, **When** parsed, **Then** both clauses are populated with their respective statement lists
4. **Given** `CALL "SUB" ON OVERFLOW DISPLAY "OVERFLOW"`, **When** parsed, **Then** on_overflow contains the DISPLAY statement
5. **Given** CALL with END-CALL terminator, **When** parsed, **Then** all exception clause statements are properly bounded by END-CALL

---

### User Story 5 - COBOL Fixed Format Compliance (Priority: P1)

**User Journey**: As a user parsing legacy COBOL source code, I need the parser to correctly handle CALL statements in fixed format (columns 7-72) with continuation lines so that I can process real-world mainframe programs.

**Why this priority**: Real-world IBM Enterprise COBOL is written in fixed format. Without this, the parser cannot handle production codebases.

**Independent Test**: Parse a CALL statement that spans multiple lines with continuation in column 7 (e.g., CALL statement starting on line 1, USING clause on line 2 with continuation marker). Verify all parameters are captured correctly.

**Acceptance Scenarios**:

1. **Given** a CALL statement with hyphen `-` in column 7 spanning multiple lines, **When** parsed, **Then** all clauses and parameters are captured as if written on a single line
2. **Given** CALL statement with comments after the statement terminator, **When** parsed, **Then** comments do not interfere with statement parsing
3. **Given** CALL in columns 8-72 with columns 1-6 ignored, **When** parsed, **Then** statement is correctly tokenized
4. **Given** literals spanning continuation lines (with hyphen in column 7) in USING parameters, **When** parsed, **Then** literals are reconstructed correctly

---

### User Story 6 - Dynamic CALL Analysis (Priority: P3)

**User Journey**: As a developer performing impact analysis, I need the parser to track possible values for dynamic CALL statements (where program name is a variable) so that I can build complete call graphs.

**Why this priority**: Dynamic CALLs are common in table-driven COBOL architectures. Without value tracking, call graphs are incomplete.

**Independent Test**: Parse a program with `MOVE "PROG-A" TO WS-VAR` followed by `CALL WS-VAR`. After analysis, verify the CallStatement's possible_values includes "PROG-A". This validates dynamic call tracking independently of other features.

**Acceptance Scenarios**:

1. **Given** dynamic CALL with a variable assigned once via MOVE statement, **When** analyzed, **Then** possible_values contains that single value
2. **Given** dynamic CALL with multiple MOVE assignments to the same variable, **When** analyzed, **Then** possible_values contains all moved values
3. **Given** dynamic CALL with conditional MOVE assignments (IF/EVALUATE branches), **When** analyzed, **Then** possible_values includes all branch-assigned values
4. **Given** dynamic CALL where variable has no MOVE assignments tracked, **When** analyzed, **Then** possible_values is empty
5. **Given** dynamic CALL where variable is assigned via COMPUTE or other non-MOVE statement, **When** analyzed, **Then** parser does not track those values (MVP scope)



### Edge Cases

- What happens when CALL statement has no program name (syntax error)?
- How does the parser handle CALL with USING but no parameters listed?
- What if END-CALL appears without ON EXCEPTION/NOT ON EXCEPTION clauses?
- How are nested CALL statements within exception handlers processed?
- What if a CALL statement uses reserved words as parameter names?
- How does the parser handle CALL to intrinsic functions vs subprograms?
- What if CALL has both RETURNING and GIVING clauses? (RESOLVED: Parser treats them as mutually exclusive and raises an error)
- How are ADDRESS OF and LENGTH OF special registers handled in USING parameters?

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Parser MUST recognize and parse CALL statements with literal string program names (e.g., `CALL "SUBPROG"`)
- **FR-002**: Parser MUST recognize and parse CALL statements with variable program names (e.g., `CALL WS-PROGRAM-NAME`) and mark them as dynamic calls
- **FR-003**: Parser MUST capture all USING parameters with their names and passing modes (REFERENCE, CONTENT, VALUE)
- **FR-004**: Parser MUST default parameter passing mode to REFERENCE when no mode is explicitly specified
- **FR-005**: Parser MUST capture RETURNING clause and store the return variable name in returning_parameter (giving_parameter must be null)
- **FR-006**: Parser MUST capture GIVING clause as an alternative to RETURNING and store the return variable name in giving_parameter (returning_parameter must be null)
- **FR-006a**: Parser MUST reject CALL statements that contain both RETURNING and GIVING clauses with a parse error
- **FR-007**: Parser MUST parse ON EXCEPTION clause and capture all statements within it, subject to the same recursion depth limits as the main parser
- **FR-008**: Parser MUST parse NOT ON EXCEPTION clause and capture all statements within it, subject to the same recursion depth limits as the main parser
- **FR-009**: Parser MUST parse ON OVERFLOW clause and capture all statements within it, subject to the same recursion depth limits as the main parser
- **FR-010**: Parser MUST recognize END-CALL as the terminator for exception-handling CALL statements
- **FR-011**: Parser MUST handle CALL statements spanning multiple lines in COBOL fixed format (columns 7-72) with hyphen `-` in column 7 as the continuation indicator
- **FR-012**: Parser MUST preserve continuation line content across multiple source lines when hyphen `-` appears in column 7
- **FR-013**: Parser MUST generate CallStatement AST nodes with all captured properties (called_program, is_dynamic, using_parameters, returning_parameter, giving_parameter, on_exception, not_on_exception, on_overflow)
- **FR-014**: Parser MUST serialize CallStatement nodes to JSON with all properties preserved
- **FR-015**: Dynamic call analyzer MUST track possible values for variables used in dynamic CALL statements by analyzing MOVE statement assignments only (MVP scope)
- **FR-016**: Dynamic call analyzer MUST populate possible_values array on CallStatement nodes after analysis with values collected from MOVE statement tracking

### Test Coverage Requirements

- **FR-017**: Test suite MUST include unit tests for each parameter passing mode (REFERENCE, CONTENT, VALUE, default)
- **FR-018**: Test suite MUST include tests for RETURNING and GIVING clauses independently and combined with USING
- **FR-019**: Test suite MUST include tests for all exception handling clauses (ON EXCEPTION, NOT ON EXCEPTION, ON OVERFLOW)
- **FR-020**: Test suite MUST include tests for multi-line CALL statements in fixed format
- **FR-021**: Test suite MUST include integration tests for dynamic CALL value tracking
- **FR-022**: Test suite MUST include contract tests verifying JSON serialization stability of CallStatement

### Key Entities

- **CallStatement**: Represents a CALL statement in the AST with properties: called_program (string), is_dynamic (boolean), using_parameters (array of CallParameter), returning_parameter (string or null), giving_parameter (string or null), on_exception (array of Statement nodes), not_on_exception (array of Statement nodes), on_overflow (array of Statement nodes)
- **CallParameter**: Represents a parameter passed in a CALL statement with properties: name (string), passing_mode (string: "REFERENCE", "CONTENT", or "VALUE")
- **DynamicCallAnalyzer**: Component that tracks variable assignments and populates possible_values for dynamic CALL statements

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Parser successfully handles all 6 CALL statement variation categories (one per user story): (1) Basic static/dynamic CALL parsing, (2) All parameter passing modes, (3) RETURNING/GIVING clauses, (4) Exception handling clauses, (5) Fixed format multi-line continuation, (6) Dynamic value tracking
- **SC-002**: Test coverage for CALL statement parsing reaches 95% or higher (measured by line coverage)
- **SC-003**: All parameter passing modes (BY REFERENCE, BY CONTENT, BY VALUE, default) are correctly identified in parsed AST nodes
- **SC-004**: Dynamic CALL value tracking correctly identifies at least 90% of statically determinable program names in test cases
- **SC-005**: CALL statement parsing completes within 10ms for statements with up to 50 parameters
- **SC-006**: Zero parsing errors occur for valid CALL statements in COBOL-85 and IBM Enterprise COBOL fixed format
- **SC-007**: JSON export of CallStatement AST nodes is consistent and stable across parser versions (validated by contract tests)
- **SC-008**: Parser handles CALL statements spanning up to 20 continuation lines without data loss

## Implementation Notes

### Current State Analysis

Based on the codebase review:

1. **Existing Implementation**: CallStatement model exists in `cobolparser/models/statements.py` with comprehensive properties
2. **Parser Support**: `parse_call_statement()` method exists in `cobolparser/parser.py` with inline parsing support
3. **Test Coverage**: 4 test files exist for CALL statements:
   - `tests/unit/test_call_statement_parsing.py` - Parameter modes, RETURNING, exception clauses
   - `tests/unit/test_statements.py` - Basic CallStatement model tests
   - `tests/integration/test_call_comprehensive.py` - Integration testing
   - `tests/contracts/test_dynamic_call_contract.py` - API contracts
4. **Documentation**: Comprehensive documentation exists in `docs/call-statements.md` covering static/dynamic CALLs

### Identified Gaps

1. **Parameter Passing Modes**: Tests exist but coverage may be incomplete for mixed-mode scenarios
2. **Fixed Format Handling**: No explicit tests for multi-line CALL statements with continuation lines
3. **RETURNING vs GIVING**: Current code uses both `returning_parameter` and `giving_parameter` - need to verify which is correct per COBOL spec or if both should be supported
4. **END-CALL Terminator**: Parser logic for END-CALL boundary detection needs verification
5. **Edge Case Coverage**: Missing tests for malformed CALL statements, nested exception handlers, special register parameters (ADDRESS OF, LENGTH OF)

### Assumptions

- Parser already handles COBOL fixed format tokenization (columns 1-6 sequence, 7 indicator, 8-72 content)
- Lexer correctly identifies continuation lines and reconstructs multi-line statements
- IBM Enterprise COBOL dialect takes priority over ANSI COBOL where they differ
- RETURNING and GIVING are synonymous (IBM uses RETURNING, some dialects use GIVING)
- Default parameter passing mode is BY REFERENCE per COBOL standard
- Dynamic call analysis is a post-parsing phase (not performed during initial parsing)

## Assumptions

- The lexer correctly tokenizes COBOL fixed format source (columns 7-72, continuation indicated by hyphen `-` in column 7 per ANSI COBOL-85)
- RETURNING and GIVING clauses are functionally equivalent (both store return variable)
- Parameter passing mode defaults to REFERENCE when not specified
- Exception clause bodies (ON EXCEPTION, NOT ON EXCEPTION, ON OVERFLOW) can contain any valid COBOL statements, parsed to the same recursion depth limits as the main parser
- END-CALL is required only when exception clauses are present
- Dynamic call analysis is optional and performed after initial parsing
- Test environment includes sample COBOL programs in fixed format for integration testing

## Dependencies

- Lexer must provide tokens with accurate source location information for fixed format
- Statement parsing infrastructure must support nested statement parsing (for exception clause bodies)
- AST node serialization framework must support complex nested structures (exception clauses containing statement arrays)
- Test framework must support parameterized tests for testing multiple variations efficiently

## Out of Scope

- CALL statement optimization or performance tuning
- Call graph visualization or reporting tools
- CALL statement refactoring capabilities
- Support for free format COBOL (only fixed format is in scope)
- Cross-program data flow analysis beyond simple call graphs
- CALL to Java/C/C++ interoperability (JNI, LINKAGE SECTION)
- Advanced dynamic call analysis using symbolic execution or constraint solving
- **Future Extensions** (Phase 2+): Tracking program names assigned via COMPUTE, ADD, SUBTRACT, ACCEPT, intrinsic functions, or other non-MOVE statements in dynamic CALL analysis

