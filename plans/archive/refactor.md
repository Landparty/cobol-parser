COBOL Parser Refactoring Plan (v2 - Enhanced)
1. Executive Summary
The current 
CobolParser
 implementation is a monolithic "God Class" (8354 lines, 132 methods) violating Single Responsibility (SRP) and Open/Closed (OCP) principles. This enhanced plan provides detailed, actionable steps to decompose it into testable, single-responsibility units using Strategy and Visitor patterns.

2. Codebase Cross-Reference
2.1 Primary Files Under Refactoring
File	Lines	Methods	Role
parser.py
8354	132	Core parser - God Class
lexer.py
1534	32	Tokenization (stable, minimal changes)
models/statements.py
1921	232	Mutable AST nodes
models/program.py
~1000	~30	Program/Division/Section nodes
2.2 Key Methods to Decompose (by Category)
Statement Parsers (High Priority)
These are candidates for extraction into individual StatementParser implementations:

Method	Lines	Complexity	Target Module
_parse_perform_inline
4084-4370 (286)	Very High	parsers/perform_parser.py
_parse_call_inline
3376-3440 (64)	High	parsers/call_parser.py
_parse_call_exception_handlers
3525-3913 (388)	Very High	parsers/call_parser.py
_parse_evaluate_inline
4928-5241 (313)	Very High	parsers/evaluate_parser.py
_parse_if_inline
4619-4819 (200)	High	parsers/if_parser.py
parse_call_statement
6858-7175 (317)	Very High	parsers/call_parser.py
parse_perform_statement
5642-5961 (319)	Very High	parsers/perform_parser.py
parse_if_statement
6719-6856 (137)	High	parsers/if_parser.py
parse_evaluate_statement
6131-6288 (157)	High	parsers/evaluate_parser.py
parse_move_statement
5436-5614 (178)	Medium	parsers/move_parser.py
parse_display_statement
5616-5640 (24)	Low	parsers/display_parser.py
Clause/Helper Parsers (Supporting)
Method	Lines	Target
_parse_call_using_parameters_inline
3915-3997	parsers/call_parser.py
_parse_test_timing_clause
3999-4030	parsers/perform_parser.py
_parse_until_condition
4032-4082	parsers/condition_parser.py
_parse_size_error_clauses
6290-6359	parsers/clause_handlers.py
_parse_overflow_clauses
6661-6717	parsers/clause_handlers.py
Utility Methods (Infrastructure)
Method	Lines	Target
_skip_whitespace_and_comments
7243-7259	core/token_stream.py
_is_keyword
7261-7273	core/token_stream.py
advance_token
323-331	core/token_stream.py
peek_token
333-338	core/token_stream.py
match_token
368-374	core/token_stream.py
3. Phase 0: Safety Net
3.1 Objective
Establish a comprehensive regression suite to catch any behavioral changes during refactoring.

3.2 Implementation Steps
Inventory existing tests:
tests/integration/test_sample_programs.py
tests/unit/test_sample_features.py
tests/contracts/test_sample_api_contracts.py
Run baseline and capture metrics:
cd c:\Users\samdi\Documents\workspace\cobol-parser
python -m pytest tests/ -v --tb=short --cov=cobolparser --cov-report=html
Create baselines/parser_baseline.json: Export passing test names and timing.
Add complexity baseline:
pip install radon
radon cc cobolparser/parser.py -a -s > baselines/complexity_baseline.txt
3.3 Testing Checkpoint
 All existing tests pass (115+ tests).
 HTML coverage report generated at htmlcov/index.html.
 Complexity baseline captured.
3.4 Dependencies
None (start here).

3.5 Risk Mitigation
Low risk. Read-only analysis phase.
4. Phase 1: TokenStream Abstraction
4.1 Objective
Encapsulate token list and integer index into a TokenStream class, eliminating primitive obsession.

