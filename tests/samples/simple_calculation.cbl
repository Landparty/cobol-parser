      *****************************************************************
      * IBM Enterprise COBOL Sample - Simple Calculation Program
      * Demonstrates: Basic arithmetic, PERFORM loops, conditionals
      * Features: IBM COBOL syntax, COMP-3 fields, structured logic
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CALC-DEMO.
       
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-NUMBERS.
           05  WS-NUM1             PIC 9(5)V99 COMP-3 VALUE 123.45.
           05  WS-NUM2             PIC 9(5)V99 COMP-3 VALUE 67.89.
           05  WS-RESULT           PIC 9(6)V99 COMP-3.
           
       01  WS-COUNTER              PIC 9(3) VALUE 1.
       01  WS-MAX-COUNT            PIC 9(3) VALUE 10.
       
       01  WS-DISPLAY-FIELDS.
           05  WS-DISPLAY-NUM1     PIC ZZZ,ZZ9.99.
           05  WS-DISPLAY-NUM2     PIC ZZZ,ZZ9.99. 
           05  WS-DISPLAY-RESULT   PIC Z,ZZZ,ZZ9.99.
       
       PROCEDURE DIVISION.
       MAIN-LOGIC.
           DISPLAY 'Starting Calculation Demo'
           PERFORM BASIC-CALCULATIONS
           PERFORM LOOP-CALCULATIONS  
           DISPLAY 'Calculation Demo Complete'
           STOP RUN.
           
       BASIC-CALCULATIONS.
           COMPUTE WS-RESULT = WS-NUM1 + WS-NUM2
           MOVE WS-NUM1 TO WS-DISPLAY-NUM1
           MOVE WS-NUM2 TO WS-DISPLAY-NUM2
           MOVE WS-RESULT TO WS-DISPLAY-RESULT
           DISPLAY 'Addition: ' WS-DISPLAY-NUM1 ' + ' 
                   WS-DISPLAY-NUM2 ' = ' WS-DISPLAY-RESULT
           
           COMPUTE WS-RESULT = WS-NUM1 * WS-NUM2
           MOVE WS-RESULT TO WS-DISPLAY-RESULT
           DISPLAY 'Multiplication: ' WS-DISPLAY-NUM1 ' * '
                   WS-DISPLAY-NUM2 ' = ' WS-DISPLAY-RESULT.
                   
       LOOP-CALCULATIONS.
           DISPLAY 'Performing loop calculations:'
           PERFORM CALCULATE-POWERS
               VARYING WS-COUNTER FROM 1 BY 1
               UNTIL WS-COUNTER > WS-MAX-COUNT.
               
       CALCULATE-POWERS.
           COMPUTE WS-RESULT = WS-NUM1 ** WS-COUNTER
           MOVE WS-RESULT TO WS-DISPLAY-RESULT
           DISPLAY 'Power ' WS-COUNTER ': ' WS-DISPLAY-NUM1
                   ' ** ' WS-COUNTER ' = ' WS-DISPLAY-RESULT.