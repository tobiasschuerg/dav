# DAV Touren-Tool

Listet alle aktuellen Touren der Sektionen **DAV Friedrichshafen**,
**DAV Ravensburg** und **DAV Überlingen** auf, direkt von den jeweiligen
Sektionswebsites.

## Nutzung

```bash
pip install requests

python3 dav_touren.py                       # alle Sektionen, Textausgabe
python3 dav_touren.py --section fn          # nur Friedrichshafen
python3 dav_touren.py --section rv          # nur Ravensburg
python3 dav_touren.py --section ue          # nur Überlingen
python3 dav_touren.py --format csv --output touren.csv
python3 dav_touren.py --format json --output touren.json
```

Optionen:

- `--section {fn,rv,ue,all}` – nur eine Sektion abfragen (Standard: `all`)
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
  die jeweils nur ihre eigenen Touren als JSON-LD listen.
- **Ravensburg** (dav-ravensburg.info): Nutzt die TYPO3-Extension `we_tour`.
  Deren Kalender-Listenansicht wird über den internen AJAX-Endpunkt
  `/we_tour.ajax` abgefragt und die zurückgelieferte HTML-Tabelle geparst.
  Die Tourart ("Kategorie:") steht nur auf der Detailseite jeder Tour und
  wird von dort nachgeladen.
- **Überlingen** (dav-ueberlingen.de): WordPress mit eigenem `touren`-Post-Type
  (per REST API unter `/wp-json/wp/v2/touren` abrufbar, allerdings ohne
  strukturiertes Tourdatum). Stattdessen wird die paginierte `/touren`-
  Archivseite gescraped, die Datum, Titel und Tourart serverseitig in HTML
  rendert.

Alle drei Quellen sind undokumentierte, aber öffentlich zugängliche
Implementierungsdetails der jeweiligen Websites – bei Layout-Änderungen der
Seiten kann das Tool angepasst werden müssen.

### Mehrtagestouren und Anmeldefrist

Jede Tour trägt zusätzlich `end_date` und `registration_deadline` (ISO-Daten,
leer wenn unbekannt):

- **Mehrtagestouren**: Friedrichshafen liefert `endDate` strukturiert im
  JSON-LD. Ravensburg und Überlingen zeigen Datumsspannen ("13.09.2026 -
  20.09.2026" bzw. "27.08.–31.08.") in Liste bzw. Detailseite, aus denen das
  Enddatum geparst wird.
- **Anmeldefrist**: Bei Ravensburg steht "Datum Ende Anmeldung:" strukturiert
  auf der Detailseite und ist zuverlässig. Bei Friedrichshafen wird die
  Beschreibung nach Mustern wie "Anmeldung bis 11.10., 18 Uhr" oder
  "Anmeldung und VB: 15. Oktober" durchsucht – das ist Freitext einzelner
  Tourenleiter*innen und daher Best-Effort, keine Garantie. Für Überlingen
  wird aktuell keine Anmeldefrist erkannt (die Archivseite zeigt sie nicht,
  die Detailseiten werden für diese Sektion nicht abgerufen).

## Gehostete Website

`generate_site.py` schreibt die aktuellen Touren als hübsch formatiertes
`docs/tours.json` und legt daneben eine Kopie von `site/template.html` als
`docs/index.html` ab; die Seite lädt die Daten zur Laufzeit per `fetch()`.
Die Trennung hält Datenänderungen (fast täglich) und Layoutänderungen
(selten) in getrennten, gut lesbaren Diffs:

```bash
python3 generate_site.py --output-dir docs
```

`.github/workflows/deploy.yml` führt das jeden Montag früh aus (sowie bei
Änderungen an `dav_touren.py`/`generate_site.py`/`site/template.html` und
manuell per "Run workflow") und committet `docs/index.html` und
`docs/tours.json` direkt in dieses Repository, sofern sich etwas geändert
hat – kein separater Pages-Artefakt-Workflow, keine Deploy-Historie außerhalb
von Git.

**Einmaliger manueller Schritt:** Unter *Settings → Pages → Build and
deployment → Source* muss **"Deploy from a branch"** mit Branch `main` und
Ordner `/docs` ausgewählt sein. Die Seite ist danach unter
`https://<user>.github.io/<repo>/` erreichbar.
