"""SARIF 2.1.0 output for the findings-shaped reports.

SARIF (Static Analysis Results Interchange Format, OASIS) is what GitHub
code scanning, Azure DevOps and most IDE problem panes read. Three reports
here are lists of located, graded findings and map onto it directly:

* ``lint`` -- one file's :class:`~.lint.LintReport` (:func:`lint_results`);
* ``scan --analyzer lint`` -- the same per file across a tree;
* ``call-check`` -- :class:`~.call_interface.CallInterfaceReport`
  (:func:`call_check_results`).

One run per log, one ``rules`` entry per rule id that produced a result.
A location is the file a finding is really in -- the copybook for a finding
inside an expanded member, through the ``origin`` the lint source map
stamps -- given relative to *base* (the working directory by default) with
``uriBaseId`` ``%SRCROOT%`` when it lies under it, which is what code
scanning resolves against the checkout; otherwise an absolute ``file:`` URI.
A finding with no line has no ``locations`` rather than a made-up one.
Caveats and rules that failed to run are ``toolExecutionNotifications``, so
a quiet log is never mistaken for a checked program.
"""

from __future__ import annotations

import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .bug_patterns import BUG_PATTERN_DESCRIPTIONS
from .code_patterns import CODE_PATTERN_DESCRIPTIONS
from .compiler_checks import COMPILER_RULE_DESCRIPTIONS

SARIF_VERSION = "2.1.0"
SARIF_SCHEMA = "https://json.schemastore.org/sarif-2.1.0.json"
INFORMATION_URI = "https://github.com/Landparty/cobol-parser"

#: Our severities to SARIF ``level``s.
_LEVELS = {"error": "error", "warning": "warning", "info": "note"}

#: One line per rule id, for ``rules[].shortDescription``.
RULE_DESCRIPTIONS: dict[str, str] = {
    "parse": "The source could not be parsed cleanly",
    "dead-code": "Paragraph or section that can never be reached",
    "unused-variables": "Data item never referenced in the PROCEDURE DIVISION",
    "move-type-check": "MOVE between incompatible or truncating categories",
    "io-sequence": "File operation out of sequence with its OPEN / CLOSE",
    "linkage-check": "CALL or ENTRY interface mismatch within one file",
    "recursion-check": "PERFORM / GO TO cycle or self-CALL that may not end",
    "complexity": "Procedure with high cyclomatic complexity",
    "dclgen-check": "SQL host variable that disagrees with its DCLGEN column",
    "sql-cics-check": "SQL or CICS response not checked, or used unsafely",
    "call-check/argument-count": "CALL passes a different number of arguments",
    "call-check/passing-mode": "CALL passes BY VALUE where BY REFERENCE is "
    "declared, or the reverse",
    "call-check/length": "CALL argument shorter or longer than the callee's "
    "parameter",
    "call-check/usage": "CALL argument of a different storage class than the "
    "callee's parameter",
    "call-check/returning": "CALL RETURNING disagrees with the callee",
    # lint's call-check rule (one id for every kind, unlike call-check's own
    # SARIF output above).
    "call-check": "CALL interface disagrees with the CALLed program",
    # The bug-pattern rules describe themselves.
    **BUG_PATTERN_DESCRIPTIONS,
    **COMPILER_RULE_DESCRIPTIONS,
    **CODE_PATTERN_DESCRIPTIONS,
}


@dataclass
class SarifResult:
    """One finding, in the terms SARIF needs."""

    rule: str
    severity: str
    message: str
    file: str | None = None
    line: int | None = None
    column: int | None = None
    #: Extra facts kept in ``properties`` (kind, symbol, callee, ...).
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class SarifNotification:
    """A note about the run itself (a caveat, a rule that did not run)."""

    message: str
    level: str = "note"
    file: str | None = None


def lint_results(report: dict[str, Any], source_file: str) -> list[SarifResult]:
    """The findings of one ``LintReport.to_dict()`` linted from
    *source_file*. A finding's ``origin`` (where an expanded line really
    is) wins over its ``location``, which counts expanded lines."""
    out: list[SarifResult] = []
    for finding in report.get("findings") or []:
        origin = finding.get("origin") or {}
        location = finding.get("location") or {}
        if origin.get("file") and origin.get("line"):
            file, line, column = origin["file"], origin["line"], origin.get("column")
        elif location.get("line"):
            file, line, column = source_file, location["line"], None
        else:
            file, line, column = source_file, None, None
        properties = {
            key: finding[key] for key in ("kind", "symbol") if finding.get(key)
        }
        out.append(
            SarifResult(
                rule=finding["rule"],
                severity=finding["severity"],
                message=finding["message"],
                file=file,
                line=line,
                column=column,
                properties=properties,
            )
        )
    return out


