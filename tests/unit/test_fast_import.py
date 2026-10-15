"""Import-guard tests for the optional Cython extension modules.

These tests run regardless of whether Cython extensions are compiled.
When compiled, they verify the fast-path classes load and behave correctly,
and that they are swapped in only under the ``COBOLPARSER_ACCEL=1`` opt-in
(pure Python is the default). When not compiled, they skip gracefully.
"""

import os
import subprocess
import sys

import pytest

from cobolparser._accel import ENV_VAR, accelerators_enabled


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


def _active_backends(env_value):
    """Which lexer / normalizer a fresh interpreter picks, as two booleans.

    A subprocess, so the module-level choice is made from scratch under the
    given ``COBOLPARSER_ACCEL`` value (``None`` = unset) rather than reusing
    whatever this test process imported.
    """
    env = {k: v for k, v in os.environ.items() if k != ENV_VAR}
    if env_value is not None:
        env[ENV_VAR] = env_value
    program = (
        "import cobolparser.lexer as L, cobolparser.preprocess as P\n"
        "print(L.CobolLexer is not L._CobolLexerPure,"
        " P.normalize_fixed_format is not P._normalize_fixed_format_pure)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout.split()


def test_pure_python_is_the_default_even_when_compiled():
    """Without the opt-in the extensions are never swapped in."""
    assert _active_backends(None) == ["False", "False"]
    assert _active_backends("0") == ["False", "False"]


def test_fast_lexer_is_active():
    """CobolLexer in lexer module is the Cython class under the opt-in."""
    pytest.importorskip(
        "cobolparser._lexer_fast", reason="_lexer_fast extension not compiled"
    )
    assert _active_backends("1")[0] == "True"


def test_fast_preprocess_is_active():
    """normalize_fixed_format is the Cython version under the opt-in."""
    pytest.importorskip(
        "cobolparser._preprocess_fast", reason="_preprocess_fast extension not compiled"
    )
    assert _active_backends("1")[1] == "True"


def test_accelerators_enabled_spellings(monkeypatch):
    for value in ("1", "true", "YES", " on "):
        monkeypatch.setenv(ENV_VAR, value)
        assert accelerators_enabled()
    for value in ("", "0", "false", "no", "off", "2"):
        monkeypatch.setenv(ENV_VAR, value)
        assert not accelerators_enabled()
    monkeypatch.delenv(ENV_VAR)
    assert not accelerators_enabled()


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
