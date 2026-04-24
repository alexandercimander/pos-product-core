from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class BindingSegment:
    key: str
    role_filter: str | None = None
    index: int | None = None
    index_alias: str | None = None


def parse_binding_path(path: str) -> list[BindingSegment]:
    segments: list[BindingSegment] = []
    for raw_segment in path.split("."):
        if "[role=" in raw_segment and raw_segment.endswith("]"):
            key, filter_part = raw_segment.split("[role=", maxsplit=1)
            segments.append(BindingSegment(key=key, role_filter=filter_part[:-1]))
            continue
        if raw_segment.endswith("]") and "[" in raw_segment:
            key, index_part = raw_segment.split("[", maxsplit=1)
            if index_part[:-1].isdigit():
                segments.append(BindingSegment(key=key, index=int(index_part[:-1])))
                continue
            if index_part[:-1].isidentifier():
                segments.append(BindingSegment(key=key, index_alias=index_part[:-1]))
                continue
        segments.append(BindingSegment(key=raw_segment))
    return segments


def _resolve_alias_index(payload: dict[str, Any], alias: str | None) -> int | None:
    if alias not in {"active", "current"}:
        return None
    runtime_context = payload.get("runtimeContext")
    if isinstance(runtime_context, dict):
        value = runtime_context.get("activeInsuredPersonIndex")
        if isinstance(value, int) and value >= 0:
            return value
    return 0


def resolve_binding(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for segment in parse_binding_path(path):
        if not isinstance(current, dict):
            return None

        current = current.get(segment.key)
        if segment.role_filter:
            if not isinstance(current, list):
                return None
            current = next(
                (item for item in current if segment.role_filter in item.get("roles", [])),
                None,
            )
        resolved_index = (
            segment.index
            if segment.index is not None
            else _resolve_alias_index(payload, segment.index_alias)
        )
        if resolved_index is not None:
            if not isinstance(current, list):
                return None
            if resolved_index >= len(current):
                return None
            current = current[resolved_index]
    return current
