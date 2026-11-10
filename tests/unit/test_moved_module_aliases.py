"""Names and modules that moved keep working at their old paths."""

from __future__ import annotations

import importlib
import warnings

import pytest

import cobolparser
from cobolparser import parser


def test_normalize_and_source_format_aliases_are_the_same_modules():
    from cobolparser._source_text import normalize, source_format

    assert importlib.import_module("cobolparser.preprocess._normalize") is normalize
    assert (
        importlib.import_module("cobolparser.preprocess.source_format") is source_format
    )
    from cobolparser.preprocess import normalize_fixed_format

    assert normalize_fixed_format is normalize.normalize_fixed_format


@pytest.mark.parametrize(
    "module,name",
    [
        ("cobolparser.preprocess", "parse_cobol_with_expansion"),
        ("cobolparser.preprocess.copybook_expander", "parse_cobol_with_expansion"),
        ("cobolparser.preprocess.copybook_expander", "warn_dropped_debug_lines"),
    ],
)
def test_moved_parse_helpers_resolve_with_a_warning(module, name):
    with pytest.warns(DeprecationWarning, match=f"cobolparser.parser.{name}"):
        found = getattr(importlib.import_module(module), name)
    assert found is getattr(parser, name)


def test_new_homes_do_not_warn():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        from cobolparser.parser import parse_cobol_with_expansion

        assert cobolparser.parse_cobol_with_expansion is parse_cobol_with_expansion
