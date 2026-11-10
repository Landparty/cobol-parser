# Public API

What `cobolparser` promises to keep stable, and what it does not. Semantic
versioning (release-please, Conventional Commits) applies to tiers 1 and 2:
removing or renaming a name there, or changing a signature incompatibly, is a
major release. Tier 3 can change in any release.

## Tier 1: the facade (`from cobolparser import ...`)

The names below are exactly `cobolparser.__all__`;
`tests/contracts/test_public_api_list.py` fails when the two differ, so a
name enters or leaves the public API only by editing this page too.

<!-- public-api:facade -->
* **Core parsing errors and configuration:** `ParseError`, `CobolParseError`, `ParseStatistics`
* **AST model classes:** `CobolProgram`, `CobolDivision`, `CobolSection`, `CobolStatement`, `CobolExpression`, `EvaluateStatement`, `WhenClause`, `CobolDataItem`, `SourceLocation`, `ASTNode`, `MoveStatement`, `DisplayStatement`, `PerformStatement`, `CommitStatement`, `RollbackStatement`, `PictureClause`, `OccursClause`
* **Lexer components:** `CobolLexer`, `Token`, `TokenType`, `LexerError`, `tokenize_cobol`
* **Parser components:** `CobolParser`, `ParseResult`, `parse_cobol`
* **Batch parsing:** `parse_files`, `parse_files_with_copybooks`, `BatchResult`
* **Multi-file analyzer scan:** `scan_files`, `ScanOptions`, `ScanReport`, `cross_file_clone_groups`
* **Profiling:** `ProfilingResult`, `FunctionProfile`
* **Preprocessing utilities:** `normalize_fixed_format`
* **Enhanced features:** `MemoryConfiguration`, `SerializationConfig`, `ErrorRecoveryMode`, `DialectType`
* **Package metadata:** `__version__`, `__author__`, `__license__`
* **Dialect support:** `IBMEnterpriseCobol`
* **Copybook expansion:** `expand_copybooks`, `parse_cobol_with_expansion`, `clear_file_cache`, `set_file_cache_size`, `get_file_cache_stats`, `CopybookExpansion`, `CopyStatement`, `CopybookSearchPath`, `ExpansionStatistics`, `PreprocessingError`, `CircularReferenceError`, `CopybookNotFoundError`, `PathTraversalError`, `EncodingError`, `NestingDepthError`
* **Analysis utilities:** `ProgramAnalyzer`, `CRUDFlags`, `CRUDMatrix`, `CRUDMatrixGenerator`, `DeadCodeAnalyzer`, `DeadCodeReport`, `DeadCodeItem`, `DynamicCallAnalyzer`, `FileEntry`, `TableEntry`, `LanguageEnvironmentAnalyzer`, `LEAnalysisResult`, `LEFunctionUsage`, `LEServiceCall`, `ProgramContext`, `ProgramFlowAnalyzer`, `ProgramFlowReport`, `BranchArm`, `BranchNode`, `FlowNode`, `FlowEdge`, `FlowEdgeType`, `IOLogger`, `IOLogReport`, `IOOperation`, `UnusedVariableAnalyzer`, `UnusedVariableReport`, `UnusedVariableItem`, `DclgenChecker`, `DclgenReport`, `DclgenViolation`, `IOSequenceAnalyzer`, `IOSequenceReport`, `IOSequenceViolation`, `IOViolationKind`, `LinkageChecker`, `LinkageReport`, `LinkageViolation`, `LinkageViolationKind`, `MoveTypeChecker`, `MoveTypeReport`, `MoveTypeViolation`, `MoveViolationKind`, `DataCategory`, `LintAnalyzer`, `LintReport`, `LintFinding`, `RecursionRiskAnalyzer`, `RecursionRiskReport`, `RecursionRisk`, `ComplexityAnalyzer`, `ComplexityReport`, `ComplexityThresholds`, `ProcedureComplexity`, `BusinessRuleExtractor`, `BusinessRuleReport`, `BusinessRule`, `RedundancyAnalyzer`, `RedundancyReport`, `CloneGroup`, `CloneMember`, `TechnicalDebtAnalyzer`, `TechnicalDebtReport`, `DebtWeights`, `ComponentBreakdown`, `OffenderProcedure`
<!-- /public-api:facade -->

## Tier 2: stable subpackages

Importable, documented in the OKF topic named, and covered by semver:

