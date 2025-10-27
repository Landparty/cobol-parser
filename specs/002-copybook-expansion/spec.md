# Feature Specification: Nested Copybook Expansion

**Feature Branch**: `002-copybook-expansion`  
**Created**: 2025-10-27  
**Status**: Draft  
**Input**: User description: "Implement a separate function that will expand nested copybooks in a COBOL program and then parse it as an extended program"

## Clarifications

### Session 2025-10-27

- Q: Should the expansion function validate and restrict copybook paths to prevent path traversal attacks? → A: Restrict all copybook paths to within configured search directories (prevent `..` traversal)
- Q: What should happen when the same copybook is referenced multiple times via COPY statements? → A: Expand each COPY statement independently (inline content every time)
- Q: How should the system handle empty or whitespace-only copybook files? → A: Treat as valid (expand to nothing)
- Q: How should the system handle potential encoding differences between source files? → A: Auto-detect encoding per file and convert all to UTF-8
- Q: How should the system handle path separators in copybook references and search paths? → A: Normalize all paths to OS-native format (convert automatically)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Basic Copybook Expansion (Priority: P1)

A COBOL parser user has a program containing COPY statements that reference external copybook files. They want to expand all COPY statements by replacing them with the actual copybook content, creating a single unified source file that can be parsed without external dependencies.

**Why this priority**: This is the fundamental capability - without basic expansion, the feature provides no value. This enables parsing of COBOL programs that use copybooks.

**Independent Test**: Can be fully tested by providing a COBOL program with simple COPY statements and verifying that the function returns expanded source code with copybook content inlined.

**Acceptance Scenarios**:

1. **Given** a COBOL program with a single `COPY MEMBER1.` statement and a copybook file `MEMBER1.cpy` exists, **When** the expansion function is called with the program source and copybook directory path, **Then** the COPY statement is replaced with the content from `MEMBER1.cpy`.

2. **Given** a COBOL program with multiple COPY statements in different divisions, **When** the expansion function is called, **Then** each COPY statement is replaced with its corresponding copybook content in the correct location.

3. **Given** a COBOL program with COPY statements using different syntax variants (`COPY "MEMBER"`, `COPY MEMBER`, `COPY MEMBER IN LIBRARY`), **When** the expansion function is called, **Then** all syntax variants are correctly recognized and expanded.

4. **Given** a COBOL program with no COPY statements, **When** the expansion function is called, **Then** the original program source is returned unchanged.

---

### User Story 2 - Nested Copybook Resolution (Priority: P2)

A COBOL parser user has copybooks that themselves contain COPY statements (nested copybooks). They want all nested COPY statements resolved recursively so the final expanded program has no remaining COPY statements at any nesting level.

**Why this priority**: Real-world enterprise COBOL programs commonly use nested copybooks for modular data structures. Without nested resolution, the feature is incomplete for production use.

**Independent Test**: Can be tested independently by providing a main program that copies a copybook, where that copybook itself contains COPY statements, and verifying complete expansion.

**Acceptance Scenarios**:

1. **Given** a COBOL program with `COPY LEVEL1.` and `LEVEL1.cpy` contains `COPY LEVEL2.`, **When** the expansion function is called, **Then** both COPY statements are resolved and the final output contains content from both LEVEL1 and LEVEL2.

2. **Given** nested copybooks with 3 levels of depth (program → copybook1 → copybook2 → copybook3), **When** the expansion function is called, **Then** all COPY statements are recursively expanded regardless of nesting level.

3. **Given** a copybook that references multiple other copybooks, **When** the expansion function is called as part of nested expansion, **Then** all nested COPY statements are resolved in the correct order.

---

### User Story 3 - Circular Reference Detection (Priority: P3)

A COBOL parser user has copybooks with circular references (copybook A includes copybook B, which includes copybook A). They want the expansion function to detect this error condition and report it clearly rather than entering an infinite loop.

**Why this priority**: While circular references are rare in well-maintained COBOL code, detecting them prevents catastrophic failures and provides useful debugging information.

**Independent Test**: Can be tested by intentionally creating copybooks with circular references and verifying that the function raises an appropriate error with details about the circular dependency chain.

**Acceptance Scenarios**:

1. **Given** copybook A contains `COPY B.` and copybook B contains `COPY A.`, **When** the expansion function is called, **Then** a circular reference error is raised listing the dependency chain (A → B → A).

2. **Given** copybooks with indirect circular references (A → B → C → A), **When** the expansion function is called, **Then** the circular reference is detected and reported with the complete chain.

3. **Given** multiple independent COPY statements where only one creates a circular reference, **When** the expansion function is called, **Then** the error message identifies which specific COPY statement caused the circular reference.

---

### User Story 4 - Source Location Preservation (Priority: P4)

A COBOL parser user wants to trace errors in the expanded program back to their original source location (either the main program or a specific copybook). They need the expansion function to preserve or generate metadata mapping expanded content to original source locations.

**Why this priority**: This enhances the developer experience by enabling accurate error reporting, but the core expansion functionality works without it.

**Independent Test**: Can be tested by expanding a program with copybooks, introducing an intentional syntax error in a copybook, parsing the expanded result, and verifying that error messages reference the original copybook file and line number.

**Acceptance Scenarios**:

1. **Given** a COBOL program with copybook includes, **When** the expansion function is called with location tracking enabled, **Then** the expanded source includes metadata indicating which lines originated from which source file.

2. **Given** an expanded program with source location metadata, **When** a parsing error occurs in expanded copybook content, **Then** the error message references the original copybook filename and line number.

3. **Given** nested copybooks, **When** source location tracking is enabled, **Then** the deepest source file (original copybook) is identified for each line in the expanded output.

---

### Edge Cases

