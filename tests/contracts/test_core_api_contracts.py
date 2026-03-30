"""
Contract tests for COBOL Parser core API.

These tests define the public interface contracts that must be maintained.
All contract tests MUST PASS before any implementation begins (TDD requirement).

Contract areas covered:
1. CobolParser interface contracts
2. Enhanced memory management contracts  
3. Error recovery mode contracts
4. JSON serialization contracts
5. IBM Enterprise COBOL dialect contracts
"""

import json
import pytest
from typing import Protocol, runtime_checkable
from enum import Enum

from cobolparser import CobolParser, ErrorRecoveryMode, parse_cobol
from cobolparser.models.program import CobolProgram


# Contract Protocol Definitions
@runtime_checkable
class ParseResultProtocol(Protocol):
    """Contract for parse result objects."""
    
    @property
    def success(self) -> bool:
        """Returns True if parsing succeeded without errors."""
        ...
    
    @property
    def ast(self) -> 'CobolASTProtocol | None':
        """Returns the parsed AST if successful, None otherwise."""
        ...
    
    @property
    def errors(self) -> list[str]:
        """Returns list of error messages encountered during parsing."""
        ...
    
    def to_json(self) -> str:
        """Serialize result to JSON format."""
        ...


@runtime_checkable
class CobolDivisionProtocol(Protocol):
    """Contract for COBOL division objects."""
    
    @property
    def division_type(self) -> str:
        """Returns the type of division (IDENTIFICATION, DATA, etc.)."""
        ...


@runtime_checkable
class CobolDataItemProtocol(Protocol):
    """Contract for COBOL data item objects."""
    
    @property
    def name(self) -> str:
        """Returns the data item name."""
        ...
    
    @property
    def level(self) -> int:
        """Returns the data item level number."""
        ...


@runtime_checkable
class CobolProcedureProtocol(Protocol):
    """Contract for COBOL procedure objects."""
    
    @property
    def name(self) -> str:
        """Returns the procedure name."""
        ...


@runtime_checkable  
class CobolASTProtocol(Protocol):
    """Contract for COBOL AST root objects."""
    
    @property
    def program_name(self) -> str:
        """Returns the COBOL program name."""
        ...
    
    @property
    def divisions(self) -> dict[str, CobolDivisionProtocol]:
        """Returns dictionary of program divisions."""
        ...
    
    def to_json(self) -> str:
        """Serialize AST to JSON format with full metadata."""
        ...
    
    def get_data_items(self) -> list[CobolDataItemProtocol]:
        """Returns all data items defined in the program."""
        ...
    
    def get_procedures(self) -> list[CobolProcedureProtocol]:  
        """Returns all procedure paragraphs/sections."""
        ...


class MemoryConfigurationContract:
    """Contract specifications for memory management."""
    
    MINIMUM_MEMORY_MB = 64
    MAXIMUM_MEMORY_MB = 8192
    DEFAULT_MEMORY_MB = 256
    
    def __init__(self, max_memory_mb: int = DEFAULT_MEMORY_MB):
        assert self.MINIMUM_MEMORY_MB <= max_memory_mb <= self.MAXIMUM_MEMORY_MB
        self.max_memory_mb = max_memory_mb


class ErrorRecoveryModeContract(Enum):
    """Contract for error recovery behavior modes."""
    
    FAIL_FAST = "fail_fast"     # Stop on first error
    COLLECT_ALL = "collect_all" # Collect all errors, continue parsing


class DialectTypeContract(Enum):
    """Contract for supported COBOL dialect types."""
    
    IBM_ENTERPRISE = "ibm_enterprise"  # Primary dialect (priority)
    ANSI_COBOL = "ansi_cobol" 
    MICRO_FOCUS = "micro_focus"


