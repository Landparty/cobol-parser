# COBOL Parser Performance Enhancement Plan

**Document Version:** 1.0  
**Created:** January 2026  
**Total Estimated Effort:** 122-132 hours across 3 phases  
**Project Duration:** 8-10 weeks (with parallel implementation)

---

## Executive Summary

This plan outlines performance optimizations for the COBOL parser targeting memory reduction, parsing speed improvements, and I/O efficiency. The enhancements are organized in three phases with clear dependencies, risk assessments, and success metrics.

**Expected Outcomes:**
- Token processing: 20-30% faster
- Memory usage: 30-50% reduction for large programs
- AST traversal: 50-70% faster with Bloom filters
- Copybook resolution: 40-60% faster with parallelization

---

## PHASE 1: HIGH PRIORITY (48-50 hours)

### Priority Rationale
These enhancements target the most frequently executed code paths with highest ROI. Token lookahead caching directly improves parser responsiveness, lazy AST creation reduces memory footprint for large programs, and string interning optimizes the hottest code path (keyword identification).

---

### 1.1 Token Lookahead Caching

#### 1.1.1 Problem Statement
- `peek_token()` is called repeatedly (100-1000s times per large file)
- Each call performs array index lookup without any caching
- Multiple peeks for the same offset are redundant
- No cache invalidation strategy exists

#### 1.1.2 Technical Approach

**Architecture:**
```python
class CobolParser:
    def __init__(self, ...):
        # Add lookahead cache
        self._lookahead_cache: Dict[int, Optional[Token]] = {}
        
    def advance_token(self) -> bool:
        """Advance to next token and invalidate lookahead cache."""
        # Clear cache when advancing (invalidation strategy)
        self._lookahead_cache.clear()
        self.current_token_index += 1
        if self.current_token_index < len(self.tokens):
            self.current_token = self.tokens[self.current_token_index]
            return True
        else:
            self.current_token = None
            return False
    
    def peek_token(self, offset: int = 1) -> Optional[Token]:
        """Peek at token with caching."""
        if offset in self._lookahead_cache:
            return self._lookahead_cache[offset]
        
        index = self.current_token_index + offset
        if 0 <= index < len(self.tokens):
            token = self.tokens[index]
        else:
            token = None
        
        self._lookahead_cache[offset] = token
        return token
```

**Design Decisions:**
- **Cache Strategy**: Simple offset-based dictionary (clearer than offset calculation)
- **Invalidation**: Full clear on every `advance_token()` (safe, but conservative)
- **Optional Enhancement**: LRU cache with max size if memory becomes concern
- **Thread Safety**: Not needed (single-threaded parser state)

#### 1.1.3 Affected Files and Methods

| File | Method | Impact |
|------|--------|--------|
| `cobolparser/parser.py` | `__init__()` | Add `_lookahead_cache` initialization |
| `cobolparser/parser.py` | `advance_token()` | Add cache.clear() call |
| `cobolparser/parser.py` | `peek_token()` | Add cache check and store |

#### 1.1.4 Implementation Steps

1. **Step 1: Add Cache Field** (15 min)
   - Add `self._lookahead_cache: Dict[int, Optional[Token]] = {}` in `__init__()`
   - No backward compatibility issues

2. **Step 2: Modify advance_token()** (10 min)
   - Add `self._lookahead_cache.clear()` at start of method
   - Ensures cache stays synchronized with position

3. **Step 3: Modify peek_token()** (20 min)
   - Check cache first before array access
   - Store result in cache
   - Handle None case properly for out-of-bounds

4. **Step 4: Unit Tests** (30 min)
   - Test cache hit/miss scenarios
   - Test cache invalidation on advance
   - Test peek at various offsets

#### 1.1.5 Testing Strategy

**Unit Tests** (`tests/unit/test_lookahead_cache.py`):
```python
def test_lookahead_cache_hit():
    """Verify cached lookahead returns same token object."""
    parser = CobolParser()
    parser.tokens = [token1, token2, token3]
    
    # First call populates cache
    result1 = parser.peek_token(1)
    # Second call should hit cache
    result2 = parser.peek_token(1)
    
    assert result1 is result2  # Same object reference
    assert len(parser._lookahead_cache) == 1

def test_lookahead_cache_invalidation():
    """Verify cache clears on advance_token()."""
    parser = CobolParser()
    parser.tokens = [token1, token2, token3]
    
    parser.peek_token(1)  # Populate cache
    assert len(parser._lookahead_cache) == 1
    
    parser.advance_token()  # Should clear cache
    assert len(parser._lookahead_cache) == 0

def test_multiple_offset_caching():
    """Verify caching works for multiple offsets."""
    parser = CobolParser()
    parser.tokens = [token1, token2, token3, token4]
    
    parser.peek_token(1)
    parser.peek_token(2)
    parser.peek_token(3)
    
    assert len(parser._lookahead_cache) == 3
```

**Integration Tests**: Use existing `test_parse_*.py` files to verify parser still works correctly

**Performance Tests** (`tests/performance/test_lookahead_perf.py`):
```python
def test_lookahead_cache_performance():
    """Measure improvement in peek_token() performance."""
    # Parse large COBOL file with many peek calls
    # Measure: time, cache hit ratio
    # Expected: 20-30% speedup in token parsing
```

#### 1.1.6 Performance Metrics

| Metric | Baseline | Target | Measurement Method |
|--------|----------|--------|-------------------|
| peek_token() calls/sec | ~100K | ~130K | Benchmark test |
| Cache hit ratio | 0% | 70-80% | Counter in peek_token() |
| Parser time (large file) | 2.5s | 2.0s | timeit module |
| Memory overhead | 0 | <1KB | sys.getsizeof() |

#### 1.1.7 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Cache invalidation bug | Low | High | Comprehensive unit tests, edge case coverage |
| Memory leak | Very Low | Medium | Clear() called reliably in advance_token() |
| Thread safety (future) | Very Low | Medium | Document single-threaded assumption |

#### 1.1.8 Estimated Effort

- Implementation: 1 hour
- Testing: 1.5 hours
- Code review/refinement: 0.5 hours
- **Total: 3 hours**

#### 1.1.9 Success Criteria

