# Validierung Stufe 1 — Ableitungen V1–V7 (2026-10-15)

Spec: `docs/superpowers/specs/2026-10-07-aktivitaeten-und-workouts-design.md` §12.3 (Kriterien), Teil B (Rechenregeln). Datenbasis: Entwicklungs-DB, Nutzer Max (139 Aktivitäten, 103 Läufe). Garmin-Vergleichswerte aus den archivierten `activity_list`-Payloads (`raw_payload.kind='activity_list'`, je `activityId` der zuletzt abgerufene Eintrag) und aus den `lap_mesgs` des FIT-Archivs. Branch `stufe1-datenbasis`.

Erzeugt mit `scripts/validate_activity_derivations.py --user-id <uuid> --out <datei>` (nur Lesezugriffe). Die Tabellen unten sind die Ausgabe des Skripts; die Erklärungen darunter sind von Hand.

## Laufzeit und Umfang (B.5)

| Kriterium | Ergebnis |
|---|---|
| gesamte Historie inkl. FIT-Dekodierung < 2 min | `derive_pending` 139/139 in 68,1 s (Erstlauf); nach dem Höhen-Fix (s. V4) erneut 139/139 in 67,2 s; nach Anhebung von `ACTIVITY_DERIVED_ALGO_VERSION` auf 2 über `derive_pending` ohne Auswahl 139/139 in 68,9 s, Prüfergebnisse unverändert; 0 Fehlschläge |
| Zeilen | `activity_stats` 139 (quality ok 132, partial 7), `activity_split` 2.404, `activity_best_effort` 391, `activity_step_result` 273 |

## Übersicht

| # | Prüfung | Kriterium | Ergebnis | erfüllt |
|---|---|---|---|---|
| V1 | Km-Splits gegen 1-km-Auto-Lap-Runden | ≤ 1 s in ≥ 95 % | 618/634 = 97,5 % (97 Läufe) | ja |
| V2 | Best Effort 5 km / 1 km gegen `fastestSplit_5000` / `_1000` | ≤ max(2 s, 1 %) in ≥ 90 % | 5 km 70/86 = 81,4 %; 1 km 90/95 = 94,7 %. Mit Garmins Gesamtzeit: 94,2 % / 97,9 %; zusätzlich ohne Sprungfilter: 100 % / 100 % | 5 km nein, 1 km ja |
| V3 | Historien-Bestwert gegen Garmin-PR | ≤ max(2 s, 1 %) | 5 km 1.325,4 s (Δ −0,03 s), 10 km 2.710,2 s (Δ −0,01 s); PR-Aktivität 262 im Archiv | ja |
| V4 | Σ Hm↑ gegen `elevationGain` | ±10 % in ≥ 90 % | 71/121 = 58,7 % (vor dem Fix 22/121 = 18,2 %) | nein — mit B.1 nicht erreichbar (H5) |
| V5 | Ø-Kadenz gegen `averageRunningCadenceInStepsPerMinute` | ±2 spm | 103/103, max 0,80 spm | ja |
| V6 | Ø-HF gegen `activity.avg_hr` | ±1 bpm | 139/139, davon 136 exakt | ja |
| V7 | Soll/Ist 272 + zwei Workout-Läufe (402, 250) | Ausführungen = Schritte × Wdh.; Dauer ±1 s | 272, 402, 250: alle gelaufenen Ausführungen ±0,74 s. Alle 43 Workout-Läufe: 40/43 | nach Wortlaut nicht erfüllt (9/10, 9/10, 7/8 — letzte Erholung nicht gelaufen); erfüllt bei geänderter Zählregel — Zählregel zur Bestätigung durch Max |

Laufband-Lauf 22 (Stream-Distanz 5,3 km, Garmin nach Bearbeitung 7,3 km; vorläufig, zur Bestätigung durch Max: keine Skalierung in Stufe 1): ohne Höhenkanal, ohne Auto-Lap und ohne `fastestSplit_*`, also nur in V5, V6 und V7. Dort prüfen wir Kadenz, HF und Dauer, die von der Distanz nicht abhängen; die Distanz und die Pace je Schritt (Stream-Maßstab) prüft V7 nicht.

