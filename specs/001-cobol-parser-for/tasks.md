# Tasks: COBOL Parser for Python

**Input**: Design documents from `/specs/001-cobol-parser-for/`  
**Prerequisites**: plan.md (required), research.md, data-model.md, contracts/

## Execution Flow (main)
```
✅ 1. Load plan.md from feature directory
   → Found: Python 3.13+, pytest, Single package (`cobolparser`)
   → Extract: Standard library only, IBM Enterprise COBOL focus, JSON export, configurable memory
✅ 2. Load optional design documents:
   → ✅ data-model.md: 7 core entities + MemoryConfiguration + SerializationConfig + enhanced metadata
   → ✅ contracts/: parser_api.md (updated with memory/JSON), plugin_api.md (IBM focus)
   → ✅ research.md: Recursive descent, configurable memory limits, error recovery modes
✅ 3. Generate tasks by category:
   → ✅ Setup: Python package structure, pyproject.toml, pytest configuration  
   → ✅ Tests: Contract tests for enhanced API, integration tests for memory/JSON/error modes
   → ✅ Core: Enhanced models with JSON support, parser with memory tracking, configuration classes
   → ✅ Integration: Memory management, error recovery modes, JSON serialization, IBM dialect focus
   → ✅ Polish: Unit tests for new features, performance validation, enhanced documentation
✅ 4. Apply task rules:
   → ✅ Different files marked [P] for parallel execution
   → ✅ Same file tasks are sequential  
   → ✅ TDD enforced: All tests before implementation (constitutional requirement)
✅ 5. Number tasks sequentially (T001-T050)
✅ 6. Generate dependency graph based on enhanced architecture
✅ 7. Create parallel execution examples with new components
✅ 8. Validate task completeness:
   → ✅ All enhanced contracts have tests (memory, JSON, error modes)
   → ✅ All entities including configuration classes have models
   → ✅ All API functions including new features implemented
   → ✅ Constitutional requirements addressed (TDD, memory, IBM focus, JSON, coverage)
✅ 9. Return: SUCCESS (enhanced tasks ready for execution)
```

## Format: `[ID] [P?] Description`
- **[P]**: Can run in parallel (different files, no dependencies)
- Include exact file paths in descriptions

## Path Conventions
Based on plan.md enhanced structure: Single Python package with organized components
- **Package**: `cobolparser/` with submodules (`parser/`, `models/`, `dialects/`, `plugins/`)
- **Tests**: `tests/contracts/`, `tests/integration/`, `tests/unit/`, `tests/samples/`  
- **Examples**: `examples/` with usage examples and sample COBOL programs
- **Config**: `pyproject.toml`, `README.md`, `docs/` for API documentation

## Phase 3.1: Setup
- [ ] T001 Create enhanced Python package structure per plan.md: cobolparser/{parser/,models/,dialects/,plugins/}, tests/{contracts/,integration/,unit/,samples/}, examples/
- [ ] T002 Initialize Python 3.13+ project with pyproject.toml and pytest dependencies  
- [ ] T003 [P] Configure package __init__.py with CobolParser class export and enhanced API
- [ ] T004 [P] Create IBM Enterprise COBOL sample files in tests/samples/ibm/ with modern features

## Phase 3.2: Tests First (TDD) ⚠️ MUST COMPLETE BEFORE 3.3  
**CRITICAL: These tests MUST be written and MUST FAIL before ANY implementation**

### Contract Tests (Enhanced API) [P]
- [ ] T005 [P] Contract test CobolParser.parse_file() with memory limits in tests/contracts/test_parser_api_parse_file.py
- [ ] T006 [P] Contract test CobolParser.parse_string() with error modes in tests/contracts/test_parser_api_parse_string.py
- [ ] T007 [P] Contract test CobolParser.export_json() with SerializationConfig in tests/contracts/test_parser_api_json_export.py
- [ ] T008 [P] Contract test MemoryConfiguration presets and validation in tests/contracts/test_memory_configuration.py
- [ ] T009 [P] Contract test SerializationConfig presets and filtering in tests/contracts/test_serialization_config.py
- [ ] T010 [P] Contract test ErrorRecoveryMode and enhanced error handling in tests/contracts/test_error_recovery.py
- [ ] T011 [P] Contract test Plugin API with IBM Enterprise COBOL focus in tests/contracts/test_plugin_api.py

