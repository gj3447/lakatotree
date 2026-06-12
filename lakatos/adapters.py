"""외부 lineage/provenance 생태계 adapter.

OpenLineage, DVC, W3C PROV 를 core dependency 로 끌어오지 않고 같은 의미를
plain dict 로 내보낸다. 순수 엔진은 그대로 두고, Marquez/DVC/prov-python
연결은 이 모듈 위의 얇은 I/O layer 로 구현한다.
# KG: span_lakatotree_adapters
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import asdict
from datetime import datetime, timezone
from uuid import uuid5, NAMESPACE_URL

from .engine import BashAct, InternetObservation, LineageReplayResult
from .lineage import Derivation, by_output, rebuild_plan, roots


OPENLINEAGE_SCHEMA_URL = "https://openlineage.io/spec/1-0-5/OpenLineage.json"
LAKATOS_PRODUCER = "https://github.com/airobotics-ailab/lakatotree"
MARQUEZ_LINEAGE_PATH = "/api/v1/lineage"


class MarquezClientError(RuntimeError):
    """Marquez/OpenLineage 전송 실패."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _stable_run_id(namespace: str, job_name: str, output: str, output_sha: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"{namespace}:{job_name}:{output}:{output_sha}"))


def _dataset_name(path: str) -> str:
    return path or "<anonymous>"


def _marquez_lineage_url(base_url: str) -> str:
    return base_url.rstrip("/") + MARQUEZ_LINEAGE_PATH


def _json_response(body: bytes) -> dict | str:
    if not body:
        return {}
    text = body.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def derivation_to_openlineage_event(
    derivation: Derivation,
    *,
    namespace: str = "lakatotree",
    event_type: str = "COMPLETE",
    event_time: str | None = None,
) -> dict:
    """Derivation 1건을 OpenLineage RunEvent 모양 dict 로 변환한다.

    OpenLineage 의 핵심 vocabulary 는 Run/Job/Dataset 이다. LakatoTree 에서는
    Derivation 이 한 PipelineRun 에 해당하고, inputs/output 이 Dataset 이다.
    """
    run_id = _stable_run_id(namespace, derivation.producer, derivation.output, derivation.output_sha)
    return {
        "eventType": event_type,
        "eventTime": event_time or _utc_now(),
        "run": {
            "runId": run_id,
            "facets": {
                "lakatotree_replay": {
                    "_producer": LAKATOS_PRODUCER,
                    "_schemaURL": f"{LAKATOS_PRODUCER}/schemas/lakatotree-replay.json",
                    "kind": derivation.kind,
                    "output_sha": derivation.output_sha,
                    "producer_sha": derivation.producer_sha,
                    "params": derivation.params,
                }
            },
        },
        "job": {
            "namespace": namespace,
            "name": derivation.producer or f"source:{derivation.output}",
        },
        "inputs": [
            {
                "namespace": namespace,
                "name": _dataset_name(path),
                "facets": {
                    "dataSource": {
                        "_producer": LAKATOS_PRODUCER,
                        "_schemaURL": f"{OPENLINEAGE_SCHEMA_URL}#/definitions/DatasourceDatasetFacet",
                        "name": path,
                    },
                    "lakatotree_hash": {
                        "_producer": LAKATOS_PRODUCER,
                        "_schemaURL": f"{LAKATOS_PRODUCER}/schemas/lakatotree-hash.json",
                        "sha256": sha,
                    },
                },
            }
            for path, sha in derivation.inputs
        ],
        "outputs": [
            {
                "namespace": namespace,
                "name": _dataset_name(derivation.output),
                "facets": {
                    "lakatotree_hash": {
                        "_producer": LAKATOS_PRODUCER,
                        "_schemaURL": f"{LAKATOS_PRODUCER}/schemas/lakatotree-hash.json",
                        "sha256": derivation.output_sha,
                    },
                    "lakatotree_artifact": {
                        "_producer": LAKATOS_PRODUCER,
                        "_schemaURL": f"{LAKATOS_PRODUCER}/schemas/lakatotree-artifact.json",
                        "kind": derivation.kind,
                    },
                },
            }
        ],
        "producer": LAKATOS_PRODUCER,
        "schemaURL": f"{OPENLINEAGE_SCHEMA_URL}#/definitions/RunEvent",
    }


