"""
Complexity and maintainability metrics for COBOL programs.

Computes per-paragraph metrics including:
- Cyclomatic complexity (McCabe)
- Halstead software science metrics (volume, difficulty, effort)
- Maximum nesting depth
- Fan-in / fan-out (using the control flow graph)
- "God paragraph" detection
- Copybook coupling

Output: JSON (to_json) and self-contained HTML report (to_html).
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from typing import Any

from ..models.ast_base import SourceLocation
from ..models.program import CobolProgram
from ..models.statements.control import (
    EvaluateStatement,
    GoStatement,
    IfStatement,
    PerformStatement,
    SearchStatement,
)
from ..models.statements.misc import CopyStatement

# ------------------------------------------------------------------ #
# Thresholds for "god paragraph" detection
# ------------------------------------------------------------------ #
GOD_PARAGRAPH_STATEMENTS: int = 50
GOD_PARAGRAPH_COMPLEXITY: int = 10
GOD_PARAGRAPH_NESTING: int = 5
GOD_PARAGRAPH_FAN_OUT: int = 8


@dataclass
class HalsteadMetrics:
    """Halstead software science metrics for a single paragraph.

    Operators are COBOL statement verbs (MOVE, ADD, COMPUTE …) plus
    arithmetic/comparison symbols extracted from expressions.
    Operands are variable names and literals from statement operand lists.
    """

    n1: int = 0  # distinct operators
    n2: int = 0  # distinct operands
    N1: int = 0  # total operator occurrences
    N2: int = 0  # total operand occurrences

    @property
    def vocabulary(self) -> int:
        return self.n1 + self.n2

    @property
    def length(self) -> int:
        return self.N1 + self.N2

    @property
    def volume(self) -> float:
        v = self.vocabulary
        return (self.N1 + self.N2) * math.log2(v) if v > 1 else 0.0

    @property
    def difficulty(self) -> float:
        return (self.n1 / 2) * (self.N2 / self.n2) if self.n2 > 0 else 0.0

    @property
    def effort(self) -> float:
        return self.difficulty * self.volume

    @property
    def time_to_program(self) -> float:
        """Estimated programming time in seconds (Halstead's formula)."""
        return self.effort / 18

    @property
    def delivered_bugs(self) -> float:
        """Estimated number of bugs (Halstead's formula)."""
        return self.volume / 3000

    def to_dict(self) -> dict[str, Any]:
        return {
            "n1": self.n1,
            "n2": self.n2,
            "N1": self.N1,
            "N2": self.N2,
            "vocabulary": self.vocabulary,
            "length": self.length,
            "volume": round(self.volume, 2),
            "difficulty": round(self.difficulty, 2),
            "effort": round(self.effort, 2),
            "time_to_program_seconds": round(self.time_to_program, 2),
            "delivered_bugs": round(self.delivered_bugs, 4),
        }


@dataclass
class ParagraphMetrics:
    """Complexity metrics for a single COBOL paragraph."""

    paragraph_name: str
    section_name: str | None
    location: SourceLocation
    statement_count: int = 0
    line_count: int = 0
    cyclomatic_complexity: int = 1
    max_nesting_depth: int = 0
    fan_in: int = 0
    fan_out: int = 0
    halstead: HalsteadMetrics = field(default_factory=HalsteadMetrics)
    is_god_paragraph: bool = False
    god_paragraph_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "paragraph_name": self.paragraph_name,
            "location": self.location.to_dict(),
            "statement_count": self.statement_count,
            "line_count": self.line_count,
            "cyclomatic_complexity": self.cyclomatic_complexity,
            "max_nesting_depth": self.max_nesting_depth,
            "fan_in": self.fan_in,
            "fan_out": self.fan_out,
            "halstead": self.halstead.to_dict(),
            "is_god_paragraph": self.is_god_paragraph,
        }
        if self.section_name:
            result["section_name"] = self.section_name
        if self.god_paragraph_reasons:
            result["god_paragraph_reasons"] = self.god_paragraph_reasons
        return result