4.2 Implementation Steps
4.2.1 Create cobolparser/core/token_stream.py [NEW]
# cobolparser/core/token_stream.py
from typing import Optional, Iterator
from contextlib import contextmanager
from ..lexer import Token, TokenType
class TokenStream:
    """Encapsulates token list and position cursor."""
    
    def __init__(self, tokens: list[Token]):
        self._tokens = tokens
        self._pos = 0
    
    def peek(self, offset: int = 0) -> Optional[Token]:
        idx = self._pos + offset
        return self._tokens[idx] if idx < len(self._tokens) else None
    
    def advance(self) -> Token:
        token = self._tokens[self._pos]
        self._pos += 1
        return token
    
    def match(self, *types: TokenType) -> bool:
        token = self.peek()
        return token is not None and token.type in types
    
    def match_value(self, *values: str) -> bool:
        token = self.peek()
        return token is not None and token.value and token.value.upper() in [v.upper() for v in values]
    
    def skip_whitespace_and_comments(self) -> None:
        while self.match(TokenType.WHITESPACE, TokenType.COMMENT, TokenType.NEWLINE, TokenType.CONTINUATION):
            self.advance()
    
    @contextmanager
    def transaction(self):
        """Context manager for backtracking on failure."""
        saved_pos = self._pos
        try:
            yield
        except:
            self._pos = saved_pos
            raise
    
    @property
    def position(self) -> int:
        return self._pos
    
    @property
    def is_at_end(self) -> bool:
        return self._pos >= len(self._tokens)
4.2.2 Modify CobolParser.__init__ (parser.py L146-186)
Add self.stream: Optional[TokenStream] = None
In 
parse()
 method (L219-271), after tokenization:
self.stream = TokenStream(self.tokens)
4.2.3 Refactor Low-Level Methods
Old Method	New Implementation
advance_token(self)
Delegate to self.stream.advance()
peek_token(self, offset)
Delegate to self.stream.peek(offset)
match_token(self, *types)
Delegate to self.stream.match(*types)
_skip_whitespace_and_comments(self, tokens, i)
self.stream.skip_whitespace_and_comments()
4.3 Testing Checkpoint
python -m pytest tests/integration/test_sample_programs.py -v
python -m pytest tests/unit/test_sample_features.py -v
 All 115+ tests still pass.
 No behavioral changes.
4.4 Dependencies
Phase 0 must be complete.
4.5 Risk Mitigation
Strategy: Feature flag. Keep old implementations, add use_stream: bool flag to 
init
.
Rollback: Revert to old methods if integration tests fail.
5. Phase 2: Registry & Interface
5.1 Objective
Define StatementParser protocol and StatementRegistry. Migrate one simple statement (DISPLAY) as proof-of-concept.

5.2 Implementation Steps
5.2.1 Create cobolparser/core/interfaces.py [NEW]
from typing import Protocol, Optional
from .token_stream import TokenStream
from ..models.statements import CobolStatement
class ParseContext:
    """Shared context during parsing (current section, errors, etc.)."""
    def __init__(self, parser: "CobolParser"):
        self.parser = parser
        self.current_section = parser.current_section
        self.current_division = parser.current_division
class StatementParser(Protocol):
    """Interface for statement-specific parsers."""
    
    def can_parse(self, stream: TokenStream) -> bool:
        """Return True if this parser handles the current token."""
        ...
    
    def parse(self, stream: TokenStream, context: ParseContext) -> CobolStatement:
        """Parse and return the statement."""
        ...
5.2.2 Create cobolparser/core/registry.py [NEW]
from typing import Dict, Type, Optional
from .interfaces import StatementParser
from .token_stream import TokenStream
from ..lexer import TokenType
class StatementRegistry:
    """Maps tokens to their corresponding parsers."""
    
    def __init__(self):
        self._parsers: list[StatementParser] = []
    
    def register(self, parser: StatementParser) -> None:
        self._parsers.append(parser)
    
    def get_parser(self, stream: TokenStream) -> Optional[StatementParser]:
        for parser in self._parsers:
            if parser.can_parse(stream):
                return parser
        return None
