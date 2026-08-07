"""Regression tests: free-form `*>` inline comments are stripped by the lexer.

Prior to this fix, `*>` (the free-form COBOL inline-comment marker, legal in
both fixed- and free-form source) was recognized nowhere in the pipeline:
`normalize_fixed_format` only strips *whole* comment lines (column-7
indicator `*`/`/`/`D`), and the lexer tokenized `*` as `MULTIPLY_OP` and `>`
as `GREATER`, then lexed the comment's English words as ordinary
identifiers/keywords. A comment like `*> start at 2 ...` could lex its
"start" as the `START` keyword and produce a real (bogus)
`IOStartStatement` with no actual START verb anywhere in the source --
confirmed via `examples/cobol/shamrice/unstring.cbl:243`, previously
special-cased as a known-unresolved entry in
`tests/integration/test_boundary_inventory_corpus.py`.

Fix: `tokenize_program_text` (pure-Python `lexer.py` and the Cython
`_lexer_fast.pyx` mirror) now recognizes `*>` and emits the remainder of the
line as a single `COMMENT` token, checked before the single-character-token
dispatch that would otherwise read `*` as `MULTIPLY_OP`. `COMMENT` tokens
are already skipped by every statement parser via `skip_whitespace()`
(`parsers/statements/_utils.py`), so no parser changes were needed.
"""

from cobolparser import parse_cobol
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators import ProgramLayoutIndex
from cobolparser.lexer import CobolLexer, TokenType

try:
    from cobolparser._lexer_fast import CobolLexer as _FastLexer
except ImportError:
    _FastLexer = None


class TestInlineCommentStripping:
    def test_trailing_comment_after_statement_is_dropped(self):
        source = """       IDENTIFICATION DIVISION.
       PROGRAM-ID. TEST.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-STR PIC X(10).
       PROCEDURE DIVISION.
           MOVE "ABC" TO WS-STR *> start at 2 to not include quote
           STOP RUN.
"""
        result = parse_cobol(source, filename="test.cbl")
        assert result.success, result.errors

        procedure = result.ast.get_division("PROCEDURE")
        statements = [
            stmt.__class__.__name__
            for para in procedure.paragraphs
            for stmt in para.statements
        ]
        assert statements == ["MoveStatement", "StopStatement"]

    def test_comment_word_does_not_become_a_keyword_token(self):
        """A comment word that collides with a COBOL verb (START) must not
        surface as a token at all -- neither as START nor as anything else."""
        line = 'DISPLAY "X" *> start at 2 to not include quote'
        tokens = CobolLexer(line, free_form=True).tokenize()
        real_tokens = [
            t for t in tokens if t.type not in (TokenType.EOF, TokenType.NEWLINE)
        ]

        assert [t.type for t in real_tokens] == [
            TokenType.DISPLAY,
            TokenType.STRING_LITERAL,
            TokenType.COMMENT,
        ]
        assert real_tokens[-1].value == "*> start at 2 to not include quote"

    def test_leading_comment_on_own_line(self):
        line = "*> whole line is a comment"
        tokens = CobolLexer(line, free_form=True).tokenize()
        real_tokens = [
            t for t in tokens if t.type not in (TokenType.EOF, TokenType.NEWLINE)
        ]
        assert len(real_tokens) == 1
        assert real_tokens[0].type == TokenType.COMMENT

    def test_asterisk_greater_inside_string_literal_is_not_a_comment(self):
        """`*>` inside a quoted literal is literal text, not a comment start --
        the string-literal branch in tokenize_program_text runs first."""
        line = 'DISPLAY "A *> B"'
        tokens = CobolLexer(line, free_form=True).tokenize()
        real_tokens = [
            t for t in tokens if t.type not in (TokenType.EOF, TokenType.NEWLINE)
        ]
        assert [t.type for t in real_tokens] == [
            TokenType.DISPLAY,
            TokenType.STRING_LITERAL,
        ]
        assert real_tokens[1].value == "A *> B"

    def test_exponentiation_operator_is_unaffected(self):
        """`**` (exponentiation) must not be swallowed by the `*>` check."""
        line = "COMPUTE WS-X = WS-Y ** 2"
        tokens = CobolLexer(line, free_form=True).tokenize()
        real_tokens = [
            t for t in tokens if t.type not in (TokenType.EOF, TokenType.NEWLINE)
        ]
        assert TokenType.COMMENT not in [t.type for t in real_tokens]

    def test_unstring_shamrice_program_no_longer_has_phantom_start(self):
        result = parse_cobol("examples/cobol/shamrice/unstring.cbl")
        assert result.ast is not None, result.errors
        index = ProgramLayoutIndex.build(result.ast)
        report = BoundaryInventoryAnalyzer().analyze(result.ast, index)
        assert not any("START" in u for u in report.unresolved)

    def test_pure_and_cython_lexers_agree_on_inline_comment(self):
        if _FastLexer is None:
            return  # Cython extension not built in this environment
        line = 'MOVE "ABC" TO WS-STR *> trailing comment with keywords MOVE TO'
        pure_tokens = CobolLexer(line, free_form=True).tokenize()
        fast_tokens = _FastLexer(line, free_form=True).tokenize()
        assert [(t.type, t.value) for t in pure_tokens] == [
            (t.type, t.value) for t in fast_tokens
        ]