## V1 Km-Splits gegen Uhr-Runden

| Läufe | Splits | Quote \|Δt\| ≤ 1 s | Kriterium | erfüllt | max \|Δt\| s | Median \|Δt\| s |
|---|---|---|---|---|---|---|
| 97 | 634 | 618/634 = 97.5 % | ≥ 95 % | ja | 2.793 | 0.001 |

Ausreißer (16):

| Aktivität | km | Split s | Runde s | Δ s | Timer-Stopps in der Runde | Pause laut Runde s | Stream-Distanz bei Rundenstart m | Stream-Distanz bei Rundenende m |
|---|---|---|---|---|---|---|---|---|
| 8 | 1 | 320.52 | 321.88 | -1.36 | 1 | 81.08 | 0.00 | 1001.53 |
| 16 | 1 | 327.79 | 329.33 | -1.55 | 1 | 13.19 | 2.11 | 1002.05 |
| 18 | 1 | 346.65 | 347.70 | -1.05 | 2 | 18.28 | 0.00 | 1000.87 |
| 24 | 1 | 318.92 | 319.93 | -1.01 | 0 | 0.00 | 1.80 | 1002.85 |
| 32 | 1 | 325.57 | 326.66 | -1.09 | 0 | 0.00 | 0.00 | 1003.30 |
| 84 | 1 | 337.85 | 338.94 | -1.09 | 0 | 0.00 | 0.00 | 1003.30 |
| 86 | 1 | 393.68 | 395.10 | -1.42 | 0 | 0.00 | 1.33 | 1003.26 |
| 124 | 1 | 363.62 | 365.15 | -1.53 | 1 | 37.47 | 1.43 | 1002.95 |
| 144 | 1 | 387.94 | 389.03 | -1.09 | 0 | 0.00 | 1.34 | 1002.50 |
| 150 | 1 | 337.67 | 339.02 | -1.35 | 1 | 79.73 | 1.46 | 1002.94 |
| 154 | 1 | 364.04 | 365.08 | -1.04 | 2 | 14.37 | 0.89 | 1001.28 |
| 156 | 1 | 343.59 | 344.78 | -1.19 | 2 | 14.95 | 0.00 | 1000.44 |
| 160 | 1 | 322.66 | 324.41 | -1.76 | 2 | 54.32 | 0.00 | 1003.26 |
| 210 | 1 | 340.27 | 341.36 | -1.09 | 1 | 39.95 | 1.09 | 1003.28 |
| 258 | 1 | 330.09 | 332.88 | -2.79 | 2 | 21.31 | 3.00 | 1003.26 |
| 266 | 1 | 328.16 | 329.35 | -1.19 | 1 | 90.75 | 1.18 | 1003.03 |

**Erklärung der 16 Ausreißer.** Alle betreffen km 1, und alle sind 1,0–2,8 s *kürzer* als die Runde der Uhr. Ursache in den Daten, nicht in der Rechnung:

1. Die Uhr schließt die erste 1.000-m-Runde erst bei 1.000,4–1.003,3 m der aufgezeichneten Distanz (letzte Spalte); ihr Runden-Kilometerzähler liegt beim Start um 0,4–3,3 m hinter der `record`-Distanz. Kairos teilt nach B.3 an der exakten 1.000-m-Marke von `distance_m`. Beim Tempo des ersten Kilometers sind das 0,2–1,3 s. Ab km 2 sind beide Zählungen um denselben Betrag verschoben, deshalb stimmen die weiteren Kilometer auf Millisekunden (Median |Δt| 0,001 s).
2. In 11 der 16 Runden liegt zusätzlich ein Timer-Stopp. Die Timer-Ereignisse der FIT haben nur Sekundenauflösung, die Rundenzeiten Millisekunden. In 6 geprüften Runden mit Stopp ist die Pause aus den Ereignissen 0,5–1,7 s länger als `total_elapsed_time − total_timer_time` der Runde (258: 23,0 s gegen 21,3 s bei zwei Stopps).