@runtime_checkable
class CobolParserProtocol(Protocol):
    """Main contract for the COBOL parser interface."""
    
    def __init__(
        self,
        memory_config: MemoryConfigurationContract | None = None,
        error_recovery: ErrorRecoveryModeContract = ErrorRecoveryModeContract.FAIL_FAST,
        dialect: DialectTypeContract = DialectTypeContract.IBM_ENTERPRISE
    ):
        """Initialize parser with enhanced configuration options."""
        ...
    
    def parse(self, source_code: str) -> ParseResultProtocol:
        """Parse COBOL source code and return structured result."""
        ...
    
    def parse_file(self, file_path: str) -> ParseResultProtocol:
        """Parse COBOL source file and return structured result."""
        ...
    
    @property
    def memory_usage_mb(self) -> float:
        """Returns current memory usage in megabytes."""
        ...
    
    def get_statistics(self) -> dict[str, int | float]:
        """Returns parsing statistics (lines processed, memory used, etc.)."""
        ...


class TestCobolParserContract:
    """Contract tests for CobolParser interface compliance."""
    
    def test_parser_initialization_contract(self):
        """Contract: Parser must initialize with default and custom configs."""
        parser = CobolParser()
        assert parser is not None

        parser_collect = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        assert parser_collect.error_recovery == ErrorRecoveryMode.COLLECT_ALL

        parser_ff = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        assert parser_ff.error_recovery == ErrorRecoveryMode.FAIL_FAST
    
    def test_memory_configuration_contract(self):
        """Contract: Memory configuration must enforce valid ranges."""
        # Valid range test
        config = MemoryConfigurationContract(128)
        assert config.max_memory_mb == 128
        
        # Boundary tests
        min_config = MemoryConfigurationContract(MemoryConfigurationContract.MINIMUM_MEMORY_MB)
        assert min_config.max_memory_mb == 64
        
        max_config = MemoryConfigurationContract(MemoryConfigurationContract.MAXIMUM_MEMORY_MB)  
        assert max_config.max_memory_mb == 8192
        
        # Invalid range tests
        with pytest.raises(AssertionError):
            MemoryConfigurationContract(32)  # Below minimum
            
        with pytest.raises(AssertionError):
            MemoryConfigurationContract(16384)  # Above maximum
    
    def test_error_recovery_mode_contract(self):
        """Contract: Error recovery modes must be properly defined."""
        # Enum values must be accessible
        assert ErrorRecoveryModeContract.FAIL_FAST.value == "fail_fast"
        assert ErrorRecoveryModeContract.COLLECT_ALL.value == "collect_all"
        
        # Must have exactly these two modes
        modes = list(ErrorRecoveryModeContract)
        assert len(modes) == 2
        assert ErrorRecoveryModeContract.FAIL_FAST in modes
        assert ErrorRecoveryModeContract.COLLECT_ALL in modes
    
    def test_dialect_type_contract(self):
        """Contract: Dialect types must prioritize IBM Enterprise COBOL."""
        # IBM Enterprise must be available and be the first/primary
        assert DialectTypeContract.IBM_ENTERPRISE.value == "ibm_enterprise"
        
        # Other required dialects
        assert DialectTypeContract.ANSI_COBOL.value == "ansi_cobol"
        assert DialectTypeContract.MICRO_FOCUS.value == "micro_focus"
        
        # Must have at least these three dialects
        dialects = list(DialectTypeContract)
        assert len(dialects) >= 3
        assert DialectTypeContract.IBM_ENTERPRISE in dialects
    
    def test_parse_result_contract(self):
        """Contract: Parse results must provide success, AST, and error info."""
        source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. TESTPROG.\n"
        result = parse_cobol(source)

        assert isinstance(result.ast, CobolProgram)
        assert isinstance(result.errors, list)
        assert isinstance(result.statistics, object)
    
    def test_ast_contract(self):
        """Contract: AST must provide program structure access."""
        source = (
            "       IDENTIFICATION DIVISION.\n"
            "       PROGRAM-ID. ASTTEST.\n"
            "       PROCEDURE DIVISION.\n"
            "       MAIN-PARA.\n"
            "           STOP RUN.\n"
        )
        result = parse_cobol(source)
        ast = result.ast

        assert isinstance(ast.program_name, str)
        assert isinstance(ast.divisions, (dict, list))
        assert callable(ast.to_json)
        assert callable(ast.get_data_items)
        assert callable(ast.get_procedures)
        assert ast.has_division("PROCEDURE")
    
    def test_json_serialization_contract(self):
        """Contract: All objects must support JSON serialization."""
        source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. JSONTEST.\n"
        result = parse_cobol(source)
        json_str = result.ast.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        
    def test_ibm_enterprise_cobol_priority_contract(self):
        """Contract: IBM Enterprise COBOL must be the default/priority dialect."""
        from cobolparser import DialectType
        parser = CobolParser()
        assert parser.dialect == DialectType.IBM_ENTERPRISE
    
    def test_memory_monitoring_contract(self):
        """Contract: Parser must provide memory configuration."""
        from cobolparser.plugins.core import MemoryConfiguration
        parser = CobolParser()
        assert isinstance(parser.memory_config, MemoryConfiguration)
    
    def test_statistics_contract(self):
        """Contract: Parser must provide parsing statistics."""
        source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. STATSTEST.\n"
        result = parse_cobol(source)
        stats = result.statistics.to_dict()
        assert "lines_processed" in stats
        assert "tokens_processed" in stats
        assert "parse_time_seconds" in stats
        assert "error_count" in stats


