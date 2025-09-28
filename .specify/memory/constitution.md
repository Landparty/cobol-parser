<!--# [PROJECT_NAME] Constitution

Sync Impact Report:<!-- Example: Spec Constitution, TaskFlow Constitution, etc. -->

Version change: Template → 1.0.0 (Initial constitution)

Added principles:## Core Principles

- Test-First Development (NON-NEGOTIABLE)

- Comprehensive COBOL Coverage### [PRINCIPLE_1_NAME]

- Pythonic API Design<!-- Example: I. Library-First -->

- Error Handling & Validation[PRINCIPLE_1_DESCRIPTION]

- Extensibility Through Plugins<!-- Example: Every feature starts as a standalone library; Libraries must be self-contained, independently testable, documented; Clear purpose required - no organizational-only libraries -->

Added sections:

- Testing Standards### [PRINCIPLE_2_NAME]

- Development Workflow<!-- Example: II. CLI Interface -->

Templates requiring updates: ✅ Validated consistency[PRINCIPLE_2_DESCRIPTION]

Follow-up TODOs: None<!-- Example: Every library exposes functionality via CLI; Text in/out protocol: stdin/args → stdout, errors → stderr; Support JSON + human-readable formats -->

-->

### [PRINCIPLE_3_NAME]

# COBOL Parser Constitution<!-- Example: III. Test-First (NON-NEGOTIABLE) -->

[PRINCIPLE_3_DESCRIPTION]

## Core Principles<!-- Example: TDD mandatory: Tests written → User approved → Tests fail → Then implement; Red-Green-Refactor cycle strictly enforced -->



### I. Test-First Development (NON-NEGOTIABLE)### [PRINCIPLE_4_NAME]

Automated tests MUST be written and MUST pass for every release. TDD cycle strictly enforced: Tests written → Tests fail → Implementation → Tests pass. Code coverage MUST be tracked and aim for 90%+. All tests MUST pass before publishing or merging PRs. No exceptions.<!-- Example: IV. Integration Testing -->

[PRINCIPLE_4_DESCRIPTION]

**Rationale**: Testing ensures reliability and maintainability for enterprise COBOL modernization where errors can be costly.<!-- Example: Focus areas requiring integration tests: New library contract tests, Contract changes, Inter-service communication, Shared schemas -->



### II. Comprehensive COBOL Coverage### [PRINCIPLE_5_NAME]

Tests and examples MUST cover most current and commonly used COBOL syntax, including variations and edge cases. Parser MUST handle real-world COBOL programs, not just textbook examples. Support for all four COBOL divisions (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE) is mandatory.<!-- Example: V. Observability, VI. Versioning & Breaking Changes, VII. Simplicity -->

[PRINCIPLE_5_DESCRIPTION]

**Rationale**: COBOL has decades of syntax variations and enterprise codebases contain complex, real-world patterns that must be supported.<!-- Example: Text I/O ensures debuggability; Structured logging required; Or: MAJOR.MINOR.BUILD format; Or: Start simple, YAGNI principles -->



### III. Pythonic API Design## [SECTION_2_NAME]

Every feature MUST expose a clean, Pythonic API that feels natural to Python developers. Object model MUST represent COBOL structure as intuitive Python classes (Program, Division, Section, Paragraph, Statement). API design MUST prioritize ease of use over implementation convenience.<!-- Example: Additional Constraints, Security Requirements, Performance Standards, etc. -->



**Rationale**: Python developers should be able to work with COBOL parsing without learning COBOL intricacies.[SECTION_2_CONTENT]

<!-- Example: Technology stack requirements, compliance standards, deployment policies, etc. -->

### IV. Error Handling & Validation

System MUST provide clear error reporting for syntax errors, unsupported features, and ambiguous code. Custom exception classes MUST be used. Basic validation of structure and variable usage is required. Error messages MUST help users understand what went wrong and how to fix it.## [SECTION_3_NAME]

<!-- Example: Development Workflow, Review Process, Quality Gates, etc. -->

**Rationale**: COBOL parsing often encounters legacy code with inconsistencies; robust error handling is essential for practical usage.

[SECTION_3_CONTENT]

### V. Extensibility Through Plugins<!-- Example: Code review requirements, testing gates, deployment approval process, etc. -->

Architecture MUST support plugins and hooks to extend parsing or validation rules. Plugin system MUST allow adding new COBOL dialects, custom validation rules, and transformation capabilities without modifying core parser logic. Clear plugin API required.

## Governance

**Rationale**: COBOL has many vendor-specific extensions and enterprise-specific patterns that require customization.<!-- Example: Constitution supersedes all other practices; Amendments require documentation, approval, migration plan -->



## Testing Standards[GOVERNANCE_RULES]

<!-- Example: All PRs/reviews must verify compliance; Complexity must be justified; Use [GUIDANCE_FILE] for runtime development guidance -->

**Test Requirements**: Unit tests, integration tests, and example scripts MUST be maintained. Test suite MUST include real COBOL program samples, edge cases, and error scenarios. Performance testing required for large COBOL files (>10,000 lines). All tests MUST use pytest framework.

**Version**: [CONSTITUTION_VERSION] | **Ratified**: [RATIFICATION_DATE] | **Last Amended**: [LAST_AMENDED_DATE]

**Coverage Requirements**: Minimum 90% code coverage required. Critical parsing paths MUST have 100% coverage. Test data MUST include samples from different COBOL compilers and eras.<!-- Example: Version: 2.1.1 | Ratified: 2025-06-13 | Last Amended: 2025-07-16 -->

**Release Blocking**: No release if required tests fail. No merge if tests don't cover new functionality. Test execution MUST be automated in CI/CD pipeline.

## Development Workflow

**Code Structure**: Single Python package architecture with clear separation: parser logic, object model, error handling, utilities, and plugins. Follow Python package best practices (pyproject.toml, proper imports, documentation).

**Documentation**: README.md with installation and usage examples. Docstrings for all public classes and methods. API reference documentation required. Examples folder with real COBOL samples.

**Distribution**: PyPI publishing required (`pip install cobolparser`). Python 3.13+ compatibility required. Wheel and source distributions. Semantic versioning (MAJOR.MINOR.PATCH) based on API changes.

## Governance

Constitution supersedes all other development practices. All PRs and code reviews MUST verify compliance with these principles. Any complexity that violates principles MUST be explicitly justified with technical reasoning. 

Amendment procedure: Proposed changes MUST be documented, reviewed, and approved before implementation. Breaking changes to core principles require MAJOR version increment.

**Version**: 1.0.0 | **Ratified**: 2025-09-27 | **Last Amended**: 2025-09-27