# Research: COBOL Parser Implementation Decisions

**Feature**: COBOL Parser for Python  
**Date**: 2025-09-27  
**Context**: Technical research for implementation planning incorporating clarified requirements

## Decision: Parsing Strategy

**Chosen**: Recursive Descent Parser with Manual Lexer

**Rationale**: 
- COBOL has complex context-sensitive grammar that benefits from manual control
- Recursive descent allows for clear error recovery and custom error messages
- Manual approach enables handling of COBOL's continuation lines and comment syntax
- Better performance control for large files compared to parser generators
- Easier to implement dialect-specific variations for IBM Enterprise COBOL focus

**Alternatives Considered**:
- ANTLR or other parser generators: Too rigid for COBOL's context sensitivity and dialect variations
- PLY (Python Lex-Yacc): Good but less control over error recovery and memory management
- Hand-written lexer + parser generator: Hybrid complexity without clear benefits

## Decision: Error Recovery Architecture

**Chosen**: Configurable error recovery with error collection mode

**Rationale**: 
- Per clarifications: Users need both fail-fast and error collection modes
- Enterprise COBOL often has syntax variations that should be warnings, not errors
- Batch processing benefits from collecting all errors rather than failing fast
- Different use cases need different error tolerance levels
- Clear error reporting with line numbers and context improves user experience

**Implementation Approach**:
- Lexical errors (invalid tokens, malformed literals) with position tracking
- Syntax errors (grammar violations, missing required elements) with recovery points
- Structural errors (invalid division order, missing sections) with context
- Configurable modes: ErrorMode.FAIL_FAST, ErrorMode.COLLECT_ALL

**Alternatives Considered**:
- Fail-fast only: Too rigid for real-world COBOL parsing scenarios
- Permissive-only: May miss critical syntax issues that users need to know
- Fixed error strategy: Doesn't meet diverse user needs identified in clarifications

## Decision: Object Model Design

**Chosen**: Immutable objects with lazy evaluation and JSON serialization support

**Rationale**: 
- Per clarifications: JSON export capability required for interoperability
- Immutable objects prevent accidental modifications and support caching
- Lazy evaluation improves memory usage for large programs (addressing configurable memory limits)
- Pythonic property access hides complexity while maintaining flexibility
- JSON serialization enables integration with other tools and systems

**Implementation Approach**:
```python
from dataclasses import dataclass
from typing import List, Optional
import json

@dataclass(frozen=True)
class Program:
    name: str
    divisions: List[Division]
    
    def to_json(self, include_content: bool = True) -> str:
        """Serialize to JSON with configurable depth"""
        
@dataclass(frozen=True) 
class Division:
    name: str
    sections: List[Section]
```

**Alternatives Considered**:
- Mutable objects: Simpler but error-prone and harder to optimize for memory limits
- Dictionary-based: Not type-safe and loses IDE support, harder JSON serialization
- Purely functional: Too complex for Python developers' expectations

## Decision: JSON Serialization Strategy

**Chosen**: Custom serialization with configurable depth and filtering

**Rationale**:
- Per clarifications: JSON export required for interoperability with other tools
- COBOL object hierarchies are deep and complex (Program -> Division -> Section -> Paragraph -> Statement)
- Users need control over serialization depth to manage output size
- Filtering allows focusing on specific program aspects (e.g., only DATA division)
- Custom approach provides better performance than generic serialization

**Implementation Approach**:
```python
class SerializationConfig:
    max_depth: Optional[int] = None
    include_divisions: Set[str] = field(default_factory=set)
    include_source_lines: bool = False
    include_comments: bool = False

def to_json(self, config: SerializationConfig = None) -> str:
    """Serialize with configurable options"""
```

## Decision: Testing Strategy with Real COBOL Samples

**Chosen**: Layered testing with IBM Enterprise COBOL focus and 90%+ coverage

**Rationale**: 
- Constitution requires 90%+ code coverage and comprehensive COBOL syntax testing
- Real-world enterprise COBOL programs needed to validate practical usage
- IBM Enterprise COBOL priority requires extensive testing of IBM-specific features
- Performance testing needed for large file scenarios and memory limit validation