### Integration Tests (User Scenarios from quickstart.md) [P]
- [ ] T012 [P] Integration test basic parsing with IBM Enterprise COBOL in tests/integration/test_basic_parsing.py
- [ ] T013 [P] Integration test memory-constrained parsing scenarios in tests/integration/test_memory_limits.py  
- [ ] T014 [P] Integration test error collection mode vs fail-fast in tests/integration/test_error_recovery.py
- [ ] T015 [P] Integration test JSON export with different configurations in tests/integration/test_json_export.py
- [ ] T016 [P] Integration test IBM Enterprise COBOL specific features in tests/integration/test_ibm_cobol.py
- [ ] T017 [P] Integration test large file processing with progress callbacks in tests/integration/test_performance.py

## Phase 3.3: Core Implementation (ONLY after tests are failing)

### Configuration Classes (Foundation) [P]
- [ ] T018 [P] MemoryConfiguration class with presets (conservative/default/generous) in cobolparser/config.py
- [ ] T019 [P] SerializationConfig class with filtering and depth control in cobolparser/serialization.py
- [ ] T020 [P] ErrorRecoveryMode enum and DialectType enum in cobolparser/config.py

### Enhanced Model Classes [P]  
- [ ] T021 [P] Program class with JSON export and memory tracking in cobolparser/models/program.py
- [ ] T022 [P] Division hierarchy classes (ID/ENV/DATA/PROC) in cobolparser/models/division.py
- [ ] T023 [P] Section classes with enhanced metadata in cobolparser/models/section.py
- [ ] T024 [P] Statement classes with IBM Enterprise COBOL support in cobolparser/models/statement.py
- [ ] T025 [P] Declaration classes (variables) with advanced features in cobolparser/models/variable.py
- [ ] T026 [P] Enhanced ParseMetadata with memory and dialect tracking in cobolparser/models/metadata.py
- [ ] T027 [P] Custom exception hierarchy with error recovery support in cobolparser/errors.py

### Core Parser Components [P]
- [ ] T028 [P] COBOL lexer with memory tracking and dialect awareness in cobolparser/parser/lexer.py  
- [ ] T029 [P] COBOL grammar definitions for IBM Enterprise COBOL in cobolparser/parser/grammar.py
- [ ] T030 Recursive descent parser with error recovery modes in cobolparser/parser/recursive_descent.py
- [ ] T031 Main CobolParser class integration with configuration in cobolparser/parser/__init__.py

### Dialect Support [P]
- [ ] T032 [P] IBM Enterprise COBOL dialect handler (primary) in cobolparser/dialects/ibm_enterprise.py
- [ ] T033 [P] Base dialect classes and detection in cobolparser/dialects/__init__.py

### Plugin System [P] 
- [ ] T034 [P] Plugin base classes with IBM Enterprise COBOL focus in cobolparser/plugins/base.py
- [ ] T035 Plugin registry and registration with dialect support in cobolparser/plugins/registry.py

## Phase 3.4: Integration

### Main API Integration
- [ ] T036 CobolParser main class with memory management and configuration in cobolparser/__init__.py
- [ ] T037 JSON serialization implementation with configurable options in cobolparser/serialization.py
- [ ] T038 Memory monitoring and limits enforcement integration
- [ ] T039 Error recovery modes integration with parser and plugin system

### Enhanced Features Integration  
- [ ] T040 [P] Create comprehensive IBM Enterprise COBOL test samples in tests/samples/ibm/
- [ ] T041 [P] Create error recovery and memory limit test scenarios in tests/samples/error_cases/
- [ ] T042 Integration testing with real COBOL samples and all feature combinations

## Phase 3.5: Polish

### Unit Tests (Enhanced Components) [P]
- [ ] T043 [P] Unit tests for lexer components and memory tracking in tests/unit/test_lexer.py
- [ ] T044 [P] Unit tests for enhanced object model validation in tests/unit/test_models.py  
- [ ] T045 [P] Unit tests for memory management and configuration in tests/unit/test_memory.py
- [ ] T046 [P] Unit tests for JSON serialization with all presets in tests/unit/test_serialization.py
- [ ] T047 [P] Unit tests for error recovery modes and dialect handling in tests/unit/test_error_recovery.py

### Performance and Documentation
- [ ] T048 Performance tests for large COBOL files with memory limits (no time guarantees) 
- [ ] T049 [P] Create enhanced usage examples in examples/ (basic_parsing.py, memory_config.py, json_export.py, error_handling.py)
- [ ] T050 [P] Update README.md with installation, configuration, and JSON export examples
- [ ] T051 [P] Generate comprehensive API documentation with memory and JSON features