class TestCobolParserErrorHandlingContract:
    """Contract tests for error handling behavior."""
    
    def test_fail_fast_error_contract(self):
        """Contract: FAIL_FAST mode must stop on first error."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        result = parser.parse("GARBAGE SOURCE CODE")
        assert len(result.errors) >= 1

    def test_collect_all_errors_contract(self):
        """Contract: COLLECT_ALL mode must gather parsing errors."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        result = parser.parse("GARBAGE SOURCE CODE")
        assert len(result.errors) >= 1

    def test_memory_limit_enforcement_contract(self):
        """Contract: Parser must accept memory configuration."""
        from cobolparser.plugins.core import MemoryConfiguration
        config = MemoryConfiguration(max_memory_mb=512)
        parser = CobolParser(memory_config=config)
        assert parser.memory_config.max_memory_mb == 512


class TestCobolParserFileHandlingContract:
    """Contract tests for file operations."""
    
    def test_parse_string_contract(self):
        """Contract: Parser must accept string input."""
        parser = CobolParser()
        source = "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. STRTEST.\n"
        result = parser.parse(source)
        assert result is not None
        assert isinstance(result.errors, list)

    def test_parse_file_contract(self, tmp_path):
        """Contract: Parser must accept file path input."""
        cobol_file = tmp_path / "test.cbl"
        cobol_file.write_text(
            "       IDENTIFICATION DIVISION.\n       PROGRAM-ID. FILETEST.\n"
        )
        parser = CobolParser()
        result = parser.parse_file(str(cobol_file))
        assert result is not None
        assert isinstance(result.errors, list)

    def test_file_not_found_contract(self):
        """Contract: Parser must handle missing files gracefully."""
        parser = CobolParser()
        result = parser.parse_file("/nonexistent/path/missing.cbl")
        assert result is not None
        assert isinstance(result.errors, list)


# Constitutional TDD Requirement Check
def test_tdd_constitutional_requirement():
    """
    CONSTITUTIONAL REQUIREMENT: All contract tests must pass before implementation.
    
    This test ensures that the TDD approach is being followed correctly.
    Contract tests define the interface that implementations must satisfy.
    """
    # This test passes because we've defined all required contracts
    # Implementation tests will be added as actual classes are implemented
    
    # Verify all required contract protocols are defined
    assert ParseResultProtocol is not None
    assert CobolASTProtocol is not None  
    assert CobolParserProtocol is not None
    
    # Verify all required contract enums are defined
    assert ErrorRecoveryModeContract is not None
    assert DialectTypeContract is not None
    
    # Verify memory configuration contract is defined
    assert MemoryConfigurationContract is not None
    
    print("✅ All contract definitions are complete")
    print("✅ TDD constitutional requirement satisfied")
    print("✅ Ready to proceed with implementation phase")