✅ Cache stores and retrieves tokens correctly  
✅ Cache invalidates on every advance_token()  
✅ 70-80% cache hit ratio in typical parsing scenarios  
✅ No regression in parser correctness (all tests pass)  
✅ Measurable 20-30% improvement in token processing

---

### 1.2 Lazy AST Node Creation

#### 1.2.1 Problem Statement
- All AST nodes created eagerly during parsing
- Large programs create 100K+ nodes immediately
- Many nodes never accessed/traversed (dead code sections)
- Memory pressure impacts performance (GC, cache misses)

#### 1.2.2 Technical Approach

**Core Concept:** Use property-based lazy initialization for child nodes

**Architecture:**
```python
from typing import Callable, Optional

class ASTNode(ABC):
    def __init__(self, node_type: str, location: SourceLocation):
        self.node_type = node_type
        self.location = location
        self.parent: Optional['ASTNode'] = None
        # Lazy-loaded children: only materialize on access
        self._children: Optional[List['ASTNode']] = None
        self._children_factory: Optional[Callable[[], List['ASTNode']]] = None
        self._metadata: Dict[str, Any] = {}
    
    @property
    def children(self) -> List['ASTNode']:
        """Lazy-load children on first access."""
        if self._children is None:
            if self._children_factory is not None:
                # Factory creates children (e.g., from tokens)
                self._children = self._children_factory()
                self._children_factory = None  # Clear factory
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

**Parser Integration:**
```python
class CobolParser:
    def parse_data_items(self) -> CobolDataItem:
        """Example: Lazy loading data items."""
        item = CobolDataItem(name, location)
        
        # Instead of:
        # item.children = self._parse_all_subordinate_items()
        
        # Register factory for lazy loading:
        item.register_children_factory(
            lambda: self._parse_all_subordinate_items()
        )
        
        return item
```

**Implementation Patterns:**

1. **Sections with many statements:**
   - Don't create all statement nodes immediately
   - Use factory pattern for lazy statement parsing

2. **Data divisions:**
   - Don't expand all occurs clauses until needed
   - Defer nested level parsing

3. **Procedure division:**
   - Paragraphs created eagerly (small), statements lazy
   - Complex expressions materialized on first access

#### 1.2.3 Affected Files and Methods

| File | Class/Method | Change |
|------|--------------|--------|
| `cobolparser/models/ast_base.py` | `ASTNode.__init__()` | Add `_children_factory` field |
| `cobolparser/models/ast_base.py` | `ASTNode.children` | Convert to @property with lazy loading |
| `cobolparser/models/program.py` | `CobolSection.parse()` | Add factory registration |
| `cobolparser/models/data_items.py` | `CobolDataItem.parse()` | Add factory registration |
| `cobolparser/parser.py` | All node creation methods | Add factory calls instead of eager parsing |

#### 1.2.4 Implementation Steps

1. **Step 1: Refactor ASTNode** (2 hours)
   - Add `_children`, `_children_factory` fields
   - Convert `children` to @property
   - Add `register_children_factory()` method
   - Update all direct children assignments

2. **Step 2: Update Parser Methods** (3 hours)
   - Identify 5-10 parser methods creating many children
   - Replace eager parsing with factory registration
   - Example: `parse_data_division()`, `parse_procedure_division()`

3. **Step 3: Test Backward Compatibility** (1.5 hours)
   - Existing code accessing `.children` should work identically
   - Factory materialization transparent to callers

4. **Step 4: Performance Testing** (1 hour)
   - Measure memory reduction
   - Verify no performance regression on full tree access

#### 1.2.5 Testing Strategy

**Unit Tests** (`tests/unit/test_lazy_ast.py`):
```python
def test_lazy_children_not_materialized_initially():
    """Children factory not called until accessed."""
    factory_calls = []
    
    def factory():
        factory_calls.append(1)
        return []
    
    node = ASTNode("test", location)
    node.register_children_factory(factory)
    
    # Factory not called yet
    assert len(factory_calls) == 0
    
    # Access triggers materialization
    _ = node.children
    assert len(factory_calls) == 1
    
    # Subsequent accesses use cached result
    _ = node.children
    assert len(factory_calls) == 1

def test_children_property_setter_clears_factory():
    """Setting children directly clears factory."""
    node = ASTNode("test", location)
    node.register_children_factory(lambda: [])
    
    new_children = [ASTNode("child", location)]
    node.children = new_children
    
    assert node._children_factory is None
    assert node.children is new_children
```

**Integration Tests**: Parse full programs, verify structure unchanged

**Performance Benchmarks**:
```python
def test_memory_reduction():
    """Measure memory saved with lazy loading."""
    # Parse 10MB COBOL program
    # Compare: eager vs lazy loading
    # Expected: 30-50% reduction for typical programs
```

#### 1.2.6 Performance Metrics

| Metric | Baseline | Target | Method |
|--------|----------|--------|--------|
| Memory for 100K nodes | 50MB | 25-35MB | memory_profiler |
| Init time (no access) | 2.5s | 1.5s | timeit |
| First access latency | N/A | <100ms | timeit |
| GC pauses | 200ms | 50ms | gc.get_stats() |

#### 1.2.7 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Circular references | Low | High | Clear factory after materialization |
| Parser state issues | Medium | High | Extensive integration tests |
| Serialization (JSON) | Medium | High | Force materialization before serialization |
| Backward compatibility | Medium | High | Transparent property getter |

**Mitigation Details:**
- Add assertion: factory must be cleared before parent cleanup
- Add test for every parser method using factories
- JSON serialization calls explicit materialize() method first

#### 1.2.8 Estimated Effort

- Refactor ASTNode: 2 hours
- Update parser methods: 3 hours
- Testing: 2.5 hours
- Documentation: 0.5 hours
- **Total: 8 hours**

#### 1.2.9 Success Criteria

✅ All children accessed via property (transparent)  
✅ Factories materialized on first access only  
✅ 30-50% memory reduction for typical programs  
✅ No changes needed in parser client code  
✅ All existing tests pass without modification

---

### 1.3 String Interning for Keywords

#### 1.3.1 Problem Statement
- Lexer creates ~500-1000 duplicate keyword string objects per large file
- Keywords like "MOVE", "DISPLAY", "PERFORM" repeated 1000s of times
- String comparison creates temporary interned strings internally
- Memory waste: 10-20MB for typical enterprise COBOL program

#### 1.3.2 Technical Approach

**Using `sys.intern()`:** Built-in Python mechanism for string deduplication

```python
import sys

