"""Hermetic Gate-4 receipt over the real server port and standalone C1 CLI.

The embedded key is exclusively a synthetic harness authority.  The adapter
therefore proves mechanism and attack rejection, never real-world authority or
production approval.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import stat
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.temporal import (  # noqa: E402
    build_temporal_anchor,
    two_ended_temporal_sidecar_sha256,
)
from lakatos.verdicts import prediction_content_sha, receipt_content_sha  # noqa: E402
from lakatos.write_cert import (  # noqa: E402
    did_key_encode,
    ed25519_public_key,
)
from server.contexts.tree.judgement_policy import build_receipt_fields  # noqa: E402
from server.contexts.tree.receipt_chain import receipt_graph_prefix_sha256  # noqa: E402
from server.contexts.tree.temporal_proof import (  # noqa: E402
    build_prediction_temporal_commitment,
    build_temporal_authority_policy,
    build_two_ended_sidecar,
    prediction_temporal_commitment_sha256,
    verify_two_ended_temporal_sidecar_prefix,
)
from server.contexts.tree.temporal_verifier_port import (  # noqa: E402
    IndependentTemporalCandidate,
    IndependentTemporalVerifierUnavailable,
    SubprocessIndependentTemporalVerifier,
    SubprocessTimeAuthority,
    temporal_artifact_sha256,
    temporal_request_id,
    transport_receipt,
)
import server.contexts.tree.temporal_verifier_port as port_module  # noqa: E402


NOW = datetime.now(timezone.utc)
_SECRETS = {
    name: bytes([value]) * 32
    for name, value in {
        "producer": 101,
        "attestor": 102,
        "w1": 103,
        "w2": 104,
        "time": 105,
    }.items()
}
_DIDS = {
    name: did_key_encode(ed25519_public_key(secret))
    for name, secret in _SECRETS.items()
}


def _require(condition: bool, message) -> None:
    if not condition:
        raise RuntimeError(f"C1 two-ended temporal harness red: {message}")


def _event(cid: str, name: str) -> dict:
    return {
        "cid": cid,
        "correlation_id": cid,
        "cycle_id": cid,
        "service": "lakatotree.c1_two_ended_temporal",
        "event": name,
    }


def _anchors(receipt_sha: str, timestamp: str) -> list[dict]:
    return sorted(
        [
            build_temporal_anchor(
                _SECRETS[name], receipt_sha, timestamp, _DIDS[name]
            )
            for name in ("w1", "w2")
        ],
        key=lambda item: item["witness_did"],
    )


def _candidate(tag: str) -> tuple[IndependentTemporalCandidate, object]:
    policy = build_temporal_authority_policy(
        threshold=2,
        witness_allowlist=[_DIDS["w1"], _DIDS["w2"]],
        producer_dids=[_DIDS["producer"]],
        attestor_dids=[_DIDS["attestor"]],
        evidence_refs=[
            "kg://LakatosTree/T/research-layout",
            "kg://LakatosTree/T/temporal-witness-policy",
        ],
    )
    prediction = {
        "receipt_kind": "prediction",
        "tree": "T",
        "tag": tag,
        "metric_name": "m",
        "direction": "lower",
        "baseline_value": 2.0,
        "noise_band": 0.0,
        "scale_type": "ratio",
        "novel_prediction": "",
        "novel_metric": None,
        "novel_direction": None,
        "novel_threshold": None,
        "judge_script_sha": "1" * 64,
        "closes_question": "",
        "credence": None,
        "baseline_lineage": "no_prior",
        "registered_at": "2026-08-02T00:00:00+00:00",
        "prev_receipt_sha": None,
        "anchor_bundle_sha256": "2" * 64,
        "history_payload_sha256": "3" * 64,
    }
    prediction["receipt_sha"] = prediction_content_sha(prediction)
    t1 = _anchors(
        prediction["receipt_sha"], (NOW - timedelta(minutes=4)).isoformat()
    )
    commitment = build_prediction_temporal_commitment(
        tree_incarnation_id="incarnation-1",
        tree="T",
        tag=tag,
        prediction_receipt_sha256=prediction["receipt_sha"],
        authority_policy=policy,
        prediction_anchors=t1,
    )
    commitment_sha = prediction_temporal_commitment_sha256(commitment)
    verdict = build_receipt_fields(
        tree="T",
        tag=tag,
        target_id=tag,
        verdict="progressive",
        metric_name="m",
        metric_value=1.0,
        novel_confirmed=False,
        lakatos_status="progressive",
        judged_at="2026-08-02T00:02:00+00:00",
        judge_script_sha="1" * 64,
        prev_receipt_sha=prediction["receipt_sha"],
        measurement_grade="server_regenerated",
        engine_rule_sha="4" * 64,
        prediction_temporal_commitment_sha256=commitment_sha,
    )
    verdict["receipt_sha"] = receipt_content_sha(verdict)
    t2 = _anchors(
        verdict["receipt_sha"], (NOW - timedelta(minutes=2)).isoformat()
    )
    chain = [prediction["receipt_sha"], verdict["receipt_sha"]]
    graph_sha = receipt_graph_prefix_sha256(
        tree_incarnation_id="incarnation-1",
        tree="T",
        tag=tag,
        prediction_receipt_sha256=prediction["receipt_sha"],
        verdict_receipt_sha256=verdict["receipt_sha"],
        chain=chain,
    )
    sidecar = build_two_ended_sidecar(
        authority_policy=policy,
        prediction_receipt_sha256=prediction["receipt_sha"],
        verdict_receipt_sha256=verdict["receipt_sha"],
        receipt_graph_sha256=graph_sha,
        prediction_anchors=t1,
        verdict_anchors=t2,
    )
    sidecar_sha = two_ended_temporal_sidecar_sha256(sidecar)
    receipts = {
        prediction["receipt_sha"]: prediction,
        verdict["receipt_sha"]: verdict,
    }
    proof = verify_two_ended_temporal_sidecar_prefix(
        sidecar,
        stored_sidecar_sha256=sidecar_sha,
        authority_policy=policy,
        tree="T",
        tag=tag,
        tree_incarnation_id="incarnation-1",
        chain=chain,
        receipt_by_sha=receipts,
        evaluated_at=NOW,
    )
    request_id = temporal_request_id(
        tree_incarnation_id="incarnation-1",
        tree="T",
        tag=tag,
        verdict_receipt_sha256=verdict["receipt_sha"],
    )
    return IndependentTemporalCandidate(
        request_id=request_id,
        tree_incarnation_id="incarnation-1",
        tree="T",
        tag=tag,
        current_head_sha256=verdict["receipt_sha"],
        stored_sidecar_sha256=sidecar_sha,
        authority_policy=policy,
        sidecar=sidecar,
        chain=tuple(chain),
        receipts=tuple(transport_receipt(receipts[sha]) for sha in chain),
        authority_policy_sha256=proof.authority_policy_sha256,
        receipt_graph_sha256=proof.receipt_graph_sha256,
        prediction_receipt_sha256=proof.prediction_receipt_sha256,
        verdict_receipt_sha256=proof.verdict_receipt_sha256,
        prediction_temporal_commitment_sha256=(
            proof.prediction_temporal_commitment_sha256
        ),
        witness_dids=proof.witness_dids,
        threshold=proof.threshold,
    ), proof


def _authority_source() -> bytes:
    return f'''#!{sys.executable}
import hashlib
import json
import sys
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DOMAIN = b"lakatotree-independent-time-authority-challenge/v1\\0"
SIGN_DOMAIN = b"lakatotree-independent-time-authority-attestation/v1\\0"
SIGNER = "{_DIDS["time"]}"
SECRET = bytes.fromhex("{_SECRETS["time"].hex()}")

def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")

raw = sys.stdin.buffer.read()
challenge = json.loads(raw)
challenge_sha = hashlib.sha256(DOMAIN + raw).hexdigest()
private = Ed25519PrivateKey.from_private_bytes(SECRET)
attestations = []
for proof in challenge["proofs"]:
    body = {{
        "schema_version": "lakatotree-independent-time-authority-attestation/v1",
        "challenge_sha256": challenge_sha,
        "signer_did": SIGNER,
        **proof,
        "verifier_artifact_sha256": challenge["verifier_artifact_sha256"],
        "verifier_python_sha256": challenge["verifier_python_sha256"],
        "observed_at": "{(NOW - timedelta(seconds=1)).isoformat()}",
        "valid_until": "{(NOW + timedelta(minutes=1)).isoformat()}",
    }}
    signature = private.sign(SIGN_DOMAIN + canonical(body)).hex()
    attestations.append({{**body, "signature": signature}})
response = {{
    "schema_version": "lakatotree-independent-time-authority-response/v1",
    "challenge_sha256": challenge_sha,
    "attestations": attestations,
}}
sys.stdout.buffer.write(canonical(response) + b"\\n")
'''.encode("utf-8")


def _port(directory: Path) -> SubprocessIndependentTemporalVerifier:
    authority_path = directory / "synthetic-time-authority"
    authority_bytes = _authority_source()
    authority_path.write_bytes(authority_bytes)
    authority_path.chmod(stat.S_IRUSR | stat.S_IXUSR)
    artifact_directory = ROOT / "c1verify"
    artifact_sha, _files = temporal_artifact_sha256(artifact_directory)
    python = Path(sys.executable).resolve(strict=True)
    python_sha = hashlib.sha256(python.read_bytes()).hexdigest()
    return SubprocessIndependentTemporalVerifier(
        python_executable=python,
        artifact_directory=artifact_directory,
        expected_artifact_sha256=artifact_sha,
        expected_python_sha256=python_sha,
        time_authority=SubprocessTimeAuthority(
            executable=authority_path,
            expected_executable_sha256=hashlib.sha256(authority_bytes).hexdigest(),
            expected_signer_did=_DIDS["time"],
            nonce_factory=lambda _size: "a" * 64,
        ),
    )


def _causal_seal_splice(
    candidate: IndependentTemporalCandidate,
) -> IndependentTemporalCandidate:
    receipts = [dict(receipt) for receipt in candidate.receipts]
    verdict = receipts[-1]
    verdict["prediction_temporal_commitment_sha256"] = "0" * 64
    verdict["receipt_sha"] = receipt_content_sha(verdict)
    verdict_sha = verdict["receipt_sha"]
    chain = [*candidate.chain[:-1], verdict_sha]
    graph_sha = receipt_graph_prefix_sha256(
        tree_incarnation_id=candidate.tree_incarnation_id,
        tree=candidate.tree,
        tag=candidate.tag,
        prediction_receipt_sha256=candidate.prediction_receipt_sha256,
        verdict_receipt_sha256=verdict_sha,
        chain=chain,
    )
    sidecar = build_two_ended_sidecar(
        authority_policy=candidate.authority_policy,
        prediction_receipt_sha256=candidate.prediction_receipt_sha256,
        verdict_receipt_sha256=verdict_sha,
        receipt_graph_sha256=graph_sha,
        prediction_anchors=list(candidate.sidecar["prediction_anchors"]),
        verdict_anchors=_anchors(
            verdict_sha, (NOW - timedelta(minutes=2)).isoformat()
        ),
    )
    return replace(
        candidate,
        request_id=temporal_request_id(
            tree_incarnation_id=candidate.tree_incarnation_id,
            tree=candidate.tree,
            tag=candidate.tag,
            verdict_receipt_sha256=verdict_sha,
        ),
        current_head_sha256=verdict_sha,
        stored_sidecar_sha256=two_ended_temporal_sidecar_sha256(sidecar),
        sidecar=sidecar,
        chain=tuple(chain),
        receipts=tuple(receipts),
        receipt_graph_sha256=graph_sha,
        verdict_receipt_sha256=verdict_sha,
    )


def verify(backend, cid):
    manifest = json.loads(
        Path(__file__).with_name("harness.json").read_text(encoding="utf-8")
    )
    required = set(manifest["required_controls"])
    executed: set[str] = set()

    def control(name: str, condition: bool, message) -> None:
        _require(name in required, f"undeclared control: {name}")
        _require(name not in executed, f"duplicate control: {name}")
        _require(condition, message)
        executed.add(name)

    first, first_gate3 = _candidate("n")
    second, second_gate3 = _candidate("other")
    c1_modules_before = {
        name for name in sys.modules
        if name == "c1verify" or name.startswith("c1verify.")
    }
    with tempfile.TemporaryDirectory(prefix="lakatotree-c1-ooptdd-") as temp:
        port = _port(Path(temp))
        calls = []
        real_run = port_module._run_bounded

        def counted(*args, **kwargs):
            calls.append(tuple(args[0]))
            return real_run(*args, **kwargs)

        port_module._run_bounded = counted
        try:
            results = port.verify_batch((second, first))
        finally:
            port_module._run_bounded = real_run

        control(
            "process.two_process_positive",
            set(results) == {first.request_id, second.request_id}
            and all(result.accepted for result in results.values()),
            results,
        )
        control(
            "process.no_inprocess_c1_import",
            {
                name for name in sys.modules
                if name == "c1verify" or name.startswith("c1verify.")
            } == c1_modules_before,
            "the parent imported the standalone C1 implementation",
        )
        control(
            "identity.result_bindings",
            all(
                result.verdict_receipt_sha256
                == {first.request_id: first, second.request_id: second}[request_id]
                .verdict_receipt_sha256
                and result.input_sha256
                and result.independent_valid_until
                for request_id, result in results.items()
            ),
            results,
        )
        backend.ship([_event(cid, "two_process_temporal_verified")])
        control(
            "process.batch_single_round",
            len(calls) == 2
            and calls[0][0].endswith("authority")
            and calls[1][-1].endswith("temporal_cli.py"),
            calls,
        )
        control(
            "process.c1_isolated_argv",
            calls[1][1:4] == ("-I", "-S", "-B"),
            calls[1],
        )
        backend.ship([_event(cid, "temporal_batch_bounded")])

        spliced = replace(
            first,
            sidecar={**first.sidecar, "receipt_graph_sha256": "0" * 64},
        )
        rejected = port.verify_batch((spliced,))[spliced.request_id]
        control(
            "crypto.sidecar_splice",
            not rejected.accepted,
            rejected,
        )
        causal = _causal_seal_splice(first)
        causal_result = port.verify_batch((causal,))[causal.request_id]
        control(
            "crypto.v7_commitment_seal",
            not causal_result.accepted
            and causal_result.reason == "verdict.v7_commitment_seal",
            causal_result,
        )

        pin_directories = []

        def pin_rejected(mutate) -> bool:
            directory = Path(temp) / f"pin-{len(pin_directories)}"
            directory.mkdir()
            pin_directories.append(directory)
            fresh = _port(directory)
            mutate(fresh)
            try:
                fresh.verify_batch((first,))
            except IndependentTemporalVerifierUnavailable:
                return True
            return False

        control(
            "identity.authority_executable_pin",
            pin_rejected(
                lambda fresh: setattr(
                    fresh.time_authority, "expected_executable_sha256", "0" * 64
                )
            ),
            "authority executable pin drift accepted",
        )
        control(
            "identity.authority_signer_pin",
            pin_rejected(
                lambda fresh: setattr(
                    fresh.time_authority,
                    "expected_signer_did",
                    first.witness_dids[0],
                )
            ),
            "authority signer pin drift accepted",
        )
        control(
            "identity.artifact_pin",
            pin_rejected(
                lambda fresh: setattr(
                    fresh, "expected_artifact_sha256", "0" * 64
                )
            ),
            "artifact pin drift accepted",
        )
        control(
            "identity.python_pin",
            pin_rejected(
                lambda fresh: setattr(
                    fresh, "expected_python_sha256", "0" * 64
                )
            ),
            "Python pin drift accepted",
        )
        backend.ship([_event(cid, "temporal_splice_and_pin_rejected")])

    control(
        "claim.per_proof_only",
        first_gate3.l3_eligible is False
        and second_gate3.l3_eligible is False
        and "production_ready" not in results[first.request_id].__dict__,
        "Gate 4 escaped its per-proof claim boundary",
    )
    backend.ship([_event(cid, "temporal_claim_bounded")])

    control(
        "manifest.exact_control_set",
        executed | {"manifest.exact_control_set"} == required,
        {"missing": sorted(required - executed), "unexpected": sorted(executed - required)},
    )
    _require(executed == required, "executed control manifest drift")
