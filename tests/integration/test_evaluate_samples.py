import pathlib

from cobolparser import CobolParser
from cobolparser.models.statements import EvaluateStatement  # type: ignore

SAMPLES_DIR = pathlib.Path(__file__).parent.parent / "samples"


def test_evaluate_variants_sample_file():
    sample_path = SAMPLES_DIR / "evaluate_variants.cbl"
    source = sample_path.read_text()
    parser = CobolParser()
    result = parser.parse(source)
    assert result.ast is not None
    proc = result.ast.get_division("PROCEDURE")
    assert proc is not None
    evals = []
    # Prefer paragraphs if present
    for para in proc.paragraphs:
        for stmt in para.statements:
            if isinstance(stmt, EvaluateStatement):
                evals.append(stmt)
    if not evals:
        # Fallback to section children (implicit section when no paragraphs exist)
        for section in proc.sections:
            for child in section.children:
                if isinstance(child, EvaluateStatement):
                    evals.append(child)
    # Expect three EVALUATE statements in the sample
    assert len(evals) == 3
    # Check that WHEN OTHER exists in each
    assert all(ev.default_when is not None for ev in evals)
