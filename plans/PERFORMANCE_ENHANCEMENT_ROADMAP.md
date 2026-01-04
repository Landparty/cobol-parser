# COBOL Parser Performance Enhancement Roadmap

## Overview

This roadmap details three phases of performance optimization for the COBOL parser, focusing on parsing speed, memory efficiency, and throughput. Each phase includes technical specifications, implementation details, testing strategies, and performance metrics.

---

## PHASE 1: High Priority Optimizations

### 1.1 Token Lookahead Caching

**Purpose**: Reduce redundant `peek_token()` calls by caching results and invalidating on state changes.

**Technical Approach**:
```python
# Enhanced Lexer structure
class TokenLookaheadCache:
    def __init__(self, cache_size: int = 16):
        self.cache: Dict[int, Optional[Token]] = {}
        self.cache_size = cache_size
        self.position: int = 0
    
    def peek(self, offset: int) -> Optional[Token]:
        """Return cached token or fetch and cache"""
        if offset in self.cache:
            return self.cache[offset]
        token = self._fetch_token(offset)
        self._maintain_cache_size()
        self.cache[offset] = token
        return token
    
    def invalidate(self):
        """Clear cache on lexer position change"""
        self.cache.clear()
```

**Affected Files**:
- `cobolparser/lexer.py` - Modify `peek_token()` method
- `cobolparser/parser.py` - Update `advance_token()` to trigger cache invalidation

**Implementation Steps**:

1. **Create lookahead cache module** (`cobolparser/optimization/lookahead_cache.py`)
   - Implement `TokenLookaheadCache` class with LRU eviction
   - Add statistics tracking (hit rate, misses)
   
2. **Integrate into Lexer**
   ```python
   class Lexer:
       def __init__(self, source: str, ...):
           self.lookahead_cache = TokenLookaheadCache(cache_size=16)
       
       def peek_token(self, offset: int = 1) -> Optional[Token]:
           return self.lookahead_cache.peek(offset)
       
       def advance_token(self) -> Optional[Token]:
           token = self.current_token
           self.lookahead_cache.invalidate()
           # ... existing advance logic
           return token
   ```

3. **Update Parser peek patterns**
   - Replace multiple peek calls in conditional logic
   - Use cache statistics to tune cache size
   
4. **Configuration**
   ```python
   # cobolparser/plugins/core.py - Add to MemoryConfiguration
   class MemoryConfiguration:
       lookahead_cache_size: int = 16  # tokens to cache
       enable_cache_stats: bool = False  # track hit/miss
   ```

**Testing Strategy**:

- **Unit Tests** (`tests/unit/optimization/test_lookahead_cache.py`)
  - Test cache hit/miss on sequential peeks
  - Verify cache invalidation on advance
  - Test cache size limits and eviction
  - Benchmark peek performance with/without cache
  
- **Integration Tests**
  - Parse large COBOL programs with cache enabled
  - Verify parse results identical to non-cached version
  - Measure cache effectiveness across different program types
  
- **Regression Tests**
  - Existing parser tests must pass without modification
  - No change in parse accuracy or AST structure

**Performance Metrics**:

| Metric | Target | Baseline | Goal |
|--------|--------|----------|------|
| Lexer time reduction | -20-30% | N/A | ✓ |
| Cache hit rate | >70% | N/A | ✓ |
| Memory overhead | <2MB | N/A | ✓ |
| Programs/sec | +15-25% | N/A | ✓ |

**Estimated Effort**: 8-10 hours
- Module creation & testing: 5 hours
- Integration & benchmarking: 3-5 hours

---

### 1.2 Lazy AST Node Creation

**Purpose**: Defer child node creation until accessed, reducing memory and initialization overhead.

**Technical Approach**:

```python
from functools import cached_property

class LazyASTNode(ASTNode):
    """AST node with deferred child creation"""
    
    def __init__(self, node_type: str, location: SourceLocation):
        super().__init__(node_type, location)
        self._children_raw = []  # raw parsed data
        self._children_cache = None  # lazy-loaded children
    
    @cached_property
    def children(self) -> List[ASTNode]:
        """Children created on first access"""
        if self._children_cache is None:
            self._children_cache = [
                self._materialize_child(raw) 
                for raw in self._children_raw
            ]
        return self._children_cache
    
    def _materialize_child(self, raw_data):
        """Convert raw token data to AST node"""
        # Implement based on node type
        pass
```

**Affected Files**:
- `cobolparser/models/ast_base.py` - Base `ASTNode` class
- `cobolparser/models/program.py` - Division, Section classes
- `cobolparser/models/statements.py` - Statement nodes
- `cobolparser/parser.py` - Parser node creation logic

**Implementation Steps**:

1. **Create lazy loading base** (`cobolparser/models/ast_base.py`)
   - Modify `ASTNode` with lazy child support
   - Add `_materialize_child()` hook method
   - Implement `to_dict()` to trigger materialization only when serializing
   
2. **Update Division/Section classes**
   ```python
   class Division(LazyASTNode):
       def __init__(self, name: str, location: SourceLocation):
           super().__init__("Division", location)
           self.name = name
           self._children_raw = []  # sections stored as raw
       
       @cached_property
       def sections(self) -> List['Section']:
           return [Section._from_raw(raw) for raw in self._children_raw]
   ```

