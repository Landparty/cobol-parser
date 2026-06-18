# Design: Add shamrice/COBOL-Examples corpus and parse verification

**Date:** 2026-06-17
**Status:** Approved

## Goal

Add the 19 COBOL programs from https://github.com/shamrice/COBOL-Examples to the project as a third-party example corpus and verify they all parse correctly under the IBM Enterprise COBOL dialect. GnuCOBOL-only files are expected-to-fail with xfail rather than being excluded.

## Files Added

Destination: `examples/cobol/shamrice/` (flat layout, no subdirectories).

Source files from the repo (one per original subfolder):

| Source path | Destination filename |
|---|---|
| `accept/accept.cbl` | `accept.cbl` |
| `accept/accept-secure.cbl` | `accept-secure.cbl` |
| `accept/accept_from.cbl` | `accept_from.cbl` |
| `comp_test/comp_test.cbl` | `comp_test.cbl` |
| `display_test/display-test.cbl` | `display-test.cbl` |
| `display_timing/display_timing.cbl` | `display_timing.cbl` |
| `is_numeric/is_numeric.cbl` | `is_numeric.cbl` |
| `json_generate/json_generate.cbl` | `json_generate.cbl` (xfail) |
| `merge_sort/merge_sort_test.cbl` | `merge_sort_test.cbl` |
| `mouse/mouse_example.cbl` | `mouse_example.cbl` (xfail) |
| `numval_test/numval_test.cbl` | `numval_test.cbl` |
| `read_command_args/read_cmd_line_args.cbl` | `read_cmd_line_args.cbl` |
| `read_command_args/read_specific_cmd_line_args.cbl` | `read_specific_cmd_line_args.cbl` |
| `redifines/redefines.cbl` | `redefines.cbl` |
| `report_writer/report_test.cbl` | `report_test.cbl` |
| `screen_size/get_screen_size.cbl` | `get_screen_size.cbl` (xfail) |
| `search/search.cbl` | `search.cbl` |
| `sql/generated_sql_ex.cbl` | `generated_sql_ex.cbl` |
| `sql/sql_example.cbl` | `sql_example.cbl` |
| `sub_program/main_app.cbl` | `main_app.cbl` |
| `sub_program/sub.cbl` | `sub.cbl` |
| `trim/trim.cbl` | `trim.cbl` |
| `unstring/unstring.cbl` | `unstring.cbl` |
| `xml_generate/xml_generate.cbl` | `xml_generate.cbl` (xfail) |

Non-COBOL files (READMEs, `.sql`, `input.txt`) are not included.

## Test File

**`tests/integration/test_shamrice_examples.py`**

- Uses `pytest.mark.integration` (existing marker, no new markers needed)
- Parametrized via `pytest.param` list built at module level by globbing `examples/cobol/shamrice/*.cbl`
- Each param uses the filename stem as the test ID
- GnuCOBOL files get `pytest.mark.xfail(strict=False, reason="GnuCOBOL extension not supported")`
- Assertion: `result.ast is not None` and `result.errors == []`
- Parser instantiated with `ErrorRecoveryMode.FAIL_FAST`

## GnuCOBOL xfail List

These four files use verbs outside IBM Enterprise COBOL and are expected to fail:

- `json_generate.cbl` — `JSON GENERATE` verb
- `xml_generate.cbl` — `XML GENERATE` verb
- `mouse_example.cbl` — GnuCOBOL mouse extension
- `get_screen_size.cbl` — GnuCOBOL screen size extension

## Parse Failures → Fix the Parser

Any IBM COBOL file that fails the strict assertion (`errors == []`) requires a parser fix, not a weakened assertion. Fixes go in the parser and are documented in the commit message. If a fix is non-trivial it gets its own commit.

## What Is Not Changed

- No new pytest markers
- No changes to coverage thresholds
- No changes to existing test files
- No vendoring into `backend/_vendor/`