Beides zusammen erklärt alle 16. Eine Korrektur müsste die Pausen aus den Runden statt aus den Ereignissen nehmen; B.1 legt die Ereignisse fest, und V1 ist auch so erfüllt.

## V2 Best Effort 5 km / 1 km gegen fastestSplit

| Distanz | Läufe | Quote strikt | + Gesamtzeit wie Garmin | + ohne Sprungfilter | Kriterium | erfüllt (strikt) |
|---|---|---|---|---|---|---|
| 5k | 86 | 70/86 = 81.4 % | 81/86 = 94.2 % | 86/86 = 100.0 % | ≥ 90 % | nein |
| 1k | 95 | 90/95 = 94.7 % | 93/95 = 97.9 % | 95/95 = 100.0 % | ≥ 90 % | ja |

Ausreißer (21), Toleranz max(2 s, 1 %); „–“ bei Kairos = kein Fenster ohne Schritt > 8,5 m/s:

| Aktivität | Distanz | Kairos s (Timer) | Garmin s | Δ s | Kairos s (Gesamtzeit) | Kairos s (Gesamtzeit, ohne Sprungfilter) | Ursache |
|---|---|---|---|---|---|---|---|
| 3 | 5k | 1569.8 | 1587.9 | -18.1 | 1587.9 | 1587.9 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 12 | 5k | 1559.0 | 1577.0 | -18.0 | 1577.0 | 1577.0 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 30 | 5k | 1448.7 | 1467.7 | -19.0 | 1467.7 | 1467.7 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 70 | 5k | – | 1818.9 | – | – | 1818.9 | Sprungfilter verwirft die schnellen Fenster (3 Schritte > 8,5 m/s) |
| 94 | 5k | – | 1408.5 | – | – | 1408.5 | Sprungfilter verwirft die schnellen Fenster (25 Schritte > 8,5 m/s) |
| 100 | 5k | – | 1454.9 | – | – | 1454.9 | Sprungfilter verwirft die schnellen Fenster (17 Schritte > 8,5 m/s) |
| 136 | 5k | – | 2009.2 | – | – | 2009.2 | Sprungfilter verwirft die schnellen Fenster (3 Schritte > 8,5 m/s) |
| 164 | 5k | 1457.2 | 1615.2 | -158.0 | 1615.2 | 1615.2 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 168 | 5k | – | 1991.0 | – | – | 1991.0 | Sprungfilter verwirft die schnellen Fenster (4 Schritte > 8,5 m/s) |
| 254 | 5k | 1589.3 | 1619.7 | -30.4 | 1619.7 | 1619.7 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 258 | 5k | 1636.6 | 1654.6 | -18.0 | 1654.6 | 1654.6 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 266 | 5k | 1626.2 | 1649.3 | -23.1 | 1649.3 | 1649.3 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 270 | 5k | 1735.5 | 1772.7 | -37.2 | 1772.5 | 1772.5 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 272 | 5k | 1479.8 | 1500.2 | -20.4 | 1500.2 | 1500.2 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 398 | 5k | 1663.3 | 1749.3 | -86.0 | 1749.3 | 1749.3 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 400 | 5k | 1523.9 | 1565.9 | -42.0 | 1565.9 | 1565.9 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 3 | 1k | 306.3 | 310.1 | -3.8 | 310.1 | 310.1 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 94 | 1k | 304.9 | 264.0 | 40.9 | 304.9 | 264.0 | Sprungfilter verwirft die schnellen Fenster (25 Schritte > 8,5 m/s) |
| 100 | 1k | 342.7 | 268.8 | 73.9 | 351.7 | 268.7 | Sprungfilter verwirft die schnellen Fenster (17 Schritte > 8,5 m/s) |
| 170 | 1k | 352.0 | 357.0 | -5.0 | 357.0 | 357.0 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |
| 174 | 1k | 401.2 | 409.6 | -8.4 | 409.2 | 409.2 | Timer-Stopp im Fenster; Garmin misst Gesamtzeit |

Nicht verglichen (3):

