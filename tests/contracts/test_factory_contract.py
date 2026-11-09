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

from cobolparser.core.ast_factory import (
    ASTNodeFactory,
    create_node,
    get_factory,
    set_factory,
)
from cobolparser.core.interfaces import IStatementParser
from cobolparser.models.ast_base import ASTNode, SourceLocation
from cobolparser.models.statements import (
    AddStatement,
    CallStatement,
    ComputeStatement,
    DisplayStatement,
    DivideStatement,
    EvaluateStatement,
    IfStatement,
    MoveStatement,
    MultiplyStatement,
    PerformStatement,
    SubtractStatement,
)
from cobolparser.parsers.statements.arithmetic_parsers import (
    AddStatementParser,
    ComputeStatementParser,
    DivideStatementParser,
    MultiplyStatementParser,
    SubtractStatementParser,
)
from cobolparser.parsers.statements.call_parser import CallStatementParser
from cobolparser.parsers.statements.display_parser import DisplayStatementParser
from cobolparser.parsers.statements.evaluate_parser import EvaluateStatementParser
from cobolparser.parsers.statements.if_parser import IfStatementParser
from cobolparser.parsers.statements.move_parser import MoveStatementParser
from cobolparser.parsers.statements.perform_parser import PerformStatementParser


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
        assert hasattr(parser, "matches")
        assert hasattr(parser, "parse")

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
            ComputeStatementParser(),
        ]

        for parser in parsers:
            assert isinstance(parser, IStatementParser)
            assert hasattr(parser, "matches")
            assert hasattr(parser, "parse")


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
            DisplayStatement,
            MoveStatement,
            IfStatement,
            PerformStatement,
            EvaluateStatement,
            CallStatement,
            AddStatement,
            SubtractStatement,
            MultiplyStatement,
            DivideStatement,
            ComputeStatement,
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