def lineage_result_to_openlineage_events(
    result: LineageReplayResult,
    *,
    namespace: str = "lakatotree",
    event_time: str | None = None,
) -> list[dict]:
    """LineageReplayGate 결과의 rebuild plan 을 OpenLineage event sequence 로 변환."""
    return [
        derivation_to_openlineage_event(d, namespace=namespace, event_time=event_time)
        for d in result.rebuild_plan
    ]


def derivations_to_dvc_pipeline(derivations: list[Derivation]) -> dict:
    """Derivation 목록을 dvc.yaml 과 유사한 stage dict 로 변환한다."""
    stages: dict[str, dict] = {}
    for d in derivations:
        if d.kind == "source" or not d.producer:
            continue
        name = d.output.replace("/", "__").replace(".", "_")
        stages[name] = {
            "cmd": f"python {d.producer}",
            "deps": [path for path, _ in d.inputs] + [d.producer],
            "outs": [d.output],
            "params": d.params,
            "meta": {
                "output_sha": d.output_sha,
                "producer_sha": d.producer_sha,
                "kind": d.kind,
                "ts": d.ts,
            },
        }
    return {"stages": stages}


def derivations_to_dvc_lock(derivations: list[Derivation]) -> dict:
    """Derivation 목록을 dvc.lock 과 유사한 hash manifest 로 변환한다."""
    stages: dict[str, dict] = {}
    for d in derivations:
        if d.kind == "source" or not d.producer:
            continue
        name = d.output.replace("/", "__").replace(".", "_")
        stages[name] = {
            "cmd": f"python {d.producer}",
            "deps": [{"path": path, "md5": sha} for path, sha in d.inputs],
            "outs": [{"path": d.output, "md5": d.output_sha}],
        }
    return {"schema": "2.0", "stages": stages}


def rebuild_recipe_manifest(final_artifact: str, derivations: list[Derivation]) -> dict:
    """raw roots, rebuild order, DVC-style exports 를 한 번에 묶은 replay manifest."""
    bo = by_output(derivations)
    plan = rebuild_plan(final_artifact, bo)
    return {
        "final_artifact": final_artifact,
        "raw_roots": sorted(roots(final_artifact, bo)),
        "rebuild_steps": [asdict(d) for d in plan],
        "dvc_yaml": derivations_to_dvc_pipeline(list(plan)),
        "dvc_lock": derivations_to_dvc_lock(list(plan)),
    }


def derivations_to_prov_document(derivations: list[Derivation]) -> dict:
    """W3C PROV 의미를 plain dict 로 표현한다.

    Entity=artifact/code, Activity=derivation run, Agent=producer script.
    """
    entities: dict[str, dict] = {}
    activities: dict[str, dict] = {}
    agents: dict[str, dict] = {}
    relations: list[dict] = []

    for d in derivations:
        entities[d.output] = {
            "type": "RawDataArtifact" if d.kind == "source" else "DerivedDataArtifact",
            "sha256": d.output_sha,
            "kind": d.kind,
        }
        if d.producer:
            agent_id = f"script:{d.producer}"
            activity_id = f"derive:{d.output}@{d.ts or d.output_sha}"
            agents[agent_id] = {
                "type": "Script",
                "path": d.producer,
                "sha256": d.producer_sha,
            }
            activities[activity_id] = {
                "type": "PipelineRun",
                "params": d.params,
                "time": d.ts,
            }
            relations.append({"rel": "wasGeneratedBy", "from": d.output, "to": activity_id})
            relations.append({"rel": "wasAttributedTo", "from": activity_id, "to": agent_id})
            for path, sha in d.inputs:
                entities.setdefault(path, {"type": "DataArtifact", "sha256": sha})
                relations.append({"rel": "used", "from": activity_id, "to": path})
                relations.append({"rel": "wasDerivedFrom", "from": d.output, "to": path})

    return {
        "prefix": {"prov": "http://www.w3.org/ns/prov#"},
        "entity": entities,
        "activity": activities,
        "agent": agents,
        "relations": relations,
    }


