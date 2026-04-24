# Document Storage

## Ziel

Der `pos-product-core` soll PDF- und Attachment-Inhalte nicht dauerhaft in einer relationalen Datenbank speichern.
Stattdessen gilt:

- Inhalt in einem Document Store / Object Store
- Metadaten in PostgreSQL
- fachliche Referenzen im `sales_process`

## Aktueller technischer Schnitt

Im Code gibt es jetzt eine austauschbare `DocumentStorage`-Abstraktion:

- `filesystem`
  fuer lokale Entwicklung, Demos und einfache Preview-Staende
- `azure_blob`
  fuer Azure-basierte Deployments mit Blob Storage

Die Auswahl erfolgt ueber `POS_CORE_DOCUMENT_STORAGE_PROVIDER`.

## Konfiguration

- `POS_CORE_DOCUMENT_STORAGE_PROVIDER=filesystem|azure_blob`
- `POS_CORE_DOCUMENT_STORAGE_CACHE_ROOT`
- `POS_CORE_DOCUMENT_STORAGE_AZURE_CONNECTION_STRING`
- `POS_CORE_DOCUMENT_STORAGE_AZURE_CONTAINER`

## Warum dieser Schnitt hilfreich ist

- Die fachliche Logik in `sales_process` kennt keine Blob-APIs.
- Wir koennen lokal weiter mit Dateisystem arbeiten.
- Fuer Azure kommt spaeter nur noch Secret-/Identity-Wiring dazu.
- Ein spaeterer Wechsel auf S3-kompatiblen Storage bleibt moeglich.

## Naechster Ausbau

Fuer produktionsnahe Azure-Deployments sollten wir danach noch ergaenzen:

1. Secret-Injektion ueber Key Vault oder Managed Identity
2. Download-URLs bzw. signierte URLs fuer grosse Dokumentmengen
3. Pruefsummen, Groessen und Storage-Provider als explizite DB-Metadaten
