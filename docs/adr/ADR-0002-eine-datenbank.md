# ADR-0002 — Eine Datenbank: Postgres + TimescaleDB + pgvector

**Status:** Akzeptiert  
**Datum:** 2026-08-01  
**Entscheider:** Betreiber

---

## Kontext

Kairos hat drei verschiedene Datenzugriffsanforderungen:

1. **Zeitreihen** (Garmin-Wellness-Daten, Aktivitäten): 48 Mio. Zeilen über 5 Jahre,
   Zeitbereichsabfragen, Kompression, Continuous Aggregates.
2. **Relational** (Nutzer, Kalender, Planung, Agent-Konversationen): klassische
   Joins, Constraints, RLS.
3. **Vektoren** (Tool-Embeddings, semantisches Gedächtnis): ANN-Suche über
   ~50.000–100.000 Embeddings.

Die Frage war, ob spezialisierte Systeme je Anforderung sinnvoller sind
(z. B. InfluxDB + Postgres + Qdrant) oder ein einheitliches System.

---

## Entscheidung

**PostgreSQL 16 + TimescaleDB-Extension + pgvector-Extension** als einzige
persistente Datenbank. Redis ergänzt als flüchtiger Cache und Job-Queue,
ersetzt aber keine persistente Datenbank.

---

## Begründung

### Zeitreihen: TimescaleDB vs. InfluxDB / Prometheus

| Kriterium | TimescaleDB | InfluxDB |
|---|---|---|
| Kompression (numerische Serien) | 10–20× | 8–15× |
| SQL-Abfragen, Joins mit relationalen Daten | ✅ vollständig | ❌ Flux/InfluxQL |
| Continuous Aggregates | ✅ | ✅ (Tasks) |
| Zweites operatives System | nein | **ja** |
| Volumen (48 Mio. Zeilen / 5 Jahre) | ✅ trivial | ✅ |

TimescaleDB ist eine Postgres-Extension — kein separater Prozess, kein separates
Backup, kein separates Monitoring. Für das vorliegende Volumen (< 10 GB komprimiert)
gibt es keinen Vorteil einer dedizierten TSDB.

### Vektoren: pgvector vs. Qdrant / Weaviate

| Kriterium | pgvector (HNSW) | Qdrant |
|---|---|---|
| Latenz ANN-Suche (<100k Vektoren) | < 10 ms | < 5 ms |
| Zweites operatives System | nein | **ja** |
| Transaktionale Konsistenz mit relationalen Daten | ✅ | ❌ |
| Setup | Extension, 1 Zeile | separater Container |

Für < 100.000 Embeddings (Tool-Registry + Memories) ist pgvector mit HNSW-Index
schnell genug. Der Latenz-Vorteil von Qdrant ist bei diesem Volumen nicht messbar
relevant.

### Fazit

Ein operatives System bedeutet:
- Ein Backup-Job
- Ein Monitoring-Target
- Ein Migrations-System (Alembic)
- Keine verteilten Queries über Systemgrenzen

---

## Konsequenzen

### Positiv
- RLS gilt für alle Daten — Zeitreihen, Vektoren und relationale Daten sind
  mandantengetrennt mit demselben Mechanismus.
- Continuous Aggregates können über Joins mit relationalen Tabellen rechnen.
- Ein `pg_dump` sichert alles.

### Einschränkungen
- **Postgres skaliert vertikal, nicht horizontal.** Für 5 Nutzer und < 10 GB ist
  das kein Argument. Wenn Kairos je auf hunderte Nutzer wächst, wäre eine
  Datenbank-Separation sinnvoll — das ist dann ein anderes Projekt.
- **pgvector HNSW baut den Index im Speicher.** Bei > 1 Mio. Vektoren würde das
  RAM-Budget der VM sprengen. Aktuell: ~50.000 Embeddings (Tool-Registry +
  Memories) — unkritisch.

### Ausnahme: Redis

Redis ist kein persistenter Datenspeicher, sondern flüchtiger Job-Queue-Broker
und Cache (Session-State, Rate-Limit-Counters, Sync-Locks). Datenverlust beim
Redis-Neustart ist tolerierbar; alle persistenten Daten leben in Postgres.
