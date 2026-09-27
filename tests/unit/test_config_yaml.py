"""Tests for `cobolparser.config._yaml`, the stdlib-only YAML subset reader.

Covers:
- The shapes a config file actually uses: nested block mappings, block
  sequences (of scalars and of mappings), flow sequences and mappings,
  quoted and plain scalars, comments, an optional leading `---`
- Scalar resolution, including the two deliberate departures from YAML 1.1:
  `yes`/`no`/`on`/`off` stay strings, and a duplicate key is an error
- Every unsupported construct is REJECTED with the line number, never
  guessed at or silently dropped -- a config the user believes is in effect
  and isn't is the failure mode this reader exists to prevent
"""

from __future__ import annotations

import pytest

from cobolparser.config._yaml import YamlError, parse_yaml


def test_empty_and_comment_only_documents_are_none():
    assert parse_yaml("") is None
    assert parse_yaml("# just a comment\n\n   \n") is None


def test_flat_mapping_with_scalar_types():
    doc = parse_yaml(
        "name: PAYROLL\n"
        "rows: 25\n"
        "ratio: 1.5\n"
        "strict: true\n"
        "loose: false\n"
        "missing: null\n"
        "tilde: ~\n"
        "blank:\n"
    )
    assert doc == {
        "name": "PAYROLL",
        "rows": 25,
        "ratio": 1.5,
        "strict": True,
        "loose": False,
        "missing": None,
        "tilde": None,
        "blank": None,
    }


def test_nested_mappings_by_indentation():
    doc = parse_yaml(
        "project:\n"
        "  source_format: fixed\n"
        "  nested:\n"
        "    deeper: 1\n"
        "data:\n"
        "  charset: ebcdic\n"
    )
    assert doc == {
        "project": {"source_format": "fixed", "nested": {"deeper": 1}},
        "data": {"charset": "ebcdic"},
    }


def test_block_sequence_of_scalars():
    doc = parse_yaml("copybook_path:\n  - copybooks\n  - shared/copybooks\n")
    assert doc == {"copybook_path": ["copybooks", "shared/copybooks"]}


def test_block_sequence_of_mappings():
    doc = parse_yaml(
        "libraries:\n"
        "  - name: CUSTOMER\n"
        "    type: local\n"
        "  - name: ORDERS\n"
        "    type: local\n"
    )
    assert doc == {
        "libraries": [
            {"name": "CUSTOMER", "type": "local"},
            {"name": "ORDERS", "type": "local"},
        ]
    }


def test_flow_sequence_and_flow_mapping():
    doc = parse_yaml("paths: [a, b, c]\ndefine: {DEBUG: TRUE, LEVEL: 2}\n")
    assert doc == {"paths": ["a", "b", "c"], "define": {"DEBUG": True, "LEVEL": 2}}


def test_nested_flow_collections():
    assert parse_yaml("x: [[1, 2], {a: 3}]\n") == {"x": [[1, 2], {"a": 3}]}


def test_empty_flow_collections():
    assert parse_yaml("a: []\nb: {}\n") == {"a": [], "b": {}}


def test_quoted_strings_keep_their_content():
    doc = parse_yaml(
        "single: 'it''s fine'\n"
        'double: "a: colon # and hash"\n'
        'escapes: "tab\\there"\n'
        'unicode: "\\u0041"\n'
    )
    assert doc["single"] == "it's fine"
    assert doc["double"] == "a: colon # and hash"
    assert doc["escapes"] == "tab\there"
    assert doc["unicode"] == "A"


def test_quoted_scalar_stays_a_string():
    # Without quotes these would resolve to a bool and an int; the quotes are
    # how a user says "the literal text 42".
    assert parse_yaml('a: "true"\nb: "42"\n') == {"a": "true", "b": "42"}


