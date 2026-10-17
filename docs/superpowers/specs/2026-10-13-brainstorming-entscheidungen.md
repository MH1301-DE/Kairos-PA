# Brainstorming: Aktivitäten, Workouts und Coach-Modus (Entscheidungsprotokoll)

| | |
|---|---|
| **Datum** | 2026-10-13 |
| **Beteiligt** | Max (Entscheidungen), Claude (Vorschläge, Analysen) |
| **Grundlage** | Spec [`2026-10-07-aktivitaeten-und-workouts-design.md`](2026-10-07-aktivitaeten-und-workouts-design.md) nach AP 0; Prüfaufträge P1–P3 (Claude Code, 2026-10-13) |
| **Folgedokumente** | überarbeitete Spec (Stufe 1, in diesem Commit); Spec Stufe 2 „Scheduler & Proaktivität“ (offen); Spec Stufe 3 „Coach-Modus“ samt Wissensbank (offen) |

Das Brainstorming lief in vier Fragerunden. Die Spalte „Quelle“ nennt die Frage, auf
die die Entscheidung zurückgeht (Runde 1: F1–F17, Runde 2: R1–R15, Runde 3: T1–T3, K1,
K2, H1, S1, N1, A1, Runde 4: C1–C7).

---

## 1. Stufenplan

| Stufe | Inhalt | Dokument |
|---|---|---|
| **1** | Datenbasis (Speicherformat, FIT-Archiv, TimescaleDB entfernen, lokale Tagesgrenzen, HFmax), Aktivitäts-Tools inkl. Soll/Ist pro Intervall, Workouts inkl. Sekundärzielen (nach Uhr-Test), Aktivitäten bearbeiten und löschen | Spec 2026-10-07, überarbeitet |
| **1.1** | Kraft-Workouts mit Übungen, Sätzen, Wiederholungen und Gewicht | Ergänzung der Spec nach Stufe 1 |
| **2** | Scheduler, Web-Push, automatische Reaktionen und Entlastung | neue Spec + ADR |
| **3** | Coach-Modus, Trainingsmodell, Wissensbank; die Recherche dafür beginnt parallel zu Stufe 1 | neue Spec |

Begründung der Reihenfolge (T1): Stufe 1 bringt sofort Nutzen. Max plant weiter im Chat,
aber in Kairos, und Kairos legt die Workouts selbst auf die Uhr; der eigene Importer wird
überflüssig. Der Halbmarathon am 29.11.2026 liegt vor einem fertigen Planer.

---

## 2. Entscheidungen

### 2.1 Datenhaltung und Betrieb

| # | Entscheidung | Quelle | Folge |
|---|---|---|---|
| D1 | Sekundendaten als Arrays: eine Zeile je Aktivität und Kanal, eine gemeinsame Zeitachse je Aktivität | F1 (c) | P2: 475 MB → 8,5 MB für 139 Aktivitäten (≈ 58× kleiner). `activity_record` entfällt. |
| D2 | Keine Auswertungen über die Sekundendaten mehrerer Aktivitäten (vorerst) | F2 | Fragen über mehrere Aktivitäten beantworten die abgeleiteten Tabellen. |
| D3 | Original-FIT als ZIP archivieren, statt des dekodierten JSON; Bestand einmal gedrosselt neu laden | F3, R1 (a) | Neuberechnung ohne Garmin-Request; Workout-Schritte, Bahnen und Pausen-Events bleiben erhalten. ≈ 125 KB je Aktivität. |
| D4 | TimescaleDB entfernen, Standard-Image Postgres 16 | F4 (b), R2 (a) | Genutzt wurden nur Hypertables; Kompression und Continuous Aggregates sind wegen RLS gesperrt. ADR-0002 anpassen. |
| D5 | Backups bleiben außerhalb des Scopes | F5 | Risiko: Die Datenbank ist der einzige Ort; Rückfallebene ist ein neuer Backfill aus Garmin (≈ 3 h je Nutzer). |
| D6 | VM-Entscheidung offen | F6 | Mit D1 und D3 braucht das Doku-Szenario (5 Nutzer × 250 Aktivitäten/Jahr × 5 Jahre) ≈ 5 GB Datenbank; 40 GB SSD reichen. |
| D7 | Kein Managed Postgres oder Redis zur Speicherentlastung | Analyse 13.10. | Speicher pro GB dort 2–6× teurer; Timescale-Kompression bleibt auch dort wegen RLS gesperrt; Redis hält alles im RAM. |