3. **Parser modifications**
   - Store raw token/location info instead of building nodes immediately
   - Create factory methods for deferred node creation
   - Track materialization statistics
   
4. **Configuration**
   ```python
   class MemoryConfiguration:
       lazy_ast_creation: bool = True
       track_materialization: bool = False  # for profiling
   ```

**Testing Strategy**:

- **Unit Tests** (`tests/unit/optimization/test_lazy_nodes.py`)
  - Create node, verify children uninitialized
  - Access children, verify lazy creation
  - Serialize node, verify materialization occurs
  - Memory profiling before/after first access
  
- **Integration Tests**
  - Parse program, don't access all children
  - Measure memory for "accessed" vs "unaccessed" paths
  - Deep traversal should show same results as eager creation
  
- **Compatibility Tests**
  - `to_dict()` must produce identical output
  - Visitor pattern must work with lazy nodes
  - Existing analysis code unaffected

**Performance Metrics**:

| Metric | Target | Baseline | Goal |
|--------|--------|----------|------|
| Memory reduction | -30-50% | N/A | ✓ |
| Time to first parse | -20-40% | N/A | ✓ |
| Memory if unused paths | -60-80% | N/A | ✓ |
| AST traversal time | Same | N/A | ✓ |

**Estimated Effort**: 12-15 hours
- Base implementation: 6-7 hours
- Full migration of models: 4-5 hours
- Testing & profiling: 2-3 hours

---

### 1.3 String Interning for Keywords

**Purpose**: Use `sys.intern()` to deduplicate keyword strings in the lexer, reducing memory for large programs with many repeated keywords.

**Technical Approach**:

```python
import sys
from typing import Set

class InternedKeywordLexer:
    """Lexer with keyword string interning"""
    
    # Pre-computed set of COBOL keywords for fast lookup
    COBOL_KEYWORDS: Set[str] = {
        'IDENTIFICATION', 'DIVISION', 'PROGRAM-ID', 'DATA',
        'WORKING-STORAGE', 'PROCEDURE', 'MOVE', 'DISPLAY',
        'PERFORM', 'IF', 'ELSE', 'END-IF', 'EVALUATE',
        # ... all COBOL keywords
    }
    
    def __init__(self, source: str):
        self.source = source
        self.interned_strings: Dict[str, str] = {}
    
    def _intern_keyword(self, text: str) -> str:
        """Intern keyword string for memory efficiency"""
        upper_text = text.upper()
        
        # Check if already interned
        if upper_text in self.interned_strings:
            return self.interned_strings[upper_text]
        
        # Fast-path for known keywords
        if upper_text in self.COBOL_KEYWORDS:
            interned = sys.intern(upper_text)
            self.interned_strings[upper_text] = interned
            return interned
        
        return upper_text
    
    def _create_token(self, token_type: str, value: str, 
                      location: SourceLocation) -> Token:
        """Create token with interned string if applicable"""
        interned_value = (
            self._intern_keyword(value) 
            if token_type in ('KEYWORD', 'IDENTIFIER') 
            else value
        )
        return Token(token_type, interned_value, location)
```

**Affected Files**:
- `cobolparser/lexer.py` - Token creation and keyword handling
- `cobolparser/models/ast_base.py` - Token storage
- `cobolparser/plugins/core.py` - Configuration

**Implementation Steps**:

1. **Create keyword interning utility** (`cobolparser/optimization/string_interning.py`)
   - Maintain pre-computed keyword set
   - Implement interning with statistics
   - Add bloom filter for keyword lookup (optional)
   
2. **Modify Lexer tokenization**
   ```python
   class Lexer:
       def __init__(self, source: str, config: MemoryConfiguration):
           self.source = source
           self.intern_keywords = config.enable_string_interning
           self.keyword_set = self._build_keyword_set()
       
       def _build_keyword_set(self) -> frozenset:
           # Pre-load all COBOL keywords
           return frozenset([...keywords...])
       
       def _tokenize_word(self, word: str) -> Token:
           if self.intern_keywords and word.upper() in self.keyword_set:
               value = sys.intern(word.upper())
           else:
               value = word
           return Token('KEYWORD' if ... else 'IDENTIFIER', value, ...)
   ```

3. **Configuration option**
   ```python
   class MemoryConfiguration:
       enable_string_interning: bool = True  # default enabled
       intern_identifiers: bool = False      # only keywords by default
   ```

4. **Statistics tracking**
   ```python
   @dataclass
   class InterningStatistics:
       total_keywords: int
       interned_count: int
       memory_saved_bytes: int
       hit_rate: float
   ```

**Testing Strategy**:

- **Unit Tests** (`tests/unit/optimization/test_string_interning.py`)
  - Verify keyword interning (object identity with `is`)
  - Check non-keyword handling (no interning)
  - Measure memory of interned vs non-interned strings
  - Verify statistics accuracy
  
- **Integration Tests**
  - Parse programs with many repeated keywords
  - Verify lexer output identical with/without interning
  - Memory profiling on large programs
  
