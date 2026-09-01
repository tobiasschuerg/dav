# DAV Touren-Tool

Listet alle aktuellen Touren der Sektionen **DAV Friedrichshafen**,
**DAV Ravensburg**, **DAV Überlingen** und **DAV Lindau** auf, direkt von den
jeweiligen Sektionswebsites.

## Nutzung

```bash
pip install -r requirements.txt

python3 dav_touren.py                       # alle Sektionen, Textausgabe
python3 dav_touren.py --section fn          # nur Friedrichshafen
python3 dav_touren.py --section rv          # nur Ravensburg
python3 dav_touren.py --section ue          # nur Überlingen
python3 dav_touren.py --section li          # nur Lindau
python3 dav_touren.py --format csv --output touren.csv
python3 dav_touren.py --format json --output touren.json
```

Optionen:

- `--section {fn,rv,ue,li,all}` – nur eine Sektion abfragen (Standard: `all`)
- `--format {text,csv,json}` – Ausgabeformat (Standard: `text`)
- `--output DATEI` – Zieldatei für `csv`/`json`
- `--include-past` – auch bereits vergangene Termine der Friedrichshafener
  Saisonseite anzeigen (Standard: nur Termine ab heute)
- `--include-archive` – bei Ravensburg auch archivierte (vergangene) Touren
  einbeziehen

## Funktionsweise

- **Friedrichshafen** (dav-fn.de): Die Übersichtsseite
  `/programm_neu_so26/gesamt` ist eine Vue-Single-Page-App, bettet aber ein
  `schema.org`-JSON-LD `ItemList` mit allen Tour-Detail-URLs serverseitig ein.
  Jede Detailseite liefert ihrerseits vollständige JSON-LD-Daten (Titel,
  Datum, Beschreibung), die abgerufen werden. Die Tourart steht auf keiner
  dieser Seiten; sie wird über die fünf Bergsportart-Unterseiten
  (Wandern, Bergsteigen, Klettern, Skibergsteigen, Mountainbike) ermittelt,
  die jeweils nur ihre eigenen Touren als JSON-LD listen. Die Gruppenzugehörigkeit
  (Familiengruppe, Alpin+, Seniorengruppe, ...) wird analog über die
  "gemeinsam"-Unterseiten pro Gruppe ermittelt und getrennt von der Tourart
  im eigenen `group`-Feld geführt.
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
  einzelnen JSON-Endpunkt des Widgets
  (`api.yolawo.de/widgets/<id>/offers`), der alle Ressorts gebündelt liefert.

Alle vier Quellen sind undokumentierte, aber öffentlich zugängliche
Implementierungsdetails der jeweiligen Websites – bei Layout- oder
Systemwechseln der Seiten kann das Tool angepasst werden müssen. Um die
Sektionswebsites nicht mit paralleler Last zu treffen, entzerren alle
Requests sich selbst mit einem Mindestabstand (siehe `_ThrottledSession` in
`dav_touren.py`).

### Tourart, Gruppe und Schwierigkeit

Jede Tour trägt neben `category` (Tourart, z.B. "Wandern") ein eigenes
`group`-Feld für Zielgruppen/Untergruppen (z.B. "Familie", "Senioren",
"Alpin +") und ein `difficulty`-Feld für die jeweilige Schwierigkeitsskala
(z.B. "T2", "D", "Leicht") – Angaben, die die Sektionen uneinheitlich
benennen. `_normalize_category()` vereinheitlicht Synonyme sektionsübergreifend
(z.B. "Wanderung"/"Bergwanderung" → "Wandern", "JDAV"/"Rennmannschaft" →
"Fitness") und verschiebt Zielgruppen-Kategorien wie "Senioren" automatisch
vom `category`- ins `group`-Feld, statt sie als Tourart-Filter erscheinen zu
lassen.

### Mehrtagestouren und Anmeldefrist

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
  Lindau wird aktuell keine Anmeldefrist erkannt (bei Lindau ist die
  tatsächliche Anmeldefrist-Regel nicht über die Widget-API offengelegt;
  stattdessen liefert `status` dort eine grobe Einschätzung anhand der
  Restplätze).

## Gehostete Website

`generate_site.py` schreibt die aktuellen Touren als hübsch formatiertes
`docs/tours.json` und legt daneben eine Kopie von `site/template.html` als
`docs/index.html` ab; die Seite lädt die Daten zur Laufzeit per `fetch()`.
Die Trennung hält Datenänderungen (fast täglich) und Layoutänderungen
(selten) in getrennten, gut lesbaren Diffs:

```bash
python3 generate_site.py --output-dir docs
```

Der Abruf wird übersprungen, wenn die bestehende `tours.json` jünger als
2 Stunden ist (Zeitstempel `generated_at`); `--force` erzwingt einen Refresh
unabhängig vom Alter.

`.github/workflows/deploy.yml` führt das jeden Montag früh sowie manuell per
"Run workflow" (optional mit `force`-Input) aus und committet
`docs/index.html` und `docs/tours.json` direkt in dieses Repository, sofern
sich etwas geändert hat – kein separater Pages-Artefakt-Workflow, keine
Deploy-Historie außerhalb von Git. Der Lauf bricht bewusst ab (ohne zu
committen), wenn eine Sektion verdächtig wenige Touren liefert, statt
unvollständige Daten zu veröffentlichen.

**Einmaliger manueller Schritt:** Unter *Settings → Pages → Build and
deployment → Source* muss **"Deploy from a branch"** mit Branch `main` und
Ordner `/docs` ausgewählt sein. Die Seite ist danach unter
`https://<user>.github.io/<repo>/` erreichbar.