### 2.2 Datenqualität und Kennzahlen

| # | Entscheidung | Quelle | Folge |
|---|---|---|---|
| D8 | Tagesgrenzen nach Ortszeit statt UTC | F7 (a) | Aktivitätsdaten über ihren lokalen Start, Wellness-Daten über `app_user.home_timezone`. Tageswerte der Historie verschieben sich leicht; einmal neu berechnen. |
| D9 | TRIMP zählt weiter Samples als Sekunden | F8, P1 | P1: Die Uhr zeichnet sekündlich auf (Zeilen/Timer-Zeit = 1,000–1,003). Die vermutete Untererfassung gibt es nicht. |
| D10 | HFmax: Eingabe durch den Nutzer, sonst 220 − Alter. Der gemessene Höchstwert fließt nicht mehr ein, löst aber einen Hinweis aus, wenn er über dem eingetragenen Wert liegt. | F9, H1 | Neue Einstellungsseite für HFmax und Geburtsdatum (beides existiert nur in `user_setting`, ohne UI/API). Max: 214 bpm bestätigt. |
| D11 | Pace kurzer Abschnitte aus der Distanz rechnen; Laufleistung vom Handgelenk nur mit Hinweis zeigen | Befund Browser-Chat | Garmins Geschwindigkeitsfeld war in Max' Daten um ≈ 12–15 s geglättet; Laufleistung und Pace korrelierten mit r = 0,16. |

### 2.3 Workouts und Aktivitäten (Stufe 1)

| # | Entscheidung | Quelle | Folge |
|---|---|---|---|
| D12 | Soll/Ist pro Intervall in V1 | F13 (a) | Struktur aus den Workout-Schritten der FIT und den Runden (P3); HF-Ziele aus der Garmin-API, weil die FIT sie mehrdeutig kodiert. |
| D13 | Trefferregel: Pace-, Geschwindigkeits-, Kadenz- und Leistungsziele gelten als getroffen, wenn der Ø-Wert im Bereich ± 2 % liegt; HF-Ziele, wenn mindestens 80 % der Zeit im Bereich liegen | R10 (a) | — |
| D14 | Sekundärziele in Workouts, sobald geprüft ist, dass die Uhr sie anzeigt | C7 (b) | Neuer Prüfschritt AP 0b. |
| D15 | Kraft-Workouts mit Übungen als V1.1 direkt nach V1 | F14, R9, S1 (b) | `garminconnect` 0.3.17 bringt `StrengthWorkout`, `create_strength_set` und einen Katalog mit 1.527 Übungen in 47 Kategorien mit. |
| D16 | Bestleistungs-Distanzen bleiben: 800 m bis 100 km | F15 | — |
| D17 | Sichtbarer Marker `[kairos:…]` in der Workout-Beschreibung ist in Ordnung | F16 (a) | — |
| D18 | Aktivitäten in Garmin umbenennen und löschen bleibt in V1 | F17 (a) | — |

### 2.4 Training und Coach-Modus (Stufe 3)

