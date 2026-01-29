# Documentation Archive Index

**Archive Date**: 2026-01-29  
**Archive Version**: 1.0.0  
**Retention Period**: 7 years (until 2033-01-29)  
**Compliance Standard**: ISO 15489

## Overview

This archive contains documentation that has been superseded by current implementations or reached milestone completion. All files are preserved for compliance, audit trails, and historical reference.

## Quick Navigation

| Category | Count | Location |
|----------|-------|----------|
| Coverage Reports | 4 | `2026-01-29/coverage_reports/` |
| Metrics & Baselines | 2 | `2026-01-29/metrics/` |
| **Total** | **6** | See details below |

## Archived Files

### Coverage Reports (2026-01-29/coverage_reports/)

#### 1. EVALUATE_COVERAGE.md
- **Archive ID**: ARCH-001
- **Original Location**: `docs/EVALUATE_COVERAGE.md`
- **Archive Reason**: Completed implementation
- **Completion Status**: 100%
- **Completion Date**: 2026-01-11
- **Test Count**: 51 tests (20 positive + 16 negative + 15 coverage gate)
- **Description**: Complete coverage report for EVALUATE statement implementation including all variants, diagnostics, and regression gates.
- **Replacement Reference**: See `docs/complete-program.md` for current EVALUATE examples

#### 2. STATEMENT_COVERAGE_GAP_ANALYSIS.md
- **Archive ID**: ARCH-002
- **Original Location**: `docs/STATEMENT_COVERAGE_GAP_ANALYSIS.md`
- **Archive Reason**: Milestone reached
- **Completion Status**: 30% (13/43 statements)
- **Completion Date**: 2026-01-11
- **Description**: Comprehensive 42-week roadmap for COBOL statement coverage. Planning phase complete; execution tracked in project management system.
- **Replacement Reference**: Current status in `docs/README.md`

#### 3. STATEMENT_COVERAGE_SUMMARY.md
- **Archive ID**: ARCH-003
- **Original Location**: `docs/STATEMENT_COVERAGE_SUMMARY.md`
- **Archive Reason**: Milestone reached
- **Completion Status**: 29% (12/41 statements)
- **Completion Date**: 2026-01-11
- **Description**: Quick reference status document showing implementation progress by priority level.
- **Replacement Reference**: Current coverage status in `docs/README.md`

#### 4. STATEMENT_TEST_COVERAGE_MATRIX.md
- **Archive ID**: ARCH-004
- **Original Location**: `docs/STATEMENT_TEST_COVERAGE_MATRIX.md`
- **Archive Reason**: Milestone reached
- **Completion Status**: 27.4% (316/1,153 tests)
- **Completion Date**: 2026-01-11
- **Description**: Detailed TDD test tracking matrix with contract/integration/unit test breakdowns.
- **Replacement Reference**: Automated test reports via `pytest --cov`

### Metrics & Baselines (2026-01-29/metrics/)

#### 5. io_ticket_baseline.md
- **Archive ID**: ARCH-005
- **Original Location**: `docs/metrics/io_ticket_baseline.md`
- **Archive Reason**: Completed implementation
- **Completion Status**: 91.7% (233/254 tests)
- **Completion Date**: 2026-01-11
- **Description**: IO ticket tracking baseline for SC-004 success criteria (40% reduction target).
- **Replacement Reference**: Automated metrics via `tools/metrics/io_ticket_tracker.py`

#### 6. io-coverage/README.md
- **Archive ID**: ARCH-006
- **Original Location**: `docs/io-coverage/README.md`
- **Archive Reason**: Completed implementation
- **Completion Status**: 100%
- **Completion Date**: 2026-01-11
- **Description**: IO coverage system documentation covering 64 variations with CLI tools.
- **Replacement Reference**: CLI help: `python -m cobolparser.cli.coverage --help`

## Archive Structure

```
archived_docs/
├── archive_manifest.json          # Machine-readable metadata
├── ARCHIVE_INDEX.md               # This file
└── 2026-01-29/
    ├── coverage_reports/
    │   ├── EVALUATE_COVERAGE.md
    │   ├── STATEMENT_COVERAGE_GAP_ANALYSIS.md
    │   ├── STATEMENT_COVERAGE_SUMMARY.md
    │   └── STATEMENT_TEST_COVERAGE_MATRIX.md
    └── metrics/
        ├── io_ticket_baseline.md
        └── io-coverage/
            └── README.md
```

## Metadata Schema

Each archived file includes the following metadata in `archive_manifest.json`:

| Field | Description |
|-------|-------------|
| `id` | Unique archive identifier (ARCH-XXX) |
| `filename` | Original filename |
| `original_path` | Source location before archival |
| `archive_path` | Current location in archive |
| `archive_date` | ISO 8601 timestamp of archival |
| `archive_reason` | `completed_implementation` or `milestone_reached` |
| `completion_status` | Percentage or status at time of archival |
| `completion_date` | Date when feature/milestone was completed |
| `notes` | Additional context |
| `replacement_doc` | Where to find current information |
| `reviewed_by` | Approver of archival |
| `approval_status` | Current approval state |

## Audit Trail

| Date | Action | Description |
|------|--------|-------------|
| 2026-01-29 | Archive Created | Initial archival of completed documentation |

## Accessing Archived Content

### For Compliance Audits
All archived files are preserved in their original format with complete metadata. The `archive_manifest.json` provides machine-readable access for automated compliance checking.

### For Historical Reference
Browse the date-stamped directories (e.g., `2026-01-29/`) to view documentation as it existed at that time.

### For Current Information
Refer to the `replacement_doc` field in each archive entry for pointers to current documentation.

## Retention Policy

- **Retention Period**: 7 years from archive date
- **Retention Until**: 2033-01-29
- **Standard**: ISO 15489 (Records Management)
- **Review Cycle**: Annual review for continued retention necessity

## Contact

For questions about archived documentation or to request restoration of a specific document, refer to the project governance documentation in `.specify/memory/constitution.md`.
