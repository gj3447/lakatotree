#!/usr/bin/env python3
"""Validate and restart-safely materialize the dense HSWM LargerAI programme.

Default mode is a no-write validation.  ``--apply`` is required before any
HTTP mutation.  The script never deletes or rewrites the older HSWM tree; it
upserts only the uniquely named successor programme declared by the manifest.
The public API has no one-shot bulk transaction, so a failed run may leave a
prefix applied; every step is monotone/upserted, CLOSED questions are preserved,
and a rerun resumes safely before an exact readback gate checks the whole result.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import sys
from urllib import error, parse, request


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from lakatos.engine import (  # noqa: E402
    EmbeddedInternetEvidence,
    InternetObservation,
    LonginusRef,
    RivalProgrammeLink,
    SourceCredibilityScore,
    TheoryEmbedding,
)
from lakatos.world_gates import scan_prompt_injection, web_gate  # noqa: E402
from lakatos.verdicts import QUESTION_ANSWER_VERDICTS  # noqa: E402
from server.contexts.tree.schemas import ObservationIn  # noqa: E402


DEFAULT_MANIFEST = ROOT / "docs" / "data" / "hswm_larger_ai_programme_20260728.json"
DEFAULT_URL = "http://127.0.0.1:55170"
TREE_IDENTITY_PREFIX = "lakatotree_manifest_identity:"
SUMMARY_ONLY_SCORE_CEILING = 0.5
_SCORE_KEYS = (
    "source_class_weight",
    "link_authority",
    "primary_source_bonus",
    "provenance_score",
    "corroboration_score",
    "recency_score",
    "supply_chain_score",
)
_NODE_FIELDS = (
    "tag", "author", "verdict", "result_path", "algorithm", "comment",
    "limitation", "open_question",
)
_TREE_FIELDS = (
    "name", "title", "hard_core", "frontier_rule", "doc", "coverage_status",
    "coverage_statement", "coverage_backlog", "ontology", "require_novel_anchor",
    "require_certified_evidence", "assurance_tier", "cycle_budget",
)
_REPO_ROOTS = {
    "HSWM": Path(os.environ.get(
        "LAKATOTREE_HSWM_SOURCE_ROOT",
        ROOT.parent / "SYMPOSIUM" / "GIT" / "HSWM",
    )),
    "SYMPOSIUM": Path(os.environ.get(
        "LAKATOTREE_SYMPOSIUM_SOURCE_ROOT",
        ROOT.parent / "SYMPOSIUM",
    )),
    "lakatotree": ROOT,
}
_HYPOTHESIS_BINDINGS = {
    "hswm-exp-f1-retention": (
        "repo://HSWM/research/HSWM_RESEARCH_LEDGER.v1.json#/hypotheses/0",
        "F1-larger-ai-baselines-and-retention",
    ),
    "hswm-exp-topology-mediation": (
        "repo://HSWM/research/HSWM_RESEARCH_LEDGER.v1.json#/hypotheses/5",
        "topology-causal-mediation",
    ),
    "hswm-exp-cross-agent-transfer": (
        "repo://HSWM/research/HSWM_RESEARCH_LEDGER.v1.json#/hypotheses/4",
        "weight-only-agent-transfer",
    ),
    "hswm-exp-consolidation": (
        "repo://HSWM/research/HSWM_RESEARCH_LEDGER.v1.json#/hypotheses/6",
        "long-term-consolidation-sleep",
    ),
}
_LINE_BINDINGS = {
    "hswm-state-h-w-a-f-pi": (
        "repo://SYMPOSIUM/HSWM/HSWM_MATH_DEFINITION_UNIFIED_2026-07-26.md#L48",
        "### 2.1 객체",
    ),
    "hswm-ports-connectors-composition": (
        "repo://SYMPOSIUM/HSWM/SPEC_OPEN_SELF_SIMILAR_HSWM_2026-07-22.md#L88",
        "## 4. 타입 계약",
    ),
    "hswm-semantic-w-operators": (
        "repo://SYMPOSIUM/HSWM/SPEC_SHARED_HYPERGRAPH_NN_SEMANTIC_WEIGHT_2026-07-22.md#L24",
        "## 2. Is semantics *only* the hypergraph?",
    ),
    "hswm-exp-consensus-containment": (
        "repo://SYMPOSIUM/HSWM/HSWM_MATH_DEFINITION_UNIFIED_2026-07-26.md#L149",
        "| **L3 더 큰 AI (⊇합의)** | 스코프 격상 방향 | **OPEN** — 수학적 내용 아직 없음 | D5 |",
    ),
    "hswm-exp-state-sufficiency": (
        "repo://SYMPOSIUM/HSWM/HSWM_MATH_DEFINITION_UNIFIED_2026-07-26.md#L48",
        "### 2.1 객체",
    ),
    "hswm-exp-interface-composition": (
        "repo://SYMPOSIUM/HSWM/SPEC_OPEN_SELF_SIMILAR_HSWM_2026-07-22.md#L88",
        "## 4. 타입 계약",
    ),
}


class ManifestError(ValueError):
    """The programme cannot be safely materialized."""


def load_manifest(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def manifest_digest(data: dict) -> str:
    projection = json.loads(json.dumps(data, ensure_ascii=False))
    projection.setdefault("tree", {}).pop("manifest_digest", None)
    return hashlib.sha256(_canonical_json(projection).encode("utf-8")).hexdigest()


def _manifest_identity(data: dict) -> dict[str, str]:
    tree = data.get("tree") or {}
    expected = manifest_digest(data)
    if tree.get("manifest_digest") != expected:
        raise ManifestError("tree manifest_digest does not match canonical manifest")
    owner = str(tree.get("manifest_owner") or "").strip()
    if not owner:
        raise ManifestError("tree manifest_owner is required")
    return {"manifest_owner": owner, "manifest_digest": expected}


def _tree_payload(data: dict) -> dict:
    payload = dict(data["tree"])
    identity = _manifest_identity(data)
    payload.pop("manifest_owner")
    payload.pop("manifest_digest")
    payload["ontology"] = _canonical_json(payload["ontology"])
    marker = TREE_IDENTITY_PREFIX + _canonical_json(identity)
    doc = str(payload.get("doc") or "").rstrip()
    payload["doc"] = f"{doc}\n\n{marker}" if doc else marker
    return payload


def _remote_identity(existing: dict) -> dict | None:
    lines = [
        line for line in str(existing.get("doc") or "").splitlines()
        if line.startswith(TREE_IDENTITY_PREFIX)
    ]
    if len(lines) != 1:
        return None
    try:
        value = json.loads(lines[0][len(TREE_IDENTITY_PREFIX):])
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or set(value) != {"manifest_owner", "manifest_digest"}:
        return None
    return {key: str(value[key]) for key in ("manifest_owner", "manifest_digest")}


def _validate_bearer_transport(base_url: str, token: str) -> str:
    parsed = parse.urlsplit(base_url)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment):
        raise ValueError("base URL must be an absolute HTTP(S) origin without credentials/query/fragment")
    if token and parsed.scheme == "http":
        host = parsed.hostname.lower()
        loopback = host == "localhost"
        if not loopback:
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = False
        if not loopback:
            raise ValueError(
                "Bearer tokens require HTTPS for remote URLs; HTTP is allowed only on loopback"
            )
    return base_url.rstrip("/")


class _FailClosedRedirect(request.HTTPRedirectHandler):
    """Never replay an authenticated request to an unvalidated redirect target."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        raise error.HTTPError(
            req.full_url,
            code,
            f"redirect blocked (target={newurl!r})",
            headers,
            fp,
        )


