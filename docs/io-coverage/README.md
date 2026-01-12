# IO Coverage Documentation

This directory contains documentation and resources for the IO coverage reporting system.

## Overview

The IO coverage system provides machine-readable artifacts that track which IBM Enterprise COBOL IO variations have been tested and which are missing coverage.

## Files

- `README.md` - This file
- `artifact-schema.md` - Documentation of the coverage artifact JSON schema
- `variation-catalog.md` - Documentation of the IO variation catalog

## Quick Start

### Generate Coverage Artifact

```bash
# Run IO tests and capture results
python -m pytest tests/unit/io_statements tests/integration/io_statements --json=results.json

# Generate coverage artifact
python -m cobolparser.cli.coverage generate --pytest-results results.json --output io-coverage.json

# Or use the standalone tool
python tools/io_coverage/generate_artifact.py --pytest-results results.json --output io-coverage.json
```

### View Coverage Status

```bash
# Show all coverage status
python -m cobolparser.cli.coverage status

# Filter by verb
python -m cobolparser.cli.coverage status --verb READ

# Filter by qualifier
python -m cobolparser.cli.coverage status --qualifier "INVALID KEY"
```

### Validate Artifact

```bash
# Validate against schema
python -m cobolparser.cli.coverage validate --artifact io-coverage.json

# Or use standalone validator
python scripts/validate_io_coverage.py --artifact io-coverage.json
```

### Render Reports

```bash
# Render as Markdown
python -m cobolparser.cli.coverage render --input io-coverage.json --output coverage-report.md

# Render as CSV
python -m cobolparser.cli.coverage render --input io-coverage.json --output coverage-report.csv --format csv

# Print summary to console
python -m cobolparser.cli.coverage render --input io-coverage.json --format summary
```

## Artifact Structure

The coverage artifact (`io-coverage.json`) has the following structure:

```json
{
  "version": "1.0.0",
  "generated_at": "2024-01-15T10:30:00Z",
  "parser_version": "1.0.0",
  "total_variations": 64,
  "covered_variations": 40,
  "partial_variations": 5,
  "gap_variations": 19,
  "coverage_percent": 62.5,
  "variations": [
    {
      "id": "OPEN-INPUT-SEQUENTIAL",
      "verb": "OPEN",
      "organization": "SEQUENTIAL",
      "access_mode": "INPUT",
      "qualifiers": "",
      "status": "covered",
      "requires_fd": false,
      "ibm_reference": "SC27-8949-30",
      "tests": [
        {
          "test_id": "tests/unit/io/test_open.py::test_open_input_sequential",
          "test_type": "unit",
          "status": "passed",
          "duration": 0.015
        }
      ],
      "notes": "Basic sequential file open"
    }
  ],
  "summary": {
    "OPEN": 7,
    "CLOSE": 5,
    "READ": 10,
    ...
  }
}
```

## Status Values

| Status | Description |
|--------|-------------|
| `covered` | All tests for this variation pass |
| `partial` | Some tests pass, some fail |
| `gap` | No tests exist for this variation |
| `unsupported` | Parser does not support this variation |

## For QA Leads

### Auditing Coverage Results

1. Generate the coverage artifact after running tests
2. Review the `variations` array for entries with status `gap`
3. Check the `tests` array for each variation to see which tests cover it
4. Use the `summary` section to see coverage by verb (IO statement type)

### Adding New Test Coverage

1. Identify gaps in the catalog (`status: "gap"`)
2. Create tests in the appropriate test directory:
   - Unit tests: `tests/unit/io_statements/`
   - Integration tests: `tests/integration/io_statements/`
   - Contract tests: `tests/contracts/io_statements/`
3. Name tests with the variation ID (e.g., `test_OPEN_INPUT_SEQUENTIAL`)
4. Regenerate the artifact to see updated coverage

## CI/CD Integration

Add to your CI pipeline:

```yaml
- name: Run IO Tests
  run: |
    python -m pytest tests/unit/io_statements tests/integration/io_statements --json=results.json

- name: Generate Coverage Artifact
  run: |
    python tools/io_coverage/generate_artifact.py --pytest-results results.json --output io-coverage.json

- name: Validate Coverage Artifact
  run: |
    python scripts/validate_io_coverage.py --artifact io-coverage.json
```

## Related Documentation

- [IBM Enterprise COBOL IO Statement Reference](docs/io-statements.md)
- [Statement Test Coverage Matrix](docs/STATEMENT_TEST_COVERAGE_MATRIX.md)
- [IO Variation Catalog](../../specs/001-io-variation-coverage/io-variation-catalog.csv)