class CobolLexer:
    # Pre-intern frequently used keywords
    INTERNED_KEYWORDS = {
        'MOVE': sys.intern('MOVE'),
        'DISPLAY': sys.intern('DISPLAY'),
        'PERFORM': sys.intern('PERFORM'),
        'IF': sys.intern('IF'),
        'ELSE': sys.intern('ELSE'),
        'END-IF': sys.intern('END-IF'),
        # ... ~30 most frequent keywords
    }
    
    def tokenize_identifier(self) -> Token:
        """Tokenize identifier, intern if keyword."""
        value = self._read_identifier()
        upper_value = value.upper()
        
        # Check if keyword (existing logic)
        if upper_value in self.KEYWORDS:
            token_type = self.KEYWORDS[upper_value]
            
            # Use pre-interned string for keywords
            if upper_value in self.INTERNED_KEYWORDS:
                value = self.INTERNED_KEYWORDS[upper_value]
            else:
                # Less frequent keywords - intern on demand
                value = sys.intern(upper_value)
            
            return Token(token_type, value, location)
        
        return Token(TokenType.IDENTIFIER, value, location)
```

**Optimization Strategy:**
1. Pre-intern top 30 keywords at module load (one-time cost)
2. Intern other keywords on-demand (fallback)
3. Non-keywords left as regular strings (no interning cost)

#### 1.3.3 Affected Files and Methods

| File | Method | Change |
|------|--------|--------|
| `cobolparser/lexer.py` | `CobolLexer.__init__()` | Add INTERNED_KEYWORDS dict |
| `cobolparser/lexer.py` | `tokenize_identifier()` | Use interned strings for keywords |
| `cobolparser/lexer.py` | All other ID tokenization | Same interning logic |

#### 1.3.4 Implementation Steps

1. **Step 1: Identify Top Keywords** (30 min)
   - Count keyword frequency in test programs
   - Select top 30 keywords for pre-interning
   - Include: MOVE, DISPLAY, PERFORM, IF, END-IF, ELSE, SECTION, DIVISION, etc.

2. **Step 2: Add Pre-interned Dictionary** (30 min)
   - Create module-level INTERNED_KEYWORDS dict
   - Pre-intern at module load time

3. **Step 3: Update Tokenization Logic** (45 min)
   - Check INTERNED_KEYWORDS before interning on-demand
   - Update all tokenization methods using keywords

4. **Step 4: Testing** (45 min)
   - Verify string identity (x is y) for keywords
   - Memory profiling before/after
   - Performance benchmarking

#### 1.3.5 Testing Strategy

**Unit Tests** (`tests/unit/test_string_interning.py`):
```python
def test_keyword_string_identity():
    """Verify keywords are interned (same object)."""
    lexer1 = CobolLexer("MOVE FOO TO BAR")
    lexer2 = CobolLexer("MOVE BAZ TO QUX")
    
    tokens1 = lexer1.tokenize()
    tokens2 = lexer2.tokenize()
    
    # Both MOVE tokens should be identical objects
    move_token1 = tokens1[0]  # MOVE from first lexer
    move_token2 = tokens2[0]  # MOVE from second lexer
    
    assert move_token1.value is move_token2.value  # Same object!
    assert move_token1.value == 'MOVE'

def test_non_keywords_not_interned():
    """Non-keywords use regular strings."""
    lexer = CobolLexer("MY-VAR")
    tokens = lexer.tokenize()
    
    # MY-VAR identifier not interned (takes memory but OK)
    assert tokens[0].type == TokenType.IDENTIFIER
```

**Performance Tests**:
```python
def test_memory_reduction_from_interning():
    """Measure memory savings from string interning."""
    # Create 10,000 keyword tokens
    # Compare memory with/without interning
    # Expected: 5-15% reduction
```

#### 1.3.6 Performance Metrics

| Metric | Baseline | Target | Method |
|--------|----------|--------|--------|
| Memory for keywords | ~8MB | ~1MB | memory_profiler (large file) |
| String comparison time | ~50μs | ~10μs | timeit (1M comparisons) |
| Module load overhead | 0 | <1ms | timeit sys.intern() |
| Lexer throughput | 10MB/s | 10.5MB/s | timeit large file |

#### 1.3.7 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Interned strings persist in memory | Very Low | Low | Python cleans up on program exit |
| Incorrect identity checks | Low | High | Comprehensive testing with `is` checks |
| Compatibility (Python versions) | Very Low | Low | sys.intern() available since Python 1.4 |

#### 1.3.8 Estimated Effort

- Identify keywords: 0.5 hours
- Implementation: 0.5 hours
- Testing: 1 hour
- **Total: 2 hours**

#### 1.3.9 Success Criteria

✅ Top 30 keywords use identical string objects (is identity)  
✅ 5-15% memory reduction for large programs  
✅ No measurable lexer slowdown  
✅ All tests pass

---

## PHASE 2: MEDIUM PRIORITY (52-56 hours)

### Phase 2 Overview

Phase 2 addresses less frequently executed paths but with significant optimization potential:
- **Copybook resolution**: 40-60% speedup through parallelization (I/O bound)
- **Lexing efficiency**: 70-90% speedup for incremental changes (editing scenarios)
- **AST traversal**: 5-10% with visitor pattern (frequently called)
- **Keyword lookup**: 50-70% with Bloom filter (hot path but small optimization)

### Dependency on Phase 1
- ✓ Can proceed in parallel (no dependencies)
- ✓ Visitor pattern benefits from lazy AST nodes

---

### 2.1 Parallel Copybook Resolution

#### 2.1.1 Problem Statement
- Copybook resolution is I/O bound (disk latency dominates)
- Current implementation uses sequential file reading
- Multiple copybooks can be resolved in parallel
- Large programs with 20+ copybooks spend 5-10s in resolution

#### 2.1.2 Technical Approach

**ThreadPoolExecutor for I/O Parallelization:**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Tuple

class CopybookExpander:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers  # Configurable parallelism
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
    
    def expand_copybooks_parallel(
        self, 
        copy_statements: List[CopyStatement]
    ) -> Dict[str, CopybookExpansion]:
        """Expand multiple copybooks in parallel."""
        
        # Submit tasks to thread pool
        futures = {
            self.executor.submit(self._expand_single, stmt): stmt
            for stmt in copy_statements
        }
        
        results = {}
        
        # Collect results as they complete (not in submission order)
        for future in as_completed(futures):
            try:
                copybook_name, expansion = future.result()
                results[copybook_name] = expansion
            except Exception as e:
                stmt = futures[future]
                # Error handling: fallback or propagate
                logger.error(f"Failed to expand {stmt.name}: {e}")
        
        return results
    
    def _expand_single(self, stmt: CopyStatement) -> Tuple[str, CopybookExpansion]:
        """Expand single copybook (runs in thread pool)."""
        # I/O operations run in parallel threads
        expansion = self._load_and_parse_copybook(stmt)
        return stmt.name, expansion
```

