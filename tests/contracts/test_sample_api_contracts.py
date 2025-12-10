"""
Contract tests for COBOL parser API stability.
These tests ensure that the parser API contract remains stable across samples.
"""
import pytest
from pathlib import Path
from cobolparser import CobolParser, ErrorRecoveryMode
from cobolparser.models.ast_base import ASTNode
from cobolparser.models.program import CobolProgram, CobolDivision
from cobolparser.plugins.core import SerializationConfig, MemoryConfiguration


SAMPLES_DIR = Path(__file__).parent.parent / "samples"


class TestParserAPIContract:
    """Test that parser API remains consistent."""
    
    def test_parse_file_returns_result_object(self):
        """Test that parse_file returns a result with expected attributes."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / "figurative_constants.cbl"
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: Result must have ast, errors, statistics attributes
        assert hasattr(result, 'ast')
        assert hasattr(result, 'errors')
        assert hasattr(result, 'statistics')
        
    def test_parse_string_returns_result_object(self):
        """Test that parse returns a result with expected attributes."""
        parser = CobolParser()
        source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST.
        """
        
        result = parser.parse(source)
        
        # Contract: Result must have ast, errors, statistics attributes
        assert hasattr(result, 'ast')
        assert hasattr(result, 'errors')
        assert hasattr(result, 'statistics')
        
    def test_parser_accepts_error_recovery_mode(self):
        """Test that parser constructor accepts error_recovery parameter."""
        # Contract: Should accept ErrorRecoveryMode enum
        parser1 = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
        parser2 = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        
        assert parser1 is not None
        assert parser2 is not None
        
    def test_parser_accepts_memory_config(self):
        """Test that parser constructor accepts memory_config parameter."""
        config = MemoryConfiguration(max_memory_mb=512)
        parser = CobolParser(memory_config=config)
        
        assert parser is not None


class TestASTNodeContract:
    """Test that AST nodes maintain their contract."""
    
    @pytest.mark.parametrize("sample_file", [
        "figurative_constants.cbl",
        "control_flow.cbl",
        "arithmetic_operations.cbl",
    ])
    def test_ast_root_is_program_node(self, sample_file):
        """Test that parsed AST root is a Program node."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / sample_file
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: AST root must be a CobolProgram instance
        assert isinstance(result.ast, CobolProgram)
        
    @pytest.mark.parametrize("sample_file", [
        "figurative_constants.cbl",
        "control_flow.cbl",
        "arithmetic_operations.cbl",
    ])
    def test_program_has_program_id(self, sample_file):
        """Test that Program node has program_id attribute."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / sample_file
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: Program must have program_name
        assert hasattr(result.ast, 'program_name')
        assert result.ast.program_name is not None
        assert isinstance(result.ast.program_name, str)
        
    @pytest.mark.parametrize("sample_file", [
        "figurative_constants.cbl",
        "control_flow.cbl",
        "arithmetic_operations.cbl",
    ])
    def test_program_has_divisions(self, sample_file):
        """Test that Program node has division attributes."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / sample_file
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: Program must have division attributes or get_division method
        assert hasattr(result.ast, 'get_division')
        assert callable(result.ast.get_division)
        
    @pytest.mark.parametrize("sample_file", [
        "figurative_constants.cbl",
        "control_flow.cbl",
        "arithmetic_operations.cbl",
    ])
    def test_ast_nodes_have_to_dict_method(self, sample_file):
        """Test that all AST nodes implement to_dict method."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / sample_file
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: All ASTNode instances must have to_dict method
        assert hasattr(result.ast, 'to_dict')
        assert callable(result.ast.to_dict)
        
        # Execute to_dict and verify it returns a dict
        ast_dict = result.ast.to_dict()
        assert isinstance(ast_dict, dict)


class TestJSONSerializationContract:
    """Test that JSON serialization maintains its contract."""
    
    @pytest.mark.parametrize("sample_file", [
        "figurative_constants.cbl",
        "control_flow.cbl",
    ])
    def test_to_json_returns_string(self, sample_file):
        """Test that to_json returns a JSON string."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / sample_file
        
        result = parser.parse_file(str(sample_path))
        config = SerializationConfig()
        
        json_output = result.ast.to_json(config)
        
        # Contract: to_json must return a string
        assert isinstance(json_output, str)
        assert len(json_output) > 0
        
    @pytest.mark.parametrize("sample_file", [
        "figurative_constants.cbl",
        "control_flow.cbl",
    ])
    def test_json_contains_program_id(self, sample_file):
        """Test that JSON output contains program_id."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / sample_file
        
        result = parser.parse_file(str(sample_path))
        config = SerializationConfig()
        
        json_output = result.ast.to_json(config)
        
        # Contract: JSON must include program_name
        assert "program_name" in json_output
        assert result.ast.program_name in json_output
        
    def test_serialization_config_has_expected_options(self):
        """Test that SerializationConfig has expected options."""
        config = SerializationConfig(
            include_metadata=True,
            include_source_locations=True
        )
        
        # Contract: Config must have these attributes
        assert hasattr(config, 'include_metadata')
        assert hasattr(config, 'include_source_locations')