- **Performance Tests**
  - Memory reduction measurement
  - Lexer speed impact (should be minimal)
  - Keyword lookup performance

**Performance Metrics**:

| Metric | Target | Baseline | Goal |
|--------|--------|----------|------|
| Memory reduction | -5-15% | N/A | ✓ |
| Lexer time | Same/+2% | N/A | ✓ |
| Keyword lookup | O(1) | N/A | ✓ |

**Estimated Effort**: 4-5 hours
- Implementation: 2 hours
- Testing: 1.5 hours
- Integration: 1-1.5 hours

---

## PHASE 2: Medium Priority Optimizations

### 2.1 Parallel Copybook Resolution

**Purpose**: Resolve multiple copybooks concurrently using `ThreadPoolExecutor` to reduce I/O wait time.

**Technical Approach**:

```python
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List

class ParallelCopybookResolver:
    """Resolve copybooks in parallel"""
    
    def __init__(self, max_workers: int = 4, 
                 timeout: float = 30.0):
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.timeout = timeout
        self.resolution_cache: Dict[str, str] = {}
    
    def resolve_copybooks(self, 
                         copybook_names: List[str],
                         search_paths: List[str]) -> Dict[str, str]:
        """Resolve multiple copybooks in parallel"""
        
        futures = {}
        for name in copybook_names:
            # Skip already resolved
            if name in self.resolution_cache:
                continue
            
            future = self.executor.submit(
                self._resolve_single,
                name,
                search_paths
            )
            futures[future] = name
        
        results = {}
        for future in as_completed(futures, timeout=self.timeout):
            name = futures[future]
            try:
                content = future.result()
                results[name] = content
                self.resolution_cache[name] = content
            except Exception as e:
                logger.error(f"Failed to resolve {name}: {e}")
                results[name] = None
        
        return results
    
    def _resolve_single(self, name: str, 
                       search_paths: List[str]) -> str:
        """Resolve single copybook (runs in thread)"""
        for path in search_paths:
            file_path = os.path.join(path, f"{name}.cpy")
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    return f.read()
        raise FileNotFoundError(f"Copybook {name} not found")
```

**Affected Files**:
- `cobolparser/preprocess/copybook_expander.py` - Main copybook expansion
- `cobolparser/plugins/core.py` - Configuration

**Implementation Steps**:

1. **Create parallel resolver** (`cobolparser/optimization/parallel_copybook.py`)
   - Implement `ParallelCopybookResolver` class
   - Add thread-safe caching
   - Error handling and timeout logic
   - Statistics tracking
   
2. **Integrate into CopybookExpander**
   ```python
   class CopybookExpander:
       def __init__(self, config: MemoryConfiguration):
           self.config = config
           if config.parallel_copybooks:
               self.resolver = ParallelCopybookResolver(
                   max_workers=config.copybook_workers
               )
           else:
               self.resolver = SequentialCopybookResolver()
       
       def expand_copybooks(self, program: Program) -> Program:
           # Extract all copybook references first
           copybooks = self._extract_copybook_refs(program)
           
           # Resolve in parallel
           resolved = self.resolver.resolve_copybooks(
               copybooks,
               self.search_paths
           )
           
           # Inline resolved content
           return self._inline_copybooks(program, resolved)
   ```

3. **Configuration**
   ```python
   class MemoryConfiguration:
       parallel_copybooks: bool = True
       copybook_workers: int = 4  # thread pool size
       copybook_timeout: float = 30.0  # seconds
   ```

4. **Thread safety**
   - Use thread-safe cache (e.g., `threading.Lock`)
   - Avoid shared mutable state in worker threads
   - Proper exception propagation

**Testing Strategy**:

- **Unit Tests** (`tests/unit/optimization/test_parallel_copybook.py`)
  - Mock file system for deterministic testing
  - Test parallel resolution of multiple copybooks
  - Verify error handling (missing files, timeouts)
  - Thread safety with concurrent access
  
- **Integration Tests**
  - Parse program with many copybooks
  - Verify sequential vs parallel results identical
  - Measure speedup with varying worker counts
  
- **Performance Tests**
  - Measure I/O time reduction
  - Optimal worker count determination
  - Timeout behavior testing

**Performance Metrics**:

| Metric | Target | Baseline | Goal |
|--------|--------|----------|------|
| Copybook resolution time | -40-60% | N/A | ✓ |
| Scaling efficiency | 2-3x with 4 workers | N/A | ✓ |
| Memory overhead | <5MB | N/A | ✓ |
| Programs with many copybooks | -50%+ | N/A | ✓ |

**Estimated Effort**: 10-12 hours
- Parallel resolver implementation: 4-5 hours
- Integration & synchronization: 3-4 hours
- Testing & benchmarking: 3-4 hours

---

### 2.2 Incremental Lexing

**Purpose**: Re-lex only changed portions of source code for faster iterative parsing.

**Technical Approach**:

