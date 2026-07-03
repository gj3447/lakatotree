"""
test_omd_parallel_2pc.py — OMD D8 split-phase merge / 2PC guard (PROM node: two_phase_commit_split)

문제(literature anomaly):
  Two-phase commit (Gray, "Notes on Data Base Operating Systems", 1978) + write-ahead /
  crash recovery (ARIES, Mohan et al. 1992): a long, externally side-effecting action
  (here a `git merge`) must NOT run while a coordinator lock is held, yet it must be
  ATOMIC and RECOVERABLE. The naive single-phase coupling — do the merge then flip the
  task to MERGED+release the orbit as one un-journaled step — admits the classic torn
  write: a crash between "merge landed" and "MERGED recorded" strands the task in
  CONNECTING forever, and a blind retry re-merges (double effect).

OMD problemshift (D8 split-phase merge):
  OMD splits CONNECT into a recoverable, repo-exclusive 2PC:
    Phase A (under lock): revalidate fence + acquire repo-wide merge_token.
    Phase B (OUTSIDE lock): git merge.
    Phase C: record merge_sha BEFORE releasing the write-orbit, then MERGED.
    Restart: probe the merge trailer (mergeResult/merge_sha) to recover-forward exactly
    once or roll back — no double-merge, no stranded CONNECTING task.

Defect oracle (guard_defect): self-contained, revert-proof in-test state machine. NAIVE
  single-phase crashes between merge-OK and MERGED → on restart a blind retry re-merges
  (double effect). SPLIT-PHASE records merge_sha before release + a restart probe →
  recovers to MERGED exactly once. Also asserts AtMostOneMergeToken (two tasks cannot
  both hold the token). Toggling the split_phase flag off re-runs the identical schedule
  and the double-merge defect reappears (RED) — revert-proof by construction.

Mechanism oracle (guard_mechanism): STRUCTURAL TLA+ corroboration, independent of the
  in-test model. Asserts MergedHasMergeSha ∧ AtMostOneMergeToken ∧ TokenImpliesConnecting
  are each declared as "<Name> ==" in omd_connect.tla AND listed under INVARIANTS in
  omd_connect.cfg (i.e. actually model-checked). Negative control: a bogus invariant name
  is rejected by the same parser (oracle is not vacuous).

OMD artifact corroborated:
  <WORKSPACE>/PROJECT/PI/omd/spec/omd_connect.tla
    AtMostOneMergeToken, TokenImpliesConnecting, MergedHasMergeSha, MergedReleasesWriteLease,
    PhaseCOk records mergeSha before releasing writeHeld ("P0-6 ordering").
  <WORKSPACE>/PROJECT/PI/omd/spec/omd_connect.cfg  INVARIANTS section.
  Dimension test: <WORKSPACE>/PROJECT/PI/omd/tests/test_d8_connect_splitphase.py

KG lit node: OMD-finding-fencing-required
literature:  Two-phase commit (Gray 1978) + write-ahead/crash recovery (ARIES, Mohan 1992)
oracle_kind: tla (structural, no TLC/java run)
"""

import os
import re

# --- Real OMD artifact locations (READ-ONLY) -------------------------------
OMD_SPEC_DIR = "<WORKSPACE>/PROJECT/PI/omd/spec"
TLA_PATH = os.path.join(OMD_SPEC_DIR, "omd_connect.tla")
CFG_PATH = os.path.join(OMD_SPEC_DIR, "omd_connect.cfg")


