<!--
Sync Impact Report (Version 1.0.0 → Created 2026-01-11)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VERSION CHANGE: Initial Constitution v1.0.0 (MAJOR)
RATIONALE: First formal governance document for COBOL Parser project

PRINCIPLES ESTABLISHED:
  1. Test-First Development (TDD) - Mandatory red-green-refactor cycle
  2. Code Quality Standards - 90%+ coverage, type safety, documentation
  3. Performance Requirements - Memory efficiency and parsing speed targets
  4. User Experience Consistency - Predictable APIs and error handling
  5. IBM Enterprise COBOL Priority - Dialect-specific support commitment

TEMPLATES REQUIRING UPDATES:
  ✅ plan-template.md - Constitution Check section aligns with 5 principles
  ✅ spec-template.md - Functional requirements structure supports constitution
  ✅ tasks-template.md - Task organization reflects TDD and testing phases
  ✅ copilot-instructions.md - Runtime guidance references constitution principles

FOLLOW-UP TODOS: None - all required sections complete

COMMIT MESSAGE SUGGESTION:
  docs: establish constitution v1.0.0 (code quality, testing, performance, UX)
  
  - Define 5 core principles for project governance
  - Establish TDD as non-negotiable development practice
  - Set 90%+ test coverage and performance requirements
  - Formalize IBM Enterprise COBOL dialect priority
  - Create amendment and compliance review process

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
-->

# COBOL Parser Project Constitution

## Core Principles

### I. Test-First Development (TDD) - NON-NEGOTIABLE

Test-Driven Development is the mandatory development workflow for all features and bug fixes:

- **Red-Green-Refactor Cycle MUST Be Followed**: Write failing test → implement minimal code to pass → refactor for quality
- **Tests Written Before Implementation**: All new features require test cases written and approved before production code
- **Test Categories Required**:
  - **Contract Tests**: API stability and backward compatibility (MUST exist for all public interfaces)
  - **Integration Tests**: End-to-end workflows and cross-component interactions
  - **Unit Tests**: Component-level logic verification and edge cases
- **No Code Merges Without Tests**: Pull requests without corresponding test coverage MUST be rejected
- **Test Organization**: Follow structure `tests/{contract,integration,unit}/` with clear naming conventions

**Rationale**: TDD ensures reliability, prevents regressions, and creates living documentation. COBOL modernization projects require absolute parser correctness—bugs in parsing can corrupt migration projects affecting millions of lines of legacy code.

### II. Code Quality Standards

All code MUST meet minimum quality thresholds before merge:

- **Test Coverage**: 90%+ for new code (measured via `pytest --cov`), with focus on parser core (57%+ baseline established)
- **Type Safety**: Python 3.13+ type hints required for all functions, methods, and class attributes (enforced via `mypy`)
- **Code Formatting**: Automated formatting via `black` (line length 100) and linting via `ruff` with zero violations
- **Documentation Requirements**:
  - Every public class and method MUST have docstrings (Google style)
  - Complex algorithms MUST include inline comments explaining logic
  - AST node classes MUST document their `to_dict()` serialization format
- **Code Review Gates**: All PRs require:
  - Passing CI checks (tests, coverage, linting, type checking)
  - At least one approving review from maintainer
  - Changelog entry if user-facing change

**Rationale**: High code quality reduces maintenance burden and increases contributor confidence. Type safety prevents runtime errors in production parsing workflows. Comprehensive documentation enables community contributions and long-term maintainability.

### III. Performance Requirements

The parser MUST maintain performance characteristics suitable for enterprise-scale COBOL codebases:

- **Memory Efficiency**:
  - Configurable memory limits from 64MB (small files) to 8GB (massive programs)
  - Streaming mode MUST be available for files exceeding 1MB source size
  - Memory monitoring MUST track peak usage and emit warnings at 80% threshold
- **Parsing Speed**:
  - Target: 10,000+ lines/second on modern hardware (baseline: i5-8th gen, 16GB RAM)
  - Large file optimization: Enable token caching for programs exceeding 50,000 lines
  - Lexer performance: Tokenization MUST NOT exceed 30% of total parse time
- **Benchmarking Required**:
  - All performance-impacting changes MUST include benchmark results
  - Regression tests for performance degradation (>10% slowdown triggers review)
  - Real-world COBOL samples from 1,000 to 100,000 lines used for validation

