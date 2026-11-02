"""Definitions that sit beside the COBOL: CICS CSD and BMS maps, DB2 DDL, IMS DBD and PSB.

None of these are COBOL, but an application cannot be understood without
them: the CSD ties a transaction id to its program and a CICS file to its
dataset, BMS maps are the screens, DDL gives a table its columns and keys,
and DBD / PSB give an IMS database its segments and a program its access.

    from cobolparser.definitions import detect_definition_kind, parse_definitions

    kind = detect_definition_kind(text)        # "CSD" | "BMS" | "DDL" | "DBD" | "PSB" | None
    report = parse_definitions(text, kind)     # the matching *Definitions object
    report.to_dict()

Every parser is fault tolerant: what it cannot read goes to ``warnings`` (with
a line number) and statements it does not model are counted, never guessed.
"""

from __future__ import annotations

import re
from typing import Literal

from .bms import BmsDefinitions, BmsField, BmsMap, BmsMapset, parse_bms
from .csd import CsdDefinitions, CsdResource, _resource_type, parse_csd
from .ddl import SYSTEM_DEFAULT, DdlColumn, DdlDefinitions, DdlTable, parse_ddl
from .ims import (
    DbdDefinitions,
    ImsDatabase,
    ImsSegment,
    PsbDefinitions,
    parse_dbd,
    parse_psb,
)

DefinitionKind = Literal["CSD", "BMS", "DDL", "DBD", "PSB"]
Definitions = (
    CsdDefinitions | BmsDefinitions | DdlDefinitions | DbdDefinitions | PsbDefinitions
)

#: Every kind, in the order ``detect_definition_kind`` tries them.
DEFINITION_KINDS: tuple[DefinitionKind, ...] = ("BMS", "PSB", "DBD", "CSD", "DDL")

_BMS = re.compile(r"^\S*[ \t]+DFHMSD[ \t]", re.MULTILINE)
_PSB = re.compile(r"^\S*[ \t]+PSBGEN\b", re.MULTILINE)
_DBD = re.compile(r"^\S*[ \t]+DBD[ \t]+NAME=", re.MULTILINE)
_SEGM = re.compile(r"^\S*[ \t]+SEGM[ \t]", re.MULTILINE)
#: DFHCSDUP ``DEFINE type(`` (upper case, as DFHCSDUP members are written); the
#: type must be a CSD resource type, so IDCAMS ``DEFINE GDG(`` and Python
#: ``def f(`` are not CSD.
_CSD_DEFINE = re.compile(r"^[ \t]*DEF(?:INE)?[ \t]+([A-Z0-9]+)\(", re.MULTILINE)
_CSD_MACRO = re.compile(r"^\S*[ \t]+DFH(?:PCT|PPT|FCT)[ \t]+TYPE=", re.MULTILINE)
#: A JCL statement (``//name JOB|EXEC|DD|PROC``): a job, even one whose in-stream
#: data holds DEFINE or CREATE statements, is not a definition member.
_JCL = re.compile(r"^//\S*[ \t]+(?:JOB|EXEC|DD|PROC)\b", re.MULTILINE)
_DDL = re.compile(
    r"^[ \t]*CREATE[ \t]+(?:UNIQUE[ \t]+|GLOBAL[ \t]+TEMPORARY[ \t]+|AUXILIARY[ \t]+)?"
    r"(?:TABLE|INDEX|VIEW|ALIAS|SYNONYM|TABLESPACE)\b",
    re.MULTILINE | re.IGNORECASE,
)
_COBOL = re.compile(
    r"\b(?:IDENTIFICATION|ID)\s+DIVISION\b|\bEXEC\s+SQL\b", re.IGNORECASE
)


def detect_definition_kind(source: str) -> DefinitionKind | None:
    """Which definition *source* holds, from its content; None when it is none of them.

    A COBOL program (an IDENTIFICATION DIVISION or EXEC SQL) is never DDL,
    even when it embeds ``CREATE TABLE``, and a JCL job (records starting
    ``//``) is none of them, even when its in-stream data runs IDCAMS
    ``DEFINE``, DFHCSDUP or DSNTEP2 ``CREATE``.
    """
    sample = source[:200_000]
    if _JCL.search(sample):
        return None
    if _BMS.search(sample):
        return "BMS"
    if _PSB.search(sample):
        return "PSB"
    if _DBD.search(sample) and _SEGM.search(sample):
        return "DBD"
    if _CSD_MACRO.search(sample) or any(
        _resource_type(m.group(1)) for m in _CSD_DEFINE.finditer(sample)
    ):
        return "CSD"
    if _DDL.search(sample) and not _COBOL.search(sample):
        return "DDL"
    return None


def parse_definitions(
    source: str, kind: DefinitionKind | None = None
) -> Definitions | None:
    """Parse *source* as *kind* (detected when omitted); None when no kind applies."""
    resolved = kind or detect_definition_kind(source)
    if resolved == "BMS":
        return parse_bms(source)
    if resolved == "PSB":
        return parse_psb(source)
    if resolved == "DBD":
        return parse_dbd(source)
    if resolved == "CSD":
        return parse_csd(source)
    if resolved == "DDL":
        return parse_ddl(source)
    return None


__all__ = [
    "DEFINITION_KINDS",
    "SYSTEM_DEFAULT",
    "BmsDefinitions",
    "BmsField",
    "BmsMap",
    "BmsMapset",
    "CsdDefinitions",
    "CsdResource",
    "DbdDefinitions",
    "DdlColumn",
    "DdlDefinitions",
    "DdlTable",
    "DefinitionKind",
    "Definitions",
    "ImsDatabase",
    "ImsSegment",
    "PsbDefinitions",
    "detect_definition_kind",
    "parse_bms",
    "parse_csd",
    "parse_dbd",
    "parse_ddl",
    "parse_definitions",
    "parse_psb",
]
