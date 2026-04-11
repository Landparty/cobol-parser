      *****************************************************************
      * IMS DLI Sample: Healthcare Patient Records System
      * Program-ID: HCIMS001
      * Interface:  CBLTDLI
      *
      * IMS Database Hierarchy (PATIENTDB):
      *   HOSPITAL  (root)
      *     WARD    (level 2)
      *       PATIENT   (level 3)
      *         DIAGNOSI  (level 4 - IMS names are max 8 chars)
      *
      * Operations demonstrated:
      *   GU   - path call to get a specific patient (HOSPITAL+PATIENT)
      *   GN   - get next diagnosis under a ward (WARD+DIAGNOSI)
      *   ISRT - insert a new patient record
      *   GHU  - get-hold-unique a patient record for update
      *   REPL - replace after hold (no SSA needed)
      *   DLET - delete after hold (no SSA needed)
      *   CHKP - checkpoint (no segment access)
      *   ROLB - rollback (no segment access)
      *
      * This pattern is typical in hospital information systems where
      * patient records are stored hierarchically by hospital and ward.
      *****************************************************************
       IDENTIFICATION DIVISION.
       PROGRAM-ID. HCIMS001.
       AUTHOR. ENTERPRISE-COBOL-TEAM.
       DATE-WRITTEN. 2024-01-15.

       ENVIRONMENT DIVISION.

       DATA DIVISION.
       WORKING-STORAGE SECTION.

      *-----------------------------------------------------------------
      * IMS DLI Function Code Table
      * All codes are PIC X(4); trailing spaces are significant to IMS.
      *-----------------------------------------------------------------
       01  DLI-FUNCTION-CODES.
           05  DLI-GU          PIC X(4) VALUE 'GU  '.
           05  DLI-GN          PIC X(4) VALUE 'GN  '.
           05  DLI-GHU         PIC X(4) VALUE 'GHU '.
           05  DLI-ISRT        PIC X(4) VALUE 'ISRT'.
           05  DLI-REPL        PIC X(4) VALUE 'REPL'.
           05  DLI-DLET        PIC X(4) VALUE 'DLET'.
           05  DLI-CHKP        PIC X(4) VALUE 'CHKP'.
           05  DLI-ROLB        PIC X(4) VALUE 'ROLB'.

      *-----------------------------------------------------------------
      * PCB Mask - Program Communication Block
      * One per sensitive segment hierarchy defined in the PSB.
      *-----------------------------------------------------------------
       01  PATIENT-PCB.
           05  PCB-DBD-NAME        PIC X(8).
           05  PCB-SEG-LEVEL       PIC XX.
           05  PCB-STATUS-CODE     PIC XX.
           05  PCB-PROC-OPTIONS    PIC X(4).
           05  PCB-RESERVED        PIC S9(5) COMP.
           05  PCB-SEG-NAME-FB     PIC X(8).
           05  PCB-KEY-LENGTH      PIC S9(5) COMP.
           05  PCB-NUM-SENS-SEGS   PIC S9(5) COMP.
           05  PCB-KEY-FEEDBACK    PIC X(24).

      *-----------------------------------------------------------------
      * Segment I/O Areas - data areas for each segment type
      *-----------------------------------------------------------------
       01  HOSPITAL-IO.
           05  HOSP-ID             PIC X(8).
           05  HOSP-NAME           PIC X(30).
           05  HOSP-CITY           PIC X(20).
           05  HOSP-STATE          PIC X(2).
           05  HOSP-ZIP            PIC X(10).

       01  WARD-IO.
           05  WARD-ID             PIC X(4).
           05  WARD-NAME           PIC X(20).
           05  WARD-CAPACITY       PIC 9(4) COMP.

       01  PATIENT-IO.
           05  PAT-ID              PIC X(10).
           05  PAT-LAST-NAME       PIC X(20).
           05  PAT-FIRST-NAME      PIC X(15).
           05  PAT-DOB             PIC X(8).
           05  PAT-ADMIT-DATE      PIC X(8).
           05  PAT-WARD-ID         PIC X(4).
           05  PAT-STATUS          PIC X(1).
               88  PAT-ACTIVE      VALUE 'A'.
               88  PAT-DISCHARGED  VALUE 'D'.

       01  DIAGNOSI-IO.
           05  DIAG-CODE           PIC X(10).
           05  DIAG-DESC           PIC X(50).
           05  DIAG-DATE           PIC X(8).
           05  DIAG-SEVERITY       PIC 9.
           05  DIAG-PHYSICIAN      PIC X(20).

      *-----------------------------------------------------------------
      * Segment Search Arguments (SSAs)
      *
      * Group-item SSA layout:
      *   First 8 bytes  = segment name (padded with spaces)
      *   Next 1 byte    = ' ' (unqualified) or '(' (qualified)
      *   For qualified: field(8) + operator(2) + value + ')'
      *-----------------------------------------------------------------

      * Unqualified SSA - selects any HOSPITAL segment
       01  SSA-HOSPITAL-UNQUAL.
           05  SSA-HOSP-SEG-NAME   PIC X(8) VALUE 'HOSPITAL'.
           05  FILLER              PIC X(1) VALUE ' '.

      * Qualified SSA - selects HOSPITAL by ID key
       01  SSA-HOSPITAL-QUAL.
           05  SSA-HOSP-SEG-QN     PIC X(8) VALUE 'HOSPITAL'.
           05  SSA-HOSP-OPEN-P     PIC X(1) VALUE '('.
           05  SSA-HOSP-FIELD      PIC X(8) VALUE 'HOSP-ID '.
           05  SSA-HOSP-OPER       PIC X(2) VALUE '= '.
           05  SSA-HOSP-KEY-VALUE  PIC X(8).
           05  SSA-HOSP-CLOSE-P    PIC X(1) VALUE ')'.

      * Unqualified WARD SSA
       01  SSA-WARD.
           05  SSA-WARD-SEG-NAME   PIC X(8) VALUE 'WARD    '.
           05  FILLER              PIC X(1) VALUE ' '.

      * Qualified PATIENT SSA - selects by patient ID
       01  SSA-PATIENT-QUAL.
           05  SSA-PAT-SEG-NAME    PIC X(8) VALUE 'PATIENT '.
           05  SSA-PAT-OPEN-P      PIC X(1) VALUE '('.
           05  SSA-PAT-FIELD       PIC X(8) VALUE 'PAT-ID  '.
           05  SSA-PAT-OPER        PIC X(2) VALUE '= '.
           05  SSA-PAT-KEY-VALUE   PIC X(10).
           05  SSA-PAT-CLOSE-P     PIC X(1) VALUE ')'.

      * Unqualified DIAGNOSI SSA
       01  SSA-DIAGNOSI.
           05  SSA-DIAG-SEG-NAME   PIC X(8) VALUE 'DIAGNOSI'.
           05  FILLER              PIC X(1) VALUE ' '.

      *-----------------------------------------------------------------
      * Working fields
      *-----------------------------------------------------------------
       01  WS-HOSPITAL-KEY         PIC X(8)  VALUE SPACES.
       01  WS-PATIENT-KEY          PIC X(10) VALUE SPACES.
       01  WS-CHKP-AREA            PIC X(8)  VALUE 'CHKP0001'.
       01  WS-EOF                  PIC X(1)  VALUE 'N'.
           88  AT-END-OF-DB        VALUE 'Y'.
       01  WS-RETURN-CODE          PIC S9(4) COMP VALUE ZERO.

       LINKAGE SECTION.
       01  LS-HOSPITAL-ID          PIC X(8).
       01  LS-PATIENT-ID           PIC X(10).

       PROCEDURE DIVISION USING LS-HOSPITAL-ID
                                  LS-PATIENT-ID.

       MAIN-LOGIC.
           MOVE LS-HOSPITAL-ID TO WS-HOSPITAL-KEY
           MOVE LS-PATIENT-ID  TO WS-PATIENT-KEY
           PERFORM GET-PATIENT-BY-KEY
           PERFORM GET-ALL-WARD-DIAGNOSES
           PERFORM INSERT-NEW-PATIENT
           PERFORM UPDATE-PATIENT-STATUS
           PERFORM ISSUE-CHECKPOINT
           STOP RUN.

      *-----------------------------------------------------------------
      * GET-PATIENT-BY-KEY
      * GU path call: HOSPITAL(key) -> PATIENT(key)
      * Demonstrates: qualified path call through two hierarchy levels
      *-----------------------------------------------------------------
       GET-PATIENT-BY-KEY.
           MOVE WS-HOSPITAL-KEY TO SSA-HOSP-KEY-VALUE
           MOVE WS-PATIENT-KEY  TO SSA-PAT-KEY-VALUE
           CALL 'CBLTDLI' USING DLI-GU
                                PATIENT-PCB
                                PATIENT-IO
                                SSA-HOSPITAL-QUAL
                                SSA-PATIENT-QUAL
           IF PCB-STATUS-CODE NOT = SPACES
               DISPLAY 'GU FAILED: ' PCB-STATUS-CODE
               MOVE 8 TO WS-RETURN-CODE
           END-IF.

      *-----------------------------------------------------------------
      * GET-ALL-WARD-DIAGNOSES
      * GN path call: WARD -> DIAGNOSI (loop through all diagnoses)
      * Demonstrates: unqualified path SSA for sequential retrieval
      *-----------------------------------------------------------------
       GET-ALL-WARD-DIAGNOSES.
           MOVE 'N' TO WS-EOF
           CALL 'CBLTDLI' USING DLI-GN
                                PATIENT-PCB
                                DIAGNOSI-IO
                                SSA-WARD
                                SSA-DIAGNOSI
           PERFORM UNTIL AT-END-OF-DB
               IF PCB-STATUS-CODE = 'GE'
                   MOVE 'Y' TO WS-EOF
               ELSE
                   DISPLAY 'DIAG: ' DIAG-CODE ' - ' DIAG-DESC
                   CALL 'CBLTDLI' USING DLI-GN
                                        PATIENT-PCB
                                        DIAGNOSI-IO
                                        SSA-WARD
                                        SSA-DIAGNOSI
               END-IF
           END-PERFORM.

      *-----------------------------------------------------------------
      * INSERT-NEW-PATIENT
      * ISRT: insert a new PATIENT under qualified HOSPITAL
      * Demonstrates: ISRT with one target SSA
      *-----------------------------------------------------------------
       INSERT-NEW-PATIENT.
           MOVE SPACES TO PATIENT-IO
           MOVE WS-PATIENT-KEY TO PAT-ID
           MOVE 'A'            TO PAT-STATUS
           CALL 'CBLTDLI' USING DLI-ISRT
                                PATIENT-PCB
                                PATIENT-IO
                                SSA-HOSPITAL-QUAL
                                SSA-PATIENT-QUAL
           IF PCB-STATUS-CODE NOT = SPACES
               DISPLAY 'ISRT FAILED: ' PCB-STATUS-CODE
           END-IF.

      *-----------------------------------------------------------------
      * UPDATE-PATIENT-STATUS
      * GHU then REPL: get-hold-unique followed by replace
      * Demonstrates: two-step IMS update pattern
      *   GHU: holds PATIENT for update (path call)
      *   REPL: replaces held segment (no SSA - uses last position)
      *-----------------------------------------------------------------
       UPDATE-PATIENT-STATUS.
           MOVE WS-HOSPITAL-KEY TO SSA-HOSP-KEY-VALUE
           MOVE WS-PATIENT-KEY  TO SSA-PAT-KEY-VALUE
           CALL 'CBLTDLI' USING DLI-GHU
                                PATIENT-PCB
                                PATIENT-IO
                                SSA-HOSPITAL-QUAL
                                SSA-PATIENT-QUAL
           IF PCB-STATUS-CODE = SPACES
               MOVE 'D' TO PAT-STATUS
               CALL 'CBLTDLI' USING DLI-REPL
                                    PATIENT-PCB
                                    PATIENT-IO
           ELSE
               DISPLAY 'GHU FAILED: ' PCB-STATUS-CODE
           END-IF.

      *-----------------------------------------------------------------
      * ISSUE-CHECKPOINT
      * CHKP: IMS checkpoint call - no SSA, no segment access
      * Demonstrates: non-data DLI call with zero SSA parameters
      *-----------------------------------------------------------------
       ISSUE-CHECKPOINT.
           CALL 'CBLTDLI' USING DLI-CHKP
                                PATIENT-PCB
                                WS-CHKP-AREA.