class TestErrorHandlingContract:
    """Test that error handling maintains its contract."""
    
    def test_errors_is_list(self):
        """Test that result.errors is always a list."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / "figurative_constants.cbl"
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: errors must be a list (can be empty)
        assert isinstance(result.errors, list)
        
    def test_error_recovery_collect_all_returns_errors(self):
        """Test that COLLECT_ALL mode returns error list."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        sample_path = SAMPLES_DIR / "error_recovery_tests.cbl"
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: COLLECT_ALL should populate errors list
        assert isinstance(result.errors, list)
        assert len(result.errors) > 0
        
    def test_error_objects_have_required_attributes(self):
        """Test that error objects have message and location."""
        parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
        sample_path = SAMPLES_DIR / "error_recovery_tests.cbl"
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: Each error must have message attribute
        for error in result.errors:
            assert hasattr(error, 'message')


class TestStatisticsContract:
    """Test that parse statistics maintain their contract."""
    
    @pytest.mark.parametrize("sample_file", [
        "figurative_constants.cbl",
        "control_flow.cbl",
        "arithmetic_operations.cbl",
    ])
    def test_statistics_object_exists(self, sample_file):
        """Test that result has statistics object."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / sample_file
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: Result must have statistics
        assert result.statistics is not None
        
    @pytest.mark.parametrize("sample_file", [
        "figurative_constants.cbl",
        "control_flow.cbl",
        "arithmetic_operations.cbl",
    ])
    def test_statistics_has_expected_attributes(self, sample_file):
        """Test that statistics has expected attributes."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / sample_file
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: Statistics must have these attributes
        assert hasattr(result.statistics, 'lines_processed')
        assert hasattr(result.statistics, 'total_time_ms')
        
        # Values must be non-negative
        assert result.statistics.lines_processed >= 0
        assert result.statistics.total_time_ms >= 0


class TestMemoryConfigContract:
    """Test that memory configuration maintains its contract."""
    
    def test_memory_config_has_expected_attributes(self):
        """Test that MemoryConfiguration has expected attributes."""
        config = MemoryConfiguration(
            max_memory_mb=512,
            enable_streaming=True
        )
        
        # Contract: Config must have these attributes
        assert hasattr(config, 'max_memory_mb')
        assert hasattr(config, 'enable_streaming')
        
    def test_memory_config_accepts_defaults(self):
        """Test that MemoryConfiguration works with defaults."""
        config = MemoryConfiguration()
        
        # Contract: Should work without parameters
        assert config is not None
        
    @pytest.mark.parametrize("sample_file", [
        "figurative_constants.cbl",
        "control_flow.cbl",
    ])
    def test_parser_respects_memory_config(self, sample_file):
        """Test that parser accepts and respects memory config."""
        config = MemoryConfiguration(max_memory_mb=1024)
        parser = CobolParser(memory_config=config)
        sample_path = SAMPLES_DIR / sample_file
        
        result = parser.parse_file(str(sample_path))
        
        # Contract: Should parse successfully with config
        assert result.ast is not None


class TestDivisionContract:
    """Test that Division nodes maintain their contract."""
    
    def test_data_division_structure(self):
        """Test that DATA DIVISION has expected structure."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / "figurative_constants.cbl"
        
        result = parser.parse_file(str(sample_path))
        
        if result.ast.get_division("DATA") is not None:
            # Contract: DATA DIVISION should have sections
            data_div = result.ast.get_division("DATA")
            assert hasattr(data_div, '_sections') or hasattr(data_div, 'sections')
            
    def test_procedure_division_structure(self):
        """Test that PROCEDURE DIVISION has expected structure."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / "figurative_constants.cbl"
        
        result = parser.parse_file(str(sample_path))
        
        if result.ast.get_division("PROCEDURE") is not None:
            # Contract: PROCEDURE DIVISION should have paragraphs/sections
            proc_div = result.ast.get_division("PROCEDURE")
            assert hasattr(proc_div, 'paragraphs') or hasattr(proc_div, 'sections') or hasattr(proc_div, '_sections')


class TestBackwardCompatibility:
    """Test backward compatibility with existing API."""
    
    def test_old_parse_method_signature(self):
        """Test that parse method maintains signature."""
        parser = CobolParser()
        
        # Contract: parse(source_code: str) should work
        result = parser.parse("IDENTIFICATION DIVISION. PROGRAM-ID. TEST.")
        
        assert result is not None
        assert result.ast is not None
        
    def test_old_parse_file_signature(self):
        """Test that parse_file method maintains signature."""
        parser = CobolParser()
        sample_path = SAMPLES_DIR / "figurative_constants.cbl"
        
        # Contract: parse_file(file_path: str) should work
        result = parser.parse_file(str(sample_path))
        
        assert result is not None
        assert result.ast is not None


@pytest.mark.parametrize("sample_file", [
    "figurative_constants.cbl",
    "multiline_strings.cbl",
    "picture_clauses.cbl",
    "occurs_variations.cbl",
    "redefines_test.cbl",
    "file_operations.cbl",
    "control_flow.cbl",
    "string_operations.cbl",
    "ibm_extensions.cbl",
    "arithmetic_operations.cbl",
])
def test_all_samples_maintain_api_contract(sample_file):
    """Test that all samples work with standard API contract."""
    parser = CobolParser()
    sample_path = SAMPLES_DIR / sample_file
    
    result = parser.parse_file(str(sample_path))
    
    # Contract assertions that must hold for all samples
    assert result is not None
    assert hasattr(result, 'ast')
    assert hasattr(result, 'errors')
    assert hasattr(result, 'statistics')
    assert isinstance(result.errors, list)
    assert result.statistics is not None
    
    if result.ast is not None:
        assert isinstance(result.ast, CobolProgram)
        assert hasattr(result.ast, 'program_name')
        assert hasattr(result.ast, 'to_dict')
        assert callable(result.ast.to_dict)
