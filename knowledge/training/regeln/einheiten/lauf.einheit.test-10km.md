---
id: lauf.einheit.test-10km
version: 1
titel: Kontrolltest über 10 km für einen neuen VDOT
sportarten: [laufen]
art: einheit
evidenz: praxis
quellen: [danielsgilbert1979, daniels2022]
regel:
  typ: einheit
  sport: laufen
  zone: z3
  klasse: test
  struktur:
    - {typ: einlaufen, tempo: E, dauer_s: 900}
    - {typ: belastung, tempo: T, distanz_m: 10000, notiz: "maximal gleichmäßig laufen"}
    - {typ: auslaufen, tempo: E, dauer_s: 600}
---

## Warum

Ein maximal gelaufener 10-km-Test liefert einen aktuellen VDOT und damit aktuelle Tempi.
Kairos plant ihn ein, wenn der letzte Wert älter als ein Trainingsblock ist.

## Wann nicht

Nicht in der Taperphase und nicht direkt nach einer Erkrankung; dann lieber verschieben.

## Für den Nutzer

Ein ehrlicher 10-km-Test aktualisiert deine Tempi.