| # | Entscheidung | Quelle | Folge |
|---|---|---|---|
| D19 | Kairos erzeugt die Trainingspläne selbst | F10 (a) | Die Platzhalter-Templates der Spec entfallen; die Planung zieht in den Coach-Modus. |
| D20 | Coach-Modus als eigener Bereich plus Chat: geführter Einstieg (Ziel, Zeitraum, verfügbare Tage, Sportarten, Testwert), Feinplanung und Wochenbesprechung im Chat | T3, C1 (a) | — |
| D21 | Phasen bis zum Ziel grob, Details rollierend 1–2 Wochen im Voraus, Anpassung in der Wochenbesprechung | C2 (a) | Entspricht Max' heutigem Rhythmus (Sonntagabend nach dem Long Run). |
| D22 | Jeder Nutzer plant für sich | C3 (a) | Kein Rollenmodell für fremde Daten nötig. |
| D23 | Für alle Nutzer von Anfang an; Hauptsport Laufen, Rad oder Triathlon; Ergänzungen Kraft, Schwimmen, Yoga; Ziele unterschiedlich ambitioniert | R4 (b), C4 (b), C5 | Die Recherche muss Ausdauer-Hauptsportarten und Ergänzungssport abdecken, auch für Ziele ohne Wettkampf. |
| D24 | Wissensbank als Dateien im Repo: Einträge in eigenen Worten mit Quellen, je Eintrag ein Regelteil (führt der Plan-Generator im Code aus) und ein Erklärteil (liest der Agent zur Laufzeit) | F11, R5, R6 (a + b), K1 (a) | Jeder Planblock verweist auf Regel-ID und Version. Später optional als schreibgeschützte Kopie in Postgres. |
| D25 | Plantyp als Einstellung je Nutzer | K2 (a) | — |
| D26 | Die Bezugswerte (Pace aus Leistung, HF, Schwellen) gehören zum Plantyp | R7 | Kairos muss alle Bezugswerte liefern können. |
| D27 | Max' Regeln aus dem Browser-Coaching werden der Entwurf des ersten Plantyps; sein Phase-I-Plan wird bei Inbetriebnahme als laufender Plan übernommen | T2, C6 (a), R8 (a) | Bestand siehe §4. |
| D28 | `plan_commit`/`plan_adjust` mit Garmin-Workouts (Teil E der Spec) werden in Stufe 3 umgesetzt, nicht in Stufe 1 | Folge aus T1 und D19 | Bis dahin bleiben die `plan_*`-Tools unverändert; Workouts legt der Chat über die Workout-Tools an. |

### 2.5 Scheduler und Proaktivität (Stufe 2)

| # | Entscheidung | Quelle | Folge |
|---|---|---|---|
| D29 | Automatisch laufen: Garmin-Sync, Kalender-Sync, Neuberechnung, Workout-Abgleich, Wochenrückblick | R11 | Vorschlag: Garmin tagsüber alle 2 h, nachts einmal vollständig. |
| D30 | Reaktionen: neue Aktivität → Soll/Ist-Feedback; Workout verpasst → Vorschlag; schlechte Erholung → nächste harte Einheit entschärfen; Kalenderkonflikt → Vorschlag; Wochenrückblick am Sonntag | R12 (a–e) | — |
| D31 | Wochenrückblick zusätzlich jederzeit auf Abruf im Chat | F12 (a) | Geht mit den Tools aus Stufe 1. |
| D32 | Automatische Entlastung ohne Vorab-Bestätigung mit Leitplanken: nur entlasten, nur das nächste Workout innerhalb von 48 h, Umfang höchstens 30 % kürzer oder harte Einheit durch lockere gleicher Dauer ersetzen, sofort Push mit „Rückgängig“ bis Trainingsbeginn. Verschieben, Hinzufügen, Löschen und Mehrbelastung bleiben Vorschläge. | R13 (b), A1 (a) | Ausnahme von „Schreibvorgänge brauchen Bestätigung“ (`01` §5.3, `06` Prinzip 5) → eigener ADR. Präzedenzfall: `remember`. |
| D33 | Benachrichtigung per Web-Push über die PWA; Telegram optional später; WhatsApp verworfen | R14 (b), N1 (a) | iPhone: ab iOS 16.4, App auf dem Home-Bildschirm, Freigabe per Tipp; Inhalt Ende-zu-Ende verschlüsselt (RFC 8291). WhatsApp: Meta-Konto, Vorlagen, ≈ 0,055 $ je proaktiver Nachricht, Gesundheitsdaten über Meta. |
| D34 | Meldehäufigkeit je Nutzer einstellbar | R15 | Vorschlag Default: höchstens eine Meldung am Tag bei Auffälligkeiten plus Wochenrückblick. |

