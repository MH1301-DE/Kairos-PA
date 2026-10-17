# Wissensbank Training

Grundlage für den Coach-Modus (Spec `docs/superpowers/specs/2026-10-17-coach-modus-design.md`
§3). Der Plan-Generator liest nur den **Regelteil** (YAML-Kopf), der Agent und die Oberfläche
zusätzlich den **Erklärteil**.

## Aufbau

```
quellen.yaml          Literatur: Schlüssel → Autoren, Jahr, Titel, DOI/URL
regeln/<bereich>/     ein Eintrag (Markdown) je Regel
plantypen/            Plantyp = Auswahl von Einträgen + Parameter
```

## Eintrag

YAML-Kopf mit `id` (`<sport>.<bereich>.<name>`, stabil), `version` (steigt bei jeder
inhaltlichen Änderung), `titel`, `sportarten`, `art`, `evidenz`, `quellen` und `regel`.
Darunter die Abschnitte **„## Warum“**, **„## Wann nicht“** und **„## Für den Nutzer“**
(ein Satz, den Kairos bei Warnungen zeigt).

Planblöcke speichern `id@version`; alte Fassungen bleiben über Git nachvollziehbar.

### `art`

| Wert | Wirkung |
|---|---|
| `leitplanke` | blockiert: der Generator kürzt oder lässt weg, Änderungen im Chat nur mit Begründung und Bestätigung |
| `regel` | der Generator hält sie ein, der Prüfer warnt |
| `parameter` | der Plantyp setzt den Wert |
| `einheit` | Einheitentyp mit Struktur |
| `test` | Bezugswert und Formel |

### Evidenzstufen

`hoch` (Metaanalyse oder große Kohorte), `mittel` (einzelne RCTs), `niedrig` (kleine oder
widersprüchliche Studien), `praxis` (etablierte Trainerpraxis ohne direkte Studienlage).

### Vokabular des Regelteils

Nur die Typen aus `src/kairos/coach/rules.py`: `anteil_min`, `anteil_max`,
`obergrenze_relativ`, `obergrenze_absolut`, `zuwachs_max`, `rhythmus`, `phase`, `taper`,
`zonen`, `test`, `einheit`, `abstand_min`, `haeufigkeit`. Freie Ausdrücke oder Code sind
ausgeschlossen. Ein neuer Typ braucht eine neue Klasse und einen Test.

## Arbeitsregeln

- **Eigene Worte**, keine Textpassagen aus Büchern oder Artikeln, **keine Tabellen aus
  Büchern** (z. B. VDOT-Tabellen): Kairos rechnet aus den veröffentlichten Formeln.
- Jede Aussage mit Quelle aus `quellen.yaml`; Evidenzstufe ehrlich angeben.
- **Keine personenbezogenen Trainingsdaten** in diesem Verzeichnis (das Repo ist öffentlich).
- Der Agent liest die Wissensbank, schreibt aber nie hinein; Änderungen laufen über Pull
  Requests. `tests/test_knowledge_base.py` prüft Schema, Quellen und Referenzen.

Das ist eine Arbeitsregel, keine Rechtsberatung.
