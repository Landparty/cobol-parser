      *****************************************************************
      * Real-World COBOL Example: CALL Parameter Modes Complete
      * Demonstrates: All parameter passing mode combinations
      * Use Case: Data transformation pipeline with various param modes
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-PARAMETER-MODES-COMPLETE.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-INPUT-DATA.
           05  WS-INPUT-NUM1       PIC 9(5) VALUE 12345.
           05  WS-INPUT-NUM2       PIC 9(5) VALUE 67890.
           05  WS-INPUT-ALPHA      PIC X(20) VALUE 'TEST-DATA'.
           
       01  WS-OUTPUT-DATA.
           05  WS-OUTPUT-NUM       PIC 9(7).
           05  WS-OUTPUT-ALPHA     PIC X(30).
           05  WS-RESULT-CODE      PIC 99.
           
       01  WS-WORK-AREAS.
           05  WS-WORK-NUM         PIC 9(7) COMP-3.
           05  WS-WORK-ALPHA       PIC X(50).
           05  WS-TEMP-VALUE       PIC 9(5).
           
       01  WS-POINTERS.
           05  WS-DATA-POINTER     USAGE POINTER.
           05  WS-BUFFER-POINTER   USAGE POINTER.
           
       01  WS-LITERALS.
           05  WS-LITERAL-NUM      PIC 9(3) VALUE 100.
           05  WS-LITERAL-ALPHA    PIC X(10) VALUE 'CONSTANT'.
           
       PROCEDURE DIVISION.
       MAIN-PARAMETER-MODES.
           DISPLAY 'Parameter Passing Modes Demonstration'.
           PERFORM BY-REFERENCE-EXAMPLES.
           PERFORM BY-VALUE-EXAMPLES.
           PERFORM BY-CONTENT-EXAMPLES.
           PERFORM MIXED-MODE-EXAMPLES.
           PERFORM SPECIAL-CASES.
           STOP RUN.
           
       BY-REFERENCE-EXAMPLES.
      *    CALL with all BY REFERENCE parameters
           CALL 'ALL-REFERENCE' USING BY REFERENCE WS-INPUT-NUM1
                                      BY REFERENCE WS-INPUT-NUM2
                                      BY REFERENCE WS-OUTPUT-NUM.
           
      *    CALL with implicit REFERENCE (default mode)
           CALL 'IMPLICIT-REFERENCE' USING WS-INPUT-NUM1
                                           WS-INPUT-NUM2
                                           WS-OUTPUT-NUM.
           
      *    CALL with BY REFERENCE for modification
           CALL 'MODIFY-DATA' USING BY REFERENCE WS-WORK-NUM
                                    BY REFERENCE WS-WORK-ALPHA.
           
      *    CALL with BY REFERENCE and ADDRESS OF
           CALL 'POINTER-REFERENCE' USING BY REFERENCE ADDRESS OF WS-INPUT-DATA.
           
       BY-VALUE-EXAMPLES.
      *    CALL with all BY VALUE parameters
           CALL 'ALL-VALUE' USING BY VALUE WS-INPUT-NUM1
                                  BY VALUE WS-INPUT-NUM2
                                  BY VALUE WS-LITERAL-NUM.
           
      *    CALL with BY VALUE for read-only access
           CALL 'READ-ONLY-ACCESS' USING BY VALUE WS-INPUT-ALPHA
                                         BY VALUE WS-LITERAL-ALPHA.
           
      *    CALL with BY VALUE and literals
           CALL 'VALUE-WITH-LITERALS' USING BY VALUE 100
                                            BY VALUE 'LITERAL-STRING'.
           
      *    CALL with BY VALUE for numeric calculations
           CALL 'CALCULATE' USING BY VALUE WS-INPUT-NUM1
                                  BY VALUE WS-INPUT-NUM2
                                  BY REFERENCE WS-OUTPUT-NUM.
           
       BY-CONTENT-EXAMPLES.
      *    CALL with all BY CONTENT parameters
           CALL 'ALL-CONTENT' USING BY CONTENT WS-INPUT-NUM1
                                    BY CONTENT WS-INPUT-NUM2
                                    BY CONTENT WS-INPUT-ALPHA.
           
      *    CALL with BY CONTENT for safe passing
           CALL 'SAFE-PROCESSING' USING BY CONTENT WS-WORK-NUM
                                        BY CONTENT WS-WORK-ALPHA.
           
      *    CALL with BY CONTENT and literals
           CALL 'CONTENT-WITH-LITERALS' USING BY CONTENT 999
                                              BY CONTENT 'CONTENT-DATA'.
           
       MIXED-MODE-EXAMPLES.
      *    CALL with REFERENCE and VALUE mixed
           CALL 'MIXED-REF-VALUE' USING BY REFERENCE WS-OUTPUT-NUM
                                        BY VALUE WS-INPUT-NUM1
                                        BY VALUE WS-INPUT-NUM2.
           
      *    CALL with REFERENCE and CONTENT mixed
           CALL 'MIXED-REF-CONTENT' USING BY REFERENCE WS-OUTPUT-ALPHA
                                          BY CONTENT WS-INPUT-ALPHA.
           
      *    CALL with VALUE and CONTENT mixed
           CALL 'MIXED-VALUE-CONTENT' USING BY VALUE WS-INPUT-NUM1
                                            BY CONTENT WS-INPUT-ALPHA.
           
      *    CALL with all three modes
           CALL 'ALL-THREE-MODES' USING BY REFERENCE WS-OUTPUT-NUM
                                        BY VALUE WS-INPUT-NUM1
                                        BY CONTENT WS-INPUT-ALPHA.
           
      *    CALL with mode changes mid-parameter list
           CALL 'MODE-CHANGES' USING BY REFERENCE WS-OUTPUT-NUM
                                     BY REFERENCE WS-OUTPUT-ALPHA
                                     BY VALUE WS-INPUT-NUM1
                                     BY VALUE WS-INPUT-NUM2
                                     BY CONTENT WS-INPUT-ALPHA.
           
      *    CALL with alternating modes
           CALL 'ALTERNATING-MODES' USING BY REFERENCE WS-OUTPUT-NUM
                                          BY VALUE WS-INPUT-NUM1
                                          BY REFERENCE WS-OUTPUT-ALPHA
                                          BY VALUE WS-INPUT-NUM2
                                          BY REFERENCE WS-RESULT-CODE.
           
      *    CALL with complex mode pattern
           CALL 'COMPLEX-PATTERN' USING BY VALUE WS-INPUT-NUM1
                                        BY VALUE WS-INPUT-NUM2
                                        BY REFERENCE WS-WORK-NUM
                                        BY CONTENT WS-INPUT-ALPHA
                                        BY REFERENCE WS-OUTPUT-NUM
                                        BY CONTENT WS-LITERAL-ALPHA
                                        BY REFERENCE WS-RESULT-CODE.
           
       SPECIAL-CASES.
      *    CALL with OMITTED parameter
           CALL 'WITH-OMITTED' USING BY REFERENCE WS-OUTPUT-NUM
                                     OMITTED
                                     BY VALUE WS-INPUT-NUM1.
           
      *    CALL with literal parameters only
           CALL 'LITERALS-ONLY' USING 100
                                      'LITERAL-STRING'
                                      999.
           
      *    CALL with single parameter BY REFERENCE
           CALL 'SINGLE-REFERENCE' USING BY REFERENCE WS-OUTPUT-NUM.
           
      *    CALL with single parameter BY VALUE
           CALL 'SINGLE-VALUE' USING BY VALUE WS-INPUT-NUM1.
           
      *    CALL with single parameter BY CONTENT
           CALL 'SINGLE-CONTENT' USING BY CONTENT WS-INPUT-ALPHA.
           
      *    CALL with implicit mode then explicit mode
           CALL 'IMPLICIT-THEN-EXPLICIT' USING WS-INPUT-NUM1
                                               BY VALUE WS-INPUT-NUM2.
           
      *    CALL with explicit mode then implicit mode
           CALL 'EXPLICIT-THEN-IMPLICIT' USING BY VALUE WS-INPUT-NUM1
                                               WS-INPUT-NUM2.
           
      *    CALL with LENGTH OF parameter
           CALL 'WITH-LENGTH' USING BY VALUE LENGTH OF WS-INPUT-ALPHA
                                    BY REFERENCE WS-OUTPUT-NUM.
           
      *    CALL with SIZE parameter
           CALL 'WITH-SIZE' USING BY VALUE SIZE OF WS-INPUT-DATA
                                  BY REFERENCE WS-OUTPUT-NUM.
           
       END PROGRAM CALL-PARAMETER-MODES-COMPLETE.