def test_comments_stripped_but_not_inside_quotes_or_mid_token():
    doc = parse_yaml(
        "# leading\n" "a: 1  # trailing\n" 'b: "has # inside"\n' "c: PIC-X#Y\n"
    )
    assert doc == {"a": 1, "b": "has # inside", "c": "PIC-X#Y"}


def test_apostrophe_inside_a_plain_scalar_does_not_hide_a_comment():
    # A quote only opens a quoted scalar at the start of a value; mid-word it
    # is an ordinary character and must not swallow the comment after it.
    doc = parse_yaml(
        "owner: Sam's shop  # who runs it\n"
        "don't: 1\n"
        "list:\n"
        "  - it's here  # note\n"
        "  - 'quoted # kept'\n"
        "dash: -'x # c\n"
    )
    assert doc == {
        "owner": "Sam's shop",
        "don't": 1,
        "list": ["it's here", "quoted # kept"],
        "dash": "-'x",
    }


def test_leading_document_marker_allowed():
    assert parse_yaml("---\na: 1\n") == {"a": 1}


def test_document_end_marker_stops_parsing():
    assert parse_yaml("a: 1\n...\nb: 2\n") == {"a": 1}


def test_value_containing_colon_is_not_split():
    # Only a colon followed by whitespace separates a key from its value.
    assert parse_yaml("url: http://example.com/x\n") == {"url": "http://example.com/x"}


# -- YAML 1.2 core schema behavior, chosen deliberately -----------------------


@pytest.mark.parametrize("word", ["yes", "no", "on", "off", "Yes", "OFF"])
def test_yes_no_on_off_stay_strings(word):
    # YAML 1.1 makes these booleans, which is the single most notorious
    # source of silent config bugs (`charset: no` meaning False). This
    # reader follows the 1.2 core schema instead.
    assert parse_yaml(f"a: {word}\n") == {"a": word}


@pytest.mark.parametrize("word", [".inf", "-.inf", ".nan", "infinity"])
def test_infinity_and_nan_stay_strings(word):
    assert parse_yaml(f"a: {word}\n") == {"a": word}


def test_duplicate_key_is_an_error_not_last_one_wins():
    with pytest.raises(YamlError, match="duplicate key 'a'"):
        parse_yaml("a: 1\na: 2\n")


def test_duplicate_key_in_flow_mapping_is_an_error():
    with pytest.raises(YamlError, match="duplicate key"):
        parse_yaml("x: {a: 1, a: 2}\n")


# -- rejected constructs ------------------------------------------------------


@pytest.mark.parametrize(
    "text,message",
    [
        ("a: &anchor 1\n", "anchors"),
        ("a: *alias\n", "aliases"),
        ("a: !!str 1\n", "tags"),
        ("a: |\n  block\n", "block scalars"),
        ("a: >\n  folded\n", "folded scalars"),
        ("a:\n  <<: b\n", "merge keys"),
        ("%YAML 1.2\na: 1\n", "directives"),
        ("? a\n: b\n", "explicit keys"),
    ],
)
def test_unsupported_constructs_are_rejected(text, message):
    with pytest.raises(YamlError, match=message):
        parse_yaml(text)


def test_multiple_documents_rejected():
    with pytest.raises(YamlError, match="multiple YAML documents"):
        parse_yaml("a: 1\n---\nb: 2\n")


def test_tab_indentation_rejected_with_line_number():
    with pytest.raises(YamlError, match=r":2: tab character in indentation"):
        parse_yaml("a:\n\tb: 1\n")


def test_missing_colon_rejected():
    with pytest.raises(YamlError, match="expected 'key: value'"):
        parse_yaml("just a bare line\n")


def test_unterminated_quote_rejected():
    with pytest.raises(YamlError, match="unterminated quoted string"):
        parse_yaml('a: "no closing quote\n')


def test_unterminated_flow_collection_rejected():
    with pytest.raises(YamlError, match="unterminated flow collection"):
        parse_yaml("a: [1, 2\n")