@dataclass
class CopybookCoupling:
    """Copybook coupling metric: how many times a copybook is referenced."""

    copybook_name: str
    reference_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "copybook_name": self.copybook_name,
            "reference_count": self.reference_count,
        }


@dataclass
class ComplexityReport:
    """Complete complexity and maintainability report for a COBOL program."""

    program_name: str
    total_paragraphs: int = 0
    avg_cyclomatic_complexity: float = 0.0
    max_cyclomatic_complexity: int = 0
    avg_statement_count: float = 0.0
    total_god_paragraphs: int = 0
    paragraph_metrics: list[ParagraphMetrics] = field(default_factory=list)
    copybook_coupling: list[CopybookCoupling] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "program_name": self.program_name,
            "summary": {
                "total_paragraphs": self.total_paragraphs,
                "avg_cyclomatic_complexity": round(
                    self.avg_cyclomatic_complexity, 2
                ),
                "max_cyclomatic_complexity": self.max_cyclomatic_complexity,
                "avg_statement_count": round(self.avg_statement_count, 2),
                "total_god_paragraphs": self.total_god_paragraphs,
                "total_copybooks": len(self.copybook_coupling),
            },
            "paragraph_metrics": [m.to_dict() for m in self.paragraph_metrics],
            "copybook_coupling": [c.to_dict() for c in self.copybook_coupling],
        }

    def to_json(self, indent: int = 2) -> str:
        """Serialize the report to a JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_html(self) -> str:
        """Generate a self-contained HTML complexity report."""
        return _render_html(self)


class ComplexityAnalyzer:
    """Analyzer that computes complexity and maintainability metrics per paragraph.

    Accepts an optional pre-built ProgramFlowReport to avoid redundant analysis.
    If not provided, ProgramFlowAnalyzer is run internally.

    Example:
        ```python
        from cobolparser import parse_cobol
        from cobolparser.analysis.complexity_metrics import ComplexityAnalyzer

        result = parse_cobol(source)
        report = ComplexityAnalyzer().analyze(result.ast)
        print(report.to_json())
        with open("report.html", "w") as f:
            f.write(report.to_html())
        ```
    """

    def analyze(
        self,
        ast: CobolProgram,
        flow_report: Any = None,
    ) -> ComplexityReport:
        """Compute complexity metrics for every paragraph in the program.

        Args:
            ast: The parsed COBOL program AST.
            flow_report: Optional ProgramFlowReport.  If None, one is built
                internally via ProgramFlowAnalyzer.

        Returns:
            A ComplexityReport with per-paragraph metrics and summary statistics.
        """
        if flow_report is None:
            from .program_flow import ProgramFlowAnalyzer

            flow_report = ProgramFlowAnalyzer().analyze(ast)

        fan_out_targets, fan_in_sources = _build_fan_maps(flow_report)

        paragraph_metrics: list[ParagraphMetrics] = []

        proc_div = ast.procedure_division
        if proc_div is not None:
            for section in proc_div._sections.values():
                section_name = section.section_name
                for para in section.paragraphs:
                    m = _analyze_paragraph(
                        para,
                        section_name=section_name,
                        fan_in=len(
                            fan_in_sources.get(
                                (para.paragraph_name or "").upper(), set()
                            )
                        ),
                        fan_out=len(
                            fan_out_targets.get(
                                (para.paragraph_name or "").upper(), set()
                            )
                        ),
                    )
                    paragraph_metrics.append(m)

            for para in proc_div.paragraphs:
                m = _analyze_paragraph(
                    para,
                    section_name=None,
                    fan_in=len(
                        fan_in_sources.get(
                            (para.paragraph_name or "").upper(), set()
                        )
                    ),
                    fan_out=len(
                        fan_out_targets.get(
                            (para.paragraph_name or "").upper(), set()
                        )
                    ),
                )
                paragraph_metrics.append(m)

        copybook_coupling = _collect_copybook_coupling(ast)

        report = ComplexityReport(program_name=ast.program_name)
        report.paragraph_metrics = paragraph_metrics
        report.copybook_coupling = copybook_coupling
        report.total_paragraphs = len(paragraph_metrics)
        report.total_god_paragraphs = sum(
            1 for m in paragraph_metrics if m.is_god_paragraph
        )
        if paragraph_metrics:
            report.avg_cyclomatic_complexity = sum(
                m.cyclomatic_complexity for m in paragraph_metrics
            ) / len(paragraph_metrics)
            report.max_cyclomatic_complexity = max(
                m.cyclomatic_complexity for m in paragraph_metrics
            )
            report.avg_statement_count = sum(
                m.statement_count for m in paragraph_metrics
            ) / len(paragraph_metrics)
        return report


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #


def _build_fan_maps(
    flow_report: Any,
) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Return (fan_out_targets, fan_in_sources) dicts from a ProgramFlowReport.

    Only PERFORM and PERFORM_THRU edges are counted; FALL_THROUGH and CALL
    edges are excluded so the metrics reflect deliberate paragraph references.
    """
    try:
        from .program_flow import FlowEdgeType
    except ImportError:
        return {}, {}

    fan_out: dict[str, set[str]] = {}
    fan_in: dict[str, set[str]] = {}

    for edge in getattr(flow_report, "edges", []):
        etype = getattr(edge, "edge_type", None)
        if etype not in (FlowEdgeType.PERFORM, FlowEdgeType.PERFORM_THRU):
            continue
        src = edge.source
        tgt = edge.target
        fan_out.setdefault(src, set()).add(tgt)
        fan_in.setdefault(tgt, set()).add(src)

    return fan_out, fan_in