def observation_to_prov_document(observation: InternetObservation) -> dict:
    """InternetObservation 1건을 PROV-like document 로 변환."""
    activity = f"fetch:{observation.name}"
    entity = f"snapshot:{observation.name}"
    agent = observation.fetch_tool
    return {
        "prefix": {"prov": "http://www.w3.org/ns/prov#"},
        "entity": {
            entity: {
                "type": "InternetObservation",
                "url": observation.url,
                "content_hash": observation.content_hash,
                "source_type": observation.source_type,
                "trust": observation.credibility.trust,
                "tier": observation.credibility.tier.value,
            }
        },
        "activity": {
            activity: {
                "type": "WebFetch",
                "query": observation.query,
                "retrieved_at": observation.retrieved_at.isoformat(),
            }
        },
        "agent": {agent: {"type": "FetchTool"}},
        "relations": [
            {"rel": "wasGeneratedBy", "from": entity, "to": activity},
            {"rel": "wasAttributedTo", "from": activity, "to": agent},
        ],
    }


def bash_act_to_prov_document(act: BashAct) -> dict:
    """BashAct 를 PROV-like document 로 변환."""
    activity = f"bash:{act.name}"
    entity = f"bash:{act.name}#result"
    return {
        "prefix": {"prov": "http://www.w3.org/ns/prov#"},
        "entity": {
            entity: {
                "type": "BashResult",
                "exit_code": act.exit_code,
                "stdout_hash": act.stdout_hash,
                "stderr_hash": act.stderr_hash,
                "stdout_summary": act.stdout_summary,
                "stderr_summary": act.stderr_summary,
            }
        },
        "activity": {
            activity: {
                "type": "BashAct",
                "command": act.command,
                "cwd": act.cwd,
                "git_sha": act.git_sha,
            }
        },
        "agent": {"shell": {"type": "Shell"}},
        "relations": [
            {"rel": "wasGeneratedBy", "from": entity, "to": activity},
            {"rel": "wasAttributedTo", "from": activity, "to": "shell"},
        ],
    }