def test_trailing_content_after_flow_collection_rejected():
    with pytest.raises(YamlError, match="trailing content"):
        parse_yaml("a: [1, 2] junk\n")


def test_non_string_mapping_key_rejected():
    # Legal YAML, but `1:` and `"1":` becoming two different keys downstream
    # is never what a config file author meant.
    with pytest.raises(YamlError, match="mapping key must be a string"):
        parse_yaml("1: x\n")


def test_sequence_entry_inside_a_mapping_rejected():
    with pytest.raises(YamlError, match="sequence entry where a"):
        parse_yaml("a: 1\n- b\n")


def test_mapping_entry_inside_a_sequence_rejected():
    with pytest.raises(YamlError, match="mapping entry where a"):
        parse_yaml("- a\nb: 1\n")


def test_indented_top_level_rejected():
    with pytest.raises(YamlError, match="top-level content must not be indented"):
        parse_yaml("  a: 1\n")


def test_error_messages_name_the_file_and_line():
    # The whole point of rejecting rather than guessing is that the user can
    # go fix the line; the message has to say which one.
    with pytest.raises(YamlError, match=r"^cobol\.yml:3: duplicate key 'a'"):
        parse_yaml("a: 1\nb: 2\na: 3\n", "cobol.yml")


def test_indentless_sequence_as_mapping_value():
    # `key:` followed by `- item` at the key's own column is valid YAML and
    # the form many formatters emit; it used to be rejected.
    assert parse_yaml("copybook_paths:\n- ./copy\n- ./more\n") == {
        "copybook_paths": ["./copy", "./more"]
    }


def test_indentless_sequence_ends_at_the_next_key():
    text = "a:\n- x: 1\n  y: 2\n- z\nb:\n  c:\n  - q\n  d: 1\n"
    assert parse_yaml(text) == {
        "a": [{"x": 1, "y": 2}, "z"],
        "b": {"c": ["q"], "d": 1},
    }


def test_indentless_sequence_still_rejects_duplicate_key():
    with pytest.raises(YamlError, match="duplicate key"):
        parse_yaml("a:\n- 1\na: 2\n")


def test_nested_block_sequence_is_a_list_not_the_string_dash_x():
    # `- - x` is a sequence inside a sequence; it used to come back as the
    # string "- x".
    assert parse_yaml("a:\n  - - x\n    - y\n  - z\n") == {"a": [["x", "y"], "z"]}
    assert parse_yaml("- - - x\n") == [[["x"]]]


@pytest.mark.parametrize("text", ["1_000", "\u0663", "0x1F", "1_0.5"])
def test_numbers_follow_yaml_core_schema_not_python_int(text):
    # Python's int()/float() accept underscores and non-ASCII digits; YAML
    # does not, so these stay strings.
    assert parse_yaml(f"n: {text}\n") == {"n": text}


def test_yaml_core_numbers_still_resolve():
    assert parse_yaml("a: -7\nb: +3\nc: 1.5\nd: .5\ne: 1e3\n") == {
        "a": -7,
        "b": 3,
        "c": 1.5,
        "d": 0.5,
        "e": 1000.0,
    }


@pytest.mark.parametrize("text", ["key: a: b\n", "- k: v: w\n"])
def test_colon_space_inside_plain_value_rejected(text):
    with pytest.raises(YamlError, match="quote the value"):
        parse_yaml(text)


def test_colon_space_inside_quoted_value_is_fine():
    assert parse_yaml('key: "a: b"\n') == {"key": "a: b"}


@pytest.mark.parametrize("sep", ["\x0c", "\x85", "\u2028"])
def test_line_numbers_count_records_not_unicode_line_breaks(sep):
    # str.splitlines() also split on form feed / NEL / U+2028, pushing every
    # later line number past the one the editor shows.
    with pytest.raises(YamlError, match=r"^<config>:2: unterminated flow"):
        parse_yaml(f"a: x{sep}y\nb: [\n")
