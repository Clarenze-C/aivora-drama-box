"""API-format prompt-graph validation against a server's actual node catalog (T013).

A UI-format workflow (the editor's ``{"nodes": [...], "links": [...]}`` export) is never a
runnable API payload and is refused with a typed error naming the problem. Node capability
is checked against the ``object_info`` catalog the *server* reported — not a hardcoded
list — so a graph is only dispatched when the live server actually has every class, every
required input and every link slot. A missing node is a typed ``UnsupportedControl``:
this adapter installs nothing, ever (AT-04)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from microdrama.contracts.errors import SchemaInvalid, UnsupportedControl
from microdrama.contracts.providers import ComfyNodeInfo


def _is_link(value: object) -> bool:
    return (
        isinstance(value, list)
        and len(value) == 2
        and isinstance(value[0], str)
        and isinstance(value[1], int)
        and not isinstance(value[0], bool)
    )


def is_ui_format(graph: Any) -> bool:
    """True for an editor UI-format export (top-level ``nodes``/``links`` lists)."""
    return isinstance(graph, dict) and (
        isinstance(graph.get("nodes"), list) or isinstance(graph.get("links"), list)
    )


def validate_api_graph(graph: Any, catalog: Mapping[str, ComfyNodeInfo]) -> None:
    """Validate the API-format prompt graph against a server's reported node catalog.

    Typed failures, each before anything is dispatched:
    - not a non-empty object, or a UI-format workflow → ``SchemaInvalid``;
    - a node without ``class_type``/``inputs`` → ``SchemaInvalid`` (with ``node_id``);
    - a ``class_type`` absent from the catalog → ``UnsupportedControl`` (nothing is
      installed to satisfy it);
    - a catalog-required input missing → ``SchemaInvalid`` (with ``missing``);
    - a link to an absent/malformed node, or a slot beyond the target's declared
      outputs → ``SchemaInvalid`` (with ``input``/``target``/``slot``).
    """
    if not isinstance(graph, dict) or not graph:
        raise SchemaInvalid("prompt graph must be a non-empty object")
    if is_ui_format(graph):
        raise SchemaInvalid(
            "UI-format workflow rejected: submit the API-format prompt graph "
            "(export via Save (API Format), not the editor workflow)"
        )
    for node_id, node in graph.items():
        if (
            not isinstance(node, dict)
            or not isinstance(node.get("class_type"), str)
            or not isinstance(node.get("inputs"), dict)
        ):
            raise SchemaInvalid("malformed node: needs class_type and inputs", node_id=str(node_id))
        info = catalog.get(node["class_type"])
        if info is None:
            raise UnsupportedControl(
                "unknown node class for this server; this adapter installs nothing",
                node_id=str(node_id),
                class_type=node["class_type"],
            )
        missing = [name for name in info.required_inputs if name not in node["inputs"]]
        if missing:
            raise SchemaInvalid("required inputs missing", node_id=str(node_id), missing=missing)
        for name, value in node["inputs"].items():
            if not _is_link(value):
                continue
            target_id, slot = value
            target = graph.get(target_id)
            if not isinstance(target, dict):
                raise SchemaInvalid(
                    "link points at a missing node",
                    node_id=str(node_id),
                    input=name,
                    target=str(target_id),
                )
            target_info = catalog.get(target.get("class_type"))
            if target_info is not None and slot >= len(target_info.output_types):
                raise SchemaInvalid(
                    "link slot is beyond the target node's declared outputs",
                    node_id=str(node_id),
                    input=name,
                    target=str(target_id),
                    slot=slot,
                    declared_outputs=list(target_info.output_types),
                )


__all__ = ["is_ui_format", "validate_api_graph"]