def send_openlineage_events_to_marquez(
    events: list[dict],
    *,
    base_url: str,
    timeout: float = 10.0,
    token: str | None = None,
    opener=urllib.request.urlopen,
) -> list[dict]:
    """OpenLineage event dict 를 Marquez LineageAPI 로 전송한다.

    Marquez 는 OpenLineage event 를 `POST /api/v1/lineage` 로 받는다. 이 함수는
    adapter I/O 경계라서 순수 엔진에는 의존성을 추가하지 않고, 테스트에서는
    opener 를 주입해 네트워크 없이 검증한다.
    """
    url = _marquez_lineage_url(base_url)
    results = []
    for event in events:
        headers = {"Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            url,
            data=json.dumps(event, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with opener(request, timeout=timeout) as response:
                results.append({
                    "status": getattr(response, "status", None),
                    "response": _json_response(response.read()),
                })
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise MarquezClientError(
                f"Marquez lineage POST failed: {exc.code} {exc.reason}: {body}"
            ) from exc
        except urllib.error.URLError as exc:
            raise MarquezClientError(f"Marquez lineage POST failed: {exc}") from exc
    return results


def _prov_attr_key(key: str) -> str:
    return "prov:type" if key == "type" else f"lakatotree:{key}"


def _prov_attrs(attrs: dict) -> dict:
    return {_prov_attr_key(k): v for k, v in attrs.items() if v is not None}


def _prov_package_value(value):
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return value


def _prov_package_attr_key(key: str) -> str:
    return "prov:type" if key == "type" else f"lkt:{key}"


def _prov_package_attrs(attrs: dict) -> dict:
    return {
        _prov_package_attr_key(k): _prov_package_value(v)
        for k, v in attrs.items()
        if v is not None
    }


def prov_document_to_prov_json(doc: dict) -> dict:
    """LakatoTree PROV-like dict 를 PROV-JSON 형태로 변환한다."""
    out = {
        "prefix": {
            **doc.get("prefix", {}),
            "lakatotree": LAKATOS_PRODUCER + "/prov#",
        },
        "entity": {
            entity_id: _prov_attrs(attrs)
            for entity_id, attrs in doc.get("entity", {}).items()
        },
        "activity": {
            activity_id: _prov_attrs(attrs)
            for activity_id, attrs in doc.get("activity", {}).items()
        },
        "agent": {
            agent_id: _prov_attrs(attrs)
            for agent_id, attrs in doc.get("agent", {}).items()
        },
    }
    counters: dict[str, int] = {}
    for rel in doc.get("relations", []):
        name = rel["rel"]
        idx = counters.get(name, 0)
        counters[name] = idx + 1
        target = out.setdefault(name, {})
        rel_id = f"_:{name}{idx}"
        src = rel["from"]
        dst = rel["to"]
        if name == "wasGeneratedBy":
            target[rel_id] = {"prov:entity": src, "prov:activity": dst}
        elif name == "used":
            target[rel_id] = {"prov:activity": src, "prov:entity": dst}
        elif name == "wasDerivedFrom":
            target[rel_id] = {"prov:generatedEntity": src, "prov:usedEntity": dst}
        elif name == "wasAttributedTo":
            target[rel_id] = {"prov:entity": src, "prov:agent": dst}
        else:
            target[rel_id] = {"prov:from": src, "prov:to": dst}
    return out


def _safe_prov_id(raw: str) -> str:
    local = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw).strip("_") or "anonymous"
    if local[0].isdigit():
        local = "id_" + local
    return f"lkt:{local}"


def _to_prov_package_document(doc: dict):
    from prov.model import ProvDocument

    pdoc = ProvDocument()
    pdoc.add_namespace("lkt", LAKATOS_PRODUCER + "/prov#")
    ids = {}

    def qid(raw: str) -> str:
        if raw not in ids:
            ids[raw] = _safe_prov_id(raw)
        return ids[raw]

    for entity_id, attrs in doc.get("entity", {}).items():
        pdoc.entity(qid(entity_id), {
            **_prov_package_attrs(attrs),
            "lkt:original_id": entity_id,
        })
    for activity_id, attrs in doc.get("activity", {}).items():
        pdoc.activity(qid(activity_id), other_attributes={
            **_prov_package_attrs(attrs),
            "lkt:original_id": activity_id,
        })
    for agent_id, attrs in doc.get("agent", {}).items():
        pdoc.agent(qid(agent_id), {
            **_prov_package_attrs(attrs),
            "lkt:original_id": agent_id,
        })

    for rel in doc.get("relations", []):
        src = qid(rel["from"])
        dst = qid(rel["to"])
        if rel["rel"] == "wasGeneratedBy":
            pdoc.wasGeneratedBy(src, dst)
        elif rel["rel"] == "used":
            pdoc.used(src, dst)
        elif rel["rel"] == "wasDerivedFrom":
            pdoc.wasDerivedFrom(src, dst)
        elif rel["rel"] == "wasAttributedTo":
            pdoc.wasAttributedTo(src, dst)
    return pdoc


def serialize_prov_document(
    doc: dict,
    *,
    format: str = "json",
    use_prov_package: bool = False,
) -> str:
    """PROV-like document 를 문자열로 직렬화한다.

    `json`/`prov-json` 은 의존성 없이 안정적으로 출력한다. 다른 형식은
    `use_prov_package=True` 일 때만 optional `prov` 패키지로 위임한다.
    """
    fmt = format.lower()
    if fmt in {"json", "prov-json", "prov_json"} and not use_prov_package:
        return json.dumps(prov_document_to_prov_json(doc), ensure_ascii=False, sort_keys=True)
    if not use_prov_package:
        raise ValueError(f"format requires use_prov_package=True: {format}")
    pdoc = _to_prov_package_document(doc)
    prov_fmt = "provn" if fmt in {"provn", "prov-n"} else fmt
    return pdoc.serialize(format=prov_fmt)
