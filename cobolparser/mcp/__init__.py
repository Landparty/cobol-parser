"""An MCP server for AI agents analyzing COBOL with this library.

``cobol-parser mcp --root DIR`` serves the tools in :mod:`.tools` over stdio.
The tools themselves (:class:`CobolTools`), the workspace guard and cache
(:class:`Workspace`) and the response envelope import nothing beyond the
standard library and ``cobolparser``; only :mod:`.server` needs the ``[mcp]``
extra. Design: ``docs/plans/2026-10-15-mcp-server-design.md``.
"""

from .envelope import CAVEAT_KINDS, MCP_SURFACE_VERSION, ToolError
from .tools import CobolTools
from .workspace import Workspace

__all__ = [
    "CAVEAT_KINDS",
    "MCP_SURFACE_VERSION",
    "CobolTools",
    "ToolError",
    "Workspace",
]
