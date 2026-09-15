# IBM Enterprise COBOL program types: coverage matrix

`tests/samples/enterprise/` holds one representative program per *kind* of
program an Enterprise COBOL shop compiles, and
`tests/integration/test_enterprise_program_types.py` runs every one of them
through the whole stack: a FAIL_FAST parse with **no errors and no
warnings** (a warning means content was dropped from the AST), every
analyzer, the fixture generator (`gen-fixtures --scenarios all`), the
whole-checkout scanner, and a set of per-type trait assertions -- the
constructs that make a program *that* type must survive into the AST and
into the analyzers that consume them.

The same corpus lives in `mocky-mock/tests/fixtures/enterprise/`, where
`tests/unit/test_enterprise_corpus.py` pins what `mockymock generate` does
with each program (scaffold / nothing to mock / refused, and under which
refusal code). Keep the two copies identical.

| Program | Type | Distinguishing constructs | Parser | Analyzers | mockymock generate |
|---|---|---|---|---|---|
| `BATCHSEQ` | QSAM batch job step | `SORT ... INPUT/OUTPUT PROCEDURE`, `RELEASE`/`RETURN`, `I-O-CONTROL` (`RERUN`, `SAME RECORD AREA`, `APPLY WRITE-ONLY`), `ACCEPT FROM DATE YYYYMMDD` / `DAY-OF-WEEK`, `SPECIAL-NAMES`, `WRITE ... AFTER ADVANCING PAGE`, `RETURN-CODE` | clean | SORT procedures are flow edges, not dead code; file boundaries inventoried | scaffolds (SORT refused at `run`) |
| `VSAMKSDS` | VSAM maintenance | KSDS with `ALTERNATE RECORD KEY ... WITH DUPLICATES`, `ACCESS DYNAMIC`, two-part `FILE STATUS`, RRDS (`RELATIVE KEY`), `START KEY IS NOT LESS THAN`, `READ NEXT`, `READ KEY IS`, `REWRITE`, `DELETE ... INVALID KEY` | clean | `FileFacts` carries organization, access, keys; `START`/`REWRITE`/`DELETE` boundaries | scaffolds |
| `CICSONLN` | CICS pseudo-conversational | untranslated form (`DFHCOMMAREA` in LINKAGE, `EIBCALEN` from the translator), `RECEIVE`/`SEND MAP`, `READ FILE ... RIDFLD`, `HANDLE AID`, `DFHRESP(...)`, `LINK`, `XCTL`, `RETURN TRANSID COMMAREA`, `ASKTIME`/`FORMATTIME`, `SYNCPOINT ROLLBACK`, `ABEND` | clean | `HANDLE AID PF3(para)` is a `CICS_HANDLE` flow edge (no false dead code); `DFHCOMMAREA` is never an unreferenced LINKAGE item | refused `UNSUPPORTED_CICS_MACRO` (`DFHRESP`) |
| `CICSCHNL` | CICS channel/container + web service | `GET`/`PUT CONTAINER ... CHANNEL`, `INVOKE SERVICE`, `START TRANSID CHANNEL`, `WRITEQ TS`, `SYNCPOINT`, `JSON PARSE`/`JSON GENERATE ... NAME OF`, `DFHVALUE(CHAR)` | clean | every command is a CICS boundary keyed the way `mock_surface` keys it | refused `UNSUPPORTED_CICS_MACRO` (`DFHVALUE`) |
| `CICSLINK` | CICS LINKed-to server (translated form) | `DFHEIBLK` + `DFHCOMMAREA` in LINKAGE, `PROCEDURE DIVISION USING DFHEIBLK DFHCOMMAREA`, `HANDLE CONDITION`, `IGNORE CONDITION`, `READ ... UPDATE`, `REWRITE`, `LENGTH OF` | clean | the 30-odd `EIB*` fields are not "unused variables"; `HANDLE CONDITION` targets are flow edges | refused `UNSUPPORTED_LINKAGE_LAYOUT` (default entry with its own USING) |
| `IMSDLIB` | IMS DL/I batch | `ENTRY 'DLITCBL' USING pcb...`, PCB masks in LINKAGE, qualified/unqualified SSAs, `GU`/`GN`/`GNP`/`GHU`/`GHN`/`REPL`/`ISRT`/`DLET`, `CHKP`/`XRST` | clean | `IMSSegmentAnalyzer` resolves every function code and segment from the SSAs; `is_ims_dlitcbl_program()` | scaffolds (ENTRY + PCB LINKAGE neutralized) |
| `IMSMPP` | IMS message processing program | `PROCEDURE DIVISION USING IO-PCB ALT-PCB db-PCB`, `GU`/`ISRT` on the I/O PCB, `CHNG`/`ISRT`/`PURG` on an alternate PCB, `QC` status | clean | function codes and PCBs resolved | refused `UNSUPPORTED_LINKAGE_LAYOUT` |
| `EXECDLI` | IMS EXEC DLI command level | `EXEC DLI SCHD PSB`, `GU`/`GNP`/`GHU`/`GHN`/`REPL`/`ISRT` with `USING PCB(n) SEGMENT(...) INTO/FROM(...) WHERE(...)`, `DIBSTAT`, `TERM` | clean | `IMSSegmentAnalyzer` reports `EXEC DLI` calls with their PCB, I/O area and segments (new 2026-09-15); every command is a DLI boundary | scaffolds |
| `DB2BATCH` | DB2 batch | `INCLUDE SQLCA`, DCLGEN-style `DECLARE TABLE` + host structure + null indicators, `DECLARE CURSOR WITH HOLD ... FOR UPDATE OF`, `WHENEVER`, `FETCH ... :ind`, `UPDATE ... WHERE CURRENT OF`, rowset `FETCH NEXT ROWSET ... FOR n ROWS`, `SQLERRD(3)`, commit frequency, `CALL 'DSNTIAR'`, `ROLLBACK` | clean | cursor open/fetch/close and commit are SQL boundaries; host variables resolve; DCLGEN check clean | scaffolds |
| `DB2SP` | DB2 external stored procedure | 12-item `PROCEDURE DIVISION USING` (parameters, null indicators, SQLSTATE, procedure/specific name, diagnostic message), `DECLARE ... CURSOR WITH RETURN`, `SQLSTATE` | clean | `using_parameters` complete; SQL boundaries | refused `UNSUPPORTED_LINKAGE_LAYOUT` |
| `MQBATCH` | IBM MQ batch | `MQCONN`/`MQOPEN`/`MQGET` (wait, syncpoint)/`MQPUT1`/`MQCMIT`/`MQBACK`/`MQCLOSE`/`MQDISC` against inline MQOD/MQMD/MQGMO/MQPMO structures, `LENGTH OF` | clean | every MQI call is a CALL boundary | scaffolds |
| `SUBPROG` | called subprogram | `PROGRAM-ID ... IS INITIAL PROGRAM`, `USING BY REFERENCE ... BY VALUE ... RETURNING`, `CALL ... BY CONTENT`, `ON EXCEPTION`, `CANCEL`, a second `ENTRY`, `GOBACK`, a contained `IS RECURSIVE` program with `LOCAL-STORAGE` | clean (attributes and `RETURNING` recorded; new) | `RETURNING` item is referenced; a self-CALL in an `IS RECURSIVE` program is `LOW`/info, not an error | refused `UNSUPPORTED_NESTED_PROGRAM` |
| `NESTED` | nested programs | `IS COMMON`, `IS GLOBAL` data, `IS EXTERNAL` data, three nesting levels, `END PROGRAM` stacking | clean | every unit in `program_units()`, each linted | refused `UNSUPPORTED_NESTED_PROGRAM` |
| `RPTWRTR` | Report Writer | `RD` with `CONTROLS`/`PAGE LIMIT`/`HEADING`/`FIRST DETAIL`/`LAST DETAIL`/`FOOTING`, every group type, `SUM ... UPON`, `LINE`/`COLUMN`/`SOURCE`/`GROUP INDICATE`/`NEXT GROUP`, `PAGE-COUNTER`, `USE BEFORE REPORTING` declarative, `INITIATE`/`GENERATE`/`TERMINATE` | clean (`USE BEFORE REPORTING` now records its report groups) | the declarative section is not dead code | refused `UNSUPPORTED_DECLARATIVES` |
| `OOCOBOL` | object-oriented class | `CLASS-ID ... INHERITS`, `REPOSITORY`, `FACTORY`/`OBJECT` units, `METHOD-ID` with literal names, `USING BY VALUE`/`RETURNING`, `INVOKE ... NEW`, `INVOKE SELF`, `END METHOD`/`END OBJECT`/`END FACTORY`/`END CLASS` | clean (new: was "PROGRAM-ID is mandatory") | class, factory, object and every method are `program_units()` (`unit_kind`); each method's interface is checked | refused `UNSUPPORTED_NESTED_PROGRAM` |
| `OOCLIENT` | object-oriented client | `USAGE OBJECT REFERENCE class`, `INVOKE class 'method' USING BY VALUE ... RETURNING`, `INVOKE ... NEW`, `SET obj TO NULL`, `IF obj NOT = NULL` | clean (`OBJECT REFERENCE` now a usage with `object_class`) | -- | nothing to mock (`INVOKE` is not a boundary) |
| `XMLJSON` | XML / JSON handling | `XML PARSE ... WITH ENCODING ... RETURNING NATIONAL ... VALIDATING ... PROCESSING PROCEDURE`, `XML-EVENT`/`XML-TEXT`/`XML-NTEXT`/`XML-CODE`, `XML GENERATE ... WITH ATTRIBUTES ... NAMESPACE ... NAME OF ... TYPE OF ... SUPPRESS`, `JSON GENERATE ... NAME OF ... SUPPRESS ... CONVERTING ... TO JSON DECIMAL`, `JSON PARSE ... WITH DETAIL`, `JSON-CODE`/`JSON-STATUS` | clean (`CONVERTING` accepted; new) | the `PROCESSING PROCEDURE` is an `XML_PROCESSING_PROCEDURE` flow edge, not dead code | nothing to mock |
| `DECLARE` | DECLARATIVES | `USE AFTER STANDARD ERROR PROCEDURE ON file`, `USE GLOBAL AFTER STANDARD EXCEPTION`, `USE ... ON OUTPUT`, `END DECLARATIVES`, sections after | clean (declaratives now modelled: `CobolSection.is_declarative`; the two marker lines no longer become paragraphs) | entry point is the first procedure *after* `END DECLARATIVES`; declarative sections are runtime entries, never dead or unreachable; `io-sequence` does not walk them inline (no false "WRITE before OPEN") | refused `UNSUPPORTED_DECLARATIVES` |
| `LESERV` | Language Environment services | `CEEDAYS`/`CEEDATE`/`CEEGMT`/`CEEMOUT`/`CEEGTST`/`CEEFRST`/`CEEHDLR`/`CEEHDLU`/`CEE3ABD`, feedback code, `PROCEDURE-POINTER` + `SET ... TO ENTRY`, `SET ADDRESS OF ... TO ptr`, intrinsic `FUNCTION`s | clean | every service and function reported; a `SET ADDRESS OF` LINKAGE item is referenced | scaffolds |
| `COMPDIR` | compiler directives | `CBL`/`PROCESS` option lines, `>>DEFINE` (hyphenated names), `>>IF`/`>>ELSE`/`>>END-IF`, `>>EVALUATE`/`>>WHEN`, `IS DEFINED`, `TITLE`, `EJECT`, `SKIP2`, `/` page eject, `D` debugging lines, `REPLACE ==:TAG:== BY ==...==`/`REPLACE OFF` | clean (conditional compilation now runs by default; `REPLACE` partial words; unknown `>>` directives blanked) | -- | nothing to mock |
| `MODERN63` | Enterprise COBOL 6.x data | `PIC U(n)`, `PIC U BYTE-LENGTH n`, `DYNAMIC LENGTH LIMIT n`, `PIC N ... NATIONAL`, `COMP-5`, 64-bit `COMP`, `COMP-1`/`COMP-2`, 31-digit `COMP-3`, `SIGN LEADING SEPARATE`, `CURRENCY SIGN ... WITH PICTURE SYMBOL`, `BLANK WHEN ZERO`, `JUSTIFIED`, `VOLATILE`, `X''`/`Z''`/`N''`/`U''` literals, `POINTER`/`POINTER-64`/`PROCEDURE-POINTER`/`FUNCTION-POINTER`/`INDEX`, `SYNC`, `66 RENAMES`, `OCCURS ... KEY ... INDEXED BY`, `OCCURS UNBOUNDED DEPENDING ON`, `ALLOCATE`/`FREE`, `SET ADDRESS OF`, `SEARCH ALL`, `EXIT PARAGRAPH`/`EXIT SECTION`/`EXIT PERFORM [CYCLE]`, `PERFORM WITH TEST AFTER`, `INSPECT CONVERTING`, class conditions | clean (`PIC U`, `BYTE-LENGTH`, `DYNAMIC LENGTH`, `VOLATILE`, `UNBOUNDED` new) | -- | nothing to mock |
| `COPYREPL` | copybook-heavy | `COPY ... REPLACING ==:PFX:== BY ==...==`, a copybook that COPYs another (no REPLACING -- the only nesting IBM allows), `COPY ... OF library SUPPRESS`, a PROCEDURE DIVISION `COPY`, `EXEC SQL INCLUDE SQLCA` / a DCLGEN member | clean | items from every member present; `dclgen-check` clean | scaffolds |

## Known limitations (documented, not silent)

* `SPECIAL-NAMES. DECIMAL-POINT IS COMMA` is recorded in metadata but the
  lexer does not honour it: a numeric literal written `3,14` misparses. The
  parser warns; mockymock refuses on that warning. (`BATCHSEQ` deliberately
  does not use it.)
* `D` debugging lines (column 7) are treated as comments whether or not
  `WITH DEBUGGING MODE` is on -- the compiler's own default without the
  `TEST` option.
* mockymock: CICS programs that use `DFHRESP`/`DFHVALUE`, programs whose
  default entry has its own `PROCEDURE DIVISION USING`, DECLARATIVES and
  multi-unit compilation units are refused with the codes above; those are
  mockymock design limits, each with its own honest refusal code, not parser
  gaps.
