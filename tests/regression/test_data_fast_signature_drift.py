"""A ``_data_fast`` build older than its caller must not break parsing.

``cobolparser._data_fast`` is compiled separately from
``parsers.divisions.data_clauses``, so the binary can be older than the Python
module that calls it -- a stale in-place ``.so``, a cached ``build/`` tree, or
an installed wheel shadowing the source tree. The call site is unconditional
and positional, so before the import-time probe was added that drift raised a
``TypeError`` from the middle of every data-description entry: the division
loop recorded it as a generic error and recovered by abandoning the division,
so every program with a DATA DIVISION degraded to a near-empty AST that named
an argument count rather than the stale build behind it.

Observed on Python 3.14 against a helper compiled with 18 parameters while the
caller passed 19.
"""

import contextlib
import importlib
import sys
import types
import warnings

import pytest

from cobolparser import CobolParser
from cobolparser.parsers.divisions import data_clauses

MODULE = "cobolparser.parsers.divisions.data_clauses"

PROGRAM = (
    "       IDENTIFICATION DIVISION.\n"
    "       PROGRAM-ID. DEMO.\n"
    "       DATA DIVISION.\n"
    "       WORKING-STORAGE SECTION.\n"
    "       01 WS-COUNT PIC 9(4) VALUE 0.\n"
    "       01 WS-NAME  PIC X(20).\n"
    "       PROCEDURE DIVISION.\n"
    "       MAIN-PARA.\n"
    "           DISPLAY WS-NAME.\n"
    "           STOP RUN.\n"
)


@contextlib.contextmanager
def _data_fast_replaced_by(module):
    """Reload ``data_clauses`` seeing ``module`` as ``cobolparser._data_fast``.

    ``importlib.reload`` reuses the module's existing ``__dict__``, so the
    ``DataItemClauseParser`` that ``divisions.data`` already imported reads the
    reloaded ``_HAS_DATA_FAST`` too -- which is what makes an end-to-end parse
    inside this block exercise the fallback. Yields the reloaded module and the
    warnings raised while reloading, then restores the real import.
    """
    saved = sys.modules.get("cobolparser._data_fast")
    # A ``None`` entry in sys.modules makes ``import`` raise ImportError, which
    # is how a pure-Python install (no extension compiled) looks.
    sys.modules["cobolparser._data_fast"] = module
    try:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            reloaded = importlib.reload(sys.modules[MODULE])
        yield reloaded, caught
    finally:
        if saved is None:
            sys.modules.pop("cobolparser._data_fast", None)
        else:
            sys.modules["cobolparser._data_fast"] = saved
        importlib.reload(sys.modules[MODULE])


def _stale_extension():
    """A ``_data_fast`` stand-in compiled before the 19th parameter existed."""
    mod = types.ModuleType("cobolparser._data_fast")

    def parse_data_item_clauses_fast(
        a1, a2, a3, a4, a5, a6, a7, a8, a9, a10, a11, a12, a13, a14, a15, a16, a17, a18
    ):
        raise AssertionError("a mismatched helper must never be called")

    mod.parse_data_item_clauses_fast = parse_data_item_clauses_fast
    return mod


def test_arg_count_constant_matches_the_compiled_helper():
    """The probe's arity must track the real extension, not a stale guess."""
    fast = pytest.importorskip(
        "cobolparser._data_fast", reason="_data_fast extension not compiled"
    )
    import inspect

    params = inspect.signature(fast.parse_data_item_clauses_fast).parameters
    assert len(params) == data_clauses._DATA_FAST_ARG_COUNT


def test_probe_accepts_the_real_extension():
    fast = pytest.importorskip(
        "cobolparser._data_fast", reason="_data_fast extension not compiled"
    )
    assert data_clauses._data_fast_usable(fast.parse_data_item_clauses_fast)
    assert data_clauses._HAS_DATA_FAST


def test_stale_extension_is_rejected_and_reported():
    with _data_fast_replaced_by(_stale_extension()) as (reloaded, caught):
        assert reloaded._HAS_DATA_FAST is False
        assert reloaded._fast_data_item_clauses is None

        messages = [str(w.message) for w in caught if w.category is RuntimeWarning]
        assert any("_data_fast" in m and "disabled" in m for m in messages), messages
        # The warning has to name the fix, not just the symptom.
        assert any("build_ext" in m for m in messages), messages


def test_stale_extension_still_parses_the_data_division():
    """The regression itself: a stale binary must cost speed, not the AST."""
    with _data_fast_replaced_by(_stale_extension()) as (reloaded, _):
        assert reloaded._HAS_DATA_FAST is False

        result = CobolParser().parse(PROGRAM)

    assert result.success, [str(e) for e in result.errors]
    assert [d.division_name for d in result.ast.divisions] == [
        "IDENTIFICATION",
        "DATA",
        "PROCEDURE",
    ]
    items = {
        item.name: item.picture_clause.pattern if item.picture_clause else None
        for item in result.ast.find_all_by_type("CobolDataItem")
    }
    assert items == {"WS-COUNT": "9(4)", "WS-NAME": "X(20)"}


def test_missing_extension_is_silent():
    """An absent extension is normal (pure-Python install) -- no warning."""
    with _data_fast_replaced_by(None) as (reloaded, caught):
        assert reloaded._HAS_DATA_FAST is False
        assert [w for w in caught if w.category is RuntimeWarning] == []


def test_fast_and_fallback_agree_on_the_same_program():
    """Disabling the fast path must not change a single byte of the AST."""
    pytest.importorskip(
        "cobolparser._data_fast", reason="_data_fast extension not compiled"
    )
    assert data_clauses._HAS_DATA_FAST
    with_fast = CobolParser().parse(PROGRAM).ast.to_json()

    with _data_fast_replaced_by(_stale_extension()) as (reloaded, _):
        assert reloaded._HAS_DATA_FAST is False
        without_fast = CobolParser().parse(PROGRAM).ast.to_json()

    assert with_fast == without_fast