| Import from | What | Reference |
|---|---|---|
| `cobolparser.analysis` | everything in its `__all__` (the facade's analyzers plus `IMSSegmentAnalyzer`, `HostVariableResolver`, `Report` and the report / item types) | [`.okf/analysis.md`](../.okf/analysis.md) |
| `cobolparser.analysis.<module>` | the main public names the OKF module map lists for each analyzer module (`XrefAnalyzer`, `FieldFlowAnalyzer`, `ConstraintExtractor`, ...) | [`.okf/analysis.md`](../.okf/analysis.md#module-map-cobolparseranalysis-unless-a-path-is-given) |
| `cobolparser.analysis.context` | `ProgramContext` | [`.okf/analysis.md`](../.okf/analysis.md#calling-conventions) |
| `cobolparser.analysis.protocol` | `ProgramAnalyzer`, `Report` | below |
| `cobolparser.models`, `cobolparser.models.walk` | AST node classes; `all_paragraphs`, `section_paragraphs`, `own_statements`, `walk_statements` | [`.okf/ast-models.md`](../.okf/ast-models.md) |
| `cobolparser.layout` | record layout: `compute_record_layout`, `ProgramLayoutIndex`, `FieldSpec`, copybook record parsing | [`.okf/generators/record-data.md`](../.okf/generators/record-data.md) |
| `cobolparser.generators` | flowcharts, copybook data, decode / compare, `ProgramFixtureGenerator` and the fixture bundle | [`.okf/generators.md`](../.okf/generators.md) |
| `cobolparser.definitions`, `cobolparser.jcl` | CICS CSD / BMS, DB2 DDL, IMS DBD / PSB; JCL through jcl-parser | [`.okf/definitions.md`](../.okf/definitions.md), [`.okf/jcl.md`](../.okf/jcl.md) |
| `cobolparser.preprocess` | `expand_copybooks`, the copybook models and errors, `normalize_fixed_format` | [`.okf/preprocessing.md`](../.okf/preprocessing.md) |
| `cobolparser.parser`, `cobolparser.lexer`, `cobolparser.batch`, `cobolparser.scan` | the modules behind the facade's parsing, lexing, batch and scan names | [`.okf/parser.md`](../.okf/parser.md), [`.okf/batch.md`](../.okf/batch.md) |

[`interface-contract.md`](../interface-contract.md) adds the exact shapes the
backend adapter and mocky-mock rely on; a breaking change there bumps its own
version field as well.

## Tier 3: internal

No promise: any module or name starting with `_` (`_vocabulary`,
`_source_text`, `analysis._procedures`, ...), `cobolparser.core`,
`cobolparser.parsers`, and the internals of `cobolparser.cli` and
`cobolparser.mcp` (the CLI's commands and the MCP server's tools are the
stable surface there, not their Python modules).

## The analyzer interface

Every single-program analyzer is constructed with its options and run on one
program unit, returning a report with `to_dict()`:

```python
from cobolparser import ProgramAnalyzer, parse_cobol
from cobolparser.analysis import LintAnalyzer

def run(analyzer: ProgramAnalyzer, source: str) -> dict:
    return analyzer.analyze(parse_cobol(source).ast).to_dict()

run(LintAnalyzer(), "...")
```

`ProgramAnalyzer` (and `Report`) are `typing.Protocol`s in
`cobolparser.analysis.protocol`: a class conforms by having
`analyze(ast) -> report`, without inheriting anything. The checkers that
used to have only `check()` / `resolve()` (`MoveTypeChecker`,
`LinkageChecker`, `DclgenChecker`, `HostVariableResolver`) also answer
`analyze()`. The few analyzers that deliberately do not fit (they need a
layout index or a codebase graph, return a plain list, or annotate the AST)
are listed, with the reason, in `tests/contracts/test_analyzer_protocol.py`.

## Moved names

Old paths keep working until the next major release:

| Old path | New home | Behaviour |
|---|---|---|
| `cobolparser.preprocess.parse_cobol_with_expansion`, `cobolparser.preprocess.copybook_expander.parse_cobol_with_expansion` | `cobolparser.parser.parse_cobol_with_expansion` (and `cobolparser.parse_cobol_with_expansion`) | resolves, with a `DeprecationWarning` |
| `cobolparser.preprocess.copybook_expander.warn_dropped_debug_lines` | `cobolparser.parser.warn_dropped_debug_lines` | resolves, with a `DeprecationWarning` |
| `cobolparser.preprocess._normalize`, `cobolparser.preprocess.source_format` | `cobolparser._source_text.normalize`, `cobolparser._source_text.source_format` | the same module object, no warning |