**Rationale**: Legacy COBOL systems contain programs ranging from hundreds to hundreds of thousands of lines. Enterprise migration projects process millions of lines in batch—parser efficiency directly impacts project timelines and infrastructure costs.

### IV. User Experience Consistency

Public APIs and error handling MUST provide predictable, developer-friendly interfaces:

- **API Design**:
  - **Principle of Least Surprise**: Method names and parameters follow Python conventions (PEP 8)
  - **Sensible Defaults**: `CobolParser()` works out-of-box for 80% use cases
  - **Progressive Disclosure**: Simple usage requires no configuration; advanced needs accessible via explicit options
  - **Semantic Versioning**: MAJOR.MINOR.PATCH strictly enforced (breaking changes → MAJOR bump)
- **Error Handling**:
  - **Error Recovery Modes**: `FAIL_FAST` (production) vs `COLLECT_ALL` (debugging) clearly documented
  - **Detailed Error Messages**: Include line number, column, offending token, and recovery suggestion
  - **Error Categories**: Lexical errors vs parse errors vs semantic errors clearly distinguished
  - **Statistics Tracking**: `ParseStatistics` object provides transparency into warnings, errors, recovered vs fatal issues
- **JSON Export**:
  - **Cross-Platform Compatibility**: AST serialization uses standard JSON (no Python-specific types)
  - **Metadata Control**: `SerializationConfig` allows users to include/exclude source locations, metadata
  - **Schema Stability**: JSON schema versioned independently; breaking changes communicated via changelog

**Rationale**: Parser users range from one-time analysts to enterprise automation engineers. Consistent UX reduces onboarding friction and support burden. Clear error messages enable self-service debugging, reducing maintainer support load.

### V. IBM Enterprise COBOL Priority

IBM Enterprise COBOL dialect receives priority support and optimization:

- **Dialect-Specific Features**:
  - **COMP-3 Packed Decimal**: Full support including `calculate_storage_size()` for binary storage analysis
  - **EXEC SQL Blocks**: Embedded SQL statement preservation with dialect-aware parsing
  - **EXEC CICS Blocks**: Transaction processing commands (SEND, RECEIVE, READ, WRITE, etc.)
  - **IBM Intrinsic Functions**: LENGTH, NUMVAL, CURRENT-DATE, and other enterprise-specific built-ins
- **Dialect Architecture**:
  - `cobolparser/dialects/ibm_enterprise.py` module encapsulates IBM-specific logic
  - Plugin system allows third-party dialects without core parser changes
  - Dialect detection via compiler directives (e.g., `PROCESS` statements) or explicit configuration
- **Testing Requirements**:
  - Real-world IBM Enterprise COBOL samples MUST be included in test suite (`tests/samples/ibm/`)
  - Regression tests for IBM-specific features before each release
  - Community-contributed IBM COBOL programs prioritized for compatibility testing

**Rationale**: IBM COBOL dominates enterprise mainframe environments (banks, insurance, government). Supporting this dialect maximizes project impact and adoption. Maintaining dialect separation preserves extensibility for other COBOL variants (Micro Focus, GNU COBOL, etc.).

## Development Workflow

### Code Contribution Process

1. **Issue/Feature Discussion**: Propose changes in GitHub Issues before implementation
2. **Branch Naming**: `feature/###-description`, `bugfix/###-description`, `docs/###-description`
3. **TDD Workflow**:
   - Write failing test(s) covering new behavior
   - Implement minimal code to pass tests
   - Refactor for quality, maintainability, performance
   - Update documentation and changelog
4. **Pull Request Requirements**:
   - Pass all CI checks (618+ tests, 90%+ coverage, linting, type checking)
   - Include test evidence (test names and results)
   - Link to original issue
   - One approval from core maintainer required
5. **Review Focus Areas**:
   - **Correctness**: Does it parse valid COBOL correctly? Does it reject invalid syntax appropriately?
   - **Backward Compatibility**: Does it break existing AST structure or public APIs?
   - **Performance**: Does it introduce memory leaks or parsing slowdowns?
   - **Test Coverage**: Are edge cases covered? Are error conditions tested?

### Release Process

1. **Version Bump Decision**:
   - MAJOR: Breaking AST structure changes, public API removals, minimum Python version increase
   - MINOR: New COBOL features supported, new public APIs added, performance improvements
   - PATCH: Bug fixes, documentation updates, dependency updates
