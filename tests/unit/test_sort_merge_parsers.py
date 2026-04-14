"""Unit tests for SortStatementParser and MergeStatementParser.

Tests parsers directly via TokenStream, asserting on AST node fields.
Covers:
- SORT basic file name
- SORT ON ASCENDING/DESCENDING KEY
- SORT with multiple keys
- SORT WITH DUPLICATES IN ORDER
- SORT COLLATING SEQUENCE IS
- SORT USING file-list
- SORT GIVING file-list
- SORT INPUT PROCEDURE IS para [THRU para]
- SORT OUTPUT PROCEDURE IS para [THRU para]
- MERGE basic
- MERGE ON KEY
- MERGE COLLATING SEQUENCE IS
- MERGE USING multiple files
- MERGE GIVING
- MERGE OUTPUT PROCEDURE IS [THRU]
- matches() on correct and wrong tokens
- to_dict() structure for both SORT and MERGE
"""

from cobolparser.core.token_stream import TokenStream
from cobolparser.lexer import Token, TokenType
from cobolparser.models.ast_base import SourceLocation
from cobolparser.parsers.statements.sort_merge_parsers import (
    MergeStatementParser,
    SortStatementParser,
)


def _loc() -> SourceLocation:
    return SourceLocation(1, 1)


def _tok(ttype: TokenType, value: str) -> Token:
    return Token(ttype, value, _loc())


def _ident(value: str) -> Token:
    return _tok(TokenType.IDENTIFIER, value)


def _period() -> Token:
    return _tok(TokenType.PERIOD, ".")


def _eof() -> Token:
    return _tok(TokenType.EOF, "")


def _stream(*tokens: Token) -> TokenStream:
    return TokenStream(list(tokens))


# ---------------------------------------------------------------------------
# SortStatementParser
# ---------------------------------------------------------------------------


class TestSortStatementParserMatches:
    def test_matches_sort_token(self):
        parser = SortStatementParser()
        stream = _stream(_tok(TokenType.SORT, "SORT"), _eof())
        assert parser.matches(stream) is True

    def test_matches_sort_identifier_fallback(self):
        parser = SortStatementParser()
        stream = _stream(_ident("SORT"), _eof())
        assert parser.matches(stream) is True

    def test_does_not_match_merge(self):
        parser = SortStatementParser()
        stream = _stream(_tok(TokenType.MERGE, "MERGE"), _eof())
        assert parser.matches(stream) is False

    def test_does_not_match_empty_stream(self):
        parser = SortStatementParser()
        stream = _stream(_eof())
        assert parser.matches(stream) is False


