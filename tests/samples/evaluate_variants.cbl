       IDENTIFICATION DIVISION.
       PROGRAM-ID. EVALDEMO.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-GRADE        PIC 9.
       01  WS-STATUS       PIC X.
       01  WS-COUNTER      PIC 9.
       01  WS-LOGICAL      PIC X.
       PROCEDURE DIVISION.
      * Simple literals with WHEN OTHER
       EVALUATE WS-GRADE
           WHEN 1
               DISPLAY 'ONE'
           WHEN 2 THRU 3
               DISPLAY 'LOW'
           WHEN OTHER
               DISPLAY 'OTHER'
       END-EVALUATE.

      * Multiple subjects with ALSO and ANY
       EVALUATE WS-GRADE ALSO WS-STATUS
           WHEN 1 ALSO 'A'
               DISPLAY 'ALPHA'
           WHEN ANY ALSO 'Z'
               DISPLAY 'ANY-Z'
           WHEN OTHER
               DISPLAY 'FALLBACK'
       END-EVALUATE.

      * EVALUATE TRUE with AND/OR conditions
       EVALUATE TRUE
           WHEN WS-GRADE = 9 AND WS-COUNTER > 5
               DISPLAY 'HIGH'
           WHEN WS-COUNTER <= 5 OR WS-STATUS = 'S'
               DISPLAY 'MED'
           WHEN OTHER
               DISPLAY 'DEFAULT'
       END-EVALUATE.

       GOBACK.
       END PROGRAM EVALDEMO.
