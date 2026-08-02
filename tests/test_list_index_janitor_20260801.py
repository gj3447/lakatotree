"""q-selfdev-list-index-janitor: empty Probe trees surface as dangling."""
from __future__ import annotations

from fastapi import HTTPException

from server.contexts.tree.service import TreeService


class _Svc(TreeService):
    def __init__(self, trees: list[dict], bodies: dict[str, dict]):
        object.__setattr__(self, "_trees", trees)
        object.__setattr__(self, "_bodies", bodies)
        object.__setattr__(self, "kg", None)
        object.__setattr__(self, "kg_tx", None)
        object.__setattr__(self, "hist", None)
        object.__setattr__(self, "pg", None)
        object.__setattr__(self, "repo", None)
        object.__setattr__(self, "validator", None)
        object.__setattr__(self, "mutations", None)

    def list_trees(self) -> list[dict]:
        return list(self._trees)

    def tree_data(self, name: str) -> dict:
        if name not in self._bodies:
            raise HTTPException(404, f"나무 없음: {name}")
        return self._bodies[name]

    def delete_tree(
        self,
        name: str,
        cascade: bool = False,
        *,
        idempotency_key: str | None = None,
        require_empty: bool = False,
        require_incarnation_match: bool = False,
        expected_incarnation_id: str | None = None,
    ) -> dict:
        assert require_empty is True
        self._bodies.pop(name, None)
        self._trees[:] = [t for t in self._trees if t.get("name") != name]
        return {"ok": True, "deleted": name}


def test_janitor_finds_empty_probe_and_404():
    svc = _Svc(
        trees=[
            {"name": "RoleLayoutProbe_1", "title": "p"},
            {"name": "GoodTree", "title": "g"},
            {"name": "Ghost", "title": "x"},
        ],
        bodies={
            "RoleLayoutProbe_1": {"nodes": []},
            "GoodTree": {"nodes": [{"tag": "a"}]},
        },
    )
    out = svc.list_index_janitor(delete_empty_probes=False)
    reasons = {d["name"]: d["reason"] for d in out["dangling"]}
    assert reasons["RoleLayoutProbe_1"] == "empty_probe"
    assert reasons["Ghost"] == "list_present_load_404"
    assert "GoodTree" not in reasons
    assert out["dangling_count"] == 2


def test_janitor_delete_empty_probes():
    svc = _Svc(
        trees=[{"name": "RoleLayoutProbe_x", "title": "p"}],
        bodies={"RoleLayoutProbe_x": {"nodes": []}},
    )
    out = svc.list_index_janitor(delete_empty_probes=True)
    assert out["deleted"] == ["RoleLayoutProbe_x"]
    assert svc.list_trees() == []


class _RacingSvc(_Svc):
    def delete_tree(
        self,
        name: str,
        cascade: bool = False,
        *,
        idempotency_key: str | None = None,
        require_empty: bool = False,
        require_incarnation_match: bool = False,
        expected_incarnation_id: str | None = None,
    ) -> dict:
        # A writer inserts after the janitor's second tree_data read but before
        # the delete transaction evaluates its lock-held predicate.
        self._bodies[name]["nodes"] = [{"tag": "late"}]
        if require_empty:
            raise HTTPException(409, "lock-held empty precondition changed")
        return super().delete_tree(
            name,
            cascade,
            idempotency_key=idempotency_key,
            require_empty=require_empty,
            require_incarnation_match=require_incarnation_match,
            expected_incarnation_id=expected_incarnation_id,
        )


def test_janitor_does_not_cascade_a_node_inserted_after_empty_snapshot():
    svc = _RacingSvc(
        trees=[{"name": "RoleLayoutProbe_race", "title": "p"}],
        bodies={
            "RoleLayoutProbe_race": {
                "nodes": [],
                "tree_incarnation_id": "inc-race",
            }
        },
    )
    out = svc.list_index_janitor(delete_empty_probes=True)
    assert out["deleted"] == []
    assert svc.tree_data("RoleLayoutProbe_race")["nodes"] == [{"tag": "late"}]
