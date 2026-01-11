# Feature Specification: IO Variation Coverage

**Feature Branch**: `[001-io-variation-coverage]`  
**Created**: 2026-01-11  
**Status**: Draft  
**Input**: User description: "I would like to make sure that all the different variation I/O statements are covered and tested by the parser for a cobol fix format."

## Clarifications

### Session 2026-01-11

- Q: What is the authoritative catalog for enumerating all IO statement variations? → A: IBM Enterprise COBOL Language Reference.
- Q: What format should the IO coverage summary use for consistency across tooling? → A: Machine-readable JSON/CSV artifact (with schema) produced by CI.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Parse every IBM COBOL IO form (Priority: P1)

Parser engineers need the COBOL parser to successfully read IBM Enterprise COBOL fixed-format programs that contain every OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, ACCEPT, DISPLAY, and UNLOCK variation so that no mission-critical batch job fails during migration.

**Why this priority**: Production workloads depend on these IO statements; a single unsupported variation blocks entire compiler migrations.

**Independent Test**: Run the parser against a curated suite that isolates each IO statement variation and confirm the resulting AST structures and diagnostics match the specification.

**Acceptance Scenarios**:

1. **Given** a fixed-format COBOL source containing sequential, indexed, and relative file definitions with matching OPEN/CLOSE modes, **When** the parser runs with error recovery enabled, **Then** it produces AST nodes for every IO statement without fatal errors or dropped tokens.
2. **Given** a program that mixes READ ... AT END, READ ... INVALID KEY, and WRITE ... ADVANCING options, **When** the parser processes it, **Then** each qualifier appears in the structured output so downstream tooling can reason about flow control.

---

### User Story 2 - Guarantee regression coverage (Priority: P2)

QA leads must be able to prove that every supported IO variation has at least one automated unit or integration test so regressions are caught before release.

**Why this priority**: Without proven coverage, subtle IO regressions slip through and only surface during costly mainframe promotion windows.

**Independent Test**: Execute the IO-specific test matrix and verify that each targeted statement variation flips the suite to red if its expected AST or diagnostics change.

**Acceptance Scenarios**:

1. **Given** the IO variation matrix, **When** a developer removes support for WRITE ... AFTER ADVANCING, **Then** the dedicated regression test fails with a clear explanation of the missing qualifier.
2. **Given** a new ACCEPT variation is added to the parser, **When** the QA harness runs, **Then** it reports the new variation as covered with both positive and negative cases.

---

### User Story 3 - Surface coverage status to maintainers (Priority: P3)

Release managers need an at-a-glance view of which IO statements and qualifiers are supported, partially supported, or intentionally out of scope so they can plan delivery timelines and stakeholder messaging.

**Why this priority**: Transparent coverage prevents duplicate bug reports and keeps customer-facing teams aligned on capabilities.

**Independent Test**: Generate the IO coverage report from the parser artifacts and confirm it lists every targeted statement along with test references.

**Acceptance Scenarios**:

1. **Given** the IO coverage summary, **When** a maintainer reviews a support ticket about CLOSE WITH NO REWIND, **Then** they can cite the exact test that verifies the behavior or note that it is pending.
2. **Given** a stakeholder asks whether DELETE with INVALID KEY is supported, **When** the maintainer checks the coverage table, **Then** it clearly indicates the support state and linked regression test.

---

### Edge Cases

- Statements split across multiple continuation lines in Area B while retaining indicator characters in columns 7–11.
- IO statements that interleave multiple optional clauses (e.g., READ ... WITH LOCK ... KEY IS ... AT END ... INVALID KEY) inside nested IF or PERFORM blocks.
- Programs that mix file organizations (sequential, indexed, VSAM, relative) within the same division and reuse file names across sections.
- ACCEPT and DISPLAY statements that target environment names (DATE, TIME) or data items with editing characters while the statement is preceded by fixed-format comment indicators.
- OPEN/CLOSE combinations that include IBM-specific phrases such as NO REWIND, LOCK, or REEL/UNIT control.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The parser MUST recognize every IBM Enterprise COBOL fixed-format variation of OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, ACCEPT, DISPLAY, and UNLOCK statements, even when keywords are split by continuation lines or column-sensitive spacing.
- **FR-002**: Structured output MUST capture each IO statement’s file name, mode (INPUT, OUTPUT, I-O, EXTEND), access type (sequential, random, dynamic), locking semantics, and clause-specific qualifiers (ADVANCING, INVALID KEY, AT END, NO REWIND, WITH LOCK, KEY IS ...).
- **FR-003**: When an unsupported or invalid IO combination appears, the parser MUST emit actionable diagnostics that cite the exact source line and column offsets without aborting the rest of the parse in COLLECT_ALL mode.
- **FR-004**: A regression test matrix MUST exist where every identified IO variation has at least one positive test (successful parse) and one negative test (expected diagnostic) enforced through CI.
- **FR-005**: Sample COBOL programs used in tests MUST exercise sequential, indexed, relative, and VSAM files, including combinations with FD-level clauses (BLOCK CONTAINS, RECORD KEY, ALTERNATE RECORD KEY) to ensure IO statements bind to their metadata.
- **FR-006**: JSON exports of IO-related AST nodes MUST include the enriched metadata so downstream tooling (visualizers, analyzers, memory monitors) can consume a consistent schema.
- **FR-007**: Performance safeguards MUST ensure the IO coverage suites can parse at least a 5MB fixed-format source within existing memory limits (default 256MB) without requiring manual configuration changes.
- **FR-008**: Documentation delivered with the coverage suite MUST list each IO variation, associated tests, and any intentional exclusions so maintainers can update the matrix in under 15 minutes.
- **FR-009**: CI MUST emit a machine-readable IO coverage artifact (JSON or CSV conforming to a published schema) that downstream dashboards and documentation generators can consume without manual edits.

### Key Entities *(include if feature involves data)*

- **IO Statement Variation**: Describes a specific COBOL IO verb plus its qualifiers (e.g., READ NEXT RECORD WITH LOCK AT END) and the expected structured output metadata.
- **IO Test Fixture**: A COBOL source snippet (and expected AST/diagnostic assertions) mapped to one or more IO statement variations for regression coverage.
- **IO Coverage Summary**: Aggregated report that lists each variation, linked regression tests, execution status, and gaps requiring future work.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of the targeted IO statement variations parse successfully (no fatal errors) across the curated fixed-format suite, confirmed in both FAIL_FAST and COLLECT_ALL modes.
- **SC-002**: The IO regression suites complete in under 90 seconds on the reference environment while exercising every variation with at least one positive and one negative assertion.
- **SC-003**: The IO coverage summary reports 100% coverage for the enumerated variations, and CI fails automatically if any variation lacks a mapped test.
- **SC-004**: Support teams reduce IO-related parser tickets by 40% within one release because diagnostics clearly identify unsupported phrases and link to coverage status.
- **SC-005**: Each CI run publishes the IO coverage artifact with 100% validation against the agreed schema, and downstream dashboards consume it without manual intervention.

## Assumptions

- Scope is limited to IBM Enterprise COBOL fixed-format syntax; free-format or non-IBM dialect extensions remain out of scope for this feature.
- Target IO statements are OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, ACCEPT, DISPLAY, and UNLOCK; other verbs (e.g., EXEC CICS) are tracked separately.
- Existing memory configuration defaults (256MB limit with streaming disabled) are considered sufficient once performance safeguards in FR-007 are met.
- The IBM Enterprise COBOL Language Reference serves as the canonical source for enumerating IO variation coverage (verbs, qualifiers, and clause combinations).
