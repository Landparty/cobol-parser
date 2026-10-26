"""Tests for `cobolparser.config.project`: the cobol.yml schema and discovery.

Covers:
- Upward discovery from a subdirectory, `cobol.yml` beating `cobol.yaml` in
  the same directory, and "found nothing" being an all-default config rather
  than an error
- Paths resolved against the config file's own directory, not the cwd -- a
  run from a subdirectory must search the same copybook libraries as one
  from the project root
- Every recognized key, in both the shapes it accepts (`define` as a mapping
  or as a SYMBOL=VALUE list; a single string where a list is allowed)
- Unknown keys, bad types and out-of-range enum values are REJECTED naming
  the file and the key, never silently ignored
- The `mockymock:`/`analyzer:` tool sections pass through unvalidated, so
  this package never has to know another tool's schema
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cobolparser.config import (
    ConfigError,
    ProjectConfig,
    find_config_file,
    load_project_config,
    resolve,
)

FULL = """\
version: 1

project:
  copybook_path: [copybooks, shared/copybooks]
  callee_path: src/subprograms
  source_format: fixed
  dialect: ibm-enterprise
  error_recovery: fail-fast
  seed: 42
  extensions: [.cbl, .cob]
  define:
    DEBUG: "TRUE"
    BARE:

data:
  charset: ebcdic
  endian: big
  record_format: variable
  record_separator: newline
  rows: 25

lint:
  rules: [dead-code, unused-variables]
  min_severity: warning
  fail_on: error

mockymock:
  test_root: tests
  anything_at_all: 1
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "cobol.yml").write_text(FULL)
    (tmp_path / "src" / "deep").mkdir(parents=True)
    return tmp_path


# -- discovery ----------------------------------------------------------------


def test_no_config_anywhere_is_all_defaults_not_an_error(tmp_path):
    config = load_project_config(tmp_path)
    assert config == ProjectConfig()
    assert config.source is None
    assert config.copybook_path == ()


def test_found_by_walking_up_from_a_subdirectory(project):
    config = load_project_config(project / "src" / "deep")
    assert config.source == project / "cobol.yml"


def test_yml_beats_yaml_in_the_same_directory(tmp_path):
    (tmp_path / "cobol.yaml").write_text("project:\n  seed: 1\n")
    (tmp_path / "cobol.yml").write_text("project:\n  seed: 2\n")
    assert load_project_config(tmp_path).seed == 2


def test_yaml_extension_is_found_when_yml_is_absent(tmp_path):
    (tmp_path / "cobol.yaml").write_text("project:\n  seed: 1\n")
    config = load_project_config(tmp_path)
    assert config.seed == 1
    assert config.source == tmp_path / "cobol.yaml"


def test_find_config_file_returns_none_when_nothing_found(tmp_path):
    assert find_config_file(tmp_path) is None


def test_explicit_path_skips_the_search(tmp_path):
    elsewhere = tmp_path / "other"
    elsewhere.mkdir()
    (elsewhere / "cobol.yml").write_text("project:\n  seed: 9\n")
    (tmp_path / "cobol.yml").write_text("project:\n  seed: 1\n")
    config = load_project_config(tmp_path, path=elsewhere / "cobol.yml")
    assert config.seed == 9


def test_explicit_path_that_does_not_exist_is_an_error(tmp_path):
    # A search finding nothing is fine; a file the user named and that is
    # not there is a typo they need told about.
    with pytest.raises(ConfigError, match="config file not found"):
        load_project_config(path=tmp_path / "nope.yml")


# -- the schema ---------------------------------------------------------------


def test_every_recognized_key_is_read(project):
    config = load_project_config(project)
    assert config.version == 1
    assert config.copybook_path == (
        str(project / "copybooks"),
        str(project / "shared" / "copybooks"),
    )
    assert config.callee_path == (str(project / "src" / "subprograms"),)
    assert config.source_format == "fixed"
    assert config.dialect == "ibm-enterprise"
    assert config.error_recovery == "fail-fast"
    assert config.seed == 42
    assert config.extensions == (".cbl", ".cob")
    assert config.data.charset == "ebcdic"
    assert config.data.endian == "big"
    assert config.data.record_format == "variable"
    assert config.data.record_separator == "newline"
    assert config.data.rows == 25
    assert config.lint.rules == ("dead-code", "unused-variables")
    assert config.lint.min_severity == "warning"
    assert config.lint.fail_on == "error"