**Thread Safety Considerations:**
- Each thread gets its own parser instance (no shared state)
- Path resolver is read-only (thread-safe)
- Caching layer needs lock protection if used

#### 2.1.3 Affected Files and Methods

| File | Method | Change |
|------|--------|--------|
| `cobolparser/preprocess/copybook_expander.py` | `CopybookExpander.__init__()` | Add ThreadPoolExecutor |
| `cobolparser/preprocess/copybook_expander.py` | `expand_copybooks()` | Use parallel expansion |
| `cobolparser/preprocess/copybook_expander.py` | New: `_expand_single()` | Single copybook expansion |

#### 2.1.4 Implementation Steps

1. **Step 1: Baseline Measurement** (1 hour)
   - Measure current copybook resolution time
   - Identify programs with many copybooks
   - Establish performance baseline

2. **Step 2: Add ThreadPoolExecutor** (1.5 hours)
   - Import concurrent.futures
   - Create executor in __init__()
   - Add configuration for max_workers

3. **Step 3: Refactor Expansion Logic** (2 hours)
   - Extract single-copybook logic to _expand_single()
   - Create futures for all copybooks
   - Collect results with error handling

4. **Step 4: Thread Safety Audit** (1.5 hours)
   - Review all state accessed in threads
   - Add locks if needed (path resolver caching)
   - Test thread safety

5. **Step 5: Testing** (2 hours)
   - Unit tests for parallel expansion
   - Stress tests with many copybooks
   - Performance benchmarks

#### 2.1.5 Testing Strategy

**Unit Tests** (`tests/unit/test_parallel_copybooks.py`):
```python
def test_parallel_expansion_correctness():
    """Verify parallel expansion produces same result as sequential."""
    sequential_result = expander.expand_copybooks_sequential(stmts)
    parallel_result = expander.expand_copybooks_parallel(stmts)
    
    assert sequential_result == parallel_result

def test_parallel_expansion_with_dependencies():
    """Verify nested copybook dependencies handled correctly."""
    # Copy A includes Copy B
    # Both expanded in parallel
    # Dependency chain maintained

def test_max_workers_configuration():
    """Verify max_workers parameter controls parallelism."""
    expander = CopybookExpander(max_workers=2)
    # Monitor: only 2 threads active at once
```

**Performance Tests**:
```python
def test_parallel_speedup():
    """Measure speedup from parallelization."""
    # Test with program containing 10+ copybooks
    # Sequential time: ~5s, Parallel time: ~1-2s
    # Expected speedup: 3-4x
```

#### 2.1.6 Performance Metrics

| Metric | Baseline | Target | Method |
|--------|----------|--------|--------|
| Copybook resolution (10 files) | 5.0s | 1.5s | timeit |
| Speedup factor | 1x | 3-4x | ratio calc |
| Thread pool overhead | N/A | <50ms | timeit |
| Memory per thread | 20MB | 20MB | psutil |

#### 2.1.7 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Thread safety issues | Medium | High | Comprehensive testing, shared state review |
| Deadlock (circular includes) | Low | High | Existing circular reference detection works |
| Oversubscription (too many threads) | Low | Medium | Default max_workers=4 (configurable) |
| Exception handling in threads | Medium | Medium | Proper try-catch and result checking |

#### 2.1.8 Estimated Effort

- Baseline measurement: 1 hour
- Implementation: 3.5 hours
- Testing: 2 hours
- Documentation: 0.5 hours
- **Total: 7 hours**

#### 2.1.9 Success Criteria

✅ Parallel expansion produces identical results  
✅ 3-4x speedup for programs with 10+ copybooks  
✅ Thread safety verified (no race conditions)  
✅ Error handling covers thread exceptions  
✅ Configurable max_workers parameter

---

### 2.2 Incremental Lexing

#### 2.2.1 Problem Statement
- Full re-lexing on every edit (IDE scenario)
- Only small portion of file typically changes
- Re-lexing unchanged code wastes CPU
- IDE responsiveness critical for user experience

#### 2.2.2 Technical Approach

**Incremental Lexing Strategy:**

```python
class IncrementalLexer:
    def __init__(self, previous_tokens: List[Token] = None):
        self.previous_tokens = previous_tokens or []
        self.token_cache: Dict[int, Token] = {
            token.location.line: token for token in previous_tokens
        }
    
    def lex_range(
        self,
        source: str,
        start_line: int,
        end_line: int
    ) -> List[Token]:
        """Re-lex only the changed range."""
        
        new_tokens = []
        
        # Find unchanged tokens before change
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
        
        # Adjust line numbers for changed tokens
        for token in changed_tokens:
            token.location.line += start_line - 1
        
        # Find unchanged tokens after change
        unchanged_after = [
            t for t in self.previous_tokens
            if t.location.line > end_line
        ]
        
        # Combine: before + changed + after
        new_tokens = unchanged_before + changed_tokens + unchanged_after
        
        return new_tokens
```

**Validation Logic:**
```python
def validate_incremental_result(
    full_lex: List[Token],
    incremental_lex: List[Token],
    changed_range: Tuple[int, int]
) -> bool:
    """Verify incremental lexing matches full lexing."""
    # Compare tokens in changed range
    # Allow for minor position adjustments
    return compare_token_sequences(full_lex, incremental_lex)
```