```python
from dataclasses import dataclass
from typing import List, Tuple

@dataclass
class LineRange:
    start: int  # line number
    end: int
    
    def contains(self, line: int) -> bool:
        return self.start <= line <= self.end

class IncrementalLexer:
    """Lex only changed portions of source"""
    
    def __init__(self, source: str, full_lexer: Lexer):
        self.source = source
        self.full_lexer = full_lexer
        self.token_cache: Dict[int, Token] = {}  # line -> tokens
        self.version = 0
    
    def update(self, new_source: str, 
               changed_lines: LineRange) -> List[Token]:
        """Lex only changed lines"""
        
        self.source = new_source
        self.version += 1
        
        # Invalidate affected tokens
        for line in range(changed_lines.start, changed_lines.end + 1):
            self.token_cache.pop(line, None)
        
        # Re-lex only changed region
        changed_text = '\n'.join(
            self.source.split('\n')[
                changed_lines.start:changed_lines.end + 1
            ]
        )
        
        new_tokens = self.full_lexer.tokenize(changed_text)
        
        # Cache new tokens
        for token in new_tokens:
            line = token.location.line
            if line not in self.token_cache:
                self.token_cache[line] = []
            self.token_cache[line].append(token)
        
        return new_tokens
    
    def get_all_tokens(self) -> List[Token]:
        """Reconstruct full token stream from cache"""
        all_tokens = []
        for line in sorted(self.token_cache.keys()):
            all_tokens.extend(self.token_cache[line])
        return all_tokens
```

**Affected Files**:
- `cobolparser/lexer.py` - Add incremental lexing support
- `cobolparser/parser.py` - Parser invalidation on token changes
- `cobolparser/plugins/core.py` - Configuration

**Implementation Steps**:

1. **Create incremental lexer** (`cobolparser/optimization/incremental_lexer.py`)
   - Implement change tracking
   - Line-based token caching
   - Invalidation logic
   
2. **Modify base Lexer**
   ```python
   class Lexer:
       def __init__(self, source: str, incremental: bool = False):
           self.source = source
           self.incremental = incremental
           if incremental:
               self.incremental_state = IncrementalLexerState()
       
       def update_source(self, new_source: str, 
                         changed_lines: LineRange) -> List[Token]:
           """Update with incremental lexing"""
           if self.incremental:
               return self.incremental_state.update(
                   new_source, changed_lines
               )
           # Fall back to full re-lex
           return self.tokenize(new_source)
   ```

3. **Change tracking utility**
   ```python
   class SourceChangeDetector:
       """Detect changed lines between versions"""
       
       @staticmethod
       def detect_changes(old_source: str, 
                         new_source: str) -> LineRange:
           old_lines = old_source.split('\n')
           new_lines = new_source.split('\n')
           
           # Find first difference
           start = 0
           for i, (old, new) in enumerate(zip(old_lines, new_lines)):
               if old != new:
                   start = i
                   break
           
           # Find last difference
           end = max(len(old_lines), len(new_lines))
           # ... implement end detection
           
           return LineRange(start, end)
   ```

4. **Configuration**
   ```python
   class MemoryConfiguration:
       incremental_lexing: bool = False  # opt-in
       incremental_cache_size: int = 1000  # tokens
   ```

**Testing Strategy**:

- **Unit Tests** (`tests/unit/optimization/test_incremental_lexer.py`)
  - Single line changes
  - Multi-line changes
  - Addition/deletion of lines
  - Cache invalidation correctness
  - Full reconstruction matches original
  
- **Integration Tests**
  - Iterative parsing (simulate editor)
  - Verify parse results identical
  - Measure speedup percentage
  
- **Edge Cases**
  - Changes at division boundaries
  - Multiline statements
  - Comments spanning lines

**Performance Metrics**:

| Metric | Target | Baseline | Goal |
|--------|--------|----------|------|
| Re-lex time (small change) | -70-90% | N/A | ✓ |
| Cache hit rate | >80% | N/A | ✓ |
| Memory for cache | <10MB | N/A | ✓ |
| IDE responsiveness | 100x faster | N/A | ✓ |

**Estimated Effort**: 14-16 hours
- Change detection: 3-4 hours
- Incremental lexer: 5-6 hours
- Integration & cache: 3-4 hours
- Testing: 3-4 hours

---

### 2.3 AST Visitor Pattern

**Purpose**: Replace recursive `traverse_depth_first()` with visitor pattern for better memory efficiency and flexibility.

**Technical Approach**:

```python
from abc import ABC, abstractmethod
from typing import Any, Generic, TypeVar

T = TypeVar('T')

class ASTVisitor(ABC, Generic[T]):
    """Base visitor for AST traversal"""
    
    @abstractmethod
    def visit_program(self, node: Program) -> T:
        pass
    
    @abstractmethod
    def visit_division(self, node: Division) -> T:
        pass
    
    @abstractmethod
    def visit_section(self, node: Section) -> T:
        pass
    
    @abstractmethod
    def visit_statement(self, node: Statement) -> T:
        pass
    
    def visit(self, node: ASTNode) -> T:
        """Dispatch to appropriate visit method"""
        method_name = f"visit_{node.node_type.lower()}"
        method = getattr(self, method_name, self.generic_visit)
        return method(node)
    
    def generic_visit(self, node: ASTNode) -> T:
        """Fallback for unhandled node types"""
        pass

class AnalysisVisitor(ASTVisitor):
    """Example: collect all variable references"""
    
    def __init__(self):
        self.variables: Set[str] = set()
    
    def visit_program(self, node: Program) -> None:
        for division in node.divisions:
            self.visit(division)
    
    def visit_data_item(self, node: DataItem) -> None:
        self.variables.add(node.name)
        for child in node.children:
            self.visit(child)
    
    def visit_statement(self, node: Statement) -> None:
        # Extract variable references from statement
        pass

# Usage in AST base class
class ASTNode:
    def accept(self, visitor: ASTVisitor) -> Any:
        """Accept visitor for traversal"""
        return visitor.visit(self)
```