| Aktivität | Distanz | Garmin s | Grund |
|---|---|---|---|
| 154 | 5k | 1609.7 | distance_source=mixed (B.4: nur gps) |
| 154 | 1k | 308.6 | distance_source=mixed (B.4: nur gps) |
| 160 | 1k | 310.0 | distance_source=mixed (B.4: nur gps) |

**Erklärung.** Strikt erfüllt 1 km, 5 km nicht. Alle 21 Ausreißer haben eine von zwei Ursachen:

- **Timer-Zeit statt Gesamtzeit (14 Ausreißer).** B.4 legt für Best Efforts die Timer-Zeit fest; Garmins `fastestSplit_*` misst die Gesamtzeit inklusive Pausen. Liegt im schnellsten Fenster ein Timer-Stopp (Ampel, Intervallpause mit Stopp), ist Kairos um die Pausenlänge schneller (272: 1.479,8 s gegen 1.500,2 s; 164: −158 s). Rechnet man mit derselben Funktion über die Gesamtzeit, stimmen alle 14 innerhalb der Toleranz (Spalte „Gesamtzeit“, 12 davon auf 0,1 s genau). Die Timer-Zeit bleibt laut Entscheidung; der Nachteil ist, dass Bestwerte aus Läufen mit Stopps schneller aussehen als bei Garmin.
- **Sprungfilter (7 Ausreißer: 5 × 5 km ohne Wert, 2 × 1 km zu langsam).** B.4 verwirft jedes Fenster, das einen 1-s-Schritt über 8,5 m/s enthält. In 12 von 103 Läufen gibt es solche Schritte. Bei den Intervall-Läufen 94 und 100 (25 bzw. 17 Schritte, 3-s-Tempo höchstens 6,7 m/s) ist das GPS-Zittern um einzelne Sekunden. Bei den Sprint-Workouts 70, 136 und 168 (3–4 Schritte, 3-s-Tempo 8,5–8,6 m/s) sind es echte Sprints. Weil jedes 5-km-Fenster einen solchen Schritt enthält, gibt es dort keinen 5-km-Wert, und der 1-km-Wert von 94/100 weicht auf ein langsameres Fenster aus (304,9 s statt 264,0 s). Ohne Filter stimmen alle 7 mit Garmin überein. Der einzige echte GPS-Sprung der Historie (398: 87,8 m/s, zwei Schritte > 12 m/s) liegt nicht im besten Fenster. Die Rechnung folgt B.4; der Fehler steckt in der Regel. Optionen zur Entscheidung: Schwelle 12 m/s (verwirft nur 398) oder den Sprung über ein 3-s-Tempo erkennen (behält 94/100, die Sprints 70/136/168 lägen weiter an der Grenze).

Nicht verglichen: 154 und 160 haben `distance_source='mixed'`; B.4 rechnet nur bei `gps`. Ohne Best Effort sind außerdem der Laufband-Lauf 22 (Garmin liefert dort kein `fastestSplit`) und Läufe unter 5 km bzw. 1 km.

## V3 Bestwert der Historie gegen Garmin-PR

| Distanz | Garmin-PR s | PR-Aktivität im Archiv | Kairos-Bestwert s | Kairos-Aktivität | Δ s | erfüllt (≤ max(2 s, 1 %)) |
|---|---|---|---|---|---|---|
| 5k | 1325.4 | ja: activityId 24430918779 = Aktivität 262 | 1325.4 | 262 | -0.03 | ja |
| 10k | 2710.2 | ja: activityId 24430918779 = Aktivität 262 | 2710.2 | 262 | -0.01 | ja |

**Erklärung.** Die PR-Aktivität für beide Distanzen ist 262 (activityId 24430918779). Sie liegt im Archiv, und ihr `fastestSplit_5000`/`_10000` ist der kleinste Wert der ganzen Historie. Der Kairos-Bestwert kommt aus derselben Aktivität und liegt 0,03 bzw. 0,01 s neben dem PR. Es gibt keinen Timer-Stopp im Fenster, deshalb macht die Wahl zwischen Timer- und Gesamtzeit hier keinen Unterschied.

## V4 Σ Hm↑ gegen elevationGain