def lint_notifications(
    report: dict[str, Any], source_file: str
) -> list[SarifNotification]:
    """A lint report's caveats and failed rules, as run notifications."""
    out = [
        SarifNotification(message=str(caveat), file=source_file)
        for caveat in report.get("caveats") or []
    ]
    out += [
        SarifNotification(
            message=f"lint rule {failure.get('rule')} did not run: "
            f"{failure.get('error')}",
            level="error",
            file=source_file,
        )
        for failure in report.get("failed_rules") or []
    ]
    return out


def call_check_results(report: Any) -> list[SarifResult]:
    """Every :class:`~.call_interface.CallInterfaceFinding` of *report*."""
    out: list[SarifResult] = []
    for finding in report.findings:
        properties: dict[str, Any] = {
            "caller": finding.caller,
            "callee": finding.callee,
            "callee_path": finding.callee_path,
        }
        if finding.position is not None:
            properties["position"] = finding.position
        if finding.origin_file is not None:
            properties["program_file"] = finding.path
        out.append(
            SarifResult(
                rule=f"call-check/{finding.kind}",
                severity=finding.severity,
                message=finding.message,
                file=finding.file,
                line=finding.line or None,
                properties=properties,
            )
        )
    return out


def call_check_notifications(report: Any) -> list[SarifNotification]:
    """What ``call-check`` could not compare, and the files it could not
    parse."""
    out = [SarifNotification(message=str(note)) for note in report.unchecked]
    out += [
        SarifNotification(
            message=f"not parsed: {error.get('error')}",
            level="error",
            file=error.get("path"),
        )
        for error in report.errors
    ]
    return out


def _artifact(file: str, base: Path) -> dict[str, Any]:
    path = Path(file)
    absolute = path if path.is_absolute() else (Path.cwd() / path)
    absolute = Path(os.path.normpath(absolute))
    try:
        relative = absolute.relative_to(base)
    except ValueError:
        return {"uri": absolute.as_uri()}
    return {"uri": relative.as_posix(), "uriBaseId": "%SRCROOT%"}


def sarif_log(
    results: Iterable[SarifResult],
    notifications: Iterable[SarifNotification] = (),
    *,
    base: str | Path | None = None,
) -> dict[str, Any]:
    """A SARIF 2.1.0 log of one run holding *results*."""
    from .._version import __version__

    root = Path(os.path.normpath(Path(base).resolve() if base else Path.cwd()))
    results = list(results)
    rule_ids = list(dict.fromkeys(result.rule for result in results))
    index = {rule: i for i, rule in enumerate(rule_ids)}
    sarif_results: list[dict[str, Any]] = []
    for result in results:
        entry: dict[str, Any] = {
            "ruleId": result.rule,
            "ruleIndex": index[result.rule],
            "level": _LEVELS.get(result.severity, "note"),
            "message": {"text": result.message},
        }
        if result.file and result.line:
            region: dict[str, Any] = {"startLine": int(result.line)}
            if result.column:
                region["startColumn"] = int(result.column)
            entry["locations"] = [
                {
                    "physicalLocation": {
                        "artifactLocation": _artifact(result.file, root),
                        "region": region,
                    }
                }
            ]
        if result.properties:
            entry["properties"] = dict(result.properties)
        sarif_results.append(entry)

    notes: list[dict[str, Any]] = []
    for note in notifications:
        item: dict[str, Any] = {"level": note.level, "message": {"text": note.message}}
        if note.file:
            item["locations"] = [
                {"physicalLocation": {"artifactLocation": _artifact(note.file, root)}}
            ]
        notes.append(item)

    run: dict[str, Any] = {
        "tool": {
            "driver": {
                "name": "cobol-parser",
                "version": __version__,
                "informationUri": INFORMATION_URI,
                "rules": [
                    {
                        "id": rule,
                        "shortDescription": {"text": RULE_DESCRIPTIONS.get(rule, rule)},
                    }
                    for rule in rule_ids
                ],
            }
        },
        "originalUriBaseIds": {"%SRCROOT%": {"uri": root.as_uri() + "/"}},
        "invocations": [
            {
                "executionSuccessful": True,
                "toolExecutionNotifications": notes,
            }
        ],
        "results": sarif_results,
    }
    return {"$schema": SARIF_SCHEMA, "version": SARIF_VERSION, "runs": [run]}
