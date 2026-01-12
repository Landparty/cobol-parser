# Data Model — IO Variation Coverage

## Entity Overview

| Entity | Purpose | Notes |
|--------|---------|-------|
| `IOStatementVariation` | Canonical definition of a COBOL IO verb + qualifier combination derived from the IBM reference. | Serves as primary key for coverage tracking. |
| `IOTestFixture` | Source snippet + expected AST/diagnostic assertions used in TDD suites. | Links variations to concrete tests across contract/integration/unit layers. |
| `IOCoverageArtifact` | Machine-readable JSON/CSV record emitted by CI summarizing variation support, test references, and last execution status. | Consumed by dashboards and docs. |
| `IODialectProfile` | Captures dialect-specific toggles (IBM Enterprise COBOL today) that influence which variations must be present. | Enables future reuse for other dialects without redefining the matrix. |
| `IOErrorDiagnostic` | Structured info for negative tests (expected ParseError, line/column, recovery hints). | Embedded within fixtures and coverage artifact entries. |

## `IOStatementVariation`

| Field | Type | Description | Validation |
|-------|------|-------------|------------|
| `id` | `string` | Stable identifier, e.g., `READ-NEXT-WITH-LOCK-AT-END`. | Uppercase letters, digits, and dashes only; unique. |
| `verb` | `Literal["OPEN","CLOSE","READ","WRITE","REWRITE","DELETE","START","ACCEPT","DISPLAY","UNLOCK"]` | COBOL verb. | Required. |
| `file_organization` | `Literal["SEQUENTIAL","INDEXED","RELATIVE","VSAM","N/A"]` | Which FD organization is required. | Required; `N/A` allowed for ACCEPT/DISPLAY. |
| `access_mode` | `Literal["INPUT","OUTPUT","I-O","EXTEND","SEQUENTIAL","RANDOM","DYNAMIC","N/A"]` | OPEN/READ qualifiers. | Optional. |
| `qualifiers` | `List[Qualifier]` | Ordered list of clause flags (AT END, INVALID KEY, ADVANCING, WITH LOCK, KEY IS …). | Must match IBM catalog and fixed-format syntax rules. |
| `requires_fd_clauses` | `List[string]` | FD metadata (e.g., `RECORD KEY`, `ALTERNATE KEY`). | Used to validate fixture setup. |
| `metadata` | `Dict[str, Any]` | Allows annotations (e.g., `"requires-lock-mode": true`). | Optional but must serialize via `to_dict()`. |

Relationships: One `IOStatementVariation` can have many `IOTestFixture` records (positive and negative). Variations also point to zero or more `IODialectProfile` entries that declare applicability.

State Diagram:

```
UNSPECIFIED → PLANNED → TESTED → COVERED
                          ↘
                           GAP (if test fails)
```

- Initial import sets `UNSPECIFIED` until mapped to a variation.
- When TDD tests exist but fail, state is `GAP`.
- When all associated tests pass, state is `COVERED`.

## `IOTestFixture`

| Field | Type | Description |
|-------|------|-------------|
| `fixture_id` | `string` | Unique slug, e.g., `read-next-with-lock-positive`. |
| `variation_id` | `string` | FK → `IOStatementVariation.id`. |
| `category` | `Literal["unit","contract","integration"]` | Matches pytest markers/paths. |
| `source_path` | `string` | Path to COBOL sample or inline snippet file. |
| `expected_ast_node` | `string` | Fully qualified AST class name (e.g., `IOReadStatement`). |
| `expected_metadata` | `Dict[str, Any]` | Snapshot of AST fields to assert. |
| `expected_errors` | `List[IOErrorDiagnostic]` | Populated for negative fixtures. |
| `performance_tag` | `Literal["smoke","full","stress"]` | Helps orchestrate suite selections. |

Each fixture MUST reference at least one pytest test (link stored in coverage artifact). Fixtures enforce the red-green-refactor cycle: add fixture → write failing test → implement parser support.

## `IOCoverageArtifact`

| Field | Type | Description |
|-------|------|-------------|
| `schema_version` | `string` | Allows backward-compatible evolution. |
| `generated_at` | `datetime` | ISO 8601 timestamp (UTC). |
| `dialect_profile` | `string` | References `IODialectProfile.id`. |
| `variations` | `List[CoverageEntry]` | Embedded objects summarizing status per variation. |
| `baseline_metrics` | `Dict[str, Any]` | Stores runtime, memory, coverage percentages for comparison. |

`CoverageEntry` structure:
- `variation_id`
- `status` (`"covered" | "gap" | "missing"`)
- `last_run` timestamp
- `tests_passed / tests_failed`
- `links` (list of pytest node ids or documentation anchors)
- `notes` (optional, e.g., failing clause combos)

## `IODialectProfile`

| Field | Type | Description |
|-------|------|-------------|
| `id` | `string` | Example: `IBM-ENTERPRISE-COBOL`. |
| `version_range` | `string` | e.g., `"5.2+"`. |
| `required_variations` | `List[string]` | Variation IDs mandated for this dialect. |
| `optional_variations` | `List[string]` | Nice-to-have features tracked separately. |

Profiles allow the same infrastructure to target Micro Focus or GnuCOBOL later without refactoring the coverage matrix.

## `IOErrorDiagnostic`

| Field | Type | Description |
|-------|------|-------------|
| `code` | `string` | Parser error code or symbolic name. |
| `message` | `string` | Human-friendly text displayed in diagnostics. |
| `line` / `column` | `int` | 1-based positions from `SourceLocation`. |
| `recovery_hint` | `string` | Suggestion shown in COLLECT_ALL mode. |

Diagnostics are optional for positive fixtures but required when a test validates parser error behavior.

## Relationships & Integrity Rules

- Every `IOTestFixture` references exactly one `IOStatementVariation`; a variation must have ≥1 positive fixture and ≥1 negative fixture before being marked `COVERED`.
- `IOCoverageArtifact.variations[].status` is derived from the aggregate result of associated fixtures; manual overrides are forbidden.
- `IODialectProfile.required_variations` must be a subset of the master variation list and is validated during artifact generation.
- `IOErrorDiagnostic` entries embedded in fixtures must include both the user-facing message and the parser error code so existing tooling (e.g., `ParseStatistics`) can correlate them.

## Validation Workflow

1. **Catalog Sync**: Import IBM reference table → seed/refresh `IOStatementVariation` rows.
2. **Fixture Review**: For each new variation, create fixture skeletons referencing actual COBOL snippets and AST clauses.
3. **TDD Execution**: Write failing tests linked to fixtures, implement parser updates, confirm `IOCoverageArtifact` flips to `covered`.
4. **CI Enforcement**: Coverage job verifies schema, ensures no variation reverts from `covered` to `gap` without justification, and publishes diff summaries.

This model ensures we honor the existing parser framework while adding the observability and regressions controls requested in the spec.
