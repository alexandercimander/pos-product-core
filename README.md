# pos-product-core

Fachbackend fuer alle Eingangskanaele des PoS-Systems.

## Verantwortung

- Tarifierung
- Gesundheitsfragen
- Vorschlag
- Antrag
- Vertriebsvorgaenge
- Runtime-Projektionen
- Status-Engine

## API-Schnitt

Dieses Repo startet als `FastAPI`-Service und stellt die fachlichen Kernendpunkte bereit unter:

- `/api/applications`
- `/api/health-questions`
- `/api/proposals`
- `/api/runtime`
- `/api/sales-processes`
- `/api/status-engine`
- `/api/tariffs`

## Herkunft des Startstands

Dieser Starter wurde aus dem aktuellen Monolithen herausgeschnitten und enthaelt den ersten logischen `Product Core`-Schnitt. Admin- und Builder-spezifische Endpunkte gehoeren **nicht** hier hinein.

## Naechste Schritte

1. Artefakt- und Datenhaltungsstrategie fuer den Core festziehen
2. Builder-spezifische Restkopplungen sauber entfernen
3. echte Datenbank statt reinem JSON-Store vorbereiten
4. Admin- und Runtime-Consumer ueber stabile API-Vertraege anbinden

## Vertiefende Dokumentation

- `docs/DOCUMENT_STORAGE.md`
- `docs/DATABASE_VERSIONING.md`

## Lokaler Start

```bash
uvicorn app.main:app --reload --port 8001
```
