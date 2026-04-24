from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from typing import Any
from urllib import error, request

from fastapi import HTTPException

from app.core.config import settings


@dataclass
class ExternalHttpResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=502, detail="Externe Antwort war kein gueltiges JSON.") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=502, detail="Externe Antwort muss ein JSON-Objekt sein.")
        return payload


def _build_headers(auth_type: str) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, application/pdf",
    }
    if auth_type == "BASIC":
        token = base64.b64encode(
            f"{settings.external_basic_username}:{settings.external_basic_password}".encode("utf-8")
        ).decode("ascii")
        headers["Authorization"] = f"Basic {token}"
    elif auth_type == "BEARER":
        headers["Authorization"] = f"Bearer {settings.external_bearer_token}"
    elif auth_type == "API_KEY" and settings.external_api_key_value:
        headers[settings.external_api_key_header] = settings.external_api_key_value
    return headers


def post_json(endpoint: str, payload: dict[str, Any], auth_type: str = "NONE") -> ExternalHttpResponse:
    if not endpoint:
        raise HTTPException(status_code=400, detail="Kein externer Endpoint konfiguriert.")

    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        endpoint,
        data=body,
        headers=_build_headers(auth_type),
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=settings.external_request_timeout_seconds) as response:
            return ExternalHttpResponse(
                status_code=response.status,
                headers={key: value for key, value in response.headers.items()},
                body=response.read(),
            )
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore") or exc.reason
        raise HTTPException(
            status_code=502,
            detail=f"Externer Endpoint antwortete mit Fehler: {detail}",
        ) from exc
    except error.URLError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Externer Endpoint konnte nicht erreicht werden: {exc.reason}",
        ) from exc
