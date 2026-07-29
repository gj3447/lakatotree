"""Command-line surface for the sealed LakatoTree scientific backtest."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from lakatos.backtest import (
    RESULT_STATUSES,
    build_backtest_measurement_lock,
    finalize_backtest_result_lock,
    joint_confirmatory_power_plan,
    required_discordant_pairs,
    run_locked_manifest,
    validate_manifest_path,
    verify_independent_replay,
)


def _load_json(path: str | Path) -> dict:
    def strict_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    value = json.loads(
        Path(path).read_text(encoding="utf-8"),
        object_pairs_hook=strict_object,
        parse_constant=lambda item: (_ for _ in ()).throw(
            ValueError(f"non-finite JSON constant is forbidden: {item}")
        ),
    )
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _guard_create_only(outputs: list[str | Path], inputs: list[str | Path]) -> None:
    resolved_outputs = [Path(path).expanduser().resolve() for path in outputs]
    resolved_inputs = {Path(path).expanduser().resolve() for path in inputs}
    if len(set(resolved_outputs)) != len(resolved_outputs):
        raise ValueError("scientific output paths must be distinct")
    if any(path in resolved_inputs for path in resolved_outputs):
        raise ValueError("scientific output must not overwrite a locked input")
    existing = [str(path) for path in resolved_outputs if path.exists()]
    if existing:
        raise FileExistsError("scientific outputs are create-only: " + ", ".join(existing))


def _write_json(path: str | Path, value: dict) -> str:
    payload = (
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("xb") as handle:
        handle.write(payload)
    return hashlib.sha256(payload).hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="validate without running devices")
    validate.add_argument("manifest")

    power = commands.add_parser("power", help="exact discordant-pair power plan")
    power.add_argument("--conditional-advantage", type=float, required=True)
    power.add_argument("--alpha", type=float, default=0.025)
    power.add_argument("--target-power", type=float, default=0.8)

    joint = commands.add_parser("joint-power", help="exact three-gate confirmatory power plan")
    joint.add_argument("--external-cases", type=int, required=True)
    joint.add_argument("--discordance-rate-floor", type=float, required=True)
    joint.add_argument("--conditional-advantage", type=float, default=0.8)
    joint.add_argument("--pairwise-alpha", type=float, default=0.025)
    joint.add_argument("--sensitivity-alternative", type=float, default=0.9)
    joint.add_argument("--sensitivity-wilson-floor", type=float, default=0.7)
    joint.add_argument("--joint-target-power", type=float, default=0.8)

    lock = commands.add_parser("lock", help="build a canonical premeasurement input lock")
    lock.add_argument("manifest")
    lock.add_argument("--output", required=True)

    run = commands.add_parser("run", help="run a locked manifest; confirmation needs quorum")
    run.add_argument("manifest")
    run.add_argument("--lock", required=True)
    run.add_argument("--output", required=True)
    run.add_argument("--receipt-output", required=True)

    replay = commands.add_parser("replay", help="independently replay producer bytes")
    replay.add_argument("manifest")
    replay.add_argument("--lock", required=True)
    replay.add_argument("--producer-result", required=True)
    replay.add_argument("--producer-receipt", required=True)
    replay.add_argument("--replayer-did", required=True)
    replay.add_argument("--replay-signature", required=True)
    replay.add_argument("--receipt-output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "validate":
        errors = validate_manifest_path(args.manifest)
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 1
    if args.command == "power":
        plan = required_discordant_pairs(
            conditional_advantage=args.conditional_advantage,
            alpha=args.alpha,
            target_power=args.target_power,
        )
        print(json.dumps(plan, sort_keys=True, indent=2))
        return 0
    if args.command == "joint-power":
        plan = joint_confirmatory_power_plan(
            external_cases=args.external_cases,
            discordance_rate_floor=args.discordance_rate_floor,
            conditional_advantage=args.conditional_advantage,
            pairwise_alpha=args.pairwise_alpha,
            sensitivity_alternative=args.sensitivity_alternative,
            sensitivity_wilson_floor=args.sensitivity_wilson_floor,
            joint_target_power=args.joint_target_power,
        )
        print(json.dumps(plan, sort_keys=True, indent=2))
        return 0 if plan["passed"] else 1
    if args.command == "lock":
        _guard_create_only([args.output], [args.manifest])
        wrapper = build_backtest_measurement_lock(args.manifest)
        _write_json(args.output, wrapper)
        print(json.dumps({
            "measurement_lock_sha": wrapper["measurement_lock_sha"],
            "measurement_lock_key": wrapper["measurement_lock_key"],
            "expected_manifest_sha256": wrapper["expected_manifest_sha256"],
        }, sort_keys=True))
        return 0
    if args.command == "replay":
        _guard_create_only(
            [args.receipt_output],
            [args.manifest, args.lock, args.producer_result, args.producer_receipt],
        )
        verified = verify_independent_replay(
            args.manifest,
            lock=_load_json(args.lock),
            producer_result_path=args.producer_result,
            producer_receipt=_load_json(args.producer_receipt),
            replayer_did=args.replayer_did,
            replay_signature_hex=args.replay_signature,
        )
        _write_json(args.receipt_output, verified)
        print(json.dumps({
            "status": "VERIFIED_REPLAY",
            "result_sha256": verified["result_sha256"],
            "measurement_lock_sha": verified["measurement_lock_sha"],
            "measurement_lock_key": verified["measurement_lock_key"],
            "claim_eligible": verified["claim_eligible"],
            "claim_grade": verified["claim_grade"],
            "scientific_result_verified": verified["scientific_result_verified"],
            "publication_eligible": verified["publication_eligible"],
        }, sort_keys=True))
        return 0

    _guard_create_only(
        [args.output, args.receipt_output],
        [args.manifest, args.lock],
    )
    wrapper = _load_json(args.lock)
    result = run_locked_manifest(args.manifest, lock=wrapper)
    result_sha = _write_json(args.output, result)
    if result.get("status") not in RESULT_STATUSES:
        print(json.dumps({
            "status": result.get("status"),
            "result_sha256": result_sha,
            "receipt_emitted": False,
        }, sort_keys=True))
        return 2
    receipt = finalize_backtest_result_lock(
        wrapper,
        result_sha256=result_sha,
        result_status=result["status"],
    )
    _write_json(args.receipt_output, receipt)
    print(json.dumps({
        "status": result["status"],
        "result_sha256": result_sha,
        "measurement_lock_sha": receipt["measurement_lock_sha"],
        "measurement_lock_key": receipt["measurement_lock_key"],
        "claim_eligible": receipt["claim_eligible"],
        "claim_grade": receipt["claim_grade"],
        "scientific_result_verified": receipt["scientific_result_verified"],
        "publication_eligible": receipt["publication_eligible"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
