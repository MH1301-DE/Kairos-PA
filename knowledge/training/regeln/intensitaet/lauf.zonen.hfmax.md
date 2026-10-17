---
id: lauf.zonen.hfmax
version: 1
titel: Rückfall-Herzfrequenzbereiche in Prozent der HFmax
sportarten: [laufen]
art: parameter
evidenz: praxis
quellen: [daniels2022, tanaka2001]
regel:
  typ: zonen
  bezugswert: hf_max
  einheit: prozent_hfmax
  zonen:
    - {name: E, zone3: z1, von: 65, bis: 79}
    - {name: M, zone3: z2, von: 80, bis: 89}
    - {name: T, zone3: z2, von: 88, bis: 92}
    - {name: I, zone3: z3, von: 97, bis: 100}
    - {name: R, zone3: z3, von: 97, bis: 100}
---

## Warum

Fehlt eine Schwellenherzfrequenz, lassen sich grobe Bereiche aus der maximalen
Herzfrequenz ableiten. Ohne gemessene HFmax schätzt Kairos sie mit 208 − 0,7 × Alter
(Tanaka); die Streuung liegt bei etwa ± 10 Schlägen.

## Wann nicht

Wenn eine gemessene HFmax oder ein LTHR-Test vorliegt, gelten diese Werte; die Bereiche
hier sind dann nur noch Plausibilitätsprüfung.

## Für den Nutzer

Diese Bereiche sind geschätzt; ein Schwellentest macht sie genauer.
