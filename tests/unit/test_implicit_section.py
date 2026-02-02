from cobolparser import parse_cobol, ErrorRecoveryMode


def get_statement_types(ast_root):
    types = []
    if not ast_root: return types
    for div in getattr(ast_root, 'divisions', []):
        if getattr(div, 'division_name', '') != 'PROCEDURE':
            continue
        # Collect statements from sections' paragraphs (new architecture)
        for sec in getattr(div, 'sections', []):
            for para in getattr(sec, 'paragraphs', []):
                for stmt in getattr(para, 'statements', []):
                    if getattr(stmt, 'node_type', '') == 'Statement':
                        types.append(stmt.statement_type)
        # Also check section.children for backwards compatibility (paragraphs are children)
        for sec in getattr(div, 'sections', []):
            for child in getattr(sec, 'children', []):
                # If child is a paragraph, get statements from it
                if hasattr(child, 'statements'):
                    for stmt in getattr(child, 'statements', []):
                        if getattr(stmt, 'node_type', '') == 'Statement' and stmt.statement_type not in types:
                            types.append(stmt.statement_type)
                # If child is direct statement (old architecture), add it
                elif getattr(child, 'node_type', '') == 'Statement':
                    types.append(child.statement_type)
    return types


def test_implicit_section_created_for_top_level_code():
    src = """000100 IDENTIFICATION DIVISION.\n000200 PROGRAM-ID. TOP1.\n000300 PROCEDURE DIVISION.\n000400     MOVE A TO B.\n"""
    result = parse_cobol(src, filename='<mem>', error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    kinds = get_statement_types(result.ast)
    assert 'MOVE' in kinds, f"Expected MOVE captured, got {kinds}"