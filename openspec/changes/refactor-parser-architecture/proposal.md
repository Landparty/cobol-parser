# Proposal: Refactor Parser Architecture

## Why

The current `CobolParser` class monolithically handles all parsing concerns (divisions, sections, statements) in 7,500+ lines of code. This creates tight coupling, difficult unit testing, hard-to-extend statement parsers, and unclear separation of concerns. By refactoring into a factory-based architecture with dedicated division and statement parsers following SOLID principles, we will reduce core parser complexity to <1,000 lines, enable isolated testing, and establish a foundation for dialect extensibility and maintainability.

## What Changes

- **Parser structure**: Replace monolithic `CobolParser` with delegating orchestrator using `DivisionParserFactory`
- **Division handling**: Extract `IdentificationDivisionParser`, `EnvironmentDivisionParser`, `DataDivisionParser`, `ProcedureDivisionParser`
- **Statement parsing**: Migrate all statement parsers to use `StatementParserRegistry` for dynamic dispatch
- **Node creation**: Introduce `ASTNodeFactory` for consistent centralized node instantiation
- **Error handling**: Establish `ParseError` hierarchy with better error context and recovery modes
- **Directory structure**: Reorganize from flat `parsers/` to hierarchical `core/`, `parsers/divisions/`, `parsers/statements/`
- **Interfaces**: Create `IDivisionParser`, `IStatementParser`, `ITokenStream` abstractions
- **Token handling**: Introduce `TokenStream` abstraction with lookahead support
- **Testing**: Implement comprehensive unit, integration, and contract test suites (114 tests minimum)

## Capabilities

### New Capabilities

- `division-parser-factory`: Factory pattern for instantiating division parsers
- `statement-parser-registry`: Dynamic registry and dispatch system for statement parsers
- `ast-node-factory`: Centralized AST node creation with validation
- `environment-division-parser`: Dedicated parser for FILE-CONTROL, SELECT, and file descriptions
- `data-division-parser`: Dedicated parser for data definitions and working storage
- `procedure-division-parser`: Dedicated parser for statement sequences and control flow
- `token-stream-abstraction`: Stream-based token navigation with lookahead
- `parser-error-hierarchy`: Structured error types with context information
- `solid-architecture`: SOLID principles implementation (SRP, OCP, LSP, ISP, DIP)
- `comprehensive-test-coverage`: Unit, integration, and contract test suites with 90%+ coverage

### Modified Capabilities

- `ibm-enterprise-dialect`: Will be extended through factory registration without core changes
- `error-recovery`: Will use standardized error hierarchy instead of inline handling

## Impact

- **Code**: Core parser reduced from 7,500+ to <1,000 lines; new factory and abstraction layers (~2,000 lines); division/statement parsers (~3,000 lines)
- **APIs**: Public interface remains compatible; internal parser class hierarchy becomes internal implementation detail
- **Testing**: All new code requires unit tests; integration tests validate division/statement interaction; contract tests validate public API
- **Performance**: Lookahead optimization in `TokenStream`; lazy parser initialization via factories
- **Dependencies**: No new external dependencies; uses Python 3.13+ stdlib only
- **Breaking Changes**: None for public API; internal `CobolParser` implementation details will change
- **Migration Timeline**: 5-phase rollout: Foundation → Extraction → Orchestration → Factory → Validation
