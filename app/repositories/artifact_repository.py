from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ArtifactRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def read_json(self, *parts: str) -> dict[str, Any]:
        target = self.root.joinpath(*parts)
        with target.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write_json(self, payload: dict[str, Any], *parts: str) -> dict[str, Any]:
        target = self.root.joinpath(*parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        return payload

    def delete(self, *parts: str) -> None:
        target = self.root.joinpath(*parts)
        if target.exists():
            target.unlink()

    def list_json(self, *parts: str) -> list[dict[str, Any]]:
        folder = self.root.joinpath(*parts)
        if not folder.exists():
            return []
        payloads: list[dict[str, Any]] = []
        for file_path in sorted(folder.glob("*.json")):
            with file_path.open("r", encoding="utf-8") as handle:
                payloads.append(json.load(handle))
        return payloads

    def list_directories(self, *parts: str) -> list[str]:
        folder = self.root.joinpath(*parts)
        if not folder.exists():
            return []
        return sorted(path.name for path in folder.iterdir() if path.is_dir())
