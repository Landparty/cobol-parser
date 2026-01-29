# Performance Enhancement Implementation Guide

**Quick Reference for Developers**

---

## Getting Started

The complete plan is in `PERFORMANCE_ENHANCEMENT_PLAN.md`. This guide provides quick implementation checklists for each enhancement.

---

## PHASE 1: High Priority (Week 1-2)

### Enhancement 1.1: Token Lookahead Caching

**Files to Modify:**
- `cobolparser/parser.py` (parser class)

**Quick Implementation:**
```python
# In CobolParser.__init__():
self._lookahead_cache: Dict[int, Optional[Token]] = {}

# Modify advance_token():
def advance_token(self) -> bool:
    self._lookahead_cache.clear()  # ADD THIS LINE
    self.current_token_index += 1
    # ... rest of method

# Modify peek_token():
def peek_token(self, offset: int = 1) -> Optional[Token]:
    if offset in self._lookahead_cache:  # ADD
        return self._lookahead_cache[offset]  # ADD
    
    index = self.current_token_index + offset
    if 0 <= index < len(self.tokens):
        token = self.tokens[index]
    else:
        token = None
    
    self._lookahead_cache[offset] = token  # ADD
    return token
```

**Tests to Add:**
- `tests/unit/test_lookahead_cache.py` (3 test cases)

**Verification:**
```bash
python -m pytest tests/unit/test_lookahead_cache.py -v
python -m pytest tests/ --cov=cobolparser -q  # Ensure no regression
```

**Time Estimate:** 3 hours

---

### Enhancement 1.2: String Interning for Keywords

**Files to Modify:**
- `cobolparser/lexer.py` (CobolLexer class)

**Quick Implementation:**
```python
import sys

class CobolLexer:
    # Add after KEYWORDS dict definition
    INTERNED_KEYWORDS = {
        'MOVE': sys.intern('MOVE'),
        'DISPLAY': sys.intern('DISPLAY'),
        'PERFORM': sys.intern('PERFORM'),
        'IF': sys.intern('IF'),
        'ELSE': sys.intern('ELSE'),
        'END-IF': sys.intern('END-IF'),
        'SECTION': sys.intern('SECTION'),
        'DIVISION': sys.intern('DIVISION'),
        # ... add top 30 keywords by frequency
    }
    
    # In tokenize_identifier() or equivalent:
    if upper_value in self.KEYWORDS:
        token_type = self.KEYWORDS[upper_value]
        
        # Use interned keyword string
        if upper_value in self.INTERNED_KEYWORDS:
            value = self.INTERNED_KEYWORDS[upper_value]
        else:
            value = sys.intern(upper_value)
        
        return Token(token_type, value, location)
```

**Tests to Add:**
- `tests/unit/test_string_interning.py` (2-3 test cases)

**Verification:**
```bash
python -c "
from cobolparser.lexer import CobolLexer
lexer = CobolLexer('MOVE FOO TO BAR')
tokens = lexer.tokenize()
# Check string identity: print(tokens[0].value is sys.intern('MOVE'))
"
```

**Time Estimate:** 2 hours

---

### Enhancement 1.3: Lazy AST Node Creation

**Files to Modify:**
- `cobolparser/models/ast_base.py` (ASTNode class)
- `cobolparser/parser.py` (multiple parse methods)

**Quick Implementation - ASTNode Refactoring:**
```python
from typing import Callable, Optional

class ASTNode(ABC):
    def __init__(self, node_type: str, location: SourceLocation):
        # ... existing code
        self._children: Optional[List['ASTNode']] = None
        self._children_factory: Optional[Callable[[], List['ASTNode']]] = None
    
    @property
    def children(self) -> List['ASTNode']:
        """Lazy-load children on first access."""
        if self._children is None:
            if self._children_factory is not None:
                self._children = self._children_factory()
                self._children_factory = None
            else:
                self._children = []
        return self._children
    
    @children.setter
    def children(self, value: List['ASTNode']) -> None:
        """Direct assignment clears factory."""
        self._children = value
        self._children_factory = None
    
    def register_children_factory(self, factory: Callable[[], List['ASTNode']]):
        """Register factory function for lazy loading."""
        self._children_factory = factory
```

**Parser Integration Example:**
```python
def parse_data_division(self) -> Optional[CobolDivision]:
    """Example: lazy load data items."""
    division = CobolDivision(name, location)
    
    # Instead of:
    # division.children = self._parse_sections()
    
    # Register factory:
    division.register_children_factory(lambda: self._parse_sections())
    return division
```

**Tests to Add:**
- `tests/unit/test_lazy_ast.py` (4-5 test cases covering materialization, identity, memory)

**Verification:**
```bash
python -m pytest tests/unit/test_lazy_ast.py::test_lazy_children_not_materialized_initially -v
memory_profiler # Measure memory reduction before/after
```

