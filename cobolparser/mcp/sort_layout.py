"""DFSORT / SYNCSORT control statements laid over a record layout.

``SORT FIELDS=(263,16,CH,A)`` and ``OUTREC FIELDS=(1:263,16,17:1,262)``
name bytes, not fields. Given the input record's byte map (from the
COBOL program that reads the dataset), each sort key, INCLUDE / OMIT
test and reformatted output segment is said in field names, and the
input bytes the output leaves out are listed. Pure text work: the
caller finds the layout.

Exact by construction, or absent: a statement this cannot read (a
parsed edit mask, a variable-length ``p`` with no length, IFTHEN) is
named in ``not_mapped`` rather than guessed at.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

#: One elementary field: name, 0-based offset, length in bytes.
Field = tuple[str, int, int]


@dataclass(frozen=True)
class Segment:
    """``out_pos`` (1-based) .. + ``length``: input bytes from ``in_pos``,
    or a literal (``in_pos`` None) such as ``C'X'`` or ``5X``."""

    out_pos: int
    length: int
    in_pos: int | None
    literal: str | None = None


@dataclass
class SortControl:
    sort_keys: list[tuple[int, int, str, str]]
    sort_verb: str | None
    #: ``(verb, p, m, op, value)``: *value* is the constant as coded, or
    #: ``(p2, m2)`` when the test compares with other bytes of the record.
    tests: list[tuple[str, int, int, str, str | tuple[int, int]]]
    inrec: list[Segment] | None
    outrec: list[Segment] | None
    not_mapped: list[str]
    #: True when an OUTFIL statement reformats an output (BUILD=, OUTREC=,
    #: OVERLAY=, IFTHEN=, ...): the output layout is not the one mapped.
    outfil_reformat: bool = False


_STATEMENT = re.compile(
    r"\b(SORT|MERGE|INCLUDE|OMIT|INREC|OUTREC)\s+"
    r"(FIELDS|COND|BUILD|OVERLAY|FINDREP|IFTHEN)\s*=\s*",
)
_FORMAT = re.compile(r"\bFORMAT\s*=\s*([A-Z]{2})")
_OPERATORS = frozenset({"EQ", "NE", "GT", "GE", "LT", "LE"})
_CONNECTORS = frozenset({"AND", "OR", "&", "|"})
_OUTFIL = re.compile(r"\bOUTFIL\b")
_OUTFIL_PARAM = re.compile(r"\s*([A-Z][A-Z0-9]*)\s*=\s*")
#: OUTFIL parameters that select records or reformat them.
_OUTFIL_FILTERS = frozenset({"INCLUDE", "OMIT", "SAVE"})
_OUTFIL_REFORMATS = frozenset(
    {
        "OUTREC",
        "BUILD",
        "OVERLAY",
        "IFTHEN",
        "IFOUTLEN",
        "FINDREP",
        "PARSE",
        "VTOF",
        "FTOV",
        "CONVERT",
        "HEADER1",
        "HEADER2",
        "HEADER3",
        "TRAILER1",
        "TRAILER2",
        "TRAILER3",
        "SECTIONS",
        "REMOVECC",
        "NODETAIL",
    }
)


def _balanced(text: str, start: int) -> str | None:
    """The text inside the parenthesis at *start*, quotes respected."""
    if start >= len(text) or text[start] != "(":
        return None
    depth = 0
    quoted = False
    for i in range(start, len(text)):
        char = text[i]
        if char == "'":
            quoted = not quoted
        elif quoted:
            continue
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start + 1 : i]
    return None


def _split(text: str) -> list[str]:
    """Top-level comma-separated items, quotes and parentheses respected."""
    items: list[str] = []
    depth = 0
    quoted = False
    current = ""
    for char in text:
        if char == "'":
            quoted = not quoted
        elif not quoted and char == "(":
            depth += 1
        elif not quoted and char == ")":
            depth -= 1
        if char == "," and not quoted and depth == 0:
            items.append(current.strip())
            current = ""
            continue
        current += char
    if current.strip():
        items.append(current.strip())
    return items


def _flat(text: str) -> list[str]:
    """Comma-separated items with every parenthesised group opened up:
    ``(1,2,CH,EQ,C'A'),AND,(3,1,CH,EQ,C'B')`` reads as one flat list."""
    out: list[str] = []
    for item in _split(text):
        inner = _balanced(item, 0) if item.startswith("(") else None
        if inner is not None and len(inner) == len(item) - 2:
            out.extend(_flat(inner))
        else:
            out.append(item)
    return out


def _tests(
    verb: str, body: str, not_mapped: list[str]
) -> list[tuple[str, int, int, str, str | tuple[int, int]]]:
    """The ``p,m[,f],op,value`` comparisons of an INCLUDE / OMIT COND=.

    *value* is a constant (quotes respected: ``C'N,'``) or another field,
    ``p2,m2[,f2]``. A condition this does not read goes to *not_mapped*
    whole, rather than a part of it being reported.
    """
    tokens = _flat(body)
    tests: list[tuple[str, int, int, str, str | tuple[int, int]]] = []
    i = 0
    while i < len(tokens):
        if not (
            i + 2 < len(tokens) and tokens[i].isdigit() and tokens[i + 1].isdigit()
        ):
            not_mapped.append(f"{verb} COND=({body})")
            return []
        start, length = int(tokens[i]), int(tokens[i + 1])
        i += 2
        if re.fullmatch(r"[A-Z]{2}", tokens[i]) and tokens[i] not in _OPERATORS:
            i += 1
        if i >= len(tokens) or tokens[i] not in _OPERATORS or i + 1 >= len(tokens):
            not_mapped.append(f"{verb} COND=({body})")
            return []
        op = tokens[i]
        i += 1
        value: str | tuple[int, int]
        if tokens[i].isdigit() and i + 1 < len(tokens) and tokens[i + 1].isdigit():
            value = (int(tokens[i]), int(tokens[i + 1]))
            i += 2
            if (
                i < len(tokens)
                and re.fullmatch(r"[A-Z]{2}", tokens[i])
                and tokens[i] not in _CONNECTORS
            ):
                i += 1
        else:
            value = tokens[i]
            i += 1
        tests.append((verb, start, length, op, value))
        if i < len(tokens):
            if tokens[i] not in _CONNECTORS:
                not_mapped.append(f"{verb} COND=({body})")
                return []
            i += 1
    return tests


def _outfil(text: str, control: SortControl) -> None:
    """OUTFIL statements: their record selection and reformatting are not
    mapped (each FNAMES= output may have its own); name them."""
    for found in _OUTFIL.finditer(text):
        pos = found.end()
        params: list[tuple[str, str]] = []
        while True:
            param = _OUTFIL_PARAM.match(text, pos)
            if param is None:
                break
            pos = param.end()
            if pos < len(text) and text[pos] == "(":
                inner = _balanced(text, pos)
                if inner is None:
                    break
                value = f"({inner})"
            else:
                value = re.match(r"[^,\s]*", text[pos:]).group(0)  # type: ignore[union-attr]
            pos += len(value)
            params.append((param.group(1), value))
            if pos < len(text) and text[pos] == ",":
                pos += 1
                continue
            break
        names = next((v for k, v in params if k in ("FNAMES", "FILES")), None)
        label = f"OUTFIL FNAMES={names}" if names else "OUTFIL"
        for key, value in params:
            if key in _OUTFIL_FILTERS or key in _OUTFIL_REFORMATS:
                control.not_mapped.append(f"{label}: {key}={value}")
            if key in _OUTFIL_REFORMATS:
                control.outfil_reformat = True


def _join(lines: list[str]) -> str:
    """The cards as one text: a statement continues on the next card after
    a trailing comma; sequence numbers and comments are already gone."""
    out = []
    for line in lines:
        card = line.strip()
        if card.startswith("*"):
            continue
        out.append(card)
    return " ".join(out).upper()


_LITERAL = re.compile(r"^(\d*)(C'(?:[^']|'')*'|X'[0-9A-F]*'|X|Z)$")


def _literal_length(token: str) -> int | None:
    found = _LITERAL.match(token)
    if found is None:
        return None
    count = int(found.group(1) or 1)
    body = found.group(2)
    if body.startswith("C'"):
        return count * len(body[2:-1].replace("''", "'"))
    if body.startswith("X'"):
        return count * (len(body) - 3) // 2
    return count


def _segments(text: str, where: str, not_mapped: list[str]) -> list[Segment] | None:
    """``c:p,l`` / ``p,l`` / literal items of a FIELDS= or BUILD= list."""
    tokens = _split(text)
    out_pos = 1
    segments: list[Segment] = []
    i = 0
    while i < len(tokens):
        token = tokens[i]
        column = re.match(r"^(\d+):(.*)$", token)
        if column:
            out_pos = int(column.group(1))
            token = column.group(2).strip()
            if not token:
                i += 1
                continue
        if token.isdigit():
            if i + 1 < len(tokens) and tokens[i + 1].isdigit():
                length = int(tokens[i + 1])
                segments.append(Segment(out_pos, length, int(token)))
                out_pos += length
                i += 2
                # A format or edit after p,l (``ZD``, ``EDIT=(...)``,
                # ``TO=PD``) changes the bytes written: not mapped.
                if i < len(tokens) and re.match(r"^[A-Z]{2}\b|^[A-Z]+=", tokens[i]):
                    not_mapped.append(f"{where}: {token},{length},{tokens[i]}")
                    return None
                continue
            not_mapped.append(f"{where}: {token} with no length")
            return None
        length_of = _literal_length(token)
        if length_of is not None:
            segments.append(Segment(out_pos, length_of, None, token))
            out_pos += length_of
            i += 1
            continue
        not_mapped.append(f"{where}: {token}")
        return None
    return segments


def parse_sort_control(lines: list[str]) -> SortControl:
    """The SORT / MERGE keys, INCLUDE / OMIT tests and INREC / OUTREC
    layouts of one SYSIN."""
    text = _join(lines)
    control = SortControl([], None, [], None, None, [])
    for found in _STATEMENT.finditer(text):
        verb, operand = found.group(1), found.group(2)
        body = _balanced(text, found.end())
        if body is None:
            if verb in ("SORT", "MERGE") and text[found.end() :].startswith("COPY"):
                control.sort_verb = f"{verb} FIELDS=COPY"
            continue
        if verb in ("SORT", "MERGE"):
            control.sort_verb = verb
            fmt = _FORMAT.search(text[found.end() + len(body) + 2 :][:40])
            items = _split(body)
            width = 3 if fmt else 4
            for at in range(0, len(items) - width + 1, width):
                group = items[at : at + width]
                if not (group[0].isdigit() and group[1].isdigit()):
                    control.not_mapped.append(f"{verb}: {','.join(group)}")
                    break
                kind = fmt.group(1) if fmt else group[2]
                control.sort_keys.append(
                    (int(group[0]), int(group[1]), kind, group[-1])
                )
        elif verb in ("INCLUDE", "OMIT"):
            control.tests.extend(_tests(verb, body, control.not_mapped))
        elif operand in ("FIELDS", "BUILD"):
            segments = _segments(body, f"{verb} {operand}", control.not_mapped)
            if verb == "INREC":
                control.inrec = segments
            else:
                control.outrec = segments
        else:
            control.not_mapped.append(f"{verb} {operand}=")
    _outfil(text, control)
    return control


def _span(start: int, length: int) -> str:
    return f"{start}-{start + length - 1}" if length > 1 else str(start)


def fields_at(fields: list[Field], start: int, length: int) -> str:
    """The fields bytes *start* (1-based) .. +*length* cover, in words."""
    begin, end = start - 1, start - 1 + length
    hit = [f for f in fields if f[1] < end and f[1] + f[2] > begin]
    if not hit:
        return "no field (past the end of the record)"
    words: list[str] = []
    run: list[str] = []

    def flush() -> None:
        # A long run of whole fields reads as a range, not a list.
        if len(run) > 3:
            words.append(f"{run[0]} through {run[-1]} ({len(run)} fields)")
        else:
            words.extend(run)
        run.clear()

    for name, offset, size in hit:
        lo, hi = max(begin, offset), min(end, offset + size)
        if lo == offset and hi == offset + size:
            run.append(name)
            continue
        flush()
        words.append(
            f"part of {name} (its bytes {lo - offset + 1}-{hi - offset} of {size})"
        )
    flush()
    return ", ".join(words)


def _through(
    segments: list[Segment], start: int, length: int
) -> list[tuple[int, int]] | None:
    """The input byte ranges output bytes *start*..+*length* come from;
    None when any of them is a literal or not written."""
    out: list[tuple[int, int]] = []
    pos, end = start, start + length
    while pos < end:
        seg = next(
            (s for s in segments if s.out_pos <= pos < s.out_pos + s.length), None
        )
        if seg is None or seg.in_pos is None:
            return None
        take = min(end, seg.out_pos + seg.length) - pos
        out.append((seg.in_pos + pos - seg.out_pos, take))
        pos += take
    return out


def _gaps(segments: list[Segment], record_length: int) -> list[tuple[int, int]]:
    """Input bytes 1..*record_length* no segment copies."""
    copied = sorted(
        (s.in_pos, s.in_pos + s.length) for s in segments if s.in_pos is not None
    )
    gaps = []
    pos = 1
    for lo, hi in copied:
        if lo > pos:
            gaps.append((pos, lo - pos))
        pos = max(pos, hi)
    if pos <= record_length:
        gaps.append((pos, record_length - pos + 1))
    return gaps


def map_sort(
    control: SortControl, fields: list[Field], record_length: int
) -> dict[str, Any]:
    """*control* in field names of the input layout *fields*."""
    answer: dict[str, Any] = {}
    inrec = control.inrec

    def at_input(start: int, length: int) -> str:
        """A key or test position, read through INREC when there is one."""
        if inrec is None:
            return fields_at(fields, start, length)
        ranges = _through(inrec, start, length)
        if ranges is None:
            return "bytes INREC writes from a literal"
        return "; ".join(
            f"input {_span(lo, n)}: {fields_at(fields, lo, n)}" for lo, n in ranges
        )

    if control.sort_keys:
        answer["sort_keys"] = [
            {
                "positions": _span(start, length),
                "fields": at_input(start, length),
                "format": kind,
                "order": {"A": "ascending", "D": "descending"}.get(order, order),
            }
            for start, length, kind, order in control.sort_keys
        ]
        if inrec is not None:
            answer["sort_keys_note"] = (
                "positions are in the INREC output, mapped back to the input"
            )
    elif control.sort_verb:
        answer["sort"] = control.sort_verb
    if control.tests:
        answer["record_tests"] = [
            {
                "statement": verb,
                "positions": _span(start, length),
                # INCLUDE / OMIT run before INREC: input positions.
                "fields": fields_at(fields, start, length),
                "test": (
                    f"{op} {value}"
                    if isinstance(value, str)
                    else f"{op} bytes {_span(*value)} " f"({fields_at(fields, *value)})"
                ),
            }
            for verb, start, length, op, value in control.tests
        ]
    for name, segments in (("inrec", control.inrec), ("outrec", control.outrec)):
        if segments is None:
            continue
        rows = []
        for seg in segments:
            row: dict[str, Any] = {"positions": _span(seg.out_pos, seg.length)}
            if seg.in_pos is None:
                row["literal"] = seg.literal
            elif name == "outrec" and inrec is not None:
                row["from"] = _span(seg.in_pos, seg.length) + " of the INREC output"
                ranges = _through(inrec, seg.in_pos, seg.length)
                if ranges is not None:
                    row["fields"] = "; ".join(
                        f"input {_span(lo, n)}: {fields_at(fields, lo, n)}"
                        for lo, n in ranges
                    )
            else:
                row["from"] = _span(seg.in_pos, seg.length)
                row["fields"] = fields_at(fields, seg.in_pos, seg.length)
            rows.append(row)
        answer[f"{name}_layout"] = rows
        last = max((s.out_pos + s.length - 1 for s in segments), default=0)
        answer[f"{name}_length"] = last
    # The first reformat reads the input record: what it leaves out is lost.
    copied_from = control.inrec if control.inrec is not None else control.outrec
    if copied_from is not None:
        answer["input_not_copied"] = [
            {"positions": _span(lo, n), "fields": fields_at(fields, lo, n)}
            for lo, n in _gaps(copied_from, record_length)
        ]
    if control.not_mapped:
        answer["not_mapped"] = control.not_mapped
    return answer


def read_back(
    control: SortControl, fields: list[Field], read_as: list[Field]
) -> list[dict[str, Any]] | None:
    """Each field of the layout the output is read through (*read_as*),
    with the input fields its bytes come from; None without a reformat.

    When OUTFIL reformats the output, each field says it is not mapped."""
    if control.outfil_reformat:
        return [
            {
                "field": name,
                "positions": _span(offset + 1, length),
                "gets": "not mapped: an OUTFIL statement reformats the output",
            }
            for name, offset, length in read_as
        ]
    segments = control.outrec if control.outrec is not None else control.inrec
    if segments is None:
        return None
    written = max((s.out_pos + s.length - 1 for s in segments), default=0)
    rows = []
    for name, offset, length in read_as:
        words = []
        pos, end = offset + 1, offset + 1 + length
        while pos < end:
            seg = next(
                (s for s in segments if s.out_pos <= pos < s.out_pos + s.length),
                None,
            )
            if seg is None:
                stop = min([end] + [s.out_pos for s in segments if s.out_pos > pos])
                where = "past the output's end" if pos > written else "not written"
                words.append(f"bytes {_span(pos, stop - pos)} {where}")
                pos = stop
                continue
            take = min(end, seg.out_pos + seg.length) - pos
            if seg.in_pos is None:
                words.append(f"the literal {seg.literal}")
            else:
                lo = seg.in_pos + pos - seg.out_pos
                words.append(fields_at(fields, lo, take))
            pos += take
        rows.append(
            {
                "field": name,
                "positions": _span(offset + 1, length),
                "gets": "; ".join(words),
            }
        )
    return rows