# ===========================================================================
# In-test minimal 2PC merge model (for the DEFECT oracle).
# Mirrors omd_connect.tla: DONE -> CONNECTING -> MERGED with a repo-wide
# merge_token, a merge trailer (merge_result / merge_sha) and a crash modeled
# as an explicit reordered step.
# ===========================================================================
class MergeOrchestrator:
    """A tiny connect/merge coordinator.

    `split_phase=False` reproduces the naive single-phase coupling.
    `split_phase=True` records merge_sha BEFORE release and supports a restart
    probe that recovers a torn merge exactly once.
    """

    def __init__(self, split_phase):
        self.split_phase = split_phase
        # repo-wide exclusion: at most one task may own the merge token
        self.token_owner = None
        # side-effect ledger: how many times git-merge actually applied
        self.merge_applied_count = 0
        # per-task state
        self.tasks = {}  # name -> dict(state, merge_result, merge_sha, write_held, pinned)

    def add_task(self, name):
        self.tasks[name] = {
            "state": "DONE",
            "merge_result": "NONE",
            "merge_sha": None,
            "write_held": True,
            "pinned": False,
        }

    # ---- Phase A: under lock, grab repo-wide merge token --------------------
    def phase_a(self, name):
        t = self.tasks[name]
        if t["state"] != "DONE" or not t["write_held"]:
            return False
        if self.token_owner is not None:  # AtMostOneMergeToken enforcement
            return False
        t["state"] = "CONNECTING"
        t["pinned"] = True
        t["merge_result"] = "NONE"
        self.token_owner = name
        return True

    # ---- Phase B: OUTSIDE lock, the real side effect (git merge) -----------
    def phase_b_merge(self, name):
        """The actual side-effecting merge. Increments the global ledger."""
        t = self.tasks[name]
        assert t["state"] == "CONNECTING" and self.token_owner == name
        self.merge_applied_count += 1
        t["merge_result"] = "OK"

    # ---- Phase C: commit. Ordering differs by mode -------------------------
    def phase_c_commit(self, name, crash_before_record=False):
        """Commit the merge result.

        Naive (single-phase): flip MERGED + release, and ONLY THEN record sha.
          A crash between merge and MERGED leaves the task CONNECTING with no
          journaled evidence -> not recoverable.
        Split-phase: record merge_sha FIRST (durable trailer), then MERGED+release.
        Returns True if commit completed, False if it crashed mid-way.
        """
        t = self.tasks[name]
        assert t["state"] == "CONNECTING" and t["merge_result"] == "OK"

        if self.split_phase:
            # P0-6 ordering: durable evidence BEFORE release
            t["merge_sha"] = "sha-%s" % name
            if crash_before_record:
                # crash modeled AFTER the durable record but before flip:
                # the trailer already persisted, so recovery can roll forward.
                return False
            t["state"] = "MERGED"
            t["write_held"] = False
            t["pinned"] = False
            self.token_owner = None
            return True
        else:
            # naive: flip + release first, sha last (un-journaled)
            if crash_before_record:
                # torn write: merge landed, but state/sha never recorded.
                return False
            t["state"] = "MERGED"
            t["write_held"] = False
            t["pinned"] = False
            self.token_owner = None
            t["merge_sha"] = "sha-%s" % name
            return True

    # ---- Restart reconciliation -------------------------------------------
    def restart_recover(self, name):
        """Reconcile a task found in CONNECTING after a crash.

        Split-phase: probe the merge trailer. If merge_result==OK (merge landed)
          roll FORWARD to MERGED exactly once (do NOT re-run phase_b_merge).
        Naive: no durable trailer / no recovery logic -> task stays stranded,
          and the only way "forward" is to retry the whole merge (double effect).
        """
        t = self.tasks[name]
        if t["state"] != "CONNECTING":
            return
        if self.split_phase:
            if t["merge_result"] == "OK":
                # recover-forward WITHOUT re-merging
                if t["merge_sha"] is None:
                    t["merge_sha"] = "sha-%s" % name
                t["state"] = "MERGED"
                t["write_held"] = False
                t["pinned"] = False
                self.token_owner = None
            else:
                # roll back
                t["state"] = "DONE"
                t["pinned"] = False
                self.token_owner = None
        else:
            # naive retry path: blindly re-merge (double effect) to "make progress"
            self.phase_b_merge(name)
            t["state"] = "MERGED"
            t["write_held"] = False
            t["pinned"] = False
            self.token_owner = None
            t["merge_sha"] = "sha-%s" % name


# ===========================================================================
# GUARD: DEFECT oracle (negative / improvement). Revert-proof by construction.
# ===========================================================================
import os as _os
import pytest as _pytest
pytestmark = _pytest.mark.skipif(
    not _os.path.isdir("<WORKSPACE>/PROJECT/PI/omd"),
    reason="OMD 자매 repo 미체크아웃(hermetic CI) — 크로스레포 도그푸드 가드는 로컬에서만 실측")

def test_single_phase_merge_crash_strands_split_phase_recovers_exactly_once():
    # ---- NAIVE single-phase: crash mid-commit -> torn write ----------------
    naive = MergeOrchestrator(split_phase=False)
    naive.add_task("A")
    assert naive.phase_a("A")
    naive.phase_b_merge("A")  # git merge actually landed once
    assert naive.merge_applied_count == 1
    completed = naive.phase_c_commit("A", crash_before_record=True)
    assert completed is False, "modeled crash between merge and MERGED"

    # restart: naive has no durable trailer/recovery -> it re-merges (double effect)
    naive.restart_recover("A")
    # The defect manifests as EITHER a strand (still CONNECTING) OR a double-merge.
    naive_stranded = naive.tasks["A"]["state"] == "CONNECTING"
    naive_double = naive.merge_applied_count > 1
    assert naive_stranded or naive_double, (
        "naive single-phase must exhibit the classic failure: strand or double-merge"
    )
    # In this faithful model it is specifically a double-merge:
    assert naive_double and naive.merge_applied_count == 2

    # ---- SPLIT-PHASE: same crash schedule -> recover exactly once ----------
    split = MergeOrchestrator(split_phase=True)
    split.add_task("A")
    assert split.phase_a("A")
    split.phase_b_merge("A")
    assert split.merge_applied_count == 1
    completed = split.phase_c_commit("A", crash_before_record=True)
    assert completed is False, "same modeled crash point"
    # durable trailer was written BEFORE release -> recover-forward, no re-merge
    split.restart_recover("A")
    assert split.tasks["A"]["state"] == "MERGED", "split-phase recovers to MERGED"
    assert split.tasks["A"]["merge_sha"] is not None, "MergedHasMergeSha"
    assert split.tasks["A"]["write_held"] is False, "MergedReleasesWriteLease"
    assert split.merge_applied_count == 1, "no double-merge: exactly-once side effect"
    assert split.token_owner is None, "merge_token released after MERGED"

    # ---- AtMostOneMergeToken: two tasks cannot both hold the token ---------
    repo = MergeOrchestrator(split_phase=True)
    repo.add_task("A")
    repo.add_task("B")
    assert repo.phase_a("A") is True
    assert repo.phase_a("B") is False, "AtMostOneMergeToken: B blocked while A holds token"
    assert repo.token_owner == "A"

    # ---- REVERT-PROOF sensitivity: disable the split-phase ordering/recovery,
    #      re-run the identical schedule, and prove the defect RETURNS.
    reverted = MergeOrchestrator(split_phase=False)
    reverted.add_task("A")
    assert reverted.phase_a("A")
    reverted.phase_b_merge("A")
    reverted.phase_c_commit("A", crash_before_record=True)
    reverted.restart_recover("A")
    assert reverted.merge_applied_count == 2, (
        "without split-phase mechanism the double-merge defect must reappear"
    )


