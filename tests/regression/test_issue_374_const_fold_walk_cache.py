"""Regression tests for issue #374: ``gen-fixtures --scenarios all`` was
quadratic in program size because every ``ConstantFolder.fold`` re-walked
the whole PROCEDURE DIVISION for its READ / DISPLAY / WRITE sites and
recomputed every statement's nested lists.

The program walk is now computed once per program and the unseeded fold is
memoised per (program, index). These tests pin that the cache never changes
an answer: a repeated or interleaved fold equals a fresh one, the memoised
result is never shared with a caller, and nothing leaks outside a fold.
"""

from __future__ import annotations

import gc
import weakref

from cobolparser import parse_cobol
from cobolparser.analysis import const_fold
from cobolparser.analysis.boundary_inventory import BoundaryInventoryAnalyzer
from cobolparser.analysis.const_fold import ConstantFolder
from cobolparser.generators import ProgramFixtureGenerator
from cobolparser.layout.program import ProgramLayoutIndex

_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. CACHE374.
       ENVIRONMENT DIVISION.
       INPUT-OUTPUT SECTION.
       FILE-CONTROL.
           SELECT F1 ASSIGN TO F1DD FILE STATUS IS WS-FS1.
       DATA DIVISION.
       FILE SECTION.
       FD F1.
       01 R1.
          05 R1-AMT  PIC 9(5).
       WORKING-STORAGE SECTION.
       01 WS-FS1 PIC XX.
       01 WS-EOF PIC X VALUE 'N'.
       01 WS-A   PIC 9(3).
       01 WS-TOT PIC 9(7) VALUE 0.
       PROCEDURE DIVISION.
       MAIN-PARA.
           OPEN INPUT F1
           MOVE 42 TO WS-A
           READ F1 AT END MOVE 'Y' TO WS-EOF END-READ
           IF R1-AMT > 10
              ADD 1 TO WS-TOT
           ELSE
              ADD 2 TO WS-TOT
           END-IF
           DISPLAY WS-A WS-TOT R1-AMT
           CLOSE F1
           GOBACK.
"""


def _program():
    result = parse_cobol(_SOURCE, filename="cache374.cbl")
    assert result.ast is not None and result.errors == [], result.errors
    return result.ast, ProgramLayoutIndex.build(result.ast)


def test_repeated_folds_equal_a_fresh_fold():
    ast, index = _program()
    folder = ConstantFolder()
    first = folder.fold(ast, index)
    seeded = folder.fold(ast, index, seed_values={"R1-AMT": "00099"})
    again = folder.fold(ast, index)
    seeded_again = folder.fold(ast, index, seed_values={"R1-AMT": "00099"})

    fresh_ast, fresh_index = _program()
    fresh = ConstantFolder().fold(fresh_ast, fresh_index)
    fresh_seeded = ConstantFolder().fold(
        fresh_ast, fresh_index, seed_values={"R1-AMT": "00099"}
    )

    assert first.known == again.known == fresh.known
    assert first.known["WS-A"] == "42"
    assert seeded.known == seeded_again.known == fresh_seeded.known
    assert first.read_keys == again.read_keys == fresh.read_keys


def test_memoised_unseeded_fold_is_never_shared():
    ast, index = _program()
    folder = ConstantFolder()
    first = folder.fold(ast, index)
    first.known["WS-A"] = "999"
    first.known["INJECTED"] = "x"
    second = folder.fold(ast, index)
    assert second.known["WS-A"] == "42"
    assert "INJECTED" not in second.known
    assert second is not first


def test_memo_is_per_index():
    ast, index = _program()
    other_index = ProgramLayoutIndex.build(ast)
    assert ConstantFolder().fold(ast, index).known == (
        ConstantFolder().fold(ast, other_index).known
    )


def test_no_walk_leaks_outside_a_fold():
    ast, index = _program()
    ConstantFolder().fold(ast, index, seed_values={"R1-AMT": "00001"})
    assert const_fold._CURRENT_WALK.get() is None


def _bundle_json() -> str:
    ast, index = _program()
    report = BoundaryInventoryAnalyzer().analyze(ast, index)
    return (
        ProgramFixtureGenerator()
        .generate_with_scenarios(ast, index, report, mode="all", seed=7)
        .to_json()
    )


def test_fixture_bundle_is_unchanged_by_the_cache(monkeypatch):
    cached = _bundle_json()

    def uncached(self, ast, index, *, seed_values=None, success_skipped=frozenset()):
        # The pre-#374 fold: no program walk, no memo.
        return self._fold(ast, index, seed_values, frozenset(success_skipped))

    monkeypatch.setattr(ConstantFolder, "fold", uncached)
    assert _bundle_json() == cached


def test_the_cache_does_not_keep_a_folded_program_alive():
    # Everything the walk holds leads back to the AST (statement ``parent``
    # chains, ``index.ast``): keyed weakly on the AST, the entry kept its
    # own key alive and no folded program was ever freed.
    ast, index = _program()
    folder = ConstantFolder()
    folder.fold(ast, index)
    folder.fold(ast, index, seed_values={"R1-AMT": "00099"})
    ast_ref, index_ref = weakref.ref(ast), weakref.ref(index)
    del ast, index
    gc.collect()
    assert ast_ref() is None
    assert index_ref() is None


def test_an_index_folded_with_another_ast_does_not_reuse_its_walk():
    ast, index = _program()
    other_ast, _ = _program()
    ConstantFolder().fold(ast, index)
    walk = const_fold._WALK_CACHE[index]
    ConstantFolder().fold(other_ast, index)
    assert const_fold._WALK_CACHE[index] is not walk
    assert const_fold._WALK_CACHE[index].program() is other_ast


_SKIP_SOURCE = """\
       IDENTIFICATION DIVISION.
       PROGRAM-ID. SKIP591.
       DATA DIVISION.
       WORKING-STORAGE SECTION.
       01 WS-FLAG PIC X.
       01 WS-NAME PIC X(4).
       PROCEDURE DIVISION.
       MAIN-PARA.
           IF WS-FLAG = 'Q'
              DISPLAY 'QUIT'
              STOP RUN
           END-IF.
           MOVE 'DONE' TO WS-NAME.
           DISPLAY WS-NAME.
           STOP RUN.
"""


def test_unseeded_memo_is_keyed_on_success_skipped():
    # #374 x #591: the unseeded fold depends on ``success_skipped`` (an arm a
    # success status never takes does not make later writes uncertain), so
    # the memo must not hand one set's answer to a fold under another.
    result = parse_cobol(_SKIP_SOURCE, filename="skip591.cbl")
    assert result.ast is not None
    ast, index = result.ast, ProgramLayoutIndex.build(result.ast)
    (if_stmt,) = ast.find_all_by_type("IfStatement")
    skipped = {id(if_stmt.then_statements[0])}
    folder = ConstantFolder()

    plain = folder.fold(ast, index)
    with_skip = folder.fold(ast, index, success_skipped=skipped)
    plain_again = folder.fold(ast, index)
    with_skip_again = folder.fold(ast, index, success_skipped=skipped)

    assert "WS-NAME" not in plain.known
    assert with_skip.known == {"WS-NAME": "DONE"}
    assert plain_again.known == plain.known
    assert with_skip_again.known == with_skip.known
