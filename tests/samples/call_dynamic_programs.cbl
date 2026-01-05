      *****************************************************************
      * Real-World COBOL Example: Dynamic Program CALL
      * Demonstrates: CALL with variable program names
      * Use Case: Service registry and plugin architecture
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALL-DYNAMIC-PROGRAMS.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-PROGRAM-REGISTRY.
           05  WS-VALIDATION-SVC   PIC X(30) VALUE 'VALIDATION-SERVICE'.
           05  WS-PROCESSING-SVC   PIC X(30) VALUE 'PROCESSING-SERVICE'.
           05  WS-REPORTING-SVC    PIC X(30) VALUE 'REPORTING-SERVICE'.
           05  WS-AUDIT-SVC        PIC X(30) VALUE 'AUDIT-SERVICE'.
           
       01  WS-DYNAMIC-NAMES.
           05  WS-PROGRAM-NAME     PIC X(30).
           05  WS-SERVICE-NAME     PIC X(30).
           05  WS-MODULE-NAME      PIC X(30).
           
       01  WS-SERVICE-TABLE.
           05  WS-SERVICE-ENTRY OCCURS 10 TIMES.
               10  WS-SERVICE-ID   PIC 9(3).
               10  WS-SERVICE-PGM  PIC X(30).
           
       01  WS-CONTROL-DATA.
           05  WS-SERVICE-INDEX    PIC 9(3).
           05  WS-SERVICE-TYPE     PIC 9.
           05  WS-RESULT-CODE      PIC 99.
           
       01  WS-INPUT-DATA.
           05  WS-TRANSACTION-ID   PIC X(12).
           05  WS-AMOUNT           PIC 9(9)V99 COMP-3.
           
       PROCEDURE DIVISION.
       MAIN-DYNAMIC-CALLS.
           DISPLAY 'Dynamic Program CALL Demonstration'.
           PERFORM INITIALIZE-REGISTRY.
           PERFORM SIMPLE-DYNAMIC-CALLS.
           PERFORM COMPUTED-PROGRAM-NAMES.
           PERFORM TABLE-DRIVEN-CALLS.
           PERFORM CONDITIONAL-DYNAMIC-CALLS.
           STOP RUN.
           
       INITIALIZE-REGISTRY.
      *    Initialize service registry table
           MOVE 1 TO WS-SERVICE-ID(1).
           MOVE 'VALIDATION-SERVICE' TO WS-SERVICE-PGM(1).
           MOVE 2 TO WS-SERVICE-ID(2).
           MOVE 'PROCESSING-SERVICE' TO WS-SERVICE-PGM(2).
           MOVE 3 TO WS-SERVICE-ID(3).
           MOVE 'REPORTING-SERVICE' TO WS-SERVICE-PGM(3).
           
       SIMPLE-DYNAMIC-CALLS.
      *    CALL with variable program name
           MOVE 'DYNAMIC-SERVICE' TO WS-PROGRAM-NAME.
           CALL WS-PROGRAM-NAME USING WS-TRANSACTION-ID.
           
      *    CALL with variable from registry
           CALL WS-VALIDATION-SVC USING WS-TRANSACTION-ID
                                        WS-AMOUNT.
           
      *    CALL with variable and multiple parameters
           MOVE 'MULTI-PARAM-SERVICE' TO WS-SERVICE-NAME.
           CALL WS-SERVICE-NAME USING WS-TRANSACTION-ID
                                      WS-AMOUNT
                                      WS-RESULT-CODE.
           
      *    CALL with variable and BY REFERENCE
           CALL WS-PROCESSING-SVC USING BY REFERENCE WS-AMOUNT
                                        BY REFERENCE WS-RESULT-CODE.
           
      *    CALL with variable and RETURNING
           CALL WS-AUDIT-SVC USING WS-TRANSACTION-ID
               RETURNING WS-RESULT-CODE.
           
       COMPUTED-PROGRAM-NAMES.
      *    CALL with computed program name based on type
           EVALUATE WS-SERVICE-TYPE
               WHEN 1
                   MOVE 'TYPE-ONE-SERVICE' TO WS-PROGRAM-NAME
               WHEN 2
                   MOVE 'TYPE-TWO-SERVICE' TO WS-PROGRAM-NAME
               WHEN OTHER
                   MOVE 'DEFAULT-SERVICE' TO WS-PROGRAM-NAME
           END-EVALUATE.
           CALL WS-PROGRAM-NAME USING WS-TRANSACTION-ID.
           
      *    CALL with program name from condition
           IF WS-AMOUNT > 1000.00
               MOVE 'HIGH-VALUE-SERVICE' TO WS-SERVICE-NAME
           ELSE
               MOVE 'STANDARD-SERVICE' TO WS-SERVICE-NAME
           END-IF.
           CALL WS-SERVICE-NAME USING WS-AMOUNT.
           
      *    CALL with concatenated program name
           STRING 'SERVICE-' DELIMITED BY SIZE
                  'PROCESSOR' DELIMITED BY SIZE
                  INTO WS-PROGRAM-NAME
           END-STRING.
           CALL WS-PROGRAM-NAME USING WS-TRANSACTION-ID.
           
       TABLE-DRIVEN-CALLS.
      *    CALL with program name from table
           MOVE 1 TO WS-SERVICE-INDEX.
           CALL WS-SERVICE-PGM(WS-SERVICE-INDEX) 
                USING WS-TRANSACTION-ID.
           
      *    CALL with program name from table in loop
           PERFORM VARYING WS-SERVICE-INDEX FROM 1 BY 1
               UNTIL WS-SERVICE-INDEX > 3
               CALL WS-SERVICE-PGM(WS-SERVICE-INDEX)
                    USING WS-TRANSACTION-ID
                          WS-AMOUNT
           END-PERFORM.
           
      *    CALL with program name lookup
           PERFORM VARYING WS-SERVICE-INDEX FROM 1 BY 1
               UNTIL WS-SERVICE-INDEX > 10
                   OR WS-SERVICE-ID(WS-SERVICE-INDEX) = 2
               CONTINUE
           END-PERFORM.
           IF WS-SERVICE-INDEX <= 10
               CALL WS-SERVICE-PGM(WS-SERVICE-INDEX)
                    USING WS-TRANSACTION-ID
           END-IF.
           
       CONDITIONAL-DYNAMIC-CALLS.
      *    CALL with dynamic name and exception handler
           MOVE 'RISKY-SERVICE' TO WS-PROGRAM-NAME.
           CALL WS-PROGRAM-NAME USING WS-TRANSACTION-ID
               ON EXCEPTION
                   DISPLAY 'Dynamic service failed'
                   MOVE 'FALLBACK-SERVICE' TO WS-PROGRAM-NAME
                   CALL WS-PROGRAM-NAME USING WS-TRANSACTION-ID
               END-CALL.
           
      *    CALL with fallback logic
           MOVE 'PRIMARY-SERVICE' TO WS-SERVICE-NAME.
           CALL WS-SERVICE-NAME USING WS-TRANSACTION-ID
               ON EXCEPTION
                   MOVE 'SECONDARY-SERVICE' TO WS-SERVICE-NAME
                   CALL WS-SERVICE-NAME USING WS-TRANSACTION-ID
                       ON EXCEPTION
                           MOVE 'TERTIARY-SERVICE' TO WS-SERVICE-NAME
                           CALL WS-SERVICE-NAME USING WS-TRANSACTION-ID
                       END-CALL
               END-CALL.
           
      *    CALL with dynamic name in nested IF
           IF WS-AMOUNT > 5000.00
               IF WS-SERVICE-TYPE = 1
                   MOVE 'VIP-HIGH-VALUE' TO WS-PROGRAM-NAME
               ELSE
                   MOVE 'STANDARD-HIGH-VALUE' TO WS-PROGRAM-NAME
               END-IF
               CALL WS-PROGRAM-NAME USING WS-AMOUNT
           END-IF.
           
      *    CALL with service registry pattern
           MOVE 'REGISTRY-LOOKUP' TO WS-MODULE-NAME.
           CALL WS-MODULE-NAME USING WS-SERVICE-TYPE
               RETURNING WS-PROGRAM-NAME.
           CALL WS-PROGRAM-NAME USING WS-TRANSACTION-ID.
           
       END PROGRAM CALL-DYNAMIC-PROGRAMS.
