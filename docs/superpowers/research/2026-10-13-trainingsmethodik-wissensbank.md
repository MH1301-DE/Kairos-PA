# Recherche: Trainingsmethodik für die Wissensbank (Stufe 3)

| | |
|---|---|
| **Datum** | 2026-10-13 |
| **Status** | Recherche abgeschlossen (erste Runde); Grundlage für die Spec „Coach-Modus“ |
| **Baut auf** | [Entscheidungsprotokoll](../specs/2026-10-13-brainstorming-entscheidungen.md) D19–D28, insbesondere D23 (Zielgruppe), D24 (Wissensbank im Repo), D25/D26 (Plantyp und Bezugswerte), D27 (Max' Regeln als erster Plantyp) |
| **Folgedokument** | Spec Stufe 3 „Coach-Modus“ (offen) |

---

## 0. Ergebnis in Kürze

1. **Intensitätsverteilung:** Belastbar ist nur der gemeinsame Kern: **≥ 70–80 % der
   Trainingszeit locker** (unter der ersten Schwelle), der Rest verteilt auf Schwelle und
   hohe Intensität. Ob polarisiert oder pyramidal besser ist, ist für Leistung im
   Wettkampf nicht entschieden (Metaanalyse 2024: Vorteil nur bei VO₂peak, nicht bei
   Zeitfahren). → Die Verteilung wird ein **Parameter des Plantyps**, kein Dogma.
2. **Progression:** Die bekannte „10 %-Regel pro Woche“ ist schwächer belegt als eine neue,
   direkt umsetzbare Regel: **Ein einzelner Lauf, der mehr als 10 % länger ist als der
   längste Lauf der letzten 30 Tage, erhöht das Verletzungsrisiko** (5.205 Läufer,
   Garmin-Daten, BJSM 2025). Kairos hat alle Daten, um diese Leitplanke zu prüfen.
3. **ACWR** (zeigt Kairos im Dashboard) ist als Verletzungsprädiktor umstritten; in der
   BJSM-Kohorte zeigte er keinen positiven Zusammenhang. Als Orientierung ja, als Regel nein.
4. **Taper:** 8–14 Tage, Umfang −41 bis −60 %, Intensität und Häufigkeit halten.
5. **Kraft:** 2–3 Einheiten pro Woche mit **schweren Lasten (≥ 80 % 1RM)** und
   Plyometrie verbessern die Laufökonomie; leichte Lasten und Isometrie nicht. Kraft und
   Ausdauer mit ≥ 3 h Abstand legen.
6. **HFmax-Rückfallwert:** `208 − 0,7 × Alter` (Tanaka) ist genauer als `220 − Alter`.
   Das betrifft A.6 der Stufe-1-Spec und ist eine Entscheidung für Max (§8).
7. **Wissensbank:** Ein Eintrag = eine Regel mit **maschinenlesbarem Regelteil**
   (YAML, festes Vokabular) und **Erklärteil** (Markdown, in eigenen Worten, mit Quellen).
   Plantypen setzen sich aus Einträgen zusammen. Vorschlag für Format, Katalog und die
   ersten vier Plantypen in §7.
8. **Max' Regeln** aus dem Browser-Coaching sind fast durchweg durch die Literatur
   gedeckt. Zwei Zahlen passen nicht zusammen (§6.2).

---

## 1. Fragestellung und Vorgehen

**Fragen** (aus D23/D24): Welche Trainingsmethoden sind für Laufen, Rad und Triathlon als
Hauptsport und Kraft, Schwimmen und Yoga als Ergänzung belegt, auch für Ziele ohne
Wettkampf? Welche Regeln daraus kann ein Plan-Generator ausführen? Welche Bezugswerte
braucht jeder Plantyp?

**Vorgehen:** Übersichtsarbeiten und Metaanalysen zuerst, dann einzelne RCTs, dann
etablierte Trainingsbücher für die Praxis. Jede Aussage im Regelteil der Wissensbank
bekommt eine **Evidenzstufe**:

| Stufe | Bedeutung |
|---|---|
| hoch | Metaanalyse oder große Kohorte mit konsistentem Ergebnis |
| mittel | einzelne RCTs oder Metaanalyse mit niedriger Studienqualität |
| niedrig | kleine oder widersprüchliche Studien |
| praxis | etablierte Trainerpraxis ohne direkte Studienlage |

**Einschränkungen dieser Runde:** PubMed/PMC blockierten automatische Abrufe (Captcha),
Europe PMC drosselte nach wenigen Anfragen. Die Angaben stammen deshalb aus Abstracts
und Volltexten bei Verlagen, Repositorien und Literaturdatenbanken (BISp/IAT). Nicht im
Original geprüft und deshalb **nicht verwendet**: Rosenblat et al. 2019 (Metaanalyse
polarisiert vs. Schwelle), Casado et al. 2022 in *Sports Medicine* (Weltklasse-Läufer).
Die Inhalte der Trainingsbücher (§3) sind zusammengefasst, nicht wörtlich geprüft.

---

## 2. Intensität

### 2.1 Drei-Zonen-Modell als gemeinsame Sprache

Die Forschung zur Intensitätsverteilung nutzt fast durchweg drei Zonen, abgegrenzt durch
die erste und zweite Schwelle (ventilatorisch oder Laktat):

| Zone | Abgrenzung | Typische Einheiten |
|---|---|---|
| Z1 | unter der 1. Schwelle (≈ 2 mmol/l Laktat) | lockere Läufe, Long Run, Grundlage |
| Z2 | zwischen den Schwellen | Tempodauerlauf, Schwellenintervalle, Marathontempo |
| Z3 | über der 2. Schwelle | VO₂max-Intervalle, Wiederholungen |

Die sportartspezifischen Zonen (5 HF-Zonen, 7 Leistungszonen, Daniels-Tempi) lassen sich
auf diese drei abbilden. **Vorschlag:** Kairos rechnet Verteilungen immer im
Drei-Zonen-Modell und zeigt die feineren Zonen nur in Workouts.

### 2.2 Verteilung: Was ist belegt?

| Quelle | Wer | Ergebnis |
|---|---|---|
| Seiler 2010, Übersicht | national/international konkurrenzfähige Ausdauerathleten | ≈ 80 % der Einheiten locker, ≈ 20 % hart; mehr Intervalle bei bereits gut Trainierten zeigen langfristig keinen überzeugenden Zusatznutzen |
| Stöggl & Sperlich 2014, RCT, 9 Wochen | 48 gut trainierte Ausdauerathleten | Polarisiert (68/6/26 %) verbesserte VO₂peak um 11,7 %, Schwelle (46/54/0) und hoher Umfang (83/16/1) nicht weiter |
| Muñoz et al. 2014, RCT, 10 Wochen | 30 Freizeitläufer | 10 km: polarisiert (77/3/20) −5,0 %, zwischen den Schwellen (46/35/19) −3,6 %; Gruppenunterschied **nicht signifikant** |
| Festa et al. 2020, RCT, 8 Wochen | 38 Freizeitläufer | polarisiert (77/3/20) und schwellenbetont (40/50/10) ähnlich wirksam; schwellenbetont brauchte **17 % weniger Zeit** |
| Casado et al. 2022 (IJSM), systematische Übersicht | Mittel- und Langstreckenläufer, 20 Studien | pyramidal und polarisiert besser als schwellenbetont; Empfehlung **≥ 70 % locker, ≤ 30 % Schwelle + Intervalle** |
| Silva Oliveira et al. 2024, Metaanalyse | 17 Studien, 437 Teilnehmer | polarisiert besser für VO₂peak (SMD 0,24), vor allem < 12 Wochen und bei hoch Trainierten; **kein Unterschied** bei Zeitfahren (SMD −0,01), Zeit bis Erschöpfung und Schwellenleistung |
| Norwegische Doppelschwelle (Übersicht 2023, 13 Elite-Läufer) | Elite, 120–180 km/Woche | 75–80 % locker, 2–4 Schwelleneinheiten pro Woche, teils zwei am Tag, laktatgesteuert |

**Folgerungen für Regeln**

- **Fest:** Anteil Z1 ≥ 70 % der Zeit pro Woche, Ziel 75–80 % (Evidenz hoch).
- **Plantyp-Parameter:** polarisiert (Z2 klein) oder pyramidal (Z2 > Z3). Für Freizeitsportler
  mit wenig Zeit ist eine schwellenbetonte Woche nicht schlechter (Festa 2020); für
  Wettkampfziele mit genug Zeit liegt pyramidal/polarisiert vorn (Casado 2022).
- **Nicht übernehmen:** die norwegische Doppelschwelle. Sie setzt hohe Umfänge und
  Laktatmessung voraus; für 40–60 km/Woche gibt es keine Belege.

### 2.3 Bezugswerte und Tests je Sportart (D26)

| Sportart | Bezugswert | Ermittlung | Zonen daraus |
|---|---|---|---|
| Laufen | **VDOT** | Wettkampf oder Test über 3–15 km; Formel nach Daniels & Gilbert (1979): Sauerstoffkosten `VO₂ = −4,60 + 0,182258·v + 0,000104·v²` (v in m/min), Anteil an VO₂max `0,8 + 0,1894393·e^(−0,012778·t) + 0,2989558·e^(−0,1932605·t)` (t in min), VDOT = Quotient | Tempi E, M, T, I, R (Daniels) |
| Laufen | **Critical Speed** | mehrere Bestzeiten (z. B. 3 und 12 min) oder 3-min-All-out-Test (Pettitt 2016) | Grenze zwischen schwerem und sehr schwerem Bereich; Intervalle über CS |
| Laufen/Rad | **LTHR** | 30-min-Zeitfahren allein, Ø-HF der letzten 20 min (Friel) | 5 HF-Zonen in % LTHR, getrennt für Laufen und Rad |
| Rad | **FTP** | 20-min-Test × 0,95 (Allen & Coggan 2006) | 7 Leistungszonen: < 55, 56–75, 76–90, 91–105, 106–120, 121–150, > 150 % FTP |
| Schwimmen | **CSS** | 400 m und 200 m (bzw. 50 m) maximal: `CSS = (400 − 200) / (T400 − T200)` (Wakayoshi 1992) | Tempo pro 100 m relativ zur CSS |
| Kraft | **1RM bzw. RIR** | geschätzt aus Wiederholungen bis kurz vor Muskelversagen | Last in % 1RM oder „2 Wiederholungen in Reserve“ |
| alle | **HFmax** | Messung (Feld- oder Labortest), sonst Formel (§2.4) | nur als Rückfall für HF-Zonen |

Die HF-Zonen in % LTHR (Friel) unterscheiden sich zwischen Laufen und Rad (Z1 Laufen
< 85 %, Rad < 81 % LTHR). Ein Plantyp, der HF-Zonen nutzt, muss deshalb die Sportart kennen.

### 2.4 HFmax-Formel

Tanaka, Monahan & Seals (2001): Metaanalyse über 351 Studien mit 18.712 Personen plus
Laborvalidierung an 514 Personen ergibt **HFmax = 208 − 0,7 × Alter**, unabhängig von
Geschlecht und Trainingszustand. `220 − Alter` überschätzt bei Jüngeren und unterschätzt
ab etwa 40 Jahren, bei 70 Jahren um rund 10 bpm. Die Streuung beträgt bei beiden Formeln
etwa ± 10 bpm; eine gemessene HFmax ist immer besser.

**Vorschlag für A.6 (Stufe 1):** Rückfallregel `208 − 0,7 × Alter` statt `220 − Alter`.
Die Änderung ist eine Zeile im Code und ändert nichts für Nutzer mit eingetragener HFmax.

---

## 3. Methodiken je Sportart (Überblick)

Bücher und Trainerpraxis, zusammengefasst. Sie liefern die **Einheitentypen** und
**Phasenlogik**; die Zahlen werden gegen §2 und §4 geprüft, bevor sie in Regeln landen.

| Methode | Kern | Bezugswert | Eignung für Kairos |
|---|---|---|---|
| Lydiard | lange aerobe Basis, dann Hügel, dann Tempo/Intervalle, dann Schärfe | Gefühl/HF | Phasenlogik für Plantyp 1 |
| Daniels („Running Formula“) | fünf Tempi aus VDOT; Grenzen je Einheit: T ≤ 10 %, I ≤ 8 %, R ≤ 5 % des Wochenumfangs, M ≤ 20 %; Long Run ≤ 2:30 h | VDOT | **Kern für Laufen**: Formeln öffentlich, Grenzen klar regelbar |
| Pfitzinger („Advanced Marathoning“) | Marathonblöcke mit Long Runs, mittellangen Läufen und Laktatschwellenläufen | Renntempo, HF | Einheitentypen für Marathon |
| Hansons Marathon Method | „kumulative Ermüdung“: Long Run gedeckelt (≈ 26 km), dafür hohe Häufigkeit | Renntempo | Alternative für Zeitknappe? eher nein (6 Tage/Woche) |
| 80/20 (Fitzgerald) | 80 % locker, 20 % mittel/hart, Zonen nach LTHR/Pace | LTHR | deckt sich mit §2.2 |
| Coggan/Allen | Leistungszonen, TSS/CTL/ATL | FTP | **Kern für Rad** |
| Friel („Triathlete's Training Bible“) | klassische Periodisierung (Basis, Aufbau, Spitze, Wettkampf), LTHR-Zonen je Sportart, Koppeleinheiten | LTHR, FTP, CSS | **Kern für Triathlon** |

Für den Radsport gibt es eine eigene RCT zu polarisiert vs. Schwelle (Neal et al. 2013,
trainierte Radfahrer, 6 Wochen): polarisiert verbesserte Leistung und Schwellen stärker.
Zu Koppeleinheiten (Rad → Lauf) gibt es kaum kontrollierte Studien; sie bleiben **praxis**.

---

## 4. Periodisierung, Progression, Taper, Erholung

### 4.1 Periodisierungsmodelle

| Modell | Befund |
|---|---|
| klassisch/linear (Basis → Aufbau → Spitze) | Standard in allen Büchern aus §3; Evidenz **praxis** |
| Block (wenige Fähigkeiten pro 1–4-Wochen-Block konzentriert) | Metaanalyse Mølmen et al. 2019: kleiner Vorteil bei VO₂max (SMD 0,40) und Wmax (SMD 0,28), aber nur 6 gepoolte Studien mit 107 Personen und niedriger Qualität |

**Folgerung:** Kairos bildet Phasen ab (D21: Phasen grob, Details rollierend 1–2 Wochen).
Das Modell wird Plantyp-Parameter; Default klassisch.

### 4.2 Progression und Verletzungsrisiko

| Quelle | Befund |
|---|---|
| Nielsen et al. 2014 (873 Laufeinsteiger, 1 Jahr) | > 30 % mehr Wochenumfang über 2 Wochen → mehr Verletzungen als < 10 %; betrifft vor allem Überlastungsverletzungen wie Patellaspitzen-, ITB- und Schienbeinkantensyndrom |
| **Frandsen et al. 2025** (5.205 Läufer, 588.071 Läufe, Garmin, 18 Monate) | Ein Lauf **> 10 % länger als der längste der letzten 30 Tage**: Verletzungsrate ×1,64 (10–30 % länger), ×1,52 (30–100 %), ×2,28 (> 100 %). **Woche-zu-Woche-Verhältnis: kein Zusammenhang.** ACWR: negative Dosis-Wirkung |
| Impellizzeri et al. 2020; Editorial Zouhal et al. 2021 | ACWR methodisch umstritten (willkürliche Fenster, mathematische Kopplung); Evidenz „kontrovers“ |

**Folgerungen für Regeln**

- **Leitplanke (Evidenz hoch):** kein Lauf > 110 % des längsten Laufs der letzten 30 Tage.
  Kairos kann das aus `activity_stats` prüfen, sowohl beim Planen als auch beim
  Wochenrückblick.
- **Weiche Regel (Evidenz mittel):** Wochenumfang höchstens +10 % gegenüber dem Schnitt der
  letzten Wochen; bei Einsteigern strenger.
- **ACWR:** im Dashboard weiter zeigen, aber nicht als Verletzungsampel und nicht als Regel.

### 4.3 Entlastungswochen

Ein Rhythmus 3 : 1 (drei Belastungs-, eine Entlastungswoche mit −20 bis −30 % Umfang) ist
Standard in der Trainerpraxis, aber nicht direkt untersucht. Evidenz: **praxis**.
Der Rhythmus wird Plantyp-Parameter (2 : 1 bis 4 : 1).

### 4.4 Taper

Bosquet et al. 2007 (Metaanalyse, 27 Studien): **Dauer etwa 2 Wochen** (8–14 Tage),
**Umfang −41 bis −60 %**, progressiv bzw. exponentiell reduziert, **Intensität und Häufigkeit
unverändert**. Die Volumenreduktion ist der wirksamste Hebel. Für den Marathon sind in
der Praxis 2–3 Wochen üblich.

### 4.5 HRV-gesteuertes Training (für Stufe 2)

Manresa-Rocamora et al. 2021 (Metaanalyse, 8 Studien, 199 Personen, 2–8 Wochen):
HRV-gesteuert ist für VO₂max (SMD 0,13) und Leistung (SMD 0,20) **nicht signifikant**
besser als vorab festgelegtes Training, erhält aber die vagale HRV besser und erzeugt
möglicherweise weniger Non-Responder. Übliche Entscheidungsregel: harte Einheit, wenn der
7-Tage-Schnitt von RMSSD im Normalbereich liegt (Baseline ± 0,5 SD), sonst locker oder
Pause.

**Folgerung für D32 (automatische Entlastung):** Die Regel „schlechte Erholung → nächste
harte Einheit entschärfen“ ist mit dieser Literatur vereinbar. Der Nutzen ist klein, das
Risiko auch. Die Schwelle sollte relativ zur eigenen Baseline sein, nicht absolut.

---

## 5. Ergänzungssport und Ziele ohne Wettkampf

### 5.1 Krafttraining für Ausdauersportler

| Quelle | Befund |
|---|---|
| Blagrove et al. 2018 (24 Studien, Läufer) | Laufökonomie +2–8 %, Zeitfahren 1,5–10 km tendenziell besser; VO₂max und Körperzusammensetzung unverändert; Empfehlung 2–3 Einheiten/Woche, schwer + explosiv + Plyometrie |
| Llanos-Lagos et al. 2024 (Metaanalyse, 652 Läufer) | wirksam: **schwer (≥ 80 % 1RM)**, kombiniert und Plyometrie; **nicht wirksam: submaximale Lasten und Isometrie**. 6–24 Wochen, 1–4 Einheiten/Woche |
| Schumann et al. 2022 (43 Studien) | Ausdauer + Kraft beeinträchtigt Maximalkraft und Muskelaufbau nicht; **Schnellkraft leidet, wenn beides in einer Einheit** liegt; ≥ 3 h Abstand: kein Effekt |

**Regeln:** 2 Krafteinheiten/Woche in der Basis, 1 in Spitze und Taper (praxis);
Hauptübungen mit ≥ 80 % 1RM bzw. 3–6 Wiederholungen nahe dem Versagen plus Sprünge;
≥ 3 h Abstand zur Ausdauereinheit, nicht vor einer Qualitätseinheit am Folgetag (praxis).
Das betrifft D15 (Kraft-Workouts mit Übungen in V1.1).

### 5.2 Schwimmen

Für Ergänzungsschwimmer reicht die **CSS** als Bezugswert (§2.3); Zonen relativ dazu
(Erholung 65–75 %, Grundlage 75–90 %, Schwelle 90–100 %, VO₂max 100–110 % der
CSS-Geschwindigkeit; die Grenzen variieren je Quelle). Technik dominiert bei Freizeitschwimmern; Pläne setzen deshalb
Technikanteile fest statt Intensitätsziele (praxis).

### 5.3 Yoga und Mobilität

Die Studienlage zu Yoga bei Sportlern ist dünn: Eine systematische Übersicht (Grilli
Cadieux et al. 2021) fand 6 Studien niedriger Qualität mit Hinweisen auf geringere
Leistungsangst und bessere Zufriedenheit. **Folgerung:** Yoga als Erholungs- oder
Mobilitätseinheit planen, ohne Leistungsversprechen; nicht auf das Belastungsbudget anrechnen
(Evidenz niedrig).

### 5.4 Ziele ohne Wettkampf und Einsteiger

- **Gesundheit (WHO 2020, Bull et al.):** pro Woche 150–300 min moderat **oder** 75–150 min
  intensiv **plus** Kraft für alle großen Muskelgruppen an ≥ 2 Tagen; ab 65 Jahren
  zusätzlich Gleichgewicht/Kraft an ≥ 3 Tagen. Das ist ein messbares Ziel, das Kairos aus
  Aktivitäten und HF-Zeit prüfen kann.
- **Einsteiger Laufen:** Lauf-Geh-Wechsel, 3 Einheiten/Woche, in 9 Wochen von 1-min-Läufen
  zu 30 min am Stück (NHS „Couch to 5K“); bei Einsteigern ist die Progressionsregel (§4.2)
  am wichtigsten, weil dort die meisten Überlastungsverletzungen entstehen.

---

## 6. Abgleich mit Max' Regeln aus dem Browser-Coaching (D27)

### 6.1 Regeln

| Regel (Entscheidungsprotokoll §4) | Befund | Vorschlag |
|---|---|---|
| ≈ 80 % locker | deckt sich mit §2.2 (Evidenz hoch) | übernehmen |
| zwei Qualitätseinheiten pro Woche | deckt sich mit Seiler 2010 und Casado 2022 | übernehmen |
| Umfang höchstens +8–10 % pro Woche | Woche-zu-Woche-Verhältnis in der großen Kohorte ohne Zusammenhang; > 30 % schadet bei Einsteigern | als weiche Regel übernehmen, **zusätzlich** die Einzellauf-Leitplanke (110 % des längsten Laufs der letzten 30 Tage) |
| jede 4. Woche Entlastung (−30 %) | Praxis, nicht direkt untersucht | übernehmen als Parameter |
| Long Run höchstens 30–35 % des Wochenumfangs | Praxis; Daniels begrenzt auf 2:30 h | übernehmen, plus 2:30 h als Obergrenze; die Einzellauf-Regel greift zuerst |
| Taper 3 Wochen, Umfang −40 %, Intensität bleibt | Metaanalyse: ≈ 2 Wochen, −41 bis −60 %, Intensität und Häufigkeit halten | für den Marathon 3 Wochen lassen, Umfang am Ende stärker reduzieren (bis −60 %) |
| Kraft 2× pro Woche (einbeinig, Plyometrie, Hüftabduktoren) | deckt sich mit Blagrove 2018; Llanos-Lagos 2024: **schwere** Lasten nötig | um mindestens eine schwere Hauptübung ergänzen (≥ 80 % 1RM) |
| Entkopplung im Long Run < 4 % | Friel nutzt < 5 % (Pa:HR) als Marker aerober Fitness | übernehmen; Kairos kann sie aus `activity_stream` berechnen |

### 6.2 Zahlen

Nach der Daniels-Formel ergibt der 10-km-Test (45:11) **VDOT ≈ 45,0** (im Protokoll steht
45,5). Daraus folgen als Äquivalente Halbmarathon ≈ 1:40:10 und Marathon ≈ 3:28.

| Wert im Protokoll | Entspricht | Anmerkung |
|---|---|---|
| Grundlage 5:25–5:50/km | E-Tempo bei VDOT 45 (65–74 % VO₂max): ≈ 5:19–5:54 | passt |
| Schwelle 4:35/km | T-Tempo (88 % VO₂max) ≈ 4:38 | passt |
| Intervall 4:10–4:15/km | I-Tempo (98 % VO₂max) ≈ 4:14 | passt |
| Halbmarathontempo 4:38–4:42/km | Zielzeit 1:37:48–1:39:12 | **widerspricht** „realistisch 1:33–1:36“ (das wären 4:24–4:33/km, VDOT 47–49) |
| Marathon 3:05–3:15 | VDOT 48,7–51,8 | 4–7 VDOT-Punkte über dem Stand vom 20.09.; der Kontrolltest am 31.10. zeigt, ob das realistisch ist |

Entweder ist eine der beiden Halbmarathon-Angaben falsch übertragen, oder die Zeit ist ein
Fernziel. Max sollte das klären, bevor die Werte in den ersten Plan wandern.

---

## 7. Vorschlag für die Wissensbank (D24)

### 7.1 Ablage und Format

```
knowledge/training/
  README.md                 Aufbau, Vokabular des Regelteils, Evidenzstufen
  quellen.yaml              Literatur: Schlüssel → Autoren, Jahr, Titel, DOI/URL
  regeln/
    intensitaet/            Verteilung, Zonenmodelle
    progression/            Umfang, Einzellauf, Entlastung
    taper/
    kraft/
    tests/                  VDOT, LTHR, FTP, CSS
    einheiten/              Einheitentypen (Long Run, Schwellenintervalle, …)
  plantypen/
    ausdauer-laufen-pyramidal.yaml
    …
```

**Ein Eintrag** ist eine Markdown-Datei. Der Regelteil steht im YAML-Kopf und nutzt ein
**festes Vokabular**, das der Plan-Generator implementiert (kein frei ausführbarer Code).
Der Erklärteil darunter ist für den Agenten und den Nutzer.

```markdown
---
id: lauf.progression.einzellauf
version: 1
titel: Kein Lauf mehr als 10 % über dem längsten der letzten 30 Tage
sportarten: [laufen]
art: leitplanke
evidenz: hoch
quellen: [frandsen2025]
regel:
  typ: obergrenze_relativ
  groesse: lauf.distanz_m
  bezug: {funktion: max, groesse: lauf.distanz_m, fenster_tage: 30}
  faktor: 1.10
  aktion: kuerzen
---

## Warum
In einer Kohorte von 5.205 Läufern stieg die Verletzungsrate, sobald ein einzelner Lauf
mehr als 10 % länger war als der längste Lauf der vorangegangenen 30 Tage …

## Wann nicht
Nach Pausen > 30 Tage gilt der Bezugswert als unbekannt; dann greift die
Einsteiger-Progression.
```

**Regeln für Einträge**

- `id` ist stabil, `version` steigt bei jeder inhaltlichen Änderung. Planblöcke speichern
  `id@version` (D24), damit eine Begründung auch nach Änderungen nachvollziehbar bleibt.
- `evidenz` aus §1; der Agent nennt sie, wenn er eine Regel begründet.
- `quellen` nur über Schlüssel aus `quellen.yaml`.
- Ein CI-Test validiert alle Einträge gegen ein Schema: bekannte `typ`-Werte, existierende
  Quellen, eindeutige `id`s.

**Vokabular für `regel.typ`** (erste Fassung, wächst mit den Einträgen)

| Typ | Bedeutung | Beispiel |
|---|---|---|
| `anteil_min` / `anteil_max` | Anteil einer Größe an einer Summe | Z1 ≥ 75 % der Wochenzeit |
| `obergrenze_relativ` | Wert ≤ Faktor × Bezugswert | Einzellauf ≤ 1,10 × längster Lauf 30 Tage |
| `zuwachs_max` | Änderung gegenüber Vorperiode | Wochenumfang ≤ +10 % |
| `rhythmus` | wiederkehrendes Muster | jede 4. Woche −30 % |
| `phase` | Phasenfolge mit Dauer und Schwerpunkt | Basis → Aufbau → Spitze → Taper |
| `zonen` | Zonengrenzen relativ zu einem Bezugswert | HF-Zonen in % LTHR |
| `test` | Protokoll und Formel für einen Bezugswert | VDOT aus Wettkampfzeit |
| `einheit` | Einheitentyp mit Struktur und Grenzen | Schwellenintervalle, T ≤ 10 % Wochenumfang |
| `abstand_min` | Mindestabstand zwischen Einheiten | Kraft ≥ 3 h vor/nach Ausdauer |

### 7.2 Katalog der ersten Einträge

| Bereich | Einträge | Quellen |
|---|---|---|
| Intensität | Drei-Zonen-Modell; Z1-Anteil ≥ 70 %; polarisiert; pyramidal | Seiler 2010, Stöggl 2014/2015, Casado 2022, Silva Oliveira 2024, Festa 2020 |
| Tests | VDOT; Critical Speed; LTHR (Lauf, Rad); FTP; CSS; HFmax-Formel | Daniels & Gilbert 1979, Pettitt 2016, Friel, Allen & Coggan, Wakayoshi 1992, Tanaka 2001 |
| Progression | Einzellauf ≤ 110 %; Wochenzuwachs ≤ 10 %; Einsteiger-Progression; Entlastungsrhythmus | Frandsen 2025, Nielsen 2014, NHS |
| Einheiten | Long Run (≤ 2:30 h, ≤ 30–35 %); Schwelle (≤ 10 %); Intervalle (≤ 8 %); Wiederholungen (≤ 5 %); Marathontempo (≤ 20 %); Steigerungen | Daniels, Pfitzinger |
| Taper | 2 Wochen, −41 bis −60 %, Intensität halten | Bosquet 2007 |
| Kraft | schwere Last; Plyometrie; Abstand ≥ 3 h; Häufigkeit nach Phase | Blagrove 2018, Llanos-Lagos 2024, Schumann 2022 |
| Erholung | HRV-Baseline-Regel (für Stufe 2) | Manresa-Rocamora 2021 |
| Gesundheit | WHO-Minuten, Kraft ≥ 2 Tage | Bull 2020 |
| Ergänzung | Yoga als Erholung ohne Leistungsanspruch | Grilli Cadieux 2021 |

### 7.3 Plantypen (D25)

| Plantyp | Zielgruppe | Bausteine | Bezugswerte |
|---|---|---|---|
| `ausdauer-laufen-pyramidal` | Wettkampfläufer (Max) | Phasen klassisch, Z1 ≥ 80 %, 2 Qualitätseinheiten, Einheitengrenzen nach Daniels, Einzellauf-Leitplanke, 3 : 1, Taper, Kraft 2× | VDOT, LTHR, HFmax |
| `einsteiger-laufen` | Laufeinsteiger, Wiedereinsteiger | Lauf-Geh-Progression, 3 Einheiten/Woche, nur Z1, strenge Progression | keine (HFmax optional) |
| `gesundheit-ausdauer` | Ziele ohne Wettkampf, beliebige Sportart | WHO-Minuten, Kraft ≥ 2 Tage, Yoga/Mobilität optional | HFmax |
| `ausdauer-rad` | Radfahrer mit Leistungsmesser | Coggan-Zonen, Z1 ≥ 75 %, Entlastungsrhythmus, Taper | FTP, LTHR |

Triathlon (Friel) folgt als fünfter Plantyp, sobald ein Nutzer ihn braucht; er
kombiniert die Bausteine von Laufen, Rad und Schwimmen (CSS) und ergänzt
Koppeleinheiten.

### 7.4 Urheberrecht (das Repo ist öffentlich)

Methoden, Formeln und Erkenntnisse sind nicht geschützt, ihre konkrete Darstellung schon.
Deshalb:

- Einträge **in eigenen Worten**, keine Textpassagen aus Büchern oder Artikeln;
- **keine Tabellen aus Büchern** übernehmen (z. B. Daniels' VDOT-Tabellen): Kairos
  berechnet die Werte aus den veröffentlichten Formeln;
- Quellen immer angeben, mit DOI bzw. Link.

Das ist eine Arbeitsregel, keine Rechtsberatung.

---

## 8. Entscheidungen für Max

1. **HFmax-Rückfall:** `208 − 0,7 × Alter` (Tanaka) statt `220 − Alter` in A.6? Betrifft die
   laufende Umsetzung von Stufe 1.
2. **Halbmarathon-Ziel:** 1:33–1:36 oder Tempo 4:38–4:42 (≈ 1:38–1:39)? (§6.2)
3. **Default-Verteilung** für `ausdauer-laufen-pyramidal`: pyramidal oder polarisiert?
   Die Literatur entscheidet es nicht; Vorschlag pyramidal in der Basis, polarisiert in
   kurzen Blöcken vor dem Wettkampf.
4. **Reihenfolge der Plantypen:** Vorschlag `ausdauer-laufen-pyramidal` →
   `gesundheit-ausdauer` → `einsteiger-laufen` → `ausdauer-rad` → Triathlon. Welche
   Sportarten und Ziele haben die anderen Nutzer (Entscheidungsprotokoll §6, Punkt 3)?
5. **Kraft:** Soll Kairos 1RM-Schätzungen speichern (für Lastvorgaben in V1.1) oder nur mit
   „Wiederholungen in Reserve“ arbeiten?

---

## Quellen

- Allen H, Coggan A (2006). *Training and Racing with a Power Meter*. VeloPress. Zonen und 20-min-Test zusammengefasst nach [Favero: Power training zones](https://cycling.favero.com/en/blog/power-training-zones-cycling) und [Favero: FTP test](https://cycling.favero.com/en/blog/ftp-test-what-it-and-how-do-it).
- Blagrove RC, Howatson G, Hayes PR (2018). Effects of strength training on the physiological determinants of middle- and long-distance running performance: a systematic review. *Sports Med* 48(5):1117–1149. [Repositorium Loughborough](https://repository.lboro.ac.uk/articles/journal_contribution/Effects_of_strength_training_on_the_physiological_determinants_of_middle-_and_long-distance_running_performance_a_systematic_review/9619553)
- Bosquet L, Montpetit J, Arvisais D, Mujika I (2007). Effects of tapering on performance: a meta-analysis. *Med Sci Sports Exerc* 39(8):1358–1365. [Zusammenfassung](https://coachsci.sdsu.edu/csa/vol131/bosquet.htm)
- Bull FC et al. (2020). World Health Organization 2020 guidelines on physical activity and sedentary behaviour. *Br J Sports Med* 54:1451–1462. doi:10.1136/bjsports-2020-102955. [Repositorium](https://digibug.ugr.es/handle/10481/66573)
- Casado A et al. (2022). Training-intensity distribution on middle- and long-distance runners: a systematic review. *Int J Sports Med* 43(4):305–316. doi:10.1055/a-1559-3623. [Thieme](https://thieme-connect.de/products/all/doi/10.1055/a-1559-3623)
- Daniels J (2022). *Daniels' Running Formula*, 4. Aufl. Human Kinetics. Tempi und Einheitengrenzen zusammengefasst nach [Coach Ray: Jack Daniels running intensity](https://www.coachray.nz/2023/05/03/jack-daniels-running-intensity/); Formeln nach Daniels J, Gilbert J (1979), *Oxygen Power*, wiedergegeben im [intervals.icu-Forum](https://forum.intervals.icu/t/script-for-calculating-jack-daniels-vdot/131024).
- Festa L, Tarperi C, Skroce K, La Torre A, Schena F (2020). Effects of different training intensity distribution in recreational runners. *Front Sports Act Living* 1:70. [Frontiers](https://www.frontiersin.org/journals/sports-and-active-living/articles/10.3389/fspor.2019.00070/full)
- Fitzgerald M (2014). *80/20 Running*. Penguin.
- Frandsen JSB et al. (2025). How much running is too much? Identifying high-risk running sessions in a 5200-person cohort study. *Br J Sports Med* 59(17):1203–1210. doi:10.1136/bjsports-2024-109380. [LIH Research Portal](https://researchportal.lih.lu/en/publications/how-much-running-is-too-much-identifying-high-risk-running-sessio/)
- Friel J. LTHR-Test und Zonen: [TrainingPeaks](https://www.trainingpeaks.com/blog/joe-friel/); *The Triathlete's Training Bible*, VeloPress.
- Grilli Cadieux E, Gemme C, Dupuis G (2021). Effects of yoga interventions on psychological health and performance of competitive athletes: a systematic review. *J Sci Sport Exerc* 3(2):158–166. [Journal](https://journal.hep.com.cn/josisae/EN/10.1007/s42978-020-00104-y)
- Impellizzeri FM et al. (2020). Acute:chronic workload ratio: conceptual issues and fundamental pitfalls. *Int J Sports Physiol Perform* 15(6):907–913. Einordnung: Zouhal H et al. (2021), Editorial, *Front Physiol* 12:669687, [doi:10.3389/fphys.2021.669687](https://dx.doi.org/10.3389/fphys.2021.669687).
- Llanos-Lagos C, Ramirez-Campillo R, Moran J, Sáez de Villarreal E (2024). Effect of strength training programs in middle- and long-distance runners' economy at different running speeds: a systematic review with meta-analysis. *Sports Med* 54(4):895–932. [Repositorium Essex](https://repository.essex.ac.uk/37272/)
- Manresa-Rocamora A et al. (2021). Heart rate variability-guided training for enhancing cardiac-vagal modulation, aerobic fitness, and endurance performance: a methodological systematic review with meta-analysis. *Int J Environ Res Public Health* 18:10299. [MDPI (PDF)](https://mdpi-res.com/d_attachment/ijerph/ijerph-18-10299/article_deploy/ijerph-18-10299.pdf)
- Mølmen KS, Øfsteng SJ, Rønnestad BR (2019). Block periodization of endurance training – a systematic review and meta-analysis. *Open Access J Sports Med* 10:145–160. [Dove Press](https://www.dovepress.com/block-periodization-of-endurance-training-a-systematic-review-and-meta-peer-reviewed-fulltext-article-OAJSM)
- Muñoz I et al. (2014). Does polarized training improve performance in recreational runners? *Int J Sports Physiol Perform* 9(2):265–272. [BISp/IAT](https://lida.sport-iat.de/ta/Record/4031233?lng=en)
- Neal CM et al. (2013). Six weeks of a polarized training-intensity distribution leads to greater physiological and performance adaptations than a threshold model in trained cyclists. *J Appl Physiol* 114:461–471. [Deakin](https://dro.deakin.edu.au/articles/journal_contribution/Six_weeks_of_a_polarized_training-intensity_distribution_leads_to_greater_physiological_and_performance_adaptations_than_a_threshold_model_in_trained_cyclists/20795662)
- NHS. Couch to 5K. [nhs.uk](https://www.nhs.uk/better-health/get-active/get-running-with-couch-to-5k/)
- Nielsen RO et al. (2014). Excessive progression in weekly running distance and risk of running-related injuries. *J Orthop Sports Phys Ther* 44(10):739–747. [PDF](https://www.orthobethesda.com/wp-content/uploads/2020/06/jospt-running-increased-mileage.pdf)
- Pettitt RW (2016). Applying the critical speed concept to racing strategy and interval training prescription. *Int J Sports Physiol Perform* 11(7):842–847. [BISp/IAT](https://lida.sport-iat.de/dlv/Record/4041747?lng=en)
- Pfitzinger P, Douglas S (2019). *Advanced Marathoning*, 3. Aufl. Human Kinetics.
- Schumann M et al. (2022). Compatibility of concurrent aerobic and strength training for skeletal muscle size and function: an updated systematic review and meta-analysis. *Sports Med* 52:601–612. [BISp/IAT](https://lida.sport-iat.de/ta/Record/4078897?lng=en)
- Seiler S (2010). What is best practice for training intensity and duration distribution in endurance athletes? *Int J Sports Physiol Perform* 5(3):276–291. [BISp/IAT](https://lida.sport-iat.de/ta/Record/4020753?lng=en)
- Silva Oliveira P, Boppre G, Fonseca H (2024). Comparison of polarized versus other types of endurance training intensity distribution on athletes' endurance performance: a systematic review with meta-analysis. *Sports Med* 54(8):2071–2095. doi:10.1007/s40279-024-02034-z
- Stöggl T, Sperlich B (2014). Polarized training has greater impact on key endurance variables than threshold, high intensity, or high volume training. *Front Physiol* 5:33. [Frontiers](https://www.frontiersin.org/journals/physiology/articles/10.3389/fphys.2014.00033/full)
- Stöggl T, Sperlich B (2015). The training intensity distribution among well-trained and elite endurance athletes. *Front Physiol* 6:295. [Frontiers](https://public-pages-files-2025.frontiersin.org/journals/physiology/articles/10.3389/fphys.2015.00295/text)
- Tanaka H, Monahan KD, Seals DR (2001). Age-predicted maximal heart rate revisited. *J Am Coll Cardiol* 37(1):153–156. [PDF](https://webs.um.es/jlyuste/documts/tanaka.pdf)
- The Norwegian double-threshold method in distance running: systematic literature review (2023). *Scientific Journal of Sport and Performance* 3(1):38–46. doi:10.55860/NBXV4075. [BISp/IAT](https://lida.sport-iat.de/ta/Record/4085594)
- Wakayoshi K et al. (1992). Determination and validity of critical velocity as an index of swimming performance in the competitive swimmer. *Eur J Appl Physiol* 64:153–157. Protokoll nach [Topend Sports](https://www.topendsports.com/testing/tests/critical-swim-speed.htm).