5.2.3 Create cobolparser/parsers/display_parser.py [NEW]
from ..core.interfaces import StatementParser, ParseContext
from ..core.token_stream import TokenStream
from ..models.statements import DisplayStatement
from ..lexer import TokenType
class DisplayStatementParser(StatementParser):
    """Parser for DISPLAY statements."""
    
    def can_parse(self, stream: TokenStream) -> bool:
        token = stream.peek()
        if token is None:
            return False
        return token.type == TokenType.DISPLAY or (
            token.type == TokenType.IDENTIFIER and token.value.upper() == "DISPLAY"
        )
    
    def parse(self, stream: TokenStream, context: ParseContext) -> DisplayStatement:
        start_token = stream.advance()  # Consume DISPLAY
        stmt = DisplayStatement(start_token.location)
        
        stream.skip_whitespace_and_comments()
        
        # Collect display items until period or next statement
        while not stream.is_at_end:
            token = stream.peek()
            if token.type == TokenType.PERIOD:
                break
            if token.type in (TokenType.IDENTIFIER,) and token.value.upper() in ("UPON",):
                stream.advance()  # UPON
                stream.skip_whitespace_and_comments()
                if not stream.is_at_end:
                    stmt.set_output_device(stream.advance().value)
                break
            if token.type in (TokenType.STRING_LITERAL, TokenType.IDENTIFIER, TokenType.NUMERIC_LITERAL):
                stmt.add_display_item(stream.advance().value)
            else:
                stream.advance()  # Skip unknown
            stream.skip_whitespace_and_comments()
        
        return stmt
5.2.4 Modify CobolParser.__init__ to initialize registry
from .core.registry import StatementRegistry
from .parsers.display_parser import DisplayStatementParser
# In __init__:
self.registry = StatementRegistry()
self.registry.register(DisplayStatementParser())
5.2.5 Modify 
_parse_display_inline
 (L3365-3374) to delegate
def _parse_display_inline(self, tokens, i):
    # Create temporary stream from position
    temp_stream = TokenStream(tokens[i:])
    context = ParseContext(self)
    parser = self.registry.get_parser(temp_stream)
    if parser:
        stmt = parser.parse(temp_stream, context)
        if self.current_section:
            self.current_section.add_child(stmt)
        return i + temp_stream.position
    return i  # Fallback
5.3 Testing Checkpoint
python -m pytest tests/unit/test_sample_features.py::TestSpecialFeatures -v
python -m pytest tests/integration/test_sample_programs.py -v
 DISPLAY tests pass.
 No regression in other tests.
5.4 Dependencies
Phase 1 (TokenStream) must be complete.
5.5 Risk Mitigation
Strategy: Dual-path. Old inline parser as fallback if registry returns None.
Rollback: Remove registry delegation, revert to inline parsing.
6. Phase 3: Statement Decomposition
6.1 Objective
Migrate complex statements one-by-one into dedicated StatementParser classes.

