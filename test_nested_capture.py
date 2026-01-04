"""Test to verify that statements within PERFORM THRU paragraphs are captured."""

import pytest
from cobolparser.parser import CobolParser
from cobolparser.plugins.core import ErrorRecoveryMode


def test_perform_thru_captures_nested_statements():
    """Verify that CALL statements within PERFORM THRU paragraph ranges are captured."""
    source = """
        IDENTIFICATION DIVISION.
        PROGRAM-ID. TEST-NESTED.
        
        PROCEDURE DIVISION.
        MAIN-PARA.
            PERFORM PARA-START THRU PARA-END.
            STOP RUN.
            
        PARA-START.
            DISPLAY 'Starting'.
            CALL 'SUBPROG1'.
            
        PARA-MIDDLE.
            CALL 'SUBPROG2'.
            DISPLAY 'Middle'.
            
        PARA-END.
            CALL 'SUBPROG3'.
            DISPLAY 'Ending'.
    """
    
    parser = CobolParser(error_recovery=ErrorRecoveryMode.COLLECT_ALL)
    result = parser.parse(source)
    
    assert result is not None
    print(f"Parse success: {result.success}")
    print(f"Errors: {result.errors}")
    
    if result.success and result.ast:
        # Get procedure division
        proc_div = result.ast.get_division("PROCEDURE")
        assert proc_div is not None, "PROCEDURE division should exist"
        
        # Get all sections (paragraphs)
        sections = proc_div.sections
        print(f"\nFound {len(sections)} sections/paragraphs:")
        
        for section in sections:
            print(f"\n  Section: {section.section_name}")
            print(f"  Children: {len(section.children)}")
            
            # Print all statements in this paragraph
            for child in section.children:
                print(f"    - {child.statement_type}: {child}")
                
                # Check if it's a CALL statement
                if hasattr(child, 'called_program'):
                    print(f"      Called program: {child.called_program}")
        
        # Verify PARA-START has CALL statement
        para_start = next((s for s in sections if s.section_name == "PARA-START"), None)
        assert para_start is not None, "PARA-START should exist"
        
        # Check for CALL statement in PARA-START
        call_statements = [c for c in para_start.children if hasattr(c, 'called_program')]
        print(f"\nCALL statements in PARA-START: {len(call_statements)}")
        
        if call_statements:
            print("✅ CALL statements within PERFORM THRU paragraphs ARE being captured!")
            for call in call_statements:
                print(f"  - {call.called_program}")
        else:
            print("❌ CALL statements within PERFORM THRU paragraphs are NOT being captured")
            
        # Also check PARA-MIDDLE and PARA-END
        para_middle = next((s for s in sections if s.section_name == "PARA-MIDDLE"), None)
        para_end = next((s for s in sections if s.section_name == "PARA-END"), None)
        
        if para_middle:
            middle_calls = [c for c in para_middle.children if hasattr(c, 'called_program')]
            print(f"\nCALL statements in PARA-MIDDLE: {len(middle_calls)}")
            
        if para_end:
            end_calls = [c for c in para_end.children if hasattr(c, 'called_program')]
            print(f"CALL statements in PARA-END: {len(end_calls)}")


if __name__ == "__main__":
    test_perform_thru_captures_nested_statements()
