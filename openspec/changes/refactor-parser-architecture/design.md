# Design: Refactor Parser Architecture

## Context

The COBOL parser currently implements all parsing logic monolithically in `cobolparser/parser.py` (~7,500 lines). This single file handles:
- IDENTIFICATION, ENVIRONMENT, DATA, and PROCEDURE divisions
- SELECT and FILE-CONTROL statements  
- All statement types (MOVE, DISPLAY, IF, PERFORM, EVALUATE, etc.)
- Data item definitions with picture clauses
- Error recovery and token consumption logic

**Current pain points:**
- High cyclomatic complexity makes unit testing difficult
- Adding new statement types requires modifying the main parser
- Hard to isolate and debug specific division or statement parsing
- Difficult to extend for new dialects (e.g., GnuCOBOL, Micro Focus)
- Tests often require parsing entire programs to test single statements
- No clear contract between parser layers

**Project context:**
- Python 3.13+ with strict type hints
- TDD architecture with 90%+ code coverage requirement
- IBM Enterprise COBOL priority (COMP-3, EXEC SQL/CICS)
- Existing test framework: pytest with 38 contract, 17 integration, 59 unit tests

## Goals / Non-Goals

**Goals:**
- Enable isolated unit testing of each parser component
- Reduce `CobolParser` from 7,500+ to <1,000 lines through delegation
- Establish clear interfaces between parser layers (SOLID principles)
- Create extensible pattern for adding new statement types without modifying core
- Implement comprehensive test coverage (114+ tests across contract/integration/unit)
- Maintain backward-compatible public API
- Support dialect extensibility through factory registration
- Improve error reporting with structured error hierarchy

**Non-Goals:**
- Change AST node structure or semantics (models/ stay intact)
- Optimize lexer or tokenization (lexer.py unchanged)
- Modify public API contract tests
- Support Python versions <3.13
- Implement new statement types beyond current scope
- Add new external dependencies

## Decisions

### 1. Factory Pattern for Division Parsers

**Decision**: Create `DivisionParserFactory` to instantiate division-specific parsers (`IdentificationDivisionParser`, `EnvironmentDivisionParser`, `DataDivisionParser`, `ProcedureDivisionParser`).

**Rationale**: 
- Isolates division detection logic from parsing logic
- Enables testing each division independently
- Allows registering new divisions without modifying core parser
- Maps to Open/Closed Principle (OCP) - new divisions can be added without changing existing code

**Alternatives considered:**
- Monolithic parsing with internal switch statements (current approach) → Rejected: causes tight coupling
- Runtime intrective parser discovery → Rejected: adds complexity without clear benefit for 4 fixed divisions
- Visitor pattern → Rejected: overkill for our division types; factory simpler

**Implementation approach:**
```python
class DivisionParserFactory:
    _PARSERS: Dict[str, Type[IDivisionParser]] = {
        "IDENTIFICATION": IdentificationDivisionParser,
        "ENVIRONMENT": EnvironmentDivisionParser,
        "DATA": DataDivisionParser,
        "PROCEDURE": ProcedureDivisionParser,
    }
    
    @classmethod
    def create_parser(cls, division_name: str) -> IDivisionParser:
        parser_class = cls._PARSERS.get(division_name.upper())
        if not parser_class:
            raise DivisionNotFoundError(f"Unknown division: {division_name}")
        return parser_class()
```

---

### 2. Statement Parser Registry for Dynamic Dispatch

**Decision**: Create `StatementParserRegistry` with `IStatementParser` interface for all statement parsers (DisplayParser, MoveParser, IfParser, etc.).

**Rationale**:
- Statement types vary by COBOL dialect; registry allows runtime registration
- Isolates statement parsing from procedure division orchestration
- Enables testing individual statements without full program context
- Supports IBM Enterprise COBOL extensions (EXEC SQL, EXEC CICS)

**Alternatives considered**:
- Long if/elif chains in ProcedureDivisionParser → Rejected: unmaintainable for 50+ statement types
- Metaclass registration → Rejected: too magical; explicit registry clearer
- Interface dispatch only → Rejected: can't handle ambiguous statement starts

**Implementation approach:**
```python
class StatementParserRegistry:
    _PARSERS: List[IStatementParser] = []
    
    @classmethod
    def register(cls, parser: IStatementParser) -> None:
        cls._PARSERS.append(parser)
    
    @classmethod
    def find_parser(cls, token_stream: TokenStream) -> IStatementParser:
        for parser in cls._PARSERS:
            if parser.matches(token_stream):
                return parser
        raise UnknownStatementError(f"No parser for: {token_stream.peek()}")
```

---

### 3. TokenStream Abstraction with Lookahead

**Decision**: Create `TokenStream` class wrapping token list with `peek()`, `consume()`, `expect()` methods and optional lookahead buffer.

**Rationale**:
- Encapsulates token navigation logic (position management, bounds checking)
- Lookahead enables predictive parsing (match statement type before consuming)
- Reduces token list access errors (OutOfBounds, None checks)
- Consistent interface across all parsers

