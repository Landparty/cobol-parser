      * Top-level procedure copybook - nests into L2
           DISPLAY "Level 1 reached".
           COPY PROC-DEEP-L2.
           MOVE "L1-COMPLETE" TO WS-STATUS.