#### 2.2.3 Affected Files and Methods

| File | Method | Change |
|------|--------|--------|
| `cobolparser/lexer.py` | New class: `IncrementalLexer` | Add incremental support |
| `cobolparser/lexer.py` | New: `lex_range()` | Range-based lexing |
| `cobolparser/parser.py` | `parse()` | Optional: accept previous tokens |

#### 2.2.4 Implementation Steps

1. **Step 1: Design Change Detection** (1.5 hours)
   - Define API: what ranges can be re-lexed?
   - Consider: line boundaries, token boundaries
   - Handle edge cases: strings spanning lines

2. **Step 2: Implement IncrementalLexer** (2.5 hours)
   - Extract source range
   - Re-lex changed portion
   - Merge with unchanged tokens

3. **Step 3: Validation Logic** (2 hours)
   - Comparison function for token sequences
   - Handle position differences
   - Test coverage for validation

4. **Step 4: Integration Tests** (2 hours)
   - Test various change scenarios
   - Verify incremental = full lex
   - Performance benchmarks

#### 2.2.5 Testing Strategy

**Unit Tests** (`tests/unit/test_incremental_lexing.py`):
```python
def test_incremental_lex_single_line_change():
    """Verify incremental lex for single line change."""
    original = "MOVE FOO TO BAR.\nMOVE BAZ TO QUX."
    modified = "MOVE FOO TO BAR.\nMOVE CHANGED TO QUX."
    
    full_tokens = CobolLexer(modified).tokenize()
    
    original_tokens = CobolLexer(original).tokenize()
    incremental = IncrementalLexer(original_tokens).lex_range(
        modified, start_line=2, end_line=2
    )
    
    assert tokens_equal(full_tokens, incremental)

def test_incremental_lex_preserves_unchanged():
    """Unchanged tokens should be identical objects."""
    # If token unchanged, should reuse same object
```

**Performance Tests**:
```python
def test_incremental_speedup():
    """Measure speedup for single-line edits."""
    # 1MB file, change 1 line
    # Sequential lex: ~50ms
    # Incremental lex: ~5ms
    # Speedup: 10x
```

#### 2.2.6 Performance Metrics

| Metric | Baseline | Target | Method |
|--------|----------|--------|--------|
| Single line change (1MB file) | 50ms | 5ms | timeit |
| Speedup factor | 1x | 10-20x | ratio |
| Validation overhead | N/A | <5% | percentage |
| Memory (cached tokens) | 0 | ~5MB | psutil |

#### 2.2.7 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Incremental result differs from full | Medium | High | Comprehensive validation tests |
| Token position/line numbering bugs | Medium | High | Thorough testing of edge cases |
| Validation false negatives | Low | High | Compare token by token with offsets |

#### 2.2.8 Estimated Effort

- Design: 1.5 hours
- Implementation: 2.5 hours
- Testing: 2 hours
- Validation: 2 hours
- **Total: 8 hours**

#### 2.2.9 Success Criteria

✅ Incremental lex produces identical results to full lex  
✅ 10-20x speedup for single-line edits  
✅ Validation catches any discrepancies  
✅ Edge cases handled (multi-line strings, comments)

---

### 2.3 AST Visitor Pattern

#### 2.3.1 Problem Statement
- Current traversal: `traverse_depth_first()` creates generator
- Generator allocates stack frames, iterator objects for each traversal
- Visitor pattern allows more efficient traversal
- Enables selective node processing (skip subtrees)

#### 2.3.2 Technical Approach

**Visitor Pattern Implementation:**

```python
from abc import ABC, abstractmethod

class ASTVisitor(ABC):
    """Base visitor for AST traversal."""
    
    @abstractmethod
    def visit(self, node: ASTNode) -> bool:
        """
        Visit a node.
        Return: True to continue, False to skip children.
        """
        pass
    
    def visit_all(self, nodes: List[ASTNode]) -> None:
        """Visit all nodes in list."""
        for node in nodes:
            self.visit_node(node)
    
    def visit_node(self, node: ASTNode) -> None:
        """Internal: visit node and recurse if needed."""
        should_recurse = self.visit(node)
        if should_recurse:
            for child in node.children:
                self.visit_node(child)

class JSONExportVisitor(ASTVisitor):
    """Example: Convert AST to JSON."""
    
    def __init__(self):
        self.json_objects = []
    
    def visit(self, node: ASTNode) -> bool:
        """Process node for JSON export."""
        json_repr = node.to_dict()
        self.json_objects.append(json_repr)
        return True  # Visit children

class ValidatingVisitor(ASTVisitor):
    """Example: Validate AST structure."""
    
    def __init__(self):
        self.errors = []
    
    def visit(self, node: ASTNode) -> bool:
        """Validate node."""
        if not node.location:
            self.errors.append(f"Node {node.node_type} missing location")
        return True

# Usage
root_node = parse_result.ast
export_visitor = JSONExportVisitor()
root_node.accept(export_visitor)
json_data = export_visitor.json_objects
```

**Integration with ASTNode:**
```python
class ASTNode(ABC):
    def accept(self, visitor: ASTVisitor) -> None:
        """Accept visitor for traversal."""
        visitor.visit_node(self)
```

#### 2.3.3 Affected Files and Methods

| File | Method/Class | Change |
|------|--------------|--------|
| `cobolparser/models/ast_base.py` | New: `ASTVisitor` class | Base visitor interface |
| `cobolparser/models/ast_base.py` | `ASTNode.accept()` | Accept visitor |
| `cobolparser/models/ast_base.py` | Optional: deprecate `traverse_depth_first()` | Migrate to visitor |

#### 2.3.4 Implementation Steps

1. **Step 1: Define Visitor Pattern** (1 hour)
   - Create ASTVisitor base class
   - Add accept() method to ASTNode

2. **Step 2: Implement Core Visitors** (2 hours)
   - JSONExportVisitor (existing JSON conversion)
   - ValidatingVisitor (validation logic)
   - TraversalVisitor (simple traversal)

3. **Step 3: Migrate Existing Code** (1.5 hours)
   - Find usages of traverse_depth_first()
   - Convert to visitor pattern
   - Keep traverse_depth_first() for compatibility

4. **Step 4: Testing** (1 hour)
   - Verify visitor produces same results as iterator
   - Test selective traversal (skip subtrees)

