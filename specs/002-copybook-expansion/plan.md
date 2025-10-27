# Implementation Plan: Nested Copybook Expansion

**Branch**: `002-copybook-expansion` | **Date**: 2025-10-27 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-copybook-expansion/spec.md`

**Note**: This plan is filled in by the `/speckit.plan` command and includes research, data model, and contract generation.

## Summary

Implement a standalone copybook expansion function that resolves COBOL COPY statements by inlining copybook content from the filesystem. The solution handles nested copybooks recursively, detects circular references, validates paths against directory traversal attacks, normalizes path separators for cross-platform compatibility, and auto-detects file encodings. Integration with the existing parser via `parse_cobol_with_expansion()` enables end-to-end parsing of programs with copybook dependencies.

**MVP (P1)**: Basic copybook expansion with simple COPY statements
**Phase 2 (P2-P4)**: Nested resolution, source location preservation, advanced features

## Technical Context

**Language/Version**: Python 3.13+ (mandatory per project constitution)  
**Primary Dependencies**: None (pure Python, dependency-free per constitution)  
**Storage**: Local filesystem (copybook files)  
**Testing**: pytest with 81%+ coverage requirement (mandatory per constitution)  
**Target Platform**: Cross-platform (Windows/Linux/macOS)  
**Project Type**: Single library module extending existing parser  
**Performance Goals**: <100ms for typical programs (5-15 copybooks), <1s for circular detection  
**Constraints**: Maximum 100 levels nesting depth, auto-encoding detection, path traversal prevention  
**Scale/Scope**: Support enterprise COBOL with real-world copybook patterns

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**Status: ✅ PASS** - Feature aligns with all COBOL Parser constitution principles:

| Principle | Requirement | Status | Notes |
|-----------|-------------|--------|-------|
| **I. TDD (NON-NEGOTIABLE)** | Tests written first, 81%+ coverage, contract tests for APIs | ✅ PASS | Feature spec includes 16 acceptance scenarios; will require comprehensive unit + integration + contract tests |
| **II. IBM Enterprise COBOL** | IBM dialect priority, COPY REPLACING support | ✅ PASS | FR-017 handles COPY REPLACING; all standard IBM COPY syntax supported |
| **III. JSON Serialization** | CopybookExpansion/SourceLocationMap must have `to_dict()` | ✅ PASS | Data model designed for JSON export (FR-015) |
| **IV. Memory Management** | Efficient handling, configurable limits, streaming | ✅ PASS | Max 100 nesting levels (FR-010), performance <100ms target (SC-005) |
| **V. Python 3.13+** | Modern features, type hints, dataclasses, enums | ✅ PASS | Explicit in Technical Context (Python 3.13+) |
| **VI. API Contracts** | Contract tests for public APIs | ✅ PASS | `expand_copybooks()` and `parse_cobol_with_expansion()` require contract tests |
| **VII. Code Quality** | Ruff/Black/Mypy, docstrings, no unused imports | ✅ PASS | Standard for all features; will enforce during implementation |

**Gate Result**: All principles compatible. No violations. Proceed to Phase 0.

## Project Structure

### Documentation (this feature)

```text
specs/002-copybook-expansion/
├── plan.md              # This file (/speckit.plan output)
├── research.md          # Phase 0 output - research findings
├── data-model.md        # Phase 1 output - entities and relationships
├── quickstart.md        # Phase 1 output - usage examples
├── contracts/           # Phase 1 output - API contracts
│   └── expand_copybooks.yaml
├── spec.md              # Feature specification (completed)
├── checklists/
│   └── requirements.md  # Quality validation
└── tasks.md             # Phase 2 output (/speckit.tasks - NOT created by this command)
```

### Source Code (repository root)

```text
cobolparser/
├── __init__.py
├── preprocess.py        # NEW: Copybook expansion module
│   ├── copybook_expander.py          # Core expansion logic
│   ├── copy_statement_parser.py       # Parse COPY statements
│   └── path_resolver.py              # Path resolution with validation
├── lexer.py             # Existing lexer (used by expander)
├── parser.py            # Existing parser (used by integration function)
└── [existing modules]

tests/
├── unit/
│   └── test_copybook_expansion.py    # Unit tests for expansion logic
├── integration/
│   └── test_copybook_expansion_integration.py
├── contracts/
│   └── test_copybook_expansion_contracts.py
└── samples/
    ├── copybook_programs/            # Test COBOL programs
    ├── copybooks/                    # Test copybook files
    └── mixed_encodings/              # Test encoding handling