**Time Estimate:** 8 hours

---

## PHASE 2: Medium Priority (Week 3-4)

### Enhancement 2.1: Parallel Copybook Resolution

**Files to Modify:**
- `cobolparser/preprocess/copybook_expander.py`

**Quick Implementation:**
```python
from concurrent.futures import ThreadPoolExecutor, as_completed

class CopybookExpander:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers
    
    def expand_copybooks_parallel(
        self, 
        copy_statements: List[CopyStatement]
    ) -> Dict[str, CopybookExpansion]:
        """Expand multiple copybooks in parallel."""
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._expand_single, stmt): stmt
                for stmt in copy_statements
            }
            
            results = {}
            for future in as_completed(futures):
                try:
                    name, expansion = future.result()
                    results[name] = expansion
                except Exception as e:
                    stmt = futures[future]
                    # Handle error (log, skip, or propagate)
                    pass
        
        return results
    
    def _expand_single(self, stmt: CopyStatement) -> Tuple[str, CopybookExpansion]:
        """Expand single copybook (runs in thread)."""
        expansion = self._load_and_parse_copybook(stmt)
        return stmt.name, expansion
```

**Tests to Add:**
- `tests/unit/test_parallel_copybooks.py` (correctness, speedup)

**Time Estimate:** 7 hours

---

### Enhancement 2.2: Incremental Lexing

**Files to Modify:**
- `cobolparser/lexer.py` (new IncrementalLexer class)
- `cobolparser/parser.py` (optional: accept previous tokens)

**Quick Implementation:**
```python
class IncrementalLexer:
    def __init__(self, previous_tokens: List[Token] = None):
        self.previous_tokens = previous_tokens or []
    
    def lex_range(
        self,
        source: str,
        start_line: int,
        end_line: int
    ) -> List[Token]:
        """Re-lex only the changed range."""
        
        # Unchanged tokens before change
        unchanged_before = [
            t for t in self.previous_tokens
            if t.location.line < start_line
        ]
        
        # Re-lex changed range
        changed_source = '\n'.join(
            source.split('\n')[start_line-1:end_line]
        )
        lexer = CobolLexer(changed_source)
        changed_tokens = lexer.tokenize()
        
        # Adjust line numbers
        for token in changed_tokens:
            token.location.line += start_line - 1
        
        # Unchanged tokens after change
        unchanged_after = [
            t for t in self.previous_tokens
            if t.location.line > end_line
        ]
        
        return unchanged_before + changed_tokens + unchanged_after
```

**Tests to Add:**
- `tests/unit/test_incremental_lexing.py` (validation, performance)

**Time Estimate:** 8 hours

---

### Enhancement 2.3: AST Visitor Pattern

**Files to Modify:**
- `cobolparser/models/ast_base.py`

**Quick Implementation:**
```python
from abc import ABC, abstractmethod

class ASTVisitor(ABC):
    """Base visitor for AST traversal."""
    
    @abstractmethod
    def visit(self, node: 'ASTNode') -> bool:
        """Visit node. Return True to continue, False to skip children."""
        pass
    
    def visit_node(self, node: 'ASTNode') -> None:
        """Internal: visit and recurse."""
        should_recurse = self.visit(node)
        if should_recurse:
            for child in node.children:
                self.visit_node(child)

class ASTNode(ABC):
    # ... existing code
    
    def accept(self, visitor: ASTVisitor) -> None:
        """Accept visitor for traversal."""
        visitor.visit_node(self)
```

**Example Visitor:**
```python
class JSONExportVisitor(ASTVisitor):
    def __init__(self):
        self.json_objects = []
    
    def visit(self, node: ASTNode) -> bool:
        self.json_objects.append(node.to_dict())
        return True
```

**Tests to Add:**
- `tests/unit/test_visitor_pattern.py` (correctness, selectivity)

**Time Estimate:** 5.5 hours

---

### Enhancement 2.4: Bloom Filter for Keywords

**Files to Modify:**
- `cobolparser/lexer.py`

**Quick Implementation:**
```python
class BloomFilter:
    """Simple Bloom filter for keyword pre-filtering."""
    
    def __init__(self, items: Set[str], num_hashes: int = 3):
        self.bit_array = [False] * (len(items) * 10)
        self.num_hashes = num_hashes
        
        for item in items:
            self._insert(item)
    
    def _hash(self, item: str, seed: int) -> int:
        return (hash((item, seed)) % len(self.bit_array))
    
    def _insert(self, item: str) -> None:
        for i in range(self.num_hashes):
            idx = self._hash(item, i)
            self.bit_array[idx] = True
    
    def might_contain(self, item: str) -> bool:
        """Fast: return False = definitely not in set."""
        for i in range(self.num_hashes):
            idx = self._hash(item, i)
            if not self.bit_array[idx]:
                return False
        return True

# In CobolLexer
class CobolLexer:
    def __init__(self, ...):
        self._keyword_filter = BloomFilter(set(self.KEYWORDS.keys()))
    
    def tokenize_identifier(self) -> Token:
        value = self._read_identifier()
        upper_value = value.upper()
        
        # Fast check
        if not self._keyword_filter.might_contain(upper_value):
            return Token(TokenType.IDENTIFIER, value, self.location)
        
        # Slow check
        if upper_value in self.KEYWORDS:
            # ... handle keyword
```

