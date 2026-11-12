#!/usr/bin/env python3
"""OKF content checker -- the bundle's claims, tested against the code.

``okf_staleness_check.py`` can only ask *whether* an OKF file was touched when
its source changed; appending a dated paragraph satisfies it, and that is how
the topic files drifted while the hook stayed green.  This script checks what
the files *say*:

* **imports** -- every ``from cobolparser... import A, B`` written anywhere in
  a topic file (code block or prose) must run;
* **dotted names** -- every backticked ``cobolparser.module.Name[.attr]`` must
  resolve;
* **paths** -- every backticked repo path (``cobolparser/...``, ``tests/...``,
  ``scripts/...``, ``docs/...``) must exist;
* **links** -- every relative markdown link must point at an existing file,
  and every ``#anchor`` at a real heading;
* **generated spans** -- text between ``<!-- okf:gen NAME -->`` and
  ``<!-- /okf:gen -->`` must equal what generator ``NAME`` produces from the
  code right now (counts, enum members, the CLI subcommand table, ...).
  ``--write`` regenerates them in place;
* **bare counts** -- a number stated next to a counted noun this script can
  generate (``244 TokenType values``, ``33 analysis modules``) must sit inside
  a generated span, so the next change to the code cannot leave it stale.

Archives (``.okf/history/`` and ``.okf/log.md``) record what *was* true, so
they are checked for links only.

Usage::

    python scripts/okf_check.py            # check, exit 1 on any problem
    python scripts/okf_check.py --write    # regenerate generated spans first
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import inspect
import re
import sys
from collections.abc import Callable, Iterable
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OKF_DIR = REPO_ROOT / ".okf"
# Files outside .okf/ that carry the same claims and are checked the same way.
EXTRA_FILES = [
    REPO_ROOT / "CLAUDE.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "interface-contract.md",
    REPO_ROOT / "docs" / "README.md",
    REPO_ROOT / "docs" / "mcp-server.md",
    REPO_ROOT / "docs" / "project-config.md",
    REPO_ROOT / "docs" / "fixture-bundle-schema.md",
    REPO_ROOT / "docs" / "enterprise-program-types.md",
    REPO_ROOT / "docs" / "public-api.md",
]

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


# --------------------------------------------------------------------------
# Generators: NAME -> callable returning the exact text of the span
# --------------------------------------------------------------------------


def _public_modules(package_dir: Path) -> list[str]:
    return sorted(
        p.stem
        for p in package_dir.glob("*.py")
        if not p.stem.startswith("_") and p.stem != "__init__"
    )


def _private_helpers(package_dir: Path) -> list[str]:
    return sorted(p.stem for p in package_dir.glob("_*.py") if p.stem != "__init__")


def _cli_subparsers() -> dict[str, argparse.ArgumentParser]:
    from cobolparser.cli.parse import _build_parser

    parser = _build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return dict(action.choices)
    raise RuntimeError("cobol-parser has no subcommands")


def _cli_help(name: str) -> str:
    from cobolparser.cli.parse import _build_parser

    parser = _build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for choice in action._choices_actions:
                if choice.dest == name:
                    return (choice.help or "").strip()
    return ""


def _gen_cli_subcommand_table() -> str:
    rows = [
        "| Subcommand | What it does | Positionals | Options |",
        "|---|---|---|---|",
    ]
    for name, sub in _cli_subparsers().items():
        positionals = []
        options = []
        for action in sub._actions:
            if isinstance(action, argparse._HelpAction):
                continue
            if action.option_strings:
                longest = max(action.option_strings, key=len)
                options.append(f"`{longest}`")
            else:
                label = action.metavar or action.dest
                if action.nargs in ("*", "+"):
                    label = f"{label}..."
                if action.nargs == "?":
                    label = f"[{label}]"
                positionals.append(f"`{label}`")
        rows.append(
            f"| `{name}` | {_cli_help(name).replace('|', '/')} | "
            f"{' '.join(positionals) or '--'} | {' '.join(options) or '--'} |"
        )
    return "\n" + "\n".join(rows) + "\n"


def _gen_tokentype_count() -> str:
    from cobolparser.lexer import TokenType

    return str(len(TokenType))


def _gen_analysis_module_count() -> str:
    return str(len(_public_modules(REPO_ROOT / "cobolparser" / "analysis")))


def _gen_analysis_private_helpers() -> str:
    helpers = _private_helpers(REPO_ROOT / "cobolparser" / "analysis")
    return ", ".join(f"`{h}.py`" for h in helpers)


def _gen_analysis_private_helper_count() -> str:
    return str(len(_private_helpers(REPO_ROOT / "cobolparser" / "analysis")))


def _gen_program_flow_modules() -> str:
    mods = _public_modules(REPO_ROOT / "cobolparser" / "analysis" / "program_flow")
    return ", ".join(f"`{m}.py`" for m in mods)


def _gen_cli_subcommand_count() -> str:
    return str(len(_cli_subparsers()))


def _gen_lint_rules() -> str:
    from cobolparser.analysis.lint import RULES

    return ", ".join(f"`{r}`" for r in RULES)


def _gen_lint_rule_count() -> str:
    from cobolparser.analysis.lint import RULES

    return str(len(RULES))


def _gen_scan_analyzers() -> str:
    from cobolparser.scan import ANALYZERS

    return ", ".join(f"`{a}`" for a in ANALYZERS)


def _gen_flow_edge_types() -> str:
    from cobolparser.analysis.program_flow import FlowEdgeType

    return ", ".join(f"`{m.name}`" for m in FlowEdgeType)


def _gen_statement_parser_file_count() -> str:
    return str(
        len(_public_modules(REPO_ROOT / "cobolparser" / "parsers" / "statements"))
    )


def _gen_registered_statement_parser_count() -> str:
    from cobolparser.parsers.divisions.procedure_registry import (
        create_statement_registry,
    )

    return str(len(create_statement_registry().get_all_parsers()))


def _gen_unsupported_verbs() -> str:
    from cobolparser.parsers.divisions.procedure_recovery import UNSUPPORTED_VERBS

    return ", ".join(f"`{v}`" for v in sorted(UNSUPPORTED_VERBS))


def _gen_generators_export_count() -> str:
    import cobolparser.generators as gen

    return str(len(gen.__all__))


def _gen_bundle_version() -> str:
    from cobolparser.generators.data.bundle import BUNDLE_VERSION

    return str(BUNDLE_VERSION)


def _gen_mcp_caveat_kinds() -> str:
    from cobolparser.mcp.envelope import CAVEAT_KINDS

    return ", ".join(f"`{k}`" for k in CAVEAT_KINDS)


GENERATORS: dict[str, Callable[[], str]] = {
    "cli-subcommand-table": _gen_cli_subcommand_table,
    "cli-subcommand-count": _gen_cli_subcommand_count,
    "tokentype-count": _gen_tokentype_count,
    "analysis-module-count": _gen_analysis_module_count,
    "analysis-private-helpers": _gen_analysis_private_helpers,
    "analysis-private-helper-count": _gen_analysis_private_helper_count,
    "program-flow-modules": _gen_program_flow_modules,
    "lint-rules": _gen_lint_rules,
    "lint-rule-count": _gen_lint_rule_count,
    "scan-analyzers": _gen_scan_analyzers,
    "flow-edge-types": _gen_flow_edge_types,
    "statement-parser-file-count": _gen_statement_parser_file_count,
    "registered-statement-parser-count": _gen_registered_statement_parser_count,
    "unsupported-verbs": _gen_unsupported_verbs,
    "generators-export-count": _gen_generators_export_count,
    "bundle-version": _gen_bundle_version,
    "mcp-caveat-kinds": _gen_mcp_caveat_kinds,
}

GEN_RE = re.compile(
    r"<!-- okf:gen (?P<name>[\w-]+) -->(?P<body>.*?)<!-- /okf:gen -->", re.S
)

# A number next to one of these nouns is a count the code can answer, so it
# must come from a generator.  Patterns are deliberately narrow: they match the
# phrasings the bundle actually uses, not every number in the prose.
BARE_COUNT_PATTERNS = [
    (re.compile(r"\b\d+ `?TokenType`? (?:values|types|members)"), "tokentype-count"),
    (
        re.compile(r"\b\d+ (?:public |static[- ])?analy(?:sis|zer) modules"),
        "analysis-module-count",
    ),
    (re.compile(r"\b\d+ (?:CLI )?subcommands"), "cli-subcommand-count"),
    (re.compile(r"\b\d+ (?:lint )?rules\b"), "lint-rule-count"),
    (
        re.compile(r"\b\d+ statement[- ]parser files"),
        "statement-parser-file-count",
    ),
    (re.compile(r"\b\d+ registered\b"), "registered-statement-parser-count"),
]


# --------------------------------------------------------------------------
# Checks
# --------------------------------------------------------------------------


@dataclasses.dataclass
class Problem:
    path: Path
    line: int
    kind: str
    message: str

    def __str__(self) -> str:
        rel = self.path.relative_to(REPO_ROOT)
        return f"{rel}:{self.line}: [{self.kind}] {self.message}"


def _line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _is_archive(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    return rel.startswith(".okf/history/") or rel == ".okf/log.md"


def okf_files() -> list[Path]:
    return sorted(OKF_DIR.rglob("*.md")) + [p for p in EXTRA_FILES if p.exists()]


def check_generated(path: Path, text: str) -> list[Problem]:
    problems = []
    for m in GEN_RE.finditer(text):
        name = m.group("name")
        gen = GENERATORS.get(name)
        if gen is None:
            problems.append(
                Problem(
                    path,
                    _line_of(text, m.start()),
                    "gen",
                    f"unknown generator {name!r}",
                )
            )
            continue
        expected = gen()
        if m.group("body") != expected:
            got = m.group("body").strip()
            shown = got if len(got) < 80 else got[:77] + "..."
            problems.append(
                Problem(
                    path,
                    _line_of(text, m.start()),
                    "gen",
                    f"{name} is stale (has {shown!r}); run scripts/okf_check.py --write",
                )
            )
    return problems


def write_generated(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        gen = GENERATORS.get(m.group("name"))
        if gen is None:
            return m.group(0)
        return f"<!-- okf:gen {m.group('name')} -->{gen()}<!-- /okf:gen -->"

    return GEN_RE.sub(repl, text)


def check_bare_counts(path: Path, text: str) -> list[Problem]:
    masked = GEN_RE.sub(lambda m: " " * len(m.group(0)), text)
    problems = []
    for pattern, gen_name in BARE_COUNT_PATTERNS:
        for m in pattern.finditer(masked):
            problems.append(
                Problem(
                    path,
                    _line_of(text, m.start()),
                    "count",
                    f"hard-coded count {m.group(0)!r}: wrap the number in "
                    f"<!-- okf:gen {gen_name} -->N<!-- /okf:gen -->",
                )
            )
    return problems


IMPORT_RE = re.compile(
    r"from\s+(cobolparser[\w.]*)\s+import\s+(\([^)]*\)|[\w, ]+(?:\\\n[\w, ]+)*)"
)


def _import_names(clause: str) -> list[str]:
    clause = clause.strip().strip("()")
    clause = re.sub(r"#[^\n]*", "", clause)
    names = []
    for part in clause.replace("\\\n", " ").split(","):
        part = part.strip()
        if not part:
            continue
        names.append(part.split()[0])
    return names


def check_imports(path: Path, text: str) -> list[Problem]:
    problems = []
    for m in IMPORT_RE.finditer(text):
        module_name = m.group(1).rstrip(".")
        line = _line_of(text, m.start())
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:  # noqa: BLE001 -- report any import failure
            problems.append(
                Problem(path, line, "import", f"cannot import {module_name}: {exc}")
            )
            continue
        for name in _import_names(m.group(2)):
            if name == "*" or not name.isidentifier():
                continue
            if hasattr(module, name):
                continue
            try:
                importlib.import_module(f"{module_name}.{name}")
            except Exception:  # noqa: BLE001
                problems.append(
                    Problem(path, line, "import", f"{module_name} has no name {name!r}")
                )
    return problems


DOTTED_RE = re.compile(r"`(cobolparser(?:\.[A-Za-z_]\w*)+)`")


def _has_attribute(obj: object, name: str) -> bool:
    if hasattr(obj, name):
        return True
    if inspect.isclass(obj):
        if dataclasses.is_dataclass(obj) and name in {
            f.name for f in dataclasses.fields(obj)
        }:
            return True
        if name in getattr(obj, "__annotations__", {}):
            return True
        try:
            source = inspect.getsource(obj)
        except (OSError, TypeError):
            return False
        return f"self.{name}" in source
    return False


def resolve_dotted(dotted: str) -> str | None:
    """Return None when ``dotted`` resolves, else the reason it does not."""
    parts = dotted.split(".")
    module = None
    index = 0
    for i in range(len(parts), 0, -1):
        try:
            module = importlib.import_module(".".join(parts[:i]))
        except ModuleNotFoundError:
            continue
        except Exception as exc:  # noqa: BLE001
            return f"importing {'.'.join(parts[:i])} raised {exc!r}"
        index = i
        break
    if module is None:
        return "no importable module prefix"
    obj: object = module
    for name in parts[index:]:
        if not _has_attribute(obj, name):
            return f"{'.'.join(parts[:index])} has no attribute path {'.'.join(parts[index:])!r}"
        try:
            obj = getattr(obj, name)
        except AttributeError:
            # A dataclass field or an attribute set in __init__: it exists, but
            # there is nothing further to walk into.
            break
    return None


def check_dotted_names(path: Path, text: str) -> list[Problem]:
    problems = []
    for m in DOTTED_RE.finditer(text):
        reason = resolve_dotted(m.group(1))
        if reason:
            problems.append(
                Problem(
                    path, _line_of(text, m.start()), "name", f"`{m.group(1)}`: {reason}"
                )
            )
    return problems


PATH_RE = re.compile(
    r"`((?:cobolparser|tests|scripts|docs|tools|examples|benchmarks)/[\w./-]*)`"
)


def check_paths(path: Path, text: str) -> list[Problem]:
    problems = []
    for m in PATH_RE.finditer(text):
        rel = m.group(1).rstrip("/.")
        # Globs, templates and the documented placeholder name (foo_parser.py)
        # are not claims about the tree.
        if any(ch in rel for ch in "*<>{}") or not rel or "foo" in rel:
            continue
        if not (REPO_ROOT / rel).exists():
            problems.append(
                Problem(
                    path,
                    _line_of(text, m.start()),
                    "path",
                    f"`{m.group(1)}` does not exist",
                )
            )
    return problems


LINK_RE = re.compile(r"\[[^\]\n]*\]\(([^)\s]+)\)")
FENCE_RE = re.compile(r"^(```|~~~).*?^\1", re.S | re.M)


def _slug(heading: str) -> str:
    heading = heading.strip().lower()
    heading = re.sub(r"[^\w\- ]", "", heading)
    return heading.replace(" ", "-")


def _anchors(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path not in cache:
        text = FENCE_RE.sub("", path.read_text(encoding="utf-8"))
        seen: dict[str, int] = {}
        anchors = set()
        for line in text.splitlines():
            if not line.startswith("#"):
                continue
            slug = _slug(line.lstrip("#"))
            n = seen.get(slug, 0)
            anchors.add(slug if n == 0 else f"{slug}-{n}")
            seen[slug] = n + 1
        cache[path] = anchors
    return cache[path]


def check_links(
    path: Path, text: str, cache: dict[Path, set[str]] | None = None
) -> list[Problem]:
    cache = {} if cache is None else cache
    problems = []
    scan = FENCE_RE.sub(lambda m: "\n" * m.group(0).count("\n"), text)
    for m in LINK_RE.finditer(scan):
        target = m.group(1)
        if re.match(r"^[a-z]+:", target):
            continue
        file_part, _, anchor = target.partition("#")
        line = _line_of(scan, m.start())
        dest = (path.parent / file_part).resolve() if file_part else path
        if file_part and not dest.is_relative_to(REPO_ROOT):
            continue  # a sibling repo (backend/, mocky-mock/): not ours to check
        if file_part and not dest.exists():
            problems.append(Problem(path, line, "link", f"{target}: no such file"))
            continue
        if anchor and dest.suffix == ".md" and anchor not in _anchors(dest, cache):
            problems.append(Problem(path, line, "link", f"{target}: no such heading"))
    return problems


_SYMBOLS: set[str] | None = None


def defined_symbols() -> set[str]:
    """Every name ``cobolparser`` defines: classes, functions, methods,
    assignments, attributes set on ``self``, dataclass fields, enum members."""
    global _SYMBOLS
    if _SYMBOLS is None:
        import ast
        import builtins
        import dataclasses as _dc
        import enum
        import json
        import os
        import pathlib
        import subprocess

        names: set[str] = set()
        # The stdlib names the bundle cites when explaining *why* (``str.splitlines()``
        # is the classic) are claims about Python, not about this package.
        for module in (
            builtins,
            str,
            bytes,
            list,
            dict,
            set,
            os,
            os.path,
            json,
            re,
            sys,
            pathlib.Path,
            subprocess,
            argparse,
            _dc,
            enum,
            inspect,
            importlib,
        ):
            names.update(dir(module))
        # Names from outside Python itself: the Claude Code hook event the
        # staleness checker is wired to.
        names.update({"PostToolUse"})
        names.update({"Path", "PurePath", "ProcessPoolExecutor", "ThreadPoolExecutor"})
        sources = [
            *(REPO_ROOT / "cobolparser").rglob("*.py"),
            *(REPO_ROOT / "tests").rglob("*.py"),
            *(REPO_ROOT / "scripts").rglob("*.py"),
            *(REPO_ROOT / "tools").rglob("*.py"),
        ]
        for source in sources:
            try:
                tree = ast.parse(source.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, FileNotFoundError):
                continue
            for node in ast.walk(tree):
                if isinstance(
                    node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
                ):
                    names.add(node.name)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute) and isinstance(
                    node.ctx, ast.Store
                ):
                    names.add(node.attr)
                elif isinstance(node, ast.AnnAssign) and isinstance(
                    node.target, ast.Name
                ):
                    names.add(node.target.id)
                elif isinstance(node, ast.alias):
                    names.add(node.asname or node.name.split(".")[-1])
        _SYMBOLS = names
    return _SYMBOLS


# `CamelCase` (two humps at least, so COBOL words and acronyms are left alone),
# `Class.member`, and `function()` / `obj.method()` spans name code.
CAMEL_RE = re.compile(r"`([A-Z][a-z]+(?:[A-Z][a-z0-9]+)+)`")
MEMBER_RE = re.compile(
    r"`([A-Z][A-Za-z0-9]*[a-z][A-Za-z0-9]*)\.([A-Za-z_]\w*)(?:\(\))?`"
)
# `CHANGELOG.md`, `Foo.cbl`: a file name, not a member access.
FILE_SUFFIXES = {
    "md",
    "py",
    "pyx",
    "c",
    "cbl",
    "cob",
    "cpy",
    "jcl",
    "json",
    "yml",
    "yaml",
    "txt",
    "csv",
    "toml",
    "cfg",
    "ini",
    "html",
    "prof",
    "so",
}
CALL_RE = re.compile(r"`(?:[A-Za-z_]\w*\.)*([a-z_]\w*)\(\)`")


EXTERNAL_RE = re.compile(r"<!-- okf:external ([^>]*?) -->")


def check_symbols(path: Path, text: str) -> list[Problem]:
    # A file that documents another codebase's names (the backend adapter, a
    # sibling repo) declares them: <!-- okf:external CobolLegacyParser ... -->
    external = {n for m in EXTERNAL_RE.finditer(text) for n in m.group(1).split()}
    symbols = defined_symbols() | external
    problems = []
    scan = GEN_RE.sub(lambda m: " " * len(m.group(0)), text)
    for regex in (CAMEL_RE, MEMBER_RE, CALL_RE):
        for m in regex.finditer(scan):
            if regex is MEMBER_RE and m.group(2).lower() in FILE_SUFFIXES:
                continue
            missing = [g for g in m.groups() if g not in symbols]
            if missing:
                problems.append(
                    Problem(
                        path,
                        _line_of(text, m.start()),
                        "symbol",
                        f"{m.group(0)}: cobolparser defines no {', '.join(missing)}",
                    )
                )
    return problems


# Flags every (or nearly every) parsing subcommand shares; cli.md describes
# them once in the table's legend rather than in every row.
SHARED_CLI_FLAGS = {
    "--help",
    "--compact",
    "--source-format",
    "--free-form",
    "--debug-lines",
    "--no-debug-lines",
    "--dialect",
    "--error-recovery",
    "--copybook-path",
    "--program",
    "--define",
    "--abend-program",
    "--encoding",
    "--output",
    "--profile",
    "--profile-top-n",
    "--profile-output",
    "--strict-copybooks",
}
CLI_TABLE_HEADING = "## Subcommand reference"


def check_cli_table(path: Path, text: str) -> list[Problem]:
    """The hand-written subcommand table in cli.md, verified against argparse:
    one row per subcommand, every flag it names exists on that subcommand, and
    every flag of the subcommand beyond the shared set is named in its row."""
    if CLI_TABLE_HEADING not in text:
        return []
    start = text.index(CLI_TABLE_HEADING)
    end = text.find("\n## ", start + len(CLI_TABLE_HEADING))
    section = text[start : end if end != -1 else len(text)]
    base_line = _line_of(text, start)
    rows: dict[str, tuple[int, str]] = {}
    for offset, line in enumerate(section.splitlines()):
        m = re.match(r"\|\s*`([\w-]+)`\s*\|", line)
        if m:
            rows[m.group(1)] = (base_line + offset, line)
    subparsers = _cli_subparsers()
    problems = []
    for name in sorted(set(subparsers) - set(rows)):
        problems.append(
            Problem(path, base_line, "cli", f"no table row for subcommand `{name}`")
        )
    for name in sorted(set(rows) - set(subparsers)):
        problems.append(
            Problem(path, rows[name][0], "cli", f"`{name}` is not a subcommand")
        )
    for name, (line_no, line) in rows.items():
        sub = subparsers.get(name)
        if sub is None:
            continue
        real = {o for a in sub._actions for o in a.option_strings if o.startswith("--")}
        # "A without `--program`" / "no `--compact`" name a flag by its absence.
        absent = set()
        for m in re.finditer(
            r"(?:without|no)\s+((?:`--[\w-]+`[/, ]*(?:or |and )?)+)", line
        ):
            absent.update(re.findall(r"--[\w-]+", m.group(1)))
        named = set(re.findall(r"(?<![\w-])--[a-z][\w-]*", line)) - absent
        for flag in sorted(named - real):
            problems.append(
                Problem(path, line_no, "cli", f"`{name}` has no flag {flag}")
            )
        own = {
            max(a.option_strings, key=len)
            for a in sub._actions
            if a.option_strings and not set(a.option_strings) & SHARED_CLI_FLAGS
        }
        for flag in sorted(own - named):
            problems.append(Problem(path, line_no, "cli", f"`{name}` row omits {flag}"))
    return problems


CONTENT_CHECKS: list[Callable[[Path, str], list[Problem]]] = [
    check_generated,
    check_bare_counts,
    check_imports,
    check_dotted_names,
    check_paths,
    check_symbols,
    check_cli_table,
]


def check_file(path: Path, cache: dict[Path, set[str]] | None = None) -> list[Problem]:
    text = path.read_text(encoding="utf-8")
    problems = check_links(path, text, cache)
    if not _is_archive(path):
        for check in CONTENT_CHECKS:
            problems.extend(check(path, text))
    return problems


def check_all(paths: Iterable[Path] | None = None) -> list[Problem]:
    cache: dict[Path, set[str]] = {}
    problems: list[Problem] = []
    for path in paths if paths is not None else okf_files():
        problems.extend(check_file(path, cache))
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--write", action="store_true", help="regenerate okf:gen spans before checking"
    )
    parser.add_argument("files", nargs="*", type=Path, help="default: the whole bundle")
    args = parser.parse_args(argv)
    paths = [p.resolve() for p in args.files] or okf_files()
    if args.write:
        for path in paths:
            text = path.read_text(encoding="utf-8")
            new = write_generated(text)
            if new != text:
                path.write_text(new, encoding="utf-8")
                print(f"regenerated {path.relative_to(REPO_ROOT)}")
    problems = check_all(paths)
    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} OKF problem(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