---

## 3. Befunde vom 2026-10-13

**P1 Abtastrate.** Für die letzten 20 Aktivitäten liegt das Verhältnis HF-Zeilen zu
`duration_s` bei 1,000–1,003, der Median-Abstand der Zeitstempel bei 1 s. Längere Lücken
(13–91 s) sind Pausen. `activity.duration_s` ist damit die Timer-Zeit ohne Pausen.

**P2 Speicher des Array-Formats** (lz4, reale Daten, 139 Aktivitäten):

| | `activity_record` heute | Arrays |
|---|---|---|
| Zeilen | 2.226.357 | 839 Kanalzeilen + 139 Zeitachsen |
| Größe | 475 MB (225 MB Tabelle, 249 MB Indizes) | 8,5 MB (Zeitachsen 1,5 MB, Kanäle 6,6 MB) |
| je Aktivität | 3.499,5 KB | 59,9 KB |

Je Aktivität und Kanal: HF 3,6 KB, Kadenz 2,7, Höhe 4,3, Geschwindigkeit 5,0, Leistung 6,3,
Breite 13,4 und Länge 14,2 (beide `float8`), Zeitachse 9,8 KB (`int4`). Die Zeitachse
macht ≈ 16 % aus; Lauflängen-Kodierung (sekündlich bis auf Pausen) würde sie fast
vollständig einsparen.

**P3 Workout-Schritte in der Aktivitätsdatei** (Aktivität 272, „W3 Do Schwelle 4x6“, 10.09.2026):

- Die archivierten Runden enthalten `wkt_step_index` (0 Einlaufen, 1 Intervall, 2 Trabpause,
  4 Auslaufen; die letzte Runde mit Auslöser `session_end` hat keinen). Index 3 ist der
  Wiederholungsschritt und erscheint in keiner Runde.
- Ein Intervall verteilt sich auf zwei Runden (Auto-Lap nach Distanz, Rest nach Zeit).
  Soll/Ist muss aufeinanderfolgende Runden desselben Schritts zusammenfassen.
- Die Original-FIT enthält `workout_mesgs` und `workout_step_mesgs` (Name, Dauer, Zieltyp,
  Zielwerte, Notiz). Archiviert wurden sie bisher nicht.
- **HF-Ziele in der FIT sind mehrdeutig.** Laut FIT-Profil bedeuten Werte bis 100 „% HFmax“
  und Werte über 100 „bpm + 100“. Die FIT enthält 100/150, die Garmin-API für dasselbe
  Workout 100–150 bpm. HF-Ziele kommen deshalb aus der API.
- **Pace-Grenzen:** Die FIT speichert niedrig/hoch in m/s, die API je nach Erzeuger in
  unterschiedlicher Reihenfolge (Importer: schnellere Grenze zuerst; AP-0-Wegwerf-Workout:
  langsamere zuerst). Beim Lesen nach Wert sortieren.

**Fixtures (AP 0).**

- Max' Workouts nutzen **Schritt-Notizen** (Feld `description`, bis 39 Zeichen, z. B.
  „KADENZ - Tempo halten! Metronom 164 spm“). Das Kairos-Modell kennt sie nicht; ohne
  Erweiterung gingen sie beim Ändern verloren.
- Die Felder für **Sekundärziele** (`secondaryTargetType`, `secondaryTargetValueOne/Two`,
  `secondaryTargetValueUnit`, `secondaryZoneNumber`) sind in jedem Schritt vorhanden und
  derzeit leer.

