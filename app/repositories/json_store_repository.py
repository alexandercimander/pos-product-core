from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsonStoreRepository:
    def __init__(self, root: Path) -> None:
        self.root = root

    def read(self, filename: str) -> dict[str, Any]:
        target = self.root / filename
        if not target.exists():
            return {}
        with target.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def write(self, filename: str, payload: dict[str, Any]) -> dict[str, Any]:
        target = self.root / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, ensure_ascii=False)
        return payload