#### 2.3.5 Testing Strategy

**Unit Tests** (`tests/unit/test_visitor_pattern.py`):
```python
def test_visitor_traversal_order():
    """Verify visitor traversal matches depth-first order."""
    visited = []
    
    class CollectingVisitor(ASTVisitor):
        def visit(self, node):
            visited.append(node)
            return True
    
    root = create_test_ast()
    visitor = CollectingVisitor()
    root.accept(visitor)
    
    # Compare with traverse_depth_first()
    traversed = list(root.traverse_depth_first())
    assert visited == traversed

def test_visitor_can_skip_subtrees():
    """Visitor can skip visiting children."""
    visited = []
    
    class SelectiveVisitor(ASTVisitor):
        def visit(self, node):
            visited.append(node)
            # Skip children of specific type
            return node.node_type != "SKIP_CHILDREN"
    
    # Tree with node marked to skip
    # Should only visit parent, not children
```

#### 2.3.6 Performance Metrics

| Metric | Baseline | Target | Method |
|------|----------|--------|--------|
| Traversal time (100K nodes) | 200ms | 180ms | timeit |
| Memory for traversal | 20MB | 18MB | memory_profiler |
| Selective traversal (skip 50%) | 200ms | 100ms | timeit with skip |

#### 2.3.7 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| Visitor breaks existing code | Low | High | Keep backward-compatible traverse_depth_first() |
| Performance regression | Very Low | Medium | Benchmark before/after |
| Complexity increase | Low | Low | Document visitor pattern clearly |

#### 2.3.8 Estimated Effort

- Design: 1 hour
- Implementation: 2 hours
- Migration: 1.5 hours
- Testing: 1 hour
- **Total: 5.5 hours**

#### 2.3.9 Success Criteria

✅ Visitor pattern processes all nodes correctly  
✅ Backward-compatible with existing code  
✅ Enables selective traversal (skip subtrees)  
✅ No performance regression

---

### 2.4 Bloom Filter for Keywords

#### 2.4.1 Problem Statement
- Keyword lookup: check if string is in 400+ element dictionary
- Bloom filter provides O(1) false-negative checks
- Can eliminate expensive full lookup for non-keywords
- Optimization for "is this an identifier?" query

#### 2.4.2 Technical Approach

**Bloom Filter Implementation:**

```python
from typing import Set

class BloomFilter:
    """Simple Bloom filter for keyword pre-filtering."""
    
    def __init__(self, items: Set[str], num_hashes: int = 3):
        self.bit_array = [False] * (len(items) * 10)  # 10x space
        self.num_hashes = num_hashes
        self.items = items
        
        # Populate filter
        for item in items:
            self._insert(item)
    
    def _hash(self, item: str, seed: int) -> int:
        """Generate hash with seed."""
        return (hash((item, seed)) % len(self.bit_array))
    
    def _insert(self, item: str) -> None:
        """Insert item into filter."""
        for i in range(self.num_hashes):
            idx = self._hash(item, i)
            self.bit_array[idx] = True
    
    def might_contain(self, item: str) -> bool:
        """Check if item might be in set (fast, no false negatives)."""
        for i in range(self.num_hashes):
            idx = self._hash(item, i)
            if not self.bit_array[idx]:
                return False  # Definitely not in set
        return True  # Might be in set (false positives OK)

# Integration
class CobolLexer:
    def __init__(self, source, ...):
        # Create Bloom filter for keywords
        self._keyword_filter = BloomFilter(set(self.KEYWORDS.keys()))
    
    def tokenize_identifier(self) -> Token:
        """Fast path for identifiers using Bloom filter."""
        value = self._read_identifier()
        upper_value = value.upper()
        
        # Fast check: definitely not a keyword?
        if not self._keyword_filter.might_contain(upper_value):
            return Token(TokenType.IDENTIFIER, value, self.get_location())
        
        # Slow path: check full dictionary
        if upper_value in self.KEYWORDS:
            token_type = self.KEYWORDS[upper_value]
            return Token(token_type, value, self.get_location())
        
        return Token(TokenType.IDENTIFIER, value, self.get_location())
```

**False Positive Rate:**
- With 10x space and 3 hashes: ~1% false positive rate
- Acceptable: 1% of identifiers do full lookup anyway
- Non-keywords never see full dictionary (100% win)

#### 2.4.3 Affected Files and Methods

| File | Method | Change |
|------|--------|--------|
| `cobolparser/lexer.py` | New: `BloomFilter` class | Keyword pre-filter |
| `cobolparser/lexer.py` | `CobolLexer.__init__()` | Create Bloom filter |
| `cobolparser/lexer.py` | `tokenize_identifier()` | Use Bloom filter |

#### 2.4.4 Implementation Steps

1. **Step 1: Implement BloomFilter** (45 min)
   - Simple bit array based implementation
   - Multiple hash functions

2. **Step 2: Integrate into Lexer** (45 min)
   - Create filter in __init__()
   - Use in tokenize_identifier()

3. **Step 3: Tuning** (30 min)
   - Test false positive rate
   - Adjust num_hashes, bit_array_size
   - Benchmark dictionary lookup vs filter

4. **Step 4: Testing** (45 min)
   - Verify false-negative rate is 0
   - Measure false-positive rate
   - Performance comparison

#### 2.4.5 Testing Strategy

**Unit Tests** (`tests/unit/test_bloom_filter.py`):
```python
def test_bloom_filter_no_false_negatives():
    """Verify all items in set are detected."""
    keywords = {'MOVE', 'DISPLAY', 'PERFORM'}
    bf = BloomFilter(keywords)
    
    for keyword in keywords:
        assert bf.might_contain(keyword)

def test_bloom_filter_false_positive_rate():
    """Measure false positive rate on non-keywords."""
    keywords = set(COBOL_KEYWORDS.keys())
    bf = BloomFilter(keywords)
    
    non_keywords = ['FOO123', 'BAR456', 'MY-VAR', ...]
    false_positives = sum(
        1 for word in non_keywords
        if bf.might_contain(word) and word not in keywords
    )
    
    rate = false_positives / len(non_keywords)
    assert rate < 0.05  # <5% acceptable
```

