
# Implementation Plan: COBOL Parser for Python

**Branch**: `001-cobol-parser-for` | **Date**: 2025-09-27 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-cobol-parser-for/spec.md`

## Execution Flow (/plan command scope)
```
1. Load feature spec from Input path
   → If not found: ERROR "No feature spec at {path}"
2. Fill Technical Context (scan for NEEDS CLARIFICATION)
   → Detect Project Type from file system structure or context (web=frontend+backend, mobile=app+api)
   → Set Structure Decision based on project type
3. Fill the Constitution Check section based on the content of the constitution document.
4. Evaluate Constitution Check section below
   → If violations exist: Document in Complexity Tracking
   → If no justification possible: ERROR "Simplify approach first"
   → Update Progress Tracking: Initial Constitution Check
5. Execute Phase 0 → research.md
   → If NEEDS CLARIFICATION remain: ERROR "Resolve unknowns"
6. Execute Phase 1 → contracts, data-model.md, quickstart.md, agent-specific template file (e.g., `CLAUDE.md` for Claude Code, `.github/copilot-instructions.md` for GitHub Copilot, `GEMINI.md` for Gemini CLI, `QWEN.md` for Qwen Code or `AGENTS.md` for opencode).
7. Re-evaluate Constitution Check section
   → If new violations: Refactor design, return to Phase 1
   → Update Progress Tracking: Post-Design Constitution Check
