---
type: Module
title: Static Analysis
description: Routing page for cobolparser/analysis/ (37 public modules + the program_flow/ package + 6 private helpers) and dialects/le_signatures.py -- calling conventions shared by every analyzer, which .okf/analysis/*.md file covers which analyzer, the module map and the public imports.
tags: [analysis, routing, dead-code, program-flow, lint, xref, field-lineage, business-rules, fixtures, codebase-graph, sql-cics-lint, le-signatures]
timestamp: 2026-10-15T00:00:00Z
---

# Static Analysis

`cobolparser/analysis/` holds every static analyzer: 37 public modules, the
`program_flow/` package (the control-flow graph, 8 modules) and 6 private
helpers (`_procedures.py`, `_names.py`, `_files.py`, `_cics.py`,
`_sql_whenever.py`, `_sql_flow.py`) the analyzers share so they cannot
disagree. The reference is split by family under [analysis/](analysis/): read
[Calling conventions](#calling-conventions), then load only the file [Which
file?](#which-file) names. Most analyzers back a same-named [CLI](cli.md) subcommand.

## Calling conventions

**Shape.** Every analyzer takes a parsed `CobolProgram` (`parse_cobol(...).ast`)
and returns a report dataclass with `to_dict()` (`IMSSegmentAnalyzer` returns a
plain `list[IMSDLICall]`). Most are `<Analyzer>().analyze(ast) -> <Report>`;
the exceptions are `MoveTypeChecker` / `LinkageChecker` / `DclgenChecker`
(`.check(ast)`), `HostVariableResolver` (`.resolve(ast)`), `ConstantFolder`
(`.fold(ast, index, seed_values=...)`), `ProgramDiffer`
(`.diff(old_ast, new_ast)`), `CodebaseGraphBuilder` (`.build(paths)` /
`.build_from_directory(root)`, many files), `ConstraintExtractor`
(`.extract(ast, index, boundary_report)`), `BoundaryInventoryAnalyzer`
(`.analyze(ast, index, ...)`, needs a `ProgramLayoutIndex`), and
`DynamicCallAnalyzer` (`.analyze(ast) -> None`: it annotates the AST's CALL
statements in place). CFG consumers (recursion, complexity, debt, lint) accept
a precomputed `flow_report=`.

**Shared facts: `ProgramContext`.** `analysis/context.py`'s `ProgramContext(ast)`
builds one unit's cross-reference (`.xref`), flow graph (`.flow`) and
`ProcedureIndex` (`.procedures`, `None` without a PROCEDURE DIVISION) lazily,
once each. The analyzers that read those facts take a context wherever they
take an AST: `XrefAnalyzer` / `ProgramFlowAnalyzer` (which then return the
memoized report), `LintAnalyzer`, `BugPatternAnalyzer`, `CodePatternAnalyzer`,
`CompilerCheckAnalyzer`, `ComplexityAnalyzer`, `RecursionRiskAnalyzer`,
`TechnicalDebtAnalyzer`, `ProgramSignatureExtractor`,
`ConstraintExtractor.extract` and `ProgramFixtureGenerator.generate*`. A bare
AST gets a context for that one call (`ProgramContext.of`), so nothing is shared
across calls unless the caller passes the same context; `ctx.unit(program)`
keeps one per contained program. The MCP server keeps one per unit per parse
(`ParsedProgram.context` / `.xref` / `.flow`). Invariants: facts are shared, so
a reader must not mutate a report it got from a context (the `xref` CLI appends
caveats to its own report, which it builds bare); and a context assumes its AST
no longer changes. `BusinessRuleExtractor` and `FieldFlowAnalyzer` keep their
own `XrefAnalyzer` instance: they call its name-resolution helpers, which read
and write the instance's state, so a shared report would not do.

**Scope.** Most analyzers are program-unit scoped: they examine the unit they
are given and skip `ast.contained_programs` (iterate `ast.program_units()` to
cover a file; `LintAnalyzer` and the `program-signature` CLI do).
`LinkageChecker` is the exception: by default
(`include_contained_programs=True`) it walks every contained unit too.

**Honest reports.** What an analyzer could not check goes to its `caveats` /
`unchecked` / `unresolved` / `unresolved_count` field rather than being dropped,
so a quiet report is never a clean one; consumers must surface those fields.
Report origins after copybook expansion: [analysis/lint.md](analysis/lint.md).

## Which file?

| Task / question | Classes | Load |
|---|---|---|
| Control flow, reachability, dead paragraphs, loops, complexity, clones, debt score, decisions no input can change | `ProgramFlowAnalyzer`, `DeadCodeAnalyzer`, `InputDependenceAnalyzer`, `RecursionRiskAnalyzer`, `ComplexityAnalyzer`, `RedundancyAnalyzer`, `TechnicalDebtAnalyzer` | [analysis/flow.md](analysis/flow.md) |
| Data items, symbols, MOVEs, CALL/LINKAGE, file I/O order, CRUD, dynamic CALL values | `UnusedVariableAnalyzer`, `XrefAnalyzer`, `MoveTypeChecker`, `LinkageChecker`, `IOLogger`, `IOSequenceAnalyzer`, `CRUDMatrixGenerator`, `DynamicCallAnalyzer`, `IOCoverageReporter` | [analysis/data-use.md](analysis/data-use.md) |
| Embedded SQL, DCLGEN, CICS, IMS DL/I, LE services and intrinsics | `HostVariableResolver`, `DclgenChecker`, `SqlCicsAnalyzer`, `IMSSegmentAnalyzer`, `LanguageEnvironmentAnalyzer`, `le_service_signature` | [analysis/sql-cics-ims.md](analysis/sql-cics-ims.md) |
| One severity-graded finding list; bug-pattern rules; source-map origins | `LintAnalyzer`, `BugPatternAnalyzer`, `apply_source_map`, `stamp_report_origins` | [analysis/lint.md](analysis/lint.md) |
| Field-level impact across programs, datasets, tables | `FieldFlowAnalyzer`, `LineageGraph`, `bindings_from_jobs` | [analysis/lineage.md](analysis/lineage.md) |
| Business rules as decision tables | `BusinessRuleExtractor` | [analysis/business-rules.md](analysis/business-rules.md) |
| Call/copy graph, copybook impact, callee interfaces, behaviour diff | `CodebaseGraphBuilder`, `CopybookImpactAnalyzer`, `ProgramSignatureExtractor`, `ProgramDiffer` | [analysis/codebase.md](analysis/codebase.md) |
| `gen-fixtures`: boundaries, branch constraints, witnesses, expectations | `BoundaryInventoryAnalyzer`, `ConstraintExtractor`, `solve`, `ConstantFolder`, `count_invocations` | [analysis/fixtures-support.md](analysis/fixtures-support.md) |
| JCL DD → dataset bindings | `cobolparser.jcl` | [jcl.md](jcl.md) |

## Module map (`cobolparser/analysis/` unless a path is given)

| Module | Main public names | File |
|---|---|---|
| `program_flow/` | `ProgramFlowAnalyzer`, `FlowEdgeType`, `LEADING_SENTENCES_NODE` | [flow](analysis/flow.md) |
| `dead_code.py` | `DeadCodeAnalyzer`, `DeadCodeReport`, `DeadCodeItem` | [flow](analysis/flow.md) |
| `input_dependence.py` | `InputDependenceAnalyzer`, `InputDependenceReport`, `Decision`, `UnreachableResult` | [flow](analysis/flow.md#inputdependenceanalyzer) |
| `_values.py` | `ValuePass` (the value pass behind `InputDependenceAnalyzer`) | [flow](analysis/flow.md#inputdependenceanalyzer) |
| `recursion_risk.py` | `RecursionRiskAnalyzer` | [flow](analysis/flow.md) |
| `complexity.py` | `ComplexityAnalyzer`, `ComplexityThresholds` | [flow](analysis/flow.md) |
| `redundancy.py` | `RedundancyAnalyzer` (clone groups, paragraph fingerprints) | [flow](analysis/flow.md) |
| `technical_debt.py` | `TechnicalDebtAnalyzer`, `DebtWeights` | [flow](analysis/flow.md) |
| `context.py` | `ProgramContext` (memoized xref, flow graph, procedure index) | [analysis](#calling-conventions) |
| `_procedures.py` | `ProcedureIndex`, `enclosing_section`, `qualify` | [flow](analysis/flow.md) |
| `_cics.py` | `cics_exit_kind`, `cics_terminator_kind`, `cics_identifier_options` | [flow](analysis/flow.md), [data-use](analysis/data-use.md) |
| `_sql_whenever.py` | `whenever_coverage` | [flow](analysis/flow.md) |
| `unused_variables.py` | `UnusedVariableAnalyzer`, `collect_declared_items`, `qualified_data_name` | [data-use](analysis/data-use.md) |
| `xref.py` | `XrefAnalyzer` | [data-use](analysis/data-use.md) |
| `move_type_checker.py` | `MoveTypeChecker`, `DataCategory`, `MoveViolationKind` | [data-use](analysis/data-use.md) |
| `linkage_checker.py` | `LinkageChecker`, `LinkageViolationKind` | [data-use](analysis/data-use.md) |
| `io_logger.py` | `IOLogger` | [data-use](analysis/data-use.md) |
| `io_sequence.py` | `IOSequenceAnalyzer`, `IOViolationKind` | [data-use](analysis/data-use.md) |
| `io_coverage_reporter.py` | `IOCoverageReporter`, `CoverageStatus`, `TestType`, `IoCoverageArtifact` | [data-use](analysis/data-use.md) |
| `crud_matrix.py` | `CRUDMatrixGenerator`, `CRUDMatrix`, `CRUDFlags` | [data-use](analysis/data-use.md) |
| `value_tracker.py` | `DynamicCallAnalyzer` | [data-use](analysis/data-use.md) |
| `_names.py` | `base_data_name`, `strip_subscripts`, `strip_qualification`, `bare_item_name`, `qualified_references`, `callee_names`, `IDENTIFIER_TOKEN_RE`, `strip_translator_arguments`, `is_translator_function` | [data-use](analysis/data-use.md) |
| `_files.py` | `record_to_file_map`, `resolve_file_name`, `same_record_area_groups` | [data-use](analysis/data-use.md) |
| `host_var_resolver.py` | `HostVariableResolver` | [sql-cics-ims](analysis/sql-cics-ims.md) |
| `dclgen_check.py` | `DclgenChecker` | [sql-cics-ims](analysis/sql-cics-ims.md) |
| `sql_cics_lint.py` | `SqlCicsAnalyzer` | [sql-cics-ims](analysis/sql-cics-ims.md) |
| `ims_segment_analyzer.py` | `IMSSegmentAnalyzer`, `IMSDLICall`, `IMSEntryPoint` | [sql-cics-ims](analysis/sql-cics-ims.md) |
| `language_env_analyzer.py` | `LanguageEnvironmentAnalyzer` | [sql-cics-ims](analysis/sql-cics-ims.md) |
| `dialects/le_signatures.py` | `le_service_signature`, `intrinsic_signature`, `catalog_to_dict` | [sql-cics-ims](analysis/sql-cics-ims.md) |
| `bug_patterns.py` | `BugPatternAnalyzer`, `BUG_PATTERN_RULES`, `BUG_PATTERN_DESCRIPTIONS`, `walk_statements` (re-exported from the statement models; the seven bug-pattern lint rules) | [lint](analysis/lint.md#bug-pattern-rules) |
| `compiler_checks.py` | `CompilerCheckAnalyzer`, `CompilerChecks`, `COMPILER_RULES`, `COMPILER_RULE_DESCRIPTIONS` (the ten compiler-check lint rules) | [lint](analysis/lint.md#compiler-check-rules) |
| `code_patterns.py` | `CodePatternAnalyzer`, `CODE_PATTERN_RULES`, `CODE_PATTERN_DESCRIPTIONS`, `run_code_pattern` (the eight code-pattern lint rules, ideas from other COBOL linters) | [lint](analysis/lint.md#code-pattern-rules) |
| `lint.py` | `LintAnalyzer`, `RULES`, `ALL_RULES`, `add_call_check_findings`, `add_line_length_findings`, `line_length_findings`, `filter_by_severity`, `add_parse_errors`, `apply_source_map`, `stamp_report_origins`, `fixed_format_column_offset` | [lint](analysis/lint.md) |
| `sarif.py` | `sarif_log`, `SarifResult`, `SarifNotification`, `lint_results`, `call_check_results` | [lint](analysis/lint.md#sarif-output) |
| `field_lineage.py` | `FieldFlowAnalyzer` | [lineage](analysis/lineage.md) |
| `lineage_graph.py` | `LineageGraph` | [lineage](analysis/lineage.md) |
| `field_widening.py` | `FieldWideningAnalyzer` | [lineage](analysis/lineage.md) |
| `lineage_jcl.py` | `bindings_from_jobs`, `load_jobs`, `jobs_from_sources` | [lineage](analysis/lineage.md) |
| `_sql_flow.py` | `analyze_sql` | [lineage](analysis/lineage.md) |
| `business_rules.py` | `BusinessRuleExtractor` | [business-rules](analysis/business-rules.md) |
| `codebase.py` | `CodebaseGraphBuilder`, `CopybookImpactAnalyzer` | [codebase](analysis/codebase.md) |
| `program_signature.py` | `ProgramSignatureExtractor`, `extract_signatures` | [codebase](analysis/codebase.md) |
| `call_interface.py` | `CallInterfaceChecker`, `CalleeResolver`, `find_callee_file` | [codebase](analysis/codebase.md) |
| `ast_diff.py` | `ProgramDiffer` | [codebase](analysis/codebase.md) |
| `boundary_inventory.py` | `BoundaryInventoryAnalyzer` | [fixtures-support](analysis/fixtures-support.md) |
| `constraints.py` | `ConstraintExtractor` | [fixtures-support](analysis/fixtures-support.md) |
| `domains.py` | `solve`, `Witness`, `Unsatisfiable`, `NumericDomain` / `TextDomain` / `EnumDomain` | [fixtures-support](analysis/fixtures-support.md) |
| `const_fold.py` | `ConstantFolder`, `keyed_read_key` | [fixtures-support](analysis/fixtures-support.md) |
| `invocation_counts.py` | `count_invocations`, `is_plain_eof_loop`, `status_sites` | [fixtures-support](analysis/fixtures-support.md) |

## Public API

```python
# Importable from the top-level package
from cobolparser import (
    DeadCodeAnalyzer, UnusedVariableAnalyzer, ProgramFlowAnalyzer,
    RecursionRiskAnalyzer, ComplexityAnalyzer, RedundancyAnalyzer,
    TechnicalDebtAnalyzer, LintAnalyzer, BusinessRuleExtractor, DclgenChecker,
    IOLogger, IOSequenceAnalyzer, MoveTypeChecker, LinkageChecker,
    LanguageEnvironmentAnalyzer, CRUDMatrixGenerator, DynamicCallAnalyzer,
    ProgramContext,
)
# cobolparser.analysis re-exports all of the above plus
from cobolparser.analysis import IMSSegmentAnalyzer, HostVariableResolver
# The rest import from their own module
from cobolparser.analysis.program_flow import FlowEdgeType, LEADING_SENTENCES_NODE
from cobolparser.analysis.xref import XrefAnalyzer
from cobolparser.analysis.input_dependence import InputDependenceAnalyzer
from cobolparser.analysis.program_signature import ProgramSignatureExtractor, extract_signatures
from cobolparser.analysis.call_interface import CallInterfaceChecker
from cobolparser.analysis.codebase import CodebaseGraphBuilder, CopybookImpactAnalyzer
from cobolparser.analysis.sql_cics_lint import SqlCicsAnalyzer
from cobolparser.analysis.ast_diff import ProgramDiffer
from cobolparser.analysis.field_lineage import FieldFlowAnalyzer
from cobolparser.analysis.lineage_graph import LineageGraph
from cobolparser.analysis.lineage_jcl import bindings_from_jobs, load_jobs, jobs_from_sources
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.constraints import ConstraintExtractor
from cobolparser.analysis.domains import solve, Witness, Unsatisfiable
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.analysis.invocation_counts import count_invocations
from cobolparser.dialects.le_signatures import le_service_signature, intrinsic_signature
```

`cobolparser.__all__` lists only the first group (`IOSequenceAnalyzer`, `MoveTypeChecker`,
`LinkageChecker` import but are not in it); `cobolparser.analysis.__all__` adds
the second group and the report / item / enum types.

## See also

* [ast-models.md](ast-models.md) (input AST) · [cli.md](cli.md) (CLI wrappers) ·
  [batch.md](batch.md) (`scan`) · [tests.md](tests.md) (`tests/unit/analysis/`)
* [generators.md](generators.md) -- `ProgramLayoutIndex`, `ScenarioPlanner`,
  `ProgramFixtureGenerator`, flowcharts; [preprocessing.md](preprocessing.md) --
  the expansion source map behind `origin`; [jcl.md](jcl.md) -- JCL adapter
* [history](history/analysis.md) -- dated fix write-ups, audits and bug hunts
