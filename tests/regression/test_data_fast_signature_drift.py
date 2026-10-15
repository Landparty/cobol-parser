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

import ast
import contextlib
import importlib
import logging
import os
import pathlib
import subprocess
import sys
import textwrap
import types
import warnings

import pytest

from cobolparser import CobolParser
from cobolparser._accel import ENV_VAR
from cobolparser.parsers.divisions import data_clauses

MODULE = "cobolparser.parsers.divisions.data_clauses"
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

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
        with _accel_opted_in():
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


@contextlib.contextmanager
def _accel_opted_in():
    """Set ``COBOLPARSER_ACCEL=1`` for the block, restoring it afterwards.

    The extension is only looked for under the opt-in, so every probe below
    has to reload ``data_clauses`` with it set to examine anything at all.
    """
    saved = os.environ.get(ENV_VAR)
    os.environ[ENV_VAR] = "1"
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop(ENV_VAR, None)
        else:
            os.environ[ENV_VAR] = saved


@contextlib.contextmanager
def _real_extension_opted_in():
    """Reload ``data_clauses`` with the opt-in set and the real extension."""
    try:
        with _accel_opted_in():
            yield importlib.reload(sys.modules[MODULE])
    finally:
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
    with _real_extension_opted_in() as reloaded:
        assert reloaded._HAS_DATA_FAST


def test_extension_is_ignored_without_the_opt_in(caplog, monkeypatch):
    """Pure Python is the default: not even a stale binary is looked at."""
    monkeypatch.delenv(ENV_VAR, raising=False)
    monkeypatch.setitem(sys.modules, "cobolparser._data_fast", _stale_extension())
    try:
        with caplog.at_level(logging.WARNING, logger=MODULE):
            reloaded = importlib.reload(sys.modules[MODULE])
            assert reloaded._HAS_DATA_FAST is False
            assert reloaded._fast_data_item_clauses is None
        assert not [r for r in caplog.records if "_data_fast" in r.getMessage()]
    finally:
        monkeypatch.undo()
        importlib.reload(sys.modules[MODULE])


def test_stale_extension_is_rejected_and_reported(caplog):
    with caplog.at_level(logging.WARNING, logger=MODULE):
        with _data_fast_replaced_by(_stale_extension()) as (reloaded, caught):
            assert reloaded._HAS_DATA_FAST is False
            assert reloaded._fast_data_item_clauses is None

            messages = [r.getMessage() for r in caplog.records]
            assert any(
                "_data_fast" in m and "disabled" in m for m in messages
            ), messages
            # The message has to name the fix, not just the symptom.
            assert any("build_ext" in m for m in messages), messages

    # Reported through logging, never `warnings.warn`: this fires at import,
    # and a warning here becomes an `import cobolparser` failure under
    # `-W error` -- worse than the degraded parse the guard exists to prevent.
    assert [w for w in caught if w.category is RuntimeWarning] == []


def test_import_survives_warnings_as_errors():
    """A stale extension must not break `import cobolparser` under -W error."""
    program = textwrap.dedent("""
        import sys, types
        stale = types.ModuleType("cobolparser._data_fast")
        stale.parse_data_item_clauses_fast = (
            lambda a1, a2, a3, a4, a5, a6, a7, a8, a9, a10,
            a11, a12, a13, a14, a15, a16, a17, a18: 0
        )
        sys.modules["cobolparser._data_fast"] = stale
        import cobolparser
        from cobolparser.parsers.divisions import data_clauses
        assert data_clauses._HAS_DATA_FAST is False
        print("OK")
        """)
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", program],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        env={**os.environ, ENV_VAR: "1"},
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK" in result.stdout


def test_arg_count_constant_matches_the_real_call_site():
    """The probe is only honest if the constant tracks the actual call.

    ``_data_fast_usable`` checks the constant against the compiled extension,
    and another test checks the same pair -- but nothing ties either to the
    literal argument list in ``parse_data_item``. Bump the constant and the
    ``.pyx`` while missing the call site and the probe still passes, while the
    real call raises ``TypeError``: the original bug, now unguarded *and*
    unreported. Count the call's arguments straight out of the source.
    """
    source = pathlib.Path(data_clauses.__file__).read_text()
    tree = ast.parse(source)

    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_fast_data_item_clauses"
    ]
    assert len(calls) == 1, f"expected exactly one fast-path call, found {len(calls)}"

    call = calls[0]
    assert not call.keywords, "the fast-path call must stay positional"
    assert not any(
        isinstance(a, ast.Starred) for a in call.args
    ), "a starred argument would make the call's arity unknowable here"
    assert len(call.args) == data_clauses._DATA_FAST_ARG_COUNT


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
    with _real_extension_opted_in() as reloaded:
        assert reloaded._HAS_DATA_FAST
        with_fast = CobolParser().parse(PROGRAM).ast.to_json()

    with _data_fast_replaced_by(_stale_extension()) as (reloaded, _):
        assert reloaded._HAS_DATA_FAST is False
        without_fast = CobolParser().parse(PROGRAM).ast.to_json()

    assert with_fast == without_fast