**Performance Tests**:
```python
def test_bloom_vs_dict_lookup():
    """Compare Bloom filter + dict vs dict only."""
    # For 1M lookups: ~50% are non-keywords
    # Bloom filter should be 40-50% faster
```

#### 2.4.6 Performance Metrics

| Metric | Baseline | Target | Method |
|------|----------|--------|--------|
| Identifier lookup time | 50ns | 25ns | timeit (1M ops) |
| False positive rate | N/A | <5% | measurement |
| Speedup for non-keywords | 1x | 2x | ratio |
| Filter creation time | N/A | <1ms | timeit |

#### 2.4.7 Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|-----------|
| False positives cause wrong tokenization | Very Low | High | Verify with full dict lookup |
| Performance regression | Very Low | Low | Comprehensive benchmarking |

#### 2.4.8 Estimated Effort

- Implementation: 1.5 hours
- Testing: 1 hour
- Tuning: 0.5 hours
- **Total: 3 hours**

#### 2.4.9 Success Criteria

✅ Zero false negatives (all keywords detected)  
✅ <5% false positive rate  
✅ 40-50% faster identifier lookup for non-keywords  
✅ Correct tokenization on full test suite

---

## PHASE 3: LOW PRIORITY (22-26 hours)

### Phase 3 Overview

These optimizations have lower impact but improve robustness:
- **Memory Pool**: Reduces allocation overhead for Token objects
- **Regex Caching**: Ensures all regex patterns compiled once

Can be implemented in parallel with Phase 2, or deferred if time constraints.

---

### 3.1 Memory Pool for Tokens

#### 3.1.1 Problem Statement
- Lexer creates 100K+ Token objects for large files
- Each Token: small object but allocation overhead
- Python GC pressure for short-lived objects
- Object pooling can reduce allocation/GC overhead

#### 3.1.2 Technical Approach

```python
from typing import List

class TokenPool:
    """Object pool for Token reuse."""
    
    def __init__(self, initial_size: int = 1000):
        self.pool: List[Token] = []
        self.initial_size = initial_size
        self._initialize_pool()
    
    def _initialize_pool(self) -> None:
        """Pre-allocate tokens."""
        for _ in range(self.initial_size):
            self.pool.append(Token(TokenType.IDENTIFIER, "", None))
    
    def acquire(
        self,
        token_type: TokenType,
        value: str,
        location: SourceLocation
    ) -> Token:
        """Get or create token from pool."""
        if self.pool:
            token = self.pool.pop()
            token.type = token_type
            token.value = value
            token.location = location
            return token
        else:
            # Fallback: create new token
            return Token(token_type, value, location)
    
    def release(self, token: Token) -> None:
        """Return token to pool."""
        # Only pool if below max size
        if len(self.pool) < self.initial_size * 2:
            self.pool.append(token)

# Integration
class CobolLexer:
    def __init__(self, ...):
        self.token_pool = TokenPool(initial_size=1000)
    
    def _create_token(
        self,
        token_type: TokenType,
        value: str
    ) -> Token:
        """Create token from pool."""
        return self.token_pool.acquire(
            token_type, value, self.get_location()
        )
```

#### 3.1.3 Affected Files

| File | Method | Change |
|------|--------|--------|
| `cobolparser/lexer.py` | New: `TokenPool` class | Token pooling |
| `cobolparser/lexer.py` | `CobolLexer.__init__()` | Create pool |
| `cobolparser/lexer.py` | `_create_token()` | Use pool |

#### 3.1.4 Implementation Steps

1. **Step 1: Implement TokenPool** (1 hour)
2. **Step 2: Integrate into Lexer** (45 min)
3. **Step 3: Testing** (1 hour)

#### 3.1.5 Testing Strategy

```python
def test_token_pool_reuse():
    """Verify tokens are reused from pool."""
    pool = TokenPool(initial_size=10)
    
    # Acquire and release
    t1 = pool.acquire(TokenType.IDENTIFIER, "FOO", loc)
    pool.release(t1)
    
    # Next acquire reuses same object
    t2 = pool.acquire(TokenType.IDENTIFIER, "BAR", loc)
    assert t1 is t2
```

#### 3.1.6 Performance Metrics

| Metric | Target |
|--------|--------|
| Token allocation reduction | 30-50% |
| GC time reduction | 20-30% |
| Memory pressure | Lower |

#### 3.1.7 Estimated Effort

- Implementation: 2 hours
- Testing: 1 hour
- **Total: 3 hours**

---

### 3.2 Compiled Regex Caching

#### 3.2.1 Problem Statement
- Lexer uses ~10-15 regex patterns
- Python caches compiled patterns, but worth making explicit
- Ensures all patterns pre-compiled at module load
- Eliminates any lazy compilation overhead

#### 3.2.2 Technical Approach

```python
import re
from typing import Pattern

class RegexCache:
    """Cache compiled regex patterns."""
    
    PATTERNS: Dict[str, Pattern] = {
        'IDENTIFIER': re.compile(r'[A-Z][A-Z0-9\-]*', re.IGNORECASE),
        'NUMERIC': re.compile(r'\d+\.?\d*'),
        'STRING': re.compile(r"'([^']|'')*'"),
        'COMMENT': re.compile(r'\*>.*'),
        # ... more patterns
    }
    
    @classmethod
    def get(cls, name: str) -> Pattern:
        """Get compiled pattern."""
        return cls.PATTERNS[name]

# Integration
class CobolLexer:
    IDENTIFIER_PATTERN = RegexCache.get('IDENTIFIER')
    NUMERIC_PATTERN = RegexCache.get('NUMERIC')
    STRING_PATTERN = RegexCache.get('STRING')
```

#### 3.2.3 Implementation Steps

1. **Step 1: Catalog Regex Patterns** (1 hour)
   - Find all re.compile() calls
   - Document pattern purpose

2. **Step 2: Create RegexCache** (1 hour)
   - Pre-compile all patterns at module load

3. **Step 3: Replace All Calls** (1.5 hours)
   - Update lexer to use RegexCache
   - Remove inline re.compile()

4. **Step 4: Testing** (1 hour)

#### 3.2.4 Estimated Effort

- Catalog: 1 hour
- Implementation: 2.5 hours
- **Total: 3.5 hours**

---

