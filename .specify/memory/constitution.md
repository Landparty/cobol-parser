<!--
Sync Impact Report - Constitution v1.0.0 Initial Ratification
==============================================================
Version Change: (none) → 1.0.0
Action: Initial constitution ratification for COBOL Parser project

Principles Established:
1. Test-Driven Development (TDD) - NON-NEGOTIABLE
2. IBM Enterprise COBOL Priority
3. JSON Serialization Contract
4. Memory Management & Performance
5. Python 3.13+ Modern Standards
6. API Contract Stability
7. Code Quality Standards

Templates Status:
✅ plan-template.md - Reviewed, constitution gates align with TDD and testing principles
✅ spec-template.md - Reviewed, requirements structure aligns with user story priority approach
✅ tasks-template.md - Reviewed, task categorization reflects TDD and independent testing principles
✅ agent-file-template.md - Reviewed, no constitution-specific updates needed
✅ checklist-template.md - Reviewed, no constitution-specific updates needed

Follow-up Actions:
- None - all placeholders resolved
- Constitution ready for use

Generated: 2025-10-26
-->

# COBOL Parser Constitution

## Core Principles

### I. Test-Driven Development (NON-NEGOTIABLE)

**TDD MUST be followed rigorously for all feature development:**

- Tests written FIRST → User approval → Tests FAIL → Then implement
- Red-Green-Refactor cycle strictly enforced
- Minimum 81% code coverage required (enforced via pytest --cov-fail-under=81)
- All new features MUST include comprehensive unit tests before implementation
- Tests demonstrate the feature's correctness, not just code execution

**Rationale**: With 618 tests (38 contract, 17 integration, 563 unit) providing 81%+ coverage, TDD ensures parser reliability for production COBOL codebases. Legacy COBOL systems require absolute correctness—parsing errors can break multi-million-line enterprise applications.

### II. IBM Enterprise COBOL Priority

**IBM Enterprise COBOL dialect features take precedence over ANSI COBOL:**

- COMP-3 packed decimal support with `calculate_storage_size()` implementations
- EXEC SQL embedded SQL blocks with host variable detection
- EXEC CICS transaction commands and API calls
- IBM intrinsic functions (LENGTH, NUMVAL, etc.) prioritized
- z/OS platform-specific extensions supported

**When choosing between ANSI COBOL and IBM Enterprise COBOL compatibility, IBM Enterprise COBOL wins.**

**Rationale**: The primary use case is parsing IBM mainframe COBOL programs. IBM Enterprise COBOL represents the vast majority of production COBOL code in Fortune 500 enterprises.

### III. JSON Serialization Contract

**All AST nodes MUST implement `to_dict()` for JSON export:**

- Every AST node class inherits from `ASTNode`
- Mandatory `to_dict() -> Dict[str, Any]` method implementation
- Must include: node_type, location (via SourceLocation), and all semantic properties
- Supports `SerializationConfig` for metadata and source location control
- Cross-platform interoperability is non-negotiable

**Rationale**: JSON export enables integration with analysis tools, IDEs, language servers, and cross-platform COBOL tooling. Modern development workflows require machine-readable AST formats.

### IV. Memory Management & Performance

**Parser MUST handle enterprise-scale COBOL programs efficiently:**

- Configurable memory limits (64MB minimum to 8GB maximum)
- Streaming support enabled for programs >1MB
- Chunked processing with configurable chunk sizes
- Performance monitoring via `ParseStatistics` (parse time, memory usage, tokens/sec)
- Token caching and lexer optimizations for large files

**Performance targets:**
- Small programs (<1MB): <100ms parse time
- Medium programs (1-10MB): 100ms-1s parse time
- Large programs (10MB+): 1-10s with streaming
- Memory usage: 2-5x source code size during parsing

**Rationale**: Enterprise COBOL programs can exceed 100,000 lines. Without proper memory management, the parser becomes unusable for real-world mainframe codebases.

### V. Python 3.13+ Modern Standards

**Code MUST leverage Python 3.13+ features exclusively:**

- Dataclasses for AST nodes and configuration objects
- Type hints (typing module) for all public APIs and internal functions
- Enums for state machines, error modes, and configuration options
- Pattern matching (match/case) where appropriate
- Modern error handling with specific exception types

**Type checking with mypy MUST pass with strict configuration (disallow_untyped_defs=true).**

**Rationale**: Python 3.13+ provides superior type safety, performance, and maintainability. The parser is a foundational library requiring long-term stability and clear contracts.

### VI. API Contract Stability

**Public API changes require contract tests to prevent breakage:**

- 38 contract tests validate API stability across versions
- All new public APIs MUST include contract tests before merge
- Breaking changes require MAJOR version bump (semantic versioning)
- Contract tests live in `tests/contracts/` and verify method signatures, return types, and behavior
- Integration tests (17 tests) validate end-to-end workflows

**Contract test requirements:**
- Method signature validation
- Return type verification
- Exception behavior documentation
- Backward compatibility checks for existing APIs

**Rationale**: The parser is used by analysis tools, IDEs, and automation systems. Breaking API changes cascade to downstream consumers. Contract tests provide compile-time guarantees.

### VII. Code Quality Standards

**All code MUST pass quality gates before merge:**

