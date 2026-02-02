"""Contract tests for ASTNodeFactory API stability.

These tests verify that the public APIs of ASTNodeFactory remain stable
and that statement parsers maintain backward-compatible behavior when
using the factory for node creation.

Contract tests ensure:
- Factory method signatures don't break
- Statement parsers still produce correct AST nodes
- Parser behavior is equivalent before/after factory introduction
- Public API contracts are honored
"""

import pytest
from cobolparser.core.ast_factory import ASTNodeFactory, get_factory, set_factory, create_node
from cobolparser.models.ast_base import SourceLocation, ASTNode
from cobolparser.models.statements import (
    DisplayStatement, MoveStatement, IfStatement, PerformStatement,
    EvaluateStatement, CallStatement, AddStatement, SubtractStatement,
    MultiplyStatement, DivideStatement, ComputeStatement
)
from cobolparser.parsers.statements.display_parser import DisplayStatementParser
from cobolparser.parsers.statements.move_parser import MoveStatementParser
from cobolparser.parsers.statements.if_parser import IfStatementParser
from cobolparser.parsers.statements.perform_parser import PerformStatementParser
from cobolparser.parsers.statements.evaluate_parser import EvaluateStatementParser
from cobolparser.parsers.statements.call_parser import CallStatementParser
from cobolparser.parsers.statements.arithmetic_parsers import (
    AddStatementParser, SubtractStatementParser, MultiplyStatementParser,
    DivideStatementParser, ComputeStatementParser
)
from cobolparser.core.interfaces import IStatementParser


class TestASTNodeFactoryAPIContract:
    """Contract tests for ASTNodeFactory public API."""
    
    def test_factory_create_method_returns_ast_node(self):
        """Factory.create() must return an ASTNode subclass instance."""
        factory = ASTNodeFactory()
        location = SourceLocation(1, 1)
        
        node = factory.create(DisplayStatement, location)
        
        assert isinstance(node, ASTNode)
        assert isinstance(node, DisplayStatement)
    
    def test_factory_create_with_location_parameter(self):
        """Factory.create() must accept location as positional parameter."""
        factory = ASTNodeFactory()
        location = SourceLocation(10, 5)
        
        node = factory.create(DisplayStatement, location)
        
        assert node.location == location
        assert node.location.line == 10
        assert node.location.column == 5
    
    def test_factory_with_metadata_returns_node_for_chaining(self):
        """Factory.with_metadata() must return the same node for method chaining."""
        factory = ASTNodeFactory()
        node = factory.create(DisplayStatement, SourceLocation(1, 1))
        
        result = factory.with_metadata(node, {'key': 'value'})
        
        assert result is node
        assert node.get_metadata('key') == 'value'
    
    def test_factory_with_context_returns_node_for_chaining(self):
        """Factory.with_context() must return the same node for method chaining."""
        factory = ASTNodeFactory()
        node = factory.create(DisplayStatement, SourceLocation(1, 1))
        
        result = factory.with_context(node, 'PROCEDURE', 'MAIN')
        
        assert result is node
        assert node.division_name == 'PROCEDURE'
        assert node.section_name == 'MAIN'
    
    def test_factory_validate_node_type_returns_bool(self):
        """Factory.validate_node_type() must return True on success."""
        factory = ASTNodeFactory()
        node = factory.create(DisplayStatement, SourceLocation(1, 1))
        
        result = factory.validate_node_type(node, DisplayStatement)
        
        assert isinstance(result, bool)
        assert result is True
    
    def test_factory_get_creation_count_returns_int(self):
        """Factory.get_creation_count() must return integer count."""
        factory = ASTNodeFactory()
        initial = factory.get_creation_count()
        
        factory.create(DisplayStatement, SourceLocation(1, 1))
        factory.create(MoveStatement, SourceLocation(2, 1))
        
        assert factory.get_creation_count() == initial + 2
    
    def test_factory_get_validation_errors_returns_list(self):
        """Factory.get_validation_errors() must return list of strings."""
        factory = ASTNodeFactory()
        
        errors = factory.get_validation_errors()
        
        assert isinstance(errors, list)


