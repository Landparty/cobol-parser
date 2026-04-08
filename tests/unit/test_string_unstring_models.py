"""Unit tests for StringStatement and UnstringStatement AST models.

These models exist in models/statements/data.py but have no parser,
so they are tested via direct instantiation.

Extended to cover setter methods and to_dict serialization.
"""

from cobolparser.models.ast_base import SourceLocation
from cobolparser.models.statements.data import (
    DisplayStatement,
    StringStatement,
    UnstringStatement,
)

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

    # --- Setter and serialization coverage ---

    def test_add_operand(self):
        stmt = StringStatement(LOC)
        stmt.add_operand("WS-FIRST")
        stmt.add_operand("WS-LAST")
        assert stmt.operands == ["WS-FIRST", "WS-LAST"]

    def test_set_into_target(self):
        stmt = StringStatement(LOC)
        stmt.set_into_target("WS-FULL-NAME")
        assert stmt.into_target == "WS-FULL-NAME"

    def test_set_pointer_variable(self):
        stmt = StringStatement(LOC)
        stmt.set_pointer_variable("WS-PTR")
        assert stmt.pointer_variable == "WS-PTR"

    def test_add_delimiter(self):
        stmt = StringStatement(LOC)
        stmt.add_delimiter("SPACES")
        stmt.add_delimiter("LOW-VALUES")
        assert stmt.delimiters == ["SPACES", "LOW-VALUES"]

    def test_set_on_overflow_clause_with_statements(self):
        stmt = StringStatement(LOC)
        overflow = DisplayStatement(SourceLocation(2, 1))
        overflow.add_display_item("OVERFLOW")
        stmt.set_on_overflow_clause([overflow])
        assert stmt.on_overflow is not None
        assert len(stmt.on_overflow) == 1

    def test_set_not_on_overflow_clause_with_statements(self):
        stmt = StringStatement(LOC)
        ok_stmt = DisplayStatement(SourceLocation(3, 1))
        ok_stmt.add_display_item("OK")
        stmt.set_not_on_overflow_clause([ok_stmt])
        assert stmt.not_on_overflow is not None
        assert len(stmt.not_on_overflow) == 1

    def test_to_dict_with_all_fields(self):
        stmt = StringStatement(LOC)
        stmt.add_operand("WS-A")
        stmt.add_delimiter("SPACES")
        stmt.set_into_target("WS-RESULT")
        stmt.set_pointer_variable("WS-PTR")
        overflow = DisplayStatement(SourceLocation(2, 1))
        overflow.add_display_item("ERR")
        stmt.set_on_overflow_clause([overflow])
        not_overflow = DisplayStatement(SourceLocation(3, 1))
        not_overflow.add_display_item("OK")
        stmt.set_not_on_overflow_clause([not_overflow])

        d = stmt.to_dict()
        assert d["operands"] == ["WS-A"]
        assert d["delimiters"] == ["SPACES"]
        assert d["into_target"] == "WS-RESULT"
        assert d["pointer_variable"] == "WS-PTR"
        assert len(d["on_overflow"]) == 1
        assert len(d["not_on_overflow"]) == 1


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

    # --- Setter and serialization coverage ---

    def test_set_source(self):
        stmt = UnstringStatement(LOC)
        stmt.set_source("WS-INPUT-STRING")
        assert stmt.source_operand == "WS-INPUT-STRING"

    def test_add_delimiter(self):
        stmt = UnstringStatement(LOC)
        stmt.add_delimiter("SPACES")
        stmt.add_delimiter(",")
        assert stmt.delimiters == ["SPACES", ","]

    def test_add_into_target_simple(self):
        stmt = UnstringStatement(LOC)
        stmt.add_into_target("WS-FIELD-1")
        assert len(stmt.into_targets) == 1
        assert stmt.into_targets[0]["target"] == "WS-FIELD-1"
        assert stmt.into_targets[0]["delimiter_var"] is None
        assert stmt.into_targets[0]["count_var"] is None

    def test_add_into_target_with_delimiter_and_count(self):
        stmt = UnstringStatement(LOC)
        stmt.add_into_target("WS-F1", delimiter_var="WS-D", count_var="WS-C")
        t = stmt.into_targets[0]
        assert t["target"] == "WS-F1"
        assert t["delimiter_var"] == "WS-D"
        assert t["count_var"] == "WS-C"

    def test_set_pointer_variable(self):
        stmt = UnstringStatement(LOC)
        stmt.set_pointer_variable("WS-PTR")
        assert stmt.pointer_variable == "WS-PTR"

    def test_set_on_overflow_clause_with_statements(self):
        stmt = UnstringStatement(LOC)
        overflow = DisplayStatement(SourceLocation(2, 1))
        overflow.add_display_item("OVERFLOW")
        stmt.set_on_overflow_clause([overflow])
        assert stmt.on_overflow is not None
        assert len(stmt.on_overflow) == 1

    def test_set_not_on_overflow_clause_with_statements(self):
        stmt = UnstringStatement(LOC)
        ok_stmt = DisplayStatement(SourceLocation(3, 1))
        ok_stmt.add_display_item("OK")
        stmt.set_not_on_overflow_clause([ok_stmt])
        assert stmt.not_on_overflow is not None

    def test_to_dict_with_all_fields(self):
        stmt = UnstringStatement(LOC)
        stmt.set_source("WS-INPUT")
        stmt.add_delimiter("SPACES")
        stmt.add_into_target("WS-O1", delimiter_var="WS-D1", count_var="WS-C1")
        stmt.add_into_target("WS-O2")
        stmt.set_pointer_variable("WS-PTR")
        overflow = DisplayStatement(SourceLocation(2, 1))
        overflow.add_display_item("ERR")
        stmt.set_on_overflow_clause([overflow])
        not_overflow = DisplayStatement(SourceLocation(3, 1))
        not_overflow.add_display_item("OK")
        stmt.set_not_on_overflow_clause([not_overflow])

        d = stmt.to_dict()
        assert d["source_operand"] == "WS-INPUT"
        assert d["delimiters"] == ["SPACES"]
        assert len(d["into_targets"]) == 2
        assert d["pointer_variable"] == "WS-PTR"
        assert len(d["on_overflow"]) == 1
        assert len(d["not_on_overflow"]) == 1