def test_copybook_paths_anchored_to_the_config_file_not_the_cwd(project):
    # Loaded from two different directories, the same absolute paths.
    from_root = load_project_config(project)
    from_deep = load_project_config(project / "src" / "deep")
    assert from_root.copybook_path == from_deep.copybook_path


def test_absolute_copybook_path_passes_through(tmp_path):
    absolute = tmp_path / "elsewhere"
    (tmp_path / "cobol.yml").write_text(
        f"project:\n  copybook_path: {absolute.as_posix()}\n"
    )
    assert load_project_config(tmp_path).copybook_path == (str(absolute),)


def test_single_string_accepted_where_a_list_is(tmp_path):
    (tmp_path / "cobol.yml").write_text("project:\n  copybook_path: copybooks\n")
    assert load_project_config(tmp_path).copybook_path == (str(tmp_path / "copybooks"),)


def test_define_mapping_normalized_to_symbol_equals_value(project):
    # A bare key (no value) is the `--define SYMBOL` spelling, which the CLI
    # reads as SYMBOL=TRUE -- so it must NOT become "BARE=None".
    assert load_project_config(project).define == ("DEBUG=TRUE", "BARE")


def test_define_accepts_the_flag_spelling_as_a_list(tmp_path):
    (tmp_path / "cobol.yml").write_text('project:\n  define: ["DEBUG=TRUE", "TRACE"]\n')
    assert load_project_config(tmp_path).define == ("DEBUG=TRUE", "TRACE")


def test_define_boolean_value_rendered_as_cobol_truth(tmp_path):
    (tmp_path / "cobol.yml").write_text("project:\n  define:\n    DEBUG: true\n")
    assert load_project_config(tmp_path).define == ("DEBUG=TRUE",)


@pytest.mark.parametrize(
    ("value", "shape"),
    [("[a, b]", "list"), ("{x: 1}", "mapping"), ("\n      - a", "list")],
)
def test_define_collection_value_rejected_not_stringified(tmp_path, value, shape):
    # Used to become `--define "DEBUG=['a', 'b']"` -- Python's repr of the
    # list, handed to the preprocessor as the symbol's value.
    (tmp_path / "cobol.yml").write_text(f"project:\n  define:\n    DEBUG: {value}\n")
    with pytest.raises(ConfigError, match=f"project.define.DEBUG.*not a {shape}"):
        load_project_config(tmp_path)


def test_empty_file_is_a_config_with_a_source_and_no_settings(tmp_path):
    (tmp_path / "cobol.yml").write_text("# nothing yet\n")
    config = load_project_config(tmp_path)
    assert config.source == tmp_path / "cobol.yml"
    assert config.copybook_path == ()


def test_tool_sections_pass_through_unvalidated(project):
    config = load_project_config(project)
    assert config.tool_section("mockymock") == {
        "test_root": "tests",
        "anything_at_all": 1,
    }
    # An absent section reads as empty rather than raising, so a tool can
    # ask for its own section unconditionally.
    assert config.tool_section("analyzer") == {}


# -- rejections ---------------------------------------------------------------


def test_unknown_top_level_key_rejected(tmp_path):
    (tmp_path / "cobol.yml").write_text("projects:\n  seed: 1\n")
    with pytest.raises(ConfigError, match="unknown key.*projects"):
        load_project_config(tmp_path)


def test_unknown_project_key_rejected_naming_the_section(tmp_path):
    # The hyphenated spelling is the likely typo, since every CLI flag uses
    # one; silently ignoring it would leave the user with a config they
    # believe is in effect and isn't.
    (tmp_path / "cobol.yml").write_text("project:\n  copybook-path: [x]\n")
    with pytest.raises(ConfigError, match="unknown key.*'project'.*copybook-path"):
        load_project_config(tmp_path)


def test_unknown_data_key_rejected(tmp_path):
    (tmp_path / "cobol.yml").write_text("data:\n  charsets: ascii\n")
    with pytest.raises(ConfigError, match="unknown key.*'data'"):
        load_project_config(tmp_path)


@pytest.mark.parametrize(
    "text,message",
    [
        ("project:\n  source_format: fixed-ish\n", "source_format"),
        ("project:\n  dialect: micro-focus\n", "dialect"),
        ("project:\n  error_recovery: keep-going\n", "error_recovery"),
        ("data:\n  charset: utf8\n", "charset"),
        ("data:\n  endian: middle\n", "endian"),
        ("data:\n  record_format: spanned\n", "record_format"),
        ("data:\n  record_separator: crlf\n", "record_separator"),
        ("lint:\n  min_severity: critical\n", "min_severity"),
        ("lint:\n  fail_on: sometimes\n", "fail_on"),
    ],
)
def test_out_of_range_enum_values_rejected(tmp_path, text, message):
    (tmp_path / "cobol.yml").write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_project_config(tmp_path)


