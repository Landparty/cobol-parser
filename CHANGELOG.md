# Changelog

All notable changes to the COBOL parser project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

* All CLI outputs are now properly identified. Every JSON document emitted by
  the `cobol-parser` CLI starts with a `source_file` key (the input path as
  given on the command line) and, for subcommands that parse the source, a
  `program_id` key (the PROGRAM-ID from the IDENTIFICATION DIVISION, or
  `null` when the program has none). This covers `analyze`, `dead-code`,
  `program-flow` (JSON format), `io-sequence`, `move-type-check`,
  `linkage-check`, `language-env`, `ims-dli`, `expand`, and `parse`
  (`--errors`/`--stats` wrapper). `batch` entries additionally carry
  `program_id` next to the existing `path`. Mermaid flowcharts from
  `program-flow --format mermaid` now start with a `%% Program: <name>`
  comment header (DOT output already named the digraph after the program).
  The contract is pinned by `tests/unit/cli/test_output_identification.py`.

### Changed

* **CLI output shapes for list-style results** (part of the output
  identification change above; library APIs are unchanged). `tokenize` now
  emits `{"source_file": ..., "tokens": [...]}` instead of a bare token
  list. `parse --find-type` emits `{"source_file", "program_id",
  "node_type", "matches"}` instead of a bare node list, and dotted-path
  extraction (`parse <file> <path>`) emits `{"source_file", "program_id",
  "path", "result"}` instead of the bare subtree; with `--errors`/`--stats`
  a path extraction now carries those keys directly instead of being wrapped
  under an `"ast"` key.

* `PictureClause` now validates the PICTURE pattern and exposes `is_valid` and
  `validation_errors` (also surfaced in `to_dict()`). Validation is
  conservative -- it flags only unambiguously illegal pictures (empty pattern,
  illegal characters, malformed/empty/zero repeat factors, unbalanced
  parentheses, more than one `V`, both `V` and a decimal point, multiple
  decimal points, and a misplaced or duplicated `S`) so valid pictures are
  never rejected. Pattern parsing remains lenient: an invalid picture is
  flagged but never aborts the surrounding parse.

### Changed

* Internal code-review cleanup removing dead code and consolidating
  duplication (no public-API or behaviour changes; full test suite unchanged).
  Removed unreferenced symbols (`ParserHost` protocol, `TokenStream.match_value`,
  four unused `CobolFileDescription` builder methods, the orphaned
  `TestReference` dataclass, a stray `TypeVar`, and ten dead fixed-format column
  constants in the lexer that duplicated the preprocessor's). Consolidated
  copy-pasted logic behind shared helpers: per-subcommand parse/emit/parser
  boilerplate in the CLI (`_parse_or_fail`, `_emit_report`,
  `_build_analyzer_parser`, `_stats_dict`); clause-list serialization and
  clause/operand setters in the statement AST models
  (`CobolStatement._serialize_clauses` / `_add_unique_operand` and IO clause
  mixins); IO statement-parser preamble and INVALID KEY / KEY-IS handling
  (`create_statement`, `consume_key_is`, `try_consume_keyword`, and reuse of
  `parse_invalid_key_clauses`); and the duplicated unescaped-quote scan in the
  copybook preprocessor.
* Silent `except Exception` handlers that swallowed failures without a trace
  now emit diagnostics instead. `batch.parse_files_with_copybooks()` logs a
  `WARNING` (logger `cobolparser.batch`) when copybook expansion fails and it
  falls back to parsing raw source, and the statement-parser probe helpers
  `peek_token()` / `try_parse_nested()` log at `DEBUG` when their "never raise"
  contract suppresses an exception. The fall-back behaviour itself is
  unchanged. The dead broad-`except` around `CobolProgram.get_division()` in
  the CRUD matrix generator (a plain dict lookup that cannot raise) was
  removed.

### Fixed

* `ASTNode.find_all_by_type()` / `find_first_by_type()` now also match a
  node's concrete class name (e.g. `"MoveStatement"`, `"CallStatement"`,
  `"ExecSQLStatement"`, `"IOReadStatement"`) in addition to the `node_type`
  attribute. All statement subclasses share the generic `node_type`
  `"Statement"`, so lookups by statement class name silently returned nothing
  — which meant the `analyze` CLI subcommand always printed an empty
  `"calls"` list and `parse --find-type` could never select a specific
  statement kind (both are documented to work this way). Lookups by
  `node_type` (`"Statement"`, `"DataItem"`, `"ConditionNameItem"`, ...) are
  unchanged, and serialized output is unaffected.

