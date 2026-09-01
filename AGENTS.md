# AGENTS.md

Technische Hinweise für Agents/Contributor, die an diesem Repository
arbeiten. Für Installation und CLI-Nutzung siehe [README.md](README.md).

## Architektur

- `dav_touren.py` – Scraping-Logik für die vier Sektionen, das `Tour`-
  Datenmodell und die sektionsübergreifende Normalisierung (Tourart, Gruppe,
  Schwierigkeit).
- `generate_site.py` – baut `docs/` (die deployte Website) aus den Live-Daten
  und `site/template.html`.
- `site/template.html` – die eigentliche Frontend-App: Vanilla JS, kein
  Build-Step, keine Abhängigkeiten.
- `docs/index.html`, `docs/404.html`, `docs/tours.json` – generierte
  Artefakte. **Nicht von Hand editieren** – immer über `generate_site.py`
  neu erzeugen, sonst laufen sie vom Template auseinander.
- `.github/workflows/deploy.yml` – CI, führt `generate_site.py` aus und
  committet `docs/` bei Änderungen.

## Datenquellen je Sektion

Alle vier Quellen sind undokumentierte, aber öffentlich zugängliche
Implementierungsdetails der jeweiligen Websites – bei Layout- oder
Systemwechseln der Seiten kann das Tool angepasst werden müssen.

- **Friedrichshafen** (dav-fn.de): Die Übersichtsseite
  `/programm_neu_so26/gesamt` ist eine Vue-Single-Page-App, bettet aber ein
  `schema.org`-JSON-LD `ItemList` mit allen Tour-Detail-URLs serverseitig ein.
  Jede Detailseite liefert ihrerseits vollständige JSON-LD-Daten (Titel,
  Datum, Beschreibung), die abgerufen werden. Die Tourart steht auf keiner
  dieser Seiten; sie wird über die fünf Bergsportart-Unterseiten
  (Wandern, Bergsteigen, Klettern, Skibergsteigen, Mountainbike) ermittelt,
  die jeweils nur ihre eigenen Touren als JSON-LD listen. Die
  Gruppenzugehörigkeit (Familiengruppe, Alpin+, Seniorengruppe, ...) wird
  analog über die "gemeinsam"-Unterseiten pro Gruppe ermittelt und getrennt
  von der Tourart im eigenen `group`-Feld geführt.
- **Ravensburg** (dav-ravensburg.info): Nutzt die TYPO3-Extension `we_tour`.
  Deren Kalender-Listenansicht wird über den internen AJAX-Endpunkt
  `/we_tour.ajax` abgefragt und die zurückgelieferte HTML-Tabelle geparst.
  Tourart und Bewertung/Schwierigkeit ("Bewertung:") stehen nur auf der
  Detailseite jeder Tour und werden von dort nachgeladen.
- **Überlingen** (dav-ueberlingen.de): WordPress mit eigenem `touren`-Post-Type
  (per REST API unter `/wp-json/wp/v2/touren` abrufbar, allerdings ohne
  strukturiertes Tourdatum). Stattdessen wird die paginierte `/touren`-
  Archivseite gescraped, die Datum, Titel, Tourart und Schwierigkeit (T-Skala)
  serverseitig in HTML rendert.
- **Lindau** (alpenverein-lindau.de): Bettet sein Tourenprogramm als
  Angular-Widget des Drittanbieters Yolawo ein, statt es serverseitig zu
  rendern. Die Touren kommen daher nicht aus dem HTML, sondern aus einem
  einzelnen JSON-Endpunkt des Widgets (`api.yolawo.de/widgets/<id>/offers`),
  der alle Ressorts gebündelt liefert. Die tatsächliche Anmeldefrist-Regel
  ist über diese API nicht offengelegt; `status` liefert stattdessen eine
  grobe Einschätzung anhand der Restplätze.

Um die Sektionswebsites nicht mit paralleler Last zu treffen, entzerren alle
Requests sich selbst mit einem Mindestabstand (`_ThrottledSession` in
`dav_touren.py`) – das gilt auch beim manuellen Testen einzelner Fetch-
Funktionen, also keine Sektion wiederholt in kurzer Folge abfragen.

## Tourart, Gruppe und Schwierigkeit