```

**Structure Decision**: Single library module (Option 1) - Copybook expansion is a preprocessing layer integrated into the existing parser. No separate projects needed; module extends cobolparser with new preprocessing functions that integrate into existing parser pipeline.

## Complexity Tracking

> **No Constitution violations detected. Feature is straightforward preprocessing task with clear scope.**

Feature is SIMPLE - no complexity justifications needed:
- Pure Python implementation (standard for project)
- No additional external dependencies (maintains zero-dependency goal)
- Straightforward file I/O and text processing
- Clear error handling requirements
- No architectural complexity beyond recursive file reading

---

## Phase 0: Research & Unknowns Resolution

**Gate Status**: ✅ PASS (no critical unknowns - all clarifications completed in speckit.clarify)

### Research Tasks Completed

All technical decisions have been made during spec clarification:

1. ✅ **Path Traversal Security**: Use path validation to restrict to search directories
2. ✅ **Duplicate Handling**: Expand each COPY independently (standard COBOL behavior)
3. ✅ **Empty Copybooks**: Treat as valid (expand to empty content)
4. ✅ **Encoding Handling**: Auto-detect and convert to UTF-8
5. ✅ **Path Normalization**: Normalize to OS-native format automatically

### No Research.md Needed

Since all clarifications are resolved, Phase 0 can be skipped. Proceed directly to Phase 1 design.

---

## Phase 1: Design & Data Model

### Data Model Entities

**CopybookExpansion** (result of expansion)
- `expanded_source: str` - Complete expanded COBOL source
- `included_copybooks: List[str]` - Paths to all copybooks that were included
- `max_depth_reached: int` - Maximum nesting depth encountered
- `source_location_map: Optional[Dict[int, Tuple[str, int]]]` - Line → (file, line_number)
- `statistics: ExpansionStatistics` - Performance metrics

**CopyStatement** (parsed COPY statement)
- `member_name: str` - Copybook member name
- `library_qualifier: Optional[str]` - Optional library name (IN/OF)
- `replacing_clauses: Optional[List[Tuple[str, str]]]` - Text replacement pairs
- `source_location: SourceLocation` - Where in source file

**CopybookSearchPath** (configuration)
- `directories: List[str]` - Search directories (ordered)
- `extensions: List[str]` - File extensions to try
- `case_sensitive: bool` - Platform-specific path handling
- `max_nesting_depth: int` - Circular reference limit

**ExpansionContext** (internal state during recursion)
- `current_file: str` - File being processed
- `expansion_stack: List[str]` - Stack for circular reference detection
- `source_maps: Dict[int, Tuple[str, int]]` - Accumulated source location maps

### Key Validations (from FR)

- **Path Traversal (FR-014)**: All paths must resolve within search directories
- **Empty Copybooks (FR-012)**: Valid, expand to empty string
- **Encoding (FR-013)**: Auto-detect per file, convert to UTF-8 internally
- **Nesting Limits (FR-010)**: Max 100 levels (configurable)
- **Circular References (FR-005)**: Detect and report with chain

### API Contracts

**Primary Function**:
```python
def expand_copybooks(
    source_code: str,
    copybook_paths: List[str],
    max_nesting_depth: int = 100,
    preserve_source_locations: bool = False,
) -> CopybookExpansion
```

**Integration Function**:
```python
def parse_cobol_with_expansion(
    source_code: str,
    filename: str,
    copybook_paths: List[str],
) -> ParseResult
```

**Exception Types**:
- `CircularReferenceError` - Copybook cycle detected
- `CopybookNotFoundError` - Copybook file not found
- `PathTraversalError` - Attempted path escape detected
- `EncodingError` - Failed to detect/convert encoding
- `NestingDepthError` - Exceeded max nesting depth

### Testing Strategy

**Unit Tests** (test_copybook_expansion.py):
- COPY statement parsing (all syntax variants)
- Path resolution and validation
- Encoding detection/conversion
- Empty copybook handling
- File I/O error cases

**Integration Tests** (test_copybook_expansion_integration.py):
- End-to-end expansion of real COBOL programs
- Nested copybooks (3+ levels)
- Circular reference detection
- Integration with parser
- Mixed encoding scenarios

**Contract Tests** (test_copybook_expansion_contracts.py):
- Function signatures
- Return types
- Exception behavior
- API stability
- Source location mapping accuracy

---

## Phase 2: Task Generation

Phase 2 tasks will be generated by `/speckit.tasks` command.
Task organization by priority:
- **Phase 1 (Setup)**: Project structure, base classes, error types
- **Phase 2 (Foundation)**: Path validation, file I/O, basic COPY parsing
- **Phase 3 (P1 Story)**: Basic expansion implementation
- **Phase 4 (P2 Story)**: Nested resolution
- **Phase 5 (P3 Story)**: Circular reference detection
- **Phase 6 (P4 Story)**: Source location tracking
- **Phase 7 (Polish)**: COPY REPLACING, edge cases, documentation
