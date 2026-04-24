# Database Versioning

## Empfehlung

Fuer den aktuellen Stack wuerde ich **Alembic** und nicht Liquibase als ersten Standard waehlen.

Warum:

- `pos-product-core` ist Python- und SQLModel-/SQLAlchemy-nah
- Alembic ist dafuer das natuerliche Migrationswerkzeug
- weniger Betriebsgewicht als Liquibase
- sehr gut fuer service-spezifische Migrationen pro Repo

## Wann Liquibase trotzdem sinnvoll sein kann

Liquibase wuerde ich erst dann bevorzugen, wenn ihr bewusst einen zentralen,
technologieuebergreifenden Datenbank-Governance-Standard wollt, z. B.:

- viele Services in unterschiedlichen Sprachen
- zentrales DBA-/Platform-Team
- einheitlicher Freigabeprozess fuer SQL-Changes

## Zielbild fuer uns

Kurzfristig:

- `pos-builder` bekommt eigene Migrationen
- `pos-product-core` bekommt eigene Migrationen
- jede Service-DB wird separat versioniert

Mittelfristig:

- Migrationslauf in CI/CD
- automatischer Run vor App-Start oder als dedizierter Deploy-Step
- Roll-forward statt manuellem Direkt-SQL

## Versionierungsregeln

1. Jede Schemaaenderung erfolgt ueber Migrationen.
2. Kein manuelles SQL in produktionsnahen Umgebungen.
3. App-Code und Migration werden im selben Repo versioniert.
4. Releases dokumentieren, welche Migrationen erforderlich sind.
5. Rueckwaertskompatible Migrationen bevorzugen, wenn mehrere Runtimes parallel laufen.

## Was wir spaeter konkret aufbauen sollten

- Alembic-Setup pro Python-Service
- `migrations/versions`
- Baseline-Migration fuer die ersten Produktivtabellen
- Deployment-Step wie:
  - `alembic upgrade head`

## Wichtig fuer Builder vs. Core

Die Datenbanken sollten getrennt versioniert werden:

- `pos-builder` Migrationen nur fuer Control-Plane-Tabellen
- `pos-product-core` Migrationen nur fuer operative Fachtabellen

So bleiben Verantwortung und Rollout sauber getrennt.
