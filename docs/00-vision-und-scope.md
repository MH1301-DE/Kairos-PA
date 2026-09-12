# 00 — Vision & Scope

## 1. Kernversprechen

> **Kairos gibt dir täglich eine klare, verlässliche Antwort auf die Fragen: Wie
> fit bin ich wirklich? Was sollte ich heute trainieren — und wann passt es in
> meinen Tag?**

Der Assistent liest Garmin-Daten und Kalender, berechnet Kennzahlen deterministisch
und macht — auf Wunsch — konkrete Vorschläge. Er ersetzt keine Sportwissenschaft,
aber er macht dein eigenes Wissen handlungsfähig.

---

## 2. Ziele

### 2.1 Primärziele

1. **Morgenritual.** Täglich auf einen Blick: Erholungszustand, Belastungsform,
   freie Blöcke im Kalender. Ohne App-Hopping zwischen Garmin Connect, Kalender und
   Tabellenkalkulation.

2. **Konkrete Trainingsvorschläge statt Allgemeinplätze.** Der Agent kennt CTL, ATL,
   TSB, HRV-Baseline, letzten harten Reiz und nächstes Ziel. Er sagt nicht
   "Erholung ist wichtig" — er sagt "dein TSB ist −17, die nächste harte Einheit
   solltest du frühestens übermorgen legen. Heute passt ein 45-min-Locker-Lauf, ab
   18:30 hast du Zeit."

3. **Zeitersparnis bei der Wochen- und Saisonplanung.** Trainingsblöcke, Wettbewerbe
   und Erholungsphasen landen auf Knopfdruck als Kalendertermine — bestätigt, nicht
   blindlings ausgeführt.

4. **Tiefe Einblicke in Gesundheits- und Trainingszustand.** Langzeittrends,
   Korrelationen, Zielvergleiche — ohne SQL oder Tabellenkalkulation. Der Agent
   rechnet, du interpretierst.

5. **Daten, denen du vertraust.** Vollständiges Archiv aller Garmin-Rohdaten.
   Plausibilitätsprüfung, Datenquality-Flags, Datenstand-Anzeige im Dashboard.
   Keine Halluzination von Zahlen.

### 2.2 Sekundärziele

- Nahtlose Multi-Kalender-Unterstützung (Google + Apple/CalDAV) ohne manuelle
  Synchronisation.
- Proaktive Hinweise bei Auffälligkeiten (HRV-Einbruch, Schlafdefizit,
  Übertrainingssignal) — dosiert, nicht nervig.
- Erweiterbar für weitere Domänen (Ernährung, Lernen, Stimmung) ohne Umbau des Kerns.

---

## 3. Nicht-Ziele

| Was Kairos nicht ist | Begründung |
|---|---|
| **Kein öffentliches Produkt** | Entwickelt für eine geschlossene Gruppe von 5 Personen; kein Signup, keine Skalierung auf beliebig viele Nutzer |
| **Kein Arzt / keine medizinische Diagnose** | Gesundheitsdaten werden analysiert, nie diagnostiziert. Bei auffälligen Mustern wird auf ärztliche Abklärung hingewiesen — ohne eigene Deutung |
| **Kein Ernährungsberater** | Keine Kalorientracking- oder Diät-Empfehlungen; Körperzusammensetzung wird erfasst, aber nicht bewertet |
| **Kein Ersatz für Sportwissenschaft** | Kairos rechnet bewährte Kennzahlen (TRIMP, CTL/ATL/TSB, HRV-Baseline) — er ersetzt keinen Trainer, der das Gesamtbild kennt |
| **Kein allgemeines Produktivitätswerkzeug** | Keine Aufgabenverwaltung, kein E-Mail-Client, keine Notizapp — Fokus auf Training und Zeitplanung |

---

## 4. Nutzergruppe

**5 Personen, einander bekannt, selbst betrieben.**

- Alle haben Zugang zu Garmin Connect und einem oder mehreren Kalendern.
- Mindestens eine Person (Betreiber) hat technisches Grundverständnis für Deployment
  und Konfiguration.
- Die anderen Nutzer werden geführt ongeboardet, brauchen aber keine technischen
  Kenntnisse für den Normalbetrieb.
- Garmin-Gerätemodelle variieren (Forerunner, Fenix, Venu-Klasse) — die
  verfügbaren Datentypen können pro Nutzer abweichen (z. B. HRV-Status, Training
  Readiness, Body Battery).

---

## 5. Use Cases — die 15 Referenzfragen

Diese Fragen sind gleichzeitig die **Eval-Suite**: Kairos muss sie vollständig,
korrekt und nachvollziehbar beantworten können, bevor Phase 4 als abgeschlossen gilt.
Die genannten Zahlen müssen exakt mit dem Tool-Ergebnis übereinstimmen.

