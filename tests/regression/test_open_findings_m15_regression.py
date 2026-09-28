"""Regression tests for open finding M15 (audit reports/open-findings.md).

M15: ``detect_encoding`` was a raw 0x40-vs-0x20 byte-count heuristic with a
5% threshold — an ASCII file with many '@' (0x40) characters was misdetected
as EBCDIC.  ``convert_to_utf8`` always decoded with ``errors="replace"``,
silently substituting undecodable bytes with U+FFFD.

The fix scores ASCII-vs-EBCDIC COBOL plausibility (charset proportion,
newline conventions, keyword hits) instead of the single byte-count ratio,
and adds a configurable ``encoding_errors`` policy ("replace" | "strict")
threaded from ``expand_copybooks`` down to the decoder.
"""

import pytest

from cobolparser.preprocess import EncodingError
from cobolparser.preprocess.copybook_expander import (
    clear_file_cache,
    convert_to_utf8,
    detect_encoding,
    expand_copybooks,
    read_file_with_encoding,
)

EBCDIC_SNIPPET = (
    "       01  EMPLOYEE-RECORD.\n"
    "           05  EMP-ID      PIC 9(6).\n"
    "           05  EMP-NAME    PIC X(30).\n"
)


@pytest.fixture(autouse=True)
def _fresh_file_cache():
    """Isolate each test from the module-level copybook content cache."""
    clear_file_cache()
    yield
    clear_file_cache()


