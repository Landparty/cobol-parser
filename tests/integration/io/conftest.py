"""Apply the ``io`` marker to every test collected in this directory.

Structural enforcement (in addition to the parent directory's marker):
new files here cannot drift out of ``-m io`` selection.
"""

from pathlib import Path

import pytest

_THIS_DIR = Path(__file__).parent


def pytest_collection_modifyitems(items):
    for item in items:
        if _THIS_DIR in item.path.parents:
            item.add_marker(pytest.mark.io)