**Sonstiges.** Die Commits der letzten Tage stammen von `haenel@igmr.rwth-aachen.de`; die
Adresse fehlt in der Liste der menschlichen Entwickler in `CLAUDE.md`. Falls sie Max gehört,
dort und in `docs/HANDOVER.md` ergänzen.

---

## 4. Bestand aus dem Browser-Coaching (Startwert für Stufe 3)

Quelle: Claude-Chat „Marathon-Vorbereitung für Sub-drei-Ziel“, Stand 12.10.2026.

| Thema | Stand |
|---|---|
| Ziele | Marathon April 2027, Ziel 3:05–3:15 (Entscheidung über Sub-3 nach dem Halbmarathon Ende Februar); Halbmarathon-Simulation 29.11.2026, realistisch 1:33–1:36 |
| Bezugswerte | 10-km-Test 20.09.2026: 45:11 (VDOT ≈ 45,5); HFmax 214 |
| Bereiche | je Pace und HF, z. B. Grundlage 5:25–5:50 bei 145–160, Long Run bis HF 160, Halbmarathontempo 4:38–4:42, Schwelle 4:35 bei 182–188, Intervall 4:10–4:15 |
| Periodisierung | Basis (Sep–Nov) → Kraftausdauer (Dez–Jan) → spezifische Phase (Feb bis Mitte März) → 3 Wochen Taper (Umfang −40 %, Intensität bleibt) |
| Regeln | Umfang höchstens +8–10 % pro Woche; jede 4. Woche Entlastung (−30 %); Long Run höchstens 30–35 % des Wochenumfangs; ≈ 80 % locker; zwei Qualitätseinheiten pro Woche |
| Wochenrhythmus | Dienstreisen Mo-Abend bis Do-Abend, Qualität meist Fr–So; Kraft 2× pro Woche (einbeinige Übungen, Plyometrie, Hüftabduktoren) |
| Phase I | 21.09.–29.11.2026, 42 → 58 km; Entlastung Woche 4 (12.–18.10.) und 8; 10-km-Kontrolltest Sa 31.10.; Taper ab 23.11. |
| Beobachtung | Entkopplung im Long Run (Ziel < 4 % über 20 km), Kadenz (Ziel 164–168, wegen der Innensehne am Knöchel vorerst 164), Bodenkontaktzeit, 10-km-Zeit |
| Ablauf | Besprechung sonntagabends nach dem Long Run anhand der FIT-Dateien; Workouts über den eigenen Importer |

Die Quellen für die Regeln ergänzt die Recherche zu Stufe 3.

---

## 5. Folgen je Dokument

| Dokument | Änderung | Wann |
|---|---|---|
| Spec 2026-10-07 | überarbeitet: Speicherformat, FIT-Archiv, TimescaleDB, Tagesgrenzen, HFmax, Soll/Ist, Sekundärziele, Schritt-Notizen, Teil E nach Stufe 3, Eval, Arbeitspakete | dieser Commit |
| `01`, `02`, `07`, ADR-0002, `README.md` | TimescaleDB entfernt, Speicherrechnung mit Arrays | AP 8 der Spec |
| `08-roadmap.md` | Stufenplan, offene Punkte | AP 8 der Spec |
| `CLAUDE.md`, `docs/HANDOVER.md` | Commit-Adresse ergänzen (falls Max' Adresse) | sofort, Max entscheidet |
| neue Spec Stufe 2 + ADR „Automatische Entlastung“ | D29–D34 | nach Stufe 1 |
| neue Spec Stufe 3 + Wissensbank `knowledge/training/` | D19–D28, Recherche Trainingsmethodik | Recherche parallel, Spec danach |

## 6. Offen

1. VM-Größe und Anbieter (D6).
2. Backups (D5), bewusst zurückgestellt.
3. Stufe 3: konkrete Sportarten und Ziele der anderen Nutzer, Auswahl der Methodiken nach der Recherche.