**Alternatives considered**:
- Bare token list indexing → Rejected: error-prone, scattered bounds checks
- Iterator pattern → Rejected: can't look ahead, must consume to peek
- Custom deque → Rejected: unnecessary; list with position works fine

**Implementation approach:**
```python
class TokenStream:
    def __init__(self, tokens: List[Token], lookahead: int = 3):
        self._tokens = tokens
        self._position = 0
        self._lookahead_size = lookahead
    
    def peek(self, offset: int = 0) -> Token:
        index = self._position + offset
        if index >= len(self._tokens):
            raise UnexpectedEndOfInput("Token stream exhausted")
        return self._tokens[index]
    
    def consume(self) -> Token:
        token = self.peek()
        self._position += 1
        return token
    
    def expect(self, value: str) -> Token:
        token = self.peek()
        if token.value.upper() != value.upper():
            raise TokenMismatch(f"Expected {value}, got {token.value}")
        return self.consume()
```

---

### 4. Parser Error Hierarchy and Context

**Decision**: Create `ParseError` base class with subclasses (`TokenMismatch`, `UnexpectedEndOfInput`, `DivisionNotFound`, `UnknownStatement`) including line/column information.

**Rationale**:
- Structured error handling enables better error reporting and recovery
- Line/column context improves debugging and IDE integration
- Specific exception types enable targeted error handling
- Replaces current string-based error messages

**Alternatives considered**:
- Generic Exception with error codes → Rejected: type safety lost
- Error objects instead of exceptions → Rejected: doesn't integrate with Python error handling
- Single ParseError with error codes → Rejected: less specific, poorer IDE support

**Implementation approach:**
```python
class ParseError(Exception):
    def __init__(self, message: str, location: SourceLocation = None):
        self.message = message
        self.location = location
        super().__init__(self._format_message())
    
    def _format_message(self) -> str:
        if self.location:
            return f"{self.location}: {self.message}"
        return self.message

class TokenMismatch(ParseError):
    pass

class UnexpectedEndOfInput(ParseError):
    pass

class DivisionNotFound(ParseError):
    pass

class UnknownStatement(ParseError):
    pass
```

---

### 5. Directory Reorganization: Hierarchical Structure

**Decision**: Reorganize from flat `cobolparser/parsers/` to hierarchical structure:
```
cobolparser/
├── core/               # Abstractions, interfaces, factories
│   ├── interfaces.py   # IDivisionParser, IStatementParser, ITokenStream
│   ├── exceptions.py   # ParseError hierarchy
│   ├── token_stream.py # TokenStream class
│   ├── factories.py    # DivisionParserFactory, StatementParserRegistry
│   └── ast_factory.py  # ASTNodeFactory (centralized node creation)
├── parsers/
│   ├── divisions/      # Division-specific parsers
│   │   ├── __init__.py
│   │   ├── identification.py
│   │   ├── environment.py
│   │   ├── data.py
│   │   └── procedure.py
│   └── statements/     # Statement-specific parsers
│       ├── __init__.py
│       ├── display.py
│       ├── move.py
│       ├── if_statement.py
│       ├── perform.py
│       ├── evaluate.py
│       └── ...
├── models/             # AST nodes (unchanged)
├── parser.py           # Simplified CobolParser (delegator)
└── __init__.py
```

**Rationale**:
- Clear separation of concerns: interfaces, implementations, orchestration
- Scalable: new statement types go in `statements/` without touching core
- Mirrors parser complexity: each division/statement in own module
- Easier to navigate and maintain

**Alternatives considered**:
- Single file per division+statements → Rejected: 1000+ line files still hard to maintain
- Flat parsers/ with many files → Rejected: no organization, hard to find related code

---

### 6. Dependency Inversion via Interfaces

**Decision**: All division and statement parsers implement `IDivisionParser` or `IStatementParser`. Main `CobolParser` depends on abstractions, not concrete parsers.

**Rationale**:
- Core parser doesn't need to know specific parser implementations
- New dialect parsers can substitute implementations without changing core
- Enables mock parsers in unit tests
- Aligns with Dependency Inversion Principle

**Implementation approach:**
```python
class IDivisionParser(ABC):
    @abstractmethod
    def parse(self, token_stream: TokenStream) -> ASTNode:
        pass
    
    @abstractmethod
    def can_parse(self, token_stream: TokenStream) -> bool:
        pass

class IStatementParser(ABC):
    @abstractmethod
    def parse(self, token_stream: TokenStream) -> ASTNode:
        pass
    
    @abstractmethod
    def matches(self, token_stream: TokenStream) -> bool:
        pass
```

---

## Risks / Trade-offs

### Risk: Increased Initial Development Effort
**Impact**: Medium (estimated 40-60 hours across 5 phases)  
**Mitigation**: 
- Phased rollout allows incremental validation
- Phase 1 foundation provides quick wins and test infrastructure
- Reuse existing statement parser logic; don't rewrite

### Risk: Performance Regression from Factory Lookup
**Impact**: Low (factory creation is O(1); typically <1µs per parse)  
**Mitigation**:
- Cache parser instances in registry
- Use lookahead buffer in TokenStream to reduce peeking
- Benchmark parsing before/after phases

