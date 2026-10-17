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

In einer großen Kohorte mit Daten von Laufuhren stieg das Verletzungsrisiko deutlich,
sobald ein einzelner Lauf mehr als 10 % länger war als der längste Lauf der
vorangegangenen 30 Tage. Das Verhältnis der Wochenumfänge zeigte dort keinen solchen
Zusammenhang. Kairos prüft deshalb jeden geplanten Lauf gegen die eigene Historie.

## Wann nicht

Nach einer Pause von mehr als 30 Tagen fehlt der Bezugswert; dann plant Kairos vorsichtig
von kurzen Läufen aus neu. Wettkämpfe zählen mit, weil sie die Belastung real erhöht haben.

## Für den Nutzer

Ein Lauf, der mehr als 10 % länger ist als dein längster der letzten 30 Tage, erhöht das Verletzungsrisiko.
