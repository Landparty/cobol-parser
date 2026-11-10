"""docs/public-api.md's facade list is exactly ``cobolparser.__all__``."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import cobolparser

pytestmark = pytest.mark.contract

DOC = Path(__file__).resolve().parents[2] / "docs" / "public-api.md"


def _documented() -> list[str]:
    text = DOC.read_text(encoding="utf-8")
    block = text.split("<!-- public-api:facade -->", 1)[1]
    block = block.split("<!-- /public-api:facade -->", 1)[0]
    return re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", block)


def test_the_written_list_is_the_facade():
    documented = _documented()
    assert len(documented) == len(set(documented)), "a name is listed twice"
    assert set(documented) == set(cobolparser.__all__)


def test_every_public_name_is_importable():
    for name in cobolparser.__all__:
        assert hasattr(cobolparser, name), name