**Affected Files**:
- `cobolparser/models/ast_base.py` - Add visitor support
- `cobolparser/analysis/` - Convert analyzers to visitors
- `cobolparser/parser.py` - Optional optimization

**Implementation Steps**:

1. **Create visitor framework** (`cobolparser/models/visitor.py`)
   - Base `ASTVisitor` abstract class
   - Default visitor implementations
   - Visitor composition utilities
   
2. **Add visitor support to ASTNode**
   ```python
   class ASTNode:
       def accept(self, visitor: ASTVisitor) -> Any:
           """Accept visitor for double-dispatch"""
           return visitor.visit(self)
   ```

3. **Convert existing analyzers to visitors**
   - `value_tracker.py` → `ValueTrackerVisitor`
   - Any other analysis code
   
4. **Visitor composition**
   ```python
   class CompositeVisitor(ASTVisitor):
       """Combine multiple visitors"""
       def __init__(self, *visitors: ASTVisitor):
           self.visitors = visitors
       
       def visit(self, node: ASTNode) -> List[Any]:
           return [v.visit(node) for v in self.visitors]
   ```

**Testing Strategy**:

- **Unit Tests** (`tests/unit/models/test_visitor.py`)
  - Visitor dispatch correctness
  - All node types handled
  - Composition of visitors
  - Result correctness matches old traversal
  
- **Integration Tests**
  - Convert existing analyzers
  - Verify same results as before
  - No performance regression
  
- **Compatibility Tests**
  - Old `traverse_depth_first()` deprecated but functional
  - Migration guide for users

**Performance Metrics**:

| Metric | Target | Baseline | Goal |
|--------|--------|----------|------|
| Traversal speed | +5-10% | N/A | ✓ |
| Code clarity | Better | N/A | ✓ |
| Memory for stack | -20-30% | N/A | ✓ |
| Multiple passes | -40-50% | N/A | ✓ |

**Estimated Effort**: 12-14 hours
- Visitor framework: 3-4 hours
- Integration into AST: 2-3 hours
- Analyzer migration: 3-4 hours
- Testing: 2-3 hours

---

### 2.4 Bloom Filter for Keywords

**Purpose**: Pre-filter identifiers using Bloom filter before expensive keyword set lookup.

**Technical Approach**:

```python
from typing import Set

class BloomFilter:
    """Space-efficient set membership testing"""
    
    def __init__(self, items: Set[str], false_positive_rate: float = 0.01):
        self.size = self._calculate_size(len(items), false_positive_rate)
        self.hash_count = self._calculate_hash_count(
            self.size, len(items)
        )
        self.bits = bytearray((self.size + 7) // 8)
        
        # Add all items
        for item in items:
            self._add(item)
    
    def _add(self, item: str):
        """Add item to filter"""
        for i in range(self.hash_count):
            hash_val = self._hash(item, i)
            byte_idx = hash_val // 8
            bit_idx = hash_val % 8
            self.bits[byte_idx] |= (1 << bit_idx)
    
    def contains(self, item: str) -> bool:
        """Test membership (may return false positives)"""
        for i in range(self.hash_count):
            hash_val = self._hash(item, i)
            byte_idx = hash_val // 8
            bit_idx = hash_val % 8
            if not (self.bits[byte_idx] & (1 << bit_idx)):
                return False
        return True
    
    def _hash(self, item: str, seed: int) -> int:
        """Hash function with seed"""
        h = hash((item, seed)) % self.size
        return abs(h)
    
    @staticmethod
    def _calculate_size(n: int, fp_rate: float) -> int:
        """Calculate bit array size for target false positive rate"""
        import math
        return int(-n * math.log(fp_rate) / (math.log(2) ** 2))
    
    @staticmethod
    def _calculate_hash_count(m: int, n: int) -> int:
        """Calculate optimal number of hash functions"""
        import math
        return max(1, int((m / n) * math.log(2)))

class OptimizedKeywordLexer:
    """Lexer using Bloom filter for keyword lookup"""
    
    KEYWORDS = frozenset([...all COBOL keywords...])
    
    def __init__(self):
        self.bloom_filter = BloomFilter(self.KEYWORDS)
        self.keyword_set = self.KEYWORDS
    
    def is_keyword(self, text: str) -> bool:
        """Fast keyword check using Bloom filter"""
        upper_text = text.upper()
        
        # Bloom filter fast-path
        if not self.bloom_filter.contains(upper_text):
            return False  # Definitely not a keyword
        
        # Confirm with exact set (handles rare false positives)
        return upper_text in self.keyword_set
```