class TestM15EncodingDetection:
    """Encoding detection robustness and decode-strictness regressions."""

    def test_real_ebcdic_copybook_detected_and_round_tripped(self, tmp_path):
        """A genuine cp037-encoded copybook is detected and decodes losslessly."""
        cpy = tmp_path / "EMPREC.cpy"
        cpy.write_bytes(EBCDIC_SNIPPET.encode("cp037"))

        assert detect_encoding(str(cpy)) == "cp037"

        warnings: list[str] = []
        content = read_file_with_encoding(str(cpy), warnings=warnings)
        assert content == EBCDIC_SNIPPET
        assert warnings == []  # lossless decode -> no lossy-decode warning

    def test_ebcdic_copybook_expands_via_public_api(self, tmp_path):
        """expand_copybooks() inlines an EBCDIC copybook transparently."""
        cpy = tmp_path / "EMPREC.cpy"
        cpy.write_bytes(EBCDIC_SNIPPET.encode("cp037"))

        result = expand_copybooks("       COPY EMPREC.\n", [str(tmp_path)])
        assert "EMPLOYEE-RECORD" in result.expanded_source
        assert "EMP-NAME" in result.expanded_source

    def test_ascii_with_many_at_signs_not_misdetected_as_ebcdic(self, tmp_path):
        """'@'-heavy ASCII must not be classified as EBCDIC (defeats old heuristic).

        The old detector compared count(0x40) vs count(0x20) with a 5%
        threshold after a failed strict-UTF-8 decode; this content (200 '@'
        bytes, one invalid 0xFF byte) satisfied that ratio and was returned
        as cp037 even though it is plainly ASCII COBOL text.
        """
        content = (
            b"      01  MASK-FIELD  PIC X(64).\n"
            b"      88  ALL-AT-SIGNS  VALUE '" + b"@" * 200 + b"'.\n"
            b"\xff\n"
        )
        # Precondition: this really does defeat the old 0x40/0x20 heuristic.
        assert content.count(b"\x40") > content.count(b"\x20")
        assert content.count(b"\x40") > len(content) * 0.05

        cpy = tmp_path / "ATSIGNS.cpy"
        cpy.write_bytes(content)
        # ASCII-shaped, not valid UTF-8 (the lone 0xFF): an 8-bit ASCII
        # superset, never EBCDIC. It was labelled "ascii" before 2026-09-28,
        # which turned every byte >= 0x80 into U+FFFD.
        assert detect_encoding(str(cpy)) == "cp1252"

    def test_pure_valid_utf8_with_many_at_signs_stays_utf8(self, tmp_path):
        """Fully valid ASCII/UTF-8 text with '@' runs is never demoted to EBCDIC."""
        cpy = tmp_path / "ATVALID.cpy"
        cpy.write_bytes(b"      01  FILLER  PIC X(80)  VALUE '" + b"@" * 120 + b"'.\n")
        assert detect_encoding(str(cpy)) in ("utf-8", "ascii")

    def test_utf8_with_accents_detected(self, tmp_path):
        """UTF-8 multi-byte characters are decisive for UTF-8 detection."""
        text = "       01  CLIENT-NOM  PIC X(30).  *> Québec café\n"
        cpy = tmp_path / "ACCENT.cpy"
        cpy.write_bytes(text.encode("utf-8"))

        assert detect_encoding(str(cpy)) == "utf-8"
        assert read_file_with_encoding(str(cpy)) == text

    def test_utf8_bom_still_decisive(self, tmp_path):
        cpy = tmp_path / "BOM.cpy"
        cpy.write_bytes(b"\xef\xbb\xbf       01  X  PIC 9.\n")
        assert detect_encoding(str(cpy)) == "utf-8-sig"

    def test_strict_mode_raises_with_file_and_offset_context(self, tmp_path):
        """encoding_errors='strict' raises EncodingError naming file + offset."""
        cpy = tmp_path / "GARBAGE.cpy"
        cpy.write_bytes(b"01 GOOD.\n\xff\xfe junk")

        with pytest.raises(EncodingError) as exc_info:
            read_file_with_encoding(
                str(cpy), encoding_override="ascii", encoding_errors="strict"
            )
        message = str(exc_info.value)
        assert "GARBAGE.cpy" in message
        assert "offset 9" in message
        assert "0xff" in message

    def test_strict_mode_threaded_through_expand_copybooks(self, tmp_path):
        """The public expand_copybooks API surfaces strict decode failures."""
        cpy = tmp_path / "BADENC.cpy"
        cpy.write_bytes(b"01 BAD-FIELD PIC X.\n\xff")

        with pytest.raises(EncodingError):
            expand_copybooks(
                "       COPY BADENC.\n",
                [str(tmp_path)],
                encoding="ascii",
                encoding_errors="strict",
            )

    def test_replace_mode_warns_with_replacement_count(self, tmp_path):
        """Default replace mode still decodes, but reports how many bytes lost."""
        cpy = tmp_path / "LOSSY.cpy"
        cpy.write_bytes(b"01 A-FIELD PIC X.\n\xff\xfe")

        warnings: list[str] = []
        content = read_file_with_encoding(
            str(cpy), encoding_override="ascii", warnings=warnings
        )
        assert content.count("�") == 2
        assert len(warnings) == 1
        assert "Lossy decode" in warnings[0]
        assert "2 byte(s)" in warnings[0]
        assert "LOSSY.cpy" in warnings[0]

    def test_replace_mode_warning_reaches_expansion_statistics(self, tmp_path):
        cpy = tmp_path / "LOSSY2.cpy"
        cpy.write_bytes(b"01 B-FIELD PIC X.\n\xff")

        result = expand_copybooks(
            "       COPY LOSSY2.\n", [str(tmp_path)], encoding="ascii"
        )
        lossy = [w for w in result.statistics.warnings if "Lossy decode" in w]
        assert len(lossy) == 1
        assert "1 byte(s)" in lossy[0]

    def test_invalid_errors_policy_rejected(self):
        with pytest.raises(ValueError):
            convert_to_utf8(b"01 X.", "ascii", errors="ignore")

    def test_strict_clean_decode_returns_content(self):
        assert (
            convert_to_utf8(b"01 CLEAN PIC X.", "ascii", errors="strict")
            == "01 CLEAN PIC X."
        )