6.2 Migration Order (by risk/value)
Order	Statement	Source Methods	New File	Risk
1	MOVE	
parse_move_statement
, 
_parse_move_inline
parsers/move_parser.py	Low
2	CALL	
parse_call_statement
, 
_parse_call_inline
, 
_parse_call_exception_handlers
, 
_parse_call_using_parameters_inline
parsers/call_parser.py	Med
3	IF	
parse_if_statement
, 
_parse_if_inline
, 
_parse_inline_if_into_perform
, 
_parse_inline_call_into_if
parsers/if_parser.py	Med
4	PERFORM	
parse_perform_statement
, 
_parse_perform_inline
, 
_parse_test_timing_clause
, 
_parse_until_condition
, 
_parse_inline_call_into_perform
parsers/perform_parser.py	High
5	EVALUATE	
parse_evaluate_statement
, 
_parse_evaluate_inline
, 
_parse_evaluate_selector
, 
_validate_evaluate_statement
parsers/evaluate_parser.py	High
6.3 Implementation Pattern (for each)
Create parsers/<stmt>_parser.py.
Implement StatementParser protocol.
Register in StatementRegistry.
Modify parse_<stmt>_statement to delegate.
Modify _parse_<stmt>_inline to delegate.
Run tests after each migration.
6.4 Testing Checkpoint (after each statement)
python -m pytest tests/ -v -k "<statement_name>"
python -m pytest tests/integration/test_sample_programs.py -v
6.5 Dependencies
Phase 2 (Registry & Interface) must be complete.
6.6 Risk Mitigation
Strategy: Migrate one statement at a time. Full test suite after each.
Rollback: Revert single parser file. Old methods remain as fallback until stable.
7. Phase 4: AST Hardening
7.1 Objective
Convert mutable AST nodes to immutable frozen=True dataclasses.

7.2 Files to Modify
models/statements.py
models/program.py
models/data_items.py
7.3 Implementation Steps
Start with leaf nodes (e.g., 
MoveStatement
, 
DisplayStatement
).
Replace setter methods (
set_source
) with dataclass.replace().
Change List fields to tuple.
Update parsers to construct immutable nodes.
7.4 Testing Checkpoint
python -m pytest tests/ -v
 All tests pass.
 No AttributeError from frozen assignments.
7.5 Dependencies
Phase 3 should be substantially complete (parsers decoupled from internal mutation).
7.6 Risk Mitigation
Strategy: Migrate leaf nodes first. Keep parent nodes mutable until children are stable.
Rollback: Revert frozen=True on specific classes.
8. Phase Dependencies Graph
Phase 0: Safety Net
Phase 1: TokenStream
Phase 2: Registry & Interface
Phase 3: Decomposition
Phase 4: AST Hardening
3.1 MOVE Parser
3.2 CALL Parser
3.3 IF Parser
3.4 PERFORM Parser
3.5 EVALUATE Parser
9. Performance Benchmarks
9.1 Baseline Capture (Phase 0)
python -c "
import time
from cobolparser import CobolParser
from pathlib import Path
samples = list(Path('tests/samples').glob('*.cbl'))
parser = CobolParser()
start = time.perf_counter()
for _ in range(3):
    for f in samples:
        parser.parse_file(str(f))
elapsed = (time.perf_counter() - start) / 3
print(f'Average parse time (17 samples x3): {elapsed:.3f}s')
" > baselines/performance_baseline.txt
9.2 Acceptance Threshold
Parsing time shall not increase by more than 10% from baseline.
9.3 Verification (After Each Phase)
# Re-run benchmark, compare to baseline
python -c "..." > baselines/performance_phase_N.txt
10. Acceptance Criteria
Criterion	Target	Verification
Cyclomatic Complexity	No method > 10 in new parsers	radon cc cobolparser/parsers/ -a -s
CobolParser reduction	N methods removed (delegated)	Method count before/after
Test Coverage	100% branch in new parsers	pytest --cov=cobolparser/parsers --cov-branch
Regression	0 failing tests	pytest tests/ -v
Performance	< 10% slowdown	Benchmark comparison
Linting	0 pylint coupling warnings	pylint cobolparser/parsers/
11. Verification Commands Summary
Phase	Command
All Phases	python -m pytest tests/ -v --tb=short
Coverage	python -m pytest tests/ --cov=cobolparser --cov-report=html
Complexity	radon cc cobolparser/parser.py cobolparser/parsers/ -a -s
Integration	python -m pytest tests/integration/test_sample_programs.py -v
Contract	python -m pytest tests/contracts/test_sample_api_contracts.py -v
Performance	See Section 9.1 script