**Tests to Add:**
- `tests/unit/test_bloom_filter.py` (no false negatives, FP rate)

**Time Estimate:** 3 hours

---

## PHASE 3: Low Priority (Week 5)

### Enhancement 3.1: Token Memory Pool

**Files to Modify:**
- `cobolparser/lexer.py`

**Quick Implementation:**
```python
class TokenPool:
    def __init__(self, initial_size: int = 1000):
        self.pool = []
        for _ in range(initial_size):
            self.pool.append(Token(TokenType.IDENTIFIER, "", None))
    
    def acquire(
        self,
        token_type: TokenType,
        value: str,
        location: SourceLocation
    ) -> Token:
        if self.pool:
            token = self.pool.pop()
            token.type = token_type
            token.value = value
            token.location = location
            return token
        return Token(token_type, value, location)
    
    def release(self, token: Token) -> None:
        if len(self.pool) < 2000:
            self.pool.append(token)
```

**Time Estimate:** 3 hours

---

### Enhancement 3.2: Compiled Regex Caching

**Files to Modify:**
- `cobolparser/lexer.py`

**Quick Implementation:**
```python
import re

class RegexCache:
    PATTERNS = {
        'IDENTIFIER': re.compile(r'[A-Z][A-Z0-9\-]*', re.IGNORECASE),
        'NUMERIC': re.compile(r'\d+\.?\d*'),
        'STRING': re.compile(r"'([^']|'')*'"),
        'COMMENT': re.compile(r'\*>.*'),
    }
    
    @classmethod
    def get(cls, name: str):
        return cls.PATTERNS[name]

# Usage in lexer
CobolLexer.IDENTIFIER_PATTERN = RegexCache.get('IDENTIFIER')
```

**Time Estimate:** 3.5 hours

---

## Testing Checklist

### Before Each Implementation
- [ ] Run full test suite: `pytest tests/ -v`
- [ ] Measure baseline metrics
- [ ] Document expected improvement

### After Each Implementation
- [ ] Add unit tests (minimum 80% coverage)
- [ ] Run full test suite (zero regressions)
- [ ] Run integration tests
- [ ] Measure performance improvement
- [ ] Memory profiling (if memory optimization)
- [ ] Document results

### Final Verification
- [ ] All Phase 1 tests pass
- [ ] All Phase 2 tests pass
- [ ] All Phase 3 tests pass
- [ ] Overall test coverage ≥ 90%
- [ ] Performance targets met
- [ ] Backward compatibility verified

---

## Performance Measurement Commands

```bash
# Baseline (current state)
python -m pytest tests/ -v --durations=10

# Memory profiling
python -m memory_profiler test_large_program.py

# CPU profiling
python -m cProfile -s cumtime parse_large_file.py

# Coverage report
python -m pytest --cov=cobolparser --cov-report=html tests/

# Benchmark enhancements
python tests/performance/benchmark_suite.py
```

---

## Rollback Procedure

If an enhancement causes issues:

1. **Identify**: Which enhancement caused regression?
2. **Disable**: Set feature flag or revert changes
3. **Investigate**: Run tests to isolate issue
4. **Fix**: Debug and re-implement
5. **Re-test**: Comprehensive test before retry

### Feature Flags (Optional)
```python
# In cobolparser/plugins/core.py
class FeatureFlags:
    LOOKAHEAD_CACHE = True
    LAZY_AST = True
    STRING_INTERNING = True
    PARALLEL_COPYBOOKS = True
    INCREMENTAL_LEXING = False  # Disable if issues
```

---

## Reference: File Locations

| Component | File |
|-----------|------|
| Parser | `cobolparser/parser.py` |
| Lexer | `cobolparser/lexer.py` |
| AST Base | `cobolparser/models/ast_base.py` |
| AST Program | `cobolparser/models/program.py` |
| AST Data Items | `cobolparser/models/data_items.py` |
| Copybook Expander | `cobolparser/preprocess/copybook_expander.py` |
| Plugins/Config | `cobolparser/plugins/core.py` |
| Tests | `tests/` |

---

## Contact & Questions

Refer to main plan: `PERFORMANCE_ENHANCEMENT_PLAN.md`

For detailed technical approaches, see corresponding sections in the main plan.