def _analyze_paragraph(
    para: Any,
    section_name: str | None,
    fan_in: int,
    fan_out: int,
) -> ParagraphMetrics:
    """Compute all metrics for a single CobolParagraph."""
    name = getattr(para, "paragraph_name", "") or ""
    location = getattr(para, "location", SourceLocation(0, 1))
    stmts = list(getattr(para, "statements", []))

    metrics = ParagraphMetrics(
        paragraph_name=name,
        section_name=section_name,
        location=location,
        fan_in=fan_in,
        fan_out=fan_out,
    )

    operators: dict[str, int] = {}
    operands: dict[str, int] = {}

    _scan_statements(stmts, metrics, operators, operands, nesting=0)

    metrics.halstead = _finalize_halstead(operators, operands)
    _classify_god_paragraph(metrics)

    # Estimate line count
    if stmts:
        last_loc = getattr(stmts[-1], "location", None)
        if last_loc and location.line > 0:
            metrics.line_count = max(1, last_loc.line - location.line + 1)
        else:
            metrics.line_count = metrics.statement_count
    else:
        metrics.line_count = 1

    return metrics


def _scan_statements(
    stmts: list[Any],
    metrics: ParagraphMetrics,
    operators: dict[str, int],
    operands: dict[str, int],
    nesting: int,
) -> None:
    """Recursively scan statements, updating metrics, operators, and operands."""
    for stmt in stmts:
        if not hasattr(stmt, "node_type"):
            continue

        metrics.statement_count += 1
        metrics.max_nesting_depth = max(metrics.max_nesting_depth, nesting)

        stype = getattr(stmt, "statement_type", None)
        if stype:
            operators[stype] = operators.get(stype, 0) + 1

        for op in getattr(stmt, "operands", []):
            if op:
                operands[op.upper()] = operands.get(op.upper(), 0) + 1

        if isinstance(stmt, IfStatement):
            metrics.cyclomatic_complexity += 1
            _scan_statements(
                stmt.then_statements, metrics, operators, operands, nesting + 1
            )
            _scan_statements(
                stmt.else_statements, metrics, operators, operands, nesting + 1
            )

        elif isinstance(stmt, EvaluateStatement):
            # Each WHEN clause is a decision point
            metrics.cyclomatic_complexity += len(stmt.when_clauses)
            for wc in stmt.when_clauses:
                _scan_statements(
                    wc.statements, metrics, operators, operands, nesting + 1
                )
            if stmt.default_when:
                _scan_statements(
                    stmt.default_when.statements,
                    metrics,
                    operators,
                    operands,
                    nesting + 1,
                )

        elif isinstance(stmt, PerformStatement):
            if stmt.perform_type in ("UNTIL", "VARYING"):
                metrics.cyclomatic_complexity += 1
                # Extract arithmetic operators from UNTIL/VARYING conditions
                if stmt.until_condition is not None:
                    cond_text = str(stmt.until_condition)
                    for sym in re.findall(r"[+\-*/=><]", cond_text):
                        operators[sym] = operators.get(sym, 0) + 1
            if stmt.inline_statements:
                _scan_statements(
                    stmt.inline_statements,
                    metrics,
                    operators,
                    operands,
                    nesting + 1,
                )

        elif isinstance(stmt, SearchStatement):
            metrics.cyclomatic_complexity += len(stmt.when_clauses)
            for wc_dict in stmt.when_clauses:
                _scan_statements(
                    wc_dict.get("statements", []),
                    metrics,
                    operators,
                    operands,
                    nesting + 1,
                )
            if stmt.at_end_clause:
                _scan_statements(
                    stmt.at_end_clause, metrics, operators, operands, nesting + 1
                )

        elif isinstance(stmt, GoStatement):
            if stmt.depending_on_variable:
                # Computed GO TO: each distinct target is a branch
                targets = [
                    op
                    for op in getattr(stmt, "operands", [])
                    if op.upper() != (stmt.depending_on_variable or "").upper()
                ]
                metrics.cyclomatic_complexity += max(len(targets), 1)

        # Collect arithmetic/comparison operators from COMPUTE expressions
        expr = getattr(stmt, "expression", None)
        if expr is not None:
            expr_text = str(expr)
            for sym in re.findall(r"[+\-*/]", expr_text):
                operators[sym] = operators.get(sym, 0) + 1