def _resolve_json_pointer(value, pointer: str):
    if not pointer.startswith("/"):
        raise ManifestError(f"invalid JSON Pointer fragment: {pointer!r}")
    current = value
    for raw_token in pointer[1:].split("/"):
        token = raw_token.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not (token == "0" or (token.isdigit() and not token.startswith("0"))):
                raise ManifestError(f"JSON Pointer list index is not canonical: {token!r}")
            try:
                index = int(token)
                current = current[index]
            except (ValueError, IndexError) as exc:
                raise ManifestError(f"JSON Pointer list index does not resolve: {token!r}") from exc
        elif isinstance(current, dict):
            if token not in current:
                raise ManifestError(f"JSON Pointer key does not resolve: {token!r}")
            current = current[token]
        else:
            raise ManifestError(f"JSON Pointer traverses scalar at {token!r}")
    return current


def _resolve_repo_reference(reference: str):
    """Resolve a repository URI to an existing file and exact fragment target."""

    if not reference.startswith("repo:"):
        raise ManifestError(f"not a repository reference: {reference!r}")
    locator = reference[len("repo:"):]
    if locator.startswith("//"):
        authority_path = locator[2:]
        authority, separator, relative_fragment = authority_path.partition("/")
        if not separator or authority not in _REPO_ROOTS:
            raise ManifestError(f"unknown repository authority: {reference!r}")
        base = _REPO_ROOTS[authority]
    else:
        relative_fragment = locator.lstrip("/")
        base = ROOT
    relative_path, has_fragment, fragment = relative_fragment.partition("#")
    if not relative_path:
        raise ManifestError(f"repository reference has no path: {reference!r}")
    base = base.resolve()
    path = (base / relative_path).resolve()
    try:
        path.relative_to(base)
    except ValueError as exc:
        raise ManifestError(f"repository reference escapes its authority: {reference!r}") from exc
    if not path.is_file():
        raise ManifestError(f"repository source file does not exist: {reference!r}")
    if not has_fragment:
        return path
    if fragment.startswith("/"):
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ManifestError(f"JSON Pointer source is not readable JSON: {reference!r}") from exc
        return _resolve_json_pointer(document, fragment)
    if fragment.startswith("L") and fragment[1:].isdigit():
        line_number = int(fragment[1:])
        lines = path.read_text(encoding="utf-8").splitlines()
        if line_number < 1 or line_number > len(lines) or not lines[line_number - 1].strip():
            raise ManifestError(f"line fragment does not resolve to content: {reference!r}")
        return lines[line_number - 1]
    raise ManifestError(f"repository fragment must be JSON Pointer or #L<number>: {reference!r}")


def _reference_authority(reference: str) -> str:
    locator = reference[len("repo:"):]
    if not locator.startswith("//"):
        return "lakatotree"
    return locator[2:].partition("/")[0]


def _target_digest(value) -> str:
    raw = (value if isinstance(value, str) else _canonical_json(value)).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _graph_counts(nodes: list[dict]) -> dict[str, int | float]:
    tags = {node["tag"] for node in nodes}
    adjacency = {tag: set() for tag in tags}
    edges = 0
    typed = 0
    for node in nodes:
        for edge in node.get("parent_edges", []):
            parent = edge["tag"]
            edges += 1
            if edge.get("relation_kind") and edge.get("evidence_ref"):
                typed += 1
            if parent not in adjacency:
                continue
            adjacency[node["tag"]].add(parent)
            adjacency[parent].add(node["tag"])
    components = 0
    unseen = set(tags)
    while unseen:
        components += 1
        stack = [unseen.pop()]
        while stack:
            current = stack.pop()
            reached = adjacency[current] & unseen
            unseen -= reached
            stack.extend(reached)
    return {
        "nodes": len(nodes),
        "edges": edges,
        "roots": sum(not node.get("parent_edges") for node in nodes),
        "components": components,
        "multi_parent_nodes": sum(len(node.get("parent_edges", [])) > 1 for node in nodes),
        "typed_edge_ratio": round(typed / edges, 6) if edges else 0.0,
    }


