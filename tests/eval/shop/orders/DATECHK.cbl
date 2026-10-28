       IDENTIFICATION DIVISION.
       PROGRAM-ID. DATECHK.
       DATA DIVISION.
       LINKAGE SECTION.
       01  LS-DATE.
           05  LS-YYYY               PIC 9(4).
           05  LS-MM                 PIC 99.
           05  LS-DD                 PIC 99.
       01  LS-RC                     PIC S9(4) COMP.
       PROCEDURE DIVISION USING LS-DATE LS-RC.
       0000-CHECK.
           MOVE 0 TO LS-RC
           IF LS-MM < 1 OR LS-MM > 12 OR LS-DD < 1 OR LS-DD > 31
               MOVE 4 TO LS-RC
           END-IF
           GOBACK.
