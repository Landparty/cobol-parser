"""Independent source census: what a COBOL program *should* put in its AST.

The corpus harness (``tools/corpus/run.py``) checks the parser against this
census. The census deliberately does not use the parser, the lexer or the
fixed-format normalizer: it reads the (copybook-expanded) source text with its
own small tokenizer, so a token the lexer drops, a statement a parser
swallows or a paragraph the boundary logic misses shows up as a difference
instead of being hidden by the same code on both sides. The one library
helper it borrows is ``detect_fixed_format`` (whether columns 1-7 are a
sequence/indicator area), because guessing that wrong would make every count
meaningless and the parser takes the same decision first.

What it counts, per compilation unit summed over the file:

* **Statements by verb** in the PROCEDURE DIVISION. A verb word is a
  statement start (COBOL verbs are reserved words, so they cannot be
  data-names); a few verbs that IBM Enterprise COBOL does *not* reserve
  (``WEAK_VERBS``) only count as the first word on a line, where real code
  writes them. ``EXEC ... END-EXEC`` counts as one ``EXEC`` statement,
  ``NEXT SENTENCE`` as one, ``XML``/``JSON GENERATE|PARSE`` as one.
* **Paragraph and section headers**: a non-verb word followed by ``.`` (or by
  ``SECTION``) at the start of a sentence, or -- in fixed format -- written in
  Area A on its own line, which catches a header after a statement that is
  missing its period.
* **Data description entries**: a level number (01-49, 66, 77, 78, 88) at the
  start of a sentence in the DATA DIVISION, outside the REPORT, SCREEN and
  COMMUNICATION sections (whose entries the AST models differently).

The census is a heuristic, not a COBOL parser. Where it cannot be sure it says
so in ``caveats`` (an unexpanded COPY, a REPLACE, pseudo-text) so the harness
can mark the comparison as unreliable instead of reporting a false bug.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from cobolparser._source_text.source_format import detect_fixed_format

# Reserved COBOL verbs: any occurrence outside a literal starts a statement.
STRONG_VERBS = frozenset("""
    ACCEPT ADD ALTER CALL CANCEL CLOSE COMPUTE CONTINUE DELETE DISPLAY DIVIDE
    ENTRY EVALUATE EXIT GENERATE GO GOBACK IF INITIALIZE INITIATE INSPECT
    INVOKE MERGE MOVE MULTIPLY OPEN PERFORM READ RELEASE RETURN REWRITE
    SEARCH SET SORT START STOP STRING SUBTRACT TERMINATE UNLOCK
    UNSTRING USE WRITE
    """.split())

# Verbs IBM Enterprise COBOL does not reserve (or only some dialects do):
# counted only as the first word of a line, so a data-name spelled the same
# way is not mistaken for a statement.
WEAK_VERBS = frozenset("""
    ALLOCATE CHAIN COMMIT DISABLE ENABLE ENTER EXAMINE EXHIBIT FREE NOTE
    PURGE RAISE READY RECEIVE RESET RESUME ROLLBACK SEND SERVICE TRANSFORM
    VALIDATE
    """.split())

# Listing-control words: the parser keeps them as statements too, but they
# are not program logic, so the comparison ignores them on both sides.
LISTING_WORDS = frozenset({"EJECT", "SKIP1", "SKIP2", "SKIP3", "TITLE"})

# SUPPRESS is also a phrase of XML/JSON GENERATE and PARSE; the Report Writer
# statement is only ever the whole sentence of a USE BEFORE REPORTING
# procedure, so it is counted at the start of a sentence only.
SENTENCE_START_VERBS = frozenset({"SUPPRESS"})

ALL_VERBS = STRONG_VERBS | WEAK_VERBS | SENTENCE_START_VERBS

SCOPE_TERMINATORS = frozenset("""
    END-ACCEPT END-ADD END-CALL END-CHAIN END-COMPUTE END-DELETE END-DISPLAY
    END-DIVIDE END-EVALUATE END-EXEC END-IF END-INVOKE END-JSON END-MULTIPLY
    END-PERFORM END-READ END-RECEIVE END-RETURN END-REWRITE END-SEARCH
    END-SEND END-START END-STRING END-SUBTRACT END-UNSTRING END-WRITE END-XML
    """.split())

# Words that may start a sentence followed by a period without being a
# procedure name.
_NOT_PROCEDURE_NAMES = (
    ALL_VERBS
    | LISTING_WORDS
    | {
        "DECLARATIVES",
        "END",
        "ELSE",
        "THEN",
        "WHEN",
        "OTHER",
        "SENTENCE",
        "NEXT",
        "COPY",
        "REPLACE",
        "EXEC",
        "EXECUTE",
    }
)

# 78 is the Micro Focus / GnuCOBOL constant entry.
_LEVELS = frozenset(range(1, 50)) | {66, 77, 78, 88}
_SKIPPED_DATA_SECTIONS = frozenset({"REPORT", "SCREEN", "COMMUNICATION"})

_WORD_RE = re.compile(r"[A-Za-z0-9$#@_][A-Za-z0-9$#@_\-]*")


@dataclass
class Token:
    text: str  # upper-cased word, "." or a literal placeholder
    line: int  # 1-based line in the expanded source
    col: int  # 0-based column within the code area
    line_first: bool  # first token on its line

    @property
    def is_word(self) -> bool:
        return self.text not in (".", "'LIT'")


@dataclass
class Census:
    """What the source says the AST should contain."""

    fixed_format: bool = True
    verbs: Counter[str] = field(default_factory=Counter)
    paragraphs: list[tuple[str, int]] = field(default_factory=list)
    sections: list[tuple[str, int]] = field(default_factory=list)
    data_entries: int = 0
    data_entries_by_level: Counter[int] = field(default_factory=Counter)
    units: int = 0
    caveats: list[str] = field(default_factory=list)


def _code_lines(source: str, fixed: bool) -> list[tuple[int, str]]:
    """(line number, code text) with comments and sequence areas removed."""
    out: list[tuple[int, str]] = []
    # Plain "\n" split on purpose: the expanded text the parser sees uses
    # "\n" line ends, and form feeds inside a line are just whitespace here.
    for number, raw in enumerate(source.replace("\r\n", "\n").split("\n"), 1):
        line = raw.replace("\t", "    ")
        if fixed:
            if len(line) < 7:
                continue
            indicator = line[6]
            if indicator in "*/":
                continue
            if indicator in "dD":
                continue  # debugging line, compiled only WITH DEBUGGING MODE
            code = line[7:72]
            if indicator == "-":
                # Continuation: glue to the previous line (literal
                # continuations begin with a quote that reopens the literal).
                cont = code.lstrip()
                if out and cont[:1] in ("'", '"'):
                    prev_no, prev = out[-1]
                    out[-1] = (
                        prev_no,
                        _drop_open_literal(prev) + " 'LIT' " + _after_reopen(cont),
                    )
                    continue
                if out:
                    prev_no, prev = out[-1]
                    out[-1] = (prev_no, prev.rstrip() + cont)
                    continue
        else:
            code = line
        stripped = code.strip()
        if not stripped:
            continue
        if stripped.startswith(("*>", ">>", "$")):
            continue  # free-form comment, compiler directive, MF $SET
        if not fixed and code[:1] in ("*", "/"):
            continue  # Micro Focus free format: "*" or "/" in column 1
        out.append((number, code))
    return out


def _drop_open_literal(text: str) -> str:
    """Cut a line at an unterminated literal (it continues on the next line)."""
    quote: str | None = None
    start = 0
    for i, ch in enumerate(text):
        if quote is None and ch in ("'", '"'):
            quote, start = ch, i
        elif quote is not None and ch == quote:
            quote = None
    return text[:start] if quote is not None else text


def _after_reopen(cont: str) -> str:
    """The text after the continued literal closes on a continuation line."""
    quote = cont[0]
    i = 1
    while i < len(cont):
        if cont[i] == quote:
            if i + 1 < len(cont) and cont[i + 1] == quote:
                i += 2
                continue
            return cont[i + 1 :]
        i += 1
    return ""


def tokenize(source: str) -> tuple[list[Token], bool]:
    """Tokens of *source* (words upper-cased, literals collapsed, periods kept)."""
    fixed = detect_fixed_format(source)
    tokens: list[Token] = []
    in_pseudo = False  # inside ==pseudo-text== that spans lines
    for number, code in _code_lines(source, fixed):
        i = 0
        first = True
        n = len(code)
        if in_pseudo:
            j = code.find("==")
            if j < 0:
                continue
            in_pseudo = False
            i = j + 2
        while i < n:
            ch = code[i]
            if ch in " \t,;\f":
                i += 1
                continue
            if code.startswith("*>", i):
                break
            if ch in ("'", '"'):
                j = i + 1
                while j < n:
                    if code[j] == ch:
                        if j + 1 < n and code[j + 1] == ch:
                            j += 2
                            continue
                        break
                    j += 1
                tokens.append(Token("'LIT'", number, i, first))
                first = False
                i = j + 1
                continue
            if code.startswith("==", i):
                j = code.find("==", i + 2)
                tokens.append(Token("'LIT'", number, i, first))
                first = False
                if j < 0:
                    in_pseudo = True
                    break
                i = j + 2
                continue
            if ch == ".":
                # A separator period is followed by a space or the line end;
                # anything else is a decimal point or a PICTURE character.
                if i + 1 < n and not code[i + 1].isspace():
                    i += 1
                    continue
                tokens.append(Token(".", number, i, first))
                first = False
                i += 1
                continue
            m = _WORD_RE.match(code, i)
            if m:
                word = m.group(0).upper()
                # X'..' / N'..' / Z'..' / G'..' literal prefixes
                end = m.end()
                if (
                    end < n
                    and code[end] in ("'", '"')
                    and word in {"X", "N", "Z", "G", "NX", "B", "BX", "U", "FX", "FL"}
                ):
                    i = end
                    continue
                # A word ending in "." followed by space: the period is a separator.
                tokens.append(Token(word, number, i, first))
                first = False
                i = end
                continue
            # Operators and parentheses carry no structure the census needs.
            i += 1
    return tokens, fixed


def census(source: str) -> Census:
    """Count statements, procedure headers and data entries in *source*."""
    tokens, fixed = tokenize(source)
    result = Census(fixed_format=fixed)
    division: str | None = None
    data_section: str | None = None
    sentence_start = True
    i = 0
    n = len(tokens)

    def nxt(k: int = 1) -> str:
        return tokens[i + k].text if i + k < n else ""

    while i < n:
        tok = tokens[i]
        word = tok.text

        # Division headers (any division, any unit).
        if nxt() == "DIVISION" and word in {
            "IDENTIFICATION",
            "ID",
            "ENVIRONMENT",
            "DATA",
            "PROCEDURE",
        }:
            if word in ("IDENTIFICATION", "ID"):
                result.units += 1
            division = "IDENTIFICATION" if word == "ID" else word
            data_section = None
            # Skip the header up to its period (PROCEDURE DIVISION USING ...).
            while i < n and tokens[i].text != ".":
                i += 1
            i += 1
            sentence_start = True
            continue
        if word == "END" and nxt() in {
            "PROGRAM",
            "CLASS",
            "METHOD",
            "FACTORY",
            "OBJECT",
            "FUNCTION",
        }:
            division = None
            while i < n and tokens[i].text != ".":
                i += 1
            i += 1
            sentence_start = True
            continue

        if word == ".":
            sentence_start = True
            i += 1
            continue

        if word in ("COPY",) and division is not None:
            result.caveats.append(f"unexpanded COPY at line {tok.line}")
        if word == "REPLACE" and (sentence_start or tok.line_first):
            result.caveats.append(f"REPLACE at line {tok.line}")

        if division == "DATA":
            if nxt() == "SECTION" and tok.is_word:
                data_section = word.split("-")[0]
                i += 2
                continue
            if word == "EXEC":
                i = _skip_exec(tokens, i)
                continue
            if (
                sentence_start
                and word.isdigit()
                and data_section not in _SKIPPED_DATA_SECTIONS
            ):
                level = int(word)
                if level in _LEVELS:
                    result.data_entries += 1
                    result.data_entries_by_level[level] += 1
            sentence_start = False
            i += 1
            continue

        if division != "PROCEDURE":
            sentence_start = False if word != "." else True
            i += 1
            continue

        # ---- PROCEDURE DIVISION ----
        if word == "EXEC" or word == "EXECUTE":
            result.verbs["EXEC"] += 1
            i = _skip_exec(tokens, i)
            sentence_start = False
            continue
        if word == "NOTE" and tok.line_first:
            result.verbs["NOTE"] += 1
            while i < n and tokens[i].text != ".":
                i += 1
            continue

        header_position = sentence_start or (fixed and tok.line_first and tok.col < 4)
        if (
            header_position
            and tok.is_word
            and word not in _NOT_PROCEDURE_NAMES
            and word not in SCOPE_TERMINATORS  # "END-IF." ends a sentence
        ):
            if nxt() == ".":
                result.paragraphs.append((word, tok.line))
                i += 2
                sentence_start = True
                continue
            if nxt() == "SECTION":
                result.sections.append((word, tok.line))
                while i < n and tokens[i].text != ".":
                    i += 1
                i += 1
                sentence_start = True
                continue
        if word in ("DECLARATIVES",) and nxt() == ".":
            i += 2
            sentence_start = True
            continue
        if word == "END" and nxt() == "DECLARATIVES":
            i += 3
            sentence_start = True
            continue

        if word == "NEXT" and nxt() == "SENTENCE":
            result.verbs["NEXT SENTENCE"] += 1
            i += 2
            sentence_start = False
            continue
        if word in ("XML", "JSON") and nxt() in ("GENERATE", "PARSE"):
            result.verbs[word] += 1
            i += 2
            sentence_start = False
            continue
        prev = tokens[i - 1].text if i > 0 else ""
        if word == "ENTRY" and prev == "TO":
            pass  # SET procedure-pointer TO ENTRY 'name'
        elif word == "PERFORM" and prev == "EXIT":
            pass  # EXIT PERFORM [CYCLE]
        elif word == "EXIT" and prev == "UNTIL":
            pass  # PERFORM UNTIL EXIT (an endless loop, not an EXIT statement)
        elif word in SENTENCE_START_VERBS:
            if sentence_start:
                result.verbs[word] += 1
        elif word in STRONG_VERBS:
            result.verbs[word] += 1
        elif word in WEAK_VERBS and tok.line_first:
            result.verbs[word] += 1
        sentence_start = False
        i += 1
    return result


def _skip_exec(tokens: list[Token], i: int) -> int:
    """Index just past the END-EXEC closing the EXEC block at *i*."""
    n = len(tokens)
    while i < n and tokens[i].text != "END-EXEC":
        i += 1
    return i + 1