# ===========================================================================
# TLA+ structural parsing helpers (mechanism oracle).
# ===========================================================================
def _tla_declares_invariant(tla_text, name):
    """True iff `<name> ==` is declared at the start of a line in the .tla."""
    pat = re.compile(r"(?m)^\s*" + re.escape(name) + r"\s*==")
    return bool(pat.search(tla_text))


def _cfg_invariants(cfg_text):
    """Return the set of invariant names listed under the INVARIANTS section.

    The INVARIANTS keyword introduces a list of bare names, one per line, until
    the next top-level TLC config keyword (or EOF).
    """
    keywords = {
        "CONSTANTS", "CONSTANT", "SPECIFICATION", "INVARIANT", "INVARIANTS",
        "PROPERTY", "PROPERTIES", "CONSTRAINT", "CONSTRAINTS", "SYMMETRY",
        "VIEW", "INIT", "NEXT", "CHECK_DEADLOCK", "ACTION_CONSTRAINT",
        "ACTION_CONSTRAINTS", "ALIAS", "POSTCONDITION",
    }
    names = set()
    in_section = False
    for raw in cfg_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        first = line.split()[0]
        if first in keywords:
            in_section = first in ("INVARIANTS", "INVARIANT")
            # a keyword line may also carry inline names (e.g. "INVARIANTS Foo")
            if in_section:
                for tok in line.split()[1:]:
                    if tok not in keywords:
                        names.add(tok)
            continue
        if in_section:
            for tok in line.split():
                if tok in keywords:
                    in_section = False
                    break
                names.add(tok)
    return names


# ===========================================================================
# GUARD: MECHANISM oracle (positive / novel). Independent of the in-test model.
# ===========================================================================
def test_omd_tla_checks_merge_sha_and_at_most_one_merge_token():
    assert os.path.exists(TLA_PATH), "real OMD spec must exist: %s" % TLA_PATH
    assert os.path.exists(CFG_PATH), "real OMD cfg must exist: %s" % CFG_PATH

    with open(TLA_PATH, "r", encoding="utf-8") as f:
        tla = f.read()
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        cfg = f.read()

    cfg_invs = _cfg_invariants(cfg)

    required = ["MergedHasMergeSha", "AtMostOneMergeToken", "TokenImpliesConnecting"]
    for name in required:
        assert _tla_declares_invariant(tla, name), (
            "omd_connect.tla must DECLARE invariant %s ==" % name
        )
        assert name in cfg_invs, (
            "omd_connect.cfg must MODEL-CHECK %s under INVARIANTS (got %s)"
            % (name, sorted(cfg_invs))
        )

    # Negative control: the oracle must genuinely discriminate (not vacuous).
    bogus = "MergedHasNoShaWhatsoever"
    assert not _tla_declares_invariant(tla, bogus), "bogus name must not be declared"
    assert bogus not in cfg_invs, "bogus name must not be model-checked"


# ===========================================================================
# Extra regression / negative-control coverage (non load-bearing).
# ===========================================================================
def test_cfg_parser_extracts_known_connect_invariants():
    """Sanity: parser recovers the full INVARIANTS list and excludes CONSTANTS."""
    with open(CFG_PATH, "r", encoding="utf-8") as f:
        cfg = f.read()
    invs = _cfg_invariants(cfg)
    for expected in [
        "AtMostOneMergeToken", "TokenImpliesConnecting",
        "MergedHasMergeSha", "MergedReleasesWriteLease",
    ]:
        assert expected in invs, "missing model-checked invariant %s" % expected


def test_split_phase_clean_path_is_exactly_once():
    """No crash: split-phase still merges exactly once and reaches MERGED."""
    m = MergeOrchestrator(split_phase=True)
    m.add_task("A")
    assert m.phase_a("A")
    m.phase_b_merge("A")
    assert m.phase_c_commit("A", crash_before_record=False) is True
    assert m.tasks["A"]["state"] == "MERGED"
    assert m.merge_applied_count == 1
    assert m.token_owner is None