def test_unknown_lint_rule_rejected_listing_the_real_ones(tmp_path):
    (tmp_path / "cobol.yml").write_text("lint:\n  rules: [dead-cod]\n")
    with pytest.raises(ConfigError, match="unknown lint rule.*dead-cod"):
        load_project_config(tmp_path)


def test_boolean_seed_rejected(tmp_path):
    # bool is an int subclass; `seed: true` is a mistake, not seed 1.
    (tmp_path / "cobol.yml").write_text("project:\n  seed: true\n")
    with pytest.raises(ConfigError, match="seed.*must be an integer"):
        load_project_config(tmp_path)


def test_non_integer_rows_rejected(tmp_path):
    (tmp_path / "cobol.yml").write_text("data:\n  rows: many\n")
    with pytest.raises(ConfigError, match="rows.*must be an integer"):
        load_project_config(tmp_path)


def test_copybook_path_of_wrong_type_rejected(tmp_path):
    (tmp_path / "cobol.yml").write_text("project:\n  copybook_path: 7\n")
    with pytest.raises(ConfigError, match="copybook_path.*string or a list"):
        load_project_config(tmp_path)


def test_section_that_is_not_a_mapping_rejected(tmp_path):
    (tmp_path / "cobol.yml").write_text("project: [a, b]\n")
    with pytest.raises(ConfigError, match="'project' must be a mapping"):
        load_project_config(tmp_path)


def test_future_schema_version_rejected_with_an_upgrade_hint(tmp_path):
    # Better to refuse than to read a v2 file under v1 rules and act on a
    # partial understanding of it.
    (tmp_path / "cobol.yml").write_text("version: 99\n")
    with pytest.raises(ConfigError, match="unsupported config version 99"):
        load_project_config(tmp_path)


def test_malformed_yaml_reported_as_a_config_error_naming_the_file(tmp_path):
    (tmp_path / "cobol.yml").write_text("project:\n\tseed: 1\n")
    with pytest.raises(ConfigError, match=r"cobol\.yml:2.*tab character"):
        load_project_config(tmp_path)


def test_non_utf8_file_rejected(tmp_path):
    (tmp_path / "cobol.yml").write_bytes(b"project:\n  seed: \xff\xfe\n")
    with pytest.raises(ConfigError, match="not valid UTF-8"):
        load_project_config(tmp_path)


# -- the precedence helper ----------------------------------------------------


def test_resolve_prefers_cli_then_config_then_default():
    assert resolve("cli", "config", "default") == "cli"
    assert resolve(None, "config", "default") == "config"
    assert resolve(None, None, "default") == "default"
    assert resolve(None, None) is None


# -- ~ / $VAR expansion and missing directories (#550) -------------------------


def test_tilde_in_a_path_entry_is_the_home_directory(tmp_path, monkeypatch):
    home = tmp_path / "home"
    (home / "cpy").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    (tmp_path / "cobol.yml").write_text('project:\n  copybook_path: "~/cpy"\n')

    config = load_project_config(tmp_path)

    assert config.copybook_path == (str(home / "cpy"),)
    assert config.missing_directories() == []


def test_environment_variables_in_a_path_entry_are_expanded(tmp_path, monkeypatch):
    monkeypatch.setenv("SHOP_CPY", str(tmp_path / "shop"))
    (tmp_path / "cobol.yml").write_text(
        'project:\n  copybook_path: ["$SHOP_CPY/a", "${SHOP_CPY}/b"]\n'
        '  callee_path: "$SHOP_CPY/calls"\n'
    )

    config = load_project_config(tmp_path)

    assert config.copybook_path == (
        str(tmp_path / "shop" / "a"),
        str(tmp_path / "shop" / "b"),
    )
    assert config.callee_path == (str(tmp_path / "shop" / "calls"),)


def test_missing_directories_names_each_entry_that_is_not_one(tmp_path):
    (tmp_path / "there").mkdir()
    (tmp_path / "cobol.yml").write_text(
        "project:\n  copybook_path: [there, nowhere]\n  callee_path: gone\n"
    )

    config = load_project_config(tmp_path)

    assert config.missing_directories() == [
        ("project.copybook_path", str(tmp_path / "nowhere")),
        ("project.callee_path", str(tmp_path / "gone")),
    ]