class TestSortStatementParserParse:
    def test_sort_sets_file_name(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ON"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("USING"),
            _ident("IN-FILE"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert stmt.file_name == "SORT-FILE"

    def test_sort_ascending_key(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ON"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert len(stmt.keys) >= 1
        assert stmt.keys[0]["field"] == "FIELD-A"
        assert stmt.keys[0]["order"] == "ASCENDING"

    def test_sort_descending_key(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ON"),
            _ident("DESCENDING"),
            _ident("KEY"),
            _ident("FIELD-B"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert stmt.keys[0]["order"] == "DESCENDING"

    def test_sort_multiple_keys(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ON"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("ON"),
            _ident("DESCENDING"),
            _ident("KEY"),
            _ident("FIELD-B"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert len(stmt.keys) == 2
        assert stmt.keys[0]["order"] == "ASCENDING"
        assert stmt.keys[1]["order"] == "DESCENDING"

    def test_sort_key_multiple_fields(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("FIELD-B"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert len(stmt.keys) == 2

    def test_sort_with_duplicates(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ON"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("WITH"),
            _ident("DUPLICATES"),
            _ident("IN"),
            _ident("ORDER"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert stmt.duplicates_in_order is True

    def test_sort_collating_sequence(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("COLLATING"),
            _ident("SEQUENCE"),
            _ident("IS"),
            _ident("EBCDIC-COLLATING"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert stmt.collating_sequence == "EBCDIC-COLLATING"

    def test_sort_using_single_file(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("USING"),
            _ident("IN-FILE"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert "IN-FILE" in stmt.using_files

    def test_sort_using_multiple_files(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("USING"),
            _ident("IN-FILE-1"),
            _ident("IN-FILE-2"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert "IN-FILE-1" in stmt.using_files
        assert "IN-FILE-2" in stmt.using_files

    def test_sort_giving_file(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("USING"),
            _ident("IN-FILE"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert "OUT-FILE" in stmt.giving_files

    def test_sort_input_procedure(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("INPUT"),
            _ident("PROCEDURE"),
            _ident("IS"),
            _ident("BUILD-SORT-INPUT"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert stmt.input_procedure == "BUILD-SORT-INPUT"
        assert stmt.input_procedure_thru is None

    def test_sort_input_procedure_thru(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("INPUT"),
            _ident("PROCEDURE"),
            _ident("IS"),
            _ident("PARA-START"),
            _ident("THRU"),
            _ident("PARA-END"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert stmt.input_procedure == "PARA-START"
        assert stmt.input_procedure_thru == "PARA-END"

    def test_sort_output_procedure(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("USING"),
            _ident("IN-FILE"),
            _ident("OUTPUT"),
            _ident("PROCEDURE"),
            _ident("IS"),
            _ident("PROCESS-SORTED"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert stmt.output_procedure == "PROCESS-SORTED"
        assert stmt.output_procedure_thru is None

    def test_sort_output_procedure_through(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("USING"),
            _ident("IN-FILE"),
            _ident("OUTPUT"),
            _ident("PROCEDURE"),
            _ident("IS"),
            _ident("OUT-START"),
            _ident("THROUGH"),
            _ident("OUT-END"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert stmt.output_procedure == "OUT-START"
        assert stmt.output_procedure_thru == "OUT-END"

    def test_sort_statement_type(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        assert stmt.statement_type == "SORT"

    def test_sort_to_dict_structure(self):
        tokens = [
            _tok(TokenType.SORT, "SORT"),
            _ident("SORT-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("USING"),
            _ident("IN-FILE"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = SortStatementParser().parse(_stream(*tokens))
        d = stmt.to_dict()
        assert d["statement_type"] == "SORT"
        assert "file_name" in d
        assert "keys" in d
        assert "duplicates_in_order" in d
        assert "collating_sequence" in d
        assert "input_procedure" in d
        assert "input_procedure_thru" in d
        assert "output_procedure" in d
        assert "output_procedure_thru" in d
        assert "using_files" in d
        assert "giving_files" in d


# ---------------------------------------------------------------------------
# MergeStatementParser
# ---------------------------------------------------------------------------


class TestMergeStatementParserMatches:
    def test_matches_merge_token(self):
        parser = MergeStatementParser()
        stream = _stream(_tok(TokenType.MERGE, "MERGE"), _eof())
        assert parser.matches(stream) is True

    def test_matches_merge_identifier_fallback(self):
        parser = MergeStatementParser()
        stream = _stream(_ident("MERGE"), _eof())
        assert parser.matches(stream) is True

    def test_does_not_match_sort(self):
        parser = MergeStatementParser()
        stream = _stream(_tok(TokenType.SORT, "SORT"), _eof())
        assert parser.matches(stream) is False

    def test_does_not_match_empty_stream(self):
        parser = MergeStatementParser()
        stream = _stream(_eof())
        assert parser.matches(stream) is False


class TestMergeStatementParserParse:
    def test_merge_sets_file_name(self):
        tokens = [
            _tok(TokenType.MERGE, "MERGE"),
            _ident("MERGE-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("FIELD-A"),
            _ident("USING"),
            _ident("IN-1"),
            _ident("IN-2"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = MergeStatementParser().parse(_stream(*tokens))
        assert stmt.file_name == "MERGE-FILE"
        assert stmt.statement_type == "MERGE"

    def test_merge_ascending_key(self):
        tokens = [
            _tok(TokenType.MERGE, "MERGE"),
            _ident("MERGE-FILE"),
            _ident("ON"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("SORT-KEY"),
            _ident("USING"),
            _ident("FILE-A"),
            _ident("FILE-B"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = MergeStatementParser().parse(_stream(*tokens))
        assert len(stmt.keys) == 1
        assert stmt.keys[0]["field"] == "SORT-KEY"
        assert stmt.keys[0]["order"] == "ASCENDING"

    def test_merge_multiple_using_files(self):
        tokens = [
            _tok(TokenType.MERGE, "MERGE"),
            _ident("MERGE-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("KEY-FIELD"),
            _ident("USING"),
            _ident("FILE-A"),
            _ident("FILE-B"),
            _ident("FILE-C"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = MergeStatementParser().parse(_stream(*tokens))
        assert "FILE-A" in stmt.using_files
        assert "FILE-B" in stmt.using_files
        assert "FILE-C" in stmt.using_files

    def test_merge_giving_file(self):
        tokens = [
            _tok(TokenType.MERGE, "MERGE"),
            _ident("MERGE-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("KEY-FIELD"),
            _ident("USING"),
            _ident("FILE-A"),
            _ident("FILE-B"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = MergeStatementParser().parse(_stream(*tokens))
        assert "OUT-FILE" in stmt.giving_files

    def test_merge_collating_sequence(self):
        tokens = [
            _tok(TokenType.MERGE, "MERGE"),
            _ident("MERGE-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("KEY-FIELD"),
            _ident("COLLATING"),
            _ident("SEQUENCE"),
            _ident("IS"),
            _ident("MY-COLLATION"),
            _ident("USING"),
            _ident("FILE-A"),
            _ident("FILE-B"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = MergeStatementParser().parse(_stream(*tokens))
        assert stmt.collating_sequence == "MY-COLLATION"

    def test_merge_output_procedure(self):
        tokens = [
            _tok(TokenType.MERGE, "MERGE"),
            _ident("MERGE-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("KEY-FIELD"),
            _ident("USING"),
            _ident("FILE-A"),
            _ident("FILE-B"),
            _ident("OUTPUT"),
            _ident("PROCEDURE"),
            _ident("IS"),
            _ident("PROCESS-MERGED"),
            _period(),
            _eof(),
        ]
        stmt = MergeStatementParser().parse(_stream(*tokens))
        assert stmt.output_procedure == "PROCESS-MERGED"
        assert stmt.output_procedure_thru is None

    def test_merge_output_procedure_thru(self):
        tokens = [
            _tok(TokenType.MERGE, "MERGE"),
            _ident("MERGE-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("KEY-FIELD"),
            _ident("USING"),
            _ident("FILE-A"),
            _ident("FILE-B"),
            _ident("OUTPUT"),
            _ident("PROCEDURE"),
            _ident("IS"),
            _ident("PARA-BEGIN"),
            _ident("THRU"),
            _ident("PARA-FINISH"),
            _period(),
            _eof(),
        ]
        stmt = MergeStatementParser().parse(_stream(*tokens))
        assert stmt.output_procedure == "PARA-BEGIN"
        assert stmt.output_procedure_thru == "PARA-FINISH"

    def test_merge_to_dict_structure(self):
        tokens = [
            _tok(TokenType.MERGE, "MERGE"),
            _ident("MERGE-FILE"),
            _ident("ASCENDING"),
            _ident("KEY"),
            _ident("KEY-FIELD"),
            _ident("USING"),
            _ident("FILE-A"),
            _ident("FILE-B"),
            _ident("GIVING"),
            _ident("OUT-FILE"),
            _period(),
            _eof(),
        ]
        stmt = MergeStatementParser().parse(_stream(*tokens))
        d = stmt.to_dict()
        assert d["statement_type"] == "MERGE"
        assert "file_name" in d
        assert "keys" in d
        assert "collating_sequence" in d
        assert "output_procedure" in d
        assert "output_procedure_thru" in d
        assert "using_files" in d
        assert "giving_files" in d