8. Plan Phase 2 → Describe task generation approach (DO NOT create tasks.md)
9. STOP - Ready for /tasks command
```

**IMPORTANT**: The /plan command STOPS at step 7. Phases 2-4 are executed by other commands:
- Phase 2: /tasks command creates tasks.md
- Phase 3-4: Implementation execution (manual or via tools)

## Summary
Build a comprehensive COBOL parser library for Python 3.13+ that can parse all four COBOL divisions (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE) and expose COBOL program structure through a Pythonic API. The parser prioritizes accuracy over performance, supports configurable memory limits and error recovery modes, focuses on IBM Enterprise COBOL dialect, and provides JSON serialization capabilities for interoperability. Implementation follows test-first development with 90%+ coverage requirements and plugin extensibility for custom parsing rules.

## Technical Context
**Language/Version**: Python 3.13+ (minimum version for modern language features)  
**Primary Dependencies**: Standard library only for core parsing, pytest for testing framework  
**Storage**: File-based input (COBOL source files), in-memory object model output  
**Testing**: pytest with 90%+ code coverage requirement, including real COBOL sample files  
**Target Platform**: Cross-platform (Windows, Linux, macOS) via PyPI distribution
**Project Type**: Single Python package library (`cobolparser`)  
**Performance Goals**: Best-effort parsing for large enterprise COBOL files without specific time guarantees, prioritize accuracy over speed  
**Constraints**: Configurable memory limit options, configurable error recovery modes (fail-fast vs error collection), offline-capable  
**Scale/Scope**: Handle enterprise COBOL programs (10,000+ lines), IBM Enterprise COBOL dialect priority, JSON export capability

## Constitution Check
*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

**I. Test-First Development (NON-NEGOTIABLE)**: ✅ PASS
- Plan includes pytest framework with 90%+ coverage requirement
- TDD cycle enforced: contract tests → implementation → integration tests
- Performance testing for large COBOL files included

**II. Comprehensive COBOL Coverage**: ✅ PASS  
- All four COBOL divisions (IDENTIFICATION, ENVIRONMENT, DATA, PROCEDURE) supported
- Real-world COBOL programs targeted, not just textbook examples
- IBM Enterprise COBOL dialect prioritized with other dialect support

**III. Pythonic API Design**: ✅ PASS
- Object model represents COBOL as intuitive Python classes (Program, Division, Section, etc.)
- Clean API that abstracts COBOL complexity from Python developers
- Standard Python patterns for property access and navigation

**IV. Error Handling & Validation**: ✅ PASS
- Clear error reporting with line numbers and descriptions
- Custom exception classes planned
- Configurable error recovery modes (fail-fast vs error collection)

**V. Extensibility Through Plugins**: ✅ PASS
- Plugin architecture for custom parsing rules and COBOL dialect extensions
- Extension points for validation and transformation capabilities
- Plugin API to be defined in contracts phase

## Project Structure

### Documentation (this feature)
```
specs/[###-feature]/
├── plan.md              # This file (/plan command output)
├── research.md          # Phase 0 output (/plan command)
├── data-model.md        # Phase 1 output (/plan command)
├── quickstart.md        # Phase 1 output (/plan command)
├── contracts/           # Phase 1 output (/plan command)
└── tasks.md             # Phase 2 output (/tasks command - NOT created by /plan)
```

### Source Code (repository root)
```
cobolparser/
├── __init__.py              # Main API exports
├── parser/                  # Core parsing logic
│   ├── __init__.py
│   ├── lexer.py            # Tokenization
│   ├── grammar.py          # COBOL grammar definitions
│   └── recursive_descent.py # Parser implementation
├── models/                  # Object model classes
│   ├── __init__.py
│   ├── program.py          # Program class
│   ├── division.py         # Division classes
│   ├── section.py          # Section classes
│   ├── statement.py        # Statement classes
│   └── variable.py         # Variable declaration classes
├── dialects/               # COBOL dialect support
│   ├── __init__.py
│   ├── ibm_enterprise.py   # IBM Enterprise COBOL (primary)
│   ├── micro_focus.py      # Micro Focus COBOL
│   └── gnu_cobol.py        # GnuCOBOL support
├── plugins/                # Plugin system
│   ├── __init__.py
│   ├── base.py            # Plugin base classes
│   └── registry.py        # Plugin registration
├── errors.py               # Custom exception classes
├── config.py              # Configuration management
└── serialization.py       # JSON export functionality

tests/
├── contracts/             # Contract tests (API interfaces)
├── integration/           # End-to-end parsing tests
├── unit/                 # Unit tests for individual components
├── samples/              # Real COBOL sample files
│   ├── ibm/             # IBM Enterprise COBOL samples
│   ├── micro_focus/     # Micro Focus samples
│   └── gnu_cobol/       # GnuCOBOL samples
└── fixtures/             # Test data and utilities

examples/                  # Usage examples and quickstart
├── basic_parsing.py      # Simple parsing example
├── error_handling.py     # Error recovery examples
├── plugin_example.py     # Custom plugin demonstration
└── sample_programs/      # Example COBOL files

pyproject.toml            # Modern Python packaging
README.md                 # Installation and usage
docs/                    # Documentation
└── api/                 # API reference documentation
```

**Structure Decision**: Single Python package architecture selected. The `cobolparser/` package contains all core functionality with clear separation of concerns: parsing logic, object models, dialect support, plugins, and utilities. Test structure mirrors source structure with additional sample COBOL programs for realistic testing scenarios.

## Phase 0: Outline & Research
1. **Research Areas Identified**:
   - COBOL grammar structure and parsing strategies (recursive descent vs others)
   - IBM Enterprise COBOL syntax specifics and dialect differences
   - Python parsing libraries and performance patterns for large files
   - Memory management strategies for configurable memory limits
   - Plugin architecture patterns in Python parsing libraries
   - Error recovery techniques in parser design
   - JSON serialization patterns for complex object hierarchies

2. **Research Tasks**:
   ```
   Task: "Research COBOL grammar structure and identify parsing strategy options"
   Task: "Research IBM Enterprise COBOL syntax differences from ANSI standard"
   Task: "Research Python parsing performance patterns for large text files"
   Task: "Research memory management and configurable limits in Python parsers"
   Task: "Research plugin architecture patterns for parsing libraries"
   Task: "Research error recovery strategies in recursive descent parsers"
   Task: "Research JSON serialization patterns for complex nested object models"
   ```

3. **Consolidate findings** in `research.md` using format:
   - Decision: [parsing strategy, dialect priorities, architecture choices]
   - Rationale: [performance, maintainability, extensibility considerations]
   - Alternatives considered: [other parsing approaches, different architectures]

**Output**: research.md with technical decisions documented for parsing strategy, dialect support, plugin architecture, and performance approach

## Phase 1: Design & Contracts
*Prerequisites: research.md complete*

1. **Extract entities from feature spec** → `data-model.md`:
   - Entity name, fields, relationships
   - Validation rules from requirements
   - State transitions if applicable

2. **Generate API contracts** from functional requirements:
   - For each user action → endpoint
   - Use standard REST/GraphQL patterns
   - Output OpenAPI/GraphQL schema to `/contracts/`

3. **Generate contract tests** from contracts:
   - One test file per endpoint
   - Assert request/response schemas
   - Tests must fail (no implementation yet)

4. **Extract test scenarios** from user stories:
   - Each story → integration test scenario
   - Quickstart test = story validation steps

5. **Update agent file incrementally** (O(1) operation):
   - Run `.specify/scripts/powershell/update-agent-context.ps1 -AgentType copilot`
     **IMPORTANT**: Execute it exactly as specified above. Do not add or remove any arguments.
   - If exists: Add only NEW tech from current plan
   - Preserve manual additions between markers
   - Update recent changes (keep last 3)
   - Keep under 150 lines for token efficiency
   - Output to repository root

**Output**: data-model.md, /contracts/*, failing tests, quickstart.md, agent-specific file

## Phase 2: Task Planning Approach
*This section describes what the /tasks command will do - DO NOT execute during /plan*

**Task Generation Strategy**:
- Load `.specify/templates/tasks-template.md` as base
- Generate tasks from Phase 1 design docs (contracts, data model, quickstart) incorporating clarified requirements
- **Contract Tests**: Parser API (with memory management), Plugin API, JSON serialization interface [P]
- **Entity Creation**: Program, Division, Section, Statement, Variable Declaration models with JSON support [P]
- **Core Implementation**: Lexer, Parser, Error recovery modes, Memory management, Dialect handling [P]
- **Configuration**: MemoryConfiguration, SerializationConfig, ErrorRecoveryMode classes [P]
- **Integration Tests**: Full parsing workflows, memory limit scenarios, error collection mode, JSON export

**Ordering Strategy with Constitutional Focus**:
- **TDD Constitutional Order**: Contract tests → Failing tests → Implementation → Pass tests
- **Memory Management Priority**: Configuration classes → Memory tracking → Limit enforcement
- **IBM Enterprise COBOL Priority**: Core parsing → IBM dialect support → Other dialects
- **JSON Export Integration**: Object model → Serialization → Configuration options
- **Error Recovery**: Basic error handling → Configurable modes → Collection scenarios

**Estimated Output**: 35-40 numbered, ordered tasks in tasks.md including:
- 8-10 contract test tasks for enhanced API
- 12-15 model and core implementation tasks
- 6-8 configuration and memory management tasks
- 8-10 integration and JSON export tasks

**Constitutional Compliance**:
- All tasks follow Test-First Development (contract tests before implementation)
- Memory configuration tasks ensure configurable limits requirement
- IBM Enterprise COBOL tasks prioritized over other dialect support
- JSON serialization tasks enable interoperability requirement

**IMPORTANT**: This phase is executed by the /tasks command, NOT by /plan

## Phase 3+: Future Implementation
*These phases are beyond the scope of the /plan command*

**Phase 3**: Task execution (/tasks command creates tasks.md)  
**Phase 4**: Implementation (execute tasks.md following constitutional principles)  
**Phase 5**: Validation (run tests, execute quickstart.md, performance validation)

## Complexity Tracking
*Fill ONLY if Constitution Check has violations that must be justified*

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| [e.g., 4th project] | [current need] | [why 3 projects insufficient] |
| [e.g., Repository pattern] | [specific problem] | [why direct DB access insufficient] |


## Progress Tracking
*This checklist is updated during execution flow*

**Phase Status**:
- [x] Phase 0: Research complete (/plan command)
- [x] Phase 1: Design complete (/plan command)
- [x] Phase 2: Task planning complete (/plan command - describe approach only)
- [ ] Phase 3: Tasks generated (/tasks command)
- [ ] Phase 4: Implementation complete
- [ ] Phase 5: Validation passed

**Gate Status**:
- [x] Initial Constitution Check: PASS
- [x] Post-Design Constitution Check: PASS  
- [x] All NEEDS CLARIFICATION resolved (via clarifications section)
- [x] Complexity deviations documented (none identified)

---
*Based on Constitution v1.0.0 - See `/memory/constitution.md`*