### Final Validation
- [ ] T052 Validate constitutional compliance: 90% test coverage achieved
- [ ] T053 Run enhanced quickstart.md scenarios as validation tests  
- [ ] T054 Final integration: all components working with memory limits, JSON export, and IBM focus

## Dependencies

### Critical Dependencies (Constitutional TDD Requirements)
- **Tests First**: T005-T017 MUST complete before T018-T035 (contract tests before implementation)
- **Foundation First**: T018-T020 (configuration classes) before T021-T027 (models)  
- **Models Before Services**: T021-T027 before T028-T035 (object model before parser)
- **Core Before Integration**: T018-T035 before T036-T042
- **Implementation Before Polish**: T018-T042 before T043-T054

### Specific Dependencies
```
Setup Phase (T001-T004): No dependencies, can run in parallel after T001 creates structure

Test Phase (T005-T017): All tests can run in parallel, MUST complete before implementation
├── Contract tests (T005-T011) - Independent, different test files
└── Integration tests (T012-T017) - Independent, different test files  

Implementation Phase (T018-T035): Must follow dependency order
├── Configuration (T018-T020) - Can run in parallel, foundation for all other components
├── Models (T021-T027) - Can run in parallel after configuration, different model files  
├── Parser (T028-T031) - T030 depends on T028-T029, T031 depends on models
├── Dialects (T032-T033) - Can run in parallel, depends on models and parser
└── Plugins (T034-T035) - T035 depends on T034, both depend on models

Integration Phase (T036-T042): Sequential, depends on all core implementation  
├── T036 depends on all parser components (T028-T035)
├── T037 depends on models (T021-T027) and serialization config (T019)
├── T038-T039 depend on T036 (main class integration)
├── T040-T042 can run in parallel after T036-T039

Polish Phase (T043-T054): Can run in parallel, depends on full implementation
├── Unit tests (T043-T047) - Independent, different test files
├── Documentation (T049-T051) - Independent, different files  
└── Validation (T052-T054) - Sequential, final validation steps
```

## Parallel Execution Examples

### Phase 3.2: Contract Tests (All Parallel)
```bash
# Launch T005-T011 together (different test files):
Task: "Contract test CobolParser.parse_file() with memory limits in tests/contracts/test_parser_api_parse_file.py"
Task: "Contract test CobolParser.export_json() with SerializationConfig in tests/contracts/test_parser_api_json_export.py"
Task: "Contract test MemoryConfiguration presets in tests/contracts/test_memory_configuration.py"
Task: "Contract test SerializationConfig presets in tests/contracts/test_serialization_config.py"
Task: "Contract test ErrorRecoveryMode and enhanced error handling in tests/contracts/test_error_recovery.py"
Task: "Contract test Plugin API with IBM Enterprise COBOL focus in tests/contracts/test_plugin_api.py"
```

### Phase 3.2: Integration Tests (All Parallel) 
```bash
# Launch T012-T017 together (different test files):
Task: "Integration test basic parsing with IBM Enterprise COBOL in tests/integration/test_basic_parsing.py"
Task: "Integration test memory-constrained parsing scenarios in tests/integration/test_memory_limits.py"
Task: "Integration test error collection mode vs fail-fast in tests/integration/test_error_recovery.py"
Task: "Integration test JSON export with different configurations in tests/integration/test_json_export.py"
Task: "Integration test IBM Enterprise COBOL specific features in tests/integration/test_ibm_cobol.py"
```

### Phase 3.3: Configuration Classes (All Parallel)
```bash
# Launch T018-T020 together (different files):
Task: "MemoryConfiguration class with presets in cobolparser/config.py"  
Task: "SerializationConfig class with filtering in cobolparser/serialization.py"
Task: "ErrorRecoveryMode and DialectType enums in cobolparser/config.py"
```

### Phase 3.3: Enhanced Model Classes (All Parallel)
```bash
# Launch T021-T027 together (different model files):
Task: "Program class with JSON export in cobolparser/models/program.py"
Task: "Division hierarchy classes in cobolparser/models/division.py" 
Task: "Section classes with enhanced metadata in cobolparser/models/section.py"
Task: "Statement classes with IBM Enterprise COBOL support in cobolparser/models/statement.py"
Task: "Declaration classes with advanced features in cobolparser/models/variable.py"
Task: "Enhanced ParseMetadata with memory tracking in cobolparser/models/metadata.py"
Task: "Custom exception hierarchy in cobolparser/errors.py"
```