### Risk: Test Suite Expansion Complexity
**Impact**: Medium (need ~60 additional unit tests)  
**Mitigation**:
- Use pytest fixtures for common token streams
- Create reusable test utils (e.g., `create_token_stream(code)`)
- Leverage existing contract tests as templates

### Risk: Breaking Changes to Internal APIs
**Impact**: Low (public API stable; only internals change)  
**Mitigation**:
- Maintain current `CobolParser` public signature
- Run contract tests after each phase
- Document breaking changes in delta specs

### Risk: Dialect Registration Complexity
**Impact**: Low (only affects future dialect work)  
**Mitigation**:
- Design registry before implementation
- Create example dialect plugin in Phase 5

---

## Migration Plan

### Phase 1: Foundation Setup (Week 1)
- Create directory structure (`core/`, `parsers/divisions/`, `parsers/statements/`)
- Implement base interfaces (`IDivisionParser`, `IStatementParser`, `ITokenStream`)
- Implement `TokenStream` class with tests (8 unit tests)
- Implement `ParseError` hierarchy with tests (4 unit tests)
- Setup pytest configuration for new test structure

**Artifacts**: 
- `core/interfaces.py`, `core/token_stream.py`, `core/exceptions.py`
- 12 unit tests

**Risk**: Low. Mostly isolated infrastructure.

---

### Phase 2: Extraction (Week 2)
- Extract `IdentificationDivisionParser` with tests (5 unit tests)
- Extract `EnvironmentDivisionParser` with tests (8 unit tests)
- Extract `DataDivisionParser` with tests (6 unit tests)
- Extract `ProcedureDivisionParser` with tests (6 unit tests)
- Implement `DivisionParserFactory`

**Artifacts**:
- `parsers/divisions/*.py` (4 files)
- 25 unit tests

**Risk**: Medium. Requires careful extraction of parsing logic without changing semantics.

**Validation**: Run existing integration tests; ensure no behavioral changes.

---

### Phase 3: Orchestration (Week 3)
- Refactor `CobolParser` to delegate to division parsers
- Reduce from 7,500+ to ~400-500 lines
- Implement coordinated error handling across divisions
- Add integration tests (8 integration tests)

**Artifacts**:
- Refactored `parser.py` (~500 lines)
- 8 integration tests

**Risk**: High. Core orchestration logic; extensive testing needed.

**Validation**: All contract tests pass; performance benchmarks stable.

---

### Phase 4: Statement Parsers & Registry (Week 4)
- Migrate existing statement parsers to use `IStatementParser` interface
- Implement `StatementParserRegistry` for dynamic dispatch
- Create statement parser base classes for common patterns
- Add 20 unit tests for statement parsing edge cases

**Artifacts**:
- `parsers/statements/*.py` (updated with interfaces)
- `core/factories.py` (StatementParserRegistry)
- 20 unit tests

**Risk**: Medium. Touching many statement parsers; high test coverage mitigates.

**Validation**: All existing tests pass; add edge case tests for each statement.

---

### Phase 5: Factory & Optimization (Week 5)
- Implement `ASTNodeFactory` for centralized node creation
- Add lookahead optimization to `TokenStream`
- Performance benchmarking and tuning
- Comprehensive validation testing (25 contract tests)
- Document public APIs and extension patterns

**Artifacts**:
- `core/ast_factory.py`
- Performance benchmarks
- Extension documentation
- 25 contract tests

**Risk**: Low. Optimization and validation; limited new logic.

---

### Rollback Strategy

**If critical issue found in any phase:**
1. Revert changes from that phase only
2. Maintain previous phase's code as fallback
3. Git branches per phase allow isolation
4. Contract tests validate pre-refactor behavior

---

## Open Questions

1. **Should StatementParserRegistry support priority/ordering?** Currently First-Match-Wins. IBM COBOL extensions may need priority (e.g., EXEC SQL before generic EXEC).
   - Resolution needed before Phase 4

2. **How deep should TokenStream lookahead buffer be?** Currently proposed 3. May impact performance for large statements.
   - Benchmark in Phase 1 to determine optimal value

3. **Should ASTNodeFactory validate node invariants?** Current nodes don't validate; factory could enforce constraints.
   - Defer to Phase 5 based on Phase 4 validator feedback

4. **How to handle dialect registration lifecycle?** At import? At parser init? Global registry?
   - Design dialect plugin interface in Phase 4

5. **Should division parsers cache prepared data?** E.g., symtable from DATA division for PROCEDURE division reference validation.
   - Evaluate cache patterns in Phase 3 orchestration

---

## Technical Dependencies

- **Python**: 3.13+ (required for newer type hint features)
- **Testing**: pytest (existing), pytest-cov (existing)
- **Type checking**: mypy, pylint (existing)
- **No new external dependencies**

**Existing capabilities to preserve:**
- IBM Enterprise COBOL dialect detection
- Error recovery modes (FAIL_FAST vs COLLECT_ALL)
- Memory management configuration
- JSON serialization (to_dict/to_json)