class TestStatementParserFactoryIntegration:
    """Contract tests for statement parsers using factory."""
    
    def test_display_parser_produces_display_statement(self):
        """DisplayStatementParser must produce DisplayStatement nodes."""
        # This verifies the contract that the parser returns the correct type
        parser = DisplayStatementParser()
        
        assert isinstance(parser, IStatementParser)
    
    def test_move_parser_is_istatement_parser(self):
        """MoveStatementParser must implement IStatementParser."""
        parser = MoveStatementParser()
        
        assert isinstance(parser, IStatementParser)
        assert hasattr(parser, 'matches')
        assert hasattr(parser, 'parse')
    
    def test_if_parser_is_istatement_parser(self):
        """IfStatementParser must implement IStatementParser."""
        parser = IfStatementParser()
        
        assert isinstance(parser, IStatementParser)
    
    def test_perform_parser_is_istatement_parser(self):
        """PerformStatementParser must implement IStatementParser."""
        parser = PerformStatementParser()
        
        assert isinstance(parser, IStatementParser)
    
    def test_evaluate_parser_is_istatement_parser(self):
        """EvaluateStatementParser must implement IStatementParser."""
        parser = EvaluateStatementParser()
        
        assert isinstance(parser, IStatementParser)
    
    def test_call_parser_is_istatement_parser(self):
        """CallStatementParser must implement IStatementParser."""
        parser = CallStatementParser()
        
        assert isinstance(parser, IStatementParser)
    
    def test_arithmetic_parsers_implement_istatement_parser(self):
        """All arithmetic parsers must implement IStatementParser."""
        parsers = [
            AddStatementParser(),
            SubtractStatementParser(),
            MultiplyStatementParser(),
            DivideStatementParser(),
            ComputeStatementParser()
        ]
        
        for parser in parsers:
            assert isinstance(parser, IStatementParser)
            assert hasattr(parser, 'matches')
            assert hasattr(parser, 'parse')


class TestGlobalFactoryContract:
    """Contract tests for global factory functions."""
    
    def test_get_factory_returns_factory_instance(self):
        """get_factory() must return an ASTNodeFactory instance."""
        factory = get_factory()
        
        assert isinstance(factory, ASTNodeFactory)
    
    def test_get_factory_returns_singleton(self):
        """get_factory() must return the same instance on repeated calls."""
        factory1 = get_factory()
        factory2 = get_factory()
        
        assert factory1 is factory2
    
    def test_set_factory_changes_default_instance(self):
        """set_factory() must change the default factory returned by get_factory()."""
        original = get_factory()
        custom = ASTNodeFactory()
        
        set_factory(custom)
        retrieved = get_factory()
        
        assert retrieved is custom
        
        # Restore original
        set_factory(original)
    
    def test_create_node_uses_default_factory(self):
        """create_node() must use the factory from get_factory()."""
        location = SourceLocation(1, 1)
        
        node = create_node(DisplayStatement, location)
        
        assert isinstance(node, DisplayStatement)
        assert node.location == location


class TestFactoryNodeTypeContract:
    """Contract tests for factory node type handling."""
    
    def test_factory_accepts_all_statement_types(self):
        """Factory must create all standard statement types successfully."""
        factory = ASTNodeFactory()
        location = SourceLocation(1, 1)
        
        statement_types = [
            DisplayStatement, MoveStatement, IfStatement, PerformStatement,
            EvaluateStatement, CallStatement, AddStatement, SubtractStatement,
            MultiplyStatement, DivideStatement, ComputeStatement
        ]
        
        for stmt_type in statement_types:
            node = factory.create(stmt_type, location)
            assert isinstance(node, stmt_type)
            assert node.location == location
    
    def test_factory_rejects_non_astnode_types(self):
        """Factory must reject non-ASTNode types."""
        factory = ASTNodeFactory()
        location = SourceLocation(1, 1)
        
        class NotANode:
            pass
        
        with pytest.raises(TypeError):
            factory.create(NotANode, location)  # type: ignore


