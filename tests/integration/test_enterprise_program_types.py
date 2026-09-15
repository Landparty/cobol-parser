"""One program per IBM Enterprise COBOL *program type*, end to end.

``tests/samples/enterprise/`` holds one representative program for each kind
of program an Enterprise COBOL shop actually compiles -- QSAM batch with
SORT, VSAM maintenance, CICS pseudo-conversational and channel/container
programs, IMS DL/I batch, IMS MPP and EXEC DLI, DB2 batch and a DB2 stored
procedure, MQ, a called subprogram, nested programs, Report Writer, an OO
class and its client, XML/JSON, DECLARATIVES, Language Environment services,
compiler directives, the 6.x data clauses, and a copybook-heavy program.
``docs/enterprise-program-types.md`` is the matrix.

Every program must parse with **no errors and no warnings** under FAIL_FAST
(a warning means content was dropped, and a dropped statement is an unseen
boundary for the tools built on the AST), every analyzer must run over it,
the fixture generator and the whole-checkout scanner must accept it, and
each program must exhibit the traits that make it *that* type -- a CICS
program whose EXEC CICS statements were not seen would still be
"warning-free".
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from pathlib import Path
from typing import Any

import pytest

from cobolparser import (
    CobolParser,
    ComplexityAnalyzer,
    CRUDMatrixGenerator,
    DclgenChecker,
    DeadCodeAnalyzer,
    ErrorRecoveryMode,
    IOLogger,
    IOSequenceAnalyzer,
    LanguageEnvironmentAnalyzer,
    LinkageChecker,
    LintAnalyzer,
    MoveTypeChecker,
    ProgramFlowAnalyzer,
    RecursionRiskAnalyzer,
    RedundancyAnalyzer,
    TechnicalDebtAnalyzer,
    UnusedVariableAnalyzer,
    expand_copybooks,
)
from cobolparser.analysis import (
    DynamicCallAnalyzer,
    HostVariableResolver,
    IMSSegmentAnalyzer,
)
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.generators import ProgramFixtureGenerator, ProgramLayoutIndex
from cobolparser.generators.flowchart import MermaidFlowchartGenerator
from cobolparser.models.program import CobolProgram
from cobolparser.scan import ScanOptions, scan_files

pytestmark = pytest.mark.integration

CORPUS = Path(__file__).parent.parent / "samples" / "enterprise"
COPYBOOKS = [str(CORPUS / "copybooks")]

#: The corpus, by program type. The key is the file stem; the value is what
#: the program is, for the test ids and for the matrix in the docs.
PROGRAM_TYPES: dict[str, str] = {
    "BATCHSEQ": "QSAM batch job step with SORT INPUT/OUTPUT PROCEDURE",
    "VSAMKSDS": "VSAM KSDS/RRDS/ESDS maintenance",
    "CICSONLN": "CICS pseudo-conversational online transaction",
    "CICSCHNL": "CICS channel/container service program",
    "CICSLINK": "CICS LINKed-to server program (translated form)",
    "IMSDLIB": "IMS DL/I batch (DLITCBL, CBLTDLI)",
    "IMSMPP": "IMS message processing program",
    "EXECDLI": "IMS EXEC DLI command-level program",
    "DB2BATCH": "DB2 batch program",
    "DB2SP": "DB2 external stored procedure",
    "MQBATCH": "IBM MQ batch consumer/producer",
    "SUBPROG": "called subprogram (INITIAL, BY VALUE, RETURNING, ENTRY, RECURSIVE)",
    "NESTED": "nested programs (COMMON, GLOBAL, EXTERNAL)",
    "RPTWRTR": "Report Writer report",
    "OOCOBOL": "object-oriented class definition (CLASS-ID)",
    "OOCLIENT": "object-oriented client (INVOKE, OBJECT REFERENCE)",
    "XMLJSON": "XML PARSE/GENERATE and JSON GENERATE/PARSE",
    "DECLARE": "DECLARATIVES (USE AFTER STANDARD ERROR)",
    "LESERV": "Language Environment services and intrinsic functions",
    "COMPDIR": "compiler directives (CBL/PROCESS, >>DEFINE/>>IF, REPLACE)",
    "MODERN63": "Enterprise COBOL 6.x data description",
    "COPYREPL": "copybook-heavy program (COPY REPLACING, nested COPY, INCLUDE)",
}

#: Warnings the corpus is allowed to produce: informational, not a drop.
_ALLOWED_WARNINGS = ("Compilation unit contains ",)


def _params() -> list[Any]:
    return [pytest.param(name, id=name) for name in PROGRAM_TYPES]


def _parse(name: str) -> tuple[CobolProgram, list[str]]:
    """Expand copybooks, then parse under FAIL_FAST; return (ast, warnings)."""
    path = CORPUS / f"{name}.cbl"
    expansion = expand_copybooks(path.read_text(encoding="utf-8"), COPYBOOKS)
    parser = CobolParser(error_recovery=ErrorRecoveryMode.FAIL_FAST)
    result = parser.parse(expansion.expanded_source, str(path))
    assert result.ast is not None, f"{name}: no AST: {result.errors}"
    assert result.errors == [], f"{name}: parse errors: {result.errors}"
    return result.ast, list(result.warnings)


@pytest.fixture(scope="module")
def corpus_asts() -> dict[str, tuple[CobolProgram, list[str]]]:
    return {name: _parse(name) for name in PROGRAM_TYPES}


class TestCorpusShape:
    def test_every_program_type_has_a_sample(self) -> None:
        on_disk = {p.stem for p in CORPUS.glob("*.cbl")}
        assert on_disk == set(PROGRAM_TYPES), (
            "tests/samples/enterprise and PROGRAM_TYPES disagree; add the "
            "program to both (and to docs/enterprise-program-types.md)"
        )

    @pytest.mark.parametrize("name", _params())
    def test_no_content_past_column_72(self, name: str) -> None:
        for number, line in enumerate(
            (CORPUS / f"{name}.cbl").read_text().splitlines(), 1
        ):
            assert not line[72:].strip(), f"{name}:{number}: content past column 72"


class TestParsesCleanly:
    @pytest.mark.parametrize("name", _params())
    def test_fail_fast_no_errors_no_warnings(self, name: str, corpus_asts) -> None:
        _ast, warnings = corpus_asts[name]
        unexpected = [w for w in warnings if not w.startswith(_ALLOWED_WARNINGS)]
        assert unexpected == [], f"{name}: {unexpected}"

    @pytest.mark.parametrize("name", _params())
    def test_json_round_trip(self, name: str, corpus_asts) -> None:
        ast, _ = corpus_asts[name]
        payload = json.loads(ast.to_json())
        assert payload["program_name"] == ast.program_name


class TestEveryAnalyzerRuns:
    """Every analyzer, over every unit, without raising; lint runs them all
    over one parse and must report no ``failed_rules``."""

    @pytest.mark.parametrize("name", _params())
    def test_analyzers(self, name: str, corpus_asts) -> None:
        ast, _ = corpus_asts[name]
        with redirect_stdout(io.StringIO()):
            lint = LintAnalyzer().analyze(ast)
        assert lint.failed_rules == [], f"{name}: {lint.failed_rules}"
        for unit in ast.program_units():
            DeadCodeAnalyzer().analyze(unit)
            UnusedVariableAnalyzer().analyze(unit)
            flow = ProgramFlowAnalyzer().analyze(unit)
            MermaidFlowchartGenerator().generate(flow)
            RecursionRiskAnalyzer().analyze(unit, flow)
            ComplexityAnalyzer().analyze(unit)
            RedundancyAnalyzer().analyze(unit)
            TechnicalDebtAnalyzer().analyze(unit)
            IOLogger().analyze(unit)
            IOSequenceAnalyzer().analyze(unit)
            MoveTypeChecker().check(unit)
            LinkageChecker().check(unit)
            LanguageEnvironmentAnalyzer().analyze(unit)
            CRUDMatrixGenerator().analyze(unit)
            IMSSegmentAnalyzer().analyze(unit)
            HostVariableResolver().resolve(unit)
            DclgenChecker().check(unit)
            DynamicCallAnalyzer().analyze(unit)
            index = ProgramLayoutIndex.build(unit)
            BoundaryInventoryAnalyzer().analyze(unit, index)

    @pytest.mark.parametrize("name", _params())
    def test_fixture_generation(self, name: str) -> None:
        bundle = ProgramFixtureGenerator().generate_with_scenarios_from_file(
            str(CORPUS / f"{name}.cbl"),
            mode="all",
            seed=7,
            copybook_paths=COPYBOOKS,
        )
        json.loads(bundle.to_json())

    def test_scan_whole_corpus(self) -> None:
        paths = [str(CORPUS / f"{name}.cbl") for name in PROGRAM_TYPES]
        report = scan_files(paths, ScanOptions(copybook_paths=COPYBOOKS))
        payload = report.to_dict()
        files = payload["files"]
        assert len(files) == len(PROGRAM_TYPES)
        for entry in files:
            assert not entry.get("error"), entry
            for unit in entry.get("programs", []):
                assert not unit.get("failed_analyzers"), (entry["path"], unit)


# ---------------------------------------------------------------------------
# Per-type traits: the constructs that make each program its kind must
# survive into the AST and into the analyzers that consume them.
# ---------------------------------------------------------------------------


def _statement_types(ast: CobolProgram) -> set[str]:
    return {type(s).__name__ for s in ast.get_all_statements()}


def _cics_commands(ast: CobolProgram) -> set[str]:
    return {s.cics_command for s in ast.find_all_by_type("ExecCicsStatement")}


def _call_targets(ast: CobolProgram) -> set[str]:
    return {
        (s.called_program or "").strip("'\"").upper()
        for s in ast.find_all_by_type("CallStatement")
    }


def _boundary_keys(ast: CobolProgram) -> set[tuple[str, str]]:
    report = BoundaryInventoryAnalyzer().analyze(ast, ProgramLayoutIndex.build(ast))
    return {(b.ref.category, b.ref.key) for b in report.boundaries}


def _lint(ast: CobolProgram, rule: str) -> list[Any]:
    with redirect_stdout(io.StringIO()):
        report = LintAnalyzer().analyze(ast)
    return [f for f in report.findings if f.rule == rule]


def _item(ast: CobolProgram, name: str) -> Any:
    for item in ast.get_data_items():
        if item.name.upper() == name:
            return item
    raise AssertionError(f"data item {name} not found")


class TestBatchAndFiles:
    def test_batchseq_sort_with_procedures(self, corpus_asts) -> None:
        ast, _ = corpus_asts["BATCHSEQ"]
        assert {
            "SortStatement",
            "ReleaseStatement",
            "ReturnStatement",
        } <= _statement_types(ast)
        sort = ast.find_all_by_type("SortStatement")[0]
        assert sort.input_procedure == "2000-SELECT-INPUT"
        assert sort.output_procedure == "3000-WRITE-REPORT"
        assert DeadCodeAnalyzer().analyze(ast).dead_items == []
        assert {("READ", "TRAN-FILE"), ("WRITE", "REPORT-REC")} <= _boundary_keys(ast)
        assert ProgramFlowAnalyzer().analyze(ast).entry_points[0] == "0000-MAIN"

    def test_vsamksds_indexed_relative_and_verbs(self, corpus_asts) -> None:
        ast, _ = corpus_asts["VSAMKSDS"]
        index = ProgramLayoutIndex.build(ast)
        facts = index.file_facts("CUST-MASTER")
        assert facts is not None
        assert facts.organization == "INDEXED"
        assert facts.access_mode == "DYNAMIC"
        assert facts.record_key == "CM-CUST-ID"
        assert facts.alternate_keys[0]["key"] == "CM-CUST-NAME"
        assert facts.alternate_keys[0]["duplicates_allowed"] is True
        rate = index.file_facts("RATE-TABLE")
        assert rate is not None and rate.organization == "RELATIVE"
        assert rate.relative_key == "WS-RATE-RRN"
        assert {
            "IOStartStatement",
            "IORewriteStatement",
            "IODeleteStatement",
            "IOReadStatement",
        } <= _statement_types(ast)
        assert {
            ("START", "CUST-MASTER"),
            ("REWRITE", "CUST-MASTER-REC"),
        } & _boundary_keys(ast) or ("DELETE", "CUST-MASTER") in _boundary_keys(ast)


class TestCics:
    def test_cicsonln_commands_handlers_and_translator_items(self, corpus_asts) -> None:
        ast, _ = corpus_asts["CICSONLN"]
        assert {
            "RECEIVE",
            "SEND",
            "READ",
            "LINK",
            "XCTL",
            "RETURN",
            "HANDLE",
            "ASKTIME",
            "FORMATTIME",
            "SYNCPOINT",
            "ABEND",
        } <= _cics_commands(ast)
        # HANDLE AID PF3(9000-EXIT-PROGRAM) is a branch CICS takes
        flow = ProgramFlowAnalyzer().analyze(ast)
        handle_edges = {
            (e.source, e.target)
            for e in flow.edges
            if e.edge_type.value == "CICS_HANDLE"
        }
        assert ("2000-PROCESS-INPUT", "9000-EXIT-PROGRAM") in handle_edges
        assert DeadCodeAnalyzer().analyze(ast).dead_items == []
        # DFHCOMMAREA is supplied by the translator: no linkage finding
        assert not any(
            "DFHCOMMAREA" in (f.symbol or "") for f in _lint(ast, "linkage-check")
        )

    def test_cicschnl_channels_containers_web_and_json(self, corpus_asts) -> None:
        ast, _ = corpus_asts["CICSCHNL"]
        assert {
            "GET",
            "PUT",
            "INVOKE",
            "START",
            "WRITEQ",
            "SYNCPOINT",
        } <= _cics_commands(ast)
        json_statements = ast.find_all_by_type("XmlJsonStatement")
        assert {(s.verb, s.action) for s in json_statements} == {
            ("JSON", "PARSE"),
            ("JSON", "GENERATE"),
        }
        keys = _boundary_keys(ast)
        assert any(
            cat == "CICS" and key.startswith("GET CONTAINER") for cat, key in keys
        )

    def test_cicslink_translated_form(self, corpus_asts) -> None:
        ast, _ = corpus_asts["CICSLINK"]
        proc = ast.procedure_division
        assert proc is not None
        assert proc.get_metadata("using_parameters") == ["DFHEIBLK", "DFHCOMMAREA"]
        assert {"HANDLE", "IGNORE", "READ", "REWRITE", "RETURN"} <= _cics_commands(ast)
        # HANDLE CONDITION NOTFND(9000-NOT-FOUND) ERROR(9100-ERROR)
        assert DeadCodeAnalyzer().analyze(ast).dead_items == []
        # The 30-odd EIB fields the translator declares are not "unused"
        unused = {f.symbol for f in _lint(ast, "unused-variables")}
        assert not any(name.startswith("EIB") for name in unused), unused
        assert "DFHEIBLK" not in unused


class TestIms:
    def test_imsdlib_dlitcbl_and_function_codes(self, corpus_asts) -> None:
        ast, _ = corpus_asts["IMSDLIB"]
        assert ast.is_ims_dlitcbl_program()
        calls = IMSSegmentAnalyzer().analyze(ast)
        codes = {c.function_code for c in calls}
        assert {"GN", "GNP", "GHU", "GHN", "REPL", "DLET", "CHKP", "XRST"} <= codes
        assert {"CUSTSEG", "ACCTSEG"} <= set(
            IMSSegmentAnalyzer().get_all_segment_names(calls)
        )
        entry = ast.get_entry_statements()[0]
        assert entry.using_parameters == ["IO-PCB", "CUST-PCB"]

    def test_imsmpp_message_queue_pcbs(self, corpus_asts) -> None:
        ast, _ = corpus_asts["IMSMPP"]
        proc = ast.procedure_division
        assert proc is not None
        assert proc.get_metadata("using_parameters") == [
            "IO-PCB",
            "ALT-PCB",
            "ACCT-PCB",
        ]
        codes = {c.function_code for c in IMSSegmentAnalyzer().analyze(ast)}
        assert {"GU", "ISRT", "CHNG", "PURG"} <= codes

    def test_execdli_command_level(self, corpus_asts) -> None:
        ast, _ = corpus_asts["EXECDLI"]
        commands = {s.ims_command for s in ast.find_all_by_type("ExecImsStatement")}
        assert {"SCHD", "GU", "GNP", "GHU", "GHN", "REPL", "ISRT", "TERM"} <= commands
        calls = IMSSegmentAnalyzer().analyze(ast)
        assert all(c.interface == "EXEC DLI" for c in calls)
        assert {"CUSTSEG", "ACCTSEG", "NOTESEG"} <= set(
            IMSSegmentAnalyzer().get_all_segment_names(calls)
        )
        gu = next(c for c in calls if c.function_code == "GU")
        assert gu.pcb_name == "PCB(1)" and gu.io_area_name == "CUST-AREA"
        assert {("DLI", "SCHD"), ("DLI", "GU"), ("DLI", "TERM")} <= _boundary_keys(ast)


class TestDb2AndMq:
    def test_db2batch_cursors_and_host_variables(self, corpus_asts) -> None:
        ast, _ = corpus_asts["DB2BATCH"]
        # EXEC SQL parses into per-verb nodes (FetchStatement,
        # TransactionControlStatement, ...) as well as ExecSQLStatement
        sql_types = {
            type(s).__name__
            for s in ast.get_all_statements()
            if type(s).__name__ in ("ExecSQLStatement", "FetchStatement")
            or type(s).__name__ == "TransactionControlStatement"
        }
        assert sql_types == {
            "ExecSQLStatement",
            "FetchStatement",
            "TransactionControlStatement",
        }
        keys = _boundary_keys(ast)
        assert {
            ("SQL", "OPEN ACCT-CSR"),
            ("SQL", "FETCH ACCT-CSR"),
            ("SQL", "CLOSE ACCT-CSR"),
            ("SQL", "COMMIT"),
            ("CALL", "DSNTIAR"),
        } <= keys
        resolution = HostVariableResolver().resolve(ast)
        assert "BANK.ACCOUNT" in {t.upper() for t in resolution.declare_tables} or (
            resolution.declare_tables
        )
        assert DclgenChecker().check(ast).violations == []

    def test_db2sp_parameter_list_and_result_set(self, corpus_asts) -> None:
        ast, _ = corpus_asts["DB2SP"]
        proc = ast.procedure_division
        assert proc is not None
        assert len(proc.get_metadata("using_parameters")) == 12
        assert {
            ("SQL", "DECLARE"),
            ("SQL", "OPEN"),
            ("SQL", "SELECT"),
        } <= _boundary_keys(ast)

    def test_mqbatch_mqi_calls(self, corpus_asts) -> None:
        ast, _ = corpus_asts["MQBATCH"]
        assert {
            "MQCONN",
            "MQOPEN",
            "MQGET",
            "MQPUT1",
            "MQCMIT",
            "MQBACK",
            "MQCLOSE",
            "MQDISC",
        } <= _call_targets(ast)
        assert ("CALL", "MQGET") in _boundary_keys(ast)


class TestProgramStructure:
    def test_subprog_interface_and_recursion(self, corpus_asts) -> None:
        ast, _ = corpus_asts["SUBPROG"]
        assert ast.program_attributes == ["INITIAL"]
        proc = ast.procedure_division
        assert proc is not None
        assert proc.get_metadata("using_parameters") == [
            "LK-ACCOUNT",
            "LK-DAYS",
            "LK-INTEREST",
        ]
        assert proc.get_metadata("using_parameter_modes")["LK-DAYS"] == "VALUE"
        assert proc.get_metadata("returning_parameter") == "LK-RETURN-CODE"
        assert [e.entry_name.strip("'\"") for e in ast.get_entry_statements()] == [
            "SUBPROG2"
        ]
        factorial = ast.find_program_unit("FACTORL")
        assert factorial is not None and factorial.is_recursive
        risks = RecursionRiskAnalyzer().analyze(factorial).risks
        assert [r.severity for r in risks] == ["LOW"]
        assert {f.severity for f in _lint(ast, "recursion-check")} == {"info"}
        assert _lint(ast, "linkage-check") == []
        assert {("DYNCALL", "WS-DYN-NAME"), ("CALL", "FACTORL")} <= _boundary_keys(ast)

    def test_nested_units_global_and_external(self, corpus_asts) -> None:
        ast, warnings = corpus_asts["NESTED"]
        assert [u.program_name for u in ast.program_units()] == [
            "NESTED",
            "LOGGER",
            "VALIDATE",
            "INNER-CHECK",
            "POSTER",
        ]
        assert ast.find_program_unit("LOGGER").program_attributes == ["COMMON"]
        assert _item(ast, "WS-SHARED-CONTEXT").is_global
        assert _item(ast, "WS-SHOP-TOTALS").is_external
        assert any("5 program units" in w for w in warnings)

    def test_declaratives_are_modelled_and_not_flow(self, corpus_asts) -> None:
        ast, _ = corpus_asts["DECLARE"]
        proc = ast.procedure_division
        assert proc is not None
        sections = {s.section_name: s.is_declarative for s in proc._sections.values()}
        assert sections == {
            "IN-FILE-ERROR": True,
            "OUT-FILE-ERROR": True,
            "ALL-OUTPUT-ERROR": True,
            "MAIN-LOGIC": False,
        }
        # No pseudo-paragraph for the DECLARATIVES. / END DECLARATIVES. markers
        assert [p.paragraph_name for p in proc.paragraphs] == []
        uses = ast.find_all_by_type("UseStatement")
        assert [(u.use_type, u.is_global, u.file_names) for u in uses] == [
            ("ERROR", False, ["IN-FILE"]),
            ("EXCEPTION", True, ["OUT-FILE"]),
            ("ERROR", False, ["OUTPUT"]),
        ]
        flow = ProgramFlowAnalyzer().analyze(ast)
        # The first procedure after END DECLARATIVES, not the first section
        assert flow.entry_points[0] == "MAIN-LOGIC"
        assert {n.name for n in flow.nodes if n.is_declarative} >= {
            "IN-FILE-ERROR",
            "IN-FILE-ERROR-PARA",
        }
        assert flow.unreachable_nodes == []
        assert DeadCodeAnalyzer().analyze(ast).dead_items == []
        # The WRITE inside the USE procedure is not "WRITE before OPEN"
        assert IOSequenceAnalyzer().analyze(ast).violations == []

    def test_report_writer(self, corpus_asts) -> None:
        ast, _ = corpus_asts["RPTWRTR"]
        assert {"InitiateStatement", "GenerateStatement", "TerminateStatement"} <= (
            _statement_types(ast)
        )
        proc = ast.procedure_division
        assert proc is not None
        assert proc._sections["REGION-NAME-SECTION"].is_declarative
        use = ast.find_all_by_type("UseStatement")[0]
        assert use.use_type == "REPORTING"
        assert use.report_groups == ["REGION-HEAD"]
        assert DeadCodeAnalyzer().analyze(ast).dead_items == []
        assert _item(ast, "SR-AMOUNT").picture_clause.pattern == "S9(7)V99"


class TestObjectOriented:
    def test_class_units_nest(self, corpus_asts) -> None:
        ast, _ = corpus_asts["OOCOBOL"]
        assert ast.unit_kind == "CLASS"
        assert ast.program_name == "ACCOUNT"
        ident = ast.identification_division
        assert ident is not None and ident.get_metadata("inherits") == "BASE"
        assert [(u.unit_kind, u.program_name) for u in ast.program_units()] == [
            ("CLASS", "ACCOUNT"),
            ("FACTORY", "FACTORY"),
            ("METHOD", "create-account"),
            ("OBJECT", "OBJECT"),
            ("METHOD", "initialize-account"),
            ("METHOD", "deposit"),
            ("METHOD", "audit"),
            ("METHOD", "get-balance"),
        ]
        factory = ast.contained_programs[0]
        assert [u.program_name for u in factory.contained_programs] == [
            "create-account"
        ]
        assert {i.name for i in factory.get_data_items()} >= {"FACT-NEXT-ACCT-NO"}
        deposit = ast.find_program_unit("deposit")
        assert deposit is not None
        proc = deposit.procedure_division
        assert proc is not None
        assert proc.get_metadata("using_parameters") == ["LK-AMOUNT"]
        assert proc.get_metadata("using_parameter_modes") == {"LK-AMOUNT": "VALUE"}
        assert proc.get_metadata("returning_parameter") == "LK-RC"
        assert "InvokeStatement" in _statement_types(deposit)
        assert _lint(ast, "linkage-check") == []

    def test_client_object_references_and_invoke(self, corpus_asts) -> None:
        ast, _ = corpus_asts["OOCLIENT"]
        account = _item(ast, "WS-ACCOUNT")
        assert account.usage == "OBJECT REFERENCE"
        assert account.object_class == "ACCOUNT"
        invokes = ast.find_all_by_type("InvokeStatement")
        assert {(s.object_name, s.method_name) for s in invokes} >= {
            ("ACCOUNT", "create-account"),
            ("WS-ACCOUNT", "deposit"),
            ("JSTRING", "NEW"),
        }


class TestDataAndText:
    def test_xml_json_handlers_and_clauses(self, corpus_asts) -> None:
        ast, _ = corpus_asts["XMLJSON"]
        statements = {
            (s.verb, s.action): s for s in ast.find_all_by_type("XmlJsonStatement")
        }
        assert set(statements) == {
            ("XML", "PARSE"),
            ("XML", "GENERATE"),
            ("JSON", "GENERATE"),
            ("JSON", "PARSE"),
        }
        assert statements[("XML", "PARSE")].processing_procedure == "1000-XML-HANDLER"
        assert "CONVERTING LINE-PRICE TO JSON DECIMAL" in (
            statements[("JSON", "GENERATE")].clause_text or ""
        )
        assert DeadCodeAnalyzer().analyze(ast).dead_items == []
        flow = ProgramFlowAnalyzer().analyze(ast)
        assert ("0000-MAIN", "1000-XML-HANDLER") in {
            (e.source, e.target)
            for e in flow.edges
            if e.edge_type.value == "XML_PROCESSING_PROCEDURE"
        }

    def test_language_environment_services(self, corpus_asts) -> None:
        ast, _ = corpus_asts["LESERV"]
        report = LanguageEnvironmentAnalyzer().analyze(ast)
        assert {
            "CEEDAYS",
            "CEEDATE",
            "CEEMOUT",
            "CEEGTST",
            "CEEFRST",
            "CEEHDLR",
            "CEEHDLU",
            "CEE3ABD",
            "CEEGMT",
        } <= set(report.unique_services)
        assert {"CURRENT-DATE", "INTEGER-OF-DATE", "UPPER-CASE"} <= set(
            report.unique_functions
        )
        assert _item(ast, "HANDLER-ROUTINE").usage == "PROCEDURE-POINTER"
        # SET ADDRESS OF HEAP-BUFFER TO ptr references the LINKAGE item
        assert _lint(ast, "linkage-check") == []

    def test_compiler_directives(self, corpus_asts) -> None:
        ast, warnings = corpus_asts["COMPDIR"]
        assert warnings == []
        moves = [(m.source, m.targets) for m in ast.find_all_by_type("MoveStatement")]
        assert ('"PROD"', ["WS-ENV"]) in moves  # >>EVALUATE picked the PROD arm
        assert not any(src in ('"TEST"', '"DEV "') for src, _ in moves)
        assert ("0", ["WS-ROWS"]) in moves  # REPLACE ==:PFX:== BY ==WS== applied
        limits = [i for i in ast.get_data_items() if i.name == "WS-LIMIT"]
        assert [i.value_clause for i in limits] == ["500"]  # >>IF kept one arm

    def test_cobol_6x_data_description(self, corpus_asts) -> None:
        ast, _ = corpus_asts["MODERN63"]
        assert _item(ast, "WS-UTF8-NAME").picture_clause.size == 40
        assert _item(ast, "WS-UTF8-BYTES").byte_length == 120
        assert _item(ast, "WS-UTF8-BYTES").picture_clause.size == 120
        dyn = _item(ast, "WS-UTF8-DYN")
        assert dyn.is_dynamic_length and dyn.dynamic_length_limit == 4000
        assert _item(ast, "WS-NATIONAL-NAME").picture_clause.size == 40
        assert _item(ast, "WS-VOLATILE").is_volatile
        assert _item(ast, "WS-VOLATILE").picture_clause.pattern == "X(8)"
        row = _item(ast, "WS-ROW").occurs_clause
        assert row.is_unbounded and row.max_times is None and row.min_times == 1
        assert row.depending_on == "WS-ROW-COUNT"
        assert _item(ast, "WS-ADDRESS-64").usage == "POINTER-64"
        assert _item(ast, "WS-FUNC-PTR").usage == "FUNCTION-POINTER"
        assert _item(ast, "WS-SIGN-SEP").sign_clause is not None
        assert {
            "AllocateStatement",
            "FreeStatement",
            "SearchStatement",
        } <= _statement_types(ast)
        # SET ADDRESS OF LK-DYNAMIC-AREA TO ptr counts as a reference
        assert _lint(ast, "linkage-check") == []
        assert DeadCodeAnalyzer().analyze(ast).dead_items == []

    def test_copybook_program(self, corpus_asts) -> None:
        ast, _ = corpus_asts["COPYREPL"]
        names = {i.name for i in ast.get_data_items()}
        assert {
            "IN-CUST-ID",
            "IN-CITY",
            "OUT-CUST-ID",
            "OUT-CITY",
        } <= names  # REPLACING
        assert {"WS-COUNTERS", "WS-FLAGS", "WS-EOF-FLAG"} <= names  # nested COPY
        assert {"SQLCA", "SQLCODE", "DCLCUSTOMER", "CUST-NAME-TEXT"} <= names  # INCLUDE
        proc = ast.procedure_division
        assert proc is not None
        assert "8000-COMMON-ABEND" in {p.paragraph_name for p in proc.paragraphs}
        assert _lint(ast, "dclgen-check") == []
