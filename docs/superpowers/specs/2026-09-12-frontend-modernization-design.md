# Frontend-Modernisierung: Design-Spezifikation

> Autonome Session (Nutzer explizit: "gehe kritisch über das Frontend, mach es
> hübscher... schau dir moderne Websites/Frameworks an... lege Pläne an und
> führe sie aus"). Jede Design-Entscheidung unten ist mit Begründung
> dokumentiert, keine stillschweigenden Annahmen — gleiches Muster wie Phase 3.

## Ziel

Drei konkrete Lücken schließen: (1) das Dashboard ist komplett statisch (8
fest verdrahtete Module, keine Personalisierung), (2) es gibt keine einzige
echte Mobile-Breakpoint-Regel im ganzen Frontend — nur `prefers-reduced-
motion`, (3) das bestehende Design hat reale Schwächen (siehe Audit unten),
die mit gezielten Verbesserungen behoben werden, nicht mit einem kompletten
Neuaufbau.

## Kritischer Ist-Zustand-Audit

**Was bereits gut ist, nicht anfassen:** `app.css`s Design-Token-System (dark
"training cockpit" Palette, Fraunces/Inter/IBM-Plex-Mono-Dreiklang) hat
echten gestalterischen Charakter, keine generische Bootstrap-Optik. Bleibt
Grundlage — kein Wechsel zu einem Component-Framework, das das wegwischen
würde (siehe Scope-Entscheidung 1).

**Echte Lücken, mit Beleg:**

1. **Keine Dashboard-Personalisierung.** `web/src/lib/modules.ts`s `MODULES`
   ist ein statisches Array — jeder Nutzer sieht exakt dieselben 8 Kacheln in
   exakt derselben Reihenfolge, kann keine ausblenden oder umsortieren.
   `docs/05-erweiterbarkeit.md` §2.4 beschreibt das Zielbild ("Jeder Nutzer
   hat eine persönliche `user_dashboard`-Tabelle") bereits — nie gebaut.
2. **Null Mobile-Breakpoints.** `grep -r "@media" web/src` findet genau eine
   Regel im ganzen Projekt (`prefers-reduced-motion`). Konkrete Folgen auf
   einem iPhone-Viewport (375–430px Breite):
   - `+layout.svelte`s Nav (`Kairos`-Wordmark + 5 Nav-Links + "Konto & Sync
     ▾"-Dropdown-Trigger, alles in einer Flex-Zeile) läuft über oder bricht
     hässlich um — keine Hamburger-/Drawer-Alternative.
   - `.field input`s Font-Size ist `var(--text-base)` = 0,9375rem ≈ 15px —
     **unter** Safaris 16px-Schwelle, iOS zoomt beim Fokussieren jedes
     Formularfelds automatisch rein (jedes Login-, Ziel-, Kalender-Formular
     betroffen).
   - `/chat`s `16rem 1fr`-Grid (feste Sidebar-Breite) lässt auf 375px kaum
     Platz für den eigentlichen Chat-Verlauf.
   - `/calendar`s 7-Spalten-Monatsraster bekommt auf 375px ~50px pro Zelle —
     Zahlen und Event-Chips werden kaum lesbar.
   - `app.html` hat kein `viewport-fit=cover` (bricht `env(safe-area-inset-*)`
     auf Geräten mit Notch/Dynamic Island) und keinen
     `apple-mobile-web-app-capable`/`apple-touch-icon`-Eintrag — die PWA
     fühlt sich auf iPhone nicht nativ an, obwohl `vite-plugin-pwa` bereits
     installiert ist.
3. **Kleinere Politur-Punkte** (nicht strukturell, aber sichtbar): keine
   Ladeanimation/Skeleton-State außer Text ("Lädt …"); Formular-Buttons und
   Links haben keinen konsistenten Disabled-/Pending-Zustand über alle Seiten
   hinweg (manche Seiten haben ihn, z. B. Onboarding, andere nicht); der
   native `window.confirm()` für externe Kalendertermine (aus dieser Session)
   ist funktional, aber visuell ein Fremdkörper (Browser-Chrome statt
   App-Look).

## Scope-Entscheidungen (mit Begründung)

**1. Kein Wechsel zu Tailwind/shadcn-svelte, kein Component-Framework.**
Recherche (siehe unten) zeigt shadcn-svelte (auf Bits UI + Tailwind CSS v4)
als aktuell dominanten Standard für neue Svelte-5-Projekte — aber ein
Umstieg hieße, jede bestehende Seite neu zu schreiben und das bereits
gelungene, charakterstarke Eigen-Design-System wegzuwerfen. Das steht in
keinem Verhältnis zum eigentlichen Auftrag ("hübscher machen", nicht "neu
bauen"). Stattdessen: das bestehende Token-System kritisch verfeinern +
gezielt eine headless Bibliothek nur dort einsetzen, wo sie ein echtes,
schwer selbst zu lösendes Problem löst (Punkt 2).

**2. `svelte-dnd-action` für Drag-and-Drop-Kachel-Neuordnung.** Aktiv
gepflegt, Svelte-5-Runes-kompatibel (letzte Version zum Zeitpunkt dieser
Recherche vor 18 Tagen), Pointer-Events (Touch-fähig, also Mobile-tauglich),
`use:dndzone`-Action fügt sich ohne Framework-Overhead ins bestehende
CSS-System ein. Alternative (`svelte-dashboard`/Gridstack.js-Wrapper) bietet
mehr (Resize, Multi-Breakpoint-Grid-Engine), bringt aber eine fremde
CSS-/Verhaltens-Schicht mit, die gegen das bestehende Design arbeiten würde
— für "Kacheln sortieren/ausblenden" (nicht "Kacheln frei resizen") overkill.

**3. Personalisierung = Reihenfolge + Sichtbarkeit der 8 bestehenden Module,
keine nutzerdefinierten neuen Module.** `docs/05-erweiterbarkeit.md`s
volles Zielbild (deklarative `module_registry`-Tabelle, generischer
`data_endpoint` pro Modul) wäre ein eigenes, viel größeres Feature — aktuell
sind `MODULES` und ihre `ModuleDef`s reiner Frontend-Code mit Custom-Chart-
Logik pro Modul (Gauge-Bänder, Trend-Keys), keine generische Config. Diese
Spec baut nur Reihenfolge/Sichtbarkeit — ein natürlicher, aber separater
Folge-Schritt wäre später, die in dieser Session bereits gebauten
Custom-Metriken (`custom_metric_definition`) als zusätzliche Kachel-Optionen
anzubieten.

**4. Kein Light-Mode.** `color-scheme: dark` ist fest verankert, keine
`prefers-color-scheme: light`-Alternative. Bewusst nicht Teil dieser Spec —
das dunkle "Cockpit"-Thema ist die gestalterische Identität des Produkts
(siehe `app.css`s eigener Kommentar), ein Light-Mode wäre eine separate
Design-Entscheidung mit eigenem Abstimmungsbedarf, kein "Bugfix".

## Datenmodell

### Neue Tabelle: `user_dashboard_tile`

```
user_id       UUID FK app_user, RLS-Spalte, Teil des PK
module_id     TEXT NOT NULL, Teil des PK        -- z.B. 'trimp', 'hrv_baseline'
position      SMALLINT NOT NULL                  -- Sortierreihenfolge, 0-basiert
visible       BOOLEAN NOT NULL DEFAULT true

PRIMARY KEY (user_id, module_id)
FORCE ROW LEVEL SECURITY (Standard-Muster)
```

**Kein Default-Seed bei Nutzeranlage.** Fehlen Zeilen für einen Nutzer
(Neuanlage, oder noch nie personalisiert), liefert das Backend die
`MODULES`-Reihenfolge aus `modules.ts`-Äquivalent serverseitig als Fallback
— siehe unten. Kein Migrations-Seed nötig, kein Sonderfall "Nutzer X hat
noch keine Zeilen".

## Backend-Architektur

### `src/kairos/routers/dashboard.py`

- `GET /api/dashboard/layout` — liefert `[{module_id, position, visible}]`.
  Fehlen Zeilen für den Nutzer, wird die feste Standardreihenfolge (Backend-
  seitige Konstante, exakt die aktuelle `MODULES`-Reihenfolge gespiegelt)
  mit `visible=true` für alle 8 zurückgegeben — kein Unterschied zum
  heutigen Verhalten für einen Nutzer, der nie personalisiert.
- `PUT /api/dashboard/layout` — Body `{tiles: [{module_id, position,
  visible}]}`, ersetzt die komplette gespeicherte Reihenfolge des Nutzers
  (Delete-then-Insert in einer Transaktion, gleiches Muster wie
  `recompute_wellness_daily_stats`). Validiert `module_id` gegen die
  bekannte Modul-Liste (422 bei unbekannter ID) — verhindert Karteileichen,
  falls ein Modul später entfernt wird.

## Frontend-Architektur

### Dashboard-Seite (`web/src/routes/+page.svelte`)

- Lädt zusätzlich `GET /api/dashboard/layout`, sortiert/filtert `MODULES`
  entsprechend, bevor die Kacheln gerendert werden.
- Neuer "Anpassen"-Button neben "Aktualisieren" schaltet einen
  Personalisierungs-Modus frei: `use:dndzone` auf dem Kachel-Grid (Drag-Griff
  pro Kachel, sichtbar nur im Anpassen-Modus, `touch-action: none` auf dem
  Griff für sauberes Touch-Dragging), plus ein Sichtbarkeits-Toggle
  (Checkbox) pro Kachel. "Speichern" sendet den neuen Zustand via `PUT`,
  aktualisiert die serverseitige Reihenfolge.
- Ausgeblendete Kacheln verschwinden aus dem normalen Grid, tauchen im
  Anpassen-Modus aber weiter auf (abgedunkelt), damit sie wieder einblendbar
  sind — kein Datenverlust, nur Sichtbarkeit.

### Mobile-Responsive-Durchgang (betrifft jede Seite)

- **Nav (`+layout.svelte`):** unterhalb `640px` klappt die Nav-Links-Zeile
  in ein Hamburger-Icon + Vollbild-Drawer-Menü (gleiches `menu-panel`-Muster
  wie der bestehende "Konto & Sync"-Dropdown, nur volle Höhe statt Popup).
  "Konto & Sync" wird Teil desselben Drawers statt eines zweiten Triggers.
- **`.field input` Font-Size:** `var(--text-base)` (15px) → mindestens 16px
  auf Formularfeldern, verhindert iOS-Auto-Zoom. Betrifft `app.css` global,
  kein Seiten-Einzelfix nötig.
- **`app.html`:** `viewport-fit=cover` ergänzt, `apple-mobile-web-app-
  capable`/`apple-mobile-web-app-status-bar-style`/`apple-touch-icon`
  ergänzt (nutzt das bereits vorhandene PWA-Icon aus `vite-plugin-pwa`s
  Manifest-Config).
- **`main`-Container:** `padding: var(--space-6)` (32px beidseitig) skaliert
  unterhalb `640px` auf `var(--space-4)` (16px) — auf 375px Breite sind 64px
  Gesamt-Padding spürbar viel.
- **`/chat`s Sidebar-Grid:** unterhalb `768px` wird die Konversationsliste zu
  einem einklappbaren Drawer (Toggle-Button) statt einer festen linken
  Spalte — der Chat-Verlauf bekommt die volle Breite.
- **`/calendar`s Monatsraster:** unterhalb `640px` schrumpfen Zellenpadding
  und Font-Size gezielt (kein Strukturwechsel zu einer Listenansicht — das
  wäre ein größerer Umbau, hier reicht dichteres Spacing, da 7 Spalten auf
  einem Handy ohnehin das übliche Kalender-UX-Muster sind, siehe Referenz-
  Recherche unten).
- Alle Touch-Ziele (Buttons, Nav-Links, Kachel-Drag-Griffe) mindestens
  44×44px effektive Trefffläche (Apple-HIG-Richtwert), auch wenn die
  sichtbare Größe kleiner bleibt (Padding statt sichtbarer Vergrößerung).

### Kleinere Politur (aus dem Audit oben)

- Einheitlicher `.btn[disabled]`-Zustand in `app.css` (reduzierte Opazität +
  `cursor: not-allowed`) statt seitenweise unterschiedlicher Handhabung.
- Skeleton-Loading-Zustand für Kacheln (ein pulsierender Platzhalter-Block
  statt nur "Lädt …"-Text) — kleine, kontained Änderung in `MetricTile.svelte`
  bzw. der Dashboard-Seite.

## Recherche-Grundlage (2026-09-12)

- shadcn-svelte (Bits UI + Tailwind v4) ist der aktuelle De-facto-Standard
  für neue Svelte-5-Projekte — bewusst nicht übernommen, siehe
  Scope-Entscheidung 1.
- `svelte-dnd-action`: aktiv gepflegt, Svelte-5-Runes-kompatibel, Touch-fähig
  über Pointer Events — Wahl für Scope-Entscheidung 2.
- 7-Spalten-Monatsraster auf Mobile ist ein etabliertes, akzeptiertes Muster
  (Apple Kalender, Google Kalender zeigen auf dem iPhone ebenfalls ein
  komprimiertes Monatsraster, keine Listenansicht als Standard) — bestätigt,
  dass dichteres Spacing statt Strukturwechsel die richtige Wahl ist.

## Testing-Strategie

- Backend: Router-Tests für `GET`/`PUT /api/dashboard/layout` (Default-
  Fallback ohne gespeicherte Zeilen, Validierung unbekannter `module_id`,
  RLS-Isolation) — gleiches Muster wie `test_memory_router.py`.
- Frontend: Vitest-Komponententest für die Sortier-/Filter-Logik (reine
  Funktion: `MODULES` + Layout-Response → sortierte, gefilterte Liste),
  gleiches Muster wie `dashboardTiles.test.ts`.
- **Kein automatisierter visueller/Responsive-Test** — Playwright-Viewport-
  Tests wären möglich, aber ohne echten Login (Google OAuth, gleiche
  Einschränkung wie schon in dieser Session dokumentiert) nicht sinnvoll
  aufsetzbar. Manuelle Prüfung durch den Nutzer selbst empfohlen, sobald ein
  LLM-Key + echter Login verfügbar sind.

## Global Constraints (gelten für jeden Task)

- `install_rls_listener(session, user_id)` auf jeder Session, die
  `user_dashboard_tile` liest/schreibt.
- `ruff` (line-length 100) + `mypy --strict`, conventional commits.
- Frontend: Svelte-5-Runes-Syntax, bestehende `app.css`-Tokens — keine neuen
  Farben/Fonts ohne Grund, `svelte-dnd-action` ist die einzige neue
  Frontend-Abhängigkeit dieser Spec.
- Jede neue `@media`-Regel nutzt die gleichen Breakpoints konsistent
  (`640px` = Telefon/Tablet-Grenze, `768px` = größere Sidebar-Layouts) statt
  Seiten-individueller Zahlen.