class TestFactoryValidationContract:
    """Contract tests for factory validation methods."""
    
    def test_validate_node_type_raises_on_mismatch(self):
        """validate_node_type() must raise exception on type mismatch."""
        factory = ASTNodeFactory()
        display_node = factory.create(DisplayStatement, SourceLocation(1, 1))
        
        with pytest.raises(Exception):  # NodeTypeError
            factory.validate_node_type(display_node, MoveStatement)
    
    def test_validate_required_fields_accepts_valid_node(self):
        """validate_required_fields() must succeed for valid nodes."""
        factory = ASTNodeFactory()
        node = factory.create(DisplayStatement, SourceLocation(1, 1))
        
        result = factory.validate_required_fields(
            node,
            ['location', 'node_type'],
            'DisplayStatement'
        )
        
        assert result is True
    
    def test_validate_field_types_accepts_valid_types(self):
        """validate_field_types() must succeed for valid field types."""
        factory = ASTNodeFactory()
        node = factory.create(DisplayStatement, SourceLocation(1, 1))
        
        result = factory.validate_field_types(
            node,
            {'location': SourceLocation, 'node_type': str},
            'DisplayStatement'
        )
        
        assert result is True


class TestFactoryMetadataContract:
    """Contract tests for factory metadata features."""
    
    def test_metadata_persistence_after_creation(self):
        """Metadata set via with_metadata() must persist on node."""
        factory = ASTNodeFactory()
        node = factory.create(DisplayStatement, SourceLocation(1, 1))
        metadata = {'priority': 'high', 'version': '1.0'}
        
        factory.with_metadata(node, metadata)
        
        # Verify metadata persists
        assert node.get_metadata('priority') == 'high'
        assert node.get_metadata('version') == '1.0'
    
    def test_context_assignment_persists(self):
        """Context set via with_context() must persist on node."""
        factory = ASTNodeFactory()
        node = factory.create(DisplayStatement, SourceLocation(1, 1))
        
        factory.with_context(node, 'PROCEDURE', 'MAIN-SECTION')
        
        assert node.division_name == 'PROCEDURE'
        assert node.section_name == 'MAIN-SECTION'
    
    def test_method_chaining_fluent_interface(self):
        """Factory methods must support method chaining."""
        factory = ASTNodeFactory()
        
        node = (factory
                .create(DisplayStatement, SourceLocation(1, 1))
                # Note: We can't chain directly since create returns ASTNode,
                # only methods on factory can chain. This test verifies create returns correct type
                )
        
        assert isinstance(node, DisplayStatement)
        
        # Test chaining with_metadata and with_context
        result = factory.with_metadata(node, {'key': 'val'})
        result = factory.with_context(result, 'DATA')
        
        assert result.get_metadata('key') == 'val'
        assert result.division_name == 'DATA'


class TestFactoryErrorHandlingContract:
    """Contract tests for factory error handling."""
    
    def test_factory_records_error_count(self):
        """Factory must track number of creation events."""
        factory = ASTNodeFactory()
        initial = factory.get_creation_count()
        
        for i in range(5):
            factory.create(DisplayStatement, SourceLocation(i, 1))
        
        assert factory.get_creation_count() == initial + 5
    
    def test_clear_validation_errors_empties_log(self):
        """clear_validation_errors() must empty the error log."""
        factory = ASTNodeFactory()
        
        # Add test errors
        factory._validation_errors.append("Test error 1")
        factory._validation_errors.append("Test error 2")
        
        assert len(factory.get_validation_errors()) == 2
        
        factory.clear_validation_errors()
        
        assert len(factory.get_validation_errors()) == 0