**Affected Files**:
- `cobolparser/lexer.py` - Keyword lookup
- `cobolparser/optimization/bloom_filter.py` - Implementation
- `cobolparser/plugins/core.py` - Configuration

**Implementation Steps**:

1. **Create Bloom filter** (`cobolparser/optimization/bloom_filter.py`)
   - Implement Bloom filter with configurable parameters
   - Performance-optimized hash functions
   - Statistics tracking
   
2. **Integrate into Lexer**
   ```python
   class Lexer:
       def __init__(self, source: str, use_bloom_filter: bool = True):
           self.source = source
           if use_bloom_filter:
               self.keyword_filter = BloomFilter(self.COBOL_KEYWORDS)
           else:
               self.keyword_filter = None
       
       def _is_keyword(self, text: str) -> bool:
           if self.keyword_filter:
               return self.keyword_filter.contains(text.upper())
           return text.upper() in self.COBOL_KEYWORDS
   ```

3. **Configuration**
   ```python
   class MemoryConfiguration:
       use_keyword_bloom_filter: bool = True
       bloom_filter_fp_rate: float = 0.01  # 1% false positives
   ```

**Testing Strategy**:

- **Unit Tests** (`tests/unit/optimization/test_bloom_filter.py`)
  - All COBOL keywords recognized
  - Non-keywords rejected
  - False positive rate within tolerance
  - Memory usage verification
  - Performance comparison
  
- **Integration Tests**
  - Lexer with/without Bloom filter identical results
  - No change in parse accuracy
  
- **Benchmark Tests**
  - Keyword lookup speed improvement
  - Memory footprint of filter
  - Hash function performance

**Performance Metrics**:

| Metric | Target | Baseline | Goal |
|--------|--------|----------|------|
| Keyword lookup speed | -50-70% | N/A | ✓ |
| False positive rate | <1% | N/A | ✓ |
| Memory overhead | <100KB | N/A | ✓ |
| Lexer throughput | +10-15% | N/A | ✓ |

**Estimated Effort**: 6-8 hours
- Bloom filter implementation: 2-3 hours
- Lexer integration: 1-2 hours
- Testing & benchmarking: 2-3 hours

---

## PHASE 3: Low Priority Optimizations

### 3.1 Memory Pool for Tokens

**Purpose**: Use object pooling to reduce allocation/deallocation overhead for frequently-created Token objects.

**Technical Approach**:

```python
from typing import List
import threading

class TokenPool:
    """Object pool for Token reuse"""
    
    def __init__(self, initial_size: int = 1000):
        self.pool: List[Token] = [
            Token(None, None, None) for _ in range(initial_size)
        ]
        self.available = set(range(initial_size))
        self.lock = threading.Lock()
        self.stats = PoolStatistics()
    
    def acquire(self, token_type: str, value: str, 
                location: SourceLocation) -> Token:
        """Get token from pool, allocate if needed"""
        with self.lock:
            if self.available:
                idx = self.available.pop()
                token = self.pool[idx]
                token.reset(token_type, value, location)
                self.stats.allocations += 1
            else:
                token = Token(token_type, value, location)
                self.pool.append(token)
                self.stats.pool_expansions += 1
        
        return token
    
    def release(self, token: Token):
        """Return token to pool"""
        with self.lock:
            token.reset(None, None, None)
            self.available.add(len(self.pool))
            self.stats.releases += 1
    
    @property
    def utilization(self) -> float:
        """Pool utilization percentage"""
        with self.lock:
            return 1.0 - len(self.available) / len(self.pool)

@dataclass
class PoolStatistics:
    allocations: int = 0
    releases: int = 0
    pool_expansions: int = 0

# Token must support pooling
class Token:
    def __init__(self, token_type: str, value: str, 
                 location: SourceLocation):
        self.token_type = token_type
        self.value = value
        self.location = location
    
    def reset(self, token_type: str, value: str, 
              location: SourceLocation):
        """Reset for reuse"""
        self.token_type = token_type
        self.value = value
        self.location = location
```

**Affected Files**:
- `cobolparser/lexer.py` - Token creation
- `cobolparser/models/ast_base.py` - Token class
- `cobolparser/optimization/token_pool.py` - Implementation
- `cobolparser/plugins/core.py` - Configuration

**Implementation Steps**:

1. **Create token pool** (`cobolparser/optimization/token_pool.py`)
   - Thread-safe pool with lock
   - Statistics tracking
   - Configurable initial size
   
2. **Modify Token class**
   ```python
   class Token:
       # Add reset() method for pooling
       # Mark pool-eligible tokens
       __pool_eligible__ = True
   ```

3. **Lexer integration**
   ```python
   class Lexer:
       def __init__(self, source: str, enable_pooling: bool = False):
           self.source = source
           if enable_pooling:
               self.token_pool = TokenPool(initial_size=1000)
           else:
               self.token_pool = None
       
       def _create_token(self, token_type: str, value: str,
                        location: SourceLocation) -> Token:
           if self.token_pool:
               return self.token_pool.acquire(
                   token_type, value, location
               )
           return Token(token_type, value, location)
   ```