Population: 121 Aktivitäten mit Höhenkanal und elevationGain. Garmins elevationGain = FIT `session.total_ascent` bei 121/121 = 100.0 %. Toleranz ±10 % (bei elevationGain 0: ±0,5 m).

| Variante | Quote ±10 % | Quote max(±10 %, ±2 m) | Median Kairos/Garmin % | erfüllt (≥ 90 %) |
|---|---|---|---|---|
| B.1 gespeichert: Median 5, Hysterese 2 m (Extremwerte, ab 2026-10-15) | 71/121 = 58.7 % | 79/121 = 65.3 % | 102.1 | nein |
| B.1 bis 2026-10-15: Median 5, 2-m-Stufen | 22/121 = 18.2 % | 30/121 = 24.8 % | 69.4 | nein |
| Median 5, Hysterese 1 m | 15/121 = 12.4 % | 21/121 = 17.4 % | 144.0 | nein |
| Median 5, Hysterese 3 m | 41/121 = 33.9 % | 44/121 = 36.4 % | 81.2 | nein |
| Median 3, Hysterese 2 m | 65/121 = 53.7 % | 71/121 = 58.7 % | 105.2 | nein |
| ohne Median, Hysterese 2 m | 57/121 = 47.1 % | 61/121 = 50.4 % | 107.8 | nein |
| ohne Median, Hysterese 3 m | 45/121 = 37.2 % | 49/121 = 40.5 % | 85.0 | nein |

| Profil | Quote ±10 % (gespeichert) |
|---|---|
| cycling | 3/7 = 42.9 % |
| generic | 0/1 = 0.0 % |
| hiking | 11/11 = 100.0 % |
| running | 57/102 = 55.9 % |

Ausreißer gespeichert (50; davon 25 mit elevationGain < 20 m):

| Aktivität | Sportart | Garmin m | Kairos m | Δ m | Δ % |
|---|---|---|---|---|---|
| 3 | running | 51.0 | 42.0 | -9.0 | -18 |
| 8 | running | 32.0 | 38.8 | 6.8 | 21 |
| 12 | running | 63.0 | 70.8 | 7.8 | 12 |
| 14 | running | 59.0 | 43.2 | -15.8 | -27 |
| 18 | running | 20.0 | 23.0 | 3.0 | 15 |
| 20 | running | 20.0 | 17.2 | -2.8 | -14 |
| 26 | running | 56.0 | 66.0 | 10.0 | 18 |
| 28 | cycling | 135.0 | 101.4 | -33.6 | -25 |
| 30 | running | 24.0 | 26.8 | 2.8 | 12 |
| 32 | running | 42.0 | 52.6 | 10.6 | 25 |
| 40 | running | 34.0 | 37.8 | 3.8 | 11 |
| 58 | running | 35.0 | 39.3 | 4.3 | 12 |
| 64 | running | 27.0 | 33.8 | 6.8 | 25 |
| 66 | running | 30.0 | 22.4 | -7.6 | -25 |
| 74 | running | 17.0 | 13.6 | -3.4 | -20 |
| 76 | running | 11.0 | 8.8 | -2.2 | -20 |
| 78 | running | 21.0 | 17.8 | -3.2 | -15 |
| 86 | running | 7.0 | 6.0 | -1.0 | -14 |
| 88 | running | 3.0 | 4.8 | 1.8 | 60 |
| 98 | running | 24.0 | 26.6 | 2.6 | 11 |
| 108 | running | 1.0 | 6.8 | 5.8 | 580 |
| 109 | running | 2.0 | 5.6 | 3.6 | 180 |
| 110 | running | 19.0 | 16.6 | -2.4 | -13 |
| 124 | running | 16.0 | 18.6 | 2.6 | 16 |
| 134 | running | 21.0 | 24.4 | 3.4 | 16 |
| 138 | running | 16.0 | 21.8 | 5.8 | 36 |
| 146 | running | 17.0 | 12.2 | -4.8 | -28 |
| 148 | resort_skiing | 1212.0 | 2041.8 | 829.8 | 68 |
| 150 | running | 16.0 | 20.6 | 4.6 | 29 |
| 156 | running | 9.0 | 6.6 | -2.4 | -27 |
| 164 | running | 19.0 | 24.0 | 5.0 | 26 |
| 170 | running | 8.0 | 6.4 | -1.6 | -20 |
| 172 | running | 14.0 | 12.2 | -1.8 | -13 |
| 174 | running | 7.0 | 8.8 | 1.8 | 26 |
| 194 | running | 14.0 | 12.4 | -1.6 | -11 |
| 198 | running | 10.0 | 5.4 | -4.6 | -46 |
| 200 | running | 15.0 | 13.2 | -1.8 | -12 |
| 204 | running | 29.0 | 25.4 | -3.6 | -12 |
| 210 | running | 15.0 | 11.6 | -3.4 | -23 |
| 214 | running | 29.0 | 25.2 | -3.8 | -13 |
| 216 | running | 18.0 | 11.6 | -6.4 | -36 |
| 234 | cycling | 11.0 | 19.4 | 8.4 | 76 |
| 235 | running | 10.0 | 11.6 | 1.6 | 16 |
| 236 | cycling | 17.0 | 7.0 | -10.0 | -59 |
| 246 | cycling | 116.0 | 98.2 | -17.8 | -15 |
| 248 | running | 43.0 | 35.8 | -7.2 | -17 |
| 254 | running | 49.0 | 42.6 | -6.4 | -13 |
| 266 | running | 19.0 | 16.8 | -2.2 | -12 |
| 399 | running | 27.0 | 31.4 | 4.4 | 16 |
| 402 | running | 43.0 | 37.2 | -5.8 | -13 |