- **Ruff linting**: Zero errors, warnings addressed (E, W, F, I, B, C4, UP rules enabled)
- **Black formatting**: Automated formatting enforced (line-length=88, target-version=py313)
- **Mypy type checking**: Strict mode with no untyped definitions allowed
- **Docstrings**: All public functions/classes require docstrings
- **No unused imports/variables**: Enforced by ruff

**Quality gate command:** `ruff check . && black . && mypy cobolparser/`

**Rationale**: Consistent code quality reduces maintenance burden, improves collaboration, and prevents technical debt accumulation in a 1,400+ line parser codebase.

## Technical Constraints

### Two-Stage Parsing Pipeline

**Architecture is FIXED: Lexer → Parser → AST**

- **Lexer** (`lexer.py`): Tokenization with 75+ COBOL verb support, produces token stream
- **Parser** (`parser.py`): AST generation from token stream with error recovery
- **Models** (`models/`): AST node hierarchy with JSON serialization
- **Dialects** (`dialects/`): Dialect-specific extensions (IBM Enterprise COBOL)
- **Plugins** (`plugins/`): Memory config, error recovery, serialization

**State machine parsing:** Parser uses `ParseState` enum to track division/section context (IDENTIFICATION_DIVISION → DATA_DIVISION → PROCEDURE_DIVISION).

**This architecture MUST NOT be bypassed or replaced without a major version bump and architectural review.**

### Error Recovery Modes

**Two error recovery modes are supported:**

1. **FAIL_FAST** (production default): Stop parsing on first critical error
2. **COLLECT_ALL** (development/debugging): Collect all errors and continue parsing

**Error recovery mode MUST be configurable via `ErrorRecoveryMode` enum.**

**Rationale**: Production systems need fail-fast behavior for safety. Development workflows benefit from seeing all errors at once for comprehensive debugging.

### Dependency-Free Design

**The parser MUST remain dependency-free (pure Python):**

- No external dependencies in core parser (`cobolparser/`)
- Development dependencies (pytest, ruff, black, mypy) are acceptable in `[dev]` extras
- Documentation dependencies (sphinx) are acceptable in `[docs]` extras

**Rationale**: Minimizes supply chain risk, simplifies deployment, and ensures the parser can be embedded in restricted environments.

## Development Workflow

### Feature Development Process

1. **Specification Phase**: Create feature spec in `/specs/[###-feature-name]/spec.md` with user stories and acceptance criteria
2. **Test Design Phase**: Write failing tests that demonstrate the feature (TDD red phase)
3. **User Approval**: Confirm tests represent desired behavior before implementation
4. **Implementation Phase**: Implement feature to pass tests (TDD green phase)
5. **Refactoring Phase**: Clean up code while maintaining passing tests (TDD refactor phase)
6. **Contract Test Phase**: Add contract tests for any new public APIs
7. **Documentation Phase**: Update README, docstrings, and `/docs/` examples

### Required Test Categories

- **Unit tests** (`tests/unit/`): Component-specific functionality (lexer, parser, models)
- **Integration tests** (`tests/integration/`): End-to-end workflows with real COBOL programs
- **Contract tests** (`tests/contracts/`): API stability validation (REQUIRED for new APIs)

### Code Review Requirements

Before merge, ALL of the following MUST pass:

- [ ] `python -m pytest tests/ -v` (618 tests passing)
- [ ] `python -m pytest --cov=cobolparser --cov-fail-under=81` (81%+ coverage)
- [ ] `ruff check .` (zero errors)
- [ ] `black .` (formatting applied)
- [ ] `mypy cobolparser/` (type checking passes)
- [ ] Contract tests added for new public APIs
- [ ] Documentation updated (README, docstrings, examples)

## Governance

### Amendment Process

1. **Proposal**: Open GitHub issue tagged `constitution-amendment` with rationale
2. **Discussion**: Allow 7-day comment period for stakeholder input
3. **Approval**: Requires maintainer consensus (2+ maintainer approvals)
4. **Version Bump**: Update constitution version per semantic versioning rules:
   - **MAJOR**: Backward incompatible governance/principle removals or redefinitions
   - **MINOR**: New principle/section added or materially expanded guidance
   - **PATCH**: Clarifications, wording, typo fixes, non-semantic refinements
5. **Migration Plan**: Document impact on existing code and required changes
6. **Sync Templates**: Update all templates in `.specify/templates/` to reflect changes

### Compliance Reviews

- All pull requests MUST include a constitution compliance checklist
- Quarterly reviews of constitution effectiveness (tracked in GitHub Discussions)
- Annual review to ensure principles still serve project goals

### Complexity Justification

Violations of constitution principles (e.g., adding external dependencies, reducing test coverage, breaking API contracts) MUST be justified in writing with:

- **Why Needed**: Specific technical/business reason
- **Alternatives Considered**: Why simpler approaches were rejected
- **Mitigation Plan**: How to minimize impact and technical debt

Unjustified violations are rejected during code review.

### Runtime Guidance

For detailed development patterns, examples, and implementation guidance, refer to `.github/copilot-instructions.md`. The constitution defines **what** must be done; the copilot instructions define **how** to do it.

**Version**: 1.0.0 | **Ratified**: 2025-10-26 | **Last Amended**: 2025-10-26
