"""Exact graph-level validation for content-addressed verdict receipts."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

from lakatos.verdicts import (
    ReceiptChainBroken,
    fold_receipt_chain,
    match_receipt_encoding,
)


class ReceiptGraphError(ValueError):
    """The stored receipt graph is not one exact chain per owned node."""


RECEIPT_CHAIN_ROWS_CYPHER = """
MATCH (t:LakatosTree)-[:HAS_NODE]->(e)
OPTIONAL MATCH (e)-[:HAS_RECEIPT]->(rec:VerdictReceipt)
RETURN elementId(e) AS node_element_id, t.name AS tree, e.tag AS tag,
       e.current_receipt_sha AS current_receipt_sha,
       e.pred_receipt_sha AS pred_receipt_sha,
       collect(CASE WHEN rec IS NULL THEN null ELSE {
         receipt_element_id:elementId(rec), receipt:properties(rec)
       } END) AS receipts
ORDER BY tree, tag, node_element_id
"""


RECEIPT_IDENTITIES_CYPHER = """
MATCH (rec:VerdictReceipt)
OPTIONAL MATCH (owner)-[binding:HAS_RECEIPT]->(rec)
OPTIONAL MATCH (t:LakatosTree)-[:HAS_NODE]->(owner)
RETURN elementId(rec) AS receipt_element_id,
       rec.receipt_sha AS receipt_sha, properties(rec) AS receipt,
       count(DISTINCT binding) AS all_bindings,
       collect(DISTINCT CASE WHEN owner IS NULL OR t IS NULL THEN null ELSE {
         node_element_id:elementId(owner), tree:t.name, tag:owner.tag
       } END) AS owners
