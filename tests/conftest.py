"""Shared pytest fixtures for the cobol-parser test suite."""

from pathlib import Path

import pytest

from cobolparser.parser import CobolParser


@pytest.fixture
def parser() -> CobolParser:
    """Create a fresh COBOL parser instance."""
    return CobolParser()


@pytest.fixture
def samples_dir() -> Path:
    """Return the path to the shared test samples directory."""
    return Path(__file__).parent / "samples"