### Phase 3.3: Core Parser Components (Most Parallel)
```bash
# Launch T028-T029, T032-T035 together (different files):
Task: "COBOL lexer with memory tracking in cobolparser/parser/lexer.py"
Task: "COBOL grammar definitions for IBM Enterprise COBOL in cobolparser/parser/grammar.py"
Task: "IBM Enterprise COBOL dialect handler in cobolparser/dialects/ibm_enterprise.py"
Task: "Base dialect classes in cobolparser/dialects/__init__.py"
Task: "Plugin base classes with IBM focus in cobolparser/plugins/base.py"

# Note: T030-T031 and T035 are sequential within their respective files
```

### Phase 3.5: Polish (All Parallel)
```bash
# Launch T043-T047, T049-T051 together (different files):
Task: "Unit tests for lexer components in tests/unit/test_lexer.py"
Task: "Unit tests for enhanced object model in tests/unit/test_models.py"
Task: "Unit tests for memory management in tests/unit/test_memory.py" 
Task: "Unit tests for JSON serialization in tests/unit/test_serialization.py"
Task: "Create enhanced usage examples in examples/"
Task: "Update README.md with new features"
Task: "Generate comprehensive API documentation"
```

## Notes

### Constitutional Compliance Focus
- **Test-First Development**: T005-T017 enforce TDD approach (tests before implementation)
- **Memory Management**: T018, T038, T045 ensure configurable memory limits requirement
- **IBM Enterprise COBOL Focus**: T016, T032, T040 prioritize IBM Enterprise COBOL dialect
- **JSON Export Capability**: T007, T015, T019, T037, T046 enable interoperability requirement  
- **90% Coverage**: T052 validates constitutional coverage requirement
- **Comprehensive COBOL**: Real samples in T040-T041, dialect support in T032-T033

### Enhanced Features Implementation
- **Memory Configuration**: T018 (config class), T038 (enforcement), T045 (testing)  
- **Error Recovery Modes**: T010 (contract), T014 (integration), T020 (enum), T039 (implementation)
- **JSON Serialization**: T019 (config), T037 (implementation), T046 (testing)
- **IBM Enterprise Priority**: T016 (integration test), T032 (dialect handler), T040 (samples)

### Task Generation Rules Applied

1. **From Enhanced Contracts**:
   - parser_api.md (updated) → T005-T010 (contract tests for memory, JSON, error modes)
   - plugin_api.md (IBM focus) → T011 (contract test for enhanced plugin system)

2. **From Enhanced Data Model**:
   - MemoryConfiguration → T018 (configuration class)
   - SerializationConfig → T019 (serialization class) 
   - Program with JSON → T021 (enhanced model)
   - Enhanced ParseMetadata → T026 (memory tracking model)
   - 7 core entities → T021-T027 (enhanced model tasks)

3. **From Enhanced Quickstart Scenarios**:
   - Memory-constrained parsing → T013 (integration test)
   - JSON export examples → T015 (integration test)
   - IBM Enterprise COBOL → T016 (integration test)
   - Error collection mode → T014 (integration test)

4. **From Research Decisions**:
   - Recursive descent parser → T028-T031 (parser implementation)
   - IBM Enterprise COBOL focus → T032-T033 (dialect support)
   - Plugin architecture → T034-T035 (plugin system)

### Quality Assurance
- [P] tasks = different files, truly independent
- Verify tests fail before implementing (constitutional TDD requirement)
- All tests must pass before moving to next phase
- Memory limits tested under various configurations
- JSON export tested with all preset configurations  
- IBM Enterprise COBOL features comprehensively tested

## Validation Checklist
✅ All enhanced contracts have corresponding tests (T005-T011)
✅ All entities including configuration classes have model tasks (T018-T027)
✅ All tests come before implementation (T005-T017 before T018-T035)
✅ Parallel tasks are truly independent (different files, no shared dependencies)
✅ Each task specifies exact file path matching enhanced project structure
✅ No task modifies same file as another [P] task
✅ Constitutional requirements addressed (TDD, memory, IBM focus, JSON, coverage)
✅ Clarified requirements fully incorporated (memory limits, error recovery, JSON export)