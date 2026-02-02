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
    
    # Check paragraphs first
    for para in proc.paragraphs:
        for stmt in para.statements:
            if isinstance(stmt, EvaluateStatement):
                evals.append(stmt)
    
    # Check sections and their paragraphs
    if not evals:
        for section in proc.sections:
            # Check section children directly
            for child in section.children:
                if isinstance(child, EvaluateStatement):
                    evals.append(child)
            # Check section paragraphs  
            if hasattr(section, 'paragraphs'):
                for para in section.paragraphs:
                    for stmt in para.statements:
                        if isinstance(stmt, EvaluateStatement):
                            evals.append(stmt)
    
    # Expect three EVALUATE statements in the sample
    assert len(evals) == 3, f"Expected 3 EVALUATE statements, found {len(evals)}"
    # Check that WHEN OTHER exists in each
    assert all(ev.default_when is not None for ev in evals)
