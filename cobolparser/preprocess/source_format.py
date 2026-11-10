"""Alias of :mod:`cobolparser._source_text.source_format`, its home since the
lexer stopped importing :mod:`cobolparser.preprocess` (the module moved below
the lexer in the layer stack). The same module object, so a name read or
patched here is the one the code uses."""

import sys

from .._source_text import source_format as _module
from .._source_text.source_format import *  # noqa: F403

sys.modules[__name__] = _module
