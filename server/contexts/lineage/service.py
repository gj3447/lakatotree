"""Application service for data lineage, replay, and ecosystem exports.

# KG: seed-lkt-engine-route-lineage-extract-20260616
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from datetime import datetime, timezone
from typing import Any

import psycopg2.extras
from fastapi import HTTPException

from lakatos.io.adapters import (
    MarquezClientError,
    derivations_to_dvc_lock,
    derivations_to_dvc_pipeline,
    derivations_to_prov_document,
    lineage_result_to_openlineage_events,
    prov_document_to_prov_json,
)
from lakatos.io.replay import LineageReplayGate
from lakatos.io.envfp import environment_fingerprint as default_environment_fingerprint
from lakatos.io.envfp import fingerprint_sha as default_fingerprint_sha
from lakatos.io.lineage import (
    Derivation,
    build_manifest,
    by_output,
    env_drift,
    rebuild_plan,
    reproducibility_gaps,
    roots as lineage_roots,
    script_history,
    stale_inputs,
)
from server.contexts.lineage.schemas import DerivationIn
from server.ports import KgQuery, PgFactory


LineageProvider = Callable[[], Iterable[Derivation]]
PathShaProvider = Callable[[str], str | None]
EnvironmentProvider = Callable[[], dict]
FingerprintProvider = Callable[[dict], str]
RebuildPlanProvider = Callable[[str, dict[str, Derivation]], list[Derivation]]


class LineageService:
    """Owns artifact lineage recording, replay checks, and export adapters."""

    # KG: seed-lkt-engine-route-lineage-extract-20260616

    def __init__(
        self,
        *,
        kg: KgQuery,
        pg: PgFactory,
        path_sha: PathShaProvider,
        load_lineage: LineageProvider | None = None,
        safe_rebuild_plan: RebuildPlanProvider | None = None,
        environment_fingerprint: EnvironmentProvider = default_environment_fingerprint,
        fingerprint_sha: FingerprintProvider = default_fingerprint_sha,
    ):
        self.kg = kg
        self.pg = pg
        self.path_sha = path_sha
        self.load_lineage_provider = load_lineage
        self.safe_rebuild_plan_provider = safe_rebuild_plan
        self.environment_fingerprint = environment_fingerprint
        self.fingerprint_sha = fingerprint_sha

    def record_derivation(self, d: DerivationIn) -> dict:
        if d.kind != "source" and not d.inputs:
            raise HTTPException(400, f"비-source 산출물(kind={d.kind})은 inputs 필수 — "
                                     f"inputs 빈 산출물은 source 로만 기록 가능(재현성 불변식).")
        self.kg("""MERGE (o:DataArtifact {path:$out}) SET o.sha=$osha, o.kind=$kind, o.producer=$prod,
              o.producer_sha=$psha, o.params=$params, o.env=$env, o.recorded_at=$ts""",
                out=d.output, osha=d.output_sha, kind=d.kind, prod=d.producer, psha=d.producer_sha,
                params=json.dumps(d.params, ensure_ascii=False), env=d.env,
                ts=datetime.now(timezone.utc).isoformat())
        for path, sha in d.inputs:
            self.kg("""MERGE (i:DataArtifact {path:$ip}) ON CREATE SET i.sha=$ish
              WITH i MATCH (o:DataArtifact {path:$out})
              MERGE (o)-[:DERIVED_FROM {input_sha:$ish}]->(i)""",
                    ip=path, ish=sha, out=d.output)
        with self.pg() as conn, conn.cursor() as cur:
            cur.execute('INSERT INTO lineage(output, output_sha, producer, producer_sha, inputs, params, kind, env) '
                        'VALUES (%s,%s,%s,%s,%s,%s,%s,%s)',
                        (d.output, d.output_sha, d.producer, d.producer_sha,
                         json.dumps(d.inputs), json.dumps(d.params, ensure_ascii=False), d.kind, d.env))
        return {"ok": True}

    def load_lineage(self) -> list[Derivation]:
        rows = self.kg("""MATCH (o:DataArtifact) OPTIONAL MATCH (o)-[r:DERIVED_FROM]->(i:DataArtifact)
                 RETURN o.path AS out, o.sha AS osha, o.producer AS prod, o.producer_sha AS psha,
                        o.kind AS kind, o.env AS env, collect({path:i.path, sha:r.input_sha}) AS inputs""")
        ds = []
        for row in rows:
            inputs = [(item["path"], item["sha"]) for item in row["inputs"] if item["path"]]
            ds.append(Derivation(
                output=row["out"],
                output_sha=row["osha"] or "",
                producer=row["prod"] or "",
                producer_sha=row["psha"] or "",
                inputs=inputs,
                kind=row["kind"] or "intermediate",
                env=row.get("env") or "",
            ))
        return ds

    def artifact_openlineage(self, artifact: str) -> dict:
        ds, bo = self._lineage_for(artifact)
        sources = {d.output for d in ds if d.kind == "source"}
        result = LineageReplayGate.evaluate(artifact, ds, sources=sources)
        return {"artifact": artifact, "events": lineage_result_to_openlineage_events(result)}

    def send_artifact_to_marquez(self, artifact: str) -> dict:
        from lakatos.io import marquez_sink

        if not marquez_sink.enabled():
            raise HTTPException(503, "MARQUEZ_URL 미설정 — 전송 비활성. 직렬화는 GET /api/openlineage/{artifact} "
                                     "로 가능. 환경변수 MARQUEZ_URL(+선택 MARQUEZ_TOKEN) 설정 후 재시도.")
        ds, _bo = self._lineage_for(artifact)
        sources = {d.output for d in ds if d.kind == "source"}
        result = LineageReplayGate.evaluate(artifact, ds, sources=sources)
        events = lineage_result_to_openlineage_events(result)
        try:
            sent = marquez_sink.ship(events)
        except MarquezClientError as exc:
            raise HTTPException(502, f"Marquez 전송 실패(upstream): {exc}") from exc
        return {"artifact": artifact, "sent_events": len(events), "marquez": sent}

    def artifact_dvc(self, artifact: str) -> dict:
        _ds, bo = self._lineage_for(artifact)
        plan = self._safe_rebuild_plan(artifact, bo)
        return {
            "artifact": artifact,
            "dvc_yaml": derivations_to_dvc_pipeline(plan),
            "dvc_lock": derivations_to_dvc_lock(plan),
        }

    def artifact_prov(self, artifact: str, format: str | None = None) -> dict:
        _ds, bo = self._lineage_for(artifact)
        plan = self._safe_rebuild_plan(artifact, bo)
        doc = derivations_to_prov_document(plan)
        if format == "prov-json":
            return prov_document_to_prov_json(doc)
        return {"artifact": artifact, "prov": doc}

    def rebuild_verify(self, artifact: str) -> dict:
        ds, bo = self._lineage_for(artifact)
        sources = {d.output for d in ds if d.kind == "source"}
        gaps = reproducibility_gaps(artifact, bo, sources)
        current = self._current_input_shas(ds)
        current_env = self.fingerprint_sha(self.environment_fingerprint())
        plan = self._safe_rebuild_plan(artifact, bo)
        stale = {d.output: True for d in plan if stale_inputs(d, current)}
        env_changed = {d.output: {"recorded": d.env[:12], "current": current_env[:12]}
                       for d in plan if env_drift(d, current_env)}
        manifest = build_manifest(artifact, bo, env_sha=current_env)
        ok = (not gaps) and (not stale) and (not env_changed)
        # #7 정직: 이건 *정적* DAG 체크다(재실행 안 함) → executor 재실행 영수증의 'rebuildable' 과 다른 토큰.
        verdict = "rebuildable_static" if ok else "progressive_conditional"
        return dict(
            artifact=artifact,
            verdict=verdict,
            verified="static",   # 정적 분석(재실행 아님) — executor 영수증은 verified='re-executed' 격
            reproducible=(not gaps),
            gaps=sorted(gaps),
            stale=list(stale),
            env_changed=env_changed,
            manifest=dict(
                final=manifest.final,
                roots=[{"path": r.path, "sha": r.sha[:12], "schema": r.schema} for r in manifest.roots],
                env_sha=manifest.env_sha[:12],
                recipe=[{k: v for k, v in step.items() if k != "params"} for step in manifest.recipe],
            ),
            note="rebuildable_static=정적 분석상 raw root+현재환경서 재생성 가능(레시피 완전·미stale·env 일치) — 재실행은 안 함(executor rebuild-run 이 실제 영수증). progressive_conditional=env/데이터 바뀜 → 재실행 필요(consumer_b ZDF Rule #5)",
        )

    def get_script_history(self, producer: str) -> dict:
        with self.pg() as conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT output, producer_sha, ts FROM lineage WHERE producer=%s ORDER BY ts", (producer,))
            rows = cur.fetchall()
        derivations = [Derivation(output=row["output"], output_sha="", producer=producer,
                                  producer_sha=row["producer_sha"] or "", inputs=[],
                                  ts=row["ts"].isoformat())
                       for row in rows]
        return dict(producer=producer, versions=script_history(derivations, producer),
                    note="sha 바뀐 지점 = 스크립트 수정. 어느 버전이 어느 데이터 만들었나 추적")

    def get_lineage(self, artifact: str, stale: bool = False) -> dict:
        ds, bo = self._lineage_for(artifact)
        sources = {d.output for d in ds if d.kind == "source"} | {
            root for root in lineage_roots(artifact, bo) if bo.get(root) is None or not bo[root].inputs
        }
        gaps = reproducibility_gaps(artifact, bo, sources)
        plan = self._safe_rebuild_plan(artifact, bo)
        out = dict(
            artifact=artifact,
            roots=sorted(lineage_roots(artifact, bo)),
            reproducible=(not gaps),
            gaps=sorted(gaps),
            rebuild_plan=[dict(output=d.output, producer=d.producer,
                               inputs=[path for path, _ in d.inputs]) for d in plan],
            note="reproducible=True → source(ZDF)서 plan 순서대로 재실행하면 완성본 재생성",
        )
        if stale:
            current = self._current_input_shas(ds)
            changed = {}
            for derivation in plan:
                bad = stale_inputs(derivation, current)
                if bad:
                    changed[derivation.output] = [
                        {"input": path, "recorded": recorded[:12], "current": current[:12]}
                        for path, recorded, current in bad
                    ]
            out["stale"] = bool(changed)
            out["changed"] = changed
        return out

    @staticmethod
    def safe_rebuild_plan(artifact: str, bo: dict[str, Derivation]) -> list[Derivation]:
        try:
            return rebuild_plan(artifact, bo)
        except ValueError:
            return []

    def _derivations(self) -> list[Derivation]:
        if self.load_lineage_provider is not None:
            return list(self.load_lineage_provider())
        return self.load_lineage()

    def _lineage_for(self, artifact: str) -> tuple[list[Derivation], dict[str, Derivation]]:
        ds = self._derivations()
        bo = by_output(ds)
        if artifact not in bo:
            raise HTTPException(404, f"산출물 미기록: {artifact}")
        return ds, bo

    def _safe_rebuild_plan(self, artifact: str, bo: dict[str, Derivation]) -> list[Derivation]:
        if self.safe_rebuild_plan_provider is not None:
            return self.safe_rebuild_plan_provider(artifact, bo)
        return self.safe_rebuild_plan(artifact, bo)

    def _current_input_shas(self, derivations: Iterable[Derivation]) -> dict[str, str]:
        current = {}
        for derivation in derivations:
            for path, _ in derivation.inputs:
                if path in current:
                    continue
                sha = self.path_sha(path)
                if sha is not None:
                    current[path] = sha
        return current