def _finalize_halstead(
    operators: dict[str, int], operands: dict[str, int]
) -> HalsteadMetrics:
    return HalsteadMetrics(
        n1=len(operators),
        n2=len(operands),
        N1=sum(operators.values()),
        N2=sum(operands.values()),
    )


def _classify_god_paragraph(metrics: ParagraphMetrics) -> None:
    reasons: list[str] = []
    if metrics.statement_count >= GOD_PARAGRAPH_STATEMENTS:
        reasons.append(
            f"statement count {metrics.statement_count}"
            f" >= {GOD_PARAGRAPH_STATEMENTS}"
        )
    if metrics.cyclomatic_complexity >= GOD_PARAGRAPH_COMPLEXITY:
        reasons.append(
            f"cyclomatic complexity {metrics.cyclomatic_complexity}"
            f" >= {GOD_PARAGRAPH_COMPLEXITY}"
        )
    if metrics.max_nesting_depth >= GOD_PARAGRAPH_NESTING:
        reasons.append(
            f"nesting depth {metrics.max_nesting_depth}"
            f" >= {GOD_PARAGRAPH_NESTING}"
        )
    if metrics.fan_out >= GOD_PARAGRAPH_FAN_OUT:
        reasons.append(f"fan-out {metrics.fan_out} >= {GOD_PARAGRAPH_FAN_OUT}")
    metrics.is_god_paragraph = bool(reasons)
    metrics.god_paragraph_reasons = reasons


def _collect_copybook_coupling(ast: CobolProgram) -> list[CopybookCoupling]:
    counts: dict[str, int] = {}
    for stmt in ast.get_all_statements():
        if isinstance(stmt, CopyStatement):
            name = stmt.copybook_name
            if name:
                key = name.upper()
                counts[key] = counts.get(key, 0) + 1
    return [
        CopybookCoupling(copybook_name=name, reference_count=count)
        for name, count in sorted(counts.items(), key=lambda x: -x[1])
    ]


# ------------------------------------------------------------------ #
# HTML report renderer
# ------------------------------------------------------------------ #

