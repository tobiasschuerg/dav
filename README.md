# DAV Touren-Tool

Listet alle aktuellen Touren der Sektionen **DAV Friedrichshafen**,
**DAV Ravensburg**, **DAV Überlingen** und **DAV Lindau** auf, direkt von den
jeweiligen Sektionswebsites.

Live als **DAV Touren-Finder Bodensee**: https://tobiasschuerg.github.io/dav/
(siehe [Gehostete Website](#gehostete-website)).

Technische Details zu den einzelnen Datenquellen, der Tourart/Gruppe/
Schwierigkeit-Normalisierung und dem Deploy-Prozess stehen in
[AGENTS.md](AGENTS.md).

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

## Gehostete Website

`generate_site.py` baut aus den aktuellen Touren und `site/template.html`
die live unter https://tobiasschuerg.github.io/dav/ laufende Seite in `docs/`.
Ein wöchentlicher GitHub-Actions-Lauf hält sie aktuell. Details zu Aufbau und
Deploy-Mechanik stehen in [AGENTS.md](AGENTS.md).