### Gesundheit & Erholung

1. *"Wie erholt bin ich heute?"* — HRV vs. 60-Tage-Baseline, Ruhepuls-Trend, Body
   Battery, Schlafdefizit der letzten Woche.
2. *"Habe ich mich letzte Woche genug erholt?"* — TSB-Verlauf, Schlafbilanz,
   Stressmittel.
3. *"Wann war mein letzter echter Ruhetag?"* — Aktivitätslücke ≥ 24 h, TRIMP = 0.
4. *"Wie sieht mein Schlaf im Vergleich zu letztem Monat aus?"* — Trend
   Schlafdauer, Score, REM-Anteil.
5. *"Mein Puls war gestern beim gleichen Tempo deutlich höher als sonst — warum
   könnte das sein?"* — HRV, Schlaf, Temperatur, Trainingsstress der Vortage.

### Training & Belastung

6. *"Wie viel habe ich in den letzten 4 Wochen trainiert?"* — Volumen, TRIMP,
   Einheiten je Sportart, Vergleich zu den 4 Wochen davor.
7. *"Was war meine bisher beste 5-km-Zeit dieses Jahr?"* — Aktivitätssuche, Pace,
   Datum.
8. *"Wann sollte ich die nächste harte Einheit machen, ohne mich zu überlasten?"* —
   TSB, ACWR, freie Kalenderblöcke, Mindestabstand zur letzten harten Session.
9. *"Wie entwickelt sich meine Fitness dieses Jahr?"* — CTL-Verlauf YTD.
10. *"Vergleich meinen Lauf von gestern mit dem letzten Tempolauf."* — Pace,
    Kadenz, ⌀HR, Herzfrequenz-Reserve, Effizienz.

### Planung & Kalender

11. *"Plane eine Lauf-Einheit für morgen — wann passt es in meinen Tag?"* —
    Kalenderblöcke ≥ 60 min, Erholungszustand, Wetterhinweis falls Integration
    vorhanden.
12. *"Wie weit bin ich noch von meinem Halbmarathon-Ziel entfernt?"* —
    Zieldatum, aktuelles CTL vs. Ziel-CTL, verbleibende Wochen.
13. *"Erstell mir einen Trainingsplan für die nächsten 3 Wochen."* —
    Periodenplanung, Erholungsphasen, Constraints aus Kalender.
14. *"Ich habe nächste Woche viel Stress. Wie passe ich das Training an?"* —
    Belastungsreduktion, Kompromiss zwischen Fitnesshalt und Erholung.
15. *"Was habe ich diese Woche schon trainiert und was fehlt noch laut Plan?"* —
    Plan-Ist-Abgleich, offene Blöcke, TSB-Vorhersage bis Wochenende.

---

## 6. Rahmenbedingungen

| Aspekt | Entscheidung | Notiz |
|---|---|---|
| Deployment | Einzelne Linux-VM (Hetzner o. Ä.), Docker Compose | Kein Kubernetes |
| LLM-Zugang | API-basiert, pluggable über litellm (beliebiger Anbieter/API-Key pro Nutzer) | Gesundheitsdaten nur als Aggregate — nie roh; siehe [Phase-4-MVP-Design](superpowers/specs/2026-09-12-phase-4-agent-mvp-design.md) |
| Garmin-Zugang | Inoffizielle Connect-API (`garth`) | Offizielle Health API erfordert B2B-Partnerschaft; ToS-Risiko dokumentiert in [ADR-0004](adr/ADR-0004-garmin-zugang.md) |
| Nutzeranzahl | 5, geschlossene Gruppe | Kein öffentliches Signup |
| Datentrennung | Logisch via Postgres RLS | Nicht physisch getrennte Datenbanken |
| Frontend | PWA (React/Next.js oder SvelteKit) | Entscheidung steht aus, siehe [08](08-roadmap.md#vor-phase-0) |
| Sprache Backend | Python 3.12, FastAPI | — |

---

## 7. Was jetzt noch offen ist

Vollständige Liste in [08 — Roadmap, Abschnitt "Offene Punkte"](08-roadmap.md#3-offene-punkte).

Die wichtigsten Entscheidungen **vor Baubeginn**:

1. **Frontend-Framework** — SvelteKit oder Next.js?
2. **LLM-Anbieter und Modell-Routing** — welches Modell für Analyse, welches für
   einfache Abfragen?
3. **Garmin-Gerätemodelle** aller 5 Nutzer (beeinflusst verfügbare Datentypen).
5. **Backfill-Tiefe**: 12 Monate (Annahme) oder mehr?
