"""Strict JSON schema export for InvestigationOutput (Task 3.2)."""

from __future__ import annotations

from typing import Any

from tokenpilot.investigator.schema import (
    PROMPT_VERSION,
    investigation_json_schema,
    load_system_prompt,
)


def _walk_objects(node: Any, path: str = "$") -> list[tuple[str, dict[str, Any]]]:
    found: list[tuple[str, dict[str, Any]]] = []
    if isinstance(node, dict):
        if node.get("type") == "object" or "properties" in node:
            found.append((path, node))
        for key, child in node.items():
            if key == "$defs" or key == "definitions":
                if isinstance(child, dict):
                    for name, defn in child.items():
                        found.extend(_walk_objects(defn, f"{path}.{key}.{name}"))
            else:
                found.extend(_walk_objects(child, f"{path}.{key}"))
    elif isinstance(node, list):
        for i, child in enumerate(node):
            found.extend(_walk_objects(child, f"{path}[{i}]"))
    return found


def _ref_targets(schema: dict[str, Any]) -> set[str]:
    targets: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                targets.add(ref)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    return targets


def test_schema_is_strict_compatible() -> None:
    schema = investigation_json_schema()
    objects = _walk_objects(schema)
    assert objects, "expected at least one object in schema"
    for path, obj in objects:
        assert obj.get("additionalProperties") is False, path
        props = obj.get("properties") or {}
        required = obj.get("required")
        assert required == list(props.keys()), path

    # No cyclic $ref: each $ref target resolves and a DFS finds no back-edge.
    defs = schema.get("$defs") or schema.get("definitions") or {}
    resolving: set[str] = set()
    seen: set[str] = set()

    def resolve_name(ref: str) -> str | None:
        for prefix in ("#/$defs/", "#/definitions/"):
            if ref.startswith(prefix):
                return ref[len(prefix) :]
        return None

    def dfs(name: str) -> None:
        if name in resolving:
            raise AssertionError(f"cyclic $ref involving {name}")
        if name in seen:
            return
        resolving.add(name)
        defn = defs.get(name)
        if defn is None:
            resolving.remove(name)
            return
        for ref in _ref_targets(defn if isinstance(defn, dict) else {}):
            target = resolve_name(ref)
            if target is not None:
                dfs(target)
        resolving.remove(name)
        seen.add(name)

    for ref in _ref_targets(schema):
        target = resolve_name(ref)
        if target is not None:
            dfs(target)
    for name in defs:
        dfs(name)

    banned = _schema_keyword_noise(schema, {"title", "default"})
    assert banned == set(), f"strict schema must not retain {banned}"


def _schema_keyword_noise(
    node: Any, names: set[str], *, under_properties: bool = False
) -> set[str]:
    """Find banned JSON Schema keywords, ignoring keys that are property *names*."""
    found: set[str] = set()
    if isinstance(node, dict):
        for key, child in node.items():
            if under_properties:
                # Keys under "properties" are field names (e.g. output.title), not keywords.
                found |= _schema_keyword_noise(child, names, under_properties=False)
            else:
                if key in names:
                    found.add(key)
                found |= _schema_keyword_noise(
                    child, names, under_properties=(key == "properties")
                )
    elif isinstance(node, list):
        for child in node:
            found |= _schema_keyword_noise(child, names, under_properties=False)
    return found


def test_prompt_version_and_load() -> None:
    assert PROMPT_VERSION == "investigate_v1"
    text = load_system_prompt()
    assert "supplied measurements" in text.lower() or "only supplied" in text.lower()
    assert "insufficient_evidence" in text
    assert "evidence" in text.lower()
