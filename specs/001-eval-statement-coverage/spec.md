# Feature Specification: COBOL Fixed-Format EVALUATE Coverage

**Feature Branch**: `001-eval-statement-coverage`  
**Created**: 2026-01-11  
**Status**: Draft  
**Input**: User description: "I would like to make sure that all the different variation evaluation statements are covered and tested by the parser for a cobol fix format."

## User Scenarios & Testing *(mandatory)*

<!--
  IMPORTANT: User stories should be PRIORITIZED as user journeys ordered by importance.
  Each user story/journey must be INDEPENDENTLY TESTABLE - meaning if you implement just ONE of them,
  you should still have a viable MVP (Minimum Viable Product) that delivers value.
  
  Assign priorities (P1, P2, P3, etc.) to each story, where P1 is the most critical.
  Think of each story as a standalone slice of functionality that can be:
  - Developed independently
  - Tested independently
  - Deployed independently
  - Demonstrated to users independently
-->

### User Story 1 - Validate all fixed-format EVALUATE variants (Priority: P1)

Parser maintainers need to confirm every fixed-format EVALUATE variation (single subject, multiple subjects with ALSO, truth-value EVALUATE TRUE/FALSE, ANY, THRU/THROUGH ranges, nested EVALUATE) parses into a consistent AST and is backed by explicit coverage.

**Why this priority**: Missing variant support blocks COBOL program ingestion and erodes parser trust for IBM-style fixed-format source.

**Independent Test**: Run the positive EVALUATE-variant suite alone; each fixture should parse without errors and emit the expected serialized structure for its variant.

**Acceptance Scenarios**:

1. **Given** a catalog of fixed-format EVALUATE variants, **When** each sample is parsed, **Then** the parser produces a successful AST for every variant with the correct selectors and WHEN branches represented.
2. **Given** an EVALUATE statement that combines subjects with ALSO and range conditions (THRU/THROUGH), **When** parsed in fixed-format layout, **Then** the AST reflects combined selectors without loss or reordering.

---

### User Story 2 - Surface clear diagnostics for malformed EVALUATE (Priority: P2)

Quality engineers need deterministic, human-readable diagnostics when fixed-format EVALUATE statements are malformed (missing WHEN, misaligned columns, invalid ranges) to speed triage.

**Why this priority**: Clear errors prevent silent misparses and reduce investigation time when onboarding new COBOL sources.

**Independent Test**: Run the negative EVALUATE suite; each malformed sample should produce the documented diagnostic with correct line/column references while the parser remains stable.

**Acceptance Scenarios**:

1. **Given** a fixed-format EVALUATE missing a required WHEN clause, **When** parsed, **Then** a single deterministic diagnostic is emitted that cites the statement location and category of error.
2. **Given** an EVALUATE with improperly aligned continuation lines, **When** parsed, **Then** the parser reports a formatting diagnostic without crashing or producing partial AST output.

---

### User Story 3 - Maintain regression guardrails for EVALUATE support (Priority: P3)

Parser owners want a living coverage matrix so future grammar or lexer changes cannot regress fixed-format EVALUATE handling without detection.

**Why this priority**: Sustains confidence during refactors by keeping variant coverage visible and enforced.

**Independent Test**: Run only the EVALUATE regression gate; it should fail if any cataloged variant lacks a passing positive and negative test, even when unrelated parser areas change.

**Acceptance Scenarios**:

1. **Given** the variant coverage matrix, **When** the test suite executes, **Then** the report shows 100% coverage for the EVALUATE variant catalog.
2. **Given** a newly added EVALUATE variant to the catalog, **When** tests are run, **Then** the suite requires corresponding fixtures before reporting the coverage as complete.

---

[Add more user stories as needed, each with an assigned priority]

### Edge Cases

- EVALUATE statements with multiple subjects combined via ALSO and mixed literal types (numeric, alphanumeric, figurative constants).
- THRU/THROUGH ranges that overlap or reverse order within WHEN phrases.
- Use of ANY alongside other selectors in the same WHEN phrase.
- Nested EVALUATE statements inside WHEN bodies that should not interfere with outer statement parsing.
- Fixed-format specifics: sequence numbers and indicator columns present, continuation lines, and inline comments affecting column positions.
- EVALUATE TRUE/FALSE with and without explicit conditions.

## Requirements *(mandatory)*

<!--
  ACTION REQUIRED: The content in this section represents placeholders.
  Fill them out with the right functional requirements.
-->

### Functional Requirements

- **FR-001**: Define and maintain a catalog of fixed-format EVALUATE variants (single subject, multiple subjects with ALSO, EVALUATE TRUE/FALSE, ANY, THRU/THROUGH ranges, nested cases) with clear descriptions and acceptance expectations.
- **FR-002**: The parser MUST successfully parse every cataloged variant in fixed-format layout and produce a consistent structural representation that preserves selectors, ranges, and WHEN clauses.
- **FR-003**: The parser MUST validate fixed-format column rules for EVALUATE statements (indicator and area bounds, continuation handling) and surface deterministic diagnostics when violations occur.
- **FR-004**: Provide positive test fixtures that cover each cataloged variant with expected serialized output to prove support.
- **FR-005**: Provide negative test fixtures that cover malformed EVALUATE scenarios (missing WHEN, misaligned continuations, invalid range syntax, mixed selector types) with expected diagnostics and locations.
- **FR-006**: Generate a variant coverage report that highlights supported vs. missing EVALUATE variants and fails when any cataloged variant lacks passing positive and negative tests.

### Key Entities *(include if feature involves data)*

- **EVALUATE Variant Catalog**: List of recognized fixed-format EVALUATE forms with attributes such as subject count, selector types (literal, identifier, ANY, TRUE/FALSE), range usage, and nesting notes.
- **Test Fixture**: A source snippet tied to a specific variant, including expected structural representation or expected diagnostic.
- **Diagnostic Record**: Human-readable message with location references and category (formatting, syntax, unsupported construct) produced during parsing.

### Assumptions

- Focus is on fixed-format COBOL; free-format coverage is out of scope for this feature.
- The existing parser can already serialize structures and diagnostics; this effort expands variant coverage and tests without altering user-facing APIs.
- IBM Enterprise COBOL conventions guide the variant catalog (e.g., use of ALSO, THRU/THROUGH, figurative constants).

## Success Criteria *(mandatory)*

<!--
  ACTION REQUIRED: Define measurable success criteria.
  These must be technology-agnostic and measurable.
-->

### Measurable Outcomes

- **SC-001**: 100% of cataloged fixed-format EVALUATE variants have passing positive tests that assert the expected structural representation.
- **SC-002**: 100% of cataloged malformed EVALUATE scenarios emit the documented diagnostic with correct line/column references and no parser crashes.
- **SC-003**: Variant coverage report shows no gaps (0 unsupported catalog entries) before release.
- **SC-004**: Parser ingestion of fixed-format COBOL programs containing EVALUATE statements succeeds in at least 99% of sampled legacy sources used for validation.