ORDER BY receipt_sha, receipt_element_id
"""


@dataclass(frozen=True)
class ReceiptChainIndex:
    ancestors_by_scope: dict[tuple[str, str], frozenset[str]]
    receipt_by_sha: dict[str, dict[str, Any]]


def _sha(value: Any) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def validate_receipt_graph(
    node_rows: Iterable[dict[str, Any]],
    identity_rows: Iterable[dict[str, Any]],
) -> ReceiptChainIndex:
    """Validate physical identity, ownership, content, and head ancestry.

    Every physical ``VerdictReceipt`` must have exactly one ``HAS_RECEIPT``
    owner, that owner must be exactly one node in exactly one tree, and every
    receipt bound to a node must lie on the node's current head-to-genesis
    path.  This rejects dangling parents, cycles, side branches, orphan
    receipts, duplicate receipt identities, cross-node bindings, and in-place
    content tampering.
    """

    identities = [dict(row) for row in identity_rows]
    physical_by_element: dict[str, dict[str, Any]] = {}
    sha_to_elements: dict[str, set[str]] = {}
    owner_by_element: dict[str, tuple[str, str, str]] = {}
    receipt_by_sha: dict[str, dict[str, Any]] = {}

    for row in identities:
        element_id = row.get("receipt_element_id")
        receipt = row.get("receipt")
        receipt_sha = row.get("receipt_sha")
        owners = row.get("owners")
        if (
            not isinstance(element_id, str)
            or not element_id
            or not isinstance(receipt, dict)
            or not _sha(receipt_sha)
            or receipt.get("receipt_sha") != receipt_sha
            or type(row.get("all_bindings")) is not int
            or row.get("all_bindings") != 1
            or not isinstance(owners, list)
            or len(owners) != 1
            or not isinstance(owners[0], dict)
        ):
            raise ReceiptGraphError("receipt physical identity is malformed")
        owner = owners[0]
        owner_element_id = owner.get("node_element_id")
        tree = owner.get("tree")
        tag = owner.get("tag")
        if not all(
            isinstance(value, str) and bool(value)
            for value in (owner_element_id, tree, tag)
        ):
            raise ReceiptGraphError("receipt owner is not one tree-scoped node")
        if receipt.get("tree") != tree or receipt.get("tag") != tag:
            raise ReceiptGraphError("receipt scope disagrees with its owner")
        if match_receipt_encoding(receipt, receipt_sha) is None:
            raise ReceiptGraphError("receipt content hash does not rederive")
        if element_id in physical_by_element:
            raise ReceiptGraphError("receipt physical element is duplicated")
        physical_by_element[element_id] = receipt
        owner_by_element[element_id] = (owner_element_id, tree, tag)
        sha_to_elements.setdefault(receipt_sha, set()).add(element_id)
        receipt_by_sha[receipt_sha] = receipt

    if any(len(elements) != 1 for elements in sha_to_elements.values()):
        raise ReceiptGraphError("receipt sha identifies multiple physical nodes")

    nodes = [dict(row) for row in node_rows]
    seen_nodes: set[str] = set()
    seen_scopes: set[tuple[str, str]] = set()
    seen_receipt_elements: set[str] = set()
    ancestors_by_scope: dict[tuple[str, str], frozenset[str]] = {}
    for row in nodes:
        node_element_id = row.get("node_element_id")
        tree = row.get("tree")
        tag = row.get("tag")
        bound = row.get("receipts")
        if (
            not isinstance(node_element_id, str)
            or not node_element_id
            or not isinstance(tree, str)
            or not tree
            or not isinstance(tag, str)
            or not tag
            or not isinstance(bound, list)
        ):
            raise ReceiptGraphError("receipt-chain node row is malformed")
        scope = (tree, tag)
        if node_element_id in seen_nodes or scope in seen_scopes:
            raise ReceiptGraphError("receipt-chain node identity is ambiguous")
        seen_nodes.add(node_element_id)
        seen_scopes.add(scope)

        receipts: list[dict[str, Any]] = []
        local_elements: set[str] = set()
        for item in bound:
            if not isinstance(item, dict):
                raise ReceiptGraphError("bound receipt row is malformed")
            receipt_element_id = item.get("receipt_element_id")
            receipt = item.get("receipt")
            if (
                not isinstance(receipt_element_id, str)
                or receipt_element_id in local_elements
                or not isinstance(receipt, dict)
                or physical_by_element.get(receipt_element_id) != receipt
                or owner_by_element.get(receipt_element_id)
                != (node_element_id, tree, tag)
            ):
                raise ReceiptGraphError("node receipt binding is not exact")
            local_elements.add(receipt_element_id)
            seen_receipt_elements.add(receipt_element_id)
            receipts.append(receipt)

        current = row.get("current_receipt_sha")
        prediction = row.get("pred_receipt_sha")
        if current is not None and not _sha(current):
            raise ReceiptGraphError("current receipt pointer is malformed")
        if prediction is not None and not _sha(prediction):
            raise ReceiptGraphError("prediction receipt pointer is malformed")
        if current is None and receipts:
            raise ReceiptGraphError("receipts exist without a current head")
        if current is not None and not receipts:
            raise ReceiptGraphError("current head has no bound receipt")
        try:
            fold_receipt_chain(receipts, current)
        except (ReceiptChainBroken, KeyError, TypeError) as exc:
            raise ReceiptGraphError(str(exc)) from exc

        by_sha = {receipt["receipt_sha"]: receipt for receipt in receipts}
        ancestors: set[str] = set()
        cursor = current
        while cursor is not None:
            if cursor in ancestors or cursor not in by_sha:
                raise ReceiptGraphError("receipt ancestry cannot reach genesis")
            ancestors.add(cursor)
            cursor = by_sha[cursor].get("prev_receipt_sha")
        if ancestors != set(by_sha):
            raise ReceiptGraphError("bound receipt side branch is unreachable from head")
        if prediction is not None:
            pred = by_sha.get(prediction)
            if (
                prediction not in ancestors
                or not isinstance(pred, dict)
                or pred.get("receipt_kind") != "prediction"
            ):
                raise ReceiptGraphError("prediction pointer is not an ancestor receipt")
        ancestors_by_scope[scope] = frozenset(ancestors)

    if seen_receipt_elements != set(physical_by_element):
        raise ReceiptGraphError("orphan receipt is not represented by one node chain")

    return ReceiptChainIndex(
        ancestors_by_scope=ancestors_by_scope,
        receipt_by_sha=receipt_by_sha,
    )
