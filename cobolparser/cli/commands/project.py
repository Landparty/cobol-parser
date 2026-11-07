"""Project-level subcommands: config (the resolved cobol.yml) and mcp (the
MCP server)."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from ...config import ConfigError, ProjectConfig
from .._common import _add_compact_arg, _add_output_arg, _fail, _json_out, _text_out

# -- config subcommand --------------------------------------------------------


def _build_config_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "config",
        help="Show the effective cobol.yml project config and where it came from",
        description=(
            "Report which cobol.yml/cobol.yaml is in effect for the current "
            "directory and every setting it supplies. Settings the file does "
            "not mention are omitted rather than shown at their built-in "
            "default, so what is printed is exactly what the file changes."
        ),
        epilog=(
            "Examples:\n"
            "  cobol-parser config\n"
            "  cobol-parser config --json\n"
            "  cobol-parser --config ./other/cobol.yml config"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    _add_compact_arg(p)
    _add_output_arg(p)
    p.set_defaults(func=_cmd_config)


def _build_mcp_parser(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "mcp",
        help="Serve COBOL analysis tools to AI agents over MCP (stdio)",
        description=(
            "Run a Model Context Protocol server on stdin/stdout, answering "
            "questions about the COBOL under --root: read_source, lint and "
            "explain_symbol. Every location in an answer is a file and line "
            "on disk, and every answer names what could not be checked. "
            "cobol.yml is read from --root itself (never from a parent "
            "directory). Under a copybook directory outside --root only "
            "copybook members are readable, and /, the home directory, their "
            "ancestors, hidden and system directories are refused as copybook "
            "directories. Needs the [mcp] extra."
        ),
        epilog=(
            "Examples:\n"
            "  cobol-parser mcp --root /path/to/checkout\n"
            "  claude mcp add cobol -- cobol-parser mcp --root /path/to/checkout"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--root",
        default=".",
        help="Directory the server answers about; files outside it (and its "
        "copybook directories) are refused (default: the current directory)",
    )
    p.add_argument(
        "--cache-size",
        type=int,
        default=32,
        metavar="N",
        help="Parsed programs to keep in memory (default: 32)",
    )
    p.add_argument(
        "--tools",
        default="auto",
        metavar="SPEC",
        help="Tools to offer: auto (default: core, plus the JCL tools when "
        "the root holds JCL), all, or a comma-separated list of groups "
        "(core, data, jcl) and tool names. Every tool's definition is sent "
        "to the model on every turn, so fewer tools cost fewer tokens",
    )
    p.add_argument(
        "--max-answer-bytes",
        type=int,
        default=None,
        metavar="N",
        help="Size budget of one tool result: longer lists are halved until "
        "it fits, each cut listed under truncated (default: 24000; 0: none)",
    )
    p.add_argument(
        "--workers",
        type=int,
        default=None,
        metavar="N",
        help="Processes that parse programs for the cross-program indexes "
        "(default: the CPUs, at most 8; 1: parse in the server process)",
    )
    p.add_argument(
        "--cache-dir",
        default=None,
        metavar="DIR",
        help="Where per-file facts are kept between server starts, so a "
        "restarted server parses only what changed (default: "
        "$XDG_CACHE_HOME/cobol-parser/mcp, else ~/.cache/cobol-parser/mcp)",
    )
    p.add_argument(
        "--no-disk-cache",
        action="store_true",
        help="Keep facts in memory only: every start parses the whole root",
    )
    p.add_argument(
        "--no-warm-up",
        action="store_true",
        help="Do not parse the root in the background at start; the first "
        "cross-program question does it instead",
    )
    p.set_defaults(func=_cmd_mcp)


def _cmd_mcp(args: argparse.Namespace) -> None:
    try:
        from ...mcp.server import run_stdio
    except ImportError as exc:
        _fail(
            "the MCP server needs the [mcp] extra: "
            f"pip install 'cobol-parser[mcp]' ({exc})"
        )
    from ...mcp.envelope import ToolError
    from ...mcp.server import select_tools
    from ...mcp.workspace import Workspace

    config = args._project_config if getattr(args, "_config_explicit", False) else None
    try:
        workspace = Workspace(args.root, config, cache_size=args.cache_size)
    except (ToolError, ConfigError) as exc:
        _fail(str(exc))
    for directory, reason in workspace.refused_copybook_dirs:
        # stderr: over stdio, stdout is the protocol channel.
        print(
            f"warning: copybook directory {directory} (from "
            f"{workspace.config.source}) is refused, so it is not searched or "
            f"readable: {reason}",
            file=sys.stderr,
        )
    try:
        select_tools(args.tools, workspace)
    except ValueError as exc:
        _fail(str(exc))
    from ...mcp.envelope import DEFAULT_ANSWER_BYTES

    budget = (
        DEFAULT_ANSWER_BYTES if args.max_answer_bytes is None else args.max_answer_bytes
    )
    if budget < 0:
        _fail("--max-answer-bytes must be 0 or more")
    from ...mcp.facts import FactsStore, default_cache_dir

    if args.workers is not None and args.workers < 1:
        _fail("--workers must be 1 or more")
    workspace.facts_store = FactsStore(
        workspace,
        workers=args.workers,
        cache_dir=(
            None if args.no_disk_cache else (args.cache_dir or default_cache_dir())
        ),
    )
    run_stdio(workspace, args.tools, budget or None, warm_up=not args.no_warm_up)


def _config_to_dict(config: ProjectConfig) -> dict[str, Any]:
    """The loaded config as JSON, with unset keys left out entirely."""

    def prune(mapping: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in mapping.items() if v not in (None, (), [], {})}

    return {
        "config_file": str(config.source) if config.source else None,
        "version": config.version,
        "project": prune(
            {
                "copybook_path": list(config.copybook_path),
                "callee_path": list(config.callee_path),
                "proc_path": list(config.proc_path),
                "source_format": config.source_format,
                "debug_lines": config.debug_lines,
                "dialect": config.dialect,
                "error_recovery": config.error_recovery,
                "seed": config.seed,
                "extensions": list(config.extensions),
                "define": list(config.define),
            }
        ),
        "data": prune(
            {
                "charset": config.data.charset,
                "endian": config.data.endian,
                "record_format": config.data.record_format,
                "record_separator": config.data.record_separator,
                "rows": config.data.rows,
            }
        ),
        "lint": prune(
            {
                "rules": list(config.lint.rules),
                "min_severity": config.lint.min_severity,
                "fail_on": config.lint.fail_on,
                "disable": list(config.lint.disable),
                "severity": dict(config.lint.severity),
                "exclude": list(config.lint.exclude),
                "baseline": config.lint.baseline,
                "scope": list(config.lint.scope),
            }
        ),
        "tools": dict(config.tools),
        # Present only when some path entry is not a directory (#550).
        **(
            {"missing_directories": [path for _, path in missing]}
            if (missing := config.missing_directories())
            else {}
        ),
    }


def _cmd_config(args: argparse.Namespace) -> None:
    config: ProjectConfig = getattr(args, "_project_config", None) or ProjectConfig()
    payload = _config_to_dict(config)

    if args.json:
        _json_out(payload, args.compact, args.output)
        return

    lines: list[str] = []
    if config.source is None:
        lines.append("No cobol.yml found (searched upward from the current directory).")
        lines.append("")
        lines.append("Create one to set copybook paths, source format, dialect and")
        lines.append("record encoding once for every tool that reads it.")
        _text_out("\n".join(lines), args.output)
        return

    lines.append(f"Config file: {config.source}")
    lines.append(f"Schema version: {config.version}")
    missing = set(payload.get("missing_directories", ()))
    for section in ("project", "data", "lint"):
        values = payload[section]
        if not values:
            continue
        lines.append("")
        lines.append(f"[{section}]")
        for key, value in values.items():
            if isinstance(value, list):
                lines.append(f"  {key}:")
                lines.extend(
                    f"    - {entry}"
                    + (
                        "  (not an existing directory)"
                        if key in ("copybook_path", "callee_path", "proc_path")
                        and entry in missing
                        else ""
                    )
                    for entry in value
                )
            elif isinstance(value, bool):
                # Spelled the way the file spells it, not Python's True.
                lines.append(f"  {key}: {'true' if value else 'false'}")
            elif isinstance(value, dict):
                lines.append(f"  {key}:")
                lines.extend(f"    {k}: {v}" for k, v in value.items())
            else:
                lines.append(f"  {key}: {value}")
    for name, section_data in payload["tools"].items():
        lines.append("")
        lines.append(f"[{name}]  (read by that tool, not by cobol-parser)")
        for key, value in section_data.items():
            lines.append(f"  {key}: {value}")
    _text_out("\n".join(lines), args.output)