2. **Pre-Release Checklist**:
   - All tests passing on Python 3.13 and 3.14 (if available)
   - Coverage meets 90%+ threshold
   - Changelog updated with user-facing changes
   - Migration guide written for breaking changes (MAJOR releases only)
3. **Post-Release**:
   - Git tag `vMAJOR.MINOR.PATCH`
   - PyPI package published
   - GitHub release with changelog excerpt

### Quality Gates (Non-Negotiable)

- **Pre-Commit**: Local tests pass (`pytest tests/`)
- **Pre-Push**: Full test suite passes including integration tests
- **Pre-Merge**: CI checks green + code review approval
- **Pre-Release**: Performance benchmarks meet targets, documentation complete

## Performance Standards

### Baseline Requirements

All performance targets measured on reference hardware: Intel i5-8th gen, 16GB RAM, SSD storage.

| Metric | Target | Measurement Method |
|--------|--------|-------------------|
| Parsing Speed | 10,000+ lines/sec | `tests/performance/benchmark_parser.py` |
| Memory Efficiency | <256MB for 50K line program | Memory monitor peak usage |
| Lexer Overhead | <30% of total parse time | `ParseStatistics.lexer_time_ms` |
| JSON Export Time | <5% of parse time | `SerializationConfig` benchmarks |
| Token Cache Hit Rate | >80% for repeated parses | Token cache statistics |

### Performance Degradation Policy

- **>10% Slowdown**: Requires explicit justification in PR description with mitigation plan
- **>25% Slowdown**: Automatic PR rejection unless critical bug fix
- **Memory Leaks**: Zero tolerance—any detected leak blocks merge
- **Regression Testing**: Performance benchmarks run on every merge to main branch

## Security & Compliance

### Security Considerations

- **Input Validation**: Parser MUST handle malformed/malicious COBOL without crashes or hangs
- **Resource Limits**: Memory and recursion depth limits prevent denial-of-service via crafted input
- **Dependency Security**: Monthly automated scans for vulnerable dependencies (Dependabot enabled)
- **Error Message Sanitization**: No source code fragments in error messages when handling untrusted input (configurable)

### Compliance Requirements

- **License**: MIT License maintained for maximum adoption (no copyleft restrictions)
- **Attribution**: Third-party code inclusions require proper attribution in NOTICE file
- **Export Compliance**: No encryption features; parser suitable for unrestricted distribution
- **Data Privacy**: Parser processes code only; no telemetry or user data collection

## Governance

### Constitutional Authority

This constitution supersedes all other project practices and conventions. In case of conflict between this document and:

- **README.md**: Constitution takes precedence for governance/process
- **Code Comments**: Constitution takes precedence for architectural decisions
- **Historical Practices**: Constitution takes precedence (document migration plan in changelog)

### Amendment Process

1. **Proposal**: Open GitHub Issue tagged `constitution-amendment` with rationale
2. **Discussion**: Minimum 7-day community feedback period
3. **Approval**: Requires consensus from 2+ core maintainers
4. **Documentation**: Amendment changelog entry required
5. **Version Bump**: MINOR bump for new principles/sections, PATCH bump for clarifications
6. **Migration Plan**: MAJOR constitutional changes require 30-day transition period with deprecation warnings

### Compliance Review

- **Pull Request Review**: All PRs reviewed for constitutional compliance (see Development Workflow section)
- **Quarterly Audits**: Every 3 months, maintainers review codebase for drift from constitutional principles
- **Violation Handling**:
  - Non-compliant code identified in audits: Create issue, assign to original author or maintainer
  - Persistent violations: Escalate to core maintainers for architectural review
  - Exceptions: Documented in `EXCEPTIONS.md` with explicit justification and sunset date

### Project Structure Reference

Project documentation and workflows align with this constitution:

- **Development Guidance**: See `.github/copilot-instructions.md` for runtime development patterns
- **Specification Templates**: `.specify/templates/spec-template.md` for feature requirements structure
- **Planning Templates**: `.specify/templates/plan-template.md` for implementation planning
- **Task Templates**: `.specify/templates/tasks-template.md` for TDD-aligned task breakdown
- **Testing Documentation**: `docs/` directory contains comprehensive API and dialect guides

---

**Version**: 1.0.0 | **Ratified**: 2026-01-11 | **Last Amended**: 2026-01-11