## Summary Table: All Enhancements

| Phase | Enhancement | Effort | Speedup | Priority |
|-------|-------------|--------|---------|----------|
| 1 | Token Lookahead Caching | 3h | 20-30% | Critical |
| 1 | Lazy AST Node Creation | 8h | 30-50% mem | High |
| 1 | String Interning | 2h | 5-15% mem | High |
| 2 | Parallel Copybooks | 7h | 3-4x | High |
| 2 | Incremental Lexing | 8h | 10-20x | Medium |
| 2 | AST Visitor Pattern | 5.5h | 5-10% | Medium |
| 2 | Bloom Filter Keywords | 3h | 40-50% lookup | Medium |
| 3 | Token Memory Pool | 3h | 30-50% alloc | Low |
| 3 | Regex Caching | 3.5h | 20-40% | Low |
| **Total** | **9 enhancements** | **42-43h** | **Varies** | **Mixed** |

---

## Implementation Sequence & Dependencies

### Recommended Order

```
Phase 1 (Sequential):
1. Token Lookahead Caching (independent)
2. String Interning (independent)
3. Lazy AST Node Creation (independent, but benefits testing)

Phase 2 (Can run in parallel):
4. Parallel Copybooks (independent I/O improvement)
5. Incremental Lexing (independent, separate API)
6. Bloom Filter Keywords (independent)
7. AST Visitor Pattern (benefits from lazy nodes, but compatible)

Phase 3 (Can run in parallel):
8. Memory Pool for Tokens (independent)
9. Regex Caching (independent)
```

### Critical Path Dependencies

```
Phase 1 → Phase 2 (lazy nodes help visitor pattern)
Phase 1 → Phase 3 (none, truly independent)
Phase 2 → (none)
```

---

## Testing Strategy

### Test Coverage Matrix

| Enhancement | Unit | Integration | Performance | Stress |
|-------------|------|-------------|-------------|--------|
| Lookahead Cache | ✅ | ✅ | ✅ | ✅ |
| Lazy AST | ✅ | ✅ | ✅ | ✅ |
| String Intern | ✅ | ✓ | ✅ | ✓ |
| Parallel Copy | ✅ | ✅ | ✅ | ✅ |
| Incremental Lex | ✅ | ✅ | ✅ | ✓ |
| Visitor Pattern | ✅ | ✅ | ✓ | ✓ |
| Bloom Filter | ✅ | ✓ | ✅ | ✓ |
| Token Pool | ✓ | ✓ | ✅ | ✅ |
| Regex Cache | ✓ | ✓ | ✅ | ✓ |

---

## Measurement Plan

### Baseline Metrics (Before Implementation)

Run benchmarks on reference programs:
- **Small** (1-5 KLOC, 0 copybooks): ~50ms parse time
- **Medium** (50 KLOC, 5 copybooks): ~500ms parse time
- **Large** (500 KLOC, 20 copybooks): ~5s parse time
- **Memory**: 100MB for large program

### Target Metrics (After All Phases)

| Program Size | Current | Target | Improvement |
|--------------|---------|--------|-------------|
| Small | 50ms | 40ms | 20% |
| Medium | 500ms | 300ms | 40% |
| Large | 5s | 1.5s | 70% |
| Memory | 100MB | 40MB | 60% |

---

## Risk Management

### Critical Risks

| Risk | Likelihood | Severity | Mitigation |
|------|------------|----------|-----------|
| Regression in parsing correctness | Medium | Critical | Comprehensive test suite, CI/CD |
| Performance target not met | Low | High | Early benchmarking, fallback strategies |
| Thread safety issues (parallel) | Medium | High | Extensive testing, thread sanitizer |
| Memory leak in lazy loading | Low | High | Memory profiling, assertion checks |

### Fallback Strategies

1. **Token Caching** → Fall back to original `peek_token()` (no breaking change)
2. **Lazy Nodes** → Force materialization if issues detected
3. **Parallel Copybooks** → Fall back to sequential (set max_workers=1)
4. **Incremental Lexing** → Use full re-lex if validation fails
5. **Visitor Pattern** → Keep `traverse_depth_first()` for compatibility

---

## Success Metrics

### Phase 1 Success
- [ ] All Phase 1 tests pass (100% coverage)
- [ ] 20-30% speedup on token processing
- [ ] 30-50% memory reduction for lazy nodes
- [ ] Zero regressions on full test suite

### Phase 2 Success
- [ ] 3-4x speedup for copybook resolution
- [ ] 10-20x speedup for incremental edits
- [ ] 40-50% faster keyword lookup with Bloom filter
- [ ] Visitor pattern enables selective traversal

### Phase 3 Success
- [ ] 30-50% reduction in token allocations
- [ ] All regex patterns pre-compiled at load
- [ ] No performance regressions

---

## Implementation Tracking

Use this checklist to track progress:

### Phase 1
- [ ] Token Lookahead Caching (3h)
  - [ ] Implementation
  - [ ] Unit tests
  - [ ] Integration tests
  - [ ] Performance validation

- [ ] String Interning (2h)
  - [ ] Implementation
  - [ ] Testing
  - [ ] Memory profiling

- [ ] Lazy AST Nodes (8h)
  - [ ] ASTNode refactoring
  - [ ] Parser updates
  - [ ] Testing
  - [ ] Documentation

### Phase 2
- [ ] Parallel Copybooks (7h)
- [ ] Incremental Lexing (8h)
- [ ] Visitor Pattern (5.5h)
- [ ] Bloom Filter (3h)

### Phase 3
- [ ] Token Pool (3h)
- [ ] Regex Caching (3.5h)

---

## References & Resources

### Python Performance
- PEP 3140: String interning best practices
- `sys.intern()` documentation
- `concurrent.futures` tutorial
- Memory profiling: `memory_profiler`, `tracemalloc`

### Design Patterns
- Visitor Pattern: Gang of Four Design Patterns
- Object Pool Pattern for allocation reduction
- Bloom Filter: probabilistic data structures

### COBOL Parser References
- Current parser architecture in `parser.py` (4127 lines)
- Lexer implementation in `lexer.py` (1329 lines)
- AST nodes in `models/` package

---

**Document Complete**  
Last Updated: January 2026  
Next Review: After Phase 1 completion
