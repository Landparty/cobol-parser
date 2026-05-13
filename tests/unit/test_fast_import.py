"""Import-guard tests for the optional Cython extension modules.

These tests run regardless of whether Cython extensions are compiled.
When compiled, they verify the fast-path classes load and behave correctly.
When not compiled, they skip gracefully.
"""

import pytest


def test_fast_lexer_loads():
    mod = pytest.importorskip(
        "cobolparser._lexer_fast", reason="_lexer_fast extension not compiled"
    )
    assert mod.CobolLexer is not None


def test_fast_preprocess_loads():
    mod = pytest.importorskip(
        "cobolparser._preprocess_fast", reason="_preprocess_fast extension not compiled"
    )
    assert callable(mod.normalize_fixed_format)


def test_fast_lexer_is_active():
    """CobolLexer in lexer module should be the Cython class when compiled."""
    fast = pytest.importorskip(
        "cobolparser._lexer_fast", reason="_lexer_fast extension not compiled"
    )
    from cobolparser.lexer import CobolLexer

    assert (
        CobolLexer is fast.CobolLexer
    ), "lexer.CobolLexer should be the Cython class when _lexer_fast is compiled"


def test_fast_preprocess_is_active():
    """normalize_fixed_format in preprocess should be the Cython version when compiled."""
    fast = pytest.importorskip(
        "cobolparser._preprocess_fast", reason="_preprocess_fast extension not compiled"
    )
    from cobolparser.preprocess import normalize_fixed_format

    assert (
        normalize_fixed_format is fast.normalize_fixed_format
    ), "preprocess.normalize_fixed_format should be the Cython version when compiled"


def test_fast_lexer_produces_correct_tokens():
    """Fast-path lexer must produce identical output to the pure-Python lexer."""
    fast = pytest.importorskip(
        "cobolparser._lexer_fast", reason="_lexer_fast extension not compiled"
    )
    from cobolparser.lexer import _CobolLexerPure

    source = (
        "       IDENTIFICATION DIVISION.\n"
        "       PROGRAM-ID. TESTPROG.\n"
        "       DATA DIVISION.\n"
        "       WORKING-STORAGE SECTION.\n"
        "       01 WS-COUNTER PIC 9(4) VALUE ZEROS.\n"
        "       PROCEDURE DIVISION.\n"
        "           MOVE 1 TO WS-COUNTER.\n"
        "           STOP RUN.\n"
    )

    fast_tokens = fast.CobolLexer(source).tokenize()
    pure_tokens = _CobolLexerPure(source).tokenize()

    assert len(fast_tokens) == len(
        pure_tokens
    ), f"Token count mismatch: fast={len(fast_tokens)} pure={len(pure_tokens)}"
    for i, (ft, pt) in enumerate(zip(fast_tokens, pure_tokens, strict=True)):
        assert ft.type == pt.type, f"Token[{i}] type mismatch: {ft.type} vs {pt.type}"
        assert (
            ft.value == pt.value
        ), f"Token[{i}] value mismatch: {ft.value!r} vs {pt.value!r}"