_CSS = """\
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
     background:#f5f7fa;color:#333;padding:20px}
h1{font-size:1.6rem;margin-bottom:4px}
.subtitle{color:#666;font-size:.9rem;margin-bottom:20px}
.cards{display:flex;gap:12px;flex-wrap:wrap;margin-bottom:24px}
.card{background:#fff;border-radius:8px;padding:14px 20px;
      box-shadow:0 1px 4px rgba(0,0,0,.1);min-width:140px}
.card-label{font-size:.75rem;text-transform:uppercase;
             letter-spacing:.05em;color:#888}
.card-value{font-size:1.8rem;font-weight:700;margin-top:2px}
.card-value.warn{color:#d97706}
.card-value.danger{color:#dc2626}
h2{font-size:1.1rem;margin:20px 0 8px;border-bottom:2px solid #e5e7eb;
   padding-bottom:4px}
table{width:100%;border-collapse:collapse;background:#fff;
      border-radius:8px;overflow:hidden;
      box-shadow:0 1px 4px rgba(0,0,0,.1);font-size:.85rem}
th{background:#1e293b;color:#fff;padding:10px 8px;text-align:left;
   cursor:pointer;user-select:none;white-space:nowrap}
th:hover{background:#334155}
td{padding:8px;border-bottom:1px solid #f1f5f9;vertical-align:top}
tr:last-child td{border-bottom:none}
tr:hover td{background:#f8fafc}
.low{background:#dcfce7}
.med{background:#fef9c3}
.high{background:#fee2e2}
.god-row td{background:#fef2f2!important;font-weight:600}
.god-row:hover td{background:#fde8e8!important}
.badge{display:inline-block;padding:2px 8px;border-radius:9999px;
       font-size:.75rem;font-weight:600}
.badge-ok{background:#dcfce7;color:#166534}
.badge-warn{background:#fef9c3;color:#854d0e}
.badge-bad{background:#fee2e2;color:#991b1b}
.badge-god{background:#dc2626;color:#fff}
details{margin-top:4px}
summary{cursor:pointer;color:#dc2626;font-size:.8rem}
.copy-table{max-width:400px}
"""

_JS = """\
function sortTable(tblId,col,isNum){
  var t=document.getElementById(tblId),r=Array.from(t.tBodies[0].rows);
  var asc=t.dataset.sortCol==col&&t.dataset.sortAsc=='1';
  r.sort(function(a,b){
    var x=a.cells[col].textContent.trim();
    var y=b.cells[col].textContent.trim();
    if(isNum){return asc?(+y)-(+x):(+x)-(+y);}
    return asc?y.localeCompare(x):x.localeCompare(y);
  });
  r.forEach(function(row){t.tBodies[0].appendChild(row);});
  t.dataset.sortCol=col;t.dataset.sortAsc=asc?'0':'1';
}
"""


def _complexity_class(cc: int) -> str:
    if cc < 5:
        return "low"
    if cc < 10:
        return "med"
    return "high"


def _badge(cc: int) -> str:
    if cc < 5:
        cls, label = "badge-ok", "low"
    elif cc < 10:
        cls, label = "badge-warn", "medium"
    else:
        cls, label = "badge-bad", "high"
    return f'<span class="badge {cls}">{label}</span>'