**Fix (Rechenfehler gegen B.1).** Die Umsetzung aus Task 17 hat die 2-m-Hysterese als Stufenzähler gerechnet: Der Bezugswert sprang bei jeder 2-m-Stufe mit, und der Rest unter 2 m am Ende jedes Anstiegs fiel weg. Das ergab im Median 69 % von Garmins Wert, also systematisch zu wenig. Eine Hysterese soll aber nur Richtungswechsel unter 2 m unterdrücken. Neu: Hoch- und Tiefpunkte zählen voll, sobald die Gegenbewegung 2 m übersteigt (`elevation_gain_loss` in `src/kairos/activities/derive/common.py`, Commit `fix(derive): elevation hysteresis counts full climbs`, mit Regressionstests). Die Fixtures 252/272 ergeben jetzt 42,2/34,0 m gegen Garmins 40/35 m, vorher 28,2/24,0 m. Die abgeleiteten Tabellen sind danach neu berechnet.

**Warum V4 trotzdem verfehlt wird (H5, nur Bericht).** Garmins `elevationGain` ist in 121/121 Fällen gleich dem `session.total_ascent` der Uhr. Die Uhr rechnet das auf dem Gerät aus dem barometrischen Rohsignal, mit einem Filter, den wir nicht kennen; uns liegt nur die auf 0,2 m gerundete `enhanced_altitude` je Sekunde vor (sie ist in allen Dateien gleich `altitude`, also keine andere Quelle). Keine einfache Variante kommt auf 90 %. Die beste ist die neue B.1-Regel mit 58,7 % und einem Median von 102 % — sie liegt also im Mittel richtig, streut aber pro Aktivität. Bei Läufen in Max' flachem Umfeld (Median der Hm↑ ≈ 25 m) sind ±10 % nur ±2–3 m. Das liegt im Bereich der Messauflösung: 25 der 50 Ausreißer haben weniger als 20 m. Wandern trifft 11/11, Rad 3/7.

Optionen zur Entscheidung (Zahlen oben):
1. `activity_stats.elev_gain_m` aus `session.total_ascent` nehmen (= Garmin, V4 dann per Definition erfüllt) und die eigene Rechnung nur für Splits und Kurven verwenden. Dann ist die Summe der Split-Hm nicht mehr gleich der Gesamtsumme.
2. Das Kriterium ändern, z. B. „±10 % oder ±2 m“ (65,3 % mit der neuen Regel), das reicht aber auch nicht für 90 %.
3. Die B.1-Regel lassen und V4 als nicht erreichbar festhalten.