Jede Tour trägt neben `category` (Tourart, z.B. "Wandern") ein eigenes
`group`-Feld für Zielgruppen/Untergruppen (z.B. "Familie", "Senioren",
"Alpin +") und ein `difficulty`-Feld für die jeweilige Schwierigkeitsskala
(z.B. "T2", "D", "Leicht") – Angaben, die die Sektionen uneinheitlich
benennen. `_normalize_category()` vereinheitlicht Synonyme sektionsübergreifend
(z.B. "Wanderung"/"Bergwanderung" → "Wandern", "JDAV"/"Rennmannschaft" →
"Fitness") und verschiebt Zielgruppen-Kategorien wie "Senioren" automatisch
vom `category`- ins `group`-Feld, statt sie als Tourart-Filter erscheinen zu
lassen. Neue Sektions-Synonyme gehören in `_CATEGORY_ALIASES`,
`_CATEGORY_DROP` bzw. `_GROUP_LIKE_CATEGORIES` am Anfang von `dav_touren.py`.

## Mehrtagestouren und Anmeldefrist

Jede Tour trägt zusätzlich `end_date` und `registration_deadline` (ISO-Daten,
leer wenn unbekannt):

- **Mehrtagestouren**: Friedrichshafen liefert `endDate` strukturiert im
  JSON-LD. Ravensburg, Überlingen und Lindau zeigen Datumsspannen, aus denen
  das Enddatum geparst wird.
- **Anmeldefrist**: Bei Ravensburg steht "Datum Ende Anmeldung:" strukturiert
  auf der Detailseite und ist zuverlässig. Bei Friedrichshafen wird die
  Beschreibung nach Mustern wie "Anmeldung bis 11.10., 18 Uhr" oder
  "Anmeldung und VB: 15. Oktober" durchsucht – das ist Freitext einzelner
  Tourenleiter*innen und daher Best-Effort, keine Garantie. Für Überlingen und
  Lindau wird aktuell keine Anmeldefrist erkannt.

## URL-Routing der Website

Die aktive Sektion steckt als letztes Pfadsegment in der URL (z.B.
`/friedrichshafen`, siehe `SECTION_SLUGS` in `site/template.html`). Umschalten
läuft über `history.pushState` ohne Reload; Vor-/Zurück über `popstate`.

Damit ein direkter Aufruf oder Reload einer solchen URL funktioniert, obwohl
GitHub Pages rein statisch ist, ist `docs/404.html` eine 1:1-Kopie von
`docs/index.html` – GitHub Pages liefert sie für jeden nicht existierenden
Pfad aus. `generate_site.py` erzeugt beide Dateien aus demselben Template;
das ist der einzige Grund, warum diese Route funktioniert, und darf beim
Ändern der Deploy-Logik nicht auseinanderlaufen.

## Deploy / CI

- `.github/workflows/deploy.yml` läuft nur noch wöchentlich per Cron und
  manuell per `workflow_dispatch` (optional mit `force`-Input) – **kein**
  Push-Trigger mehr, damit Entwicklungs-Commits nicht bei jedem Push einen
  vollen Re-Scrape aller Sektionen auslösen.
- `generate_site.py` überspringt den Datenabruf, wenn die bestehende
  `tours.json` (Zeitstempel `generated_at`) jünger als 2 Stunden ist;
  `--force` erzwingt einen Refresh unabhängig vom Alter.
- `fetch_all_tours()` bricht bewusst ab (ohne zu committen), wenn eine
  Sektion verdächtig wenige Touren liefert (`MIN_TOURS_PER_SECTION`) – das
  hat einmal einen Abruffehler abgefangen, der sonst unbemerkt eine Sektion
  aus der Live-Seite entfernt hätte.
- **Einmaliger manueller Setup-Schritt** (bereits erledigt, nur bei einem
  Fork/Neuaufsatz relevant): Unter *Settings → Pages → Build and deployment →
  Source* muss **"Deploy from a branch"** mit Branch `main` und Ordner
  `/docs` ausgewählt sein.

## Arbeiten an diesem Repo

- Commits folgen [Conventional Commits](https://www.conventionalcommits.org/)
  (`feat:`, `fix:`, `chore(...):`, `docs:`, ...).
- Nach Änderungen an `dav_touren.py`, `generate_site.py` oder
  `site/template.html`: `docs/` lokal neu generieren
  (`python3 generate_site.py --force`) und mitcommitten, damit Code und
  deployte Seite synchron bleiben – CI regeneriert `docs/` sonst erst beim
  nächsten planmäßigen oder manuellen Lauf.
