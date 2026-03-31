"""Unit tests for StringStatement and UnstringStatement AST models.

These models exist in models/statements/data.py but have no parser,
so they are tested via direct instantiation (currently at 38% coverage).
"""
import pytest
from cobolparser.models.statements.data import StringStatement, UnstringStatement
from cobolparser.models.ast_base import SourceLocation


LOC = SourceLocation(line=1, column=1)


class TestStringStatementModel:
    """Direct unit tests for StringStatement."""

    def test_init_sets_node_type(self):
        """StringStatement statement_type is 'STRING' (node_type is the base-class 'Statement')."""
        stmt = StringStatement(LOC)
        assert stmt.statement_type == "STRING"

    def test_init_statement_type(self):
        """StringStatement statement_type is 'STRING'."""
        stmt = StringStatement(LOC)
        assert stmt.statement_type == "STRING"

    def test_init_default_on_overflow(self):
        """on_overflow defaults to None."""
        stmt = StringStatement(LOC)
        assert stmt.on_overflow is None

    def test_init_default_not_on_overflow(self):
        """not_on_overflow defaults to None."""
        stmt = StringStatement(LOC)
        assert stmt.not_on_overflow is None

    def test_init_default_operands(self):
        """operands list starts empty."""
        stmt = StringStatement(LOC)
        assert stmt.operands == []

    def test_to_dict_contains_node_type(self):
        """to_dict includes statement_type key identifying this as STRING."""
        stmt = StringStatement(LOC)
        d = stmt.to_dict()
        assert d["statement_type"] == "STRING"

    def test_to_dict_contains_location(self):
        """to_dict includes location."""
        stmt = StringStatement(LOC)
        d = stmt.to_dict()
        assert "location" in d

    def test_to_dict_contains_statement_type(self):
        """to_dict includes statement_type key."""
        stmt = StringStatement(LOC)
        d = stmt.to_dict()
        assert "statement_type" in d

    def test_to_dict_is_dict(self):
        """to_dict returns a non-empty dict."""
        stmt = StringStatement(LOC)
        d = stmt.to_dict()
        assert isinstance(d, dict)
        assert len(d) > 0

    def test_location_stored(self):
        """Location is accessible on the statement."""
        stmt = StringStatement(LOC)
        assert stmt.location.line == 1
        assert stmt.location.column == 1

    def test_on_overflow_can_be_set(self):
        """on_overflow can be assigned a list."""
        stmt = StringStatement(LOC)
        stmt.on_overflow = []
        assert stmt.on_overflow == []

    def test_not_on_overflow_can_be_set(self):
        """not_on_overflow can be assigned a list."""
        stmt = StringStatement(LOC)
        stmt.not_on_overflow = []
        assert stmt.not_on_overflow == []


class TestUnstringStatementModel:
    """Direct unit tests for UnstringStatement."""

    def test_init_sets_node_type(self):
        """UnstringStatement statement_type is 'UNSTRING' (node_type is the base-class 'Statement')."""
        stmt = UnstringStatement(LOC)
        assert stmt.statement_type == "UNSTRING"

    def test_init_statement_type(self):
        """UnstringStatement statement_type is 'UNSTRING'."""
        stmt = UnstringStatement(LOC)
        assert stmt.statement_type == "UNSTRING"

    def test_init_default_on_overflow(self):
        """on_overflow defaults to None."""
        stmt = UnstringStatement(LOC)
        assert stmt.on_overflow is None

    def test_init_default_not_on_overflow(self):
        """not_on_overflow defaults to None."""
        stmt = UnstringStatement(LOC)
        assert stmt.not_on_overflow is None

    def test_to_dict_contains_node_type(self):
        """to_dict includes statement_type key identifying this as UNSTRING."""
        stmt = UnstringStatement(LOC)
        d = stmt.to_dict()
        assert d["statement_type"] == "UNSTRING"

    def test_to_dict_contains_location(self):
        """to_dict includes location."""
        stmt = UnstringStatement(LOC)
        d = stmt.to_dict()
        assert "location" in d

    def test_to_dict_is_dict(self):
        """to_dict returns a non-empty dict."""
        stmt = UnstringStatement(LOC)
        d = stmt.to_dict()
        assert isinstance(d, dict)
        assert len(d) > 0

    def test_location_stored(self):
        """Location is accessible on the statement."""
        stmt = UnstringStatement(LOC)
        assert stmt.location.line == 1
        assert stmt.location.column == 1

    def test_on_overflow_can_be_set(self):
        """on_overflow can be assigned a list."""
        stmt = UnstringStatement(LOC)
        stmt.on_overflow = []
        assert stmt.on_overflow == []

    def test_not_on_overflow_can_be_set(self):
        """not_on_overflow can be assigned a list."""
        stmt = UnstringStatement(LOC)
        stmt.not_on_overflow = []
        assert stmt.not_on_overflow == []