def validate_manifest(data: dict, *, require_external_sources: bool = False) -> dict:
    errors: list[str] = []
    nodes = data.get("nodes") or []
    questions = data.get("questions") or []
    foundations = data.get("foundations") or []
    observations = data.get("observations") or []
    tree = data.get("tree") or {}
    ontology = tree.get("ontology") or {}
    entities = ontology.get("entities") or {}

    if data.get("schema_version") != "lakatotree-research-programme/v1":
        errors.append("unknown schema_version")
    if data.get("name") != "LakatosTree_HSWM_LargerAI_20260728":
        errors.append("successor tree name is not pinned")
    try:
        _manifest_identity(data)
    except ManifestError as exc:
        errors.append(str(exc))
    if TREE_IDENTITY_PREFIX in str(tree.get("doc") or ""):
        errors.append("base tree doc must not contain a runtime identity marker")
    manifest_text = _canonical_json(data)
    for stale in (
        "canon:hswm-semantic-hypergraph-llm-executed-functions",
        "kg:hswm-semantic-hypergraph-llm-executed-functions",
        "canon:hswm-open-self-similar-composable-plastic",
        "kg:hswm-open-self-similar-composable-plastic",
    ):
        if stale in manifest_text:
            errors.append(f"dead HSWM canon alias remains: {stale}")
    tags = [node.get("tag") for node in nodes]
    if not tags or any(not isinstance(tag, str) or not tag for tag in tags):
        errors.append("every node needs a non-empty tag")
    if len(tags) != len(set(tags)):
        errors.append("node tags must be unique")

    seen: set[str] = set()
    for node in nodes:
        tag = node.get("tag") or "<missing>"
        entity = node.get("algorithm")
        if entity not in entities:
            errors.append(f"{tag}: undeclared ontology entity {entity!r}")
            required = []
        else:
            required = entities[entity].get("required") or []
        for field in required:
            if node.get(field) in (None, ""):
                errors.append(f"{tag}: required field {field!r} is empty")
        parents_seen: set[str] = set()
        for edge in node.get("parent_edges") or []:
            parent = edge.get("tag")
            if parent not in set(tags):
                errors.append(f"{tag}: unknown parent {parent!r}")
            if parent not in seen:
                errors.append(f"{tag}: parent {parent!r} is not earlier in the DAG")
            if parent in parents_seen:
                errors.append(f"{tag}: duplicate parent edge {parent!r}")
            parents_seen.add(parent)
            if not isinstance(edge.get("inferred", False), bool):
                errors.append(f"{tag}->{parent}: inferred must be boolean")
            if not (edge.get("relation_kind") or "").strip():
                errors.append(f"{tag}->{parent}: relation_kind is empty")
            if not (edge.get("evidence_ref") or "").strip():
                errors.append(f"{tag}->{parent}: typed edge lacks evidence_ref")
        seen.add(tag)

    repo_references: set[str] = set()
    for node in nodes:
        repo_references.update(
            reference for reference in [node.get("result_path")]
            if isinstance(reference, str) and reference.startswith("repo:")
        )
        repo_references.update(
            edge["evidence_ref"] for edge in (node.get("parent_edges") or [])
            if str(edge.get("evidence_ref") or "").startswith("repo:")
        )
    for foundation in foundations:
        repo_references.update(
            reference for reference in (foundation.get("evidence_refs") or [])
            if str(reference).startswith("repo:")
        )
    for commitment in (data.get("tradition") or {}).get("commitments") or []:
        repo_references.update(
            reference for reference in (commitment.get("source_refs") or [])
            if str(reference).startswith("repo:")
        )
    for item in observations:
        repo_references.update(
            reference for reference in (item.get("evidence_refs") or [])
            if str(reference).startswith("repo:")
        )
        repo_references.update(
            ref.get("sourcePath") for ref in (item.get("longinus_refs") or [])
            if str(ref.get("sourcePath") or "").startswith("repo:")
        )
    base_references = {reference.split("#", 1)[0] for reference in repo_references}
    fragment_references = {reference for reference in repo_references if "#" in reference}
    source_rows = data.get("source_bindings") or []
    fragment_rows = data.get("fragment_bindings") or []
    source_map = {row.get("reference"): row.get("sha256") for row in source_rows}
    fragment_map = {
        row.get("reference"): row.get("target_sha256") for row in fragment_rows
    }
    if len(source_map) != len(source_rows):
        errors.append("source_bindings references must be unique")
    if len(fragment_map) != len(fragment_rows):
        errors.append("fragment_bindings references must be unique")
    if set(source_map) != base_references:
        errors.append(
            "source binding coverage mismatch: "
            f"missing={sorted(base_references - set(source_map))!r}, "
            f"extra={sorted(set(source_map) - base_references)!r}"
        )
    if set(fragment_map) != fragment_references:
        errors.append(
            "fragment binding coverage mismatch: "
            f"missing={sorted(fragment_references - set(fragment_map))!r}, "
            f"extra={sorted(set(fragment_map) - fragment_references)!r}"
        )
    unavailable_authorities: set[str] = set()
    verified_source_bindings = 0
    verified_fragment_bindings = 0
    for reference in sorted(repo_references):
        authority = _reference_authority(reference)
        root = _REPO_ROOTS.get(authority)
        if root is None:
            errors.append(f"unknown repository authority: {reference!r}")
            continue
        if not root.exists():
            unavailable_authorities.add(authority)
            if require_external_sources:
                errors.append(f"required repository source root is unavailable: {authority}")
            continue
        try:
            base_reference = reference.split("#", 1)[0]
            path = _resolve_repo_reference(base_reference)
            observed_source_sha = hashlib.sha256(path.read_bytes()).hexdigest()
            if source_map.get(base_reference) != observed_source_sha:
                errors.append(f"source byte binding mismatch: {base_reference!r}")
            else:
                verified_source_bindings += 1
            if "#" in reference:
                target = _resolve_repo_reference(reference)
                if fragment_map.get(reference) != _target_digest(target):
                    errors.append(f"fragment target binding mismatch: {reference!r}")
                else:
                    verified_fragment_bindings += 1
        except ManifestError as exc:
            errors.append(str(exc))
    by_tag = {node.get("tag"): node for node in nodes}
    for tag, (expected_reference, hypothesis_id) in _HYPOTHESIS_BINDINGS.items():
        try:
            observed_reference = str(by_tag[tag]["result_path"])
            if observed_reference != expected_reference:
                errors.append(
                    f"{tag}: wrong hypothesis binding; expected={expected_reference!r}"
                )
                continue
            if _REPO_ROOTS["HSWM"].exists():
                target = _resolve_repo_reference(observed_reference)
                if not isinstance(target, dict) or target.get("hypothesis_id") != hypothesis_id:
                    errors.append(
                        f"{tag}: result_path resolves to the wrong hypothesis; "
                        f"expected={hypothesis_id!r}"
                    )
        except (KeyError, ManifestError) as exc:
            errors.append(f"{tag}: exact hypothesis binding failed: {exc}")
    for tag, (expected_reference, expected_line) in _LINE_BINDINGS.items():
        try:
            observed_reference = str(by_tag[tag]["result_path"])
            if observed_reference != expected_reference:
                errors.append(f"{tag}: exact line binding failed; expected={expected_reference!r}")
                continue
            if _REPO_ROOTS["SYMPOSIUM"].exists():
                target = _resolve_repo_reference(observed_reference)
                if target != expected_line:
                    errors.append(
                        f"{tag}: line target drift; expected heading={expected_line!r}"
                    )
        except (KeyError, ManifestError) as exc:
            errors.append(f"{tag}: exact line binding failed: {exc}")

    counts = _graph_counts(nodes) if tags and len(tags) == len(set(tags)) else {}
    counts.update(
        observations=len(observations),
        questions=len(questions),
        foundations=len(foundations),
    )
    expected = data.get("expected_topology") or {}
    for key, want in expected.items():
        if counts.get(key) != want:
            errors.append(f"topology {key}: observed={counts.get(key)!r}, expected={want!r}")

    hard_core = tree.get("hard_core") or ""
    for phrase in ("더 큰 범위의 AI", "합의", "OM family #8", "CHU", "LLM", "하이퍼그래프"):
        if phrase not in hard_core:
            errors.append(f"hard core missing user-canon phrase: {phrase}")
    if "HSWM 표준" in hard_core or "재배맨 #4" in hard_core:
        errors.append("hard core contains the stale Jaebaeman/standard placement")
    if tree.get("coverage_status") != "partial" or not tree.get("coverage_backlog"):
        errors.append("programme must remain partial with an explicit backlog")
    if not tree.get("require_novel_anchor"):
        errors.append("novel efficacy claims must require a server anchor")

    question_names = [item.get("qname") for item in questions]
    if len(question_names) != len(set(question_names)) or any(not name for name in question_names):
        errors.append("frontier question names must be unique and non-empty")
    declared_questions = set(question_names)
    opened_questions: list[str] = []
    for node in nodes:
        opened = node.get("open_question")
        if opened and opened not in declared_questions:
            errors.append(
                f"{node.get('tag')}: open_question must reference a declared qname, got {opened!r}"
            )
        if opened:
            opened_questions.append(opened)
    if set(opened_questions) != declared_questions or len(opened_questions) != len(declared_questions):
        errors.append(
            "every frontier question must bind to exactly one answer node: "
            f"unbound={sorted(declared_questions - set(opened_questions))!r}, "
            f"duplicates={sorted(name for name in set(opened_questions) if opened_questions.count(name) > 1)!r}"
        )
    foundation_names = [item.get("name") for item in foundations]
    if len(foundation_names) != len(set(foundation_names)) or any(not name for name in foundation_names):
        errors.append("foundation names must be unique and non-empty")
    for item in foundations:
        if item.get("status") == "satisfied" and not item.get("evidence_refs"):
            errors.append(f"foundation {item.get('name')}: satisfied without evidence")

    event_ids: set[str] = set()
    longinus_source_paths: dict[str, str] = {}
    node_tags = set(tags)
    defaults = data.get("observation_defaults") or {}
    for item in observations:
        event_id = item.get("event_id")
        if not event_id or event_id in event_ids:
            errors.append(f"observation event id is empty or duplicate: {event_id!r}")
        event_ids.add(event_id)
        if item.get("tag") not in node_tags:
            errors.append(f"{event_id}: observation targets unknown node")
        content = item.get("content") or ""
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if item.get("content_hash") != digest:
            errors.append(f"{event_id}: content_hash does not bind exact extracted content")
        if not str(item.get("url") or "").startswith("https://"):
            errors.append(f"{event_id}: source URL must be https")
        if item.get("lakatos_location") not in {
            "hard_core", "protective_belt", "positive_heuristic", "negative_heuristic"
        }:
            errors.append(f"{event_id}: invalid Lakatos location")
        effective = {**defaults, **item}
        if not item.get("raw_snapshot_path"):
            for key in ("provenance_score", "supply_chain_score"):
                if float(effective.get(key) or 0.0) > SUMMARY_ONLY_SCORE_CEILING:
                    errors.append(
                        f"{event_id}: summary-only {key} exceeds "
                        f"{SUMMARY_ONLY_SCORE_CEILING} without a source snapshot"
                    )
        rival_present = any(effective.get(key) for key in (
            "rival_name", "rival_relation", "rival_node", "comparison_axes"
        ))
        if rival_present and not (effective.get("rival_name") and effective.get("rival_relation")):
            errors.append(f"{event_id}: rival evidence requires rival_name and rival_relation")
        if rival_present and not effective.get("longinus_refs"):
            errors.append(f"{event_id}: rival evidence requires Longinus refs")
        try:
            observation = ObservationIn(**{
                key: value for key, value in effective.items() if key != "tag"
            })
            allowed_source_paths = set(observation.evidence_refs) | {observation.url}
            for ref in observation.longinus_refs:
                if ref.sourcePath not in allowed_source_paths:
                    raise ValueError(
                        f"Longinus sourcePath {ref.sourcePath!r} is not the observation source"
                    )
                previous_path = longinus_source_paths.setdefault(ref.sourceId, ref.sourcePath)
                if previous_path != ref.sourcePath:
                    raise ValueError(
                        f"Longinus sourceId {ref.sourceId!r} maps to multiple source paths"
                    )
            injection = scan_prompt_injection(observation.content)
            obs_gate = web_gate({
                "url": observation.url,
                "retrieved_at": observation.retrieved_at,
                "content_hash": observation.content_hash,
                "raw_snapshot_path": observation.raw_snapshot_path,
                "source_type": observation.source_type,
                "lakatos_location": observation.lakatos_location,
                **{key: getattr(observation, key) for key in _SCORE_KEYS},
            }, injection=injection)
            if not obs_gate.passed:
                raise ValueError(f"G-Web failed: {list(obs_gate.reasons)}")
            score = SourceCredibilityScore(
                injection_penalty=injection["risk"],
                **{key: (getattr(observation, key) or 0.0) for key in _SCORE_KEYS},
            )
            longinus_refs = tuple(LonginusRef(
                sourceId=ref.sourceId, sourcePath=ref.sourcePath,
                layer=ref.layer, note=ref.note,
            ) for ref in observation.longinus_refs)
            rival_links = ()
            if rival_present:
                rival_links = (RivalProgrammeLink(
                    programme=observation.rival_name,
                    relation=observation.rival_relation,
                    rival_node=observation.rival_node,
                    comparison_axes=tuple(observation.comparison_axes),
                    evidence_refs=tuple(observation.evidence_refs or [observation.url]),
                ),)
            EmbeddedInternetEvidence(
                observation=InternetObservation(
                    name=observation.event_id,
                    url=observation.url,
                    query=observation.query,
                    retrieved_at=datetime.fromisoformat(
                        observation.retrieved_at.replace("Z", "+00:00")
                    ),
                    content_hash=observation.content_hash or observation.raw_snapshot_path,
                    fetch_tool=observation.fetch_tool,
                    source_type=observation.source_type,
                    credibility=score,
                    raw_snapshot_path=observation.raw_snapshot_path or None,
                ),
                tree_name=data["name"],
                node_tag=item.get("tag") or "",
                embedding=TheoryEmbedding(
                    lakatos_location=observation.lakatos_location,
                    theoretical_basis=observation.theory_basis,
                    foundation_refs=tuple(observation.foundation_refs),
                    longinus_refs=longinus_refs,
                ),
                rival_links=rival_links,
            ).kg_projection()
        except Exception as exc:  # noqa: BLE001 - aggregate every manifest contract violation
            errors.append(f"{event_id}: production observation contract failed: {exc}")

    open_nodes = [node for node in nodes if node.get("algorithm") == "open_experiment"]
    if len(open_nodes) < 5:
        errors.append("the discriminating experiment frontier is too sparse")
    if any(node.get("metric_name") is not None or node.get("metric_value") is not None for node in nodes):
        errors.append("unjudged manifest nodes must not self-assert measurements")

    if errors:
        raise ManifestError("\n".join(f"- {message}" for message in errors))
    return {
        "ok": True,
        "tree": data["name"],
        "topology": counts,
        "scientific_progress_verdicts": 0,
        "efficacy_claims": 0,
        "source_bindings_verified": len(base_references - {
            reference.split("#", 1)[0]
            for reference in repo_references
            if _reference_authority(reference) in unavailable_authorities
        }),
        "fragment_bindings_verified": len(fragment_references - {
            reference for reference in fragment_references
            if _reference_authority(reference) in unavailable_authorities
        }),
        "source_authorities_unavailable": sorted(unavailable_authorities),
    }


