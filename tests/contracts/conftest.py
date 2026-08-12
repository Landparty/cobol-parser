"""Apply the ``contract`` marker to every test collected under tests/contracts/.

This is structural: individual files no longer need (but may keep) their own
``pytestmark = pytest.mark.contract`` lines, and new files cannot drift out of
``-m contract`` selection.
"""

from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items):
    for item in items:
        if _THIS_DIR in item.path.parents:
            item.add_marker(pytest.mark.contract)