def _esc(s: object) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _render_html(report: ComplexityReport) -> str:
    # Summary cards
    avg_cc = round(report.avg_cyclomatic_complexity, 1)
    avg_cc_cls = "danger" if avg_cc >= 10 else ("warn" if avg_cc >= 5 else "")
    max_cc_cls = "danger" if report.max_cyclomatic_complexity >= 10 else (
        "warn" if report.max_cyclomatic_complexity >= 5 else ""
    )
    god_cls = "danger" if report.total_god_paragraphs > 0 else ""

    cards_html = f"""
    <div class="cards">
      <div class="card">
        <div class="card-label">Paragraphs</div>
        <div class="card-value">{report.total_paragraphs}</div>
      </div>
      <div class="card">
        <div class="card-label">Avg Complexity</div>
        <div class="card-value {avg_cc_cls}">{avg_cc}</div>
      </div>
      <div class="card">
        <div class="card-label">Max Complexity</div>
        <div class="card-value {max_cc_cls}">{report.max_cyclomatic_complexity}</div>
      </div>
      <div class="card">
        <div class="card-label">God Paragraphs</div>
        <div class="card-value {god_cls}">{report.total_god_paragraphs}</div>
      </div>
      <div class="card">
        <div class="card-label">Copybooks</div>
        <div class="card-value">{len(report.copybook_coupling)}</div>
      </div>
    </div>"""

    # Paragraph table
    col_defs = [
        ("Paragraph", False),
        ("Section", False),
        ("Stmts", True),
        ("Lines", True),
        ("Complexity", True),
        ("Nesting", True),
        ("Fan-In", True),
        ("Fan-Out", True),
        ("Vol", True),
        ("Effort", True),
        ("Level", False),
        ("God?", False),
    ]
    header_cells = "".join(
        f'<th onclick="sortTable(\'para-table\',{i},{str(num).lower()})">'
        f"{_esc(label)}</th>"
        for i, (label, num) in enumerate(col_defs)
    )

    rows_html = []
    for m in report.paragraph_metrics:
        row_cls = "god-row" if m.is_god_paragraph else _complexity_class(
            m.cyclomatic_complexity
        )
        god_cell = (
            '<span class="badge badge-god">GOD</span>'
            if m.is_god_paragraph
            else "&nbsp;"
        )
        reasons_html = ""
        if m.god_paragraph_reasons:
            items = "".join(
                f"<li>{_esc(r)}</li>" for r in m.god_paragraph_reasons
            )
            reasons_html = (
                f'<details><summary>reasons</summary><ul>{items}</ul></details>'
            )
        rows_html.append(
            f"<tr class='{row_cls}'>"
            f"<td>{_esc(m.paragraph_name)}{reasons_html}</td>"
            f"<td>{_esc(m.section_name or '')}</td>"
            f"<td>{m.statement_count}</td>"
            f"<td>{m.line_count}</td>"
            f"<td>{m.cyclomatic_complexity}</td>"
            f"<td>{m.max_nesting_depth}</td>"
            f"<td>{m.fan_in}</td>"
            f"<td>{m.fan_out}</td>"
            f"<td>{round(m.halstead.volume, 1)}</td>"
            f"<td>{round(m.halstead.effort, 1)}</td>"
            f"<td>{_badge(m.cyclomatic_complexity)}</td>"
            f"<td>{god_cell}</td>"
            "</tr>"
        )

    para_table = (
        f'<table id="para-table" data-sort-col="" data-sort-asc="0">'
        f"<thead><tr>{header_cells}</tr></thead>"
        f"<tbody>{''.join(rows_html)}</tbody></table>"
    )

    # Copybook coupling table
    if report.copybook_coupling:
        cb_rows = "".join(
            f"<tr><td>{_esc(c.copybook_name)}</td>"
            f"<td>{c.reference_count}</td></tr>"
            for c in report.copybook_coupling
        )
        cb_table = (
            '<table class="copy-table">'
            "<thead><tr><th>Copybook</th><th>References</th></tr></thead>"
            f"<tbody>{cb_rows}</tbody></table>"
        )
    else:
        cb_table = "<p style='color:#888'>No COPY statements found.</p>"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Complexity Report: {_esc(report.program_name)}</title>
<style>{_CSS}</style>
</head>
<body>
<h1>Complexity Report</h1>
<p class="subtitle">Program: <strong>{_esc(report.program_name)}</strong></p>
{cards_html}
<h2>Paragraph Metrics</h2>
<p style="font-size:.8rem;color:#888;margin-bottom:6px">
  Click column headers to sort. Rows are colour-coded by complexity:
  <span class="badge badge-ok">low</span> &lt;5 &nbsp;
  <span class="badge badge-warn">medium</span> 5–9 &nbsp;
  <span class="badge badge-bad">high</span> &ge;10.
</p>
{para_table}
<h2>Copybook Coupling</h2>
{cb_table}
<script>{_JS}</script>
</body>
</html>"""