* Lexer now recognises typed-literal prefixes (`X"1F"` hexadecimal, `N"..."`
  national, `NX"..."` national-hex, `G"..."` DBCS/graphic, `Z"..."`
  null-terminated, `U"..."` UTF-8, `B"..."` boolean). Previously a prefixed
  literal was split into a separate identifier token plus a string literal
  (e.g. `MOVE X"1F" TO WS` parsed `X` as its own operand), corrupting
  statement operands. Such literals now produce a single `STRING_LITERAL`
  token whose `raw_value` preserves the original prefixed source text. The
  Cython-accelerated lexer (`_lexer_fast`) was updated to match.

## [1.1.0](https://github.com/Landparty/cobol-parser/compare/v1.0.0...v1.1.0) (2026-06-19)


### Features

* add shamrice/COBOL-Examples corpus with parse verification tests ([cd0b7c4](https://github.com/Landparty/cobol-parser/commit/cd0b7c40e1e5881b2f3e634bb36fff0333d5362e))
* **ims:** add IMSEntryPoint class and integrate ENTRY 'DLITCBL' detection ([b41104c](https://github.com/Landparty/cobol-parser/commit/b41104c54b7ddddeec348f7467c483adc20b0d50))
* **lexer:** support typed-literal prefixes (X/N/NX/G/Z/U/B) ([b3d428a](https://github.com/Landparty/cobol-parser/commit/b3d428ae7844b4441357dc0c20733946bbc1a81b))
* **models:** validate PICTURE clause patterns ([6c9a414](https://github.com/Landparty/cobol-parser/commit/6c9a414aaa43c292d7e6181747fac7f49117ed53))


### Bug Fixes

* **docs:** update test count and success metrics in README and CLAUDE.md ([bfad610](https://github.com/Landparty/cobol-parser/commit/bfad61032d1d6d320cb24f7f11bb8e8bed295cdf))
* **lexer:** keep unterminated typed literals lenient in free-form ([401aa4f](https://github.com/Landparty/cobol-parser/commit/401aa4f60c2616978a3af71739a91bcd1fa4e63c))
* **logging:** include tracebacks in suppressed-exception logs; correct test docstring ([f4959c5](https://github.com/Landparty/cobol-parser/commit/f4959c569df1ed5d07df15fe8c452b8db91ef366))
* **parser:** improve real-world COBOL parse success to 99.1% on NIST-85 corpus ([7a1a387](https://github.com/Landparty/cobol-parser/commit/7a1a3876e2e2fb87648f59a2b8aa8b3710b93e2a))


### Documentation

* add design spec for shamrice COBOL examples corpus ([98bb00b](https://github.com/Landparty/cobol-parser/commit/98bb00bbbd4659f914e866905290ef542c785489))

## 1.0.0 (2026-06-16)


### Features

* add --profile, --profile-top-n, --profile-output CLI flags ([13a3f1f](https://github.com/Landparty/cobol-parser/commit/13a3f1f1b9b0690105eaed738601d9730abd76fa))
* add --profile/--profile-top-n/--profile-output CLI flags to cobol-parser ([5f2468c](https://github.com/Landparty/cobol-parser/commit/5f2468c61fc1fd61f2099fe550aff4646c02181c))
* add advanced configuration options for ignored memory patterns and language server settings ([4808304](https://github.com/Landparty/cobol-parser/commit/4808304ddf6262dc7797c45410d4ca194492891b))
* add batch.py with BatchResult, _parse_one worker, and parse_files() ([6680e5d](https://github.com/Landparty/cobol-parser/commit/6680e5d829c6344f418a28feb044a470d4231467))
* Add comprehensive COBOL CALL statement parsing, samples, and validation utilities. ([9c4d75f](https://github.com/Landparty/cobol-parser/commit/9c4d75f6b6b5f5689de5aa501ff7558640eb5006))
* Add comprehensive COBOL examples demonstrating CALL statements and exception handling ([52e5f14](https://github.com/Landparty/cobol-parser/commit/52e5f1447077d3facce33e9c9848c8f04fda5220))
* Add comprehensive test cases and samples for COBOL CALL and ENTRY statement parsing. ([c07e94b](https://github.com/Landparty/cobol-parser/commit/c07e94bb22bd6314ccdb573f724b05682bcd2a74))
* add convergence node tracking for branch decisions in program flow analysis ([b7e0787](https://github.com/Landparty/cobol-parser/commit/b7e07871882ff2ee3b68cfcdba3228958c99e191))
* add CRUDMatrixGenerator for mainframe modernization analysis ([79f2a28](https://github.com/Landparty/cobol-parser/commit/79f2a282cc7794eb7f9589fd037c92ac8f997707))
* Add examples for COBOL parser testing and demonstration ([8df3f9f](https://github.com/Landparty/cobol-parser/commit/8df3f9ffeb8a36657b531964508e628e6ce23a12))
* add IO statement parsers for OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START ([63ae8c2](https://github.com/Landparty/cobol-parser/commit/63ae8c2d44963f154362bb81642040606368364c))
* Add macOS compatibility verification script and update README ([18e724c](https://github.com/Landparty/cobol-parser/commit/18e724c3dfea79327bc6ef83c948c2fd06f828f6))
* add profiling module with ProfilerContext, ProfilingResult, FunctionProfile ([01ab5d2](https://github.com/Landparty/cobol-parser/commit/01ab5d299046c7ba1d6d1c60d230721936912279))
* add profiling overloads to CobolParser.parse() ([27a0dd8](https://github.com/Landparty/cobol-parser/commit/27a0dd8e02a6180328308932cafe07c39e2f7044))
* add profiling overloads to parse_cobol() ([1e17ef0](https://github.com/Landparty/cobol-parser/commit/1e17ef0e029fc9cafbbb6bf9abf68cbf9a5fa6ce))
* add profiling support to batch parsing functions ([1ac0f4f](https://github.com/Landparty/cobol-parser/commit/1ac0f4f08fe78382fcae884cb9c3f338ad35f055))
* add profiling support to BatchResult and parse_files() ([b3332e0](https://github.com/Landparty/cobol-parser/commit/b3332e0902f9fda206bedf5f41e968b19034ab07))
* add psutil optional dependency for profiling extra ([33774c2](https://github.com/Landparty/cobol-parser/commit/33774c20342200403eeea1ea8fedf513ebace362))
* complete ProgramFlowAnalyzer with cycle detection, unreachable nodes, and missing statement coverage ([5ac379e](https://github.com/Landparty/cobol-parser/commit/5ac379ea97766255e4a743b1f7b1b0480c4874d0))
* **docs:** Revise documentation structure and add cookbook for practical usage examples ([f0b6e1c](https://github.com/Landparty/cobol-parser/commit/f0b6e1c2db0f9fb3c3e31a3accb03a050666b9f3))
* Enhance COBOL parser to support nested PERFORM and IF statements with inline handling ([b7cf7ef](https://github.com/Landparty/cobol-parser/commit/b7cf7ef20badf742816403248f204856df0dc1c1))
* enhance COBOL parser with batch processing optimizations and reusable components ([851b348](https://github.com/Landparty/cobol-parser/commit/851b348e44e414f7d772ca9c4dfec668d3ec10f0))
* Enhance COBOL parser with fixed-format auto-detection and multi-line string support ([48375e6](https://github.com/Landparty/cobol-parser/commit/48375e6f093e21eb1bb6c0b1436e37cd13854888))
* Enhance COPY statement parser with comment and string literal handling ([6c5a97b](https://github.com/Landparty/cobol-parser/commit/6c5a97b46cc1032112bd3b29ea8c5cfc839c8900))
* Enhance dynamic CALL statement support in COBOL parser ([744d0ca](https://github.com/Landparty/cobol-parser/commit/744d0ca0ba049ca8f63c00cf8515869599164f4d))
* **evaluate-coverage:** Add specification and quality checklist for COBOL Fixed-Format EVALUATE coverage ([74f480f](https://github.com/Landparty/cobol-parser/commit/74f480f29325d44e90ca07045290f83ed3f3aeac))
* export parse_files and BatchResult from cobolparser package ([1a3a9e6](https://github.com/Landparty/cobol-parser/commit/1a3a9e61cc4d0c6d15d804c72ab04209f04fab1a))
* export ProfilingResult and FunctionProfile from cobolparser public API ([b0803c3](https://github.com/Landparty/cobol-parser/commit/b0803c3ce9739367c7c10babdd767dac010e1080))
* Implement copybook preprocessing, expand documentation with new guides, and archive historical reports and metrics. ([3790f39](https://github.com/Landparty/cobol-parser/commit/3790f3991e5b89b17375a8b2e9502a6bae319597))
* implemented parser to return IMS, CICS and DB2 instructions ([11771af](https://github.com/Landparty/cobol-parser/commit/11771af1e8cfefb3b4573b5aa0bc6d077bc33223))
* **io-statements:** Implement comprehensive support for IO statements ([39b1881](https://github.com/Landparty/cobol-parser/commit/39b1881c0d77d185c21352328c2fb3510f2edab2))
* **lexer:** Add support for figurative constants in VALUE clause parsing ([d7526e5](https://github.com/Landparty/cobol-parser/commit/d7526e592d382daeb18d872b3574b7345f57f1da))
* optimize statement retrieval in CobolProgram with caching mechanism ([6257308](https://github.com/Landparty/cobol-parser/commit/625730870b49f817d1ce79ffd69ee0e37d9d4b23))
* **parser:** Implement inline parsing for EVALUATE statement with diagnostics ([aef8eda](https://github.com/Landparty/cobol-parser/commit/aef8edabdb5254519154cc6ab3ccca285f598c63))
* **parser:** surface statement errors and honor ErrorRecoveryMode ([aa87b88](https://github.com/Landparty/cobol-parser/commit/aa87b8827590b97179534926a36d71b81a9c1c09))
* **program-flow:** model THRU ranges and classify circular dependencies ([da89832](https://github.com/Landparty/cobol-parser/commit/da8983225c237e9c8173662f774bf5c2787ce8e2))
* **program-flow:** model THRU ranges and classify cycles ([e166594](https://github.com/Landparty/cobol-parser/commit/e1665947b4e9dd12c62b4c0e4ee34320f62fdffc))
* **T015-T021:** Complete Phase 2 test suites and contracts ([c1aea81](https://github.com/Landparty/cobol-parser/commit/c1aea81c06bf06100a51d05a38d3ebbe76afa409))
* update project dependencies and enhance CLAUDE.md documentation ([2a5d200](https://github.com/Landparty/cobol-parser/commit/2a5d20019213c0784e1adb748450371bd04d56ba))


### Bug Fixes

* address review feedback on parser/lexer optimizations ([fc781c2](https://github.com/Landparty/cobol-parser/commit/fc781c2614705138cfc8f91093950bb2857ee0ef))
* apply review feedback on T3 profiling overloads ([911834d](https://github.com/Landparty/cobol-parser/commit/911834da87b848194d7498f89230384d90068884))
* catch parse_cobol exceptions in worker to prevent batch abort ([f7d8fde](https://github.com/Landparty/cobol-parser/commit/f7d8fde28afe0d59ee62acd3cd4a5bbba7d9572e))
* clean up profiling module per code review ([9eec0ce](https://github.com/Landparty/cobol-parser/commit/9eec0ce5b428fd32472890ab33d13a5353893d72))
* **copy_statement_parser:** handle \r and \r\n line endings in source_location ([b6f4822](https://github.com/Landparty/cobol-parser/commit/b6f48225c40ff087e909efaf3ca5a5c500f7280d))
* **data:** drop dead branches in _parse_data_item fallback ([e641b7c](https://github.com/Landparty/cobol-parser/commit/e641b7cd686af285604ffe2e2a1ac59aa7dd51e6))
* **data:** mirror SIGN/SYNC/JUSTIFIED/BLANK/POINTER clauses in Cython fast path ([4acb0b1](https://github.com/Landparty/cobol-parser/commit/4acb0b1433a837a40e179a69b5271522cce061e4))
* **lexer,preprocess:** scientific notation crash, configurable cache, encoding warnings ([740d725](https://github.com/Landparty/cobol-parser/commit/740d72510a109dc87cd70936219d896cd6337dbb))
* **parser,preprocess:** address Copilot review on PR [#49](https://github.com/Landparty/cobol-parser/issues/49) ([a69033e](https://github.com/Landparty/cobol-parser/commit/a69033e0ce994d94b326a365093a1820990c1dec))
* remove over-broad parse exception catch; parity test uses workers=2 for pickle coverage ([a54b31d](https://github.com/Landparty/cobol-parser/commit/a54b31d89a0531ae28214be06825420759186919))
* remove unused pytest imports flagged by ruff ([9d9c0ac](https://github.com/Landparty/cobol-parser/commit/9d9c0acf5d4c1e5f2c1b40f2f0eb3026bb0b8cd4))
* resolve 6 critical parser edge cases causing silent data loss or crashes ([88f97c6](https://github.com/Landparty/cobol-parser/commit/88f97c6113bf088e472335ca7c611dd84de55a0f))
* **setup:** drop unused zip(), satisfy ruff B905 ([2964649](https://github.com/Landparty/cobol-parser/commit/2964649fae357ce3138dfeeb4bfa5b7a6aee62dd))


### Performance Improvements

* always build Cython extensions; tighten TokenStream ([0b33ae9](https://github.com/Landparty/cobol-parser/commit/0b33ae91026807d2cd4b35b74b33fda93e6d7ae3))
* **build,parser:** always build Cython extensions; tighten TokenStream ([1739e40](https://github.com/Landparty/cobol-parser/commit/1739e409f318f1aa7f4db8fc33ce37bd58d3f04c))
* **copy_statement_parser:** pre-build newline index for O(log n) line lookups ([26c1dd3](https://github.com/Landparty/cobol-parser/commit/26c1dd33f306c199ca61f023976fec2252293b85))
* **data:** Cythonize _parse_picture_clause and _parse_data_item loops ([430e1bb](https://github.com/Landparty/cobol-parser/commit/430e1bb2e08001b1d0162fc9a654c5aeb27d479e))
* **data:** hoist _parse_section literals; cache token attrs per iteration ([c263a8c](https://github.com/Landparty/cobol-parser/commit/c263a8c15465d48782e519960645e03db6a97233))
* **data:** use shared _DIVISION_TOKEN_TYPES set; drop hasattr/list-literal cruft ([21125fa](https://github.com/Landparty/cobol-parser/commit/21125fa788652b0cd233c8020a6f1d1aa2e4c497))
* **lexer,data:** Token __slots__; hoist allocations out of data-item loop ([a933512](https://github.com/Landparty/cobol-parser/commit/a933512593d556578c413d4a7500931d971b0135))
* **lexer,models,arith:** IntEnum TokenType; PIC first-char dispatch; COMPUTE inner loop ([773cd02](https://github.com/Landparty/cobol-parser/commit/773cd02d9c952af54edc872c0d26ca51b78bb220))
* **lexer,registry:** cythonize read_number_from_text; share registry across parses ([f0400d3](https://github.com/Landparty/cobol-parser/commit/f0400d3a402dfbe16e86774b646693833999ce32))
* **lexer:** Cythonize _try_single_line_string ([a99f2e2](https://github.com/Landparty/cobol-parser/commit/a99f2e2cb32524192c22a991dc0eb6eeef184ff9))
* **lexer:** Cythonize the outer tokenize() per-line loop ([6cc4128](https://github.com/Landparty/cobol-parser/commit/6cc41282ecbd467b385deb9670de90006e8f9191))
* **move_parser:** hoist stop_token_types and keywords to module-level frozensets ([616eced](https://github.com/Landparty/cobol-parser/commit/616ecedd9e8ea295d78d04dbeb67415cb1b2da47))


### Documentation

* Add comprehensive project completion summary ([ad3471b](https://github.com/Landparty/cobol-parser/commit/ad3471b2e32b1234b81e5ab98c8f4681cc0c1ede))
* add documentation audit design spec (2026-03-30) ([2e3d39a](https://github.com/Landparty/cobol-parser/commit/2e3d39a41ec071f1119e912dcd1debc84677d77a))
* add documentation audit implementation plan (2026-03-30) ([22ce72f](https://github.com/Landparty/cobol-parser/commit/22ce72f22336bd7517ede3248880eae654f8be98))
* Add final status report - project complete and production-ready ([6e028e6](https://github.com/Landparty/cobol-parser/commit/6e028e6a52628d663a1f642506175d37dff7d0ba))
* add framework baseline analysis and fill in plan.md with technical context ([65d576d](https://github.com/Landparty/cobol-parser/commit/65d576d2a7565941258a13ea0b8a95bedc2261e9))
* add full project audit report (2026-03-29) ([69f8d0d](https://github.com/Landparty/cobol-parser/commit/69f8d0d8507b9220f1a86a8ac959898691aadd7c))
* add performance profiling design spec ([b4ba714](https://github.com/Landparty/cobol-parser/commit/b4ba714c654a01953febf69d22abd14941c78a5d))
* add performance profiling implementation plan ([f084773](https://github.com/Landparty/cobol-parser/commit/f0847735f7542e66ae84d5d00a9a0c2634db7176))
* **changelog:** note Cython data-clause drop fix ([8021401](https://github.com/Landparty/cobol-parser/commit/8021401a23188b20a07acc71493f0f64360d0987))
* **claude:** refresh CLAUDE.md to match current code state ([b7c6036](https://github.com/Landparty/cobol-parser/commit/b7c6036278d7925c819a3ce789120db253984649))
* **claude:** refresh CLAUDE.md to match current code state ([931e692](https://github.com/Landparty/cobol-parser/commit/931e69234448db1bb5ce4bbdba5b7a0a634072fe))
* correct license references from MIT to proprietary EULA ([ea2254f](https://github.com/Landparty/cobol-parser/commit/ea2254fe0ab081786d6cf6e7bcada093588a32c0))
* document all analysis features and update CLI reference ([62e3475](https://github.com/Landparty/cobol-parser/commit/62e3475ff55355c34056a1ba00a705a606797569))
* fix BatchResult example — use r.path and guard r.result nullable ([4ee44ae](https://github.com/Landparty/cobol-parser/commit/4ee44ae63297fec76a153b6a4aa43c23cc86b356))
* fix duplicate section, stale file path, and vague BC-4-6 entries ([5f36c09](https://github.com/Landparty/cobol-parser/commit/5f36c09ed761a8f4075e416134965878a4a356a4))
* fix SQL example metadata fields and DECLARE CURSOR sql_type value ([a4520ee](https://github.com/Landparty/cobol-parser/commit/a4520ee2d17bd4b56309cc9a3eb7893982df9559))
* fix stale API reference in data-items.md ([cc4ae82](https://github.com/Landparty/cobol-parser/commit/cc4ae825a645ac223e7bcca8dd5b5b584645c822))
* refresh CLAUDE.md counts (tests, files, TokenTypes, analyzers) ([44af908](https://github.com/Landparty/cobol-parser/commit/44af9083e02e3589d54b0ae25b515f46d811a828))
* **T026-T027:** Add success criteria validation and mark Phase 3 complete ([1a53991](https://github.com/Landparty/cobol-parser/commit/1a53991d01b2349ed5c2218db3c2d033b10e935a))
* update CLAUDE.md to reflect current codebase ([de6c392](https://github.com/Landparty/cobol-parser/commit/de6c39290d8d5d0fb00844cd87fc4411d49afef2))
* update CLAUDE.md to reflect current codebase state ([d2873cf](https://github.com/Landparty/cobol-parser/commit/d2873cf34dc2f451fe9ab056e436bc6848cf6e9c))
* update docs hub — fix metrics, remove dead links, add batch parsing ([363c36a](https://github.com/Landparty/cobol-parser/commit/363c36a9bb11714f83e23440ebb9f6bf153df1c8))
* update documentation and examples for COBOL parser features and fixes ([344ce35](https://github.com/Landparty/cobol-parser/commit/344ce3578d12fbcfe3fc6d62652fc8063809da6e))
* update README badges/counts and add CHANGELOG entries for v1.3.0 and v2.0.0 ([1b403e3](https://github.com/Landparty/cobol-parser/commit/1b403e35cbdecdb526a010c68b8e40a05a60049c))
* update README with correct Python version, test count, and all features ([aad07d4](https://github.com/Landparty/cobol-parser/commit/aad07d42837212480b479665bdc2258259fe7cb0))
* update statement guides — fix AST field names and removed API references ([4994a4e](https://github.com/Landparty/cobol-parser/commit/4994a4eaac7ec15ee27a673f403d93fcedb22a25))
* Update tasks.md - mark all 27 tasks complete + add implementation status report ([bc8a7b3](https://github.com/Landparty/cobol-parser/commit/bc8a7b398779cb8e21fa1e16ff2e190c02831a02))

## [Unreleased]

### Added

- **DATA DIVISION completeness**:
  - `EXTERNAL` and `GLOBAL` data-item clauses are now recorded on
    `CobolDataItem` (`is_external` / `is_global`, serialized in `to_dict()`)
    instead of being silently consumed
  - FD/SD file-description clauses are captured rather than discarded: the
    file's `01` record carries an `fd_clauses` metadata mapping with
    `block_contains`, `record` (fixed and `RECORD VARYING ... DEPENDING ON`),
    `recording_mode`, `label_records`, `code_set`, `data_records`, `linage`,
    and `value_of`
  - Edited `PICTURE` clauses are extracted and classified correctly, including
    embedded decimal points and currency / sign / check-protect / stroke
    insertion symbols (`$$$,$$9.99`, `ZZ,ZZ9.99-`, `**,**9.99`, `XXX/XXX`);
    `PictureClause` now exposes `is_numeric_edited` / `is_alphanumeric_edited`
    and computes the displayed character size

### Fixed

- The Cython-accelerated data-item clause loop (`_data_fast`) had drifted out
  of sync with the pure-Python parser and silently dropped the `SIGN`,
  `SYNCHRONIZED`, `JUSTIFIED`, `BLANK WHEN ZERO`, and bare-`POINTER` clauses in
  compiled builds. The fast loop now hands those clauses back to the
  pure-Python path, which is the single source of truth, so the two
  implementations can no longer diverge. Picture extraction is likewise
  centralized in the Python `_parse_picture_clause`.

- **Analysis toolkit**: comprehensive static and dynamic analyzers exposed via `cobolparser.analysis` and the top-level package:
  - `DeadCodeAnalyzer` — unreferenced paragraphs and sections
  - `ProgramFlowAnalyzer` — control-flow graph with typed PERFORM / GO TO / CALL / fall-through edges (also wired to the `cobol-parser program-flow` CLI). PERFORM/SORT/MERGE `... THRU ...` edges now carry `thru_target` and the ordered `range_members` of every paragraph the range spans, and detected cycles are classified in `cycle_details` by kind (`PERFORM_RECURSION` / `GOTO_LOOP` / `FALL_THROUGH` / `MIXED`) so genuine recursive dependencies are distinguishable from sequential-fall-through artifacts
  - `IOLogger` — structured report of every CALL / SQL / FILE-IO / CONSOLE-IO / ENTRY operation with direction (INPUT / OUTPUT / BIDIRECTIONAL)
  - `IOSequenceAnalyzer` — detects READ/WRITE/REWRITE/DELETE/START before OPEN, double open/close, files left open at program exit
  - `MoveTypeChecker` — flags category-incompatible MOVE statements (numeric ↔ alphabetic, etc.)
  - `LinkageChecker` — cross-references CALL arguments with ENTRY declarations and LINKAGE SECTION 01-items
  - `LanguageEnvironmentAnalyzer` — IBM LE intrinsic functions and service calls
  - `CRUDMatrixGenerator` — program × file/table Create/Read/Update/Delete matrix with CSV and JSON export
  - `IMSSegmentAnalyzer` — resolves IMS DLI segment names for CBLTDLI / AIBTDLI / CEETDLI calls (all 16 DLI function codes)
  - `HostVariableResolver` — resolves `:host-var` references in EXEC SQL to DATA DIVISION data items and DCLGEN DECLARE TABLE columns
- **CobolCheck test generation**: `cobol-parser generate-tests` CLI and `generate_cobolcheck_tests()` Python API, powered by `CoverageAnalyzer` + `TestPlanGenerator` + `CobolCheckGenerator`; supports `paragraph`, `branch`, and `boundary` strategies across 18 branch types
- CLI subcommands grew from 7 to 9 (`program-flow`, `generate-tests`)
- `docs/analysis.md` — comprehensive reference for every analyzer
- Test suite expanded to 3,456 tests across `unit/`, `integration/`, `contract/`, `regression/`, `performance/`

### Fixed

- **DATA DIVISION clause drop in the Cython fast path**: the compiled
  `_data_fast.parse_data_item_clauses_fast` hot path did not handle the
  `SIGN`, `SYNCHRONIZED`/`SYNC`, `JUSTIFIED`/`JUST`, `BLANK WHEN ZERO`, and
  `POINTER` clauses (added to the pure-Python parser later), so when the
  extension was compiled those clauses were silently dropped (e.g.
  `blank_when_zero` stayed `False`). The fast path now mirrors the
  pure-Python branches exactly.

## [1.0.0] - 2026-03-31

### Added

- COBOL parser for Python 3.13+ with full two-stage pipeline: preprocessing → lexing → parsing → AST
- IBM Enterprise COBOL dialect support: COMP-3, EXEC SQL, EXEC CICS, 75+ verbs, IBM intrinsic functions
- Fixed-format and free-form COBOL support with auto-detection; automatic column normalization and comment stripping
- Multi-line string continuation handling with doubled-quote escape sequences
- Statement parsers: CALL, PERFORM, MOVE, DISPLAY, ADD, SUBTRACT, MULTIPLY, DIVIDE, COMPUTE, IF, EVALUATE, OPEN, CLOSE, READ, WRITE, REWRITE, DELETE, START, COPY, and more
- Embedded SQL/CICS/IMS statement parsing (EXEC blocks)
- FD/SD file description and FILE-CONTROL SELECT parsing (including multi-line ASSIGN, ORGANIZATION, ACCESS clauses)
- Copybook expansion via `expand_copybooks()`
- JSON serialization of all AST nodes with optional source location and metadata
- Error recovery modes: `FAIL_FAST` (default) and `COLLECT_ALL`
- Configurable memory management: 64MB–8GB limits, chunk-based streaming for large files
- `parse_files(paths)` for parallel multi-file batch parsing using multiprocessing
- `ParseResult` with AST, errors, warnings, and `ParseStatistics` (timings, counts, peak memory)
- Plugin architecture (`cobolparser/plugins/core.py`) for memory config, dialect, and serialization config
- `ASTNodeFactory` for validated, consistent AST node construction
- `StatementParserRegistry` for dynamic statement parser dispatch
- `DynamicCallAnalyzer` — tracks possible values of variables used in dynamic `CALL` statements
- IO coverage reporter and CLI (`python -m cobolparser.cli.coverage`)
- 2,975 unit, integration, and contract tests; 81%+ line coverage enforced

### Design

- All AST nodes extend `ASTNode` with mandatory `to_dict()` for JSON serialization
- `TokenStream` wraps `List[Token]` with `peek()`, `consume()`, `expect()`
- Division parsers (`IdentificationDivisionParser`, `DataDivisionParser`, `ProcedureDivisionParser`, etc.) are each independently testable
- Statement parsers live in `cobolparser/parsers/statements/`, one file per verb or verb group
- Proprietary license — copyright © 2026 Samuel Dion, all rights reserved