- What happens when a COPY statement references a copybook file that does not exist? **Answered by FR-011**: Raise an error with copybook name and search paths.
- How does the system handle COPY statements with REPLACING clauses (text substitution)? **Answered by FR-017**: Perform text substitution after copybook content is inserted.
- What happens when a copybook file is empty or contains only whitespace? **Answered by FR-012**: Treat as valid and expand to empty content.
- How does the system handle copybook paths with different separators (forward slash vs backslash)? **Answered by FR-008**: Normalize all paths to OS-native format automatically.
- What happens when the same copybook is included multiple times in different locations? **Answered by FR-007**: Expand each COPY statement independently (inline every time).
- How does the system handle COPY statements with library qualifiers (IN/OF library-name)? **Answered by FR-003**: Supported as standard syntax variant.
- What happens when copybook nesting exceeds a reasonable depth limit (e.g., 50 levels)? **Answered by FR-010**: Configurable maximum nesting depth (default: 100 levels).
- How does the system handle encoding differences between the main program and copybook files? **Answered by FR-013**: Auto-detect encoding per file and convert to UTF-8.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a standalone function `expand_copybooks()` that accepts COBOL source code and returns expanded source code with all COPY statements replaced by copybook content.

- **FR-002**: Function MUST accept a copybook search path (list of directory paths) to locate copybook files referenced in COPY statements.

- **FR-003**: System MUST support standard COBOL COPY statement syntax including: `COPY member-name`, `COPY "member-name"`, `COPY member-name IN library-name`, and `COPY member-name OF library-name`.

- **FR-004**: System MUST resolve nested COPY statements recursively until no COPY statements remain in the expanded output.

- **FR-005**: System MUST detect circular reference loops and raise a descriptive error containing the dependency chain rather than entering an infinite loop.

- **FR-006**: System MUST preserve the original program structure (divisions, sections, paragraphs) while expanding copybook content inline at the location of each COPY statement.

- **FR-007**: System MUST expand each COPY statement independently, inlining copybook content every time the same copybook is referenced, matching standard COBOL compiler behavior.

- **FR-008**: System MUST normalize all file paths (copybook names and search paths) to OS-native separator format automatically, supporting both forward slash and backslash input for cross-platform compatibility.

- **FR-009**: System MUST handle both `.cpy` and `.CPY` file extensions, and copybook names without extensions by searching for common extensions (`.cpy`, `.CPY`, `.cbl`, `.CBL`, `.cob`, `.COB`).

- **FR-010**: System MUST provide a configurable maximum nesting depth (default: 100 levels) to prevent excessive recursion in pathological cases.

- **FR-011**: Function MUST raise an error with the copybook name and search paths when a referenced copybook file cannot be found.

- **FR-012**: System MUST treat empty or whitespace-only copybook files as valid, expanding them to empty content (matching standard COBOL compiler behavior for placeholder copybooks).

- **FR-013**: System MUST auto-detect the character encoding of each source file (main program and copybooks) and convert all content to UTF-8 internally to handle mixed-encoding scenarios (e.g., EBCDIC copybooks with ASCII programs).

- **FR-014**: System MUST validate that all resolved copybook file paths remain within the configured search directories, rejecting any path traversal attempts (e.g., containing `..` sequences) to prevent reading files outside intended locations.

- **FR-015**: System MUST optionally preserve source location metadata mapping each line in the expanded output to its original source file and line number.

- **FR-016**: System MUST provide a convenience function `parse_cobol_with_expansion()` that combines copybook expansion with parsing in a single call.

- **FR-017**: System MUST handle COPY REPLACING clauses by performing text substitution after copybook content is inserted (common IBM Enterprise COBOL feature).

### Key Entities

- **CopybookExpansion**: Represents the result of expanding copybooks in a COBOL program. Contains the expanded source code, a list of included copybook files, the expansion depth reached, and optional source location mappings.

- **CopyStatement**: Represents a parsed COPY statement from COBOL source. Contains the copybook member name, optional library qualifier, optional REPLACING clause, and source location in the original file.

- **SourceLocationMap**: Maps lines in the expanded source to their original source file and line number. Enables tracing errors back to the original copybook or main program.

- **CopybookSearchPath**: Configuration for locating copybook files. Contains an ordered list of directory paths to search, file extension preferences, and case sensitivity settings.

- **ExpansionContext**: Tracks the state during recursive expansion. Contains the current file being processed, the stack of files being expanded (for circular reference detection), and the accumulated source location mappings.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can expand COBOL programs containing nested copybooks up to 10 levels deep without errors or performance degradation.

- **SC-002**: Circular reference detection prevents infinite loops and provides error messages identifying the complete dependency chain within 1 second.

- **SC-003**: Expanded programs parse successfully with the existing parser when all copybooks are properly resolved, achieving the same parsing success rate as manually expanded programs.

- **SC-004**: Source location mapping accurately traces parsing errors in expanded content back to the original copybook file and line number in 100% of test cases.

- **SC-005**: The expansion function handles real-world IBM Enterprise COBOL programs with typical copybook usage (average 5-15 copybooks per program) with expansion time under 100ms per program.

- **SC-006**: Users can successfully parse COBOL programs with copybook dependencies without manual preprocessing, reducing setup time from manual expansion to zero.

## Assumptions

- Copybook files are available on the local filesystem at expansion time (not retrieved from remote sources or version control).
- COPY statements follow standard IBM Enterprise COBOL syntax as documented in Enterprise COBOL Language Reference.
- Users provide valid copybook search paths; the system does not auto-discover copybook locations.
- The same copybook included multiple times has identical content (no version conflicts).
- COPY REPLACING clause syntax follows IBM Enterprise COBOL conventions (substring replacement rules).
- Maximum reasonable nesting depth is 100 levels; deeper nesting indicates a configuration error.
