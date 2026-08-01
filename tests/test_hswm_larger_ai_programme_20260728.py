"""Contract for the dense, authority-separated HSWM LargerAI programme."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "data" / "hswm_larger_ai_programme_20260728.json"
SEEDER = ROOT / "scripts" / "seed_hswm_larger_ai_programme.py"


def _load() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def _load_seeder():
    spec = importlib.util.spec_from_file_location("_hswm_larger_ai_seeder", SEEDER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_manifest_validator_proves_declared_topology_portably(monkeypatch, tmp_path):
    seeder = _load_seeder()
    monkeypatch.setitem(seeder._REPO_ROOTS, "HSWM", tmp_path / "absent-hswm")
    monkeypatch.setitem(
        seeder._REPO_ROOTS, "SYMPOSIUM", tmp_path / "absent-symposium"
    )
    data = _load()
    report = seeder.validate_manifest(data)

    assert report["ok"] is True
    assert report["scientific_progress_verdicts"] == 0
    assert report["efficacy_claims"] == 0
    assert len(data["source_bindings"]) == 14
    assert len(data["fragment_bindings"]) == 10
    assert report["source_bindings_verified"] == 5
    assert report["fragment_bindings_verified"] == 2
    assert report["source_authorities_unavailable"] == ["HSWM", "SYMPOSIUM"]
    assert report["topology"] == {
        "nodes": 19,
        "edges": 52,
        "roots": 1,
        "components": 1,
        "multi_parent_nodes": 17,
        "typed_edge_ratio": 1.0,
        "observations": 12,
        "questions": 8,
        "foundations": 12,
    }


def test_available_external_roots_verify_every_declared_binding():
    seeder = _load_seeder()
    missing = sorted(
        authority
        for authority, root in seeder._REPO_ROOTS.items()
        if not root.is_dir()
    )
    if missing:
        pytest.skip(f"external source roots unavailable: {', '.join(missing)}")

    report = seeder.validate_manifest(_load(), require_external_sources=True)

    assert report["source_bindings_verified"] == 14
    assert report["fragment_bindings_verified"] == 10
    assert report["source_authorities_unavailable"] == []


def test_every_parent_edge_is_typed_evidenced_and_topologically_ordered():
    data = _load()
    seen: set[str] = set()
    edge_pairs: set[tuple[str, str]] = set()
    for node in data["nodes"]:
        for edge in node["parent_edges"]:
            assert edge["tag"] in seen
            assert edge["relation_kind"] != "knowledge_inheritance"
            assert edge["evidence_ref"]
            assert edge["inferred"] is False
            pair = (node["tag"], edge["tag"])
            assert pair not in edge_pairs
            edge_pairs.add(pair)
        seen.add(node["tag"])
    assert len(edge_pairs) == 52


def test_hard_core_preserves_user_canon_without_reintroducing_stale_placement():
    data = _load()
    hard_core = data["tree"]["hard_core"]

    for phrase in (
        "더 큰 범위의 AI",
        "합의(合意)를 포함",
        "OM family #8/CHU",
        "LLM에 의해 실행",
        "의미론적 하이퍼그래프",
        "열려 있고 자기유사적",
    ):
        assert phrase in hard_core
    assert "HSWM 표준" not in hard_core
    assert "재배맨 #4" not in hard_core
    assert data["authority_policy"]["efficacy"].startswith("No performance")


def test_formalization_uses_the_actual_h_w_a_f_pi_meanings_and_stays_revisable():
    data = _load()
    node = next(node for node in data["nodes"] if node["tag"] == "hswm-state-h-w-a-f-pi")

    for phrase in (
        "가변 의미 하이퍼그래프",
        "slow/fast semantic weights",
        "run-local activation",
        "typed LLM-executed function nodes",
        "provenance, ledger, receipts, gates",
        "SECONDARY_AI",
    ):
        assert phrase in node["comment"]
    assert "ratification" in node["limitation"]
    assert node["algorithm"] == "secondary_formalization"


def test_existing_engineering_and_scientific_states_are_not_flattened_to_success():
    data = _load()
    by_tag = {node["tag"]: node for node in data["nodes"]}

    assert "engineering receipts" in by_tag["hswm-durable-runtime-ledger"]["comment"]
    assert "UNJUDGED" in by_tag["hswm-durable-runtime-ledger"]["limitation"]
    assert "currently running" in by_tag["hswm-exp-f1-retention"]["comment"]
    assert "exploratory_supported" in by_tag["hswm-exp-topology-mediation"]["comment"]
    assert "headroom_band_ok=false" in by_tag["hswm-exp-topology-mediation"]["comment"]
    assert "exploratory_refuted" in by_tag["hswm-exp-cross-agent-transfer"]["comment"]
    assert "exploratory_refuted" in by_tag["hswm-exp-consolidation"]["comment"]
    assert "Engineering PASS is not a scientific verdict" in by_tag[
        "hswm-formal-contract-engineering-evidence"
    ]["limitation"]


def test_open_experiments_are_falsifiable_and_unscored():
    data = _load()
    experiments = [node for node in data["nodes"] if node["algorithm"] == "open_experiment"]
    question_names = {item["qname"] for item in data["questions"]}

    assert len(experiments) == 8
    assert {node["open_question"] for node in experiments} == question_names
    for node in experiments:
        assert node["open_question"]
        assert node["open_question"] in question_names
        assert node["limitation"]
        assert node["result_path"].startswith("repo://")
        assert "metric_name" not in node
        assert "metric_value" not in node
        assert node.get("verdict", "proof") == "proof"


def test_observations_bind_exact_extracted_content_and_primary_source_urls():
    data = _load()
    observations = data["observations"]
    urls = [item["url"] for item in observations]
    event_ids = [item["event_id"] for item in observations]

    assert len(urls) == len(set(urls)) == 12
    assert len(event_ids) == len(set(event_ids)) == 12
    for item in observations:
        assert item["url"].startswith("https://")
        assert item["source_type"] in {
            "peer_reviewed_primary",
            "primary_preprint",
            "peer_reviewed_review",
            "standard_primary",
        }
        assert hashlib.sha256(item["content"].encode("utf-8")).hexdigest() == item["content_hash"]
        assert "HSWM efficacy" not in item["content"] or "not" in item["content"]
        assert item["lakatos_location"] != "hard_core"


def test_foundations_and_tradition_keep_canon_separate_from_experiments():
    data = _load()
    foundations = data["foundations"]
    tradition = data["tradition"]

    assert sum(item["status"] == "satisfied" for item in foundations) == 8
    assert sum(item["status"] == "needed" for item in foundations) == 4
    assert all(item["evidence_refs"] for item in foundations if item["status"] == "satisfied")
    identity = [
        item for item in tradition["commitments"]
        if item["revisability"] == "identity_boundary"
    ]
    assert len(identity) == 3
    assert any(item["commitment_id"] == "formalization-hwafpi"
               and item["revisability"] == "routine"
               for item in tradition["commitments"])
    assert "cannot mint verdicts" in tradition["compatibility_notes"]


def test_dry_run_performs_validation_without_constructing_an_http_client(monkeypatch, capsys):
    seeder = _load_seeder()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("dry-run constructed or used an HTTP client")

    monkeypatch.setattr(seeder, "ApiClient", forbidden)
    assert seeder.main(["--manifest", str(MANIFEST)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "dry-run"
    assert out["topology"]["edges"] == 52


def test_restart_safe_apply_preserves_already_closed_questions(monkeypatch):
    seeder = _load_seeder()
    data = _load()
    closed = {"q-hswm-f1-retention"}
    client = _ApplyClient(_remote_fixture(seeder, data, closed_questions=closed))

    def verified(_data, _client, *, closed_questions=frozenset()):
        assert closed_questions == closed
        return {"verified": True}

    monkeypatch.setattr(seeder, "verify_remote", verified)
    out = seeder.apply_manifest(data, client)

    assert client.posts == []
    assert out["operations"] == 0
    assert out["closed_questions_preserved"] == 1
    assert out["nodes_already_exact"] == len(data["nodes"])
    assert out["questions_already_exact"] == len(data["questions"])
    assert out["foundations_already_exact"] == len(data["foundations"])
    assert out["tradition_already_exact"] is True
    assert out["observations_already_exact"] == len(data["observations"])
    assert not any(path.endswith("/observation") for path, _payload in client.posts)
    assert out["readback"] == {"verified": True}


def test_first_materialization_uses_atomic_create_only_claim(monkeypatch):
    seeder = _load_seeder()
    data = _load()

    class NewTreeClient:
        def __init__(self):
            self.posts: list[tuple[str, dict]] = []

        def get(self, _path, *, allow_not_found=False):
            assert allow_not_found is True
            return None

        def post(self, path, payload):
            self.posts.append((path, copy.deepcopy(payload)))
            return {"ok": True}

    client = NewTreeClient()
    monkeypatch.setattr(
        seeder,
        "verify_remote",
        lambda _data, _client, *, closed_questions=frozenset(): {"verified": True},
    )
    out = seeder.apply_manifest(data, client)

    assert client.posts[0][0] == f"/api/tree/{data['name']}?create_only=true"
    assert out["operations"] == (
        1 + len(data["nodes"]) + len(data["questions"])
        + len(data["foundations"]) + 1 + len(data["observations"])
    )


def test_tampered_observation_content_turns_manifest_red():
    seeder = _load_seeder()
    data = copy.deepcopy(_load())
    data["observations"][0]["content"] += " post-hoc mutation"

    with pytest.raises(seeder.ManifestError, match="content_hash"):
        seeder.validate_manifest(data)


def test_experiment_cannot_spawn_an_undeclared_frontier_identity():
    seeder = _load_seeder()
    data = copy.deepcopy(_load())
    experiment = next(node for node in data["nodes"] if node["algorithm"] == "open_experiment")
    experiment["open_question"] = "free-text question that would create a thirteenth frontier"

    with pytest.raises(seeder.ManifestError, match="declared qname"):
        seeder.validate_manifest(data)


def _resign(seeder, data: dict) -> dict:
    data["tree"]["manifest_digest"] = seeder.manifest_digest(data)
    return data


def _remote_fixture(
    seeder,
    data: dict,
    *,
    closed_questions: set[str] | frozenset[str] = frozenset(),
) -> dict[str, dict]:
    name = data["name"]
    encoded_name = seeder._url_segment(name)
    tree = seeder._tree_payload(data)
    tree.update(
        name=name,
        nodes=copy.deepcopy(data["nodes"]),
        frontier=[
            {
                **copy.deepcopy(question),
                "name": question["qname"],
                "status": (
                    "CLOSED" if question["qname"] in closed_questions else "OPEN"
                ),
            }
            for question in data["questions"]
        ],
        observations=[],
    )
    nodes_by_tag = {node["tag"]: node for node in tree["nodes"]}
    receipts_by_tag: dict[str, tuple[str, str]] = {}
    for question in tree["frontier"]:
        if question["status"] != "CLOSED":
            continue
        answer = next(
            node for node in tree["nodes"]
            if node.get("open_question") == question["name"]
        )
        head = hashlib.sha256(
            f"{name}/{answer['tag']}/{question['name']}".encode("utf-8")
        ).hexdigest()
        answer.update(
            verdict="progressive",
            verdict_source="scripted",
            current_receipt_sha=head,
            closed_question_count=1,
            pred_closes=question["name"],
            metric_name="fixture_metric",
            metric_value=1.0,
        )
        question["closed_events"] = [head]
        receipts_by_tag[answer["tag"]] = (head, question["name"])
    responses: dict[str, dict] = {
        f"/api/tree/{encoded_name}": tree,
        f"/api/tree/{encoded_name}/metrics": {
            "structure": {
                key: data["expected_topology"][key]
                for key in (
                    "edges",
                    "roots",
                    "components",
                    "multi_parent_nodes",
                    "typed_edge_ratio",
                )
            }
        },
        f"/api/tree/{encoded_name}/foundation": {
            "requirements": copy.deepcopy(data["foundations"]),
        },
        f"/api/tree/{encoded_name}/tradition": {
            **copy.deepcopy(data["tradition"]),
            "authority": "diagnostic_only",
        },
    }
    events_by_tag = {node["tag"]: [] for node in data["nodes"]}
    for observation in data["observations"]:
        events_by_tag[observation["tag"]].append(
            seeder._expected_observation_event(data, observation)
        )
    for tag, events in events_by_tag.items():
        responses[
            f"/api/tree/{encoded_name}/node/{seeder._url_segment(tag)}/events"
        ] = {"tag": tag, "count": len(events), "events": events}
    for tag, (head, question_name) in receipts_by_tag.items():
        base = f"/api/tree/{encoded_name}/node/{seeder._url_segment(tag)}/receipts"
        responses[base] = {
            "head": head,
            "cache_verdict": "progressive",
            "cache_source": "scripted",
            "receipts": [{
                "receipt_sha": head,
                "verdict": "progressive",
                "verdict_source": "scripted",
                "closes_question": question_name,
            }],
        }
        responses[base + "/verify"] = {
            "ok": True,
            "rederived": "progressive",
            "cache": "progressive",
            "from_receipt": True,
        }
    return responses


class _ReadClient:
    def __init__(self, responses: dict[str, dict]):
        self.responses = responses

    def get(self, path: str, *, allow_not_found: bool = False):
        if path not in self.responses:
            if allow_not_found:
                return None
            raise AssertionError(f"unexpected GET {path}")
        return copy.deepcopy(self.responses[path])


class _ApplyClient(_ReadClient):
    def __init__(self, responses: dict[str, dict]):
        super().__init__(responses)
        self.posts: list[tuple[str, dict]] = []

    def post(self, path: str, payload: dict):
        self.posts.append((path, copy.deepcopy(payload)))
        return {"ok": True}


def test_manifest_digest_canonical_keys_and_f5v2_state_are_pinned():
    seeder = _load_seeder()
    data = _load()
    raw = MANIFEST.read_text(encoding="utf-8")

    assert data["tree"]["manifest_owner"] == "codex-research-2026-07-28"
    assert data["tree"]["manifest_digest"] == seeder.manifest_digest(data)
    for stale in (
        "canon:hswm-semantic-hypergraph-llm-executed-functions",
        "kg:hswm-semantic-hypergraph-llm-executed-functions",
        "canon:hswm-open-self-similar-composable-plastic",
        "kg:hswm-open-self-similar-composable-plastic",
    ):
        assert stale not in raw
    for canonical in (
        "user-canon-hswm-functions-are-llm-executed-neural-net-2026-07-23",
        "user-canon-open-self-similar-hswm-2026-07-22",
    ):
        assert canonical in raw

    f5 = next(node for node in data["nodes"] if node["tag"] == "hswm-exp-consolidation")
    assert "exploratory_refuted" in f5["comment"]
    for token in (
        "USER_PRIMARY",
        "RATIFIED v2 (사용자 C4 verdict 2026-07-28)",
        "NOT MACHINE-LOCKED",
        "NO MEASUREMENT AUTHORIZED",
        "not server-registered",
        "unmeasured",
    ):
        assert token in f5["comment"] + " " + f5["limitation"]


def test_manifest_digest_and_dead_canon_alias_tampering_turn_red():
    seeder = _load_seeder()
    digest_tamper = copy.deepcopy(_load())
    digest_tamper["tree"]["doc"] += " post-signature mutation"
    with pytest.raises(seeder.ManifestError, match="manifest_digest"):
        seeder.validate_manifest(digest_tamper)

    alias_tamper = copy.deepcopy(_load())
    commitment = next(
        item for item in alias_tamper["tradition"]["commitments"]
        if item["commitment_id"] == "identity-semantic-hypergraph-llm-functions"
    )
    commitment["source_refs"] = ["kg:hswm-semantic-hypergraph-llm-executed-functions"]
    _resign(seeder, alias_tamper)
    with pytest.raises(seeder.ManifestError, match="dead HSWM canon alias"):
        seeder.validate_manifest(alias_tamper)


def test_external_source_roots_are_portable_but_mandatory_for_live_apply(
    monkeypatch, tmp_path,
):
    seeder = _load_seeder()
    monkeypatch.setitem(seeder._REPO_ROOTS, "HSWM", tmp_path / "absent-hswm")
    monkeypatch.setitem(seeder._REPO_ROOTS, "SYMPOSIUM", tmp_path / "absent-symposium")

    report = seeder.validate_manifest(_load())
    assert report["source_authorities_unavailable"] == ["HSWM", "SYMPOSIUM"]
    assert report["source_bindings_verified"] == 5
    assert report["fragment_bindings_verified"] == 2

    with pytest.raises(seeder.ManifestError, match="source root is unavailable"):
        seeder.validate_manifest(_load(), require_external_sources=True)


def test_repo_json_pointer_and_line_binding_tampering_turn_red():
    seeder = _load_seeder()

    pointer_tamper = copy.deepcopy(_load())
    f1 = next(node for node in pointer_tamper["nodes"] if node["tag"] == "hswm-exp-f1-retention")
    f1["result_path"] = "repo://HSWM/research/HSWM_RESEARCH_LEDGER.v1.json#/hypotheses/1"
    _resign(seeder, pointer_tamper)
    with pytest.raises(seeder.ManifestError, match="wrong hypothesis"):
        seeder.validate_manifest(pointer_tamper)

    line_tamper = copy.deepcopy(_load())
    state = next(node for node in line_tamper["nodes"] if node["tag"] == "hswm-state-h-w-a-f-pi")
    state["result_path"] = (
        "repo://SYMPOSIUM/HSWM/HSWM_MATH_DEFINITION_UNIFIED_2026-07-26.md#L50"
    )
    _resign(seeder, line_tamper)
    with pytest.raises(seeder.ManifestError, match="line binding|fragment binding"):
        seeder.validate_manifest(line_tamper)


def test_repo_bindings_reject_negative_index_traversal_and_hash_drift():
    seeder = _load_seeder()

    negative_index = copy.deepcopy(_load())
    consolidation = next(
        node for node in negative_index["nodes"]
        if node["tag"] == "hswm-exp-consolidation"
    )
    consolidation["result_path"] = (
        "repo://HSWM/research/HSWM_RESEARCH_LEDGER.v1.json#/hypotheses/-1"
    )
    _resign(seeder, negative_index)
    with pytest.raises(seeder.ManifestError, match="hypothesis binding|canonical"):
        seeder.validate_manifest(negative_index)

    traversal = copy.deepcopy(_load())
    traversal["nodes"][0]["result_path"] = "repo://lakatotree/../../outside"
    _resign(seeder, traversal)
    with pytest.raises(seeder.ManifestError, match="escapes|binding coverage"):
        seeder.validate_manifest(traversal)

    source_hash = copy.deepcopy(_load())
    binding = next(
        row for row in source_hash["source_bindings"]
        if row["reference"] == "repo:docs/FRONTIER_QUESTION_FSM.md"
    )
    binding["sha256"] = "0" * 64
    _resign(seeder, source_hash)
    with pytest.raises(seeder.ManifestError, match="source byte binding mismatch"):
        seeder.validate_manifest(source_hash)

    fragment_hash = copy.deepcopy(_load())
    fragment_hash["fragment_bindings"][-1]["target_sha256"] = "0" * 64
    _resign(seeder, fragment_hash)
    with pytest.raises(seeder.ManifestError, match="fragment target binding mismatch"):
        seeder.validate_manifest(fragment_hash)


@pytest.mark.parametrize("score_key", ["provenance_score", "supply_chain_score"])
def test_summary_only_score_ceiling_is_enforced(score_key):
    seeder = _load_seeder()
    data = _load()
    assert data["observation_defaults"][score_key] <= seeder.SUMMARY_ONLY_SCORE_CEILING

    tampered = copy.deepcopy(data)
    tampered["observations"][0][score_key] = seeder.SUMMARY_ONLY_SCORE_CEILING + 0.01
    _resign(seeder, tampered)
    with pytest.raises(seeder.ManifestError, match="without a source snapshot"):
        seeder.validate_manifest(tampered)


def test_every_rival_observation_has_a_valid_longinus_binding():
    seeder = _load_seeder()
    data = _load()
    assert len(data["observations"]) == 12
    for observation in data["observations"]:
        assert observation["rival_name"]
        assert observation["rival_relation"] in {"supports", "contradicts", "qualifies"}
        assert observation["comparison_axes"]
        assert observation["longinus_refs"]
        event = seeder._expected_observation_event(data, observation)
        assert event["rival_links"]
        assert event["longinus_refs"]


def test_rival_pair_and_longinus_requirements_turn_incomplete_embeddings_red():
    seeder = _load_seeder()
    missing_pair = copy.deepcopy(_load())
    missing_pair["observations"][0].pop("rival_relation")
    _resign(seeder, missing_pair)
    with pytest.raises(seeder.ManifestError, match="rival_name and rival_relation"):
        seeder.validate_manifest(missing_pair)

    missing_longinus = copy.deepcopy(_load())
    missing_longinus["observations"][0]["longinus_refs"] = []
    _resign(seeder, missing_longinus)
    with pytest.raises(seeder.ManifestError, match="requires Longinus refs"):
        seeder.validate_manifest(missing_longinus)


def test_longinus_source_identity_cannot_drift_or_alias_two_paths():
    seeder = _load_seeder()
    wrong_path = copy.deepcopy(_load())
    wrong_path["observations"][0]["longinus_refs"][0]["sourcePath"] = (
        "https://example.invalid/wrong-source"
    )
    _resign(seeder, wrong_path)
    with pytest.raises(seeder.ManifestError, match="not the observation source"):
        seeder.validate_manifest(wrong_path)

    alias = copy.deepcopy(_load())
    alias["observations"][1]["longinus_refs"][0]["sourceId"] = (
        alias["observations"][0]["longinus_refs"][0]["sourceId"]
    )
    _resign(seeder, alias)
    with pytest.raises(seeder.ManifestError, match="multiple source paths"):
        seeder.validate_manifest(alias)


def test_bearer_transport_and_redirects_fail_closed():
    seeder = _load_seeder()
    for url in (
        "http://127.0.0.1:55170",
        "http://[::1]:55170",
        "http://localhost:55170",
        "https://lakatotree.example",
    ):
        client = seeder.ApiClient(url, "secret")
        assert any(
            isinstance(handler, seeder._FailClosedRedirect)
            for handler in client._opener.handlers
        )

    for unsafe in (
        "http://192.168.0.26:55170",
        "http://localhost.example:55170",
        "https://user:password@lakatotree.example",
        "https://lakatotree.example?token=leak",
    ):
        with pytest.raises(ValueError):
            seeder.ApiClient(unsafe, "secret")

    handler = seeder._FailClosedRedirect()
    req = seeder.request.Request(
        "https://lakatotree.example/api/tree/T",
        headers={"Authorization": "Bearer secret"},
    )
    with pytest.raises(seeder.error.HTTPError, match="redirect blocked"):
        handler.redirect_request(
            req,
            None,
            302,
            "Found",
            {},
            "http://attacker.example/steal",
        )


def test_faithful_exact_remote_readback_passes_every_semantic_layer():
    seeder = _load_seeder()
    data = _load()
    report = seeder.verify_remote(data, _ReadClient(_remote_fixture(seeder, data)))

    assert report["manifest_owner"] == data["tree"]["manifest_owner"]
    assert report["manifest_digest"] == data["tree"]["manifest_digest"]
    assert report["nodes"] == len(data["nodes"])
    assert report["questions"] == len(data["questions"])
    assert report["foundations"] == len(data["foundations"])
    assert report["observations"] == len(data["observations"])


@pytest.mark.parametrize(
    "corruption",
    [
        "missing_head",
        "wrong_prediction_binding",
        "missing_closure_event",
        "broken_receipt_chain",
        "wrong_receipt_question",
    ],
)
def test_closed_question_requires_the_exact_verifying_closure_receipt(corruption):
    seeder = _load_seeder()
    data = _load()
    question_name = "q-hswm-f1-retention"
    responses = _remote_fixture(seeder, data, closed_questions={question_name})
    tree = responses[f"/api/tree/{data['name']}"]
    node = next(item for item in tree["nodes"] if item.get("open_question") == question_name)
    question = next(item for item in tree["frontier"] if item["name"] == question_name)
    base = (
        f"/api/tree/{data['name']}/node/"
        f"{seeder._url_segment(node['tag'])}/receipts"
    )

    if corruption == "missing_head":
        node["current_receipt_sha"] = ""
    elif corruption == "wrong_prediction_binding":
        node["pred_closes"] = "q-other"
    elif corruption == "missing_closure_event":
        question["closed_events"] = []
    elif corruption == "broken_receipt_chain":
        responses[base + "/verify"]["ok"] = False
    elif corruption == "wrong_receipt_question":
        responses[base]["receipts"][0]["closes_question"] = "q-other"

    with pytest.raises(RuntimeError, match="receipt|prediction|CLOSES_QUESTION"):
        seeder.verify_remote(
            data,
            _ReadClient(responses),
            closed_questions={question_name},
        )


def _corrupt_remote(responses: dict[str, dict], data: dict, kind: str) -> None:
    name = data["name"]
    tree_path = f"/api/tree/{name}"
    if kind == "node_comment":
        responses[tree_path]["nodes"][0]["comment"] = "WRONG"
    elif kind == "frontier_cost":
        responses[tree_path]["frontier"][0]["cost"] = 999.0
    elif kind == "observation_content_hash":
        path = next(
            path for path, value in responses.items()
            if path.endswith("/events") and value.get("events")
        )
        responses[path]["events"][0]["payload"]["content_hash"] = "WRONG"
    elif kind == "foundation_refs":
        responses[f"/api/tree/{name}/foundation"]["requirements"][0][
            "evidence_refs"
        ] = ["WRONG"]
    elif kind == "tradition_commitment":
        responses[f"/api/tree/{name}/tradition"]["commitments"][0][
            "statement"
        ] = "WRONG"
    else:
        raise AssertionError(f"unknown corruption {kind}")


@pytest.mark.parametrize(
    "corruption",
    [
        "node_comment",
        "frontier_cost",
        "observation_content_hash",
        "foundation_refs",
        "tradition_commitment",
    ],
)
def test_exact_readback_rejects_each_independent_semantic_corruption(corruption):
    seeder = _load_seeder()
    data = _load()
    responses = _remote_fixture(seeder, data)
    _corrupt_remote(responses, data, corruption)

    with pytest.raises(RuntimeError, match="mismatch"):
        seeder.verify_remote(data, _ReadClient(responses))


def test_identity_collision_fails_before_any_post():
    seeder = _load_seeder()
    data = _load()
    responses = _remote_fixture(seeder, data)
    responses[f"/api/tree/{data['name']}"]["doc"] = responses[
        f"/api/tree/{data['name']}"
    ]["doc"].replace(data["tree"]["manifest_digest"], "0" * 64)
    client = _ApplyClient(responses)

    with pytest.raises(RuntimeError, match="owner/digest collision"):
        seeder.apply_manifest(data, client)
    assert client.posts == []


def test_stale_same_observation_id_fails_preflight_before_any_post():
    seeder = _load_seeder()
    data = _load()
    responses = _remote_fixture(seeder, data)
    event_path = next(
        path for path, value in responses.items()
        if path.endswith("/events") and value.get("events")
    )
    expected_id = responses[event_path]["events"][0]["id"]
    responses[event_path]["events"][0]["payload"]["content_hash"] = "stale-same-id"
    assert responses[event_path]["events"][0]["id"] == expected_id
    client = _ApplyClient(responses)

    with pytest.raises(RuntimeError, match="remote observation immutable payload mismatch"):
        seeder.apply_manifest(data, client)
    assert client.posts == []