4. **Configuration**
   ```python
   class MemoryConfiguration:
       enable_token_pooling: bool = False  # opt-in
       token_pool_size: int = 1000
       token_pool_max_size: int = 10000
   ```

**Testing Strategy**:

- **Unit Tests** (`tests/unit/optimization/test_token_pool.py`)
  - Token acquisition and release
  - Pool expansion on demand
  - Thread safety with concurrent access
  - Statistics tracking accuracy
  - Memory efficiency verification
  
- **Integration Tests**
  - Lexer with pooling produces identical tokens
  - Pool statistics reasonable
  - No reference issues with reused tokens
  
- **Benchmark Tests**
  - Allocation speedup
  - Memory reduction
  - Pool utilization patterns

**Performance Metrics**:

| Metric | Target | Baseline | Goal |
|--------|--------|----------|------|
| Token allocation time | -30-50% | N/A | ✓ |
| GC pressure reduction | -40-60% | N/A | ✓ |
| Memory fragmentation | -50% | N/A | ✓ |
| Parsing speed | +5-10% | N/A | ✓ |

**Estimated Effort**: 8-10 hours
- Pool implementation: 3-4 hours
- Token class modifications: 1-2 hours
- Lexer integration: 1-2 hours
- Testing & benchmarking: 2-3 hours

---

### 3.2 Compiled Regex Caching

**Purpose**: Pre-compile and cache all regex patterns at module load time instead of runtime compilation.

**Technical Approach**:

```python
import re
from typing import Dict, Pattern
from enum import Enum

class RegexPattern(Enum):
    """All regex patterns used in lexer/parser"""
    COBOL_IDENTIFIER = r"[A-Z][A-Z0-9-]*"
    NUMERIC_LITERAL = r"\d+(\.\d+)?"
    STRING_LITERAL = r"\".*?\"|'.*?'"
    COMMENT_LINE = r"^\s*\*.*$"
    CONTINUATION = r"-\s*$"
    # ... all other patterns

class CompiledRegexCache:
    """Pre-compiled regex cache"""
    
    _cache: Dict[RegexPattern, Pattern] = {}
    
    @classmethod
    def initialize(cls):
        """Pre-compile all patterns at module load"""
        for pattern in RegexPattern:
            cls._cache[pattern] = re.compile(
                pattern.value,
                re.MULTILINE | re.IGNORECASE
            )
    
    @classmethod
    def get(cls, pattern: RegexPattern) -> Pattern:
        """Get pre-compiled pattern"""
        if pattern not in cls._cache:
            # Fallback (should not happen if initialized)
            cls._cache[pattern] = re.compile(pattern.value)
        return cls._cache[pattern]
    
    @classmethod
    def clear(cls):
        """Clear cache (for testing)"""
        cls._cache.clear()

# Initialize at module load
CompiledRegexCache.initialize()

# Usage in Lexer
class Lexer:
    def _match_identifier(self, text: str) -> Optional[Match]:
        pattern = CompiledRegexCache.get(RegexPattern.COBOL_IDENTIFIER)
        return pattern.match(text)
```

**Affected Files**:
- `cobolparser/lexer.py` - All regex usage
- `cobolparser/parser.py` - Any regex patterns
- `cobolparser/preprocess/preprocess.py` - Preprocessing patterns
- `cobolparser/optimization/regex_cache.py` - Implementation

**Implementation Steps**:

1. **Create regex cache** (`cobolparser/optimization/regex_cache.py`)
   - Enumerate all regex patterns
   - Pre-compile with optimal flags
   - Statistics tracking
   
2. **Identify all regex patterns**
   - Audit lexer.py for `re.compile()` calls
   - Audit parser.py for regex usage
   - Document each pattern's purpose
   
3. **Replace dynamic compilation**
   ```python
   # Before
   pattern = re.compile(r"[A-Z][A-Z0-9-]*", re.MULTILINE)
   match = pattern.match(text)
   
   # After
   pattern = CompiledRegexCache.get(RegexPattern.COBOL_IDENTIFIER)
   match = pattern.match(text)
   ```

4. **Configuration**
   ```python
   class MemoryConfiguration:
       precompile_regexes: bool = True  # enabled by default
       regex_cache_stats: bool = False  # track usage
   ```

**Testing Strategy**:

- **Unit Tests** (`tests/unit/optimization/test_regex_cache.py`)
  - All patterns compile successfully
   - Compiled patterns match same as runtime compilation
  - Cache retrieval performance
  - Statistics tracking
  
- **Integration Tests**
  - Lexer behavior unchanged
  - All test cases pass with cached regexes
  
- **Benchmark Tests**
  - Pattern matching speed improvement
  - Memory for compiled vs runtime
  - Cache hit rate tracking

**Performance Metrics**:

| Metric | Target | Baseline | Goal |
|--------|--------|----------|------|
| Pattern matching speed | -20-40% | N/A | ✓ |
| Memory for compilation | -70% | N/A | ✓ |
| Lexer throughput | +5-10% | N/A | ✓ |
| First tokenization | -10-15% | N/A | ✓ |

