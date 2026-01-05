
import sys
import os
import platform
from cobolparser import parse_cobol

def verify_environment():
    print(f"Checking environment...")
    print(f"OS: {platform.system()} {platform.release()}")
    print(f"Python: {sys.version}")
    
    # Check if we are on Mac (darwin)
    if sys.platform == 'darwin':
        print("✅ Correctly identified macOS environment.")
    else:
        print(f"ℹ️ Currently running on {sys.platform}. This script will still verify parser functionality.")

def verify_parser():
    print("\nRunning parser verification...")
    
    # Simple Hello World COBOL program
    cobol_code = """
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HELLO-MAC.
       PROCEDURE DIVISION.
           DISPLAY "Hello from macOS Compatibility Check".
           STOP RUN.
    """
    
    try:
        result = parse_cobol(cobol_code, filename="hello_mac.cob")
        
        if result.success:
            print("✅ Parser successfully processed COBOL code.")
            if result.ast and result.ast.program_name == "HELLO-MAC":
                print("✅ AST correctly generated.")
                return True
            else:
                print("❌ AST verification failed.")
                return False
        else:
            print("❌ Parsing failed with errors:")
            for error in result.errors:
                print(f"  - {error}")
            return False
            
    except Exception as e:
        print(f"❌ Exception occurred during parsing: {e}")
        return False

if __name__ == "__main__":
    print("=== COBOL Parser Mac Compatibility Verification ===\n")
    verify_environment()
    success = verify_parser()
    
    if success:
        print("\n✅ VERIFICATION SUCCESSFUL: cobol-parser is working correctly!")
        sys.exit(0)
    else:
        print("\n❌ VERIFICATION FAILED: Please check the errors above.")
        sys.exit(1)
