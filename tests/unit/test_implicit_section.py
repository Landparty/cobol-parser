from cobolparser import parse_cobol, ErrorRecoveryMode


def get_statement_types(ast_root):
    types = []
    if not ast_root: return types
    for div in getattr(ast_root, 'divisions', []):
        if getattr(div, 'division_name', '') != 'PROCEDURE':
            continue
        for sec in getattr(div, 'sections', []):
            for child in getattr(sec, 'children', []):
                if getattr(child, 'node_type', '') == 'Statement':
                    types.append(child.statement_type)
    return types


def test_implicit_section_created_for_top_level_code():
    src = """000100 IDENTIFICATION DIVISION.\n000200 PROGRAM-ID. TOP1.\n000300 PROCEDURE DIVISION.\n000400     MOVE A TO B.\n"""
    result = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    kinds = get_statement_types(result.ast)
    assert 'MOVE' in kinds, f"Expected MOVE captured, got {kinds}"