**Estimated Effort**: 4-6 hours
- Pattern identification & enumeration: 1-2 hours
- Cache implementation: 1 hour
- Lexer/parser integration: 1-2 hours
- Testing: 1-2 hours

---

## Cross-Phase Implementation Considerations

### Dependency and Ordering

1. **Phase 1 optimizations are independent** - can be implemented in any order
2. **Phase 2 can follow Phase 1** - no blocking dependencies
3. **Phase 3 is lowest impact** - can be deferred if Phase 1-2 meet goals

### Configuration Management

```python
@dataclass
class PerformanceConfiguration:
    """Complete performance optimization settings"""
    
    # Phase 1
    enable_lookahead_cache: bool = True
    lookahead_cache_size: int = 16
    
    lazy_ast_creation: bool = True
    enable_string_interning: bool = True
    
    # Phase 2
    parallel_copybooks: bool = True
    copybook_workers: int = 4
    
    incremental_lexing: bool = False
    use_visitor_pattern: bool = True
    use_keyword_bloom_filter: bool = True
    
    # Phase 3
    enable_token_pooling: bool = False
    precompile_regexes: bool = True
    
    def validate(self):
        """Validate configuration consistency"""
        assert self.copybook_workers > 0
        assert self.lookahead_cache_size > 0
```

### Metrics Collection Framework

```python
@dataclass
class PerformanceMetrics:
    """Aggregated performance metrics"""
    
    lexer_time_ms: float
    parser_time_ms: float
    total_time_ms: float
    
    memory_peak_mb: float
    memory_avg_mb: float
    
    tokens_per_second: int
    statements_per_second: int
    
    cache_hit_rate: float
    gc_collections: int
    
    def __str__(self) -> str:
        return f"""
        Total Time: {self.total_time_ms:.2f}ms
        Lexer: {self.lexer_time_ms:.2f}ms | Parser: {self.parser_time_ms:.2f}ms
        Memory: {self.memory_peak_mb:.1f}MB peak, {self.memory_avg_mb:.1f}MB avg
        Throughput: {self.tokens_per_second} tokens/sec, {self.statements_per_second} stmts/sec
        Cache Hit Rate: {self.cache_hit_rate:.1%}
        GC Collections: {self.gc_collections}
        """
```

### Testing Matrix

| Test Type | Phase 1 | Phase 2 | Phase 3 | Total |
|-----------|---------|---------|---------|-------|
| Unit | 15 | 20 | 10 | 45 |
| Integration | 8 | 10 | 5 | 23 |
| Benchmark | 5 | 8 | 5 | 18 |
| **Total** | **28** | **38** | **20** | **86** |

---

## Success Criteria and Metrics

### Primary Goals

1. **Parsing Speed**: 2-3x improvement from Phase 1-2 combined
2. **Memory Usage**: 30-50% reduction for large programs
3. **Throughput**: 1000+ programs/hour on standard hardware
4. **Scalability**: Linear time complexity for source size

### Measurement Approach

```python
def measure_performance(source_code: str, 
                       config: PerformanceConfiguration) -> PerformanceMetrics:
    """Measure parsing performance with given config"""
    
    import time
    import psutil
    import gc
    
    process = psutil.Process()
    gc.collect()
    
    start_time = time.perf_counter()
    start_memory = process.memory_info().rss
    gc_before = gc.get_count()
    
    # Parse program
    parser = CobolParser(config=config)
    ast = parser.parse(source_code)
    
    end_time = time.perf_counter()
    end_memory = process.memory_info().rss
    gc_after = gc.get_count()
    
    return PerformanceMetrics(
        total_time_ms=(end_time - start_time) * 1000,
        memory_peak_mb=end_memory / 1024 / 1024,
        tokens_per_second=len(parser.tokens) / (end_time - start_time),
        gc_collections=sum(gc_after) - sum(gc_before)
    )
```

---

## Deployment and Migration Strategy

### Backward Compatibility

- All optimizations are **opt-in** via configuration
- Default behavior unchanged until explicitly enabled
- Deprecation path for old APIs (if needed)

### Rollout Plan

1. **Week 1-2**: Phase 1 optimizations to production
2. **Week 3-4**: Phase 2 optimizations (after Phase 1 stabilization)
3. **Week 5-6**: Phase 3 optimizations (if beneficial)
4. **Week 7-8**: Combined benchmarking and tuning

### Documentation Updates

- Update PARSER_INVOCATION_GUIDE.md with config options
- Add performance tuning guide
- Document each optimization's trade-offs
- Add migration guide for users

---

## Summary

This roadmap provides a structured approach to significant COBOL parser performance improvements across three phases:

- **Phase 1**: Core optimizations (48-50 hours) yielding 2-3x speedup
- **Phase 2**: Advanced techniques (52-56 hours) for additional gains
- **Phase 3**: Fine-tuning (22-26 hours) for marginal improvements

Total estimated effort: **122-132 hours** over 8 weeks with measurable performance targets for each optimization.
