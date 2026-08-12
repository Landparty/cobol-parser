"""Apply the ``integration`` marker to every test collected under tests/integration/.

This is structural: individual files no longer need (but may keep) their own
``pytestmark = pytest.mark.integration`` lines, and new files cannot drift out
of ``-m integration`` selection.
"""

from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items):
    for item in items:
        if _THIS_DIR in item.path.parents:
            item.add_marker(pytest.mark.integration)