Weitere Ausreißer: 148 (Ski alpin, 2.042 gegen 1.212 m) — Garmin wertet hier offenbar nicht alle Anstiege; die Ursache ist nicht geprüft, das Profil ist `generic`. 108/109 (Garmin 1–2 m, Kairos 5,6–6,8 m) liegen im Rauschen eines nahezu flachen Laufs.

## V5 Ø-Kadenz gegen averageRunningCadenceInStepsPerMinute

| Läufe | Quote \|Δ\| ≤ 2 spm | Kriterium | erfüllt | max \|Δ\| spm |
|---|---|---|---|---|
| 103 | 103/103 = 100.0 % | ±2 spm je Lauf | ja | 0.80 |

Ausreißer (0)

## V6 Ø-HF gegen activity.avg_hr

| Aktivitäten mit HF | Quote \|Δ\| ≤ 1 bpm | davon exakt | Kriterium | erfüllt |
|---|---|---|---|---|
| 139 | 139/139 = 100.0 % | 136 | ±1 bpm je Aktivität | ja |

Ausreißer (0)

**Erklärung.** Keine Ausreißer. Die Kadenz folgt B.1: 2 × (cadence + fractional_cadence), zeitgewichtet einschließlich der Null-Kadenz-Samples, wie bei Garmin. Die HF ist zeitgewichtet ohne Pausen; die 3 nicht exakten Werte liegen 1 bpm daneben.

## V7 Soll/Ist pro Workout-Schritt

Kernstichprobe 272, 402, 250: erfüllt. Alle Workout-Läufe: 40/43 = 93.0 %. Runden < 5 s und die Schlussrunde ohne Schrittindex zählen nicht (B.6).

| Aktivität | geplant (Schritte × Wdh.) | gelaufen (Runden) | Kairos-Zeilen | übersprungen (Ausführung, Typ) | = Schritte × Wdh. (strikt) | max \|Δ Dauer\| s | erfüllt (gelaufene, ±1 s) |
|---|---|---|---|---|---|---|---|
| 1 | 14 | 14 | 14 | – | ja | 0.79 | ja |
| 3 | 1 | 1 | 1 | – | ja | 0.36 | ja |
| 8 | 1 | 1 | 1 | – | ja | 0.92 | ja |
| 10 | 10 | 10 | 10 | – | ja | 0.00 | ja |
| 12 | 14 | 13 | 13 | #13 recovery | nein | 0.09 | ja |
| 14 | 1 | 1 | 1 | – | ja | 0.43 | ja |
| 16 | 14 | 14 | 14 | – | ja | 0.81 | ja |
| 18 | 12 | 12 | 12 | – | ja | 0.72 | ja |
| 22 | 12 | 11 | 11 | #11 recovery | nein | 0.00 | ja |
| 24 | 14 | 11 | 11 | #11 recovery, #12 active, #13 recovery | nein | 0.34 | ja |
| 26 | 3 | 3 | 3 | – | ja | 0.36 | ja |
| 42 | 3 | 3 | 3 | – | ja | 0.94 | ja |
| 46 | 1 | 1 | 1 | – | ja | 0.00 | ja |
| 60 | 1 | 1 | 1 | – | ja | 0.28 | ja |
| 66 | 1 | 1 | 1 | – | ja | 0.20 | ja |
| 70 | 16 | 15 | 15 | #15 rest | nein | 0.54 | ja |
| 74 | 1 | 1 | 1 | – | ja | 0.23 | ja |
| 78 | 3 | 3 | 3 | – | ja | 0.03 | ja |
| 84 | 1 | 1 | 1 | – | ja | 0.00 | ja |
| 94 | 12 | 11 | 11 | #11 recovery | nein | 0.35 | ja |
| 100 | 18 | 17 | 17 | #17 recovery | nein | 1.06 | nein |
| 116 | 1 | 1 | 1 | – | ja | 0.00 | ja |
| 130 | 3 | 3 | 3 | – | ja | 0.92 | ja |
| 134 | 3 | 3 | 3 | – | ja | 0.30 | ja |
| 136 | 12 | 11 | 11 | #11 rest | nein | 0.34 | ja |
| 156 | 1 | 1 | 1 | – | ja | 2.35 | nein |
| 158 | 1 | 1 | 1 | – | ja | 0.63 | ja |
| 160 | 1 | 1 | 1 | – | ja | 2.89 | nein |
| 164 | 18 | 17 | 17 | #17 recovery | nein | 0.90 | ja |
| 168 | 16 | 13 | 13 | #7 rest, #14 rest, #15 recovery | nein | 0.69 | ja |
| 198 | 1 | 1 | 1 | – | ja | 0.00 | ja |
| 200 | 3 | 3 | 3 | – | ja | 0.15 | ja |
| 204 | 1 | 1 | 1 | – | ja | 0.24 | ja |
| 206 | 18 | 17 | 17 | #17 recovery | nein | 0.03 | ja |
| 210 | 3 | 3 | 3 | – | ja | 0.05 | ja |
| 216 | 1 | 1 | 1 | – | ja | 0.55 | ja |
| **250** | 10 | 9 | 9 | #9 recovery | nein | 0.02 | ja |
| 256 | 10 | 9 | 9 | #9 recovery | nein | 0.55 | ja |
| 266 | 14 | 13 | 13 | #13 recovery | nein | 0.25 | ja |
| 268 | 1 | 1 | 1 | – | ja | 0.00 | ja |
| 270 | 1 | 1 | 1 | – | ja | 0.27 | ja |
| **272** | 10 | 9 | 9 | #9 recovery | nein | 0.74 | ja |
| **402** | 8 | 7 | 7 | #7 recovery | nein | 0.00 | ja |