class ApiClient:
    def __init__(self, base_url: str, token: str):
        self.base_url = _validate_bearer_transport(base_url, token)
        self.token = token
        self._opener = request.build_opener(_FailClosedRedirect())

    def post(self, path: str, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = request.Request(self.base_url + path, data=body, headers=headers, method="POST")
        try:
            with self._opener.open(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"POST {path} -> HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"POST {path} failed: {exc.reason}") from exc

    def get(self, path: str, *, allow_not_found: bool = False) -> dict | None:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        req = request.Request(self.base_url + path, headers=headers, method="GET")
        try:
            with self._opener.open(req, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            if allow_not_found and exc.code == 404:
                return None
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(f"GET {path} -> HTTP {exc.code}: {detail}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"GET {path} failed: {exc.reason}") from exc


def _url_segment(value: str) -> str:
    return parse.quote(value, safe="")


def _require_equal(label: str, expected, actual) -> None:
    if _canonical_json(expected) != _canonical_json(actual):
        raise RuntimeError(f"{label} mismatch: expected={expected!r}, observed={actual!r}")


def _tree_projection(data: dict, tree: dict) -> dict:
    return {key: tree.get(key) for key in _TREE_FIELDS}


def _expected_tree_projection(data: dict) -> dict:
    payload = _tree_payload(data)
    return {key: (data["name"] if key == "name" else payload.get(key)) for key in _TREE_FIELDS}


def _edge_projection(node: dict) -> list[dict]:
    return sorted(({
        "tag": edge.get("tag") or "",
        "relation_kind": edge.get("relation_kind") or "knowledge_inheritance",
        "evidence_ref": edge.get("evidence_ref") or "",
        "inferred": bool(edge.get("inferred")),
    } for edge in (node.get("parent_edges") or [])), key=_canonical_json)


def _node_projection(node: dict) -> dict:
    return {
        "tag": node.get("tag") or "",
        "author": node.get("author") or "",
        "result_path": node.get("result_path") or "",
        "algorithm": node.get("algorithm") or "",
        "comment": node.get("comment") or "",
        "limitation": node.get("limitation") or "",
        "open_question": node.get("open_question") or "",
        "parent_edges": _edge_projection(node),
    }


def _expected_node_projection(node: dict) -> dict:
    return _node_projection(node)


def _assert_adjudication_integrity(
    tree_name: str,
    expected_nodes: dict[str, dict],
    actual_nodes: dict[str, dict],
    actual_questions: dict[str, dict],
    closed_questions: set[str] | frozenset[str],
    client: ApiClient,
) -> None:
    """Keep manifest-owned prose exact while preserving receipted server outcomes."""

    for tag, expected in expected_nodes.items():
        actual = actual_nodes.get(tag)
        if actual is None:
            continue
        question = expected.get("open_question") or ""
        if question and question in closed_questions:
            if actual.get("verdict") not in QUESTION_ANSWER_VERDICTS:
                raise RuntimeError(
                    f"remote adjudication {tag} lacks an answer verdict for CLOSED {question}"
                )
            if actual.get("verdict_source") != "scripted":
                raise RuntimeError(f"remote adjudication {tag} is not scripted/receipt-owned")
            if not actual.get("current_receipt_sha"):
                raise RuntimeError(f"remote adjudication {tag} lacks a head receipt")
            if actual.get("pred_closes") != question:
                raise RuntimeError(
                    f"remote adjudication {tag} prediction is not bound to {question}"
                )
            if int(actual.get("closed_question_count") or 0) < 1:
                raise RuntimeError(f"remote adjudication {tag} lacks CLOSES_QUESTION binding")
            if not actual.get("metric_name") or actual.get("metric_value") is None:
                raise RuntimeError(f"remote adjudication {tag} lacks its measured result")
            head = actual["current_receipt_sha"]
            if head not in (actual_questions.get(question, {}).get("closed_events") or []):
                raise RuntimeError(
                    f"remote adjudication {tag} head receipt is not the closure event for {question}"
                )
            base = f"/api/tree/{_url_segment(tree_name)}/node/{_url_segment(tag)}/receipts"
            chain = client.get(base) or {}
            verified = client.get(base + "/verify") or {}
            if chain.get("head") != head or not verified.get("ok") or not verified.get("from_receipt"):
                raise RuntimeError(f"remote adjudication {tag} receipt chain does not verify")
            head_rows = [
                row for row in (chain.get("receipts") or [])
                if row.get("receipt_sha") == head
            ]
            if len(head_rows) != 1 or head_rows[0].get("closes_question") != question:
                raise RuntimeError(
                    f"remote adjudication {tag} head receipt does not close {question}"
                )
            continue
        expected_verdict = expected.get("verdict") or "proof"
        if (actual.get("verdict") or "proof") != expected_verdict:
            raise RuntimeError(
                f"remote unclosed node {tag} verdict drift: "
                f"expected={expected_verdict!r}, observed={actual.get('verdict')!r}"
            )
        if actual.get("verdict_source") in {"scripted", "engine"}:
            raise RuntimeError(f"remote unclosed node {tag} has an unexplained forceful verdict")


def _question_projection(item: dict) -> dict:
    return {
        "name": item.get("name") or item.get("qname") or "",
        "body": item.get("body") or "",
        "expected_gain": item.get("expected_gain"),
        "cost": item.get("cost"),
    }


def _foundation_projection(item: dict) -> dict:
    status = item.get("status") or "needed"
    refs = list(item.get("evidence_refs") or [])
    return {
        "name": item.get("name") or "",
        "kind": item.get("kind") or "",
        "question": item.get("question") or "",
        "why_needed": item.get("why_needed") or "",
        "acceptance_criteria": list(item.get("acceptance_criteria") or []),
        "evidence_refs": refs,
        "status": status,
        "optional": bool(item.get("optional")),
        "owner": item.get("owner") or "",
        "risk_if_missing": item.get("risk_if_missing") or "",
        "satisfied": bool((status == "satisfied" and refs)
                          or (bool(item.get("optional")) and status == "waived")),
    }


def _tradition_projection(item: dict) -> dict:
    commitment_fields = ("commitment_id", "kind", "statement", "revisability", "source_refs")
    commitments = [{
        key: (list(commitment.get(key) or []) if key == "source_refs"
              else commitment.get(key) or "")
        for key in commitment_fields
    } for commitment in (item.get("commitments") or [])]
    return {
        "tradition_id": item.get("tradition_id") or "",
        "name": item.get("name") or "",
        "commitments": sorted(commitments, key=lambda row: row["commitment_id"]),
        "ontology_commitments": list(item.get("ontology_commitments") or []),
        "methodology_rules": list(item.get("methodology_rules") or []),
        "exemplars": list(item.get("exemplars") or []),
        "accepted_problem_types": list(item.get("accepted_problem_types") or []),
        "background_theories": list(item.get("background_theories") or []),
        "revision_policy": item.get("revision_policy") or "",
        "compatibility_notes": item.get("compatibility_notes") or "",
    }


def _expected_observation_event(data: dict, item: dict) -> dict:
    merged = {**(data.get("observation_defaults") or {}), **item}
    tag = merged.pop("tag")
    merged.setdefault("evidence_refs", [merged["url"]])
    observation = ObservationIn(**merged)
    injection = scan_prompt_injection(observation.content)
    score = SourceCredibilityScore(
        injection_penalty=injection["risk"],
        **{key: (getattr(observation, key) or 0.0) for key in _SCORE_KEYS},
    )
    obs_record = {
        "url": observation.url,
        "retrieved_at": observation.retrieved_at,
        "content_hash": observation.content_hash,
        "raw_snapshot_path": observation.raw_snapshot_path,
        "source_type": observation.source_type,
        "lakatos_location": observation.lakatos_location,
        **{key: getattr(observation, key) for key in _SCORE_KEYS},
    }
    payload = {key: str(value) for key, value in obs_record.items() if value not in (None, "")}
    payload["injection_risk"] = str(injection["risk"])
    payload["injection_signals"] = ",".join(injection["signals"])
    payload.update({key: str(round(value, 4)) for key, value in score.as_components().items()})
    payload["tier"] = score.tier.value
    payload["credibility_decomposed"] = "true"
    payload["confidence"] = str(round(score.trust, 4))
    payload["theory_basis"] = observation.theory_basis
    payload["foundation_refs"] = ",".join(observation.foundation_refs)
    payload["longinus_sourceIds"] = ",".join(ref.sourceId for ref in observation.longinus_refs)
    payload["rival_programmes"] = observation.rival_name
    full_id = f"{data['name']}/{tag}/obs/{observation.event_id}"
    rival_links = [RivalProgrammeLink(
        programme=observation.rival_name,
        relation=observation.rival_relation,
        rival_node=observation.rival_node,
        comparison_axes=tuple(observation.comparison_axes),
        evidence_refs=tuple(observation.evidence_refs),
    ).as_dict()] if observation.rival_name else []
    return {
        "id": full_id,
        "name": full_id,
        "realm": "internet",
        "actor": observation.actor,
        "action": "fetch",
        "target": tag,
        "evidence_refs": list(observation.evidence_refs),
        "payload": payload,
        "lakatos_location": observation.lakatos_location,
        "theoretical_basis": observation.theory_basis,
        "foundation_refs": list(observation.foundation_refs),
        "rival_links": sorted(rival_links, key=_canonical_json),
        "longinus_refs": sorted((ref.model_dump() for ref in observation.longinus_refs),
                                key=_canonical_json),
    }


def _event_projection(event: dict) -> dict:
    return {
        "id": event.get("id") or "",
        "name": event.get("name") or "",
        "realm": event.get("realm") or "",
        "actor": event.get("actor") or "",
        "action": event.get("action") or "",
        "target": event.get("target") or "",
        "evidence_refs": list(event.get("evidence_refs") or []),
        "payload": dict(event.get("payload") or {}),
        "lakatos_location": event.get("lakatos_location") or "",
        "theoretical_basis": event.get("theoretical_basis") or "",
        "foundation_refs": list(event.get("foundation_refs") or []),
        "rival_links": sorted((dict(link) for link in (event.get("rival_links") or [])),
                              key=_canonical_json),
        "longinus_refs": sorted((dict(ref) for ref in (event.get("longinus_refs") or [])),
                                key=_canonical_json),
    }


def _remote_observations(data: dict, client: ApiClient) -> dict[str, dict]:
    encoded_name = _url_segment(data["name"])
    result: dict[str, dict] = {}
    for tag in (node["tag"] for node in data["nodes"]):
        response = client.get(
            f"/api/tree/{encoded_name}/node/{_url_segment(tag)}/events",
            allow_not_found=True,
        )
        for event in ((response or {}).get("events") or []):
            if event.get("realm") != "internet":
                continue
            projected = _event_projection(event)
            if projected["id"] in result:
                raise RuntimeError(f"duplicate remote observation id: {projected['id']}")
            result[projected["id"]] = projected
    return result


def _assert_observation_prefix(expected: dict, actual: dict) -> bool:
    base_keys = ("id", "name", "realm", "actor", "action", "target", "evidence_refs", "payload")
    _require_equal("remote observation immutable payload",
                   {key: expected[key] for key in base_keys},
                   {key: actual[key] for key in base_keys})
    complete = True
    for key in ("lakatos_location", "theoretical_basis", "foundation_refs",
                "rival_links", "longinus_refs"):
        value = actual[key]
        if value in ("", [], None):
            complete = False
            continue
        _require_equal(f"remote observation {key}", expected[key], value)
    return complete


def _preflight_existing(data: dict, existing: dict, client: ApiClient) -> dict:
    expected_identity = _manifest_identity(data)
    if _remote_identity(existing) != expected_identity:
        raise RuntimeError(
            "existing same-name tree owner/digest collision: "
            f"expected={expected_identity!r}, observed={_remote_identity(existing)!r}"
        )
    _require_equal("remote tree metadata", _expected_tree_projection(data),
                   _tree_projection(data, existing))

    expected_questions = {q["qname"]: _question_projection(q) for q in data["questions"]}
    actual_questions = {q.get("name"): q for q in (existing.get("frontier") or [])}
    extra_questions = set(actual_questions) - set(expected_questions)
    if extra_questions:
        raise RuntimeError(f"remote frontier question set mismatch: extra={sorted(extra_questions)}")
    closed_questions: set[str] = set()
    complete_questions: set[str] = set()
    for name, question in actual_questions.items():
        status = question.get("status") or "OPEN"
        if status not in {"OPEN", "CLOSED"}:
            raise RuntimeError(f"remote frontier status mismatch: {name}={status!r}")
        actual_projection = _question_projection(question)
        if status == "OPEN":
            complete = True
            for field, expected_value in expected_questions[name].items():
                if field == "name":
                    continue
                actual_value = actual_projection[field]
                if actual_value not in (expected_value, "", None):
                    raise RuntimeError(
                        f"remote frontier question {name}.{field} mismatch: {actual_value!r}"
                    )
                if actual_value != expected_value:
                    complete = False
            if complete:
                complete_questions.add(name)
        else:
            closed_questions.add(name)
            complete_questions.add(name)
            _require_equal(f"remote closed frontier {name}", expected_questions[name], actual_projection)

    expected_node_rows = {node["tag"]: node for node in data["nodes"]}
    expected_nodes = {
        tag: _expected_node_projection(node) for tag, node in expected_node_rows.items()
    }
    actual_nodes = {node.get("tag"): node for node in (existing.get("nodes") or [])}
    extra_nodes = set(actual_nodes) - set(expected_nodes)
    if extra_nodes:
        raise RuntimeError(f"remote node set mismatch: extra={sorted(extra_nodes)}")
    for tag, node in actual_nodes.items():
        _require_equal(f"remote node {tag}", expected_nodes[tag], _node_projection(node))
    _assert_adjudication_integrity(
        data["name"], expected_node_rows, actual_nodes, actual_questions,
        closed_questions, client,
    )

    encoded_name = _url_segment(data["name"])
    foundations = client.get(f"/api/tree/{encoded_name}/foundation") or {}
    expected_foundations = {
        row["name"]: _foundation_projection(row) for row in data["foundations"]
    }
    actual_foundations = {
        row.get("name"): _foundation_projection(row)
        for row in (foundations.get("requirements") or [])
    }
    if set(actual_foundations) - set(expected_foundations):
        raise RuntimeError("remote foundation set mismatch: unexpected records")
    for name, row in actual_foundations.items():
        _require_equal(f"remote foundation {name}", expected_foundations[name], row)

    tradition = client.get(f"/api/tree/{encoded_name}/tradition", allow_not_found=True)
    if tradition is not None:
        _require_equal("remote research tradition", _tradition_projection(data["tradition"]),
                       _tradition_projection(tradition))

    expected_events = {
        event["id"]: event
        for event in (_expected_observation_event(data, item) for item in data["observations"])
    }
    actual_events = _remote_observations(data, client)
    extra_events = set(actual_events) - set(expected_events)
    if extra_events:
        raise RuntimeError(f"remote observation set mismatch: extra={sorted(extra_events)}")
    complete_events = {
        event_id for event_id, event in actual_events.items()
        if _assert_observation_prefix(expected_events[event_id], event)
    }
    return {
        "closed_questions": closed_questions,
        "nodes": set(actual_nodes),
        "questions": complete_questions,
        "foundations": set(actual_foundations),
        "tradition": tradition is not None,
        "observations": complete_events,
    }


def verify_remote(
    data: dict,
    client: ApiClient,
    *,
    closed_questions: set[str] | frozenset[str] = frozenset(),
) -> dict:
    """Exact semantic readback; counts alone can never certify convergence."""

    name = data["name"]
    encoded_name = _url_segment(name)
    tree = client.get(f"/api/tree/{encoded_name}") or {}
    metrics = client.get(f"/api/tree/{encoded_name}/metrics") or {}
    foundation = client.get(f"/api/tree/{encoded_name}/foundation") or {}
    tradition = client.get(f"/api/tree/{encoded_name}/tradition") or {}

    _require_equal("remote tree metadata", _expected_tree_projection(data),
                   _tree_projection(data, tree))
    expected_node_rows = {node["tag"]: node for node in data["nodes"]}
    expected_nodes = {
        tag: _expected_node_projection(node) for tag, node in expected_node_rows.items()
    }
    actual_node_rows = {node.get("tag"): node for node in (tree.get("nodes") or [])}
    actual_nodes = {tag: _node_projection(node) for tag, node in actual_node_rows.items()}
    _require_equal("remote node semantic set", expected_nodes, actual_nodes)

    expected_questions = {q["qname"]: _question_projection(q) for q in data["questions"]}
    actual_questions = {q.get("name"): q for q in (tree.get("frontier") or [])}
    _require_equal(
        "remote frontier question set",
        sorted(expected_questions),
        sorted(actual_questions),
    )
    for question_name, expected in expected_questions.items():
        actual = actual_questions[question_name]
        _require_equal(f"remote frontier question {question_name}", expected,
                       _question_projection(actual))
        expected_status = "CLOSED" if question_name in closed_questions else "OPEN"
        if (actual.get("status") or "OPEN") != expected_status:
            raise RuntimeError(
                f"remote frontier status mismatch: {question_name} expected={expected_status} "
                f"observed={actual.get('status')!r}"
            )
    _assert_adjudication_integrity(
        name, expected_node_rows, actual_node_rows, actual_questions,
        closed_questions, client,
    )

    expected_foundations = {
        row["name"]: _foundation_projection(row) for row in data["foundations"]
    }
    actual_foundations = {
        row.get("name"): _foundation_projection(row)
        for row in (foundation.get("requirements") or [])
    }
    _require_equal("remote foundation records", expected_foundations, actual_foundations)
    _require_equal("remote research tradition", _tradition_projection(data["tradition"]),
                   _tradition_projection(tradition))

    expected_events = {
        event["id"]: event
        for event in (_expected_observation_event(data, item) for item in data["observations"])
    }
    actual_events = _remote_observations(data, client)
    _require_equal(
        "remote observation identity set",
        sorted(expected_events),
        sorted(actual_events),
    )
    for event_id, expected in expected_events.items():
        _require_equal(f"remote observation {event_id}", expected, actual_events[event_id])

    structure = metrics.get("structure") or {}
    for key in ("nodes", "edges", "roots", "components", "multi_parent_nodes", "typed_edge_ratio"):
        want = data["expected_topology"][key]
        got = len(actual_nodes) if key == "nodes" else structure.get(key)
        if got != want:
            raise RuntimeError(f"remote structure {key}: observed={got!r}, expected={want!r}")
    return {
        "manifest_owner": _manifest_identity(data)["manifest_owner"],
        "manifest_digest": _manifest_identity(data)["manifest_digest"],
        "nodes": len(actual_nodes),
        "edges": structure.get("edges"),
        "roots": structure.get("roots"),
        "components": structure.get("components"),
        "multi_parent_nodes": structure.get("multi_parent_nodes"),
        "typed_edge_ratio": structure.get("typed_edge_ratio"),
        "questions": len(actual_questions),
        "foundations": len(actual_foundations),
        "observations": len(actual_events),
        "tradition_id": tradition.get("tradition_id"),
    }


def apply_manifest(
    data: dict,
    client: ApiClient,
    *,
    require_external_sources: bool = False,
) -> dict:
    validate_manifest(data, require_external_sources=require_external_sources)
    name = data["name"]
    encoded_name = _url_segment(name)
    existing = client.get(f"/api/tree/{encoded_name}", allow_not_found=True)
    state = {
        "closed_questions": set(),
        "nodes": set(),
        "questions": set(),
        "foundations": set(),
        "tradition": False,
        "observations": set(),
    }
    if existing is not None:
        state = _preflight_existing(data, existing, client)

    operations: list[dict] = []
    if existing is None:
        operations.append(client.post(
            f"/api/tree/{encoded_name}?create_only=true",
            _tree_payload(data),
        ))
    for node in data["nodes"]:
        if node["tag"] not in state["nodes"]:
            operations.append(client.post(f"/api/tree/{encoded_name}/node", node))
    for question in data["questions"]:
        if question["qname"] not in state["questions"]:
            operations.append(client.post(f"/api/tree/{encoded_name}/question", question))
    for foundation_row in data["foundations"]:
        if foundation_row["name"] not in state["foundations"]:
            operations.append(client.post(f"/api/tree/{encoded_name}/foundation", foundation_row))
    if not state["tradition"]:
        operations.append(client.post(f"/api/tree/{encoded_name}/tradition", data["tradition"]))

    defaults = data.get("observation_defaults") or {}
    for observation_row in data["observations"]:
        payload = {**defaults, **observation_row}
        tag = payload.pop("tag")
        payload.setdefault("evidence_refs", [payload["url"]])
        event_id = f"{name}/{tag}/obs/{payload['event_id']}"
        if event_id in state["observations"]:
            continue
        operations.append(client.post(
            f"/api/tree/{encoded_name}/node/{_url_segment(tag)}/observation",
            payload,
        ))

    failures = [
        item for item in operations
        if not isinstance(item, dict) or item.get("ok") is False or "error" in item
    ]
    if failures:
        raise RuntimeError(f"materialization returned failure payloads: {failures[:3]!r}")
    readback = verify_remote(
        data,
        client,
        closed_questions=state["closed_questions"],
    )
    return {
        "ok": True,
        "tree": name,
        "operations": len(operations),
        "nodes": len(data["nodes"]),
        "questions": len(data["questions"]),
        "foundations": len(data["foundations"]),
        "observations": len(data["observations"]),
        "closed_questions_preserved": len(state["closed_questions"]),
        "nodes_already_exact": len(state["nodes"]),
        "questions_already_exact": len(state["questions"]),
        "foundations_already_exact": len(state["foundations"]),
        "tradition_already_exact": bool(state["tradition"]),
        "observations_already_exact": len(state["observations"]),
        "readback": readback,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--url", default=os.environ.get("LAKATOTREE_URL", DEFAULT_URL))
    parser.add_argument("--apply", action="store_true", help="perform idempotent HTTP upserts")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    data = load_manifest(args.manifest)
    report = validate_manifest(data, require_external_sources=args.apply)
    if not args.apply:
        print(json.dumps({**report, "mode": "dry-run"}, ensure_ascii=False, indent=2))
        return 0
    token = os.environ.get("LAKATOS_API_TOKEN", "")
    if not token:
        raise SystemExit("LAKATOS_API_TOKEN is required for --apply")
    applied = apply_manifest(
        data,
        ApiClient(args.url, token),
        require_external_sources=True,
    )
    print(json.dumps({**report, **applied, "mode": "applied"}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