**Test Layers**:
1. **Contract Tests**: API interfaces and plugin contracts (TDD approach)
2. **Unit Tests**: Individual parser methods, object model, error handling
3. **Integration Tests**: Full COBOL program parsing with dialect-specific samples
4. **Performance Tests**: Large file processing, memory limit testing, error collection mode
5. **Serialization Tests**: JSON export accuracy and configuration options

**COBOL Sample Sources**:
- **IBM Enterprise COBOL**: IBM documentation examples, SQL integration samples, modern syntax
- **Micro Focus COBOL**: Basic compatibility samples, common enterprise patterns
- **GnuCOBOL**: Open-source samples for baseline ANSI coverage
- **Synthetic Programs**: Edge cases, malformed input, stress testing scenarios

## Decision: Plugin Architecture and COBOL Dialect Support

**Chosen**: Registry-based plugin system with IBM Enterprise COBOL priority

**Rationale**:
- Per clarifications: IBM Enterprise COBOL is primary focus with basic support for others
- Constitution requires extensibility for COBOL dialects and custom validation
- Plugin system allows community contributions without modifying core parser
- Clear extension points enable custom parsing rules and dialect variations

**Implementation Strategy**:
- **Primary Support**: IBM Enterprise COBOL (comprehensive syntax, modern features, SQL integration)
- **Basic Support**: Micro Focus COBOL, GnuCOBOL (common syntax, limited extensions)
- **Plugin System**: Registry pattern with standardized interfaces for adding dialects

**Hook Points**:
- Pre-parsing (source transformation, dialect detection)
- Division parsing (custom division types, dialect-specific sections)
- Statement parsing (vendor-specific statements, extensions)
- Post-parsing (validation rules, semantic analysis)
- Error handling (custom error types, dialect-specific messages)

**Plugin Interface**:
```python
class DialectPlugin:
    dialect_name: str
    priority: int  # Higher for more specific dialects
    
    def can_handle(self, source: str) -> bool: ...
    def pre_parse_hook(self, source: str) -> str: ...
    def statement_parse_hook(self, statement: str) -> Optional[Statement]: ...
```

## Decision: Performance and Memory Management

**Chosen**: Streaming parser with configurable memory limits and best-effort performance

**Rationale**:
- Per clarifications: Configurable memory limits and best-effort performance without time guarantees
- Enterprise COBOL files can be very large (10,000+ lines common in mainframes)
- Users need control over memory usage based on their deployment environment
- Accuracy prioritized over speed as per requirements

**Implementation Strategy**:
- Configurable memory limits (MemoryLimit enum: CONSERVATIVE=64MB, DEFAULT=512MB, GENEROUS=2GB, UNLIMITED)
- Stream-based lexical analysis to handle large files without loading entirely
- Lazy evaluation for sections and statements not immediately accessed
- Progress reporting for files >1MB without specific time commitments
- Memory-efficient string handling and object pooling

**Performance Targets**:
- **Memory**: User-configurable (default 512MB, range 64MB-8GB)
- **Time**: Best-effort with progress callbacks, no specific guarantees
- **Accuracy**: 100% for valid IBM Enterprise COBOL, graceful degradation for other dialects

## Implementation Architecture Summary

### Core Components
- **Lexer**: Manual tokenizer handling COBOL-specific syntax (areas A/B, continuation lines)
- **Parser**: Recursive descent with clear error recovery points and configurable error modes
- **Object Model**: Immutable classes with lazy evaluation and JSON serialization
- **Plugin System**: Registry-based with standardized interfaces for dialect extensions
- **Configuration**: Memory limits, error recovery modes, dialect preferences, serialization options

### Key Design Principles
- **Accuracy over Performance**: Best-effort parsing without time guarantees
- **Configurable Memory**: User-adjustable limits for different deployment environments
- **IBM Enterprise COBOL Focus**: Primary dialect with plugin support for others
- **JSON Interoperability**: Export capability for integration with external tools
- **Extensible Architecture**: Plugin system for community contributions

## Next Phase Requirements

1. **Data Model Design**: Define entity classes based on COBOL structure and clarified requirements
2. **API Contracts**: Specify parser interface, plugin interfaces, configuration API, JSON serialization
3. **Contract Tests**: Create failing tests that define expected behavior for all features
4. **Quickstart Guide**: Document basic usage patterns including configuration and JSON export

---
*Research complete - All technical decisions resolved incorporating clarified requirements*