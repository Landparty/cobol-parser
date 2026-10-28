       IDENTIFICATION DIVISION.
       PROGRAM-ID. ORDVAL.
      * ORDER VALIDATION SUBPROGRAM: DATE AND SHIP-TO CHECKS
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01  WS-DATE-PGM               PIC X(8) VALUE 'DATECHK'.
       01  WS-DATE-RC                PIC S9(4) COMP.
       LINKAGE SECTION.
           COPY ORDREC.
       01  LS-RC                     PIC S9(4) COMP.
       PROCEDURE DIVISION USING ORD-REC LS-RC.
       0000-VALIDATE.
           MOVE 0 TO LS-RC
           CALL WS-DATE-PGM USING ORD-DATE WS-DATE-RC
           IF WS-DATE-RC NOT = 0
               MOVE 4 TO LS-RC
               GOBACK
           END-IF
           EVALUATE TRUE
               WHEN ADDR-FOREIGN
                   IF ORD-PHONE
                       MOVE 8 TO LS-RC
                   END-IF
               WHEN ADDR-ZIP = ZERO
                   MOVE 12 TO LS-RC
               WHEN OTHER
                   CONTINUE
           END-EVALUATE
           GOBACK.
