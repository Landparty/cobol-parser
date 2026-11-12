"""The MCP server's tool names, by group.

Kept apart from :mod:`.server` so the CLI can list them in ``cobol-parser mcp
--help`` without the ``[mcp]`` extra installed.
"""

from __future__ import annotations

#: The tools by group. ``--tools`` takes a profile, group or tool names.
TOOL_GROUPS: dict[str, tuple[str, ...]] = {
    "core": (
        "codebase_overview",
        "program_brief",
        "explain_symbol",
        "callers_of",
        "impact_of_change",
        "where_from",
        "record_layout",
        "lint",
        "business_rules",
        "read_source",
        "read_procedure",
        "find_statements",
        "slice",
        "check_claims",
    ),
    "data": ("decode_record", "gen_fixtures", "diff_programs"),
    "jcl": ("jcl_job", "jobs_running", "dataset_users"),
}

ALL_TOOLS: tuple[str, ...] = tuple(t for g in TOOL_GROUPS.values() for t in g)