Ausführungen mit Abweichung > 1 s:

| Aktivität | Ausführung | Kairos s | Σ Runden s | Runden | Pause in den Runden s |
|---|---|---|---|---|---|
| 100 | 17 | 374.50 | 375.56 | 2 | 21.86 |
| 156 | 1 | 1797.65 | 1800.00 | 6 | 21.11 |
| 160 | 1 | 1546.09 | 1548.98 | 5 | 89.09 |

**Zählregel (vorläufig, zur Bestätigung durch Max).** Nach Wortlaut von §12.3 ist V7 nicht erfüllt: 272 9/10, 250 9/10, 402 7/8. Vorgeschlagen ist: „Ausführungen = Schritte × Wiederholungen“ zählt die tatsächlich gelaufenen Ausführungen; damit ist V7 erfüllt. Ein geplanter Schritt, der nie gelaufen wurde, ist keine Ausführung. In 272, 402 und 250 fehlt jeweils die letzte Trabpause vor dem Auslaufen: Auf das letzte Intervall folgt direkt die Auslauf-Runde. Dasselbe Muster (nur die letzte Pause fehlt) haben 10 weitere Workouts; 24 hat den Wiederholungsblock nach 5 von 6 Durchgängen beendet, 168 hat zusätzlich eine Pause in der Mitte übersprungen. Gemessen wird gegen die `lap_mesgs` der FIT (aus denen Garmin Connect die Runden zeigt). Die Reihenfolge der gelaufenen Schritte ist in allen 43 Workouts ein geordneter Teil des Plans, und die Kairos-Zeilen haben dieselben Schrittindizes wie die Rundengruppen.

**Erklärung der 3 Dauer-Ausreißer außerhalb der Kernstichprobe.** In 100 (Auslaufen), 156 und 160 (Ein-Schritt-Workouts „Basis“ über den ganzen Lauf) liegen Timer-Stopps in der Ausführung (21,9 s / 21,1 s / 89,1 s Pause). Kairos ist 1,1–2,9 s kürzer — dieselbe Ursache wie in V1: Die Ereignisse sind nur sekundengenau, und es kommt der Distanzversatz der ersten Runde hinzu. Bei 156 und 160 steckt darin auch die V1-Abweichung von km 1 (1,19 bzw. 1,76 s).

Workouts mit nur einem Schritt in einer Wiederholung (aufeinanderfolgende gleiche Indizes) kommen in den Daten nicht vor. Atem-Workouts (54, 140, `breathwork`) sind keine Läufe und hier nicht enthalten.
